"""
## src/core/effects/move.py

Move Effect System Implementation using the Reworked BaseEffect

Key Features:
- Integrates with BaseEffect for state and duration management.
- Handles move-specific phases (Casting, Active, Cooldown).
- Processes attacks, saves, and bonuses.
- Supports instant, duration, and cooldown moves.

IMPLEMENTATION MANDATES:
- Relies on BaseEffect for core state transitions (ACTIVE -> EXPIRING -> EXPIRED -> REMOVED).
- Manages internal MovePhase transitions (CASTING -> ACTIVE -> COOLDOWN -> DONE).
- Uses BaseEffect's duration logic for consistency.
- Queues async operations (like attacks) for manager processing.
"""

from typing import Optional, List, Dict, Any, Tuple, Set, Union
from enum import Enum, auto
import logging
import inspect
import time
import random

# Updated imports
from core.effects.base import BaseEffect, EffectCategory, EffectProcessTimingInfo, EffectState
from core.effects.rollmod import RollModifierType, RollModifierEffect
from core.effects.condition import ConditionType # Assuming ConditionType is defined elsewhere or needs update
from utils.advanced_dice.calculator import DiceCalculator
from core.character import StatType, Character # Import Character for type hinting

logger = logging.getLogger(__name__)

# Internal phases for MoveEffect progression
class MovePhase(Enum):
    INSTANT = "instant"    # Move resolves immediately
    CASTING = "casting"    # Move is being cast
    ACTIVE = "active"      # Move's primary effect is active
    COOLDOWN = "cooldown"  # Move is on cooldown after use
    DONE = "done"          # All phases complete, ready for BaseEffect expiry

class RollTiming(Enum):
    """When to process attack rolls relative to MovePhases."""
    INSTANT = "instant"     # Roll immediately on apply
    ACTIVE = "active"       # Roll when ACTIVE phase begins
    PER_TURN = "per_turn"   # Roll each turn during ACTIVE phase

# --- Helper Classes (SavingThrowProcessor, BonusOnHit, CombatProcessor remain largely the same) ---
# Note: These could potentially be moved to a separate utility file if used elsewhere.

class SavingThrowProcessor:
    """Handles saving throw mechanics for effects."""
    def __init__(self, debug_mode=True):
        self.debug_mode = debug_mode
        self.targets_saved: Set[str] = set()
        self.last_save_round = None

    def debug_print(self, message):
        if self.debug_mode:
            print(f"[SavingThrowProcessor] {message}")

    async def process_save(self, source: Character, targets: List[Character], save_type: str,
                         save_dc: str, effect_name: str, half_on_save: bool = False,
                         damage: Optional[str] = None) -> List[str]:
        if not targets or not save_type: return []
        self.last_save_round = getattr(source, 'round_number', None)
        from utils.dice import DiceRoller # Local import to avoid circular dependency issues
        self.debug_print(f"Processing saves for {len(targets)} targets")
        messages = []
        dc_value = 10
        if save_dc:
            try:
                parts = save_dc.lower().replace(" ", "").split("+")
                dc_value = 0
                for part in parts:
                    if part.isdigit(): dc_value += int(part)
                    elif part == "prof": dc_value += source.base_proficiency
                    elif part in ["str", "strength"]: dc_value += source.stats.get_modifier(StatType.STRENGTH)
                    elif part in ["dex", "dexterity"]: dc_value += source.stats.get_modifier(StatType.DEXTERITY)
                    elif part in ["con", "constitution"]: dc_value += source.stats.get_modifier(StatType.CONSTITUTION)
                    elif part in ["int", "intelligence"]: dc_value += source.stats.get_modifier(StatType.INTELLIGENCE)
                    elif part in ["wis", "wisdom"]: dc_value += source.stats.get_modifier(StatType.WISDOM)
                    elif part in ["cha", "charisma"]: dc_value += source.stats.get_modifier(StatType.CHARISMA)
            except Exception as e: self.debug_print(f"Error parsing save DC: {e}")
        self.debug_print(f"Calculated DC: {dc_value}")
        main_message = f"{save_type.upper()} Save DC {dc_value} | {effect_name}"
        target_results = []
        for target in targets:
            save_mod = 0
            if save_type.lower() in ["str", "strength"]: save_mod = target.saves.get(StatType.STRENGTH, 0)
            elif save_type.lower() in ["dex", "dexterity"]: save_mod = target.saves.get(StatType.DEXTERITY, 0)
            elif save_type.lower() in ["con", "constitution"]: save_mod = target.saves.get(StatType.CONSTITUTION, 0)
            elif save_type.lower() in ["int", "intelligence"]: save_mod = target.saves.get(StatType.INTELLIGENCE, 0)
            elif save_type.lower() in ["wis", "wisdom"]: save_mod = target.saves.get(StatType.WISDOM, 0)
            elif save_type.lower() in ["cha", "charisma"]: save_mod = target.saves.get(StatType.CHARISMA, 0)
            roll_result = random.randint(1, 20)
            total = roll_result + save_mod
            success = total >= dc_value
            if success: self.targets_saved.add(target.name)
            result_text = f"{target.name}: {roll_result}+{save_mod}={total} | {'✅' if success else '❌'}"
            if damage:
                damage_dealt = 0
                if not success:
                    damage_roll, _ = DiceRoller.roll_dice(damage, target)
                    damage_dealt = damage_roll
                elif half_on_save:
                    damage_roll, _ = DiceRoller.roll_dice(damage, target)
                    damage_dealt = damage_roll // 2
                    result_text += f" | Half dmg: {damage_dealt}"
                if damage_dealt > 0:
                    if target.resources.current_temp_hp > 0:
                        absorbed = min(target.resources.current_temp_hp, damage_dealt)
                        target.resources.current_temp_hp -= absorbed
                        damage_dealt -= absorbed
                        if absorbed > 0: result_text += f" | {absorbed} absorbed"
                    if damage_dealt > 0:
                        old_hp = target.resources.current_hp
                        target.resources.current_hp = max(0, old_hp - damage_dealt)
                        if not success: result_text += f" | {damage_dealt} damage"
            target_results.append(result_text)
        if target_results:
            formatted = f"🎯 `{main_message}` 🎯\n" + "\n".join(f"• `{result}`" for result in target_results)
            messages.append(formatted)
        return messages

