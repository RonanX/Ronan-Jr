"""
Core implementation of the MoveEffect class with independent phase management.
"""

import logging
from typing import Optional, List, Dict, Any, Set, Union

from core.effects.base import BaseEffect, EffectCategory, EffectState
from core.effects.rollmod import RollModifierType, RollModifierEffect
from core.effects.condition import ConditionType

# Import phase system and processors
from .state import MoveState, MoveStateMachine, RollTiming
from .base import MovePhase, MoveEffectTiming
from .combat import CombatProcessor, BonusOnHit
from .saves import SavingThrowProcessor

logger = logging.getLogger(__name__)

class MoveEffect(BaseEffect):
    """
    Move effect with independent phase management and proper turn timing.
    
    Key features:
    - Independent phase management (casting→active→cooldown)
    - Smart turn-by-turn processing
    - "During own turn" buffering to ensure correct duration
    - Phase-specific behaviors
    - Accurate duration tracking
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
        force_during: Optional[bool] = None,
        save_type: Optional[str] = None,
        save_dc: Optional[str] = None,
        half_on_save: bool = False
    ):
        """Initialize a move effect with phase-based timing"""
        # FIX: Ensure duration is an integer for BaseEffect constructor
        actual_duration = 0 if duration is None else duration
        
        # Tell BaseEffect not to manage duration - we'll handle it ourselves
        super().__init__(
            name=name,
            duration=actual_duration,  # Changed from None to actual_duration
            permanent=False,
            category=EffectCategory.STATUS,
            description=description,
            process_timing="both",
            emoji="✨",
            debug_mode=True
        )
        
        # Flag to completely ignore BaseEffect duration management
        self._ignore_base_duration = True
        
        # Initialize internal duration explicitly to avoid None comparison issues
        self._internal_duration = actual_duration
        
        # Store these privately to avoid property conflicts
        self._move_cast_time = cast_time
        self._move_duration = duration
        self._move_cooldown = cooldown
        
        # Use our own timing handler for phase management
        self.timing_handler = MoveEffectTiming(
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
        
        # Auto-detect roll timing based on parameters
        is_truly_instant = not cast_time and not duration and not cooldown
        has_only_cooldown = not cast_time and not duration and cooldown is not None
        
        # Auto-detect instant attacks more aggressively
        if (is_truly_instant or has_only_cooldown) and attack_roll:
            print(f"[Move-{name}] Auto-detected INSTANT attack (no phases or cooldown only)")
            roll_timing = "instant"
        
        # Determine roll timing
        try:
            self.roll_timing = RollTiming(roll_timing)
        except (ValueError, TypeError):
            # Default to ACTIVE if invalid
            self.roll_timing = RollTiming.ACTIVE
            print(f"[Move-{name}] Invalid roll timing '{roll_timing}', defaulting to ACTIVE")
        
        # Initialize bonus on hit
        if bonus_on_hit is None and (enable_heat_tracking or enable_hit_bonus):
            bonus_on_hit = {'stars': 1}
        
        # Handle string parsing if needed
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
        self._internal_cache = {}  # Cache for async results
        self.last_roll_round = None  # Track when we last rolled
        
        # Force timing flag
        self.is_during_own_turn = force_during
        
        print(f"[Move-{name}] Created with phases: cast_time={cast_time}, duration={duration}, cooldown={cooldown}, roll_timing={self.roll_timing.value}")

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
        """
        Apply resource costs (MP, HP, Stars) to the character.
        
        Args:
            character: The character to apply costs to
            
        Returns:
            List[str]: Messages about the applied costs
        """
        messages = []
        print(f"[Move-{self.name}] Applying costs to {character.name}")
        
        # Apply MP cost if applicable
        if self.mp_cost != 0 and hasattr(character, 'resources'):
            if hasattr(character.resources, 'current_mp'):
                # For costs (positive values)
                if self.mp_cost > 0:
                    # Check if character has enough MP
                    if character.resources.current_mp >= self.mp_cost:
                        # Deduct MP
                        character.resources.current_mp -= self.mp_cost
                        messages.append(f"{character.name} spends {self.mp_cost} MP")
                        print(f"[Move-{self.name}] {character.name} spent {self.mp_cost} MP")
                    else:
                        # Not enough MP - this should have been checked before, but just in case
                        print(f"[Move-{self.name}] WARNING: {character.name} doesn't have enough MP ({character.resources.current_mp}/{self.mp_cost})")
                        messages.append(f"{character.name} doesn't have enough MP!")
                # For healing/restoring MP (negative values)
                elif self.mp_cost < 0:
                    restore_amount = abs(self.mp_cost)
                    # Calculate how much MP can actually be restored (don't exceed max)
                    actual_restore = min(
                        restore_amount,
                        character.resources.max_mp - character.resources.current_mp
                    )
                    character.resources.current_mp += actual_restore
                    if actual_restore > 0:
                        messages.append(f"{character.name} restores {actual_restore} MP")
                        print(f"[Move-{self.name}] {character.name} restored {actual_restore} MP")
        
        # Apply HP cost if applicable
        if self.hp_cost != 0 and hasattr(character, 'resources'):
            if hasattr(character.resources, 'current_hp'):
                # For costs (positive values)
                if self.hp_cost > 0:
                    # Deduct HP - no check needed as moves can put you at 0 HP
                    character.resources.current_hp = max(0, character.resources.current_hp - self.hp_cost)
                    messages.append(f"{character.name} spends {self.hp_cost} HP")
                    print(f"[Move-{self.name}] {character.name} spent {self.hp_cost} HP")
                # For healing HP (negative values)
                elif self.hp_cost < 0:
                    heal_amount = abs(self.hp_cost)
                    # Calculate how much HP can actually be healed (don't exceed max)
                    actual_heal = min(
                        heal_amount,
                        character.resources.max_hp - character.resources.current_hp
                    )
                    character.resources.current_hp += actual_heal
                    if actual_heal > 0:
                        messages.append(f"{character.name} heals {actual_heal} HP")
                        print(f"[Move-{self.name}] {character.name} healed {actual_heal} HP")
        
        # Apply Star cost if applicable
        if self.star_cost > 0 and hasattr(character, 'action_stars'):
            if hasattr(character.action_stars, 'current_stars'):
                # Check if character has enough stars
                if character.action_stars.current_stars >= self.star_cost:
                    # Deduct stars
                    character.action_stars.current_stars -= self.star_cost
                    messages.append(f"{character.name} spends {self.star_cost} ⭐")
                    print(f"[Move-{self.name}] {character.name} spent {self.star_cost} stars")
                else:
                    # Not enough stars - this should have been checked before, but just in case
                    print(f"[Move-{self.name}] WARNING: {character.name} doesn't have enough stars ({character.action_stars.current_stars}/{self.star_cost})")
                    messages.append(f"{character.name} doesn't have enough stars!")
        
        return messages

    def on_apply(self, character, round_number: int) -> str:
        """
        Apply the effect to a character with proper phase handling.
        This is a synchronous version to interface with the core effects system.
        """
        print(f"[Move-{self.name}] Applying to {character.name} on round {round_number}")
        
        # Call parent method for basic initialization
        apply_msg = super().on_apply(character, round_number)
        
        # Apply resource costs
        cost_messages = self.apply_costs(character)
        
        # Apply timing adjustment based on context
        if self.is_during_own_turn is not None:
            # Forced timing (from parameter)
            self.timing_handler.adjust_timing(self.is_during_own_turn)
            print(f"[Move-{self.name}] Using forced timing: during_own_turn={self.is_during_own_turn}")
        elif self.timing and hasattr(self.timing, 'applied_during_own_turn'):
            # Use timing from BaseEffect
            self.timing_handler.adjust_timing(self.timing.applied_during_own_turn)
            print(f"[Move-{self.name}] Using BaseEffect timing: during_own_turn={self.timing.applied_during_own_turn}")
        
        # Apply roll modifier if configured
        if self.roll_modifier_effect:
            # Set up timing
            self.roll_modifier_effect.initialize_timing(round_number, character.name)
            
            # Add to character's modifiers
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
        if hasattr(character, 'resources'):
            if hasattr(character.resources, 'current_mp'):
                info_parts.append(f"MP: {character.resources.current_mp}/{character.resources.max_mp}")
                
        if hasattr(character, 'action_stars') and hasattr(character.action_stars, 'current_stars'):
            info_parts.append(f"Stars: {character.action_stars.current_stars}/{character.action_stars.max_stars}")
        
        # Determine if this is a truly instant effect (no phases or cooldown only)
        is_truly_instant = not self.cast_time and not self.duration and not self.cooldown
        has_only_cooldown = not self.cast_time and not self.duration and self.cooldown is not None
        
        # Manage instant effects
        attack_preview = None
        if self.attack_roll and (is_truly_instant or has_only_cooldown or self.roll_timing == RollTiming.INSTANT):
            print(f"[Move-{self.name}] Processing INSTANT attack roll")
            self.last_roll_round = round_number
            
            # Create attack preview for instant display
            attack_preview = self.combat.preview_attack(
                source=character,
                targets=self.targets, 
                attack_roll=self.attack_roll,
                reason=self.name
            )
            
            # Store coroutine for executing the actual roll
            self._internal_cache['attack_coroutine'] = self.combat.process_attack(
                source=character,
                targets=self.targets,
                attack_roll=self.attack_roll,
                damage=self.damage,
                crit_range=self.crit_range,
                reason=self.name,
                bonus_on_hit=self.bonus_on_hit
            )
            
            # If truly instant (no phases), mark for removal after execution
            if is_truly_instant:
                print(f"[Move-{self.name}] Marking for removal after execution (truly instant)")
                self.marked_for_removal = True
            # If has only cooldown, immediately enter cooldown phase
            elif has_only_cooldown:
                print(f"[Move-{self.name}] Moving directly to cooldown phase (no cast/duration)")
                self.timing_handler.current_phase = MovePhase.COOLDOWN
                self.timing_handler.turns_remaining = self.cooldown
        
        # Format application message
        if self.cast_description:
            main_message = f"{character.name} {self.cast_description} {self.name}"
        else:
            # Format based on phase
            current_phase = self.timing_handler.current_phase
            if current_phase == MovePhase.INSTANT or is_truly_instant:
                main_message = f"{character.name} uses {self.name}"
            elif current_phase == MovePhase.CASTING:
                main_message = f"{character.name} begins casting {self.name}"
            elif current_phase == MovePhase.COOLDOWN:
                main_message = f"{character.name} uses {self.name}"
            else:
                main_message = f"{character.name} uses {self.name}"
        
        # Format the complete message - don't repeat info parts
        formatted_message = self.format_effect_message(f"{main_message} | {' | '.join(info_parts)}", [])
        
        # Add attack preview or target info - prefer attack preview if available
        if attack_preview:
            formatted_message += f"\n• Attack: {attack_preview}"
        elif self.attack_roll and (self.roll_timing == RollTiming.ACTIVE or self.roll_timing == RollTiming.PER_TURN):
            # Don't show target info if we'll be showing attack rolls later
            pass
        elif self.targets:
            if len(self.targets) == 1:
                formatted_message += f"\n• Target: {self.targets[0].name}"
            else:
                target_names = [t.name for t in self.targets]
                formatted_message += f"\n• Targets: {', '.join(target_names)}"
        
        print(f"[Move-{self.name}] Apply complete, returning formatted message")
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
    
    def is_final_turn_of_phase(self) -> bool:
        """Check if this is the final turn of the current phase"""
        if not hasattr(self, 'timing_handler'):
            return False
            
        return self.timing_handler.turns_remaining == 1
        
    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process effects at the start of a character's turn.
        This is a synchronous version to interface with the core effects system.
        """
        # Only process for effect owner
        if character.name != turn_name:
            return []

        print(f"[Move-{self.name}] Turn start for {character.name} on round {round_number}")
        messages = []
        
        # Get current phase and turns remaining
        current_phase = self.timing_handler.current_phase
        turns_remaining = self.timing_handler.get_display_turns()
        phase_name = self.get_phase_name()
        
        # Check if this is the final turn of the current phase
        is_final_turn_of_phase = self.is_final_turn_of_phase()
        
        # Format turn display with phase transition warning
        if is_final_turn_of_phase:
            if current_phase == MovePhase.CASTING:
                turn_display = "Casting completes this turn"
            elif current_phase == MovePhase.ACTIVE:
                turn_display = "Final active turn"
            elif current_phase == MovePhase.COOLDOWN:
                turn_display = "Cooldown ends this turn"
            else:
                turn_display = f"{turns_remaining} turn remaining"
        else:
            turn_display = f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"
        
        # IMPORTANT: Check if this effect just entered the active phase from casting
        just_activated = self.timing_handler.just_activated
        
        # Handle based on current phase
        if current_phase == MovePhase.CASTING:
            # Show casting status
            cast_msg = self.format_effect_message(
                f"Casting {self.name}",
                [turn_display]
            )
            messages.append(cast_msg)
            
        elif current_phase == MovePhase.ACTIVE:
            # Check for attack roll processing
            is_per_turn = getattr(self, 'roll_timing', None) == RollTiming.PER_TURN
            is_active_roll = getattr(self, 'roll_timing', None) == RollTiming.ACTIVE
            
            # Schedule attack roll if needed
            should_attack = (is_per_turn or (is_active_roll and just_activated))
            
            if self.attack_roll and should_attack:
                print(f"[Move-{self.name}] Scheduling attack roll for turn start (per_turn={is_per_turn})")
                self.last_roll_round = round_number
                
                # Reset bonus tracker
                if hasattr(self, 'bonus_on_hit'):
                    self.bonus_on_hit.reset()
                
                # Create attack preview
                preview_msg = self.combat.preview_attack(
                    source=character,
                    targets=self.targets, 
                    attack_roll=self.attack_roll,
                    reason=self.name
                )
                
                # Store coroutine for actual execution
                self._internal_cache['attack_coroutine'] = self.combat.process_attack(
                    source=character,
                    targets=self.targets,
                    attack_roll=self.attack_roll,
                    damage=self.damage,
                    crit_range=self.crit_range,
                    reason=self.name,
                    bonus_on_hit=self.bonus_on_hit
                )
                
                # Add preview to message
                active_msg = self.format_effect_message(
                    f"{self.name} {phase_name}",
                    [turn_display, f"*Attack: {preview_msg}*"]
                )
            else:
                # Show active status message without attack preview
                active_msg = self.format_effect_message(
                    f"{self.name} {phase_name}",
                    [turn_display]
                )
            
            # Add status message
            messages.append(active_msg)
            
        elif current_phase == MovePhase.COOLDOWN:
            # Show cooldown status
            cooldown_msg = self.format_effect_message(
                f"{self.name} {phase_name}",
                [turn_display]
            )
            messages.append(cooldown_msg)
        
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process effects at the end of a character's turn.
        """
        # Only process for effect owner
        if character.name != turn_name:
            return []
            
        print(f"[Move-{self.name}] Turn end for {character.name} on round {round_number}")
        messages = []
        
        # Override BaseEffect duration to prevent auto-expiry
        if hasattr(self, '_ignore_base_duration') and self._ignore_base_duration:
            # Set arbitrarily high value to prevent BaseEffect from removing it
            self._duration_remaining = 999
        
        # Check if already marked for removal
        if self.marked_for_removal or self.timing_handler.should_be_removed:
            print(f"[Move-{self.name}] Already marked for removal, skipping further processing")
            return []
        
        # Process turn in our timing handler
        did_transition, transition_msg = self.timing_handler.process_turn(round_number, turn_name)
        
        # Update flags based on timing handler state
        if self.timing_handler.should_be_removed:
            self.marked_for_removal = True
            self.state = EffectState.EXPIRED
            print(f"[Move-{self.name}] Marked for removal after turn processing")
            
            # Make sure the expiry message is added to the character's feedback
            if hasattr(character, 'effect_feedback') and hasattr(character.effect_feedback, 'add_feedback'):
                expiry_msg = self.format_effect_message(f"{self.name} has expired from {character.name}")
                character.effect_feedback.add_feedback(
                    round_number=round_number,
                    effect_name=self.name,
                    expiry_message=expiry_msg
                )
        
        # Get phase name for display
        phase_name = self.get_phase_name()
        
        # If a transition occurred, format appropriate message
        if did_transition and transition_msg:
            # Get details for the message
            details = []
            
            # Add phase-specific details
            current_phase = self.timing_handler.current_phase
            if current_phase == MovePhase.ACTIVE:
                # Just transitioned to active - show duration
                turns = self.timing_handler.get_display_turns()
                if turns > 0:
                    details.append(f"Active for {turns} turn{'s' if turns != 1 else ''}")
                print(f"[Move-{self.name}] Transitioned to ACTIVE phase with {turns} turns")
            elif current_phase == MovePhase.COOLDOWN:
                # Just transitioned to cooldown - show duration
                turns = self.timing_handler.get_display_turns()
                if turns > 0:
                    details.append(f"Cooldown: {turns} turn{'s' if turns != 1 else ''}")
                print(f"[Move-{self.name}] Transitioned to COOLDOWN phase with {turns} turns")
            
            # Format transition message
            msg = self.format_effect_message(
                f"{self.name} {transition_msg}",
                details
            )
            messages.append(msg)
        else:
            # No transition - show continuation message if needed
            current_phase = self.timing_handler.current_phase
            turns_remaining = self.timing_handler.get_display_turns()
            
            # Check if this is the final turn of the current phase
            is_final_turn_of_phase = turns_remaining == 1
            
            # Format turn display with phase transition warning
            if is_final_turn_of_phase:
                if current_phase == MovePhase.CASTING:
                    turn_display = "Final turn of casting"
                elif current_phase == MovePhase.ACTIVE:
                    turn_display = "Final active turn"
                elif current_phase == MovePhase.COOLDOWN:
                    turn_display = "Final cooldown turn"
                else:
                    turn_display = f"{turns_remaining} turn remaining"
            else:
                turn_display = f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"
            
            # Only show continuation message if we have turns remaining
            if turns_remaining > 0:
                # Format message with phase name in parentheses for clarity
                msg = self.format_effect_message(
                    f"{self.name} ({phase_name}) continues",
                    [turn_display]
                )
                messages.append(msg)
        
        return messages

    def on_expire(self, character) -> str:
        """Handle effect expiration"""
        print(f"[Move-{self.name}] Expiring from {character.name}")
        
        # Call parent method
        super().on_expire(character)
        
        # Clear targets list
        self.targets = []
        
        # Format expiry message
        message = self.format_effect_message(f"{self.name} has expired from {character.name}")
        
        return message

    @property
    def is_expired(self) -> bool:
        """Override to use our own expiry logic"""
        if super().is_expired:
            return True
            
        # Check if truly instant (no phases)
        is_truly_instant = not self.cast_time and not self.duration and not self.cooldown
        if is_truly_instant:
            if hasattr(self, '_internal_cache') and not self._internal_cache:
                # If it's instant and all operations have executed
                return True
                
        # Check if marked for removal
        if self.marked_for_removal:
            return True
            
        # Check timing handler
        if hasattr(self, 'timing_handler') and self.timing_handler.should_be_removed:
            return True
            
        # For instant effects that have been processed
        if (hasattr(self, 'timing_handler') and 
            self.timing_handler.is_instant() and
            not self.timing_handler.just_applied):
            return True
            
        return False

    async def execute_pending_operations(self) -> List[str]:
        """
        Execute all pending async operations stored in the internal cache.
        This should be called from an async context AFTER on_apply or on_turn_start.
        
        Returns:
            List[str]: Messages generated from async operations
        """
        messages = []
        
        # Process attack coroutines
        if 'attack_coroutine' in self._internal_cache:
            try:
                print(f"[Move-{self.name}] Executing pending attack operation")
                attack_messages = await self._internal_cache['attack_coroutine']
                
                if isinstance(attack_messages, list):
                    messages.extend(attack_messages)
                else:
                    messages.append(attack_messages)
                    
                # Clear the coroutine after execution
                del self._internal_cache['attack_coroutine']
            except Exception as e:
                print(f"[Move-{self.name}] Error executing attack coroutine: {str(e)}")
        
        # Process save coroutines
        if 'save_coroutine' in self._internal_cache:
            try:
                print(f"[Move-{self.name}] Executing pending save operation")
                save_messages = await self._internal_cache['save_coroutine']
                if save_messages:
                    if isinstance(save_messages, list):
                        messages.extend(save_messages)
                    else:
                        messages.append(save_messages)
                del self._internal_cache['save_coroutine']
            except Exception as e:
                print(f"[Move-{self.name}] Error executing save coroutine: {str(e)}")
        
        # For truly instant effects (no phases), mark for removal after execution
        is_truly_instant = not self.cast_time and not self.duration and not self.cooldown
        if is_truly_instant:
            print(f"[Move-{self.name}] Marking truly instant effect for removal after execution")
            self.marked_for_removal = True
        
        return messages