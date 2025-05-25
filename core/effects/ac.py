"""
core/effects/ac.py:

AC effect system with priority-based modification handling.
Uses concise message format for all output.

IMPLEMENTATION MANDATES:
- Use ACManager for ALL AC modifications - never modify AC directly
- Each AC effect must have a unique effect_id
- All AC effects must properly handle duration and state transitions
- Use proper effect state machine (CREATED → ACTIVE → EXPIRING → EXPIRED → REMOVED)
- Use concise message format only
"""

from typing import Optional, List, Dict, Any, Tuple
import logging
import time
import random
from .base import BaseEffect, EffectCategory, EffectProcessTimingInfo, EffectState

logger = logging.getLogger(__name__)

# Counter for unique effect IDs
_ac_effect_counter = 0

class ACManager:
    """
    Manages all AC modifications to prevent conflicts.
    Each AC change registers with this manager instead of
    directly modifying the character's AC.
    """
    def __init__(self, base_ac: int):
        self.base_ac = base_ac
        self.modifiers = {}  # Format: {effect_id: (amount, priority)}
        self.current_ac = base_ac
    
    def add_modifier(self, effect_id: str, amount: int, priority: int = 0) -> int:
        """
        Add a new AC modifier.
        Higher priority modifiers override lower ones.
        Returns new total AC.
        """
        self.modifiers[effect_id] = (amount, priority)
        return self._recalculate()
    
    def remove_modifier(self, effect_id: str) -> int:
        """Remove a modifier and return new AC"""
        if effect_id in self.modifiers:
            del self.modifiers[effect_id]
        return self._recalculate()
    
    def _recalculate(self) -> int:
        """
        Recalculate AC based on all modifiers.
        Higher priority modifiers can override others.
        """
        # Sort by priority (highest first)
        sorted_mods = sorted(
            self.modifiers.items(),
            key=lambda x: x[1][1],
            reverse=True
        )
        
        # Start with base AC
        self.current_ac = self.base_ac
        
        # Apply modifiers in priority order
        for effect_id, (amount, _) in sorted_mods:
            self.current_ac += amount
            
        return self.current_ac
    
    def get_modifier_info(self) -> List[str]:
        """Get formatted list of all active modifiers"""
        info = []
        for effect_id, (amount, priority) in self.modifiers.items():
            sign = '+' if amount > 0 else ''
            info.append(f"{effect_id}: {sign}{amount} (Priority: {priority})")
        return info
        
    def reset(self) -> int:
        """Clear all modifiers and return base AC"""
        self.modifiers.clear()
        self.current_ac = self.base_ac
        return self.current_ac