class BonusOnHit:
    """Handles applying and tracking bonuses when a move hits."""
    def __init__(self, mp_bonus=0, hp_bonus=0, star_bonus=0, custom_note: Optional[str] = None, debug_mode: bool = True):
        self.mp_bonus = mp_bonus
        self.hp_bonus = hp_bonus
        self.star_bonus = star_bonus
        self.custom_note = custom_note
        self.debug_mode = debug_mode
        self.hit_count = 0

    def debug_print(self, message):
        if self.debug_mode: print(f"[BonusOnHit] {message}")

    def has_bonuses(self) -> bool:
        return bool(self.mp_bonus or self.hp_bonus or self.star_bonus or self.custom_note)

    def register_hit(self):
        self.hit_count += 1
        self.debug_print(f"Registered hit. Total hits: {self.hit_count}")

    def reset(self): self.hit_count = 0

    def apply_bonuses(self, character: Character) -> Tuple[Dict[str, int], str]:
        if self.hit_count == 0 or not self.has_bonuses(): return {}, ""
        from utils.dice import DiceRoller # Local import
        self.debug_print(f"Applying bonuses for {self.hit_count} hits")
        totals: Dict[str, int] = {}
        message_parts = []
        def _roll_bonus(bonus_val, char):
            # Check if bonus_val is a valid type (int or str) before processing
            if not isinstance(bonus_val, (int, str)):
                 self.debug_print(f"Invalid bonus value type: {type(bonus_val)}. Skipping.")
                 return 0
            if isinstance(bonus_val, str) and ('d' in bonus_val.lower() or any(stat in bonus_val.lower() for stat in ['str', 'dex', 'con', 'int', 'wis', 'cha'])):
                total = 0
                for _ in range(self.hit_count):
                    try:
                        roll, _ = DiceRoller.roll_dice(bonus_val, char)
                        total += roll
                    except Exception as e:
                        self.debug_print(f"Error rolling bonus dice '{bonus_val}': {e}")
                return total
            try:
                # Attempt to convert to int, handle potential errors
                return int(bonus_val) * self.hit_count
            except (ValueError, TypeError):
                self.debug_print(f"Could not convert bonus value '{bonus_val}' to int. Skipping.")
                return 0


        if self.mp_bonus:
            total_mp = _roll_bonus(self.mp_bonus, character)
            if total_mp != 0: # Only apply if there's a change
                totals['mp'] = total_mp
                old_mp = character.resources.current_mp
                character.resources.current_mp = min(character.resources.max_mp, old_mp + total_mp)
                message_parts.append(f"💙 MP: +{total_mp}")
        if self.hp_bonus:
            total_hp = _roll_bonus(self.hp_bonus, character)
            if total_hp != 0:
                totals['hp'] = total_hp
                old_hp = character.resources.current_hp
                character.resources.current_hp = min(character.resources.max_hp, old_hp + total_hp)
                message_parts.append(f"❤️ HP: +{total_hp}")
        if self.star_bonus:
            total_stars = _roll_bonus(self.star_bonus, character)
            if total_stars != 0:
                totals['stars'] = total_stars
                if hasattr(character, 'action_stars'):
                    if hasattr(character.action_stars, 'add_bonus_stars'): character.action_stars.add_bonus_stars(total_stars)
                    elif hasattr(character.action_stars, 'add_stars'): character.action_stars.add_stars(total_stars)
                message_parts.append(f"⭐ +{total_stars}")
        if self.custom_note:
            message_parts.append(f"📝 {self.custom_note} ({self.hit_count}x)")
            totals['custom'] = self.hit_count
        formatted = f"{self.hit_count} Hits! Bonuses: | {' | '.join(message_parts)}" if message_parts else f"{self.hit_count} Hits!"
        return totals, formatted

    @classmethod
    def from_dict(cls, data: Dict, debug_mode: bool = True) -> 'BonusOnHit': # Added debug_mode propagation
        if not data or not isinstance(data, dict): return cls(debug_mode=debug_mode)
        return cls(mp_bonus=data.get('mp', 0), hp_bonus=data.get('hp', 0),
                   star_bonus=data.get('stars', 0), custom_note=data.get('note'), debug_mode=debug_mode)

    def to_dict(self) -> Dict:
        data = {}
        if self.mp_bonus: data['mp'] = self.mp_bonus
        if self.hp_bonus: data['hp'] = self.hp_bonus
        if self.star_bonus: data['stars'] = self.star_bonus
        if self.custom_note: data['note'] = self.custom_note
        return data

