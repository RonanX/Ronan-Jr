"""
DebugEffect for testing the new effects system core logic.

This provides a fully-featured test effect that demonstrates all BaseEffect
functionality including proper duration tracking, state transitions, and serialization.
Use this as a reference when implementing new effect types.
"""

from typing import List, Optional, Dict, Any
import logging

# Import the BaseEffect and states from the base.py
from .base import BaseEffect, EffectState, EffectCategory, EffectProcessTimingInfo

logger = logging.getLogger(__name__)

class DebugEffect(BaseEffect):
    """
    A testing effect for debugging the core lifecycle and duration logic.
    Generates detailed debug messages at each lifecycle stage and includes serialization support.
    
    Features:
    - Complete BaseEffect implementation including to_dict/from_dict
    - Clear status messages that show internal state
    - Automatic logging of timing states
    - Support for custom messages
    - Support for permanent effects
    """
    def __init__(
        self,
        name: str = "Debug Effect",
        duration: Optional[int] = 2,
        message: Optional[str] = "Debugging...",
        process_timing: str = "both", # "start", "end", or "both"
        permanent: bool = False
    ):
        """
        Initialize the DebugEffect.

        Args:
            name (str): Name of the effect.
            duration (Optional[int]): Duration in turns. None for permanent effects.
            message (Optional[str]): Custom message for status updates.
            process_timing (str): When the effect should process ('start', 'end', 'both').
            permanent (bool): Whether the effect is permanent (never expires).
        """
        super().__init__(
            name=name,
            duration=duration,
            permanent=permanent, # Support permanent effects
            category=EffectCategory.CUSTOM, # Use CUSTOM category
            description=f"Test effect with {'permanent duration' if permanent else f'duration {duration}'}",
            process_timing=process_timing,
            emoji="🧪", # Use test tube emoji for debug effects
            debug_mode=True # Enable debug logging for this effect by default
        )
        self.custom_message = message

    def on_apply(self, character, round_number: int) -> str:
        """Called when effect is first applied."""
        # First let the base class handle state transition and timing initialization
        apply_msg = super().on_apply(character, round_number)
        
        # Log detailed timing information
        applied_during = "DURING" if self.timing and self.timing.applied_during_own_turn else "NOT DURING"
        internal_dur = self._internal_duration
        display_dur = self._display_duration
        
        self.debug(f"Applied on round {round_number}, {character.name}'s turn: {applied_during}")
        self.debug(f"Duration: Display={display_dur}, Internal={internal_dur}, Permanent={self.permanent}")

        # Create a customized message with detailed information
        details = []
        if self.permanent:
            details.append("Permanent effect (no duration)")
        else:
            details.append(f"Duration: {self._display_duration} turns")
        
        details.extend([
            f"Timing: {self.process_timing}",
            f"Applied: {applied_during} turn"
        ])
        
        if self.custom_message:
            details.append(self.custom_message)

        # Use the base class formatter to create a consistent message
        return self.format_effect_message(
            f"{self.name} applied to {character.name}",
            details=details,
            emoji="🧪"
        )

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Called at the start of the character's turn."""
        # Only process if it's the character's turn and effect is active
        if character.name != turn_name or self.state != EffectState.ACTIVE:
             return []

        self.debug(f"Turn Start processing on round {round_number}. State: {self.state.value}")
        messages = []

        # Only generate message if timing includes 'start' or 'both'
        if self.process_timing in ["start", "both"]:
            # Handle permanent effects differently
            if self.permanent:
                details = [
                    f"State: {self.state.value}",
                    f"Round: {round_number}",
                    "Permanent effect"
                ]
                if self.custom_message:
                    details.append(self.custom_message)
                
                messages.append(self.format_effect_message(
                    f"{self.name} active (Start)",
                    details=details,
                    emoji="🧪"
                ))
                return messages
            
            # For non-permanent effects, use calculate_duration
            should_expire, is_final, remaining_display = self.calculate_duration(round_number, turn_name)
            
            # Log full timing details for debugging
            self.debug(f"Duration check: ShouldExpire={should_expire}, IsFinal={is_final}, Remaining={remaining_display}")
            self.debug(f"Turns elapsed: {self.turns_elapsed}, Internal Duration: {self._internal_duration}")
            
            details = [
                f"State: {self.state.value}",
                f"Round: {round_number}",
                f"Internal Turns Left: {self._internal_duration - self.turns_elapsed if self._internal_duration is not None else 'Inf'}",
                f"Display Turns Left: {remaining_display if remaining_display is not None else 'Inf'}",
            ]
            if self.custom_message:
                details.append(self.custom_message)

            messages.append(self.format_effect_message(
                f"{self.name} active (Start)",
                details=details,
                emoji="🧪"
            ))
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Called at the end of the character's turn."""
        # Skip processing if not this character's turn
        if character.name != turn_name:
            return []
        
        self.debug(f"Turn End processing on round {round_number}. State: {self.state.value}")
        messages = []

        # Skip duration logic for permanent effects
        if self.permanent:
            if self.process_timing in ["end", "both"] and self.state == EffectState.ACTIVE:
                details = [
                    f"State: {self.state.value}",
                    f"Round: {round_number}",
                    "Permanent effect"
                ]
                if self.custom_message:
                    details.append(self.custom_message)
                    
                messages.append(self.format_effect_message(
                    f"{self.name} active (End)",
                    details=details,
                    emoji="🧪"
                ))
                
            return messages  # Return early for permanent effects
        
        # For non-permanent effects
        if self.process_timing in ["end", "both"] and self.state == EffectState.ACTIVE:
            # Get current duration status
            should_expire, is_final, remaining = self.calculate_duration(round_number, turn_name)
            
            # Add detailed information for debug but don't include expiry messages
            # They'll be handled by the base class
            if not should_expire:
                details = [
                    f"State: {self.state.value}",
                    f"Round: {round_number}",
                    f"Turns elapsed: {self.turns_elapsed}/{self._internal_duration}",
                ]
                
                if is_final:
                    details.append("Final turn")
                    
                if self.custom_message:
                    details.append(self.custom_message)
                    
                messages.append(self.format_effect_message(
                    f"{self.name} active (End)",
                    details=details,
                    emoji="🧪"
                ))

        # Now call base class to handle duration tracking
        # This will handle state transitions but we don't want the expiry message
        # to avoid duplicates
        base_messages = super().on_turn_end(character, round_number, turn_name) 
        
        # Filter out any expiry messages from base class (they should be added to feedback)
        for msg in base_messages:
            if "worn off" not in msg.lower() and "expired" not in msg.lower():
                messages.append(msg)
        
        return messages

    def on_expire(self, character) -> str:
        """Called when the effect expires or is removed."""
        # Base class handles state transition and feedback message generation
        self.debug(f"on_expire called for {self.name}, state={self.state.value}")
        
        # Call the base implementation first
        expiry_msg = super().on_expire(character)
        
        self.debug(f"Expired/Removed. Final message from base: '{expiry_msg}'")
        
        # Return empty string instead to avoid duplicate expiry messages
        # The expiry message was already added to feedback in on_turn_end
        return ""

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the effect to a dictionary for database storage.
        Adds custom_message to the base serialization.
        """
        # Get the base dictionary from parent class
        data = super().to_dict()
        
        # Add DebugEffect-specific fields
        data["custom_message"] = self.custom_message
        
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional['DebugEffect']:
        """
        Reconstruct a DebugEffect from dictionary data.
        """
        try:
            # Create a new DebugEffect instance with basic parameters
            permanent = data.get('permanent', False)
            effect = cls(
                name=data['name'],
                duration=data.get('duration'),
                message=data.get('custom_message', "Debugging..."),
                process_timing=data.get('process_timing', 'both'),
                permanent=permanent
            )
            
            # Restore state-related fields from the data
            if 'state' in data:
                effect.state = EffectState(data['state'])
                
            # Restore timing info
            timing_data = data.get('timing_info')
            if timing_data:
                from .base import EffectProcessTimingInfo
                effect.timing = EffectProcessTimingInfo(**timing_data)
                
            # Restore internal tracking fields
            if '_internal_duration' in data:
                effect._internal_duration = data.get('_internal_duration')
                
                # FIX: Ensure internal duration is valid for "not during" effects
                if effect.timing and not effect.timing.applied_during_own_turn and effect._internal_duration is not None:
                    if effect._internal_duration <= 0:
                        effect._internal_duration = 1
                        effect.debug("Fixed: Not during own turn effect had non-positive internal duration. Set to 1.")
                        
                # FIX: Ensure duration=1 during own turn has proper internal duration
                if effect._display_duration == 1 and effect.timing and effect.timing.applied_during_own_turn:
                    if effect._internal_duration < 2:
                        effect._internal_duration = 2
                        effect.debug("Fixed: Duration=1 during own turn had invalid internal duration. Set to 2.")
            
            effect.turns_elapsed = data.get('turns_elapsed', 0)
            
            effect.debug(f"Restored from dict. State={effect.state.value}, InternalDuration={effect._internal_duration}, Display={effect._display_duration}")
            return effect
            
        except Exception as e:
            logger.error(f"Error reconstructing DebugEffect from dict: {e}", exc_info=True)
            return None