class ACEffect(BaseEffect):
    """
    Handles AC modifications with proper state management and duration tracking.
    Uses a minimalist message format for all output.
    """
    def __init__(
        self, 
        amount: int, 
        duration: Optional[int] = None, 
        permanent: bool = False,
        unique_id: Optional[str] = None
    ):
        global _ac_effect_counter
        
        # Create a unique effect ID if not provided
        if unique_id is None:
            # Combine counter and timestamp for uniqueness
            _ac_effect_counter += 1
            unique_id = f"ac_{_ac_effect_counter}_{int(time.time())}_{random.randint(1000, 9999)}"
        
        # Set name and emoji based on amount
        name = f"AC {'Boost' if amount > 0 else 'Reduction'}"
        emoji = "🛡️" + ("⬆️" if amount > 0 else "⬇️" if amount < 0 else "")
        
        # IMPORTANT: Initialize base effect with standard parameters
        super().__init__(
            name=name,
            duration=None if permanent else duration,  # Set duration to None if permanent
            permanent=permanent,
            category=EffectCategory.STATUS,
            description=f"Modifies AC by {'+' if amount > 0 else ''}{amount}",
            emoji=emoji,
            debug_mode=True  # Enable debug logging
        )
        
        # Custom properties
        self.amount = amount
        self.effect_id = unique_id
    
    def on_apply(self, character, round_number: int) -> str:
        """Apply AC modification and initialize timing with concise message"""
        # IMPORTANT: Call parent method first to handle timing initialization
        apply_msg = super().on_apply(character, round_number)
        
        # Debug log timing information
        self.debug(f"Applied effect with timing: during_own_turn={self.timing.applied_during_own_turn if self.timing else 'unknown'}")
        self.debug(f"Internal duration: {self._internal_duration}, Display duration: {self._display_duration}")

        # Apply through AC manager
        character.modify_ac(self.effect_id, self.amount)
        
        # Create a concise message for application
        sign = "+" if self.amount > 0 else ""
        
        # Use action-based wording for apply message for better clarity
        if self.amount > 0:
            main_message = f"{character.name}'s armor strengthens"
        else:
            main_message = f"{character.name}'s armor weakens"
            
        details = []
        details.append(f"AC modified by {sign}{self.amount}")
        details.append(f"Current AC: {character.defense.current_ac}")

        # Add duration info
        if self.permanent:
            details.append("Effect is permanent")
        elif self._display_duration:
            s = "s" if self._display_duration != 1 else ""
            details.append(f"Duration: {self._display_duration} turn{s}")
        
        return self.format_effect_message(
            main_message,
            details,
            emoji=self._get_emoji()
        )

    def _get_emoji(self) -> str:
        """Get the appropriate emoji based on amount"""
        if self.amount > 0:
            return "🛡️⬆️"
        elif self.amount < 0:
            return "🛡️⬇️"
        else:
            return "🛡️"

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process start of turn with ONLY the concise message format.
        This is the key change - returning only one message with no supporting details.
        """
        # Only process if it's the character's turn and effect is active
        if character.name != turn_name or self.state != EffectState.ACTIVE:
            return []
            
        self.debug(f"Turn Start processing on round {round_number}")
        
        # Calculate remaining turns for accurate display
        _, is_final, remaining = self.calculate_duration(round_number, turn_name)
        
        # Format the concise message directly - no extra messages
        sign = "+" if self.amount > 0 else ""
        
        # Format duration text for display
        if self.permanent:
            duration_text = "(permanent)"
        elif is_final or remaining == 1:
            duration_text = "(expiring this turn)"
        elif remaining == 0:
            duration_text = "(expiring now)"
        else:
            duration_text = f"({remaining} turns)"
        
        # Create the concise message (this is the ONLY message returned)
        message = f"AC {sign}{self.amount} {duration_text} • Current AC: {character.defense.current_ac}"
        
        # Return only this one message - no extra messages or details
        return [self.format_effect_message(message, emoji=self._get_emoji())]
    
    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process end of turn with only concise message format.
        This uses standard_turn_end but overrides the message format.
        """
        # Skip processing if not this character's turn
        if character.name != turn_name:
            return []
        
        self.debug(f"Turn End processing on round {round_number}")
        
        # Handle duration checks and state transitions
        should_expire, is_final, remaining = self.calculate_duration(round_number, turn_name)
        
        # Check if state should change
        if self.state == EffectState.ACTIVE:
            if should_expire:
                self.debug("Duration expired. Transitioning to EXPIRED.")
                self.state = EffectState.EXPIRED
                expiry_msg = self._format_expiry_message(character)
                
                # Add to feedback instead of returning directly
                self.add_feedback(character, expiry_msg, round_number, is_expiry=True)
                return []  # No message for immediate display
            
            elif is_final:
                self.debug("Final turn reached. Transitioning to EXPIRING.")
                self.state = EffectState.EXPIRING
            
        elif self.state == EffectState.EXPIRING:
            # If already expiring, transition to expired
            self.debug("Was EXPIRING. Transitioning to EXPIRED.")
            self.state = EffectState.EXPIRED
            expiry_msg = self._format_expiry_message(character)
            
            # Add to feedback instead of returning directly
            self.add_feedback(character, expiry_msg, round_number, is_expiry=True)
            return []  # No message for immediate display
            
        # For active effects, return the concise message
        if not should_expire and not (self.state == EffectState.EXPIRED):
            sign = "+" if self.amount > 0 else ""
            
            # Format duration text for end of turn
            if self.permanent:
                duration_text = "(permanent)"
            elif is_final:
                duration_text = "(final turn)"
            elif remaining == 1:
                duration_text = "(1 turn)"
            else:
                duration_text = f"({remaining} turns)"
            
            # Create the concise message
            message = f"AC {sign}{self.amount} {duration_text} • Current AC: {character.defense.current_ac}"
            
            # Return only this one message
            return [self.format_effect_message(message, emoji=self._get_emoji())]
            
        return []  # No message if expired or other states
    
    def _format_expiry_message(self, character) -> str:
        """Format a standardized expiry message"""
        sign = "+" if self.amount > 0 else ""
        message = f"{character.name}'s armor returns to normal"
        
        return self.format_effect_message(
            message,
            [
                f"Was {sign}{self.amount}",
                f"Current AC: {character.defense.current_ac}"
            ],
            emoji="🛡️"
        )
    
    def on_expire(self, character) -> str:
        """Clean up AC modification when effect expires with concise message"""
        # Remove the AC modification
        if hasattr(character, 'remove_ac_modifier'):
            character.remove_ac_modifier(self.effect_id)
            self.debug(f"Removed AC modifier with ID: {self.effect_id} during on_expire")
        
        # Let parent handle state transition
        super().on_expire(character)
        
        # Return expiry message
        return self._format_expiry_message(character)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            'amount': self.amount,
            'effect_id': self.effect_id,
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Optional['ACEffect']:
        """Create from saved dictionary data"""
        try:
            # Extract amount and unique ID
            amount = data.get('amount', 0)
            unique_id = data.get('effect_id')
            
            # Create new effect
            effect = cls(
                amount=amount,
                duration=data.get('duration'),
                permanent=data.get('permanent', False),
                unique_id=unique_id
            )
            
            # IMPORTANT: Restore timing and state information
            if 'timing_info' in data:
                from core.effects.base import EffectProcessTimingInfo
                effect.timing = EffectProcessTimingInfo(**data['timing_info'])
                
            if 'state' in data:
                effect.state = EffectState(data['state'])
            
            # CRITICAL: Restore duration tracking state
            effect.turns_elapsed = data.get('turns_elapsed', 0)
            effect._internal_duration = data.get('_internal_duration')
            effect._display_duration = data.get('_display_duration')
            
            effect.debug(f"Restored from dict. State={effect.state.value}")
            if effect.timing:
                during = "DURING" if effect.timing.applied_during_own_turn else "NOT DURING"
                effect.debug(f"Timing restored: {during} own turn, Elapsed: {effect.turns_elapsed}")
                
            return effect
        except Exception as e:
            logger.error(f"Error creating ACEffect from dict: {e}", exc_info=True)
            return None