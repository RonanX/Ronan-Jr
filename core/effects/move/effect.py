"""
Core implementation of the MoveEffect class with FIXED timing logic.

FIXES:
1. Phase now in parentheses: "(casting) 1 turn remaining"
2. Attack rolls ONLY happen at turn start, never turn end
3. Duration now shows in apply message
4. Transitions happen at turn end but no attacks
5. Turn start decrements, turn end shows status
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

class SimplifiedMoveEffectTiming:
    """
    SIMPLIFIED timing system:
    
    - Turn START: Decrements and marks for changes
    - Turn END: Shows status and executes changes
    - Consistent behavior regardless of when applied
    """
    
    def __init__(self, 
                 cast_time: Optional[int] = None,
                 duration: Optional[int] = None, 
                 cooldown: Optional[int] = None,
                 debug_mode: bool = True):
        """Initialize simplified timing"""
        self.debug_mode = debug_mode
        self.debug_id = f"SimpleTiming-{id(self) % 10000}"
        
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
        self.pending_transition = None  # What transition to execute at turn end
        self.last_processed_round = None
        self.last_processed_turn = None
        
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
    
    def process_turn_start(self, round_number, turn_name, character_name) -> None:
        """
        Process turn START - Only decrements and marks for changes.
        No messages, no transitions - just bookkeeping.
        """
        # Skip if not this character's turn
        if character_name != turn_name:
            return
            
        # Skip if already processed this turn
        if (self.last_processed_round == round_number and 
            self.last_processed_turn == turn_name):
            self.debug(f"Already processed turn start R{round_number}, T{turn_name}")
            return
            
        # Mark as processed
        self.last_processed_round = round_number
        self.last_processed_turn = turn_name
        
        # Handle INSTANT phase
        if self.current_phase == MovePhase.INSTANT:
            self.should_be_removed = True
            self.debug("Instant effect marked for removal")
            return
        
        # Decrement turns
        self.debug(f"BEFORE decrement: phase={self.current_phase.value}, turns={self.turns_remaining}")
        
        if self.turns_remaining > 0:
            self.turns_remaining -= 1
            self.debug(f"AFTER decrement: turns={self.turns_remaining}")
            
            # Mark for transition if turns hit 0
            if self.turns_remaining <= 0:
                self._mark_for_transition()
    
    def _mark_for_transition(self):
        """Mark what transition should happen at turn end"""
        if self.current_phase == MovePhase.CASTING:
            if self.duration and self.duration > 0:
                self.pending_transition = ('active', self.duration)
                self.debug("Marked for transition: casting -> active")
            elif self.cooldown and self.cooldown > 0:
                self.pending_transition = ('cooldown', self.cooldown)
                self.debug("Marked for transition: casting -> cooldown")
            else:
                self.should_be_removed = True
                self.debug("Marked for removal after casting")
                
        elif self.current_phase == MovePhase.ACTIVE:
            if self.cooldown and self.cooldown > 0:
                self.pending_transition = ('cooldown', self.cooldown)
                self.debug("Marked for transition: active -> cooldown")
            else:
                self.should_be_removed = True
                self.debug("Marked for removal after active")
                
        elif self.current_phase == MovePhase.COOLDOWN:
            self.should_be_removed = True
            self.debug("Marked for removal after cooldown")
    
    def process_turn_end(self, round_number, turn_name, character_name) -> Tuple[Optional[str], bool]:
        """
        Process turn END - Show status and execute marked transitions.
        
        Returns:
            (status_message, should_remove)
        """
        # Skip if not this character's turn
        if character_name != turn_name:
            return None, False
            
        # Execute pending transition if any
        transition_msg = None
        if self.pending_transition:
            new_phase, new_turns = self.pending_transition
            old_phase = self.current_phase
            
            if new_phase == 'active':
                self.current_phase = MovePhase.ACTIVE
                self.turns_remaining = new_turns
                transition_msg = f"activates"
            elif new_phase == 'cooldown':
                self.current_phase = MovePhase.COOLDOWN
                self.turns_remaining = new_turns
                transition_msg = f"enters cooldown"
                
            self.pending_transition = None
            self.debug(f"Executed transition: {old_phase.value} -> {new_phase}")
            
            # Return transition message
            return transition_msg, False
        
        # If marked for removal, effect has worn off
        if self.should_be_removed:
            return "has worn off", True
        
        # Otherwise, show current status with phase in parentheses
        if self.turns_remaining > 0:
            status = f"({self.current_phase.value}) {self.turns_remaining} turn{'s' if self.turns_remaining != 1 else ''} remaining"
            return status, False
        
        return None, False
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        return {
            "phase": self.current_phase.value,
            "turns_remaining": self.turns_remaining,
            "cast_time": self.cast_time,
            "duration": self.duration,
            "cooldown": self.cooldown,
            "should_be_removed": self.should_be_removed,
            "pending_transition": self.pending_transition,
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
        instance.pending_transition = data.get("pending_transition")
        instance.last_processed_round = data.get("last_processed_round")
        instance.last_processed_turn = data.get("last_processed_turn")
        
        return instance

class MoveEffect(BaseEffect):
    """
    Move effect with FIXED timing system.
    
    REQUIREMENTS:
    - Turn START: Decrements duration, processes attacks, marks for changes
    - Turn END: Shows status, executes transitions (NO ATTACKS)
    - Phase shown in parentheses
    - Duration shown in apply message
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
    ):
        """Initialize a move effect with fixed timing"""
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
        
        # Use simplified timing handler
        self.timing_handler = SimplifiedMoveEffectTiming(
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
        self.pending_attack = False  # Track if we need to process attack after transition
        
        print(f"[Move-{name}] Created with FIXED timing: cast={cast_time}, duration={duration}, cooldown={cooldown}")

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

    def _init_roll_modifier(self, roll_modifier: Dict[str, Any], move_name: str, duration: Optional[int]):
        """Initialize roll modifier effect if configured"""
        if not roll_modifier:
            return
            
        # Extract modifier parameters
        mod_type = roll_modifier.get('type', 'bonus')
        mod_value = roll_modifier.get('value', 0)
        mod_duration = roll_modifier.get('duration', duration or 1)
        
        # Create the appropriate effect based on type
        if mod_type == 'bonus':
            self.roll_modifier_effect = RollModifierEffect(
                name=f"{move_name} Bonus",
                modifier_type=RollModifierType.BONUS,
                modifier_value=mod_value,
                duration=mod_duration,
                source=move_name
            )
        elif mod_type == 'advantage':
            self.roll_modifier_effect = RollModifierEffect(
                name=f"{move_name} Advantage",
                modifier_type=RollModifierType.ADVANTAGE,
                duration=mod_duration,
                source=move_name
            )
        elif mod_type == 'disadvantage':
            self.roll_modifier_effect = RollModifierEffect(
                name=f"{move_name} Disadvantage",
                modifier_type=RollModifierType.DISADVANTAGE,
                duration=mod_duration,
                source=move_name
            )

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
        """Apply the effect to a character with fixed timing"""
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
        
        # Add ALL timing info (cast, duration, cooldown)
        if self.cast_time and self.cast_time > 0:
            info_parts.append(f"🔄 {self.cast_time}T Cast")
        if self.duration and self.duration > 0:
            info_parts.append(f"⏱️ {self.duration}T Duration")
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
        
        # Add attack results as bulleted items (including bonus messages)
        if attack_messages:
            for result in attack_messages:
                formatted_message += f"\n• `{result}`"
        
        print(f"[Move-{self.name}] Apply complete with FIXED timing logic")
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
        FIXED: Process effects at turn START - decrement, process attacks, mark for changes.
        """
        # Only process for effect owner
        if character.name != turn_name:
            return []

        print(f"[Move-{self.name}] Turn start for {character.name} on round {round_number}")
        messages = []
        
        # Process timing at turn START (only decrements, no messages)
        self.timing_handler.process_turn_start(round_number, turn_name, character.name)
        
        # Check if we're transitioning to active phase
        will_transition_to_active = (
            self.timing_handler.pending_transition and 
            self.timing_handler.pending_transition[0] == 'active'
        )
        
        # Process attacks ONLY during active phase and not when transitioning
        current_phase = self.timing_handler.current_phase
        if (current_phase == MovePhase.ACTIVE and 
            not self.timing_handler.pending_transition):
            
            # Process ACTIVE timing attack on first turn of active phase
            if self.roll_timing == RollTiming.ACTIVE and not self.last_roll_round:
                print(f"[Move-{self.name}] Processing ACTIVE attack roll (first turn)")
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
                    for result in attack_results:
                        messages.append(f"• `{result}`")
            
            # Process PER_TURN attacks every turn
            elif self.roll_timing == RollTiming.PER_TURN and self.attack_roll:
                print(f"[Move-{self.name}] Processing PER_TURN attack roll")
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
                    for result in attack_results:
                        messages.append(f"• `{result}`")
        
        # Mark pending attack if we're about to transition to active
        if will_transition_to_active and self.roll_timing == RollTiming.ACTIVE:
            self.pending_attack = True
            print(f"[Move-{self.name}] Marked pending attack for after transition")
        
        # Check if marked for removal after processing
        if self.timing_handler.should_be_removed:
            self.marked_for_removal = True
            self.state = EffectState.EXPIRED
            print(f"[Move-{self.name}] Marked for removal after turn start processing")
        
        # Turn start returns attack messages only
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        FIXED: Process effects at turn END - show status and execute transitions (NO ATTACKS).
        """
        # Only process for effect owner
        if character.name != turn_name:
            return []
            
        print(f"[Move-{self.name}] Turn end for {character.name} on round {round_number}")
        messages = []
        
        # Override BaseEffect duration management
        if hasattr(self, '_ignore_base_duration') and self._ignore_base_duration:
            self._duration_remaining = 999  # Prevent BaseEffect from removing it
        
        # Get status and check for removal
        status_msg, should_remove = self.timing_handler.process_turn_end(round_number, turn_name, character.name)
        
        # If we have a transition message, show it
        if status_msg and "activates" in status_msg:
            # This is an activation message
            messages.append(self.format_effect_message(f"{self.name} {status_msg}", []))
            
            # Process pending attack if needed
            if self.pending_attack and self.roll_timing == RollTiming.ACTIVE and self.attack_roll:
                print(f"[Move-{self.name}] Processing pending ACTIVE attack after transition")
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
                    for result in attack_results:
                        messages.append(f"• `{result}`")
                        
                self.pending_attack = False
                
        elif status_msg and "enters cooldown" in status_msg:
            # Cooldown transition
            messages.append(self.format_effect_message(f"{self.name} {status_msg}", []))
            
        elif status_msg and "has worn off" in status_msg:
            # Effect expiring
            self.marked_for_removal = True
            self.state = EffectState.EXPIRED
            
            # Add expiry message to feedback
            if hasattr(character, 'add_effect_feedback'):
                expiry_msg = self.format_effect_message(f"{self.name} {status_msg}")
                character.add_effect_feedback(
                    effect_name=self.name,
                    expiry_message=expiry_msg,
                    round_expired=round_number,
                    turn_expired=character.name
                )
                print(f"[Move-{self.name}] Added expiry feedback for turn end embed")
                
        elif status_msg:
            # Regular status update with phase in parentheses
            messages.append(self.format_effect_message(f"{self.name} {status_msg}", []))
        
        # Mark for removal if needed
        if should_remove:
            self.marked_for_removal = True
            self.state = EffectState.EXPIRED
            print(f"[Move-{self.name}] Marked for removal at turn end")
        
        return messages

    def on_expire(self, character) -> str:
        """Handle effect expiration"""
        print(f"[Move-{self.name}] Expiring from {character.name}")
        
        # Call parent method
        super().on_expire(character)
        
        # Clear targets
        self.targets = []
        
        # Don't return a message here - it's handled by feedback system
        return ""

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
        # In fixed system, everything is handled synchronously at correct timing
        return []

    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        
        # Add move-specific data
        data.update({
            "star_cost": self.star_cost,
            "mp_cost": self.mp_cost,
            "hp_cost": self.hp_cost,
            "cast_time": self._move_cast_time,
            "duration": self._move_duration,
            "cooldown": self._move_cooldown,
            "timing_handler": self.timing_handler.to_dict() if self.timing_handler else None,
            "attack_roll": self.attack_roll,
            "damage": self.damage,
            "crit_range": self.crit_range,
            "roll_timing": self.roll_timing.value if self.roll_timing else "active",
            "targets": [t.name for t in self.targets] if self.targets else [],
            "bonus_on_hit": self.bonus_on_hit.to_dict() if self.bonus_on_hit else None,
            "marked_for_removal": self.marked_for_removal,
            "pending_attack": self.pending_attack
        })
        
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'MoveEffect':
        """Create from dictionary data"""
        # Extract parameters
        instance = cls(
            name=data.get("name", "Unknown Move"),
            description=data.get("description", ""),
            star_cost=data.get("star_cost", 0),
            mp_cost=data.get("mp_cost", 0),
            hp_cost=data.get("hp_cost", 0),
            cast_time=data.get("cast_time"),
            duration=data.get("duration"),
            cooldown=data.get("cooldown"),
            attack_roll=data.get("attack_roll"),
            damage=data.get("damage"),
            crit_range=data.get("crit_range", 20),
            roll_timing=data.get("roll_timing", "active")
        )
        
        # Restore timing handler state
        if data.get("timing_handler"):
            instance.timing_handler = SimplifiedMoveEffectTiming.from_dict(data["timing_handler"])
        
        # Restore other state
        instance.marked_for_removal = data.get("marked_for_removal", False)
        instance.pending_attack = data.get("pending_attack", False)
        
        # Note: targets would need to be restored from character names
        
        return instance