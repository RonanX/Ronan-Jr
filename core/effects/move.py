"""
## src/core/effects/move.py

Move Effect System Implementation with Simplified State Machine

Key Features:
- Direct, predictable state tracking for moves
- Clear state transitions with proper timing
- Consistent turn counting
- Extensive debug logging
- Immediate attack roll processing for instant moves
- Enhanced bonus tracking for hits
- Streamlined interface for combat feedback
"""

from typing import Optional, List, Dict, Any, Tuple, Set
from enum import Enum, auto
import logging
import inspect
import time
import random

from core.effects.base import BaseEffect, EffectCategory, EffectProcessTimingInfo
from core.effects.rollmod import RollModifierType, RollModifierEffect
from core.effects.condition import ConditionType
from utils.advanced_dice.calculator import DiceCalculator
from core.character import StatType

logger = logging.getLogger(__name__)

class MoveState(Enum):
    """Possible states for a move effect"""
    INSTANT = "instant"     # No cast time or duration
    CASTING = "casting"     # In cast time phase
    ACTIVE = "active"       # Active duration
    COOLDOWN = "cooldown"   # In cooldown phase

class RollTiming(Enum):
    """When to process attack rolls"""
    INSTANT = "instant"     # Roll immediately on use
    ACTIVE = "active"       # Roll when active phase starts
    PER_TURN = "per_turn"   # Roll each turn during duration

class MoveStateMachine:
    """
    Simplified state machine for tracking move phases.
    This class replaces the PhaseManager with a more direct approach.
    
    Key improvements:
    - Direct turn counting with no complex calculations
    - Explicit state transitions based on turn counts
    - Prevention of double-processing
    - Detailed state tracking
    - Fixed transitions that properly set the removal flag
    - Support for "during own turn" duration adjustments
    """
    def __init__(self, cast_time=None, duration=None, cooldown=None, debug_mode=True):
        """
        Initialize the state machine.
        
        Args:
            cast_time: Number of turns for casting phase (None/0 to skip)
            duration: Number of turns for active phase (None/0 to skip)
            cooldown: Number of turns for cooldown phase (None/0 to skip)
            debug_mode: Whether to output debug messages
        """
        self.debug_mode = debug_mode
        self.debug_id = f"MSM-{int(time.time() * 1000) % 10000}"  # Unique ID for debugging
        
        # Store original durations
        self.cast_time = cast_time
        self.duration = duration
        self.cooldown = cooldown
        
        self.debug_print(f"Initializing with cast={cast_time}, duration={duration}, cooldown={cooldown}")
        
        # Initialize the first state
        if cast_time and cast_time > 0:
            self.state = MoveState.CASTING
            self.turns_remaining = cast_time
        elif duration and duration > 0:
            self.state = MoveState.ACTIVE
            self.turns_remaining = duration
        elif cooldown and cooldown > 0:
            self.state = MoveState.COOLDOWN
            self.turns_remaining = cooldown
        else:
            self.state = MoveState.INSTANT
            self.turns_remaining = 0
            
        self.last_processed_round = None
        self.last_processed_turn = None
        self.was_just_activated = False    # Track if we just entered the active state
        self.should_be_removed = False     # Flag to indicate removal is needed
        self.transition_message = None     # Store the last transition message
        
        # Track whether this move was used during the character's own turn
        self.used_during_own_turn = False
        # Track internal duration adjustments
        self.duration_adjusted = False
        # Store the displayed duration for user-facing messages
        self.display_duration = duration
        
        self.debug_print(f"Starting in state: {self.state.value} with {self.turns_remaining} turns remaining")
    
    def debug_print(self, message):
        """Print debug messages if debug mode is enabled"""
        if self.debug_mode:
            print(f"[{self.debug_id}] {message}")
            
    def get_current_state(self) -> MoveState:
        """Get the current state"""
        return self.state
    
    def get_remaining_turns(self) -> int:
        """Get remaining turns in current phase"""
        return max(0, self.turns_remaining)
    
    def get_display_turns(self) -> int:
        """
        Get the user-facing duration that should be displayed.
        For effects applied during own turn, this may differ from
        the internal turns_remaining value.
        """
        if self.state != MoveState.ACTIVE or not self.duration_adjusted:
            return self.get_remaining_turns()
            
        # For duration-adjusted effects, show one less turn remaining
        if self.used_during_own_turn and self.turns_remaining > 1:
            return max(1, self.turns_remaining - 1)
            
        return max(0, self.turns_remaining)
    
    def adjust_for_during_own_turn(self, is_during_own_turn: bool = False) -> None:
        """
        Apply duration adjustments based on whether the effect is applied
        during the character's own turn.
        
        Args:
            is_during_own_turn: Whether this effect is being applied during 
                                the character's own turn
        """
        self.used_during_own_turn = is_during_own_turn
        
        # Only adjust active state durations
        if self.state != MoveState.ACTIVE or not self.duration:
            return
            
        # For effects applied during the character's own turn
        if is_during_own_turn:
            if self.duration == 1:
                # Special case for duration 1
                self.turns_remaining = 2  # Will expire after next turn
                self.display_duration = 1  # But show as 1 turn
            elif not self.duration_adjusted:
                # For longer durations, add 1 to internal duration
                self.turns_remaining += 1
                self.display_duration = self.duration  # Keep original for display
            
            self.duration_adjusted = True
            self.debug_print(f"Adjusted for during-own-turn: internal={self.turns_remaining}, display={self.display_duration}")
    
    def process_turn(self, round_number, turn_name) -> Tuple[bool, Optional[str]]:
        """
        Process a turn for this state machine with fixed transition logic.
        Returns (did_transition, transition_message)
        """
        # Prevent double-processing
        if (self.last_processed_round == round_number and 
            self.last_processed_turn == turn_name):
            self.debug_print(f"Skipping duplicate process_turn call for round {round_number}, turn {turn_name}")
            return False, None
            
        self.last_processed_round = round_number
        self.last_processed_turn = turn_name
        
        # Reset activation tracking
        self.was_just_activated = False
        self.transition_message = None
        
        # Only instant state has no turns remaining
        if self.state == MoveState.INSTANT:
            return False, None
            
        # Decrement turns remaining
        self.debug_print(f"Processing turn from {self.turns_remaining} turns remaining")
        self.turns_remaining -= 1
        
        # Handle duration expired
        if self.turns_remaining <= 0:
            old_state = self.state
            message = None
            
            # Handle state transitions
            if self.state == MoveState.CASTING:
                # After casting, go to ACTIVE if there's duration, or COOLDOWN if not
                if self.duration and self.duration > 0:
                    self.state = MoveState.ACTIVE
                    self.turns_remaining = self.duration
                    
                    # Apply duration adjustment for effects used during own turn
                    if self.used_during_own_turn and not self.duration_adjusted:
                        self.adjust_for_during_own_turn(True)
                        
                    message = "activates!"
                    self.was_just_activated = True  # Mark as just activated
                elif self.cooldown and self.cooldown > 0:
                    self.state = MoveState.COOLDOWN
                    self.turns_remaining = self.cooldown
                    message = "enters cooldown"
                else:
                    # No further phases - mark for removal and use "completes" message
                    message = "completes"
                    self.should_be_removed = True
                    
            elif self.state == MoveState.ACTIVE:
                # After active, go to COOLDOWN if there is one, otherwise remove
                if self.cooldown and self.cooldown > 0:
                    self.state = MoveState.COOLDOWN
                    self.turns_remaining = self.cooldown
                    message = "enters cooldown"
                else:
                    # No cooldown phase - mark for removal and use "wears off" message
                    message = "wears off"
                    self.should_be_removed = True
                    
            elif self.state == MoveState.COOLDOWN:
                # After cooldown, always remove the effect
                message = "cooldown has ended"
                self.should_be_removed = True
            
            self.transition_message = message
            self.debug_print(f"Transition: {old_state.value} → {self.state.value} with message: {message}")
            if self.should_be_removed:
                self.debug_print("Effect marked for removal during transition")
            
            return True, message
            
        self.debug_print(f"No transition needed. Remaining turns: {self.turns_remaining}")
        return False, None
        
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        return {
            "state": self.state.value,
            "turns_remaining": self.turns_remaining,
            "cast_time": self.cast_time,
            "duration": self.duration,
            "cooldown": self.cooldown,
            "last_processed_round": self.last_processed_round,
            "last_processed_turn": self.last_processed_turn,
            "should_be_removed": self.should_be_removed,
            "used_during_own_turn": self.used_during_own_turn,
            "duration_adjusted": self.duration_adjusted,
            "display_duration": self.display_duration
        }
        
    @classmethod
    def from_dict(cls, data: dict) -> 'MoveStateMachine':
        """Create from saved dictionary data"""
        sm = cls(
            cast_time=data.get('cast_time'),
            duration=data.get('duration'),
            cooldown=data.get('cooldown')
        )
        sm.state = MoveState(data.get('state', 'instant'))
        sm.turns_remaining = data.get('turns_remaining', 0)
        sm.last_processed_round = data.get('last_processed_round')
        sm.last_processed_turn = data.get('last_processed_turn')
        sm.should_be_removed = data.get('should_be_removed', False)
        sm.used_during_own_turn = data.get('used_during_own_turn', False)
        sm.duration_adjusted = data.get('duration_adjusted', False)
        sm.display_duration = data.get('display_duration', sm.duration)
        return sm