class CombatProcessor:
    """Handles attack rolls and damage calculations."""
    def __init__(self, debug_mode=True):
        self.targets_hit: Set[str] = set()
        self.attacks_this_turn = 0
        self.aoe_mode = 'single'
        self.debug_mode = debug_mode

    def debug_print(self, message):
        if self.debug_mode: print(f"[CombatProcessor] {message}")

    async def process_attack(self, source: Character, targets: List[Character], attack_roll: Optional[str],
                           damage: Optional[str], crit_range: int, reason: str,
                           bonus_on_hit: Optional[BonusOnHit] = None) -> List[str]:
        if not attack_roll: return []
        self.attacks_this_turn += 1
        self.debug_print(f"Processing attack {self.attacks_this_turn}")
        messages = []
        from utils.advanced_dice.attack_calculator import AttackCalculator, AttackParameters # Local import

        # Ensure hit_bonus is a BonusOnHit instance
        hit_bonus = bonus_on_hit if isinstance(bonus_on_hit, BonusOnHit) else BonusOnHit.from_dict(bonus_on_hit or {}, debug_mode=self.debug_mode)
        hit_bonus.reset()
        self.debug_print(f"Using hit bonus tracker: {hit_bonus.__dict__}")

        params = AttackParameters(
            roll_expression=attack_roll, character=source, targets=targets,
            damage_str=damage, crit_range=crit_range, aoe_mode=self.aoe_mode, reason=reason
        )
        if not targets: params.targets = None

        message, hit_data = await AttackCalculator.process_attack(params)
        messages.append(message)
        self.debug_print(f"Got hit data: {hit_data}")

        if isinstance(hit_data, dict) and hit_data:
            hit_count = 0
            for target_name, target_hit_data in hit_data.items():
                if target_hit_data.get('hit', False):
                    self.debug_print(f"Target hit: {target_name}")
                    self.targets_hit.add(target_name)
                    hit_bonus.register_hit()
                    hit_count += 1
            self.debug_print(f"Total hits: {hit_count}, Has bonuses: {hit_bonus.has_bonuses()}")
            if hit_count > 0 and hit_bonus.has_bonuses():
                self.debug_print(f"Applying bonuses for {hit_count} hits")
                _, bonus_message = hit_bonus.apply_bonuses(source)
                if bonus_message: messages.append(f"• `{bonus_message}`")
        return messages

# --- MoveEffect Class ---

