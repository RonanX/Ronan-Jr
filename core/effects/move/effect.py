"""
Core implementation of the MoveEffect class with PROPER timing logic per user specification.

YOUR EXACT LOGIC IMPLEMENTED:
1. Turn START: Decrements duration, shows status, handles attacks
2. Turn END: Only removes expired effects and shows cleanup messages
3. Duration 1 during own turn: Won't decrement until NEXT turn start, then marks for expiry
4. Applied not during turn: Decrements normally next time around
5. NO MORE force_during parameter needed - timing is built-in and consistent
"""

import logging
from typing import Optional, List, Dict, Any, Set, Union, Tuple

from core.effects.base import BaseEffect, EffectCategory, EffectState
from core.effects.rollmod import RollModifierType, RollModifierEffect
from core.effects.condition import ConditionType

# Import phase system and processors
from .state import MoveState, MoveStateMachine, RollTiming
from .base import MovePhase
from .combat import CombatProcessor, BonusOnHit
from .saves import SavingThrowProcessor

logger = logging.getLogger(__name__)

class ProperMoveEffectTiming:
    """
    PROPER timing system implementing user's exact specification:
    
    - Turn START: Decrements and processes
    - Turn END: Only cleanup and removal
    - Duration 1 during own turn: Waits one turn, then marks for expiry at next start
    - Applied not during: Normal decrement next time around
    - Built-in logic eliminates need for force_during
    """
    
    def __init__(self, 
                 cast_time: Optional[int] = None,
                 duration: Optional[int] = None, 
                 cooldown: Optional[int] = None,
                 debug_mode: bool = True):
        """Initialize proper timing"""
        self.debug_mode = debug_mode
        self.debug_id = f"ProperTiming-{id(self) % 10000}"
        
        # Store base durations
        self.cast_time = cast_time
        self.duration = duration
        self.cooldown = cooldown
        
        # Current state
        if cast_time and cast_time > 0:
            self.current_phase = MovePhase.CASTING
            self.turns_remaining = cast_time
        elif duration and duration > 0:
            self.current_phase = MovePhase.ACTIVE
            self.turns_remaining = duration
        elif cooldown and cooldown > 0:
            self.current_phase = MovePhase.COOLDOWN
            self.turns_remaining = cooldown
        else:
            self.current_phase = MovePhase.INSTANT
            self.turns_remaining = 0
            
        # Tracking
        self.should_be_removed = False
        self.marked_for_expiry = False  # NEW: Separate from removal
        self.last_processed_round = None
        self.last_processed_turn = None
        self.just_transitioned = False
        
        # Applied during own turn tracking (automatic detection)
        self.applied_during_own_turn = None  # Will be set on first processing
        self.first_turn_processed = False
        
        self.debug(f"Created with phase={self.current_phase.value}, turns={self.turns_remaining}")
    
    def debug(self, message):
        """Print debug message if debug mode is enabled"""
        if self.debug_mode:
            logger.info(f"[{self.debug_id}] {message}")
    
    def get_current_phase(self) -> MovePhase:
        """Get the current phase"""
        return self.current_phase
    
    def get_remaining_turns(self) -> int:
        """Get remaining turns in current phase"""
        return max(0, self.turns_remaining)
    
    def is_final_turn(self) -> bool:
        """Check if this is the final turn of the current phase"""
        return self.turns_remaining == 1
    
    def detect_timing_context(self, character_name: str, turn_name: str) -> bool:
        """
        Auto-detect if effect was applied during character's own turn.
        Only needs to be done once on first processing.
        """
        if self.applied_during_own_turn is not None:
            return self.applied_during_own_turn  # Already detected
            
        # Detect based on current context
        is_during = (character_name == turn_name)
        self.applied_during_own_turn = is_during
        
        self.debug(f"Auto-detected timing: applied_during_own_turn={is_during} (char={character_name}, turn={turn_name})")
        return is_during
    
    def process_turn_start(self, round_number, turn_name, character_name) -> Tuple[bool, Optional[str]]:
        """
        Process turn START - This is where ALL duration logic happens.
        
        YOUR LOGIC:
        - Duration decrements here 
        - Duration 1 during own turn: Won't decrement until NEXT turn start
        - Then marks for expiry (not removal yet)
        
        Returns:
            (did_transition, transition_message)
        """
        # Skip if not this character's turn
        if character_name != turn_name:
            return False, None
            
        # Skip if already processed this turn
        if (self.last_processed_round == round_number and 
            self.last_processed_turn == turn_name):
            self.debug(f"Already processed turn start R{round_number}, T{turn_name}")
            return False, None
            
        # Mark as processed
        self.last_processed_round = round_number
        self.last_processed_turn = turn_name
        
        # Auto-detect timing context on first processing
        is_during = self.detect_timing_context(character_name, turn_name)
        
        # Reset transition flag
        self.just_transitioned = False
        
        # Handle INSTANT phase
        if self.current_phase == MovePhase.INSTANT:
            self.should_be_removed = True
            self.debug("Instant effect marked for removal")
            return True, "completes"
        
        # SPECIAL CASE: Duration 1 during own turn on first processing
        if (not self.first_turn_processed and 
            is_during and 
            self.current_phase == MovePhase.ACTIVE and 
            self.duration == 1):
            
            self.debug("SPECIAL: Duration 1 during own turn - skipping decrement on first turn")
            self.first_turn_processed = True
            return False, None  # No decrement, no transition
        
        # Normal processing - decrement at turn start
        self.debug(f"BEFORE decrement: phase={self.current_phase.value}, turns={self.turns_remaining}")
        
        if self.turns_remaining > 0:
            self.turns_remaining -= 1
            self.debug(f"AFTER decrement: turns={self.turns_remaining}")
            
            # Check for marking for expiry (not removal yet)
            if self.turns_remaining <= 0:
                if self.current_phase == MovePhase.ACTIVE and self.duration == 1:
                    # Special case: Duration 1 effect marks for expiry but doesn't remove yet
                    self.marked_for_expiry = True
                    self.debug("Duration 1 effect marked for expiry (will be removed at turn end)")
                    return False, None  # No transition message yet
                else:
                    # Normal transition
                    return self._handle_phase_transition()
        
        self.first_turn_processed = True
        return False, None
    
    def process_turn_end(self, round_number, turn_name, character_name) -> Tuple[bool, Optional[str]]:
        """
        Process turn END - Only handles cleanup and removal messages.
        
        YOUR LOGIC:
        - No duration changes here
        - Only removes effects marked for expiry
        - Shows "worn off" messages
        
        Returns:
            (should_remove, cleanup_message)
        """
        # Skip if not this character's turn
        if character_name != turn_name:
            return False, None
            
        # Check if marked for expiry
        if self.marked_for_expiry:
            self.should_be_removed = True
            phase_name = self.current_phase.value
            self.debug(f"Turn end - removing effect marked for expiry (was {phase_name})")
            return True, f"{self.current_phase.value} effect has worn off"
        
        # Check if should be removed from other reasons
        if self.should_be_removed:
            self.debug("Turn end - effect already marked for removal")
            return True, f"{self.current_phase.value} effect expired"
        
        return False, None
    
    def _handle_phase_transition(self) -> Tuple[bool, Optional[str]]:
        """Handle transition between phases"""
        old_phase = self.current_phase
        
        if self.current_phase == MovePhase.CASTING:
            # Casting complete, move to active
            if self.duration and self.duration > 0:
                self.current_phase = MovePhase.ACTIVE
                self.turns_remaining = self.duration
                message = "activates!"
                self.debug(f"Transitioned: {old_phase.value} -> ACTIVE ({self.turns_remaining} turns)")
            elif self.cooldown and self.cooldown > 0:
                # No active phase, go straight to cooldown
                self.current_phase = MovePhase.COOLDOWN
                self.turns_remaining = self.cooldown
                message = "enters cooldown"
                self.debug(f"Transitioned: {old_phase.value} -> COOLDOWN ({self.turns_remaining} turns)")
            else:
                # No further phases
                self.should_be_removed = True
                message = "completes"
                self.debug(f"Transitioned: {old_phase.value} -> REMOVED")
                
        elif self.current_phase == MovePhase.ACTIVE:
            # Active complete, move to cooldown
            if self.cooldown and self.cooldown > 0:
                self.current_phase = MovePhase.COOLDOWN
                self.turns_remaining = self.cooldown
                message = "enters cooldown"
                self.debug(f"Transitioned: {old_phase.value} -> COOLDOWN ({self.turns_remaining} turns)")
            else:
                # No cooldown phase - mark for expiry
                self.marked_for_expiry = True
                message = None  # No message yet, will show at turn end
                self.debug(f"Active phase complete - marked for expiry")
                return False, None  # No immediate transition message
                
        elif self.current_phase == MovePhase.COOLDOWN:
            # Cooldown complete
            self.should_be_removed = True
            message = "cooldown ends"
            self.debug(f"Transitioned: {old_phase.value} -> REMOVED")
        else:
            message = "completes"
            self.should_be_removed = True
            self.debug(f"Unknown phase transition: {old_phase.value}")
        
        self.just_transitioned = True
        return True, message
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        return {
            "phase": self.current_phase.value,
            "turns_remaining": self.turns_remaining,
            "cast_time": self.cast_time,
            "duration": self.duration,
            "cooldown": self.cooldown,
            "should_be_removed": self.should_be_removed,
            "marked_for_expiry": self.marked_for_expiry,
            "applied_during_own_turn": self.applied_during_own_turn,
            "first_turn_processed": self.first_turn_processed,
            "last_processed_round": self.last_processed_round,
            "last_processed_turn": self.last_processed_turn
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create from dictionary data"""
        instance = cls(
            cast_time=data.get("cast_time"),
            duration=data.get("duration"),
            cooldown=data.get("cooldown")
        )
        
        # Restore state
        try:
            instance.current_phase = MovePhase(data.get("phase", "instant"))
        except (ValueError, TypeError):
            instance.current_phase = MovePhase.INSTANT
            
        instance.turns_remaining = data.get("turns_remaining", 0)
        instance.should_be_removed = data.get("should_be_removed", False)
        instance.marked_for_expiry = data.get("marked_for_expiry", False)
        instance.applied_during_own_turn = data.get("applied_during_own_turn")
        instance.first_turn_processed = data.get("first_turn_processed", False)
        instance.last_processed_round = data.get("last_processed_round")
        instance.last_processed_turn = data.get("last_processed_turn")
        
        return instance

class MoveEffect(BaseEffect):
    """
    Move effect with PROPER timing system per user specification.
    
    YOUR EXACT REQUIREMENTS:
    - Turn START: Decrements duration, shows status, handles attacks  
    - Turn END: Only removes expired effects and shows cleanup
    - Duration 1 during own turn: Waits one turn, then marks for expiry
    - Applied not during: Normal decrement behavior
    - NO force_during needed - timing is built-in
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
        enable_heat_tracking: bool = False,
        enable_hit_bonus: bool = False,
        roll_modifier: Optional[Dict[str, Any]] = None,
        save_type: Optional[str] = None,
        save_dc: Optional[str] = None,
        half_on_save: bool = False
        # NOTE: force_during parameter REMOVED per user request
    ):
        """Initialize a move effect with proper timing per user specification"""
        # Use actual duration for BaseEffect 
        actual_duration = 0 if duration is None else duration
        
        super().__init__(
            name=name,
            duration=actual_duration,
            permanent=False,
            category=EffectCategory.STATUS,
            description=description,
            process_timing="both",
            emoji="✨",
            debug_mode=True
        )
        
        # Flag to ignore BaseEffect duration management
        self._ignore_base_duration = True
        self._internal_duration = actual_duration
        
        # Store timing parameters
        self._move_cast_time = cast_time
        self._move_duration = duration
        self._move_cooldown = cooldown
        
        # Use proper timing handler
        self.timing_handler = ProperMoveEffectTiming(
            cast_time=cast_time,
            duration=duration,
            cooldown=cooldown,
            debug_mode=True
        )
        
        # Store resource costs
        self.star_cost = star_cost
        self.mp_cost = mp_cost
        self.hp_cost = hp_cost
        
        # Combat processors
        self.combat = CombatProcessor(debug_mode=True)
        self.saves = SavingThrowProcessor(debug_mode=True)
        
        # Store tracking info
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
        
        # Set conditions
        self.conditions = conditions or []
        
        # Store additional properties
        self.cast_description = cast_description
        self.targets = targets or []
        
        # Auto-detect roll timing
        is_truly_instant = not cast_time and not duration and not cooldown
        has_only_cooldown = not cast_time and not duration and cooldown is not None
        
        if (is_truly_instant or has_only_cooldown) and attack_roll:
            print(f"[Move-{name}] Auto-detected INSTANT attack")
            roll_timing = "instant"
        
        # Determine roll timing
        try:
            self.roll_timing = RollTiming(roll_timing)
        except (ValueError, TypeError):
            self.roll_timing = RollTiming.ACTIVE
            print(f"[Move-{name}] Invalid roll timing '{roll_timing}', defaulting to ACTIVE")
        
        # Initialize bonus on hit
        if bonus_on_hit is None and (enable_heat_tracking or enable_hit_bonus):
            bonus_on_hit = {'stars': 1}
        
        if isinstance(bonus_on_hit, str):
            try:
                import json
                bonus_on_hit = json.loads(bonus_on_hit)
            except Exception:
                bonus_on_hit = {'stars': 1}
        
        self.bonus_on_hit = BonusOnHit.from_dict(bonus_on_hit)
        
        # Initialize roll modifier if provided
        self.roll_modifier_data = roll_modifier
        self.roll_modifier_effect = None
        if roll_modifier:
            self._init_roll_modifier(roll_modifier, name, duration)
        
        # Configure combat settings
        self.combat.aoe_mode = aoe_mode
        
        # Tracking variables
        self.marked_for_removal = False
        self._internal_cache = {}
        self.last_roll_round = None
        
        print(f"[Move-{name}] Created with PROPER timing: cast={cast_time}, duration={duration}, cooldown={cooldown}")
        print(f"[Move-{name}] NO force_during parameter - timing is built-in per user specification")

    @property
    def cast_time(self):
        """Get the cast time for this move"""
        return self._move_cast_time
    
    @property
    def duration(self):
        """Get the active duration for this move"""
        return self._move_duration
    
    @property
    def cooldown(self):
        """Get the cooldown time for this move"""
        return self._move_cooldown

    def apply_costs(self, character) -> List[str]:
        """Apply resource costs (MP, HP, Stars) to the character"""
        messages = []
        print(f"[Move-{self.name}] Applying costs to {character.name}")
        
        # Apply MP cost
        if self.mp_cost != 0 and hasattr(character, 'resources'):
            if hasattr(character.resources, 'current_mp'):
                if self.mp_cost > 0:
                    if character.resources.current_mp >= self.mp_cost:
                        character.resources.current_mp -= self.mp_cost
                        messages.append(f"{character.name} spends {self.mp_cost} MP")
                        print(f"[Move-{self.name}] {character.name} spent {self.mp_cost} MP")
                    else:
                        print(f"[Move-{self.name}] WARNING: {character.name} doesn't have enough MP")
                        messages.append(f"{character.name} doesn't have enough MP!")
                elif self.mp_cost < 0:
                    restore_amount = abs(self.mp_cost)
                    actual_restore = min(
                        restore_amount,
                        character.resources.max_mp - character.resources.current_mp
                    )
                    character.resources.current_mp += actual_restore
                    if actual_restore > 0:
                        messages.append(f"{character.name} restores {actual_restore} MP")
        
        # Apply HP cost
        if self.hp_cost != 0 and hasattr(character, 'resources'):
            if hasattr(character.resources, 'current_hp'):
                if self.hp_cost > 0:
                    character.resources.current_hp = max(0, character.resources.current_hp - self.hp_cost)
                    messages.append(f"{character.name} spends {self.hp_cost} HP")
                    print(f"[Move-{self.name}] {character.name} spent {self.hp_cost} HP")
                elif self.hp_cost < 0:
                    heal_amount = abs(self.hp_cost)
                    actual_heal = min(
                        heal_amount,
                        character.resources.max_hp - character.resources.current_hp
                    )
                    character.resources.current_hp += actual_heal
                    if actual_heal > 0:
                        messages.append(f"{character.name} heals {actual_heal} HP")
        
        # Apply Star cost
        if self.star_cost > 0 and hasattr(character, 'action_stars'):
            if hasattr(character.action_stars, 'current_stars'):
                if character.action_stars.current_stars >= self.star_cost:
                    character.action_stars.current_stars -= self.star_cost
                    messages.append(f"{character.name} spends {self.star_cost} ⭐")
                    print(f"[Move-{self.name}] {character.name} spent {self.star_cost} stars")
                else:
                    print(f"[Move-{self.name}] WARNING: {character.name} doesn't have enough stars")
                    messages.append(f"{character.name} doesn't have enough stars!")
        
        return messages

    def can_use(self, character) -> Tuple[bool, str]:
        """Check if character has enough resources to use this move"""
        # Check MP cost
        if self.mp_cost > 0 and hasattr(character, 'resources'):
            if hasattr(character.resources, 'current_mp'):
                if character.resources.current_mp < self.mp_cost:
                    return False, f"Not enough MP ({character.resources.current_mp}/{self.mp_cost})"
                    
        # Check HP cost
        if self.hp_cost > 0 and hasattr(character, 'resources'):
            if hasattr(character.resources, 'current_hp'):
                if character.resources.current_hp <= self.hp_cost:
                    return False, f"Not enough HP ({character.resources.current_hp}/{self.hp_cost})"
        
        # Check star cost
        if self.star_cost > 0 and hasattr(character, 'action_stars'):
            if hasattr(character.action_stars, 'can_use_stars'):
                can_use, reason = character.action_stars.can_use_stars(self.star_cost)
                if not can_use:
                    return False, reason
            elif hasattr(character.action_stars, 'current_stars'):
                if character.action_stars.current_stars < self.star_cost:
                    return False, f"Not enough stars ({character.action_stars.current_stars}/{self.star_cost})"
        
        return True, "Ability ready to use"

    def on_apply(self, character, round_number: int) -> str:
        """Apply the effect to a character with proper timing"""
        print(f"[Move-{self.name}] Applying to {character.name} on round {round_number}")
        
        # Call parent method for basic initialization
        apply_msg = super().on_apply(character, round_number)
        
        # Apply resource costs
        cost_messages = self.apply_costs(character)
        
        # Apply roll modifier if configured
        if self.roll_modifier_effect:
            self.roll_modifier_effect.initialize_timing(round_number, character.name)
            
            if 'roll_modifiers' not in character.custom_parameters:
                character.custom_parameters['roll_modifiers'] = []
                
            character.custom_parameters['roll_modifiers'].append(self.roll_modifier_effect)
            print(f"[Move-{self.name}] Applied roll modifier: {self.roll_modifier_effect.name}")
        
        # Format information about the effect
        info_parts = []
        
        # Add resource costs
        if self.mp_cost > 0:
            info_parts.append(f"💙 MP: {self.mp_cost}")
        elif self.mp_cost < 0:
            info_parts.append(f"💙 Restore: {abs(self.mp_cost)}")
            
        if self.hp_cost > 0:
            info_parts.append(f"❤️ HP: {self.hp_cost}")
        elif self.hp_cost < 0:
            info_parts.append(f"❤️ Heal: {abs(self.hp_cost)}")
            
        if self.star_cost > 0:
            info_parts.append(f"⭐ {self.star_cost}")
        
        # Add timing info
        if self.cast_time and self.cast_time > 0:
            info_parts.append(f"🔄 {self.cast_time}T Cast")
        if self.cooldown and self.cooldown > 0:
            info_parts.append(f"⌛ {self.cooldown}T Cooldown")
        
        # Add current resource status
        if hasattr(character, 'resources') and hasattr(character.resources, 'current_mp'):
            info_parts.append(f"MP: {character.resources.current_mp}/{character.resources.max_mp}")
                
        if hasattr(character, 'action_stars') and hasattr(character.action_stars, 'current_stars'):
            info_parts.append(f"Stars: {character.action_stars.current_stars}/{character.action_stars.max_stars}")
        
        # Determine if this is truly instant
        is_truly_instant = not self.cast_time and not self.duration and not self.cooldown
        has_only_cooldown = not self.cast_time and not self.duration and self.cooldown is not None
        
        # Handle instant effects
        attack_messages = []
        if self.attack_roll and (is_truly_instant or has_only_cooldown or self.roll_timing == RollTiming.INSTANT):
            print(f"[Move-{self.name}] Processing INSTANT attack roll")
            self.last_roll_round = round_number
            
            if hasattr(self, 'bonus_on_hit'):
                self.bonus_on_hit.reset()
            
            attack_results = self.combat.perform_sync_attack(
                source=character,
                targets=self.targets,
                attack_roll=self.attack_roll,
                damage=self.damage,
                crit_range=self.crit_range,
                reason=self.name,
                bonus_on_hit=self.bonus_on_hit
            )
            
            if attack_results:
                attack_messages = attack_results
            
            # Mark for removal if truly instant
            if is_truly_instant:
                print(f"[Move-{self.name}] Marking for removal (truly instant)")
                self.marked_for_removal = True
            elif has_only_cooldown:
                print(f"[Move-{self.name}] Moving directly to cooldown")
                self.timing_handler.current_phase = MovePhase.COOLDOWN
                self.timing_handler.turns_remaining = self.cooldown
        
        # Build the primary message
        if self.cast_description:
            main_message = f"{character.name} {self.cast_description} {self.name}"
        else:
            if is_truly_instant:
                main_message = f"{character.name} uses {self.name}"
            elif self.timing_handler.current_phase == MovePhase.CASTING:
                main_message = f"{character.name} begins casting {self.name}"
            else:
                main_message = f"{character.name} uses {self.name}"
        
        # Format with info parts
        if info_parts:
            main_message = f"{main_message} | {' | '.join(info_parts)}"
            
        formatted_message = self.format_effect_message(main_message, [])
        
        # Add attack results as bulleted items
        if attack_messages:
            for result in attack_messages:
                formatted_message += f"\n• `{result}`"
        
        print(f"[Move-{self.name}] Apply complete with PROPER timing logic")
        return formatted_message

    def get_phase_name(self) -> str:
        """Get the current phase name for display purposes"""
        if not hasattr(self, 'timing_handler'):
            return ""
            
        current_phase = self.timing_handler.current_phase
        if current_phase == MovePhase.CASTING:
            return "casting"
        elif current_phase == MovePhase.ACTIVE:
            return "active"
        elif current_phase == MovePhase.COOLDOWN:
            return "cooldown"
        else:
            return ""
    
    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        PROPER LOGIC: Process effects at turn START - duration decrements here.
        """
        # Only process for effect owner
        if character.name != turn_name:
            return []

        print(f"[Move-{self.name}] Turn start for {character.name} on round {round_number}")
        messages = []
        
        # Process timing at turn START (where decrements happen)
        did_transition, transition_msg = self.timing_handler.process_turn_start(round_number, turn_name, character.name)
        
        # Get current state
        current_phase = self.timing_handler.current_phase
        turns_remaining = self.timing_handler.get_remaining_turns()
        phase_name = self.get_phase_name()
        is_final_turn = self.timing_handler.is_final_turn()
        is_marked_for_expiry = self.timing_handler.marked_for_expiry
        
        # Handle based on current phase and transitions
        if current_phase == MovePhase.CASTING:
            if did_transition and transition_msg:
                # Transition happened (casting -> active)
                msg = self.format_effect_message(f"{self.name} {transition_msg}", [])
                messages.append(msg)
            else:
                # Still casting
                turn_display = "Final turn of casting" if is_final_turn else f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"
                cast_msg = self.format_effect_message(f"Casting {self.name}", [turn_display])
                messages.append(cast_msg)
                
        elif current_phase == MovePhase.ACTIVE:
            # Handle attack rolls at turn start for active effects
            is_per_turn = getattr(self, 'roll_timing', None) == RollTiming.PER_TURN
            is_active_roll = getattr(self, 'roll_timing', None) == RollTiming.ACTIVE
            just_became_active = did_transition and self.timing_handler.just_transitioned
            
            should_attack = (is_per_turn or (is_active_roll and just_became_active))
            
            if self.attack_roll and should_attack:
                print(f"[Move-{self.name}] Processing attack roll at turn start")
                self.last_roll_round = round_number
                
                if hasattr(self, 'bonus_on_hit'):
                    self.bonus_on_hit.reset()
                
                # Show status message first
                if did_transition and transition_msg:
                    active_msg = self.format_effect_message(f"{self.name} {transition_msg}", [])
                    messages.append(active_msg)
                elif is_marked_for_expiry:
                    # Special case: Duration 1 effect marked for expiry
                    active_msg = self.format_effect_message(f"{self.name} {phase_name}", ["Final turn"])
                    messages.append(active_msg)
                else:
                    turn_display = "Final turn" if is_final_turn else f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"
                    active_msg = self.format_effect_message(f"{self.name} {phase_name}", [turn_display])
                    messages.append(active_msg)
                
                # Execute attack
                attack_results = self.combat.perform_sync_attack(
                    source=character,
                    targets=self.targets,
                    attack_roll=self.attack_roll,
                    damage=self.damage,
                    crit_range=self.crit_range,
                    reason=self.name,
                    bonus_on_hit=self.bonus_on_hit
                )
                
                if attack_results:
                    for result in attack_results:
                        messages.append(f"• `{result}`")
            else:
                # No attack, just show status
                if did_transition and transition_msg:
                    active_msg = self.format_effect_message(f"{self.name} {transition_msg}", [])
                    messages.append(active_msg)
                elif is_marked_for_expiry:
                    # Special case: Duration 1 effect marked for expiry
                    active_msg = self.format_effect_message(f"{self.name} {phase_name}", ["Final turn"])
                    messages.append(active_msg)
                else:
                    turn_display = "Final turn" if is_final_turn else f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"
                    active_msg = self.format_effect_message(f"{self.name} {phase_name}", [turn_display])
                    messages.append(active_msg)
            
        elif current_phase == MovePhase.COOLDOWN:
            if did_transition and transition_msg:
                cooldown_msg = self.format_effect_message(f"{self.name} {transition_msg}", [])
                messages.append(cooldown_msg)
            else:
                turn_display = "Final turn" if is_final_turn else f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"
                cooldown_msg = self.format_effect_message(f"{self.name} {phase_name}", [turn_display])
                messages.append(cooldown_msg)
        
        # Check if marked for removal after processing
        if self.timing_handler.should_be_removed:
            self.marked_for_removal = True
            self.state = EffectState.EXPIRED
            print(f"[Move-{self.name}] Marked for removal after turn start processing")
        
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        PROPER LOGIC: Process effects at turn END - only cleanup, no duration changes.
        """
        # Only process for effect owner
        if character.name != turn_name:
            return []
            
        print(f"[Move-{self.name}] Turn end for {character.name} on round {round_number}")
        messages = []
        
        # Override BaseEffect duration management
        if hasattr(self, '_ignore_base_duration') and self._ignore_base_duration:
            self._duration_remaining = 999  # Prevent BaseEffect from removing it
        
        # Check if already marked for removal
        if self.marked_for_removal or self.timing_handler.should_be_removed:
            print(f"[Move-{self.name}] Already marked for removal")
            return []
        
        # Process turn end (only cleanup and removal)
        should_remove, cleanup_msg = self.timing_handler.process_turn_end(round_number, turn_name, character.name)
        
        if should_remove:
            self.marked_for_removal = True
            self.state = EffectState.EXPIRED
            print(f"[Move-{self.name}] Marked for removal at turn end: {cleanup_msg}")
            
            # Add expiry message to feedback for display in turn end embed
            if hasattr(character, 'add_effect_feedback'):
                expiry_msg = self.format_effect_message(f"{self.name} has worn off")
                character.add_effect_feedback(
                    effect_name=self.name,
                    expiry_message=expiry_msg,
                    round_expired=round_number,
                    turn_expired=character.name
                )
                print(f"[Move-{self.name}] Added expiry feedback for turn end embed")
        
        return messages

    def on_expire(self, character) -> str:
        """Handle effect expiration"""
        print(f"[Move-{self.name}] Expiring from {character.name}")
        
        # Call parent method
        super().on_expire(character)
        
        # Clear targets
        self.targets = []
        
        # Format expiry message
        message = self.format_effect_message(f"{self.name} has expired from {character.name}")
        
        return message

    @property
    def is_expired(self) -> bool:
        """Check if the effect is expired and should be removed"""
        if self.marked_for_removal:
            return True
        
        if hasattr(self, 'timing_handler') and self.timing_handler:
            if hasattr(self.timing_handler, 'should_be_removed') and self.timing_handler.should_be_removed:
                return True
            if hasattr(self.timing_handler, 'current_phase') and self.timing_handler.current_phase == MovePhase.INSTANT:
                return True
        
        if hasattr(self, 'state') and hasattr(self.state, 'value'):
            return self.state.value in ['expired', 'removed']
        
        return False

    async def execute_pending_operations(self) -> List[str]:
        """Execute any pending async operations"""
        # In proper system, everything is handled synchronously at correct timing
        return []