class SavingThrowProcessor:
    """
    Handles saving throw mechanics for effects.
    
    Processes saving throws against DCs with:
    - Support for all save types (STR, DEX, etc.)
    - Formatted messages for save results
    - Optional damage application
    - Half-damage on successful save option
    """
    def __init__(self, debug_mode=True):
        self.debug_mode = debug_mode
        self.targets_saved = set()
        self.last_save_round = None
        
    def debug_print(self, message):
        """Print debug messages if debug mode is enabled"""
        if self.debug_mode:
            print(f"[SavingThrowProcessor] {message}")
            
    async def process_save(self,
                         source, 
                         targets,
                         save_type: str,
                         save_dc: str,
                         effect_name: str,
                         half_on_save: bool = False,
                         damage: Optional[str] = None) -> List[str]:
        """
        Process saving throws for targets.
        
        Args:
            source: Character causing the save
            targets: List of characters making saves
            save_type: Type of save (str, dex, con, etc.)
            save_dc: DC expression (e.g. "8+prof+int")
            effect_name: Name of the effect
            half_on_save: Whether successful save halves damage
            damage: Optional damage to apply on failure
            
        Returns:
            List of formatted message strings
        """
        # Skip if no targets or save type
        if not targets or not save_type:
            return []
            
        # Track when we last processed saves
        self.last_save_round = getattr(source, 'round_number', None)
            
        # Import utility functions
        from utils.dice import DiceRoller
        
        self.debug_print(f"Processing saves for {len(targets)} targets")
        messages = []
        
        # Calculate actual DC
        dc_value = 10  # Default DC
        if save_dc:
            # Parse expressions like "8+prof+int"
            try:
                parts = save_dc.lower().replace(" ", "").split("+")
                dc_value = 0
                
                for part in parts:
                    if part.isdigit():
                        dc_value += int(part)
                    elif part == "prof":
                        dc_value += source.base_proficiency
                    elif part in ["str", "strength"]:
                        dc_value += source.stats.get_modifier(StatType.STRENGTH)
                    elif part in ["dex", "dexterity"]:
                        dc_value += source.stats.get_modifier(StatType.DEXTERITY)
                    elif part in ["con", "constitution"]:
                        dc_value += source.stats.get_modifier(StatType.CONSTITUTION)
                    elif part in ["int", "intelligence"]:
                        dc_value += source.stats.get_modifier(StatType.INTELLIGENCE)
                    elif part in ["wis", "wisdom"]:
                        dc_value += source.stats.get_modifier(StatType.WISDOM)
                    elif part in ["cha", "charisma"]:
                        dc_value += source.stats.get_modifier(StatType.CHARISMA)
            except Exception as e:
                self.debug_print(f"Error parsing save DC: {e}")
                
        self.debug_print(f"Calculated DC: {dc_value}")
            
        # Format a single message with all save results
        main_message = f"{save_type.upper()} Save DC {dc_value} | {effect_name}"
        
        # Process each target's save
        target_results = []
        for target in targets:
            # Get save modifier based on type
            save_mod = 0
            if save_type.lower() in ["str", "strength"]:
                save_mod = target.saves.get(StatType.STRENGTH, 0)
            elif save_type.lower() in ["dex", "dexterity"]:
                save_mod = target.saves.get(StatType.DEXTERITY, 0)
            elif save_type.lower() in ["con", "constitution"]:
                save_mod = target.saves.get(StatType.CONSTITUTION, 0)
            elif save_type.lower() in ["int", "intelligence"]:
                save_mod = target.saves.get(StatType.INTELLIGENCE, 0)
            elif save_type.lower() in ["wis", "wisdom"]:
                save_mod = target.saves.get(StatType.WISDOM, 0)
            elif save_type.lower() in ["cha", "charisma"]:
                save_mod = target.saves.get(StatType.CHARISMA, 0)
                
            # Roll the save
            roll_result = random.randint(1, 20)
            total = roll_result + save_mod
            
            # Check if save succeeds
            success = total >= dc_value
            if success:
                self.targets_saved.add(target.name)
                
            # Format target result
            result_text = f"{target.name}: {roll_result}+{save_mod}={total} | {'✅' if success else '❌'}"
            
            # Handle damage if applicable
            if damage:
                damage_dealt = 0
                
                if not success:
                    # Full damage on failure
                    damage_roll, _ = DiceRoller.roll_dice(damage, target)
                    damage_dealt = damage_roll
                elif half_on_save:
                    # Half damage on success with half_on_save
                    damage_roll, _ = DiceRoller.roll_dice(damage, target)
                    damage_dealt = damage_roll // 2
                    result_text += f" | Half dmg: {damage_dealt}"
                
                # Apply the damage
                if damage_dealt > 0:
                    # Handle any temp HP first
                    if target.resources.current_temp_hp > 0:
                        absorbed = min(target.resources.current_temp_hp, damage_dealt)
                        target.resources.current_temp_hp -= absorbed
                        damage_dealt -= absorbed
                        
                        if absorbed > 0:
                            result_text += f" | {absorbed} absorbed"
                    
                    # Apply remaining damage to regular HP
                    if damage_dealt > 0:
                        old_hp = target.resources.current_hp
                        target.resources.current_hp = max(0, old_hp - damage_dealt)
                        
                        if not success:
                            result_text += f" | {damage_dealt} damage"
            
            target_results.append(result_text)
            
        # Format final message with all results
        if target_results:
            formatted = f"🎯 `{main_message}` 🎯\n" + "\n".join(f"• `{result}`" for result in target_results)
            messages.append(formatted)
            
        return messages

