"""
Move-specific base effect implementation with advanced phase-based timing.

This module provides specialized state management for moves with precise
phase transitions and duration handling.
"""

from enum import Enum
from typing import Optional, List, Dict, Any, Tuple, Union
import logging

logger = logging.getLogger(__name__)

class MovePhase(Enum):
    """Phases for a move effect with distinct behaviors"""
    INSTANT = "instant"     # Immediate effect, no duration
    CASTING = "casting"     # Cast time phase - preparing the effect
    ACTIVE = "active"       # Active duration - main effect phase
    COOLDOWN = "cooldown"   # Cooldown phase - recovery period

class MoveEffectTiming:
    """
    Handles precise turn-by-turn phase timing for move effects.
    
    Key features:
    - Independent phase tracking (casting→active→cooldown)
    - Special handling for "during own turn" timing
    - Proper instant effect handling
    - Per-turn decrementation with proper buffering
    """
    
    def __init__(self, 
                 cast_time: Optional[int] = None,
                 duration: Optional[int] = None, 
                 cooldown: Optional[int] = None,
                 debug_mode: bool = True):
        """Initialize timing with phase durations"""
        self.debug_mode = debug_mode
        self.debug_id = f"MoveTiming-{id(self) % 10000}"
        
        # Store base durations
        self.cast_time = cast_time
        self.duration = duration
        self.cooldown = cooldown
        
        # Determine initial phase based on parameters
        if cast_time and cast_time > 0:
            self.current_phase = MovePhase.CASTING
            self.turns_remaining = cast_time
            self.original_turns = cast_time
        elif duration and duration > 0:
            self.current_phase = MovePhase.ACTIVE
            self.turns_remaining = duration
            self.original_turns = duration
        elif cooldown and cooldown > 0:
            self.current_phase = MovePhase.COOLDOWN
            self.turns_remaining = cooldown
            self.original_turns = cooldown
        else:
            self.current_phase = MovePhase.INSTANT
            self.turns_remaining = 0
            self.original_turns = 0
            
        # Tracking variables
        self.last_processed_round = None
        self.last_processed_turn = None
        self.just_activated = False      # Just entered active phase flag
        self.should_be_removed = False   # Flag to indicate removal
        self.marked_for_removal = False  # Flag to mark for removal
        self.last_transition_message = None  # Last transition message
        
        # Timing adjustment flags
        self.applied_during_own_turn = False
        self.timing_adjusted = False
        
        # User-facing duration tracking
        self.display_duration = self.duration 
        self.first_turn_processed = False  # Track if we've processed a turn yet
        
        # Application status
        self.just_applied = True  # Track if effect was just applied
        
        self.debug(f"Created timing with phase={self.current_phase.value}, remaining={self.turns_remaining}/{self.original_turns}")
    
    def debug(self, message):
        """Print debug message if debug mode is enabled"""
        if self.debug_mode:
            # Replace unicode arrow with text arrow to avoid encoding issues
            message = message.replace("→", "->")
            logger.info(f"[{self.debug_id}] {message}")
    
    def get_current_phase(self) -> MovePhase:
        """Get the current phase"""
        return self.current_phase
    
    def get_remaining_turns(self) -> int:
        """Get remaining turns in current phase"""
        return max(0, self.turns_remaining)
    
    def get_original_turns(self) -> int:
        """Get the original amount of turns for this phase"""
        return self.original_turns
    
    def get_display_turns(self) -> int:
        """
        Get user-facing duration that should be displayed.
        
        For effects applied during own turn, this may differ from
        internal turns_remaining value due to the turn buffering.
        """
        # For casting phase - show raw remaining turns
        if self.current_phase == MovePhase.CASTING:
            return self.get_remaining_turns()
            
        # For active phase - handle during own turn display
        if self.current_phase == MovePhase.ACTIVE:
            # For "during own turn" with duration adjustment
            if self.applied_during_own_turn and self.timing_adjusted:
                # If we're on the buffer turn, show one less turn
                return max(1, self.turns_remaining - 1)
            
        # Return actual turns remaining for all other cases
        return self.get_remaining_turns()
    
    def is_final_turn(self) -> bool:
        """
        Check if this is the final turn of the current phase.
        Used to display "Final turn" message.
        """
        # If we're in active phase with during-own-turn adjustment
        if self.current_phase == MovePhase.ACTIVE and self.applied_during_own_turn and self.timing_adjusted:
            # Final turn is when there are 2 internal turns remaining (1 + buffer)
            return self.turns_remaining == 2
        
        # Otherwise it's the final turn when there's just 1 turn left
        return self.turns_remaining == 1
    
    def adjust_timing(self, is_during_own_turn: bool = False) -> None:
        """
        Adjust durations based on when the effect is applied.
        
        For effects applied during a character's own turn, add a turn buffer
        to prevent the effect from immediately losing a turn at end-of-turn.
        
        Args:
            is_during_own_turn: Whether effect is applied during own turn
        """
        self.applied_during_own_turn = is_during_own_turn
        self.debug(f"Timing adjustment called: during_own_turn={is_during_own_turn}")
        
        # Only adjust if we haven't already
        if self.timing_adjusted:
            return
            
        # Only adjust ACTIVE phase or CASTING phase durations
        valid_phases = [MovePhase.ACTIVE, MovePhase.CASTING]
        if self.current_phase not in valid_phases:
            return
            
        # For effects applied during own turn
        if is_during_own_turn:
            self.debug(f"Pre-adjustment: turns_remaining={self.turns_remaining}")
            
            # For duration 1, special buffering needed
            if self.original_turns == 1:
                # Set to 2 so it lasts until after the next turn
                self.turns_remaining = 2
                self.debug(f"Duration 1 special case: buffered to 2 turns internally")
            else:
                # For longer durations, add 1 to internal duration as buffer
                self.turns_remaining += 1
                self.debug(f"Added turn buffer: now {self.turns_remaining} turns")
            
            self.timing_adjusted = True
            self.debug(f"Timing adjusted for during-own-turn: internal={self.turns_remaining}, display={self.display_duration}")
    
    def process_turn(self, round_number, turn_name) -> Tuple[bool, Optional[str]]:
        """
        Process turn advancement and phase transitions.
        
        This is the heart of the timing system, handling:
        1. Turn decrementation with proper buffering
        2. Phase transitions (casting → active → cooldown)
        3. Effect expiry
        
        Returns:
            (did_transition, transition_message)
        """
        # Skip if already processed this turn
        if (self.last_processed_round == round_number and 
            self.last_processed_turn == turn_name):
            self.debug(f"Already processed round {round_number}, turn {turn_name}")
            return False, None
            
        # Mark as processed
        self.last_processed_round = round_number
        self.last_processed_turn = turn_name
        
        # Reset activation flag from last turn
        self.just_activated = False
        
        # Reset the just_applied flag if this isn't our first turn
        if self.first_turn_processed:
            self.just_applied = False
        
        # Mark that we've processed at least one turn
        self.first_turn_processed = True
        
        # Handle INSTANT phase - these expire immediately after processing
        if self.current_phase == MovePhase.INSTANT:
            # Instant effects just need to complete
            message = "completes"
            self.should_be_removed = True
            self.debug(f"Instant effect marked for removal")
            return True, message
            
        # Show debug before decrementing
        self.debug(f"BEFORE decrement: phase={self.current_phase.value}, turns_remaining={self.turns_remaining}/{self.original_turns}")
        
        # Decrement turns remaining
        old_turns = self.turns_remaining
        self.turns_remaining -= 1
        self.debug(f"AFTER decrement: {old_turns} -> {self.turns_remaining}")
        
        # Check for phase transition when turns_remaining reaches 0
        if self.turns_remaining <= 0:
            old_phase = self.current_phase
            message = None
            
            # Handle phase transitions based on current phase
            if self.current_phase == MovePhase.CASTING:
                self.debug(f"Cast time completed. Duration={self.duration}, Cooldown={self.cooldown}")
                
                # Reset first turn processed for the new phase
                self.first_turn_processed = False
                
                # FIX: Properly transition to active phase even when duration is None
                # If duration is specified, use it, otherwise default to 1
                if self.duration is not None:
                    use_duration = self.duration
                else:
                    # If no duration specified, use 1 for single-turn active phase
                    use_duration = 1
                    self.duration = 1
                    
                # After casting, go to ACTIVE phase if it should have any duration
                if use_duration > 0:
                    self.current_phase = MovePhase.ACTIVE
                    self.turns_remaining = use_duration
                    self.original_turns = use_duration
                    
                    # Apply timing adjustment if needed
                    if self.applied_during_own_turn and not self.timing_adjusted:
                        self.adjust_timing(True)
                        
                    message = "activates!"
                    self.just_activated = True
                    self.debug(f"Transitioned to ACTIVE with {self.turns_remaining} turns remaining")
                elif self.cooldown and self.cooldown > 0:
                    # Skip active phase if duration is 0, go straight to cooldown
                    self.current_phase = MovePhase.COOLDOWN
                    self.turns_remaining = self.cooldown
                    self.original_turns = self.cooldown
                    message = "enters cooldown"
                    self.debug(f"Transitioned to COOLDOWN with {self.turns_remaining} turns remaining")
                else:
                    # No further phases - mark for removal
                    message = "completes"
                    self.should_be_removed = True
                    self.debug(f"No further phases, marked for removal")
                    
            elif self.current_phase == MovePhase.ACTIVE:
                self.debug(f"Active duration completed. Cooldown={self.cooldown}")
                
                # Reset first turn processed for the new phase
                self.first_turn_processed = False
                
                # After active, go to COOLDOWN if there is one, otherwise remove
                if self.cooldown and self.cooldown > 0:
                    self.current_phase = MovePhase.COOLDOWN
                    self.turns_remaining = self.cooldown
                    self.original_turns = self.cooldown
                    message = "enters cooldown"
                    self.debug(f"Transitioned to COOLDOWN with {self.turns_remaining} turns remaining")
                else:
                    # No cooldown phase - mark for removal
                    message = "wears off"
                    self.should_be_removed = True
                    self.debug(f"No cooldown, marked for removal")
                    
            elif self.current_phase == MovePhase.COOLDOWN:
                self.debug(f"Cooldown completed")
                
                # After cooldown, always remove the effect
                message = "cooldown has ended"
                self.should_be_removed = True
                self.debug(f"Cooldown ended, marked for removal")
            
            self.last_transition_message = message
            self.debug(f"Transition: {old_phase.value} -> {self.current_phase.value} with message: {message}")
            
            return True, message
            
        self.debug(f"No transition needed. Remaining turns: {self.turns_remaining}")
        return False, None
    
    def is_instant(self) -> bool:
        """Check if this is an instant effect"""
        return self.current_phase == MovePhase.INSTANT
    
    def is_during_phase(self, phase: MovePhase) -> bool:
        """Check if we're in the specified phase"""
        return self.current_phase == phase
    
    def get_turns_to_next_phase(self) -> int:
        """Get turns remaining before next phase"""
        return self.turns_remaining
    
    def to_dict(self) -> dict:
        """Convert timing data to dictionary for storage"""
        return {
            "phase": self.current_phase.value,
            "turns_remaining": self.turns_remaining,
            "original_turns": self.original_turns,
            "cast_time": self.cast_time,
            "duration": self.duration,
            "cooldown": self.cooldown,
            "applied_during_own_turn": self.applied_during_own_turn,
            "timing_adjusted": self.timing_adjusted,
            "display_duration": self.display_duration,
            "should_be_removed": self.should_be_removed,
            "first_turn_processed": self.first_turn_processed,
            "just_applied": self.just_applied
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create timing object from dictionary data"""
        # Create instance with base parameters
        instance = cls(
            cast_time=data.get("cast_time"),
            duration=data.get("duration"),
            cooldown=data.get("cooldown")
        )
        
        # Restore phase
        try:
            phase_value = data.get("phase", "instant")
            instance.current_phase = MovePhase(phase_value)
        except (ValueError, TypeError):
            instance.current_phase = MovePhase.INSTANT
            
        # Restore other properties
        instance.turns_remaining = data.get("turns_remaining", 0)
        instance.original_turns = data.get("original_turns", instance.turns_remaining)
        instance.applied_during_own_turn = data.get("applied_during_own_turn", False)
        instance.timing_adjusted = data.get("timing_adjusted", False)
        instance.display_duration = data.get("display_duration", instance.duration)
        instance.should_be_removed = data.get("should_be_removed", False)
        instance.first_turn_processed = data.get("first_turn_processed", False)
        instance.just_applied = data.get("just_applied", False)
        
        return instance
