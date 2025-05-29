"""
Consolidated timing system for move effects.

This replaces both base.py and state.py with a single, clear timing implementation.

Key principles:
- Turn START: Decrements duration, marks transitions, processes attacks
- Turn END: Shows status, executes transitions, handles removal
- No double processing - each method called once per turn
"""

import logging
from enum import Enum
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class MovePhase(Enum):
    """Phases for a move effect"""
    INSTANT = "instant"     # Immediate effect, no duration
    CASTING = "casting"     # Cast time phase - preparing the effect
    ACTIVE = "active"       # Active duration - main effect phase
    COOLDOWN = "cooldown"   # Cooldown phase - recovery period

class RollTiming(Enum):
    """When to process attack rolls"""
    INSTANT = "instant"     # Roll immediately on use
    ACTIVE = "active"       # Roll when active phase starts
    PER_TURN = "per_turn"   # Roll each turn during duration

class MoveEffectTiming:
    """
    Consolidated timing system for move effects.
    
    Clear separation of responsibilities:
    - Turn START: Decrements, marks changes, processes attacks
    - Turn END: Shows status, executes changes, handles removal
    """
    
    def __init__(self, 
                 cast_time: Optional[int] = None,
                 duration: Optional[int] = None, 
                 cooldown: Optional[int] = None,
                 debug_mode: bool = True):
        """Initialize timing with phase durations"""
        self.debug_mode = debug_mode
        self.debug_id = f"MoveTiming-{id(self) % 10000}"
        
        # Store original parameters
        self.cast_time = cast_time
        self.duration = duration
        self.cooldown = cooldown
        
        # Determine initial phase and duration
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
        
        # State tracking
        self.should_be_removed = False
        self.pending_transition = None  # (new_phase, new_duration)
        self.just_transitioned = False  # Flag for transition messages
        
        # Turn tracking to prevent double processing
        self.last_processed_round = None
        self.last_processed_turn = None
        self.turn_start_processed = False
        self.turn_end_processed = False
        
        # Compatibility attributes for existing manager code
        self.applied_during_own_turn = False
        
        self.debug(f"Created with phase={self.current_phase.value}, turns={self.turns_remaining}")
    
    def debug(self, message):
        """Print debug message if enabled"""
        if self.debug_mode:
            logger.info(f"[{self.debug_id}] {message}")
    
    def get_current_phase(self) -> MovePhase:
        """Get the current phase"""
        return self.current_phase
    
    def get_remaining_turns(self) -> int:
        """Get remaining turns in current phase"""
        return max(0, self.turns_remaining)
    
    def process_turn_start(self, round_number: int, turn_name: str, character_name: str) -> Tuple[bool, bool]:
        """
        Process turn START - Decrements and marks for changes.
        
        Returns:
            (should_process_attacks, just_activated)
        """
        # Only process for character's own turn
        if character_name != turn_name:
            return False, False
        
        # Reset turn flags for new turn
        if (self.last_processed_round != round_number or 
            self.last_processed_turn != turn_name):
            self.turn_start_processed = False
            self.turn_end_processed = False
            self.last_processed_round = round_number
            self.last_processed_turn = turn_name
        
        # Skip if already processed turn start
        if self.turn_start_processed:
            self.debug(f"Turn start already processed for R{round_number}, T{turn_name}")
            return False, False
        
        self.turn_start_processed = True
        self.just_transitioned = False
        
        # Handle INSTANT phase
        if self.current_phase == MovePhase.INSTANT:
            self.should_be_removed = True
            self.debug("Instant effect marked for removal")
            return False, False
        
        # Decrement turns
        self.debug(f"BEFORE decrement: phase={self.current_phase.value}, turns={self.turns_remaining}")
        
        if self.turns_remaining > 0:
            self.turns_remaining -= 1
            self.debug(f"AFTER decrement: turns={self.turns_remaining}")
            
            # Mark for transition if turns hit 0
            if self.turns_remaining <= 0:
                self._mark_for_transition()
        
        # Determine if attacks should be processed
        should_process_attacks = self._should_process_attacks_at_start()
        just_activated = self.just_transitioned and self.current_phase == MovePhase.ACTIVE
        
        return should_process_attacks, just_activated
    
    def process_turn_end(self, round_number: int, turn_name: str, character_name: str) -> Tuple[Optional[str], bool]:
        """
        Process turn END - Shows status and executes transitions.
        
        Returns:
            (status_message, should_remove)
        """
        # Only process for character's own turn
        if character_name != turn_name:
            return None, False
        
        # Skip if already processed turn end
        if self.turn_end_processed:
            self.debug(f"Turn end already processed for R{round_number}, T{turn_name}")
            return None, self.should_be_removed
        
        self.turn_end_processed = True
        
        # Execute pending transition
        if self.pending_transition:
            new_phase_name, new_turns = self.pending_transition
            old_phase = self.current_phase
            
            if new_phase_name == 'active':
                self.current_phase = MovePhase.ACTIVE
                self.turns_remaining = new_turns
                message = "activates"
                self.just_transitioned = True
            elif new_phase_name == 'cooldown':
                self.current_phase = MovePhase.COOLDOWN
                self.turns_remaining = new_turns
                message = "enters cooldown"
                self.just_transitioned = True
            else:
                message = None
            
            self.pending_transition = None
            self.debug(f"Executed transition: {old_phase.value} -> {self.current_phase.value}")
            return message, False
        
        # Check for removal
        if self.should_be_removed:
            return "has worn off", True
        
        # Show current status with phase in parentheses
        if self.turns_remaining > 0:
            status = f"({self.current_phase.value}) {self.turns_remaining} turn{'s' if self.turns_remaining != 1 else ''} remaining"
            return status, False
        
        return None, False
    
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
    
    def _should_process_attacks_at_start(self) -> bool:
        """Determine if attacks should be processed at turn start"""
        # ACTIVE phase with per_turn timing always processes
        if self.current_phase == MovePhase.ACTIVE:
            return True
        
        # If transitioning to active phase, attacks will be processed after transition
        if (self.pending_transition and 
            self.pending_transition[0] == 'active'):
            return False
        
        return False
    
    def should_process_attacks_after_transition(self, roll_timing: 'RollTiming') -> bool:
        """Check if attacks should be processed after a transition"""
        return (self.just_transitioned and 
                self.current_phase == MovePhase.ACTIVE and 
                roll_timing == RollTiming.ACTIVE)
    
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
            "last_processed_turn": self.last_processed_turn,
            "applied_during_own_turn": self.applied_during_own_turn
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
        instance.applied_during_own_turn = data.get("applied_during_own_turn", False)
        
        return instance