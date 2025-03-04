"""
## src/core/effects/move.py

Move Effect System Implementation with Async Pattern Improvements

Key Features:
- Phase-based duration tracking (cast -> active -> cooldown)
- Resource cost handling
- Attack roll processing with stat mods
- Multi-target support
- Consistent async/sync patterns

Implementation Mandates:
- Clear async boundaries
- Consistent lifecycle methods
- Proper state transitions
- Uniform return values
"""

from typing import Optional, List, Dict, Any, Tuple, Set
from enum import Enum, auto
import logging
import inspect

from core.effects.base import BaseEffect, EffectCategory, EffectTiming
from core.effects.condition import ConditionType
from utils.advanced_dice.calculator import DiceCalculator

logger = logging.getLogger(__name__)

class MoveState(Enum):
    """Possible states for a move effect"""
    INSTANT = "instant"     # No cast time or duration
    CASTING = "casting"     # In cast time phase
    ACTIVE = "active"       # Active duration
    COOLDOWN = "cooldown"   # In cooldown phase

class RollTiming(Enum):
    """When to process attack/damage rolls"""
    INSTANT = "instant"     # Roll immediately on use
    ACTIVE = "active"       # Roll when active phase starts
    PER_TURN = "per_turn"   # Roll each turn during duration

class PhaseManager:
    """
    Handles state transitions between move phases.
    
    This class encapsulates the logic for:
    - Tracking phase durations
    - Managing state transitions
    - Computing remaining time
    - Determining when phases should expire
    """
    def __init__(self):
        self.phases = {}
        self.state = MoveState.INSTANT
        self.debug_mode = False
        
    def set_phase(self, state: MoveState, duration: Optional[int]) -> None:
        """Set up a phase with its duration"""
        if duration is not None and duration > 0:
            self.phases[state] = {"duration": duration, "turns_completed": 0}
    
    def get_current_phase(self) -> Optional[Dict]:
        """Get current phase info"""
        return self.phases.get(self.state)
    
    def get_remaining_turns(self) -> int:
        """Get remaining turns in current phase"""
        phase = self.get_current_phase()
        if not phase:
            return 0
        # Calculate remaining turns as the difference between duration and completed turns
        remaining = max(0, phase["duration"] - phase["turns_completed"])
        if self.debug_mode:
            print(f"DEBUG: Remaining turns in {self.state.value} phase: {remaining} " 
                  f"({phase['turns_completed']}/{phase['duration']} completed)")
        return remaining

    def increment_turn(self) -> None:
        """Increment turn counter for current phase"""
        phase = self.get_current_phase()
        if phase:
            # Record the previous value for debugging
            old_value = phase["turns_completed"]
            # Increment the counter
            phase["turns_completed"] += 1
            if self.debug_mode:
                print(f"DEBUG: Incremented {self.state.value} phase from {old_value} to {phase['turns_completed']}/{phase['duration']} turns")

    def should_transition(self) -> bool:
        """
        Check if current phase should transition to next.
        FIXED: Only transition when turns_completed EQUALS duration (not >=)
        """
        phase = self.get_current_phase()
        if not phase:
            return False
        
        # FIXED: Only transition on EXACT completion of duration
        completed = phase["turns_completed"] == phase["duration"]
        
        if self.debug_mode:
            print(f"DEBUG: Phase transition check for {self.state.value} - "
                  f"{phase['turns_completed']}/{phase['duration']} - Should transition: {completed}")
            
        return completed
    
    def transition_state(self) -> Tuple[bool, Optional[str], Optional[MoveState]]:
        """
        Process state transition if needed.
        Returns (did_transition, message, next_state)
        """
        phase = self.get_current_phase()
        if not phase:
            return False, None, None
            
        # Only transition when turns_completed EQUALS duration (not >=)
        if phase["turns_completed"] != phase["duration"]:
            return False, None, None
        
        # Now determine next state and message
        next_state = None
        message = None
        
        # Find next valid state
        if self.state == MoveState.CASTING:
            if MoveState.ACTIVE in self.phases:
                next_state = MoveState.ACTIVE
                message = "activates!"
            elif MoveState.COOLDOWN in self.phases:
                next_state = MoveState.COOLDOWN
                message = "enters cooldown"
            else:
                message = "completes"
                
        elif self.state == MoveState.ACTIVE:
            if MoveState.COOLDOWN in self.phases:
                next_state = MoveState.COOLDOWN
                message = "enters cooldown"
            else:
                message = "wears off"
                
        elif self.state == MoveState.COOLDOWN:
            message = "cooldown has ended"
        
        # Update state if transitioning
        if next_state:
            old_state = self.state
            self.state = next_state
            
            # Reset phase tracking for the new phase - start at 0 turns completed
            if phase := self.phases.get(next_state):
                # Important: We're starting the new phase with 0 turns completed
                phase["turns_completed"] = 0
                
            if self.debug_mode:
                print(f"DEBUG: Transitioned from {old_state.value} to {next_state.value} - Reset to 0 turns completed")
                
        return True, message, next_state

