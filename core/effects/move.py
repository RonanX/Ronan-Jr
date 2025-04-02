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
        self.was_just_activated = False    # Track if we just entered the active state
        self.should_be_removed = False     # Flag to indicate removal is needed
        self.transition_message = None     # Store the last transition message
        
        # FIX: Track whether this move was used during the character's own turn
        self.used_during_own_turn = False
        # FIX: Track internal duration adjustments
        self.duration_adjusted = False
        
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
        Process a turn for this state machine with fixed transition logic.
        Returns (did_transition, transition_message)
        
        FIX: Fixed transition logic between phases
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
        
        # FIX: Handle the case where turns_remaining is negative
        # This means the effect should be removed after this turn
        if self.turns_remaining < 0:
            self.debug_print("Turns remaining < 0, marking for removal")
            self.should_be_removed = True
            # Return True to indicate a transition occurred (final transition)
            return True, "final removal"
        
        # Check for transition between phases (when turns_remaining becomes 0)
        if self.turns_remaining == 0:
            old_state = self.state
            message = None
            
            # FIX: Properly handle transitions between states
            if self.state == MoveState.CASTING:
                # After casting, go to ACTIVE if there's duration, or COOLDOWN if not
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
            # FIX: Save the adjusted duration tracking
            "used_during_own_turn": self.used_during_own_turn,
            "duration_adjusted": self.duration_adjusted
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
        # FIX: Load the duration adjustment tracking
        sm.used_during_own_turn = data.get('used_during_own_turn', False)
        sm.duration_adjusted = data.get('duration_adjusted', False)
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
    Handles move execution with simplified state tracking.
    
    This redesigned implementation provides:
    - Direct state transitions
    - Predictable turn counting
    - Proper resource handling
    - Improved multihit support
    - Bonus on hit tracking
    - Automatic roll timing detection
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
        roll_modifier: Optional[Dict[str, Any]] = None  # Roll modifier to apply
    ):
        # Create specialized state machine and processors
        self.debug_mode = True
        self.debug_id = f"MoveEffect-{int(time.time() * 1000) % 10000}"
        self.debug_print(f"Initializing {name}")
        
        # Ensure cooldown is None if it's 0 or less
        if cooldown is not None and cooldown <= 0:
            cooldown = None
            
        # Create state machine with validated parameters
        self.state_machine = MoveStateMachine(
            cast_time=cast_time if cast_time and cast_time > 0 else None,
            duration=duration if duration and duration > 0 else None,
            cooldown=cooldown,
            debug_mode=self.debug_mode
        )
        
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
        
        # Set conditions
        self.conditions = conditions or []
        
        # Determine roll timing automatically if needed
        self.determine_roll_timing(roll_timing)
        
        # Additional properties
        self.cast_description = cast_description
        self.targets = targets or []
        
        # Initialize bonus on hit
        # Convert legacy heat tracking to bonus_on_hit if needed
        if bonus_on_hit is None and (enable_heat_tracking or enable_hit_bonus):
            self.debug_print(f"Converting legacy heat tracking to bonus_on_hit")
            bonus_on_hit = {'stars': 1}
        
        # Ensure bonus_on_hit is properly initialized
        self.debug_print(f"Original bonus_on_hit: {bonus_on_hit}")
        
        # Special handling for bonus_on_hit parameter
        if bonus_on_hit is not None:
            # Print the raw value for debugging
            self.debug_print(f"Raw bonus_on_hit value: {bonus_on_hit}")
            
            # Handle string values (common in Discord commands)
            if isinstance(bonus_on_hit, str):
                try:
                    import json
                    # Try to parse as JSON
                    parsed_bonus = json.loads(bonus_on_hit)
                    self.debug_print(f"Parsed bonus_on_hit from JSON: {parsed_bonus}")
                    bonus_on_hit = parsed_bonus
                except:
                    # If parsing fails, use a default value
                    self.debug_print(f"Failed to parse bonus_on_hit from string, using default")
                    bonus_on_hit = {'stars': 1}
        
        self.debug_print(f"Final bonus_on_hit: {bonus_on_hit}")
        self.bonus_on_hit = BonusOnHit.from_dict(bonus_on_hit)
        
        # Initialize roll modifier if provided
        self.roll_modifier_data = roll_modifier
        self.roll_modifier_effect = None

        # Apply roll modifier if specified
        if roll_modifier:
            self.debug_print(f"Processing roll modifier data: {roll_modifier}")
            
            # Expected format: {"type": "bonus|advantage|disadvantage", "value": int, "next_roll": bool}
            mod_type = roll_modifier.get("type", "bonus").lower()
            mod_value = roll_modifier.get("value", 1)
            next_roll_only = roll_modifier.get("next_roll", False)
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
                next_roll_only=next_roll_only,
                duration=None if next_roll_only else duration,
                permanent=False,
                description=f"From {name}"
            )
        
        # Configure combat settings
        self.combat.aoe_mode = aoe_mode
        
        # Tracking variables
        self.marked_for_removal = False
        self._internal_cache = {}  # Cache for async results
        self.last_roll_round = None  # Track when we last rolled
        
        # FIX: Add a transition counter to track how many times we've transitioned
        # This helps prevent infinite transition chains
        self.transition_count = 0
        
        # FIX: Add tracking for turn-based application and duration
        self.applied_during_own_turn = False
        self.displayed_duration = initial_duration  # For user-facing display
        
        self.debug_print(f"Initialized with state {self.state}")

    def debug_print(self, message):
        """Print debug messages if debug mode is enabled"""
        if self.debug_mode:
            print(f"[{self.debug_id}] {message}")
    
    def determine_roll_timing(self, roll_timing_str):
        """
        Determine roll timing based on input and move parameters.
        
        If a move has attack_roll and no cast_time, default to INSTANT.
        This improves user experience by showing attack results immediately.
        """
        # Try to parse provided roll timing
        try:
            self.roll_timing = RollTiming(roll_timing_str)
        except (ValueError, TypeError):
            # Default to ACTIVE if invalid
            self.roll_timing = RollTiming.ACTIVE
        
        # Auto-detect instant attacks based on configuration
        if (self.attack_roll and 
            not self.state_machine.cast_time and 
            self.roll_timing == RollTiming.ACTIVE):
            # If a move has an attack roll and no cast time, make it INSTANT by default
            # unless explicitly specified as something else
            self.roll_timing = RollTiming.INSTANT
            self.debug_print(f"Auto-detected INSTANT roll timing for attack roll")

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
                self.debug_print(f"Rolled MP cost: {mp_cost} from {self.mp_cost}")
            
            # Handle MP gain or loss
            if mp_cost > 0:
                # MP cost (using mana)
                character.resources.current_mp = max(0, character.resources.current_mp - mp_cost)
                messages.append(f"Uses {mp_cost} MP")
                if mp_roll_message:
                    messages.append(mp_roll_message)
            else:
                # MP gain (regenerating mana)
                character.resources.current_mp = min(
                    character.resources.max_mp, 
                    character.resources.current_mp - mp_cost  # Negative cost = gain
                )
                messages.append(f"Gains {abs(mp_cost)} MP")
                if mp_roll_message:
                    messages.append(mp_roll_message)
        
        # Apply HP cost (similar stat enhancement)
        if self.hp_cost:
            hp_cost = self.hp_cost
            hp_roll_message = None
            
            # Check if it's a dice expression or contains stat reference
            if isinstance(hp_cost, str) and (('d' in hp_cost.lower()) or any(stat in hp_cost.lower() for stat in ['str', 'dex', 'con', 'int', 'wis', 'cha'])):
                hp_roll, roll_desc = DiceRoller.roll_dice(hp_cost, character)
                hp_cost = hp_roll
                hp_roll_message = f"Rolled HP cost: {roll_desc}"
                self.debug_print(f"Rolled HP cost: {hp_cost} from {self.hp_cost}")
            
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
        
        # FIX: Apply star cost consistently
        if self.star_cost and self.star_cost > 0:
            # Apply star cost if character has action_stars
            if hasattr(character, 'action_stars'):
                if hasattr(character.action_stars, 'use_stars'):
                    # Use the standard method that should handle all the tracking
                    character.action_stars.use_stars(self.star_cost, self.name)
                    self.debug_print(f"Applied star cost: {self.star_cost} for move: {self.name}")
                else:
                    # Fallback to simpler approach if use_stars is not available
                    if hasattr(character.action_stars, 'current_stars'):
                        character.action_stars.current_stars = max(0, character.action_stars.current_stars - self.star_cost)
                        self.debug_print(f"Applied star cost using direct attribute: {self.star_cost}")
                    
            messages.append(f"Uses {self.star_cost} Stars")
        
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
    
    # LIFECYCLE METHODS
    
    async def on_apply(self, character, round_number: int) -> str:
        """
        Initial effect application with turn-based duration adjustment.
        
        FIX: Added special handling for moves used during character's own turn
        """
        self.debug_print(f"on_apply called for {character.name} on round {round_number}")
        
        # Initialize timing
        self.initialize_timing(round_number, character.name)
        
        # FIX: Check if this move is being used during character's own turn
        self.applied_during_own_turn = False
        # Check if we're in combat with an initiative tracker
        if hasattr(character, 'game_state') and hasattr(character.game_state, 'initiative_tracker'):
            tracker = character.game_state.initiative_tracker
            if tracker.state != "inactive":  # Check if combat is active
                # Check if it's this character's turn
                if (hasattr(tracker, 'current_turn') and tracker.current_turn and 
                    tracker.current_turn.character_name == character.name):
                    self.debug_print(f"Move used during character's own turn")
                    self.applied_during_own_turn = True
                    self.state_machine.used_during_own_turn = True
                    
                    # If we have an active phase or will transition to active, adjust duration
                    if self.state == MoveState.ACTIVE and self.state_machine.duration:
                        # Add 1 to internal turns_remaining but keep display duration the same
                        self.state_machine.turns_remaining += 1
                        self.displayed_duration = self.state_machine.duration  # Original value
                        self.state_machine.duration_adjusted = True
                        self.debug_print(f"Adjusted internal duration: +1 (now {self.state_machine.turns_remaining}) but displayed as {self.displayed_duration}")
                    elif self.state == MoveState.CASTING and self.state_machine.duration:
                        # Mark for later adjustment when move becomes active
                        self.state_machine.duration_adjusted = True
                        self.debug_print(f"Marked for duration adjustment when active")
        
        # Apply costs and format messages
        details = []
        timing_info = []
        attack_messages = []
        bonus_messages = []
        
        # Apply resource costs and collect messages
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
        
        # Add resource status info (but don't duplicate the cost values)
        resource_updates = []
        if self.mp_cost != 0:
            resource_updates.append(f"MP: {character.resources.current_mp}/{character.resources.max_mp}")
        
        if self.hp_cost != 0:
            resource_updates.append(f"HP: {character.resources.current_hp}/{character.resources.max_hp}")
        
        # Add star status info
        if self.star_cost > 0 and hasattr(character, 'action_stars'):
            if hasattr(character.action_stars, 'current_stars') and hasattr(character.action_stars, 'max_stars'):
                resource_updates.append(f"Stars: {character.action_stars.current_stars}/{character.action_stars.max_stars}")
        
        # Add timing info based on state machine
        if self.state_machine.cast_time:
            timing_info.append(f"🔄 {self.state_machine.cast_time}T Cast")
        
        # FIX: Use displayed_duration for messaging if it was adjusted
        if self.state_machine.duration:
            # If a move is used during a character's turn, we internally adjust duration 
            # but still display the original value to the user
            display_duration = self.displayed_duration if self.applied_during_own_turn else self.state_machine.duration
            timing_info.append(f"⏳ {display_duration}T Duration")
            
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
            self.debug_print(f"Processing instant attack roll")
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
            
        # Format info
        if info_parts:
            main_message = f"{main_message} | {' | '.join(info_parts)}"
            
        # Add resource updates - ONLY if they contain different info than costs
        if resource_updates:
            main_message = f"{main_message} | {' | '.join(resource_updates)}"
            
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
                    msg += f" for {self.roll_modifier_effect.duration} turns"
                    
                formatted_message += f"\n• `{msg}`"
            
        # Add attack messages directly to the response for instant attacks
        if attack_messages:
            formatted_message += "\n" + "\n".join(attack_messages)
            
        # Add bonus messages after attack messages
        if bonus_messages:
            formatted_message += "\n" + "\n".join(bonus_messages)
        
        # For instant moves with no follow-up needed, mark for removal
        if self.state == MoveState.INSTANT and self.state_machine.cooldown is None:
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
            # FIX: Check if we need to adjust duration when moving from CASTING to ACTIVE
            if (self.state_machine.used_during_own_turn and 
                self.state_machine.duration_adjusted and
                self.state_machine.was_just_activated):
                self.debug_print(f"Adding +1 to duration after transitioning to active state")
                self.state_machine.turns_remaining += 1
                self.displayed_duration = self.state_machine.duration  # Original value
                self.state_machine.duration_adjusted = True
                
            # Special handling for when we first become active or per_turn effects
            just_activated = self.last_roll_round != round_number and self.roll_timing == RollTiming.ACTIVE
            is_per_turn = self.roll_timing == RollTiming.PER_TURN
            
            # Process attack if needed (PER_TURN or newly ACTIVE)
            if self.attack_roll and (is_per_turn or just_activated):
                self.debug_print(f"Processing turn start attack roll")
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
                self.debug_print(f"Skipping attack roll - timing: {self.roll_timing.value}, last_roll_round: {self.last_roll_round}")
            
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
            
            # FIX: Use displayed_duration for consistent user-facing info
            if self.applied_during_own_turn and self.state_machine.duration_adjusted:
                # Find out how many display turns remain
                display_remaining = max(0, remaining - 1)
                details.append(f"{display_remaining} turn{'s' if display_remaining != 1 else ''} remaining")
                self.debug_print(f"Showing {display_remaining} turns remaining (internal: {remaining})")
            else:
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
        
        FIX: Improved handling for state transitions and expiry
        """
        # Only process for effect owner
        if character.name != turn_name:
            return []
            
        self.debug_print(f"on_turn_end for {character.name} on round {round_number}")
        messages = []
        
        # Get pre-transition state for comparison
        old_state = self.state
        old_remaining = self.get_remaining_turns()
        
        # FIX: Check if already marked for removal
        if self.marked_for_removal or self.state_machine.should_be_removed:
            self.debug_print(f"Effect already marked for removal, skipping further processing")
            # FIX: Add to feedback system with proper expiry message
            expiry_msg = self.format_effect_message(
                f"{self.name} has worn off from {character.name}"
            )
            self._add_expiry_feedback(character, expiry_msg, round_number)
            return []
        
        # Check transition count to prevent infinite transitions
        if self.transition_count > 10:  # Set a reasonable limit
            self.debug_print(f"Too many transitions detected ({self.transition_count}), forcing removal")
            self.marked_for_removal = True
            return []
        
        # Process state machine transition
        did_transition, transition_msg = self.state_machine.process_turn(round_number, turn_name)
        
        # Check if the state machine now indicates removal
        if self.state_machine.should_be_removed:
            self.debug_print(f"State machine indicates removal is needed after transition")
            self.marked_for_removal = True
            
            # FIX: Add a proper expiry message that will show up in the effect update
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
            return messages
        
        # Handle non-transition updates (normal duration tracking)
        if not did_transition:
            # Show duration update for active and cooldown phases
            if self.state in [MoveState.ACTIVE, MoveState.COOLDOWN] and old_remaining > 0:
                remaining = self.get_remaining_turns()
                
                # FIX: Handle display remaining turns differently based on whether 
                # the move was used during the character's own turn
                if self.applied_during_own_turn and self.state == MoveState.ACTIVE and self.state_machine.duration_adjusted:
                    # The real remaining turns is one more than what we show
                    display_remaining = max(0, remaining - 1)
                    continue_msg = self.format_effect_message(
                        f"{self.name} continues",
                        [f"{display_remaining} turn{'s' if display_remaining != 1 else ''} remaining"]
                    )
                    self.debug_print(f"Showing {display_remaining} turns remaining (internal: {remaining})")
                else:
                    # Normal display of remaining turns
                    continue_msg = self.format_effect_message(
                        f"{self.name} continues",
                        [f"{remaining} turn{'s' if remaining != 1 else ''} remaining"]
                    )
                messages.append(continue_msg)
                
            # Show casting continuation
            elif self.state == MoveState.CASTING and old_remaining > 0:
                remaining = self.get_remaining_turns()
                cast_msg = self.format_effect_message(
                    f"Casting {self.name}",
                    [f"{remaining} turn{'s' if remaining != 1 else ''} remaining"]
                )
                messages.append(cast_msg)
        
        # Show transition message if needed - with enhanced formatting
        if did_transition and transition_msg:
            self.debug_print(f"State transition: {transition_msg}")
            self.transition_count += 1
            
            # Format transition message based on new state
            if self.state == MoveState.ACTIVE:
                # Casting to Active transition
                # FIX: For moves used during character's own turn, duration needs adjustment
                if self.applied_during_own_turn and self.state_machine.duration_adjusted:
                    display_duration = self.displayed_duration
                    self.debug_print(f"Showing {display_duration} display duration (internal: {self.state_machine.duration}) for transition to active")
                else:
                    display_duration = self.get_remaining_turns()
                
                msg = self.format_effect_message(
                    f"{self.name} {transition_msg}",
                    [
                        f"Cast time complete!",
                        f"Effect active for {display_duration} turn{'s' if display_duration != 1 else ''}"
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
                    f"{self.name} cooldown has ended",
                    ["Ready to use again"],
                    emoji="✅"
                )
                # FIX: Mark for removal at the end of cooldown
                self.marked_for_removal = True
            elif transition_msg == "wears off" or transition_msg == "final removal":
                # Effect wears off (no further phases)
                msg = self.format_effect_message(
                    f"{self.name} wears off",
                    ["Effect has ended"],
                    emoji="✨"
                )
                # FIX: Mark for removal when wearing off
                self.marked_for_removal = True
            else:
                # Generic transition
                msg = self.format_effect_message(f"{self.name} {transition_msg}")
                
            messages.append(msg)
            
            # FIX: Add to feedback system if this is a final transition
            if self.marked_for_removal:
                self.debug_print(f"Adding to feedback system for final transition")
                self._add_expiry_feedback(character, msg, round_number)
        
        return messages

    # Override the is_expired property to use the state machine's removal flag
    @property
    def is_expired(self) -> bool:
        """
        A move is expired when:
        1. It's marked for removal, OR
        2. It's an INSTANT effect that has been processed, OR
        3. The state machine indicates it should be removed (turns_remaining == -1)
        """
        # If explicitly marked for removal
        if self.marked_for_removal:
            self.debug_print(f"is_expired: True (marked for removal)")
            return True
            
        # INSTANT effects expire after processing
        if self.state == MoveState.INSTANT:
            self.debug_print(f"is_expired: True (INSTANT state)")
            return True
            
        # If state machine says to remove
        if hasattr(self.state_machine, 'should_be_removed') and self.state_machine.should_be_removed:
            self.debug_print(f"is_expired: True (state machine says to remove)")
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
        
        # Set should_be_removed to True in the state machine too
        self.state_machine.should_be_removed = True
        
        # FIX: Set duration to 0 to ensure it gets removed
        if hasattr(self, 'timing'):
            self.timing.duration = 0
            
        # FIX: Add consistent expiry message format
        message = self.format_effect_message(f"{self.name} has worn off from {character.name}")
        
        # FIX: Add final turn with turn remaining = -1 to state machine
        # This ensures proper transition through the states
        self.state_machine.turns_remaining = -1
        
        return message
    
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
            "roll_timing": self.roll_timing.value,
            "targets_hit": list(self.combat.targets_hit),
            "targets_saved": list(self.saves.targets_saved) if hasattr(self.saves, 'targets_saved') else [],
            "aoe_mode": self.combat.aoe_mode,
            "bonus_on_hit": self.bonus_on_hit.to_dict() if hasattr(self.bonus_on_hit, 'to_dict') else None,
            "marked_for_removal": self.marked_for_removal,
            "last_roll_round": self.last_roll_round,
            "transition_count": getattr(self, 'transition_count', 0),  # Track transition count
            # FIX: Save turn-based duration adjustment tracking
            "applied_during_own_turn": self.applied_during_own_turn,
            "displayed_duration": self.displayed_duration
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
                aoe_mode=aoe_mode
            )
            
            # Restore state machine if it exists
            if sm_data:
                effect.state_machine = MoveStateMachine.from_dict(sm_data)
            
            # Restore usage tracking
            effect.uses_remaining = data.get('uses_remaining')
            
            # Restore combat state
            effect.combat.targets_hit = set(data.get('targets_hit', []))
            effect.combat.aoe_mode = aoe_mode
            
            # Restore save state if available
            if hasattr(effect, 'saves') and 'targets_saved' in data:
                effect.saves.targets_saved = set(data.get('targets_saved', []))
                
            # Restore timing information
            if timing_data := data.get('timing'):
                effect.timing = EffectTiming(**timing_data)
                
            # FIX: Restore marked_for_removal flag
            effect.marked_for_removal = data.get('marked_for_removal', False)
            
            # FIX: Restore transition count
            effect.transition_count = data.get('transition_count', 0)
                
            effect.last_roll_round = data.get('last_roll_round')
                
            # FIX: Restore turn-based duration adjustment tracking
            effect.applied_during_own_turn = data.get('applied_during_own_turn', False)
            effect.displayed_duration = data.get('displayed_duration', effect.state_machine.duration or 0)
                
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