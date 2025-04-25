"""
Move state management system for tracking phases of move effects.
"""

from enum import Enum
from typing import Optional, Tuple

class MoveState(Enum):
    """Possible states for a move effect"""
    INSTANT = "instant"     # No cast time or duration
    CASTING = "casting"     # In cast time phase
    ACTIVE = "active"       # Active duration
    COOLDOWN = "cooldown"   # In cooldown phase

# Add MovePhase as alias for backward compatibility
MovePhase = MoveState  # For backward compatibility with previous codebase

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
        """Initialize state machine with phase durations"""
        self.debug_mode = debug_mode
        self.debug_id = f"StateMachine-{id(self) % 10000}"
        
        # Store base durations
        self.cast_time = cast_time
        self.duration = duration
        self.cooldown = cooldown
        
        # Set initial state based on parameters
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
        Process a character's turn, updating state and duration.
        
        Returns:
            (did_transition, transition_message)
        """
        # Skip if already processed this turn
        if (self.last_processed_round == round_number and 
            self.last_processed_turn == turn_name):
            self.debug_print(f"Already processed round {round_number}, turn {turn_name}")
            return False, None
            
        # Mark as processed
        self.last_processed_round = round_number
        self.last_processed_turn = turn_name
        
        # Reset the activation flag from the last turn
        self.was_just_activated = False
        
        # Decrement turns remaining
        self.turns_remaining -= 1
        self.debug_print(f"Decremented turns_remaining to {self.turns_remaining}")
        
        # Print more debug info to track state
        self.debug_print(f"Current state: {self.state.value}, Remaining: {self.turns_remaining}")
        
        # Check for state transition when turns_remaining reaches 0
        if self.turns_remaining <= 0:
            old_state = self.state
            message = None
            
            # Handle state transitions based on current state
            if self.state == MoveState.CASTING:
                self.debug_print("Cast time completed, transitioning...")
                # After casting, go to ACTIVE if there's duration, or COOLDOWN if not
                if self.duration and self.duration > 0:
                    self.state = MoveState.ACTIVE
                    self.turns_remaining = self.duration
                    
                    # Apply duration adjustment for effects used during own turn
                    if self.used_during_own_turn and not self.duration_adjusted:
                        self.adjust_for_during_own_turn(True)
                        
                    message = "activates!"
                    self.was_just_activated = True  # Mark as just activated
                    self.debug_print(f"Transitioned to ACTIVE with {self.turns_remaining} turns remaining")
                elif self.cooldown and self.cooldown > 0:
                    self.state = MoveState.COOLDOWN
                    self.turns_remaining = self.cooldown
                    message = "enters cooldown"
                    self.debug_print(f"Transitioned to COOLDOWN with {self.turns_remaining} turns remaining")
                else:
                    # No further phases - mark for removal and use "completes" message
                    message = "completes"
                    self.should_be_removed = True
                    self.debug_print("No further phases, marked for removal")
                    
            elif self.state == MoveState.ACTIVE:
                self.debug_print("Active duration completed, transitioning...")
                # After active, go to COOLDOWN if there is one, otherwise remove
                if self.cooldown and self.cooldown > 0:
                    self.state = MoveState.COOLDOWN
                    self.turns_remaining = self.cooldown
                    message = "enters cooldown"
                    self.debug_print(f"Transitioned to COOLDOWN with {self.turns_remaining} turns remaining")
                else:
                    # No cooldown phase - mark for removal and use "wears off" message
                    message = "wears off"
                    self.should_be_removed = True
                    self.debug_print("No cooldown, marked for removal")
                    
            elif self.state == MoveState.COOLDOWN:
                self.debug_print("Cooldown completed, transitioning...")
                # After cooldown, always remove the effect
                message = "cooldown has ended"
                self.should_be_removed = True
                self.debug_print("Cooldown ended, marked for removal")
            
            self.transition_message = message
            self.debug_print(f"Transition: {old_state.value} → {self.state.value} with message: {message}")
            if self.should_be_removed:
                self.debug_print("Effect marked for removal during transition")
            
            return True, message
            
        self.debug_print(f"No transition needed. Remaining turns: {self.turns_remaining}")
        return False, None
    
    def to_dict(self) -> dict:
        """Convert state machine to dictionary for storage"""
        return {
            "state": self.state.value,
            "turns_remaining": self.turns_remaining,
            "cast_time": self.cast_time,
            "duration": self.duration,
            "cooldown": self.cooldown,
            "used_during_own_turn": self.used_during_own_turn,
            "duration_adjusted": self.duration_adjusted,
            "display_duration": self.display_duration,
            "should_be_removed": self.should_be_removed
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create state machine from dictionary data"""
        # Create instance with base parameters
        instance = cls(
            cast_time=data.get("cast_time"),
            duration=data.get("duration"),
            cooldown=data.get("cooldown")
        )
        
        # Restore state
        try:
            state_value = data.get("state", "instant")
            instance.state = MoveState(state_value)
        except (ValueError, TypeError):
            instance.state = MoveState.INSTANT
            
        # Restore other properties
        instance.turns_remaining = data.get("turns_remaining", 0)
        instance.used_during_own_turn = data.get("used_during_own_turn", False)
        instance.duration_adjusted = data.get("duration_adjusted", False)
        instance.display_duration = data.get("display_duration", instance.duration)
        instance.should_be_removed = data.get("should_be_removed", False)
        
        return instance
