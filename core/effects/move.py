"""
## src/core/effects/move.py

Move Effect System Implementation with Simplified State Machine

Key Features:
- Direct, predictable state tracking for moves
- Clear state transitions with proper timing
- Consistent turn counting
- Extensive debug logging
- Immediate attack roll processing for instant moves
- Support for saving throws with proper feedback

IMPLEMENTATION MANDATES:
- Always track absolute rounds for transition timing
- Simple state transitions on turn boundaries
- Clean separation between effect and combat processing
- Maintain sync/async boundaries for external calls
"""

from typing import Optional, List, Dict, Any, Tuple, Set
from enum import Enum, auto
import logging
import inspect
import time
import random

from core.effects.base import BaseEffect, EffectCategory, EffectTiming
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
    """
    def __init__(self, cast_time=None, duration=None, cooldown=None, debug_mode=True):
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
        self.was_just_activated = False  # Track if we just entered the active state
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
    
    def process_turn(self, round_number, turn_name) -> Tuple[bool, Optional[str]]:
        """
        Process a turn for this state machine.
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
        
        # Only instant state has no turns remaining
        if self.state == MoveState.INSTANT:
            return False, None
            
        # Decrement turns remaining
        self.debug_print(f"Processing turn from {self.turns_remaining} turns remaining")
        self.turns_remaining -= 1
        
        # Check for transition
        if self.turns_remaining <= 0:
            old_state = self.state
            message = None
            
            # Handle transitions based on current state
            if self.state == MoveState.CASTING:
                if self.duration and self.duration > 0:
                    self.state = MoveState.ACTIVE
                    self.turns_remaining = self.duration
                    message = "activates!"
                    self.was_just_activated = True  # Mark as just activated
                elif self.cooldown and self.cooldown > 0:
                    self.state = MoveState.COOLDOWN
                    self.turns_remaining = self.cooldown
                    message = "enters cooldown"
                else:
                    message = "completes"
                    
            elif self.state == MoveState.ACTIVE:
                if self.cooldown and self.cooldown > 0:
                    self.state = MoveState.COOLDOWN
                    self.turns_remaining = self.cooldown
                    message = "enters cooldown"
                else:
                    message = "wears off"
                    
            elif self.state == MoveState.COOLDOWN:
                message = "cooldown has ended"
                
            self.debug_print(f"Transition: {old_state.value} → {self.state.value} with message: {message}")
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
            "last_processed_turn": self.last_processed_turn
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