class BonusOnHit:
    """
    Handles applying and tracking bonuses when a move hits.
    
    Features:
    - Resource bonuses (MP, HP, stars) with dice expression support
    - Custom note tracking
    - Per-hit and total bonus calculation
    - Formatted message generation
    """
    def __init__(self, 
                mp_bonus=0, 
                hp_bonus=0, 
                star_bonus=0, 
                custom_note: Optional[str] = None,
                debug_mode: bool = True):
        # Store raw values, might be integers or dice expressions
        self.mp_bonus = mp_bonus
        self.hp_bonus = hp_bonus
        self.star_bonus = star_bonus
        self.custom_note = custom_note
        self.debug_mode = debug_mode
        self.hit_count = 0
        
    def debug_print(self, message):
        """Print debug messages if debug mode is enabled"""
        if self.debug_mode:
            print(f"[BonusOnHit] {message}")
    
    def has_bonuses(self) -> bool:
        """Check if any bonuses are configured"""
        return (self.mp_bonus != 0 or 
                self.hp_bonus != 0 or 
                self.star_bonus != 0 or 
                self.custom_note is not None)
    
    def register_hit(self):
        """Register a successful hit"""
        self.hit_count += 1
        self.debug_print(f"Registered hit. Total hits: {self.hit_count}")
    
    def reset(self):
        """Reset hit counter"""
        self.hit_count = 0
    
    def apply_bonuses(self, character) -> Tuple[Dict[str, int], str]:
        """
        Apply all bonuses to character based on hits.
        Supports both fixed values and dice expressions.
        Returns (bonus_totals, formatted_message)
        """
        if self.hit_count == 0 or not self.has_bonuses():
            return {}, ""
        
        # Import dice roller here to avoid circular imports
        from utils.dice import DiceRoller
        
        self.debug_print(f"Applying bonuses for {self.hit_count} hits")
        
        # Calculate total bonuses
        totals = {}
        message_parts = []
        
        # MP bonus
        if self.mp_bonus:
            # Calculate total MP bonus
            if isinstance(self.mp_bonus, str) and (('d' in self.mp_bonus.lower()) or any(stat in self.mp_bonus.lower() for stat in ['str', 'dex', 'con', 'int', 'wis', 'cha'])):
                # It's a dice expression or has stat modifier, roll it for each hit
                total_mp = 0
                for _ in range(self.hit_count):
                    mp_roll, _ = DiceRoller.roll_dice(self.mp_bonus, character)
                    total_mp += mp_roll
                self.debug_print(f"Rolled MP bonus {self.mp_bonus} × {self.hit_count} = {total_mp}")
            else:
                # It's a fixed number
                total_mp = int(self.mp_bonus) * self.hit_count
                
            totals['mp'] = total_mp
            
            # Apply MP bonus (respecting max)
            old_mp = character.resources.current_mp
            character.resources.current_mp = min(
                character.resources.max_mp,
                old_mp + total_mp
            )
            
            message_parts.append(f"💙 MP: +{total_mp}")
        
        # HP bonus
        if self.hp_bonus:
            # Calculate total HP bonus
            if isinstance(self.hp_bonus, str) and ('d' in self.hp_bonus.lower()):
                # It's a dice expression, roll it for each hit
                total_hp = 0
                for _ in range(self.hit_count):
                    hp_roll, _ = DiceRoller.roll_dice(self.hp_bonus, character)
                    total_hp += hp_roll
                self.debug_print(f"Rolled HP dice {self.hp_bonus} × {self.hit_count} = {total_hp}")
            else:
                # It's a fixed number
                total_hp = int(self.hp_bonus) * self.hit_count
                
            totals['hp'] = total_hp
            
            # Apply HP bonus (respecting max)
            old_hp = character.resources.current_hp
            character.resources.current_hp = min(
                character.resources.max_hp,
                old_hp + total_hp
            )
            
            message_parts.append(f"❤️ HP: +{total_hp}")
        
        # Star bonus
        if self.star_bonus:
            # Calculate total star bonus
            if isinstance(self.star_bonus, str) and ('d' in self.star_bonus.lower()):
                # It's a dice expression, roll it for each hit
                total_stars = 0
                for _ in range(self.hit_count):
                    stars_roll, _ = DiceRoller.roll_dice(self.star_bonus, character)
                    total_stars += stars_roll
                self.debug_print(f"Rolled star dice {self.star_bonus} × {self.hit_count} = {total_stars}")
            else:
                # It's a fixed number
                total_stars = int(self.star_bonus) * self.hit_count
                
            totals['stars'] = total_stars
            
            # Apply star bonus if character has action_stars
            if hasattr(character, 'action_stars'):
                if hasattr(character.action_stars, 'add_bonus_stars'):
                    character.action_stars.add_bonus_stars(total_stars)
                elif hasattr(character.action_stars, 'add_stars'):
                    character.action_stars.add_stars(total_stars)
                
            message_parts.append(f"⭐ +{total_stars}")
        
        # Custom note
        if self.custom_note:
            note = f"📝 {self.custom_note} ({self.hit_count}x)"
            message_parts.append(note)
            totals['custom'] = self.hit_count
        
        # Format message
        if message_parts:
            formatted = f"{self.hit_count} Hits! Bonuses: | {' | '.join(message_parts)}"
        else:
            formatted = f"{self.hit_count} Hits!"
            
        return totals, formatted
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'BonusOnHit':
        """Create from dictionary data (typically from bonus_on_hit parameter)"""
        if not data:
            return cls()
        
        # Debug the incoming data
        print(f"[BonusOnHit] Creating from data: {data}")
            
        # Handle both direct values and nested dictionaries
        if isinstance(data, dict):
            return cls(
                mp_bonus=data.get('mp', 0),     # This can now be an int or dice string
                hp_bonus=data.get('hp', 0),     # This can now be an int or dice string
                star_bonus=data.get('stars', 0), # This can now be an int or dice string
                custom_note=data.get('note')
            )
        return cls()  # Return empty instance if data is invalid
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage"""
        data = {}
        if self.mp_bonus != 0:
            data['mp'] = self.mp_bonus
        if self.hp_bonus != 0:
            data['hp'] = self.hp_bonus
        if self.star_bonus != 0:
            data['stars'] = self.star_bonus
        if self.custom_note:
            data['note'] = self.custom_note
        return data

class CombatProcessor:
    """
    Handles attack rolls and damage calculations.
    
    This class encapsulates:
    - Attack roll processing
    - Target handling
    - Damage calculation
    - Hit tracking
    - Bonus application
    
    Supports both sync and async patterns for flexibility.
    """
    def __init__(self, debug_mode=True):
        self.targets_hit = set()
        self.attacks_this_turn = 0
        self.aoe_mode = 'single'
        self.debug_mode = debug_mode
        
    def debug_print(self, message):
        """Print debug messages if debug mode is enabled"""
        if self.debug_mode:
            print(f"[CombatProcessor] {message}")
            
    async def process_attack(self, 
                           source, 
                           targets,
                           attack_roll,
                           damage,
                           crit_range,
                           reason,
                           bonus_on_hit=None) -> List[str]:
        """Process attack roll and damage"""
        # Skip if no attack roll defined
        if not attack_roll:
            return []

        # Track attack count
        self.attacks_this_turn += 1
        self.debug_print(f"Processing attack (count: {self.attacks_this_turn})")
        messages = []
        
        # Import here to avoid circular import
        from utils.advanced_dice.attack_calculator import AttackCalculator, AttackParameters
        
        # Always create a fresh BonusOnHit tracker for each attack
        if isinstance(bonus_on_hit, BonusOnHit):
            hit_bonus = bonus_on_hit
            # Reset counter for new attack
            hit_bonus.reset()
        else:
            # Convert dictionary to BonusOnHit
            hit_bonus = BonusOnHit.from_dict(bonus_on_hit)
        
        self.debug_print(f"Using hit bonus tracker: {hit_bonus.__dict__}")
        
        # Handle no targets case
        if not targets:
            # Set up attack parameters
            params = AttackParameters(
                roll_expression=attack_roll,
                character=source,
                targets=None,
                damage_str=damage,
                crit_range=crit_range,
                reason=reason
            )
            
            # Process attack - this call is already awaitable
            self.debug_print(f"Processing no-target attack with {attack_roll}")
            message, _ = await AttackCalculator.process_attack(params)
            messages.append(message)
            return messages
        
        # Set up attack parameters for all targets
        params = AttackParameters(
            roll_expression=attack_roll,
            character=source,
            targets=targets,
            damage_str=damage,
            crit_range=crit_range,
            aoe_mode=self.aoe_mode,
            reason=reason
        )

        # Process attack with all targets - get message and hit data
        self.debug_print(f"Processing attack with {attack_roll} against {len(targets)} targets")
        message, hit_data = await AttackCalculator.process_attack(params)
        messages.append(message)
        
        # Debug output for hit data
        self.debug_print(f"Got hit data: {hit_data}")
        
        # Process hit tracking
        if isinstance(hit_data, dict) and hit_data:  # Ensure it's a dictionary with entries
            # Extract hit targets from attack results
            hit_count = 0
            for target_name, target_hit_data in hit_data.items():
                if target_hit_data.get('hit', False):
                    self.debug_print(f"Target hit: {target_name}")
                    self.targets_hit.add(target_name)
                    hit_bonus.register_hit()
                    hit_count += 1
            
            self.debug_print(f"Total hits: {hit_count}, Has bonuses: {hit_bonus.has_bonuses()}")
            
            # Apply bonuses on hit if any hits occurred and we have bonuses configured
            if hit_count > 0 and hit_bonus.has_bonuses():
                self.debug_print(f"Applying bonuses for {hit_count} hits")
                bonus_totals, bonus_message = hit_bonus.apply_bonuses(source)
                self.debug_print(f"Bonus message: {bonus_message}")
                if bonus_message:
                    messages.append(f"• `{bonus_message}`")
        
        return messages

class MoveEffect(BaseEffect):
    """
    Handles move execution with improved timing and duration system.
    
    This implementation:
    1. Integrates with BaseEffect's duration system
    2. Properly handles "during own turn" timing
    3. Correctly manages state transitions
    4. Supports both immediate and delayed effects
    5. Includes force_during parameter for manual control
    """
    def __init__(
        self, 
        name: str,
        description: str,
        star_cost: int = 0,
        mp_cost: int = 0,
        hp_cost: int = 0,
        cast_time: Optional[int] = None,
        duration: Optional[int] = None,
        cooldown: Optional[int] = None,
        cast_description: Optional[str] = None,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        crit_range: int = 20,
        conditions: Optional[List[ConditionType]] = None,
        roll_timing: str = "active",
        uses: Optional[int] = None,
        targets: Optional[List['Character']] = None,
        bonus_on_hit: Optional[Dict] = None,
        aoe_mode: str = 'single',
        enable_heat_tracking: bool = False,  # Legacy parameter
        enable_hit_bonus: bool = False,      # Legacy parameter
        roll_modifier: Optional[Dict[str, Any]] = None,
        force_during: Optional[bool] = None  # New parameter for explicit timing
    ):
        """
        Initialize a move effect with improved duration handling.
        
        Args:
            name: Name of the move
            description: Description of the move
            star_cost: Action star cost
            mp_cost: Mana point cost (can be negative for regen)
            hp_cost: Health point cost (can be negative for healing)
            cast_time: Turns to cast before active
            duration: Turns active after cast
            cooldown: Turns in cooldown after active
            cast_description: Optional custom text for casting
            attack_roll: Attack roll formula (e.g. "1d20+str")
            damage: Damage formula (e.g. "2d6+dex fire")
            crit_range: Value for critical hit (20 = only on nat 20)
            conditions: List of conditions to apply
            roll_timing: When to process attack roll (instant, active, per_turn)
            uses: Number of uses per combat
            targets: List of target characters
            bonus_on_hit: Dictionary of bonuses to apply on hit
            aoe_mode: How to handle multiple targets (single or multi)
            roll_modifier: Optional roll modifier to apply
            force_during: Force the effect to be treated as during/not during own turn
        """
        # Initialize base effect with proper duration handling
        super().__init__(
            name=name,
            duration=duration,
            permanent=False,
            category=EffectCategory.STATUS,
            description=description,
            process_timing="both",
            emoji="✨",
            debug_mode=True
        )
        
        # Create state machine
        self.state_machine = MoveStateMachine(
            cast_time=cast_time,
            duration=duration,
            cooldown=cooldown,
            debug_mode=True
        )
        
        self.combat = CombatProcessor(debug_mode=True)
        self.saves = SavingThrowProcessor(debug_mode=True)
        
        # Store resource costs
        self.star_cost = star_cost
        self.mp_cost = mp_cost
        self.hp_cost = hp_cost
        
        # Store tracking info
        self.uses = uses
        self.uses_remaining = uses
        
        # Combat parameters
        self.attack_roll = attack_roll
        self.damage = damage
        self.crit_range = crit_range
        
        # Set conditions
        self.conditions = conditions or []
        
        # Store additional properties
        self.cast_description = cast_description
        self.targets = targets or []
        
        # Determine roll timing
        try:
            self.roll_timing = RollTiming(roll_timing)
        except (ValueError, TypeError):
            # Default to ACTIVE if invalid
            self.roll_timing = RollTiming.ACTIVE
            self.debug(f"Invalid roll timing '{roll_timing}', defaulting to ACTIVE")
        
        # Auto-detect instant attacks if not explicit
        if (self.attack_roll and 
            not self.state_machine.cast_time and 
            self.roll_timing == RollTiming.ACTIVE):
            # If a move has an attack roll and no cast time, make it INSTANT by default
            self.roll_timing = RollTiming.INSTANT
            self.debug(f"Auto-detected INSTANT roll timing for attack roll")
        
        # Initialize bonus on hit
        # Convert legacy heat tracking to bonus_on_hit if needed
        if bonus_on_hit is None and (enable_heat_tracking or enable_hit_bonus):
            self.debug(f"Converting legacy heat tracking to bonus_on_hit")
            bonus_on_hit = {'stars': 1}
        
        # Special handling for bonus_on_hit parameter
        if bonus_on_hit is not None:
            # Print the raw value for debugging
            self.debug(f"Raw bonus_on_hit value: {bonus_on_hit}")
            
            # Handle string values (common in Discord commands)
            if isinstance(bonus_on_hit, str):
                try:
                    import json
                    # Try to parse as JSON
                    parsed_bonus = json.loads(bonus_on_hit)
                    self.debug(f"Parsed bonus_on_hit from JSON: {parsed_bonus}")
                    bonus_on_hit = parsed_bonus
                except:
                    # If parsing fails, use a default value
                    self.debug(f"Failed to parse bonus_on_hit from string, using default")
                    bonus_on_hit = {'stars': 1}
        
        self.debug(f"Final bonus_on_hit: {bonus_on_hit}")
        self.bonus_on_hit = BonusOnHit.from_dict(bonus_on_hit)
        
        # Initialize roll modifier if provided
        self.roll_modifier_data = roll_modifier
        self.roll_modifier_effect = None

        # Apply roll modifier if specified
        if roll_modifier:
            self.debug(f"Processing roll modifier data: {roll_modifier}")
            
            # Expected format: {"type": "bonus|advantage|disadvantage", "value": int, "next_roll": bool}
            mod_type = roll_modifier.get("type", "bonus").lower()
            mod_value = roll_modifier.get("value", 1)
            next_only = roll_modifier.get("next_roll", False)
            mod_name = roll_modifier.get("name", f"{name} Roll Effect")
            
            # Convert string type to enum
            modifier_type = None
            for t in RollModifierType:
                if t.value == mod_type:
                    modifier_type = t
                    break
            
            if not modifier_type:
                modifier_type = RollModifierType.BONUS
            
            # Create the effect but don't add it yet - will be added during on_apply
            self.roll_modifier_effect = RollModifierEffect(
                name=mod_name,
                modifier_type=modifier_type,
                value=mod_value,
                next_roll_only=next_only,
                duration=None if next_only else duration,
                permanent=False,
                description=f"From {name}"
            )
        
        # Configure combat settings
        self.combat.aoe_mode = aoe_mode
        
        # Tracking variables
        self.marked_for_removal = False
        self._internal_cache = {}  # Cache for async results
        self.last_roll_round = None  # Track when we last rolled
        
        # Add transition counter to track how many times we've transitioned
        self.transition_count = 0
        
        # Add is_during_own_turn flag for duration calculation
        self.is_during_own_turn = force_during
        
        # Displayed duration for user-facing messages
        self.displayed_duration = duration  # For user-facing display

    # --- Override BaseEffect methods ---
    
    def on_apply(self, character, round_number: int) -> str:
        """
        Called when the effect is first applied to a character.
        Handles state transition, timing initialization, and duration adjustment.
        """
        self.debug(f"on_apply called for {character.name} on round {round_number}")
        
        # First call the parent method to initialize timing
        apply_msg = super().on_apply(character, round_number)
        
        # Set the state machine's during_own_turn flag from our timing info
        if self.timing and hasattr(self.state_machine, 'used_during_own_turn'):
            self.state_machine.used_during_own_turn = self.timing.applied_during_own_turn
            self.state_machine.adjust_for_during_own_turn(self.timing.applied_during_own_turn)
            self.debug(f"Set state machine during_own_turn to {self.timing.applied_during_own_turn}")
        
        # Apply resource costs and format messages
        details = []
        timing_info = []
        attack_messages = []
        bonus_messages = []
        
        # Apply costs and collect messages
        cost_messages = self.apply_costs(character)
        
        # Build cost and resource info - FIXED to avoid duplication
        costs = []
        if self.mp_cost != 0:
            if self.mp_cost > 0:
                costs.append(f"💙 MP: {self.mp_cost}")
            else:
                costs.append(f"💙 +{abs(self.mp_cost)} MP")
        
        if self.hp_cost != 0:
            if self.hp_cost > 0:
                costs.append(f"❤️ HP: {self.hp_cost}")
            else:
                costs.append(f"❤️ +{abs(self.hp_cost)} HP")
        
        # Add star cost
        if self.star_cost > 0:
            costs.append(f"⭐ {self.star_cost}")
        
        # Add timing info based on state machine
        if self.state_machine.cast_time:
            timing_info.append(f"🔄 {self.state_machine.cast_time}T Cast")
        
        # Use display_duration for consistent user-facing messages
        if self.state_machine.duration:
            timing_info.append(f"⏳ {self.displayed_duration}T Duration")
            
        if self.state_machine.cooldown:
            timing_info.append(f"⌛ {self.state_machine.cooldown}T Cooldown")
            
        # Format target info if any
        if self.targets and not (self.attack_roll and self.roll_timing == RollTiming.INSTANT):
            # Only add target details for non-instant attacks, since 
            # instant attacks show targets in the attack output
            target_names = ", ".join(t.name for t in self.targets)
            details.append(f"Target{'s' if len(self.targets) > 1 else ''}: {target_names}")
            
        # Process instant attack rolls immediately
        if self.attack_roll and self.roll_timing == RollTiming.INSTANT:
            self.debug(f"Processing instant attack roll")
            # Process attack immediately
            attack_results = await self.combat.process_attack(
                source=character,
                targets=self.targets,
                attack_roll=self.attack_roll,
                damage=self.damage,
                crit_range=self.crit_range,
                reason=self.name,
                bonus_on_hit=self.bonus_on_hit
            )
            if attack_results:
                # Separate attack messages and bonus messages
                for message in attack_results:
                    if "Hits! Bonuses:" in message:
                        bonus_messages.append(message)
                    else:
                        attack_messages.append(message)
                    
        # Build the primary message
        if self.cast_description:
            main_message = f"{character.name} {self.cast_description} {self.name}"
        else:
            if self.state_machine.state == MoveState.INSTANT:
                main_message = f"{character.name} uses {self.name}"
            elif self.state_machine.state == MoveState.CASTING:
                main_message = f"{character.name} begins casting {self.name}"
            else:
                main_message = f"{character.name} uses {self.name}"
                
        # Build supplementary info parts
        info_parts = []
        
        # Add costs and timing
        if costs:
            info_parts.append(" | ".join(costs))
        if timing_info:
            info_parts.append(" | ".join(timing_info))
            
        # Format info
        if info_parts:
            main_message = f"{main_message} | {' | '.join(info_parts)}"
            
        # Create the primary formatted message
        formatted_message = self.format_effect_message(main_message)
            
        # Add bullets for details
        if details:
            detail_strings = []
            for detail in details:
                if not detail.startswith("•") and not detail.startswith("`"):
                    detail_strings.append(f"• `{detail}`")
                else:
                    detail_strings.append(detail)
                    
            formatted_message += "\n" + "\n".join(detail_strings)
            
        # Apply roll modifier effect if configured
        if self.roll_modifier_effect:
            # Ensure it gets proper timing setup
            self.roll_modifier_effect.initialize_timing(round_number, character.name)
            
            # Add to character's custom parameters
            if 'roll_modifiers' not in character.custom_parameters:
                character.custom_parameters['roll_modifiers'] = []
                
            character.custom_parameters['roll_modifiers'].append(self.roll_modifier_effect)
            
            # Add info to message
            if isinstance(self.roll_modifier_effect.modifier_type, RollModifierType):
                if self.roll_modifier_effect.modifier_type == RollModifierType.BONUS:
                    sign = "+" if self.roll_modifier_effect.value >= 0 else ""
                    msg = f"{sign}{self.roll_modifier_effect.value} to rolls"
                else:
                    msg = f"{self.roll_modifier_effect.modifier_type.value}"
                    if self.roll_modifier_effect.value > 1:
                        msg += f" {self.roll_modifier_effect.value}"
                    msg += " to rolls"
                    
                if self.roll_modifier_effect.next_roll_only:
                    msg += " (next roll only)"
                else:
                    # Use the displayed duration
                    duration_str = "permanently" if self.permanent else f"for {self.duration} turns"
                    msg += f" {duration_str}"
                    
                formatted_message += f"\n• `{msg}`"
            
        # Add attack messages directly to the response for instant attacks
        if attack_messages:
            formatted_message += "\n" + "\n".join(attack_messages)
            
        # Add bonus messages after attack messages
        if bonus_messages:
            formatted_message += "\n" + "\n".join(bonus_messages)
        
        # For instant moves with no follow-up needed, mark for removal
        if self.state_machine.state == MoveState.INSTANT and self.state_machine.cooldown is None:
            self.marked_for_removal = True
        
        self.debug(f"on_apply complete, returning formatted message")
        return formatted_message
    
    async def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process start of turn effects with proper attack roll handling.
        
        Includes:
        - Status display based on current phase
        - Attack roll processing for active effects
        - Save processing as needed
        - Full feedback based on action outcomes
        """
        # Only process effect changes on the owner's turn
        if character.name != turn_name:
            return []

        self.debug(f"on_turn_start for {character.name} on round {round_number}")
        messages = []
        
        # Display message based on current state
        if self.state_machine.state == MoveState.CASTING:
            remaining = self.state_machine.get_remaining_turns()
            self.debug(f"Casting phase, {remaining} turns remaining")
            cast_msg = self.format_effect_message(
                f"Casting {self.name}",
                [f"{remaining} turn{'s' if remaining != 1 else ''} remaining"]
            )
            messages.append(cast_msg)
                
        elif self.state_machine.state == MoveState.ACTIVE:
            # Handle special case for newly activated effects
            just_activated = self.state_machine.was_just_activated
            is_per_turn = self.roll_timing == RollTiming.PER_TURN
            
            # Process attack if needed (PER_TURN or newly ACTIVE)
            if self.attack_roll and (is_per_turn or just_activated):
                self.debug(f"Processing turn start attack roll")
                self.last_roll_round = round_number
                
                # Reset bonus tracker for new rolls
                self.bonus_on_hit.reset()
                
                # Process attack directly
                attack_results = await self.combat.process_attack(
                    source=character,
                    targets=self.targets,
                    attack_roll=self.attack_roll,
                    damage=self.damage,
                    crit_range=self.crit_range,
                    reason=self.name,
                    bonus_on_hit=self.bonus_on_hit
                )
                if attack_results:
                    messages.extend(attack_results)
            else:
                self.debug(f"Skipping attack roll - timing: {self.roll_timing.value}, last_roll_round: {self.last_roll_round}")
            
            # Show active message
            remaining = self.state_machine.get_display_turns()
            details = []
            if self.description:
                if ';' in self.description:
                    for part in self.description.split(';'):
                        part = part.strip()
                        if part:
                            details.append(part)
                else:
                    details.append(self.description)
            
            # Add remaining duration
            details.append(f"{remaining} turn{'s' if remaining != 1 else ''} remaining")
            
            active_msg = self.format_effect_message(
                f"{self.name} active",
                details
            )
            # Only add status message if we don't already have combat results to show
            if not messages or (not any("attack" in msg.lower() for msg in messages) and 
                               not any("save" in msg.lower() for msg in messages)):
                messages.append(active_msg)
        
        elif self.state_machine.state == MoveState.COOLDOWN:
            # Show cooldown status at turn start too
            remaining = self.state_machine.get_remaining_turns()
            if remaining > 0:
                cooldown_msg = self.format_effect_message(
                    f"{self.name} cooldown",
                    [f"{remaining} turn{'s' if remaining != 1 else ''} remaining"]
                )
                messages.append(cooldown_msg)
        
        return messages

    async def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Handle phase transitions and duration tracking with enhanced feedback.
        
        This method:
        1. Processes state machine transitions
        2. Handles duration tracking consistently with BaseEffect
        3. Adds expiry messages to feedback system
        4. Returns appropriate messages for each state
        """
        # Only process for effect owner
        if character.name != turn_name:
            return []
            
        self.debug(f"on_turn_end for {character.name} on round {round_number}")
        messages = []
        
        # Get pre-transition state for comparison
        old_state = self.state_machine.state
        old_remaining = self.state_machine.get_remaining_turns()
        
        # Check if already marked for removal
        if self.marked_for_removal or self.state_machine.should_be_removed:
            self.debug(f"Effect already marked for removal, skipping further processing")
            
            # Add to feedback system with proper expiry message
            expiry_msg = self.format_effect_message(
                f"{self.name} has worn off from {character.name}"
            )
            self._add_expiry_feedback(character, expiry_msg, round_number)
            
            # Need to call parent class to handle state transition
            super().on_turn_end(character, round_number, turn_name)
            return []
        
        # Check transition count to prevent infinite transitions
        if self.transition_count > 10:
            self.debug(f"Too many transitions detected ({self.transition_count}), forcing removal")
            self.marked_for_removal = True
            super().on_turn_end(character, round_number, turn_name)
            return []
        
        # Process state machine transition first
        did_transition, transition_msg = self.state_machine.process_turn(round_number, turn_name)
        
        # Update internal state based on state machine
        if self.state_machine.state == MoveState.ACTIVE:
            self.state = EffectState.ACTIVE
        elif self.state_machine.state == MoveState.EXPIRED or self.state_machine.should_be_removed:
            self.state = EffectState.EXPIRED
            
        # Check if the state machine now indicates removal
        if self.state_machine.should_be_removed:
            self.debug(f"State machine indicates removal is needed after transition")
            self.marked_for_removal = True
            
            # Add a proper expiry message that will show up in the effect update
            expiry_msg = self.format_effect_message(
                f"{self.name} has worn off from {character.name}",
                ["Effect complete"]
            )
            self._add_expiry_feedback(character, expiry_msg, round_number)
            
            # Return special wears off message for final cleanup
            if transition_msg == "wears off" or transition_msg == "final removal":
                messages.append(self.format_effect_message(
                    f"{self.name} wears off",
                    [f"Effect has ended"]
                ))
                
            # Call parent to handle state transition
            super().on_turn_end(character, round_number, turn_name)
            return messages
        
        # Handle non-transition updates (normal duration tracking)
        if not did_transition:
            # Show duration update for active and cooldown phases
            if self.state_machine.state == MoveState.ACTIVE and old_remaining > 0:
                # Use display_turns for user-facing duration
                remaining = self.state_machine.get_display_turns()
                
                continue_msg = self.format_effect_message(
                    f"{self.name} continues",
                    [f"{remaining} turn{'s' if remaining != 1 else ''} remaining"]
                )
                messages.append(continue_msg)
                
            # Show casting continuation
            elif self.state_machine.state == MoveState.CASTING and old_remaining > 0:
                remaining = self.state_machine.get_remaining_turns()
                cast_msg = self.format_effect_message(
                    f"Casting {self.name}",
                    [f"{remaining} turn{'s' if remaining != 1 else ''} remaining"]
                )
                messages.append(cast_msg)
        
        # Show transition message if needed - with enhanced formatting
        if did_transition and transition_msg:
            self.debug(f"State transition: {transition_msg}")
            self.transition_count += 1
            
            # Format transition message based on new state
            if self.state_machine.state == MoveState.ACTIVE:
                # Casting to Active transition
                # Use display_duration for consistent user-facing messages
                display_duration = self.displayed_duration
                
                msg = self.format_effect_message(
                    f"{self.name} {transition_msg}",
                    [
                        f"Cast time complete!",
                        f"Effect active for {display_duration} turn{'s' if display_duration != 1 else ''}"
                    ],
                    emoji="✨"
                )
            elif self.state_machine.state == MoveState.COOLDOWN:
                # Active to Cooldown transition
                msg = self.format_effect_message(
                    f"{self.name} {transition_msg}",
                    [
                        f"Effect duration complete",
                        f"Cooldown: {self.state_machine.get_remaining_turns()} turn{'s' if self.state_machine.get_remaining_turns() != 1 else ''}"
                    ],
                    emoji="⏳"
                )
            elif transition_msg == "cooldown has ended":
                # Cooldown ended
                msg = self.format_effect_message(
                    f"{self.name} cooldown has ended",
                    ["Ready to use again"],
                    emoji="✅"
                )
                # Mark for removal at the end of cooldown
                self.marked_for_removal = True
            elif transition_msg == "wears off" or transition_msg == "final removal":
                # Effect wears off (no further phases)
                msg = self.format_effect_message(
                    f"{self.name} wears off",
                    ["Effect has ended"],
                    emoji="✨"
                )
                # Mark for removal when wearing off
                self.marked_for_removal = True
            else:
                # Generic transition
                msg = self.format_effect_message(f"{self.name} {transition_msg}")
                
            messages.append(msg)
            
            # Add to feedback system if this is a final transition
            if self.marked_for_removal:
                self.debug(f"Adding to feedback system for final transition")
                self._add_expiry_feedback(character, msg, round_number)
        
        # Call parent to handle state transition and duration tracking
        parent_messages = super().on_turn_end(character, round_number, turn_name)
        
        # Filter out expiry messages since we handle them above
        for msg in parent_messages:
            if "worn off" not in msg.lower() and "expired" not in msg.lower():
                messages.append(msg)
        
        return messages

    def on_expire(self, character) -> str:
        """
        Called when the effect is finally removed (either by duration or force).
        Handles state transition to REMOVED and performs cleanup.
        """
        self.debug(f"on_expire called for {self.name} on {character.name}")
        
        # Let the base class handle state transition
        super().on_expire(character)
        
        # Mark as removed in state machine too
        self.state_machine.should_be_removed = True
        
        # Clear targets list
        self.targets = []
        
        # Mark for removal to ensure it gets deleted
        self.marked_for_removal = True
        
        # Create final message
        message = self.format_effect_message(f"{self.name} has been removed from {character.name}")
        
        return message
    
    def _add_expiry_feedback(self, character, message, round_number):
        """Helper method to add expiry messages to feedback system"""
        if hasattr(character, 'add_effect_feedback'):
            self.debug(f"Adding feedback message: {message}")
            character.add_effect_feedback(
                effect_name=self.name,
                expiry_message=message,
                round_expired=round_number,
                turn_expired=character.name
            )
        else:
            self.debug("Character does not support effect feedback")
    
    # Resource handling
    def apply_costs(self, character) -> List[str]:
        """Apply resource costs and return messages"""
        messages = []
        
        # Import dice roller here to avoid circular imports
        from utils.dice import DiceRoller
        
        # Apply MP cost
        if self.mp_cost:
            mp_cost = self.mp_cost
            mp_roll_message = None
            
            # Check if it's a dice expression or contains stat reference
            if isinstance(mp_cost, str) and (('d' in mp_cost.lower()) or any(stat in mp_cost.lower() for stat in ['str', 'dex', 'con', 'int', 'wis', 'cha'])):
                mp_roll, roll_desc = DiceRoller.roll_dice(mp_cost, character)
                mp_cost = mp_roll
                mp_roll_message = f"Rolled MP cost: {roll_desc}"
                self.debug(f"Rolled MP cost: {mp_cost} from {self.mp_cost}")
            
            # Handle MP gain or loss
            if mp_cost > 0:
                character.resources.current_mp = max(0, character.resources.current_mp - mp_cost)
                messages.append(f"Uses {mp_cost} MP")
                if mp_roll_message:
                    messages.append(mp_roll_message)
            else:
                character.resources.current_mp = min(
                    character.resources.max_mp, 
                    character.resources.current_mp - mp_cost  # Negative cost = gain
                )
                messages.append(f"Gains {abs(mp_cost)} MP")
                if mp_roll_message:
                    messages.append(mp_roll_message)
        
        # Apply HP cost with similar logic
        if self.hp_cost:
            hp_cost = self.hp_cost
            hp_roll_message = None
            
            # Check if it's a dice expression or contains stat reference
            if isinstance(hp_cost, str) and (('d' in hp_cost.lower()) or any(stat in hp_cost.lower() for stat in ['str', 'dex', 'con', 'int', 'wis', 'cha'])):
                hp_roll, roll_desc = DiceRoller.roll_dice(hp_cost, character)
                hp_cost = hp_roll
                hp_roll_message = f"Rolled HP cost: {roll_desc}"
                self.debug(f"Rolled HP cost: {hp_cost} from {self.hp_cost}")
            
            # Handle HP gain or loss
            if hp_cost > 0:
                character.resources.current_hp = max(0, character.resources.current_hp - hp_cost)
                messages.append(f"Uses {hp_cost} HP")
                if hp_roll_message:
                    messages.append(hp_roll_message)
            else:
                character.resources.current_hp = min(
                    character.resources.max_hp, 
                    character.resources.current_hp - hp_cost  # Negative cost = gain
                )
                messages.append(f"Heals {abs(hp_cost)} HP")
                if hp_roll_message:
                    messages.append(hp_roll_message)
        
        # Apply star cost consistently
        if self.star_cost and self.star_cost > 0:
            # Apply star cost if character has action_stars
            if hasattr(character, 'action_stars'):
                if hasattr(character.action_stars, 'use_stars'):
                    # Use the standard method that should handle all the tracking
                    character.action_stars.use_stars(self.star_cost, self.name)
                    self.debug(f"Applied star cost: {self.star_cost} for move: {self.name}")
                else:
                    # Fallback to simpler approach if use_stars is not available
                    if hasattr(character.action_stars, 'current_stars'):
                        character.action_stars.current_stars = max(0, character.action_stars.current_stars - self.star_cost)
                        self.debug(f"Applied star cost using direct attribute: {self.star_cost}")
                    
            messages.append(f"Uses {self.star_cost} Stars")
        
        return messages

    # Override the is_expired property to use the state machine's removal flag
    @property
    def is_expired(self) -> bool:
        """
        A move is expired when:
        1. It's marked for removal, OR
        2. It's an INSTANT effect that has been processed, OR
        3. The state machine indicates it should be removed (turns_remaining == -1)
        4. The parent class considers it expired
        """
        # Check parent class first
        if super().is_expired:
            self.debug(f"is_expired: True (from parent class)")
            return True
            
        # If explicitly marked for removal
        if self.marked_for_removal:
            self.debug(f"is_expired: True (marked for removal)")
            return True
            
        # INSTANT effects expire after processing
        if self.state_machine.state == MoveState.INSTANT:
            self.debug(f"is_expired: True (INSTANT state)")
            return True
            
        # If state machine says to remove
        if hasattr(self.state_machine, 'should_be_removed') and self.state_machine.should_be_removed:
            self.debug(f"is_expired: True (state machine says to remove)")
            return True
        
        # Otherwise, not expired
        self.debug(f"is_expired: False (state: {self.state.value}, remaining: {self.state_machine.get_remaining_turns()})")
        return False

    # Serialization methods
    def to_dict(self) -> dict:
        """Convert to dictionary for storage with state preservation"""
        data = super().to_dict()
        
        # Add state machine data
        data.update({
            "state_machine": self.state_machine.to_dict(),
            "star_cost": self.star_cost,
            "mp_cost": self.mp_cost,
            "hp_cost": self.hp_cost,
            "cast_description": self.cast_description,
            "uses": self.uses,
            "uses_remaining": self.uses_remaining,
            "attack_roll": self.attack_roll,
            "damage": self.damage, 
            "crit_range": self.crit_range,
            "conditions": [c.value if hasattr(c, 'value') else str(c) for c in self.conditions] if self.conditions else [],
            "roll_timing": self.roll_timing.value if hasattr(self.roll_timing, 'value') else "active",
            "targets_hit": list(self.combat.targets_hit) if hasattr(self.combat, 'targets_hit') else [],
            "targets_saved": list(self.saves.targets_saved) if hasattr(self.saves, 'targets_saved') else [],
            "aoe_mode": self.combat.aoe_mode if hasattr(self.combat, 'aoe_mode') else 'single',
            "bonus_on_hit": self.bonus_on_hit.to_dict() if hasattr(self.bonus_on_hit, 'to_dict') else None,
            "marked_for_removal": self.marked_for_removal,
            "last_roll_round": self.last_roll_round,
            "transition_count": getattr(self, 'transition_count', 0),
            # Store timing information
            "is_during_own_turn": self.is_during_own_turn,
            "displayed_duration": self.displayed_duration
        })
        
        # Remove None values to save space
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> Optional['MoveEffect']:
        """Create from dictionary data"""
        try:
            # Extract required and optional parameters
            name = data.get('name', 'Unknown Move')
            description = data.get('description', '')
            star_cost = data.get('star_cost', 0)
            
            # Handle mp_cost and hp_cost - preserve string expressions if present
            mp_cost = data.get('mp_cost', 0)
            hp_cost = data.get('hp_cost', 0)
            cast_description = data.get('cast_description')
            uses = data.get('uses')
            attack_roll = data.get('attack_roll')
            damage = data.get('damage')
            crit_range = data.get('crit_range', 20)
            conditions = data.get('conditions', [])
            roll_timing_str = data.get('roll_timing', RollTiming.ACTIVE.value)
            
            # Get bonus on hit data
            bonus_on_hit = data.get('bonus_on_hit')
            
            # Support old heat tracking parameter for backward compatibility
            if not bonus_on_hit and data.get('enable_heat_tracking', False):
                # Create a star bonus for backward compatibility
                bonus_on_hit = {'stars': 1}
            
            # Get state machine data
            sm_data = data.get('state_machine', {})
            cast_time = sm_data.get('cast_time')
            duration = sm_data.get('duration')
            cooldown = sm_data.get('cooldown')
            
            # Get AoE mode
            aoe_mode = data.get('aoe_mode', 'single')
            
            # Get roll modifier data
            roll_modifier = data.get('roll_modifier')
            
            # Get timing information
            is_during_own_turn = data.get('is_during_own_turn')
            
            # Create base effect
            effect = cls(
                name=name,
                description=description,
                star_cost=star_cost,
                mp_cost=mp_cost,
                hp_cost=hp_cost,
                cast_time=cast_time,
                duration=duration,
                cooldown=cooldown,
                cast_description=cast_description,
                attack_roll=attack_roll,
                damage=damage, 
                crit_range=crit_range,
                conditions=[ConditionType(c) if isinstance(c, str) else c for c in conditions] if conditions else [],
                roll_timing=roll_timing_str,
                uses=uses,
                bonus_on_hit=bonus_on_hit,
                aoe_mode=aoe_mode,
                roll_modifier=roll_modifier,
                force_during=is_during_own_turn
            )
            
            # Restore state machine if it exists
            if sm_data:
                effect.state_machine = MoveStateMachine.from_dict(sm_data)
            
            # Restore state
            if 'state' in data:
                effect.state = EffectState(data['state'])
                
            # Restore tracking variables
            effect.uses_remaining = data.get('uses_remaining')
            
            # Restore combat state
            if hasattr(effect, 'combat') and 'targets_hit' in data:
                effect.combat.targets_hit = set(data.get('targets_hit', []))
                effect.combat.aoe_mode = data.get('aoe_mode', 'single')
                
            # Restore save state if available
            if hasattr(effect, 'saves') and 'targets_saved' in data:
                effect.saves.targets_saved = set(data.get('targets_saved', []))
                
            # Restore timing information
            if 'timing_info' in data:
                from core.effects.base import EffectProcessTimingInfo
                effect.timing = EffectProcessTimingInfo(**data['timing_info'])
                
            # Restore other properties
            effect.marked_for_removal = data.get('marked_for_removal', False)
            effect.last_roll_round = data.get('last_roll_round')
            effect.transition_count = data.get('transition_count', 0)
            effect.displayed_duration = data.get('displayed_duration', effect.state_machine.duration or 0)
                
            # Set internal flags for duration adjustment
            if effect.timing and hasattr(effect.state_machine, 'used_during_own_turn'):
                effect.state_machine.used_during_own_turn = effect.timing.applied_during_own_turn
                effect.state_machine.duration_adjusted = data.get('duration_adjusted', False)
                
            return effect
                
        except Exception as e:
            logger.error(f"Error reconstructing MoveEffect: {str(e)}", exc_info=True)
            return None
            
    # Special method to retrieve async results 
    async def process_async_results(self) -> List[str]:
        """
        Process any stored async coroutines from the cache.
        
        This must be called after on_apply(), on_turn_start(),
        or on_turn_end() to get any attack messages.
        
        Returns messages generated from async operations.
        """
        messages = []
        
        # Process any attack coroutines
        if 'attack_coroutine' in self._internal_cache:
            try:
                self.debug(f"Processing async attack coroutine")
                attack_messages = await self._internal_cache['attack_coroutine']
                messages.extend(attack_messages)
                del self._internal_cache['attack_coroutine']
            except Exception as e:
                self.debug(f"Error processing attack coroutine: {str(e)}")
                
        # Process any save coroutines
        if 'save_coroutine' in self._internal_cache:
            try:
                self.debug(f"Processing async save coroutine")
                save_messages = await self._internal_cache['save_coroutine']
                messages.extend(save_messages)
                del self._internal_cache['save_coroutine']
            except Exception as e:
                self.debug(f"Error processing save coroutine: {str(e)}")
                
        return messages