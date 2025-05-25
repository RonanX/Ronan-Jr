"""
Test Effect - A simple effect to test the new helper methods

This implements a minimal effect for testing the enhanced BaseEffect helpers.
It just adds a simple visual marker to a character for a specified duration.
"""

from typing import List, Dict, Any, Optional
import logging

# Import the effect system
from core.effects.base import BaseEffect, EffectState, EffectCategory

logger = logging.getLogger(__name__)

class TestEffect(BaseEffect):
    """
    Simple test effect for verifying helper methods work correctly.
    
    This effect doesn't do anything mechanically - it just applies a marker
    to a character for testing duration handling and message formatting.
    """
    
    def __init__(
        self,
        name: str = "Test Effect",
        duration: Optional[int] = 3,
        marker: str = "⚗️",
        test_message: str = "Testing...",
        permanent: bool = False,
        category: Optional[EffectCategory] = EffectCategory.CUSTOM,
        process_timing: str = "both",
        debug_mode: bool = True  # Enable debug mode by default for testing
    ):
        """
        Initialize test effect.
        
        Args:
            name: Display name of the effect
            duration: How many turns the effect lasts
            marker: Emoji or marker to display
            test_message: Message to show in updates
            permanent: If True, effect never expires by duration
            category: Effect category for organization
            process_timing: When effect logic runs
            debug_mode: Enable detailed logging
        """
        # Initialize base effect
        super().__init__(
            name=name,
            duration=None if permanent else duration,
            permanent=permanent,
            category=category,
            description=test_message,
            process_timing=process_timing,
            emoji=marker,
            debug_mode=debug_mode
        )
        
        # Store test parameters
        self.marker = marker
        self.test_message = test_message
        
        # Track state changes
        self.state_changes = []
        self.debug(f"Created {name} with marker {marker}")
    
    def on_apply(self, character, round_number: int) -> str:
        """Called when effect is first applied to a character."""
        # Call parent implementation first to handle timing and state properly
        apply_msg = super().on_apply(character, round_number)
        
        # Record state change
        self.state_changes.append(f"CREATED → ACTIVE (Round {round_number})")
        
        # Log detailed application info
        applied_during = "DURING" if self.timing and self.timing.applied_during_own_turn else "NOT DURING"
        internal_dur = self._internal_duration
        display_dur = self._display_duration
        
        self.debug(f"Applied to {character.name} on round {round_number}, {applied_during} own turn")
        self.debug(f"Duration: Display={display_dur}, Internal={internal_dur}, Permanent={self.permanent}")
        
        # Return custom message rather than the base message
        return self.format_effect_message(
            f"{self.name} applied to {character.name}",
            details=[self.test_message, f"Duration: {'Permanent' if self.permanent else f'{display_dur} turns'}"],
            emoji=self.marker
        )
    
    def custom_turn_start_logic(self, character, round_number, turn_name) -> List[str]:
        """
        Custom logic for turn start.
        Just adds a message about the test effect being active.
        """
        messages = []
        
        # Simple message showing the test is active
        messages.append(self.format_effect_message(
            f"{self.name} is active on {character.name}",
            details=[self.test_message],
            emoji=self.marker
        ))
        
        return messages
    
    def custom_turn_end_logic(self, character, round_number, turn_name) -> List[str]:
        """
        Custom logic for turn end.
        Just verifies everything works correctly.
        """
        messages = []
        
        # Check if duration tracking is working
        if not self.permanent and hasattr(self, 'turns_elapsed'):
            messages.append(self.format_effect_message(
                f"{self.name} verification",
                details=[
                    f"Elapsed: {self.turns_elapsed} turns",
                    f"Internal duration: {self._internal_duration}",
                    f"Display duration: {self._display_duration}"
                ],
                emoji="🔍"
            ))
        
        # Add an expiry message if this is the final turn
        if not self.permanent and self._internal_duration == 1:
            messages.append(self.format_effect_message(
                f"{self.name} has worn off",
                emoji=self.marker
            ))
        
        return messages
    
    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Called at the start of the character's turn."""
        # Use the standard implementation with our custom logic
        return self.standard_turn_start(
            character, 
            round_number, 
            turn_name,
            custom_logic=self.custom_turn_start_logic
        )
    
    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Called at the end of the character's turn."""
        # Track state before processing
        old_state = self.state
        
        # Use the standard implementation with our custom logic
        messages = self.standard_turn_end(
            character, 
            round_number, 
            turn_name,
            custom_logic=self.custom_turn_end_logic
        )
        
        # Check for state transitions
        if old_state != self.state:
            self.state_changes.append(f"{old_state.value} → {self.state.value} (Round {round_number})")
            self.debug(f"State transition: {old_state.value} → {self.state.value}")
        
        return messages
    
    def on_expire(self, character) -> str:
        """Called when the effect expires or is forcibly removed."""
        # Track state change before processing
        old_state = self.state
        
        # Let base class handle state transition
        super().on_expire(character)
        
        # Record state transition
        self.state_changes.append(f"{old_state.value} → {self.state.value} (Expired)")
        self.debug(f"Final state transition: {old_state.value} → {self.state.value}")
        
        # Return empty string - expiry message will be handled by standard_turn_end
        # This prevents duplicate expiry messages
        return ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        data = super().to_dict()
        
        # Add test-specific fields
        data.update({
            "marker": self.marker,
            "test_message": self.test_message,
            "state_changes": self.state_changes
        })
        
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional['TestEffect']:
        """Reconstruct from dictionary data."""
        try:
            # Create new effect with basic parameters
            effect = cls(
                name=data.get('name', 'Test Effect'),
                duration=data.get('duration'),
                marker=data.get('marker', '⚗️'),
                test_message=data.get('test_message', 'Testing...'),
                permanent=data.get('permanent', False),
                category=EffectCategory(data['category']) if data.get('category') else EffectCategory.CUSTOM,
                process_timing=data.get('process_timing', 'both')
            )
            
            # Restore state
            if 'state' in data:
                effect.state = EffectState(data['state'])
                
            # Restore timing info
            timing_data = data.get('timing_info')
            if timing_data:
                from core.effects.base import EffectProcessTimingInfo
                effect.timing = EffectProcessTimingInfo(**timing_data)
                
            # Restore duration tracking
            if '_internal_duration' in data:
                effect._internal_duration = data.get('_internal_duration')
                
            if '_display_duration' in data:
                effect._display_duration = data.get('_display_duration')
                
            effect.turns_elapsed = data.get('turns_elapsed', 0)
            
            # Restore test-specific fields
            if 'state_changes' in data:
                effect.state_changes = data.get('state_changes', [])
            
            effect.debug(f"Restored from dict. State={effect.state.value}")
            return effect
            
        except Exception as e:
            logger.error(f"Error reconstructing TestEffect from dict: {e}", exc_info=True)
            return None