class CombatProcessor:
    """
    Handles attack rolls and damage calculations.
    
    This class encapsulates:
    - Attack roll processing
    - Target handling
    - Damage calculation
    - Hit tracking 
    
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
                           enable_hit_bonus=False,
                           hit_bonus_value=1) -> List[str]:
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

        # Process attack with all targets - this call is already awaitable
        self.debug_print(f"Processing attack with {attack_roll} against {len(targets)} targets")
        message, hit_results = await AttackCalculator.process_attack(params)
        messages.append(message)
        
        # Process hit tracking
        if hit_results:
            # Extract hit targets
            for target_name, hit_data in hit_results.items():
                if hit_data.get('hit', False):
                    self.targets_hit.add(target_name)
                    self.debug_print(f"Target hit: {target_name}")
        
        # Handle hit bonus tracking if enabled
        if enable_hit_bonus and self.targets_hit:
            # Calculate bonus based on hits, applying the custom value
            hit_count = len(self.targets_hit)
            if hit_count > 0:
                total_bonus = hit_count * hit_bonus_value
                bonus_message = f"🎯 `{source.name} gains {total_bonus} star bonus from {hit_count} successful hits!`"
                messages.append(bonus_message)
                
                # Access action stars if available and apply bonus
                if hasattr(source, 'action_stars') and hasattr(source.action_stars, 'add_bonus_stars'):
                    source.action_stars.add_bonus_stars(total_bonus)
                elif hasattr(source, 'action_stars') and hasattr(source.action_stars, 'add_stars'):
                    # Fallback to add_stars if add_bonus_stars doesn't exist
                    source.action_stars.add_stars(total_bonus)
        
        return messages

class MoveEffect(BaseEffect):
    """
    Handles move execution with simplified state tracking.
    
    This redesigned implementation provides:
    - Direct state transitions
    - Predictable turn counting
    - Proper resource handling
    - Immediate attack roll processing for instant moves
    - Support for saving throws
    - Hit bonus tracking (replacing heat tracking)
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
            save_type: Optional[str] = None,
            save_dc: Optional[str] = None,
            half_on_save: bool = False,
            conditions: Optional[List[ConditionType]] = None,
            roll_timing: str = "active",
            uses: Optional[int] = None,
            targets: Optional[List['Character']] = None,
            enable_hit_bonus: bool = False,
            enable_heat_tracking: bool = False,  # Added for backward compatibility
            hit_bonus_value: int = 1  # Added for customizing bonus amount
        ):
            # Create specialized state machine and processors
            self.debug_mode = True
            self.debug_id = f"MoveEffect-{int(time.time() * 1000) % 10000}"
            self.debug_print(f"Initializing {name}")
            
            self.state_machine = MoveStateMachine(cast_time, duration, cooldown, self.debug_mode)
            self.combat = CombatProcessor(self.debug_mode)
            self.saves = SavingThrowProcessor(self.debug_mode)
            
            # Set initial duration based on state machine
            initial_duration = self.state_machine.get_remaining_turns()
            if initial_duration <= 0:
                initial_duration = 1  # Minimum duration for INSTANT moves
            
            # Initialize base effect
            super().__init__(
                name=name,
                duration=initial_duration,
                permanent=False,
                category=EffectCategory.STATUS,
                description=description,
                handles_own_expiry=True
            )
            
            # Resource costs
            self.star_cost = star_cost
            self.mp_cost = mp_cost
            self.hp_cost = hp_cost
            
            # Usage tracking
            self.uses = uses
            self.uses_remaining = uses
            
            # Combat parameters
            self.attack_roll = attack_roll
            self.damage = damage
            self.crit_range = crit_range
            
            # Save parameters
            self.save_type = save_type
            self.save_dc = save_dc
            self.half_on_save = half_on_save
            self.conditions = conditions or []
            
            # Set roll timing
            if isinstance(roll_timing, str):
                try:
                    self.roll_timing = RollTiming(roll_timing)
                except ValueError:
                    self.roll_timing = RollTiming.ACTIVE
            else:
                self.roll_timing = roll_timing
            
            # Additional properties
            self.cast_description = cast_description
            self.targets = targets or []
            
            # Support both parameter names for backward compatibility
            self.enable_hit_bonus = enable_hit_bonus or enable_heat_tracking
            self.hit_bonus_value = hit_bonus_value
            
            # Configure combat settings
            self.combat.aoe_mode = 'single'
            
            # Tracking variables
            self.marked_for_removal = False
            self._internal_cache = {}  # Cache for async results
            self.last_roll_round = None  # Track when we last rolled
            
            self.debug_print(f"Initialized with state {self.state}")

    def debug_print(self, message):
        """Print debug messages if debug mode is enabled"""
        if self.debug_mode:
            print(f"[{self.debug_id}] {message}")

    # Property accessors for state
    @property
    def state(self) -> MoveState:
        """Current move state"""
        return self.state_machine.get_current_state()
    
    def get_emoji(self) -> str:
        """Get state-specific emoji"""
        return {
            MoveState.INSTANT: "⚡",
            MoveState.CASTING: "✨",
            MoveState.ACTIVE: "✨",
            MoveState.COOLDOWN: "⏳"
        }.get(self.state, "✨")

    def get_remaining_turns(self) -> int:
        """Get the number of turns remaining in the current phase"""
        return self.state_machine.get_remaining_turns()
    
    # Resource handling
    def apply_costs(self, character) -> List[str]:
        """Apply resource costs and return messages"""
        messages = []
        
        # Apply MP cost
        if self.mp_cost != 0:
            # Handle MP gain or loss
            if self.mp_cost > 0:
                character.resources.current_mp = max(0, character.resources.current_mp - self.mp_cost)
                messages.append(f"Uses {self.mp_cost} MP")
            else:
                character.resources.current_mp = min(
                    character.resources.max_mp, 
                    character.resources.current_mp - self.mp_cost  # Negative cost = gain
                )
                messages.append(f"Gains {abs(self.mp_cost)} MP")
        
        # Apply HP cost
        if self.hp_cost != 0:
            # Handle HP gain or loss
            if self.hp_cost > 0:
                character.resources.current_hp = max(0, character.resources.current_hp - self.hp_cost)
                messages.append(f"Uses {self.hp_cost} HP")
            else:
                character.resources.current_hp = min(
                    character.resources.max_hp, 
                    character.resources.current_hp - self.hp_cost  # Negative cost = gain
                )
                messages.append(f"Heals {abs(self.hp_cost)} HP")
        
        return messages

    def can_use(self, round_number: Optional[int] = None) -> tuple[bool, Optional[str]]:
        """
        Check if move can be used.
        Returns (can_use, reason) tuple.
        """
        # Check if currently in cooldown phase
        if self.state == MoveState.COOLDOWN:
            remaining = self.get_remaining_turns()
            return False, f"On cooldown ({remaining} turns remaining)"
        
        # Check uses if tracked
        if self.uses is not None:
            if self.uses_remaining is None:
                self.uses_remaining = self.uses
            if self.uses_remaining <= 0:
                return False, f"No uses remaining (0/{self.uses})"
        
        return True, None

    # Core logic for determining if actions should happen
    def should_roll_attack(self, state: MoveState, force_roll: bool = False) -> bool:
        """Determine if we should roll attack based on timing and state"""
        if force_roll:
            return True
            
        if self.roll_timing == RollTiming.INSTANT:
            return state == MoveState.INSTANT
        elif self.roll_timing == RollTiming.ACTIVE:
            return state == MoveState.ACTIVE
        elif self.roll_timing == RollTiming.PER_TURN:
            return state == MoveState.ACTIVE
            
        return False
        
    def should_process_save(self, state: MoveState, force_save: bool = False) -> bool:
        """Determine if we should process saving throw based on timing and state"""
        # Save checks follow same logic as attack rolls
        return self.should_roll_attack(state, force_save)
    
    # LIFECYCLE METHODS
    
    async def on_apply(self, character, round_number: int) -> str:
        """
        Initial effect application - synchronous interface.
        This method handles the async operations internally.
        
        For instant moves with attack rolls:
        - Processes attack rolls immediately
        - Includes results in the initial message
        
        For other moves:
        - Sets up the effect state
        - Returns appropriate status message
        """
        self.debug_print(f"on_apply called for {character.name} on round {round_number}")
        
        # Initialize timing
        self.initialize_timing(round_number, character.name)
        
        # Apply costs and format messages
        costs = []
        details = []
        timing_info = []
        attack_messages = []
        save_messages = []
        
        # Apply resource costs
        cost_messages = self.apply_costs(character)
        for msg in cost_messages:
            if "MP" in msg:
                costs.append(f"💙 MP: {self.mp_cost}")
            elif "HP" in msg and "Heal" not in msg:
                costs.append(f"❤️ HP: {self.hp_cost}")
            elif "Heal" in msg:
                costs.append(f"❤️ Heal: {abs(self.hp_cost)}")
        
        # Add star cost
        if self.star_cost > 0:
            costs.append(f"⭐ {self.star_cost}")
            
        # Add timing info based on state machine
        if self.state_machine.cast_time:
            timing_info.append(f"🔄 {self.state_machine.cast_time}T Cast")
        if self.state_machine.duration:
            timing_info.append(f"⏳ {self.state_machine.duration}T Duration")
        if self.state_machine.cooldown:
            timing_info.append(f"⌛ {self.state_machine.cooldown}T Cooldown")
            
        # Format target info if any
        if self.targets:
            target_names = ", ".join(t.name for t in self.targets)
            details.append(f"Target{'s' if len(self.targets) > 1 else ''}: {target_names}")
            
        # Process instant attack rolls immediately
        if self.attack_roll and self.roll_timing == RollTiming.INSTANT:
            self.debug_print(f"Processing instant attack roll")
            # Process attack immediately
            attack_results = await self.combat.process_attack(
                source=character,
                targets=self.targets,
                attack_roll=self.attack_roll,
                damage=self.damage,
                crit_range=self.crit_range,
                reason=self.name,
                enable_hit_bonus=self.enable_hit_bonus
            )
            if attack_results:
                attack_messages.extend(attack_results)
                
        # Process instant saving throws immediately
        if self.save_type and self.save_dc and self.roll_timing == RollTiming.INSTANT and self.targets:
            self.debug_print(f"Processing instant saving throw")
            # Process saving throw immediately
            save_results = await self.saves.process_save(
                source=character,
                targets=self.targets,
                save_type=self.save_type,
                save_dc=self.save_dc,
                effect_name=self.name,
                half_on_save=self.half_on_save,
                damage=self.damage if not self.attack_roll else None  # Only use damage if no attack roll
            )
            if save_results:
                save_messages.extend(save_results)
                    
        # Build the primary message
        if self.cast_description:
            main_message = f"{character.name} {self.cast_description} {self.name}"
        else:
            if self.state == MoveState.INSTANT:
                main_message = f"{character.name} uses {self.name}"
            elif self.state == MoveState.CASTING:
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
            
        # Format output
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
            
        # Add attack messages directly to the response for instant attacks
        if attack_messages:
            formatted_message += "\n" + "\n".join(attack_messages)
            
        # Add save messages directly to the response for instant saves
        if save_messages:
            formatted_message += "\n" + "\n".join(save_messages)
        
        # For instant moves with no follow-up needed, mark for removal
        if self.state == MoveState.INSTANT and not self.cooldown:
            self.marked_for_removal = True
        
        self.debug_print(f"on_apply complete, returning formatted message")
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

        self.debug_print(f"on_turn_start for {character.name} on round {round_number}")
        messages = []
        
        # Display message based on current state
        if self.state == MoveState.CASTING:
            remaining = self.get_remaining_turns()
            self.debug_print(f"Casting phase, {remaining} turns remaining")
            cast_msg = self.format_effect_message(
                f"Casting {self.name}",
                [f"{remaining} turn{'s' if remaining != 1 else ''} remaining"]
            )
            messages.append(cast_msg)
                
        elif self.state == MoveState.ACTIVE:
            # Special handling for when we first become active or per_turn effects
            just_activated = self.last_roll_round != round_number and self.roll_timing == RollTiming.ACTIVE
            is_per_turn = self.roll_timing == RollTiming.PER_TURN
            
            # Process attack if needed (PER_TURN or newly ACTIVE)
            if self.attack_roll and (is_per_turn or just_activated):
                self.debug_print(f"Processing turn start attack roll")
                self.last_roll_round = round_number
                
                # Process attack directly
                attack_results = await self.combat.process_attack(
                    source=character,
                    targets=self.targets,
                    attack_roll=self.attack_roll,
                    damage=self.damage,
                    crit_range=self.crit_range,
                    reason=self.name,
                    enable_hit_bonus=self.enable_hit_bonus
                )
                if attack_results:
                    messages.extend(attack_results)
            else:
                self.debug_print(f"Skipping attack roll - timing: {self.roll_timing.value}, last_roll_round: {self.last_roll_round}")
                
            # Process saves if needed (PER_TURN or newly ACTIVE)
            if self.save_type and self.save_dc and (is_per_turn or just_activated):
                self.debug_print(f"Processing turn start saving throw")
                
                # Process save directly
                save_results = await self.saves.process_save(
                    source=character,
                    targets=self.targets,
                    save_type=self.save_type,
                    save_dc=self.save_dc,
                    effect_name=self.name,
                    half_on_save=self.half_on_save,
                    damage=self.damage if not self.attack_roll else None  # Only use damage if no attack roll
                )
                if save_results:
                    messages.extend(save_results)
            
            # Show active message
            remaining = self.get_remaining_turns()
            details = []
            if self.description:
                if ';' in self.description:
                    for part in self.description.split(';'):
                        part = part.strip()
                        if part:
                            details.append(part)
                else:
                    details.append(self.description)
            
            details.append(f"{remaining} turn{'s' if remaining != 1 else ''} remaining")
            
            active_msg = self.format_effect_message(
                f"{self.name} active",
                details
            )
            # Only add status message if we don't already have combat results to show
            if not messages or (not any("attack" in msg.lower() for msg in messages) and 
                               not any("save" in msg.lower() for msg in messages)):
                messages.append(active_msg)
        
        elif self.state == MoveState.COOLDOWN:
            # Show cooldown status at turn start too
            remaining = self.get_remaining_turns()
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
        
        Provides:
        - Clear transition messages between states
        - Duration tracking for all phases
        - Proper cleanup handling
        """
        # Only process for effect owner
        if character.name != turn_name:
            return []
            
        self.debug_print(f"on_turn_end for {character.name} on round {round_number}")
        messages = []
        
        # Get pre-transition state for comparison
        old_state = self.state
        old_remaining = self.get_remaining_turns()
        
        # Process state machine transition
        did_transition, transition_msg = self.state_machine.process_turn(round_number, turn_name)
        
        # Handle non-transition updates (normal duration tracking)
        if not did_transition:
            # Show duration update for active and cooldown phases
            if self.state in [MoveState.ACTIVE, MoveState.COOLDOWN] and old_remaining > 0:
                remaining = self.get_remaining_turns()
                state_name = "active effect" if self.state == MoveState.ACTIVE else "cooldown"
                continue_msg = self.format_effect_message(
                    f"{self.name} {state_name} continues",
                    [f"{remaining} turn{'s' if remaining != 1 else ''} remaining"]
                )
                messages.append(continue_msg)
            # Show casting continuation
            elif self.state == MoveState.CASTING and old_remaining > 0:
                remaining = self.get_remaining_turns()
                cast_msg = self.format_effect_message(
                    f"Continuing to cast {self.name}",
                    [f"{remaining} turn{'s' if remaining != 1 else ''} remaining"]
                )
                messages.append(cast_msg)
        
        # Show transition message if needed - with enhanced formatting
        if did_transition and transition_msg:
            self.debug_print(f"State transition: {transition_msg}")
            
            # Format transition message based on new state
            if self.state == MoveState.ACTIVE:
                # Casting to Active transition
                msg = self.format_effect_message(
                    f"{self.name} {transition_msg}",
                    [
                        f"Cast time complete!",
                        f"Effect active for {self.get_remaining_turns()} turn{'s' if self.get_remaining_turns() != 1 else ''}"
                    ],
                    emoji="✨"
                )
            elif self.state == MoveState.COOLDOWN:
                # Active to Cooldown transition
                msg = self.format_effect_message(
                    f"{self.name} {transition_msg}",
                    [
                        f"Effect duration complete",
                        f"Cooldown: {self.get_remaining_turns()} turn{'s' if self.get_remaining_turns() != 1 else ''}"
                    ],
                    emoji="⏳"
                )
            elif transition_msg == "cooldown has ended":
                # Cooldown ended
                msg = self.format_effect_message(
                    f"{self.name} ready to use again",
                    ["Cooldown has ended"],
                    emoji="✅"
                )
                # Delay removal until next turn to ensure message is seen
                # self.marked_for_removal = True  # Commented out to delay removal
            else:
                # Generic transition
                msg = self.format_effect_message(f"{self.name} {transition_msg}")
                
            messages.append(msg)
            
            # Mark for removal if cooldown ended - now delayed until after message is shown
            if self.state == MoveState.COOLDOWN and transition_msg == "cooldown has ended":
                # Instead of immediately marking for removal, set a flag to remove next turn
                self.debug_print(f"Marking for removal due to cooldown end (delayed)")
                self._remove_after_cooldown_msg = True
                # self.marked_for_removal = True  # Commented out to delay removal
                
            # Or if active effect wore off with no cooldown
            elif self.state == MoveState.ACTIVE and transition_msg == "wears off":
                self.debug_print(f"Marking for removal due to active effect expiry")
                self.marked_for_removal = True
        
        # Check if we need to remove after showing cooldown message
        if hasattr(self, '_remove_after_cooldown_msg') and self._remove_after_cooldown_msg:
            self.marked_for_removal = True
            self._remove_after_cooldown_msg = False
        
        return messages

    @property
    def is_expired(self) -> bool:
        """
        A move is expired when:
        1. It's marked for removal, OR
        2. It's an INSTANT effect that has been processed, OR
        3. It's in COOLDOWN phase and has completed the full cooldown
        """
        # If explicitly marked for removal
        if self.marked_for_removal:
            self.debug_print(f"is_expired: True (marked for removal)")
            return True
            
        # INSTANT effects expire after processing
        if self.state == MoveState.INSTANT:
            self.debug_print(f"is_expired: True (INSTANT state)")
            return True
            
        # Move has no remaining turns and is in final state
        if (self.state == MoveState.COOLDOWN and 
            self.get_remaining_turns() <= 0):
            self.debug_print(f"is_expired: True (COOLDOWN complete)")
            return True
            
        # Move has no remaining turns, not in cooldown, and has no cooldown parameter
        if (self.state == MoveState.ACTIVE and 
            self.get_remaining_turns() <= 0 and 
            not self.state_machine.cooldown):
            self.debug_print(f"is_expired: True (ACTIVE complete, no cooldown)")
            return True
        
        # Otherwise, not expired
        self.debug_print(f"is_expired: False (state: {self.state.value}, remaining: {self.get_remaining_turns()})")
        return False

    def on_expire(self, character) -> str:
        """Handle move expiry and ensure complete removal"""
        self.debug_print(f"on_expire for {character.name}")
        
        if self.state == MoveState.INSTANT:
            return None
            
        # Clear targets list
        self.targets = []
        
        # Mark for removal to ensure it gets deleted
        self.marked_for_removal = True
        
        # Set duration to 0 to ensure it gets removed
        if hasattr(self, 'timing'):
            self.timing.duration = 0
            
        return self.format_effect_message(f"{self.name} has ended")
    
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
            "save_type": self.save_type,
            "save_dc": self.save_dc,
            "half_on_save": self.half_on_save,
            "conditions": [c.value if hasattr(c, 'value') else str(c) for c in self.conditions] if self.conditions else [],
            "roll_timing": self.roll_timing.value,
            "targets_hit": list(self.combat.targets_hit),
            "targets_saved": list(self.saves.targets_saved) if hasattr(self.saves, 'targets_saved') else [],
            "aoe_mode": self.combat.aoe_mode,
            "enable_hit_bonus": self.enable_hit_bonus,
            "marked_for_removal": self.marked_for_removal,
            "last_roll_round": self.last_roll_round
        })
        
        # Remove None values to save space
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> 'MoveEffect':
        """Create from dictionary data"""
        try:
            # Extract required and optional parameters
            name = data.get('name', 'Unknown Move')
            description = data.get('description', '')
            star_cost = data.get('star_cost', 0)
            mp_cost = data.get('mp_cost', 0)
            hp_cost = data.get('hp_cost', 0)
            cast_description = data.get('cast_description')
            uses = data.get('uses')
            attack_roll = data.get('attack_roll')
            damage = data.get('damage')
            crit_range = data.get('crit_range', 20)
            save_type = data.get('save_type')
            save_dc = data.get('save_dc')
            half_on_save = data.get('half_on_save', False)
            conditions = data.get('conditions', [])
            roll_timing_str = data.get('roll_timing', RollTiming.ACTIVE.value)
            enable_hit_bonus = data.get('enable_hit_bonus', False) or data.get('enable_heat_tracking', False)
            
            # Get state machine data
            sm_data = data.get('state_machine', {})
            cast_time = sm_data.get('cast_time')
            duration = sm_data.get('duration')
            cooldown = sm_data.get('cooldown')
            
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
                save_type=save_type,
                save_dc=save_dc,
                half_on_save=half_on_save,
                conditions=[ConditionType(c) if isinstance(c, str) else c for c in conditions] if conditions else [],
                roll_timing=roll_timing_str,
                uses=uses,
                enable_hit_bonus=enable_hit_bonus
            )
            
            # Restore state machine if it exists
            if sm_data:
                effect.state_machine = MoveStateMachine.from_dict(sm_data)
            
            # Restore usage tracking
            effect.uses_remaining = data.get('uses_remaining')
            
            # Restore combat state
            effect.combat.targets_hit = set(data.get('targets_hit', []))
            effect.combat.aoe_mode = data.get('aoe_mode', 'single')
            
            # Restore save state if available
            if hasattr(effect, 'saves') and 'targets_saved' in data:
                effect.saves.targets_saved = set(data.get('targets_saved', []))
            
            # Restore timing information
            if timing_data := data.get('timing'):
                effect.timing = EffectTiming(**timing_data)
                
            effect.last_roll_round = data.get('last_roll_round')
            effect.marked_for_removal = data.get('marked_for_removal', False)
                
            return effect
            
        except Exception as e:
            print(f"Error reconstructing MoveEffect: {str(e)}")
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
                self.debug_print(f"Processing async attack coroutine")
                attack_messages = await self._internal_cache['attack_coroutine']
                messages.extend(attack_messages)
                del self._internal_cache['attack_coroutine']
            except Exception as e:
                self.debug_print(f"Error processing attack coroutine: {str(e)}")
                
        # Process any save coroutines
        if 'save_coroutine' in self._internal_cache:
            try:
                self.debug_print(f"Processing async save coroutine")
                save_messages = await self._internal_cache['save_coroutine']
                messages.extend(save_messages)
                del self._internal_cache['save_coroutine']
            except Exception as e:
                self.debug_print(f"Error processing save coroutine: {str(e)}")
                
        return messages