class MoveEffect(BaseEffect):
    """
    Handles move execution, integrating with the reworked BaseEffect.
    Manages internal phases (Casting, Active, Cooldown) while relying on
    BaseEffect for overall state and duration tracking.
    """
    def __init__(
        self,
        name: str,
        description: str,
        star_cost: int = 0,
        mp_cost: Union[int, str] = 0,
        hp_cost: Union[int, str] = 0,
        cast_time: Optional[int] = None,
        active_duration: Optional[int] = None, # Duration of the ACTIVE phase
        cooldown: Optional[int] = None,
        cast_description: Optional[str] = None,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        crit_range: int = 20,
        conditions: Optional[List[ConditionType]] = None,
        roll_timing: str = "active",
        uses: Optional[int] = None,
        targets: Optional[List[Character]] = None,
        bonus_on_hit: Optional[Dict] = None,
        aoe_mode: str = 'single',
        roll_modifier: Optional[Dict[str, Any]] = None,
        debug_mode: bool = True
    ):
        # Initialize BaseEffect first
        super().__init__(
            name=name,
            duration=active_duration, # Base tracks the *active* part
            permanent=False,
            category=EffectCategory.CUSTOM,
            description=description,
            process_timing="both", # Moves need start and end
            emoji="⚡",
            debug_mode=debug_mode
        )

        self.debug_id = f"MoveEffect-{int(time.time() * 1000) % 10000}"
        self.debug_print(f"Initializing {name}")

        # Store move phase durations
        self.cast_time = cast_time if cast_time and cast_time > 0 else None
        self.active_duration = active_duration if active_duration and active_duration > 0 else None
        self.cooldown = cooldown if cooldown and cooldown > 0 else None

        # Determine initial internal phase and turns left
        if self.cast_time:
            self.current_phase = MovePhase.CASTING
            self.phase_turns_left = self.cast_time
        elif self.active_duration:
            self.current_phase = MovePhase.ACTIVE
            self.phase_turns_left = self.active_duration
        elif self.cooldown:
            self.current_phase = MovePhase.COOLDOWN
            self.phase_turns_left = self.cooldown
        else:
            self.current_phase = MovePhase.INSTANT
            self.phase_turns_left = 0

        # Processors
        self.combat = CombatProcessor(self.debug_mode)
        self.saves = SavingThrowProcessor(self.debug_mode)

        # Costs and Usage
        self.star_cost = star_cost
        self.mp_cost = mp_cost
        self.hp_cost = hp_cost
        self.uses = uses
        self.uses_remaining = uses if uses is not None else None

        # Combat Details
        self.attack_roll = attack_roll
        self.damage = damage
        self.crit_range = crit_range
        self.conditions = conditions or []
        self.determine_roll_timing(roll_timing)
        self.cast_description = cast_description
        self.targets = targets or []
        self.bonus_on_hit = BonusOnHit.from_dict(bonus_on_hit or {}, debug_mode=self.debug_mode)
        self.combat.aoe_mode = aoe_mode

        # Roll Modifier
        self.roll_modifier_data = roll_modifier
        self.roll_modifier_effect: Optional[RollModifierEffect] = None
        if roll_modifier:
            self._create_roll_modifier_effect(roll_modifier, name, self.active_duration)

        # Internal Tracking
        self._internal_cache = {}
        self.last_roll_round = None
        self.was_just_activated = False # Track transition CASTING -> ACTIVE

        self.debug_print(f"Initialized. Phase: {self.current_phase.value}, PhaseTurnsLeft: {self.phase_turns_left}, BaseState: {self.state.value}")

    def _create_roll_modifier_effect(self, data: Dict, move_name: str, move_duration: Optional[int]):
         """Helper to create RollModifierEffect from data."""
         try:
             mod_type_str = data.get("type", "bonus").lower()
             mod_value = data.get("value", 1)
             next_roll_only = data.get("next_roll", False)
             mod_name = data.get("name", f"{move_name} Roll Mod")
             modifier_type = RollModifierType.BONUS
             for t in RollModifierType:
                 if t.value == mod_type_str: modifier_type = t; break
             self.roll_modifier_effect = RollModifierEffect(
                 name=mod_name, modifier_type=modifier_type, value=mod_value,
                 next_roll_only=next_roll_only,
                 duration=None if next_roll_only else move_duration,
                 permanent=False, description=f"From {move_name}"
             )
             self.debug(f"Created roll modifier effect: {mod_name}")
         except Exception as e:
             self.debug(f"Error creating roll modifier effect: {e}")
             self.roll_modifier_effect = None

    def debug_print(self, message):
        # Overriding base debug to include phase info
        if self.debug_mode:
            log_msg = f"[{self.debug_id}|P:{self.current_phase.value}|B:{self.state.value}] {message}"
            self.debug_log.append(log_msg)
            # print(log_msg) # Optional immediate print

    def determine_roll_timing(self, roll_timing_str):
        """Determine roll timing, defaulting INSTANT for attacks with no cast time."""
        try: self.roll_timing = RollTiming(roll_timing_str)
        except: self.roll_timing = RollTiming.ACTIVE
        # Adjusted logic: INSTANT only if no cast time AND no active duration
        if self.attack_roll and not self.cast_time and not self.active_duration:
            self.roll_timing = RollTiming.INSTANT
            self.debug_print("Auto-detected INSTANT roll timing.")
        elif self.attack_roll and not self.cast_time and self.roll_timing == RollTiming.ACTIVE:
             # If no cast time but has duration, default ACTIVE is fine, but log it
             self.debug_print(f"Roll timing set to ACTIVE (no cast time, has duration).")


    def get_emoji(self) -> str:
        """Get emoji based on the current internal move phase."""
        return {
            MovePhase.INSTANT: "⚡", MovePhase.CASTING: "⏳",
            MovePhase.ACTIVE: "✨", MovePhase.COOLDOWN: "⏱️",
            MovePhase.DONE: "✅"
        }.get(self.current_phase, "❓")

    def get_phase_remaining_turns(self) -> int:
        """Get turns remaining in the current internal phase."""
        return max(0, self.phase_turns_left)

    # --- Resource Handling ---
    def apply_costs(self, character: Character) -> List[str]:
        """Apply resource costs (MP, HP, Stars) and return messages."""
        messages = []
        from utils.dice import DiceRoller # Local import
        def _handle_cost(cost_attr, resource_attr, max_attr, label, emoji_cost, emoji_gain):
            cost_val = getattr(self, cost_attr)
            if not cost_val: return
            is_dice = isinstance(cost_val, str) and ('d' in cost_val.lower() or any(stat in cost_val.lower() for stat in ['str', 'dex', 'con', 'int', 'wis', 'cha']))
            actual_cost = 0
            try:
                actual_cost = int(cost_val) # Try converting first
            except (ValueError, TypeError):
                if not is_dice: # If not dice and not int, it's an error
                    self.debug_print(f"Invalid cost format for {cost_attr}: {cost_val}")
                    return
            roll_msg = None
            if is_dice:
                roll_res, roll_desc = DiceRoller.roll_dice(cost_val, character)
                actual_cost = roll_res
                roll_msg = f"Rolled {label} cost: {roll_desc}"
                self.debug_print(f"Rolled {label} cost: {actual_cost} from {cost_val}")

            if actual_cost > 0:
                setattr(character.resources, resource_attr, max(0, getattr(character.resources, resource_attr) - actual_cost))
                messages.append(f"{emoji_cost} Uses {actual_cost} {label}")
            elif actual_cost < 0: # Negative cost means gain
                setattr(character.resources, resource_attr, min(getattr(character.resources, max_attr), getattr(character.resources, resource_attr) - actual_cost))
                messages.append(f"{emoji_gain} Gains {abs(actual_cost)} {label}")
            if roll_msg: messages.append(f"`{roll_msg}`") # Add backticks

        _handle_cost('mp_cost', 'current_mp', 'max_mp', 'MP', '💙', '💙')
        _handle_cost('hp_cost', 'current_hp', 'max_hp', 'HP', '❤️', '❤️')

        if self.star_cost and self.star_cost > 0:
            if hasattr(character, 'action_stars') and hasattr(character.action_stars, 'use_stars'):
                try:
                    character.action_stars.use_stars(self.star_cost, self.name)
                    self.debug_print(f"Applied star cost: {self.star_cost}")
                    messages.append(f"⭐ Uses {self.star_cost} Stars")
                except ValueError as e: # Catch insufficient stars error
                     self.debug_print(f"Could not apply star cost: {e}")
                     messages.append(f"⚠️ Insufficient Stars ({e})")
                     # Optionally raise an error or handle insufficient resources
            else:
                 self.debug_print("Character lacks action_stars system.")
        return messages

    def can_use(self, round_number: Optional[int] = None) -> tuple[bool, Optional[str]]:
        """Check if the move can be used based on cooldown and uses."""
        if self.current_phase == MovePhase.COOLDOWN:
            return False, f"On cooldown ({self.phase_turns_left} turns left)"
        if self.uses is not None and self.uses_remaining is not None and self.uses_remaining <= 0:
            return False, f"No uses remaining (0/{self.uses})"
        return True, None

    # --- Core Logic ---
    def _advance_phase(self) -> Optional[str]:
        """Advances the internal move phase and returns a transition message."""
        old_phase = self.current_phase
        transition_message = None
        self.was_just_activated = False # Reset flag

        if self.current_phase == MovePhase.CASTING:
            if self.active_duration:
                self.current_phase = MovePhase.ACTIVE
                self.phase_turns_left = self.active_duration
                transition_message = f"{self.name} activates!"
                self.was_just_activated = True
            elif self.cooldown:
                self.current_phase = MovePhase.COOLDOWN
                self.phase_turns_left = self.cooldown
                transition_message = f"{self.name} finishes casting and enters cooldown."
            else:
                self.current_phase = MovePhase.DONE
                transition_message = f"{self.name} finishes casting."
        elif self.current_phase == MovePhase.ACTIVE:
            # BaseEffect handles ACTIVE -> EXPIRING -> EXPIRED
            # We transition to COOLDOWN or DONE only when BaseEffect state becomes EXPIRED
            # This logic is now handled in on_turn_end based on BaseEffect state
            pass # Let BaseEffect handle active duration expiry
        elif self.current_phase == MovePhase.COOLDOWN:
            self.current_phase = MovePhase.DONE
            transition_message = f"{self.name} cooldown ended."

        if old_phase != self.current_phase:
            self.debug_print(f"Phase transition: {old_phase.value} -> {self.current_phase.value}")
            return transition_message
        return None

    # --- Lifecycle Methods (Overriding BaseEffect) ---

    def on_apply(self, character: Character, round_number: int) -> str:
        """
        Handles the initial application of the move effect.
        Applies costs, initializes base timing, handles instant attacks,
        and formats the application message.
        """
        self.debug_print(f"on_apply started for {character.name} on round {round_number}")

        # 1. Apply Costs
        cost_messages = self.apply_costs(character)

        # 2. Call BaseEffect's on_apply
        # This initializes timing, adjusts internal duration, sets state to ACTIVE
        base_apply_message = super().on_apply(character, round_number)
        self.debug(f"BaseEffect on_apply completed. Base state: {self.state.value}")

        # 3. Prepare message components
        details = []
        timing_info = []

        # Build cost display string
        costs_display = []
        if self.mp_cost: costs_display.append(f"💙 MP: {self.mp_cost}")
        if self.hp_cost: costs_display.append(f"❤️ HP: {self.hp_cost}")
        if self.star_cost: costs_display.append(f"⭐ {self.star_cost}")

        # Build resource status display string
        resource_updates = [
            f"MP: {character.resources.current_mp}/{character.resources.max_mp}",
            f"HP: {character.resources.current_hp}/{character.resources.max_hp}"
        ]
        if hasattr(character, 'action_stars'):
             resource_updates.append(f"Stars: {character.action_stars.current_stars}/{character.action_stars.max_stars}")

        # Build timing display string based on internal phases
        if self.cast_time: timing_info.append(f"🔄 {self.cast_time}T Cast")
        if self.active_duration: timing_info.append(f"⏳ {self.active_duration}T Active")
        if self.cooldown: timing_info.append(f"⌛ {self.cooldown}T Cooldown")

        # Format target info only if not an instant attack
        if self.targets and self.roll_timing != RollTiming.INSTANT:
            target_names = ", ".join(t.name for t in self.targets)
            details.append(f"Target{'s' if len(self.targets) > 1 else ''}: {target_names}")

        # 4. Handle Instant Attack Rolls (Queue Async Task)
        if self.attack_roll and self.roll_timing == RollTiming.INSTANT:
            self.debug_print("Queueing instant attack roll processing")
            self._internal_cache['attack_coroutine'] = self.combat.process_attack(
                 source=character, targets=self.targets, attack_roll=self.attack_roll,
                 damage=self.damage, crit_range=self.crit_range, reason=self.name,
                 bonus_on_hit=self.bonus_on_hit
            )

        # 5. Apply Roll Modifier (if any)
        if self.roll_modifier_effect:
            self.debug_print(f"Applying roll modifier effect: {self.roll_modifier_effect.name}")
            if self.roll_modifier_effect not in character.effects:
                 # Initialize timing for the modifier effect itself
                 mod_apply_msg = self.roll_modifier_effect.on_apply(character, round_number)
                 character.effects.append(self.roll_modifier_effect)
                 details.append(f"Applied Roll Mod: {mod_apply_msg}")

        # 6. Format the Final Message
        if self.cast_description:
             main_action = f"{character.name} {self.cast_description} {self.name}"
        elif self.current_phase == MovePhase.INSTANT:
             main_action = f"{character.name} uses {self.name}"
        elif self.current_phase == MovePhase.CASTING:
             main_action = f"{character.name} begins casting {self.name}"
        else: # ACTIVE or COOLDOWN start
             main_action = f"{character.name} uses {self.name}"

        info_parts = []
        if costs_display: info_parts.append(" | ".join(costs_display))
        if timing_info: info_parts.append(" | ".join(timing_info))
        if resource_updates: info_parts.append(" | ".join(resource_updates))

        main_message_line = main_action
        if info_parts:
             main_message_line += f" | {' | '.join(info_parts)}"

        formatted_message = self.format_effect_message(main_message_line, details=details, emoji=self.get_emoji())

        # 7. Handle Instant Move Completion
        # If it's instant and has no cooldown, it's done immediately.
        if self.current_phase == MovePhase.INSTANT and not self.cooldown:
             self.debug("Instant move without cooldown, marking DONE and EXPIRED.")
             self.current_phase = MovePhase.DONE
             self.state = EffectState.EXPIRED # Mark base state for removal

        self.debug(f"on_apply complete. Final BaseState: {self.state.value}, Phase: {self.current_phase.value}")
        return formatted_message

    # Note: _check_if_during_own_turn is removed as base class handles it.
    # Note: initialize_timing is removed as base class handles it.

    async def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Handles start-of-turn logic for the move:
        - Displays casting/cooldown status.
        - Processes attacks if timing is ACTIVE (on first active turn) or PER_TURN.
        """
        # Base class checks if it's the correct turn and state (ACTIVE)
        base_messages = super().on_turn_start(character, round_number, turn_name)
        if self.state != EffectState.ACTIVE: # Only proceed if base effect is active
             return base_messages # Return empty list if not active/correct turn

        messages = []
        phase_just_changed = self.was_just_activated # Did we just transition CASTING -> ACTIVE?
        self.was_just_activated = False # Reset flag

        # 1. Display Phase Status
        if self.current_phase == MovePhase.CASTING:
            messages.append(self.format_effect_message(
                f"Casting {self.name}",
                details=[f"{self.phase_turns_left} turn{'s' if self.phase_turns_left != 1 else ''} left"],
                emoji=self.get_emoji()
            ))
        elif self.current_phase == MovePhase.COOLDOWN:
             messages.append(self.format_effect_message(
                f"{self.name} on Cooldown",
                details=[f"{self.phase_turns_left} turn{'s' if self.phase_turns_left != 1 else ''} left"],
                emoji=self.get_emoji()
            ))

        # 2. Process Attack Rolls based on Timing
        should_roll = False
        if self.attack_roll:
            if self.roll_timing == RollTiming.ACTIVE and phase_just_changed:
                should_roll = True
                self.debug_print("Processing attack roll (Timing: ACTIVE, Just Activated)")
            elif self.roll_timing == RollTiming.PER_TURN and self.current_phase == MovePhase.ACTIVE:
                should_roll = True
                self.debug_print("Processing attack roll (Timing: PER_TURN)")

        if should_roll:
            # Queue the async attack processing
            self.last_roll_round = round_number # Track roll round
            self._internal_cache['attack_coroutine'] = self.combat.process_attack(
                 source=character, targets=self.targets, attack_roll=self.attack_roll,
                 damage=self.damage, crit_range=self.crit_range, reason=self.name,
                 bonus_on_hit=self.bonus_on_hit
            )
            # Attack messages will be retrieved by the manager later

        # 3. Display Active Status (if not casting/cooldown and no attack happened)
        # BaseEffect.on_turn_end handles duration display, so we only need specific active info here.
        if self.current_phase == MovePhase.ACTIVE and not should_roll:
             # Get remaining duration from BaseEffect's calculation
             _, _, remaining_display = self.calculate_duration(round_number, turn_name)
             details = []
             if self.description: details.append(self.description)
             if remaining_display is not None:
                  details.append(f"{remaining_display} turn{'s' if remaining_display != 1 else ''} remaining")

             messages.append(self.format_effect_message(
                 f"{self.name} active", details=details, emoji=self.get_emoji()
             ))

        return messages

    async def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Handles end-of-turn logic:
        - Decrements internal phase timer.
        - Advances internal move phase (CASTING -> ACTIVE -> COOLDOWN -> DONE).
        - Calls BaseEffect.on_turn_end() to handle ACTIVE duration expiry.
        """
        # Base class checks if it's the correct turn
        base_messages = super().on_turn_end(character, round_number, turn_name)
        # BaseEffect's on_turn_end handles the ACTIVE->EXPIRING->EXPIRED transition
        # and generates duration/expiry messages based on self.active_duration.

        messages = base_messages # Start with messages from base (like duration remaining)

        # Only process phase logic if the base effect is still active or expiring
        if self.state not in [EffectState.ACTIVE, EffectState.EXPIRING]:
            self.debug_print(f"Skipping phase logic as BaseEffect state is {self.state.value}")
            return messages

        # Decrement internal phase timer if not INSTANT or DONE
        if self.current_phase not in [MovePhase.INSTANT, MovePhase.DONE]:
            self.phase_turns_left -= 1
            self.debug_print(f"Decremented phase timer. Phase: {self.current_phase.value}, Turns Left: {self.phase_turns_left}")

            # Check for internal phase transition
            if self.phase_turns_left <= 0:
                transition_msg = self._advance_phase()
                if transition_msg:
                    # Format the internal phase transition message
                    formatted_transition_msg = self.format_effect_message(transition_msg, emoji=self.get_emoji())
                    if formatted_transition_msg not in messages: # Avoid duplicates if base also expired
                         messages.append(formatted_transition_msg)

                    # If the move is now DONE (all phases complete), mark BaseEffect as EXPIRED
                    if self.current_phase == MovePhase.DONE:
                         self.debug("Move phase DONE. Marking BaseEffect as EXPIRED.")
                         self.state = EffectState.EXPIRED
                         # Add feedback for the final state
                         final_msg = self.format_effect_message(f"{self.name} has concluded.", emoji=self.get_emoji())
                         if final_msg not in messages: messages.append(final_msg)
                         self._add_feedback(character, final_msg, round_number, is_expiry=True)


        # If the BaseEffect expired, ensure the internal phase is also DONE
        if self.state == EffectState.EXPIRED and self.current_phase != MovePhase.DONE:
             self.debug(f"BaseEffect expired, forcing MovePhase to DONE (was {self.current_phase.value})")
             self.current_phase = MovePhase.DONE
             # The expiry message is already handled by BaseEffect.on_turn_end

        return messages

    def on_expire(self, character) -> str:
        """Handles final cleanup when the effect is removed."""
        self.debug_print("on_expire called.")
        # Call base expire first to ensure state is set to REMOVED
        base_msg = super().on_expire(character)

        # Add any move-specific cleanup here if needed (e.g., removing applied conditions)
        self.targets = [] # Clear targets

        # Return base message (usually empty) or a custom cleanup message
        return base_msg

    # --- Serialization ---
    def to_dict(self) -> dict:
        """Convert move effect to dictionary for storage."""
        data = super().to_dict() # Get base effect data (includes state, timing)
        data.update({
            "move_phase": self.current_phase.value,
            "phase_turns_left": self.phase_turns_left,
            "star_cost": self.star_cost,
            "mp_cost": self.mp_cost,
            "hp_cost": self.hp_cost,
            "cast_time": self.cast_time,
            "active_duration": self.active_duration, # Save active duration
            "cooldown": self.cooldown,
            "cast_description": self.cast_description,
            "uses": self.uses,
            "uses_remaining": self.uses_remaining,
            "attack_roll": self.attack_roll,
            "damage": self.damage,
            "crit_range": self.crit_range,
            "conditions": [c.value if hasattr(c, 'value') else str(c) for c in self.conditions],
            "roll_timing": self.roll_timing.value,
            "aoe_mode": self.combat.aoe_mode,
            "bonus_on_hit": self.bonus_on_hit.to_dict(),
            "roll_modifier_data": self.roll_modifier_data, # Save raw modifier data
            # Removed state_machine, marked_for_removal, transition_count, displayed_duration
            # BaseEffect handles state and duration now.
        })
        # Clean None values specifically for MoveEffect fields
        move_specific_keys = ["cast_time", "active_duration", "cooldown", "cast_description",
                              "attack_roll", "damage", "uses", "uses_remaining", "bonus_on_hit",
                              "roll_modifier_data"]
        for key in move_specific_keys:
            if key in data and data[key] is None:
                del data[key]
        if not data.get("bonus_on_hit"): # Remove empty bonus dict
             data.pop("bonus_on_hit", None)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Optional['MoveEffect']:
        """Reconstruct MoveEffect from dictionary data."""
        try:
            # Create instance using necessary args from data
            instance = cls(
                name=data['name'],
                description=data.get('description', ''),
                star_cost=data.get('star_cost', 0),
                mp_cost=data.get('mp_cost', 0),
                hp_cost=data.get('hp_cost', 0),
                cast_time=data.get('cast_time'),
                active_duration=data.get('active_duration'), # Use active_duration
                cooldown=data.get('cooldown'),
                cast_description=data.get('cast_description'),
                attack_roll=data.get('attack_roll'),
                damage=data.get('damage'),
                crit_range=data.get('crit_range', 20),
                conditions=[ConditionType(c) if isinstance(c, str) else c for c in data.get('conditions', [])],
                roll_timing=data.get('roll_timing', 'active'),
                uses=data.get('uses'),
                bonus_on_hit=data.get('bonus_on_hit'),
                aoe_mode=data.get('aoe_mode', 'single'),
                roll_modifier=data.get('roll_modifier_data') # Restore raw data
                # debug_mode is not saved/restored
            )

            # Restore BaseEffect state and timing from data
            base_instance = BaseEffect.from_dict(data)
            if base_instance:
                 instance.state = base_instance.state
                 instance.timing = base_instance.timing
                 instance._internal_duration = base_instance._internal_duration
                 instance.turns_elapsed = base_instance.turns_elapsed
            else:
                 # Fallback if base restoration fails
                 instance.state = EffectState(data.get('state', EffectState.CREATED.value))
                 timing_data = data.get('timing_info')
                 if timing_data: instance.timing = EffectProcessTimingInfo(**timing_data)
                 instance._internal_duration = data.get('_internal_duration', instance.active_duration)
                 instance.turns_elapsed = data.get('turns_elapsed', 0)


            # Restore MoveEffect specific state
            instance.current_phase = MovePhase(data.get('move_phase', MovePhase.INSTANT.value))
            instance.phase_turns_left = data.get('phase_turns_left', 0)
            instance.uses_remaining = data.get('uses_remaining', instance.uses)
            # Restore combat/save processor state if needed (omitted for brevity, depends on requirements)

            instance.debug(f"Restored MoveEffect. Phase={instance.current_phase.value}, BaseState={instance.state.value}")
            return instance

        except KeyError as e:
            logger.error(f"Missing key during MoveEffect reconstruction: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reconstructing MoveEffect '{data.get('name', 'Unknown')}': {e}", exc_info=True)
            return None

    # Special method to retrieve async results
    async def process_async_results(self) -> List[str]:
        """
        Process any stored async coroutines from the cache (e.g., attacks).
        Called by the manager after effect processing phases.
        """
        messages = []
        if 'attack_coroutine' in self._internal_cache:
            try:
                self.debug_print("Processing async attack coroutine")
                attack_messages = await self._internal_cache.pop('attack_coroutine')
                messages.extend(attack_messages)
            except Exception as e:
                self.debug_print(f"Error processing attack coroutine: {e}")
        # Add similar handling for saves if needed
        return messages