class CombatProcessor:
    """
    Handles attack rolls and damage calculations.
    
    This class encapsulates:
    - Attack roll processing
    - Target handling
    - Damage calculation
    - Heat tracking
    
    Supports both sync and async patterns for flexibility.
    """
    def __init__(self):
        self.targets_hit = set()
        self.attacks_this_turn = 0
        self.aoe_mode = 'single'
        
    async def process_attack(self, 
                           source, 
                           targets,
                           attack_roll,
                           damage,
                           crit_range,
                           reason,
                           enable_heat_tracking=False) -> List[str]:
        """Process attack roll and damage"""
        # Skip if no attack roll defined
        if not attack_roll:
            return []

        # Track attack count
        self.attacks_this_turn += 1
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
        message, hit_results = await AttackCalculator.process_attack(params)
        messages.append(message)
        
        # Process hit tracking for heat mechanic
        if hit_results:
            # Extract hit targets
            for target_name, hit_data in hit_results.items():
                if hit_data.get('hit', False):
                    self.targets_hit.add(target_name)
        
        # Handle heat tracking if enabled
        if enable_heat_tracking and self.targets_hit:
            # Source heat (attunement)
            if not hasattr(source, 'heat_stacks'):
                source.heat_stacks = 0
            
            source.heat_stacks += 1
            
            # Target heat (vulnerability) for each hit target
            for target_name in self.targets_hit:
                target = next((t for t in targets if t.name == target_name), None)
                if target:
                    if not hasattr(target, 'heat_stacks'):
                        target.heat_stacks = 0
                    target.heat_stacks += 1
        
        return messages

