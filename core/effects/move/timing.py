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
    
    def process_turn_start(self, character, round_number: int, turn_name: str) -> Optional[str]:
        """
        Turn Start: ONLY decrements duration and sets flags.
        No transitions or effect changes happen here.
        """
        # 🕐 DECREMENT DURATION
        if self.turns_remaining > 0:
            self.turns_remaining -= 1
        
        # 🏷️ SET FLAGS for turn end processing
        if self.turns_remaining <= 0:
            if self.current_phase == MovePhase.CASTING:
                # Flag for transition to active
                self.pending_transition = ('active', self.duration_turns)
                return f"**{self.effect.name}** casting complete (activating at turn end)"
                
            elif self.current_phase == MovePhase.ACTIVE:
                if self.cooldown_turns > 0:
                    # Flag for transition to cooldown
                    self.pending_transition = ('cooldown', self.cooldown_turns)
                    return f"**{self.effect.name}** duration complete (cooldown at turn end)"
                else:
                    # Flag for removal
                    self.should_be_removed = True
                    return f"**{self.effect.name}** duration complete (expiring at turn end)"
                    
            elif self.current_phase == MovePhase.COOLDOWN:
                # Flag for removal
                self.should_be_removed = True
                return f"**{self.effect.name}** cooldown complete (expiring at turn end)"
        
        # Show current status with remaining time
        return f"**{self.effect.name}** ({self.current_phase.value}) - {self.turns_remaining} turns remaining"
    
    def process_turn_end(self, character, round_number: int, turn_name: str) -> Optional[str]:
        """
        Turn End: Execute flagged transitions and show final status.
        """
        # 🔄 EXECUTE TRANSITIONS flagged during turn start
        if hasattr(self, 'pending_transition') and self.pending_transition:
            new_phase_name, new_duration = self.pending_transition
            
            if new_phase_name == 'active':
                self.current_phase = MovePhase.ACTIVE
                self.turns_remaining = new_duration
                self.pending_transition = None
                return f"**{self.effect.name}** activates! ({new_duration} turns)"
                
            elif new_phase_name == 'cooldown':
                self.current_phase = MovePhase.COOLDOWN
                self.turns_remaining = new_duration
                self.pending_transition = None
                return f"**{self.effect.name}** enters cooldown ({new_duration} turns)"
        
        # 📊 SHOW STATUS if not being removed
        if not self.should_be_removed:
            return f"**{self.effect.name}** ({self.current_phase.value}) - {self.turns_remaining} turns remaining"
        
        # Being removed - no status message needed (expiry message handled elsewhere)
        return None
    
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