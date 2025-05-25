"""
Template for creating new effects with standardized duration and message handling.

This template provides a starting point for creating new effects with consistent
behavior and proper duration handling.

Use this as a reference to create new effects that work correctly with the 
timing and duration system.
"""

from typing import List, Optional, Dict, Any
import logging

from core.effects.base import BaseEffect, EffectCategory

logger = logging.getLogger(__name__)

class TemplateEffect(BaseEffect):
    """
    Template for creating new effects with standardized behaviors.
    
    This demonstrates the recommended patterns for:
    - Duration handling (during vs not during own turn)
    - Message formatting
    - Turn processing
    - Bulk testing support
    """
    
    def __init__(
        self,
        name: str = "Template Effect",
        duration: Optional[int] = 3,
        description: str = "Template effect description",
        permanent: bool = False,
        emoji: str = "✨",
        debug_mode: bool = False,
        bulk: bool = False  # For bulk testing
    ):
        """
        Initialize a new effect with standardized parameters.
        
        Args:
            name: Display name of the effect
            duration: How many turns the effect lasts
            description: Description for UI display
            permanent: If True, effect never expires by duration
            emoji: Emoji for message formatting
            debug_mode: Enable detailed logging
            bulk: Enable bulk testing mode
        """
        # IMPORTANT: Don't modify the parent constructor call pattern
        # It handles standard duration setup 
        super().__init__(
            name=name,
            duration=duration,
            permanent=permanent,
            description=description,
            emoji=emoji,
            debug_mode=debug_mode or bulk  # Always enable debug in bulk mode
        )
        
        # Add your custom properties here
        self.bulk = bulk
        
        # YOUR CUSTOM PROPERTIES: Add any properties needed for your effect
        # For example:
        self.stat_mod_amount = 0
        self.affected_stat = None
        
        # If in bulk mode, configure for testing
        if bulk:
            self.debug(f"Initialized in BULK testing mode")
    
    def on_apply(self, character, round_number: int) -> str:
        """Apply the effect with proper duration handling"""
        # IMPORTANT: Always call parent method first to handle timing initialization
        # This ensures duration is calculated correctly based on application timing
        apply_msg = super().on_apply(character, round_number)
        
        # YOUR CUSTOM LOGIC: Add your effect's application logic here
        # Example: 
        # if hasattr(character, 'stats'):
        #     self.affected_stat = "strength" 
        #     self.stat_mod_amount = 2
        #     character.stats.add_modifier(self.affected_stat, self.stat_mod_amount, source=self.name)
        
        # Optional debug logging - only shows when debug_mode is True
        self.debug(f"Applied to {character.name} on round {round_number}")
        
        # IMPORTANT: Return the application message from parent
        # If you want to customize it, create a new message that includes the original:
        # return f"{apply_msg}\n• Additional custom message here"
        return apply_msg
    
    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process start of turn effects with standardized helper"""
        # RECOMMENDED: Use standard_turn_start for consistent duration handling
        # This ensures turns are counted correctly based on application timing
        return self.standard_turn_start(
            character, round_number, turn_name,
            custom_logic=self.custom_turn_start_logic
        )
    
    def custom_turn_start_logic(self, character, round_number: int, turn_name: str) -> List[str]:
        """Custom logic for turn start - implement your effect's behavior here"""
        messages = []
        
        # YOUR CUSTOM LOGIC: Add any start-of-turn effects here
        # Example: Apply regeneration
        # if character.name == turn_name:  # Only apply to character whose turn it is
        #     heal_amount = 5
        #     character.resources.current_hp = min(
        #         character.resources.current_hp + heal_amount,
        #         character.resources.max_hp
        #     )
        #     messages.append(self.format_effect_message(
        #         f"{character.name} regenerates {heal_amount} HP",
        #         emoji="💚"
        #     ))
        
        # Return any messages generated (can be empty list)
        return messages
    
    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process end of turn effects with standardized helper"""
        # RECOMMENDED: Use standard_turn_end for consistent duration handling
        # This ensures the effect expires at the correct time
        return self.standard_turn_end(
            character, round_number, turn_name,
            custom_logic=self.custom_turn_end_logic
        )
    
    def custom_turn_end_logic(self, character, round_number: int, turn_name: str) -> List[str]:
        """Custom logic for turn end - implement your effect's behavior here"""
        messages = []
        
        # YOUR CUSTOM LOGIC: Add any end-of-turn effects here
        # Example: Apply damage over time
        # if character.name == turn_name:  # Only apply to character whose turn it is
        #     damage = 3
        #     character.resources.current_hp -= damage
        #     messages.append(self.format_effect_message(
        #         f"{character.name} takes {damage} damage",
        #         emoji="🔥"
        #     ))
        
        # Return any messages generated (can be empty list)
        return messages
    
    def on_expire(self, character) -> str:
        """Clean up when the effect expires or is removed"""
        # YOUR CUSTOM CLEANUP: Add any cleanup logic here
        # Example: Remove stat modifiers
        # if self.affected_stat and hasattr(character, 'stats'):
        #     character.stats.remove_modifier(self.affected_stat, source=self.name)
        
        # IMPORTANT: Always call parent expire to handle state transition
        # You can add an additional message if needed:
        # expire_msg = super().on_expire(character)
        # return f"{expire_msg}\n• Additional cleanup message"
        return super().on_expire(character)
    
    # REQUIRED: Include serialization methods for database storage
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        # Get the base serialization from parent
        data = super().to_dict()
        
        # Add your custom properties
        data.update({
            # Add all custom properties you need to persist here
            "bulk": self.bulk,
            "stat_mod_amount": self.stat_mod_amount,
            "affected_stat": self.affected_stat,
            # Add more as needed
        })
        
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TemplateEffect':
        """Create from dictionary data"""
        # Create base object with standard properties
        effect = cls(
            name=data.get('name', 'Template Effect'),
            duration=data.get('duration'),
            description=data.get('description', ''),
            permanent=data.get('permanent', False),
            emoji=data.get('emoji', '✨'),
            debug_mode=data.get('debug_mode', False),
            bulk=data.get('bulk', False)
        )
        
        # Restore custom properties
        effect.stat_mod_amount = data.get('stat_mod_amount', 0)
        effect.affected_stat = data.get('affected_stat', None)
        # Restore more custom properties as needed
        
        # IMPORTANT: Restore timing and state information 
        # This ensures duration tracking works correctly after loading
        if 'timing' in data:
            from core.effects.base import EffectProcessTimingInfo
            effect.timing = EffectProcessTimingInfo(**data['timing'])
            
        if 'state' in data:
            from core.effects.base import EffectState
            effect.state = EffectState(data['state'])
        
        # CRITICAL: Restore duration tracking state
        effect.turns_elapsed = data.get('turns_elapsed', 0)
        effect._internal_duration = data.get('_internal_duration')
        effect._display_duration = data.get('_display_duration')
        
        effect.debug(f"Restored from dict. State={effect.state.value}")
        return effect