class MoveEffect(BaseEffect):
    """
    Handles move execution with phase-based state tracking.
    
    This redesigned implementation provides:
    - Clear sync/async boundaries
    - Consistent state transitions
    - Proper resource handling
    - Reliable attack roll processing
    
    IMPLEMENTATION NOTES:
    - All public lifecycle methods (on_apply, etc.) are now SYNC
    - Internal processing uses async where needed
    - Phase transitions are handled by PhaseManager
    - Combat processing is handled by CombatProcessor
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
            enable_heat_tracking: bool = False
        ):
            # Create specialized managers
            self.phase_mgr = PhaseManager()
            self.combat = CombatProcessor()
            
            # Set up phases
            if cast_time:
                self.phase_mgr.set_phase(MoveState.CASTING, cast_time)
                self.phase_mgr.state = MoveState.CASTING
            elif duration:
                self.phase_mgr.set_phase(MoveState.ACTIVE, duration)
                self.phase_mgr.state = MoveState.ACTIVE
            else:
                self.phase_mgr.state = MoveState.INSTANT
                
            # Set up additional phases if needed
            if duration and self.phase_mgr.state != MoveState.ACTIVE:
                self.phase_mgr.set_phase(MoveState.ACTIVE, duration)
            if cooldown:
                self.phase_mgr.set_phase(MoveState.COOLDOWN, cooldown)
            
            # Initial duration is based on first phase
            initial_duration = cast_time if cast_time else duration
            if initial_duration is None:
                initial_duration = cooldown if cooldown else 1  # Default to 1 for INSTANT
            
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
            self.enable_heat_tracking = enable_heat_tracking
            
            # Configure combat settings
            self.combat.aoe_mode = 'single'
            
            # Tracking variables
            self.last_processed_round = None
            self.last_processed_turn = None
            self.marked_for_removal = False
            self._internal_cache = {}  # Cache for attack results
            
            # Debug flag - can be toggled for verbose output
            self.debug = False

    # Property accessors for state
    @property
    def state(self) -> MoveState:
        """Current move state"""
        return self.phase_mgr.state
    
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
        return self.phase_mgr.get_remaining_turns()
    
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
            if phase := self.phase_mgr.get_current_phase():
                remaining = phase["duration"] - phase["turns_completed"]
                return False, f"On cooldown ({remaining} turns remaining)"
        
        # Check uses if tracked
        if self.uses is not None:
            if self.uses_remaining is None:
                self.uses_remaining = self.uses
            if self.uses_remaining <= 0:
                return False, f"No uses remaining (0/{self.uses})"
        
        return True, None

    # Core logic for determining if attacks should roll
    def should_roll(self, state: MoveState, force_roll: bool = False) -> bool:
        """Determine if we should roll based on timing and state"""
        if force_roll:
            return True
            
        if self.roll_timing == RollTiming.INSTANT:
            return state == MoveState.INSTANT
        elif self.roll_timing == RollTiming.ACTIVE:
            return state == MoveState.ACTIVE
        elif self.roll_timing == RollTiming.PER_TURN:
            return state == MoveState.ACTIVE
            
        return False
    
    # LIFECYCLE METHODS - These are now sync for consistent interfaces
    
    def on_apply(self, character, round_number: int) -> str:
        """
        Initial effect application - synchronous interface.
        This method handles the async operations internally.
        """
        # Initialize timing
        self.initialize_timing(round_number, character.name)
        
        # Apply costs and format messages
        costs = []
        details = []
        timing_info = []
        
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
            
        # Add timing info
        phase_timing = self.phase_mgr.phases
        if MoveState.CASTING in phase_timing:
            cast_time = phase_timing[MoveState.CASTING]["duration"]
            timing_info.append(f"🔄 {cast_time}T Cast")
        if MoveState.ACTIVE in phase_timing:
            duration = phase_timing[MoveState.ACTIVE]["duration"]
            timing_info.append(f"⏳ {duration}T Duration")
        if MoveState.COOLDOWN in phase_timing:
            cooldown = phase_timing[MoveState.COOLDOWN]["duration"]
            timing_info.append(f"⌛ {cooldown}T Cooldown")
            
        # Format target info if any
        if self.targets:
            target_names = ", ".join(t.name for t in self.targets)
            details.append(f"Target{'s' if len(self.targets) > 1 else ''}: {target_names}")
            
        # Process instant attack rolls here if needed
        attack_messages = []
        if self.attack_roll and self.roll_timing == RollTiming.INSTANT:
            # Process the attack using our CombatProcessor
            # Store the coroutine in the cache for later processing
            self._internal_cache['attack_coroutine'] = self.combat.process_attack(
                source=character,
                targets=self.targets,
                attack_roll=self.attack_roll,
                damage=self.damage,
                crit_range=self.crit_range,
                reason=self.name,
                enable_heat_tracking=self.enable_heat_tracking
            )
                    
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
        
        # Return message (without attack messages that need async)
        return formatted_message
    
    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process start of turn effects - returns list of messages"""
        # Store tracking values
        self.last_processed_round = round_number
        self.last_processed_turn = turn_name
        
        # Only process effect changes on the owner's turn
        if character.name != turn_name:
            return []

        messages = []
        
        # First, check if we need to transition phases BEFORE showing any messages
        # This ensures we start the turn in the proper phase
        did_transition, transition_msg, next_state = self.phase_mgr.transition_state()
        if did_transition and transition_msg:
            messages.append(self.format_effect_message(f"{self.name} {transition_msg}"))
            
            # If we transitioned to active, prepare attack roll if timing is ACTIVE
            if next_state == MoveState.ACTIVE and self.attack_roll and self.roll_timing == RollTiming.ACTIVE:
                # Process the attack using CombatProcessor
                # Store the coroutine in the cache for later async processing
                self._internal_cache['attack_coroutine'] = self.combat.process_attack(
                    source=character,
                    targets=self.targets,
                    attack_roll=self.attack_roll,
                    damage=self.damage,
                    crit_range=self.crit_range,
                    reason=self.name,
                    enable_heat_tracking=self.enable_heat_tracking
                )
    
        # Now handle the current state (which might have just changed)
        if self.state == MoveState.CASTING:
            # Show casting message with turns remaining
            remaining = self.get_remaining_turns()
            if not any("activates" in msg for msg in messages):  # Don't show if we just activated
                cast_msg = self.format_effect_message(
                    f"Casting {self.name}",
                    [f"{remaining} turns remaining"]
                )
                messages.append(cast_msg)
                
        elif self.state == MoveState.ACTIVE:
            # Process attack if timing is ACTIVE and we didn't just transition
            # This handles the case where we were already in ACTIVE state
            if self.attack_roll and self.roll_timing == RollTiming.ACTIVE and not any("activates" in msg for msg in messages):
                # Process the attack - store for later async processing
                self._internal_cache['attack_coroutine'] = self.combat.process_attack(
                    source=character,
                    targets=self.targets,
                    attack_roll=self.attack_roll,
                    damage=self.damage,
                    crit_range=self.crit_range,
                    reason=self.name,
                    enable_heat_tracking=self.enable_heat_tracking
                )
            
            # Only add active message if we didn't just transition
            if not any("activates" in msg for msg in messages):
                # Show active message with description and turns remaining
                remaining = self.get_remaining_turns()
                
                details = []
                # Add description
                if self.description:
                    # Split description by semicolons for bullet points
                    if ';' in self.description:
                        for part in self.description.split(';'):
                            part = part.strip()
                            if part:
                                details.append(part)
                    else:
                        details.append(self.description)
                
                # Add remaining turns
                details.append(f"{remaining} turns remaining")
                
                active_msg = self.format_effect_message(
                    f"{self.name} active",
                    details
                )
                messages.append(active_msg)
            
            # Process per-turn attack rolls
            if self.attack_roll and self.roll_timing == RollTiming.PER_TURN:
                # Process the attack - store for later async processing
                self._internal_cache['attack_coroutine'] = self.combat.process_attack(
                    source=character,
                    targets=self.targets,
                    attack_roll=self.attack_roll,
                    damage=self.damage,
                    crit_range=self.crit_range,
                    reason=self.name,
                    enable_heat_tracking=self.enable_heat_tracking
                )
        
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Handle phase transitions and duration tracking.
        """
        # Store tracking values
        self.last_processed_round = round_number
        self.last_processed_turn = turn_name
        
        # Only process turn end effects for the effect owner
        if character.name != turn_name:
            return []
            
        messages = []
        
        # Complete this turn for the current phase
        self.phase_mgr.increment_turn()
        
        # Get remaining turns for messaging
        remaining = self.get_remaining_turns()
        
        # Handle phase transitions if the phase is complete
        did_transition, transition_msg, next_state = self.phase_mgr.transition_state()
        if did_transition and transition_msg:
            messages.append(self.format_effect_message(f"{self.name} {transition_msg}"))
        
            # If we've completed the cooldown, mark for removal
            if self.state == MoveState.COOLDOWN and transition_msg == "cooldown has ended":
                self.marked_for_removal = True
                if hasattr(self, 'timing'):
                    self.timing.duration = 0
        else:
            # If phase not complete, show appropriate progress message
            if self.state == MoveState.CASTING:
                if remaining > 0:
                    messages.append(self.format_effect_message(
                        f"Casting {self.name}",
                        [f"{remaining} turns remaining"]
                    ))
                    
            elif self.state == MoveState.ACTIVE:
                if remaining > 0:
                    messages.append(self.format_effect_message(
                        f"{self.name} continues",
                        [f"{remaining} turns remaining"]
                    ))
                    
            elif self.state == MoveState.COOLDOWN:
                if remaining > 0:
                    messages.append(self.format_effect_message(
                        f"{self.name} cooldown",
                        [f"{remaining} turns remaining"]
                    ))
        
        return messages
        
    @property
    def is_expired(self) -> bool:
        """
        Check if move effect is fully expired.
        A move is expired when marked for removal or all phases complete.
        FIXED: Only check exact completion, not >= condition
        """
        if self.marked_for_removal:
            return True
            
        if self.state == MoveState.INSTANT:
            return True
            
        current_phase = self.phase_mgr.get_current_phase()
        if not current_phase:
            return True
            
        # FIXED: Check if we're in the final phase with completed duration
        # Using equality check instead of >= to prevent early expiration
        if self.state == MoveState.COOLDOWN:
            return current_phase["turns_completed"] == current_phase["duration"]
        elif self.state == MoveState.ACTIVE and MoveState.COOLDOWN not in self.phase_mgr.phases:
            return current_phase["turns_completed"] == current_phase["duration"]
        elif self.state == MoveState.CASTING and MoveState.ACTIVE not in self.phase_mgr.phases and MoveState.COOLDOWN not in self.phase_mgr.phases:
            return current_phase["turns_completed"] == current_phase["duration"]
            
        return False

    def on_expire(self, character) -> str:
        """Handle move expiry and ensure complete removal"""
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
        
        # Add phase data
        phase_data = {state.value: phase for state, phase in self.phase_mgr.phases.items()}
        
        # Add move-specific data
        data.update({
            "state": self.state.value,
            "phases": phase_data,
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
            "aoe_mode": self.combat.aoe_mode,
            "enable_heat_tracking": self.enable_heat_tracking,
            "marked_for_removal": self.marked_for_removal,
            "last_processed_round": self.last_processed_round,
            "last_processed_turn": self.last_processed_turn
        })
        
        # Remove None values to save space
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> 'MoveEffect':
        """Create from dictionary data"""
        try:
            # Extract phase durations
            phases = data.get('phases', {})
            cast_time = phases.get(MoveState.CASTING.value, {}).get('duration')
            duration = phases.get(MoveState.ACTIVE.value, {}).get('duration')
            cooldown = phases.get(MoveState.COOLDOWN.value, {}).get('duration')
            
            # Extract combat data
            attack_roll = data.get('attack_roll')
            damage = data.get('damage')
            crit_range = data.get('crit_range', 20)
            save_type = data.get('save_type')
            save_dc = data.get('save_dc')
            half_on_save = data.get('half_on_save', False)
            conditions = data.get('conditions', [])
            
            # Normalize roll timing
            roll_timing_str = data.get('roll_timing', RollTiming.ACTIVE.value)
            
            # Create base effect
            effect = cls(
                name=data['name'],
                description=data.get('description', ''),
                star_cost=data.get('star_cost', 0),
                mp_cost=data.get('mp_cost', 0),
                hp_cost=data.get('hp_cost', 0),
                cast_time=cast_time,
                duration=duration,
                cooldown=cooldown,
                cast_description=data.get('cast_description'),
                attack_roll=attack_roll,
                damage=damage, 
                crit_range=crit_range,
                save_type=save_type,
                save_dc=save_dc,
                half_on_save=half_on_save,
                conditions=[ConditionType(c) if isinstance(c, str) else c for c in conditions] if conditions else [],
                roll_timing=roll_timing_str,
                uses=data.get('uses'),
                enable_heat_tracking=data.get('enable_heat_tracking', False)
            )
            
            # Restore state
            if state_value := data.get('state'):
                effect.phase_mgr.state = MoveState(state_value)
                
            # Restore phase progress
            for state_str, phase_info in phases.items():
                state = MoveState(state_str)
                if state in effect.phase_mgr.phases:
                    effect.phase_mgr.phases[state]["turns_completed"] = phase_info.get('turns_completed', 0)
            
            # Restore usage tracking
            effect.uses_remaining = data.get('uses_remaining')
            
            # Restore combat state
            effect.combat.targets_hit = set(data.get('targets_hit', []))
            effect.combat.aoe_mode = data.get('aoe_mode', 'single')
            
            # Restore timing information
            if timing_data := data.get('timing'):
                effect.timing = EffectTiming(**timing_data)
                
            effect.last_processed_round = data.get('last_processed_round')
            effect.last_processed_turn = data.get('last_processed_turn')
            effect.marked_for_removal = data.get('marked_for_removal', False)
                
            return effect
            
        except Exception as e:
            logger.error(f"Error reconstructing MoveEffect: {str(e)}")
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
                attack_messages = await self._internal_cache['attack_coroutine']
                messages.extend(attack_messages)
                del self._internal_cache['attack_coroutine']
            except Exception as e:
                logger.error(f"Error processing attack coroutine: {str(e)}")
                
        return messages