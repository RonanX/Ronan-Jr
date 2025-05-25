"""
core/effects/stat.py:

Stat effect system with stat modifier tracking and proper stacking.
Follows the same pattern as the working ACEffect implementation.

IMPLEMENTATION MANDATES:
- Track all stat modifications in character.stats
- Handle stacking of effects on the same stat type
- Track individual effect durations while maintaining a sum of effects
- Use proper effect state machine (CREATED → ACTIVE → EXPIRING → EXPIRED → REMOVED)
- Ensure proper cleanup when duration expires
"""

from typing import Optional, List, Dict, Any, Union, Tuple
from enum import Enum
from core.effects.base import BaseEffect, EffectCategory, EffectState
import logging

logger = logging.getLogger(__name__)

class StatType(str, Enum):
    STRENGTH = "strength"
    DEXTERITY = "dexterity"
    CONSTITUTION = "constitution"
    INTELLIGENCE = "intelligence"
    WISDOM = "wisdom"
    CHARISMA = "charisma"
    
    @classmethod
    def from_string(cls, stat_type: str) -> 'StatType':
        """Convert string to StatType enum value"""
        try:
            # Try direct conversion first
            return cls(stat_type.lower())
        except ValueError:
            # Try abbreviated forms (STR, DEX, etc.)
            stat_map = {
                "str": cls.STRENGTH,
                "dex": cls.DEXTERITY,
                "con": cls.CONSTITUTION,
                "int": cls.INTELLIGENCE,
                "wis": cls.WISDOM,
                "cha": cls.CHARISMA,
            }
            
            # Check for abbreviated form
            if stat_type.lower() in stat_map:
                return stat_map[stat_type.lower()]
                
            # Log warning and return default
            logger.warning(f"Invalid stat type: {stat_type}, defaulting to STRENGTH")
            return cls.STRENGTH

class StatManager:
    """
    Manages stat modifications for characters.
    
    This provides a central place to track all stat modifiers
    similar to how ACManager works for AC effects.
    """
    def __init__(self, character):
        """Initialize with base stats from character"""
        self.character = character
        self.modifiers = {}  # Format: {stat_type: {effect_id: amount}}
        self.base_values = {}
        
        # Initialize base values from character
        if hasattr(character, 'stats') and hasattr(character.stats, 'base'):
            for stat_type in StatType:
                if stat_type in character.stats.base:
                    self.base_values[stat_type] = character.stats.base[stat_type]
        
    def add_modifier(self, stat_type: StatType, effect_id: str, amount: int) -> int:
        """
        Add a stat modifier.
        Returns the new total value.
        """
        # Initialize dict for stat type if needed
        if stat_type not in self.modifiers:
            self.modifiers[stat_type] = {}
            
        # Add modifier
        self.modifiers[stat_type][effect_id] = amount
        
        # Apply to character
        return self._apply_modifiers(stat_type)
    
    def remove_modifier(self, stat_type: StatType, effect_id: str) -> int:
        """
        Remove a stat modifier.
        Returns the new total value.
        """
        # Check if modifier exists
        if stat_type in self.modifiers and effect_id in self.modifiers[stat_type]:
            # Remove it
            del self.modifiers[stat_type][effect_id]
            
            # Apply to character
            return self._apply_modifiers(stat_type)
        
        # If not found, just recalculate current value
        return self._apply_modifiers(stat_type)
    
    def get_total_modifier(self, stat_type: StatType) -> int:
        """Get total modifier value for a stat"""
        if stat_type not in self.modifiers:
            return 0
            
        return sum(self.modifiers[stat_type].values())
    
    def _apply_modifiers(self, stat_type: StatType) -> int:
        """Apply modifiers to character and return new value"""
        # Get base value
        base_value = self._get_base_value(stat_type)
        
        # Calculate total modifier
        total_mod = self.get_total_modifier(stat_type)
        
        # Calculate new value
        new_value = base_value + total_mod
        
        # Set in character's stats
        if hasattr(self.character, 'stats') and hasattr(self.character.stats, 'modified'):
            try:
                # Apply to stats.modified
                self.character.stats.modified[stat_type] = new_value
                
                # Update derived stats if possible
                if hasattr(self.character, '_update_derived_stats'):
                    self.character._update_derived_stats()
            except Exception as e:
                logger.error(f"Error setting stat {stat_type}: {e}")
        
        return new_value
    
    def _get_base_value(self, stat_type: StatType) -> int:
        """Get base value for a stat"""
        # Use cached base value if available
        if stat_type in self.base_values:
            return self.base_values[stat_type]
            
        # Otherwise get from character
        if hasattr(self.character, 'stats') and hasattr(self.character.stats, 'base'):
            try:
                value = self.character.stats.base.get(stat_type, 10)
                # Cache for future use
                self.base_values[stat_type] = value
                return value
            except Exception as e:
                logger.error(f"Error getting base value for {stat_type}: {e}")
                
        # Default
        return 10
    
    def get_all_modifiers(self, stat_type: StatType) -> Dict[str, int]:
        """Get all modifiers for a stat type"""
        if stat_type not in self.modifiers:
            return {}
        
        return self.modifiers[stat_type].copy()
    
    def reset(self, stat_type: Optional[StatType] = None) -> None:
        """
        Reset all modifiers for a stat type, or all stats if None.
        """
        if stat_type:
            # Reset specific stat
            if stat_type in self.modifiers:
                self.modifiers[stat_type] = {}
                self._apply_modifiers(stat_type)
        else:
            # Reset all stats
            for stat in list(self.modifiers.keys()):
                self.modifiers[stat] = {}
                self._apply_modifiers(stat)


class StatEffect(BaseEffect):
    """
    Effect that modifies a character's stats with proper stacking and duration.
    
    Features:
    - Proper duration tracking integrated with BaseEffect
    - Stacking support for multiple effects on the same stat
    - Consistent message formatting
    - Full restoration on expiry
    """
    def __init__(
        self, 
        stat_type: Union[StatType, str], 
        amount: int, 
        duration: Optional[int] = 3,
        permanent: bool = False,
        custom_name: Optional[str] = None
    ):
        # Convert string stat_type to enum if needed
        if isinstance(stat_type, str):
            stat_type = StatType.from_string(stat_type)
            
        # Generate appropriate name based on amount and stat
        if custom_name:
            name = custom_name
        else:
            stat_name = stat_type.name.title()
            if amount > 0:
                name = f"{stat_name} Boost" 
            elif amount < 0:
                name = f"{stat_name} Penalty"
            else:
                name = f"{stat_name} Effect"
                
        # Choose appropriate emoji based on amount
        emoji = "💪⬆️" if amount > 0 else "💪⬇️" if amount < 0 else "💪"
                
        # Initialize the base effect with standard parameters
        super().__init__(
            name=name,
            duration=duration,
            permanent=permanent,
            category=EffectCategory.STATUS,
            description=f"Modifies {stat_name} by {'+' if amount > 0 else ''}{amount}",
            emoji=emoji,
            debug_mode=True  # Enable logging for easier debugging
        )
        
        # Store effect-specific properties
        self.stat_type = stat_type
        self.amount = amount
        self.original_value = None  # Will store original stat value before modification
        self.base_value = None      # Will store base value before any modification
        
        # Generate unique ID for this effect
        import time, random
        self.effect_id = f"stat_{stat_type.value}_{int(time.time())}_{random.randint(1000, 9999)}"
        
        # Create a debug log entry
        self.debug(f"Created StatEffect: {stat_type.value} {'+' if amount > 0 else ''}{amount}, Duration: {duration}")
    
    def on_apply(self, character, round_number: int) -> str:
        """
        Apply the stat effect to the character.
        
        This method:
        1. Initializes timing using parent method
        2. Gets the current stat value before modification
        3. Applies the stat modification
        4. Returns a formatted message
        """
        # Call parent method first to handle timing initialization
        apply_msg = super().on_apply(character, round_number)
        
        # Store the original stat values
        self.original_value = self._get_stat_value(character, self.stat_type)
        self.base_value = self._get_base_stat_value(character, self.stat_type)
        
        # Initialize stat manager if needed
        self._ensure_stat_manager(character)
        
        # Apply stat modification via stat manager
        new_value = character.stat_manager.add_modifier(
            self.stat_type, 
            self.effect_id, 
            self.amount
        )
        
        # Get total modifier for display
        total_mod = character.stat_manager.get_total_modifier(self.stat_type)
        sign = "+" if total_mod > 0 else ""
        
        # Generate message based on whether it's an increase or decrease
        if self.amount > 0:
            main_message = f"{character.name}'s {self.stat_type.name.title()} increases"
        else:
            main_message = f"{character.name}'s {self.stat_type.name.title()} decreases"
            
        # Create details for message
        details = []
        details.append(f"{self.stat_type.name.title()} modified by {'+' if self.amount > 0 else ''}{self.amount}")
        details.append(f"Base value: {self.base_value}")
        
        # Add total modifier info if there are multiple effects
        if total_mod != self.amount:
            details.append(f"Total modifier: {sign}{total_mod}")
            
        details.append(f"Current value: {new_value}")
        
        # Add duration info
        if self.permanent:
            details.append("Effect is permanent")
        elif self._display_duration:
            s = "s" if self._display_duration != 1 else ""
            details.append(f"Duration: {self._display_duration} turn{s}")
        
        # Return formatted message
        return self.format_effect_message(main_message, details, emoji=self._get_emoji())
    
    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process the start of a turn for this effect.
        
        This method:
        1. Shows current status of the stat effect
        2. Includes appropriate duration information
        """
        # Only process if it's the character's turn and effect is active
        if character.name != turn_name or self.state != EffectState.ACTIVE:
            return []
            
        self.debug(f"Turn Start processing on round {round_number}")
        
        # Calculate remaining turns for accurate display
        should_expire, is_final, remaining = self.calculate_duration(round_number, turn_name)
        
        # Get current values
        current_value = self._get_stat_value(character, self.stat_type)
        total_mod = self._get_stat_manager(character).get_total_modifier(self.stat_type)
        
        # IMPROVED: More precise duration display
        if self.permanent:
            duration_text = "(permanent)"
        elif should_expire:
            duration_text = "(expiring now)"
        elif is_final:
            duration_text = "(expiring this turn)" 
        elif remaining == 1:
            duration_text = "(1 turn left)"
        else:
            # For display purposes, show actual turns left visually
            if self.timing and self.timing.applied_during_own_turn:
                # Improve display for "during own turn" effects
                # Show the actual turns remaining for better visual countdown
                rounds_passed = round_number - self.timing.start_round
                if rounds_passed == 0:
                    # First round - show full duration
                    duration = self._display_duration
                    duration_text = f"({duration} turns)"
                else:
                    # For subsequent rounds, show accurate remaining turns
                    if self._display_duration > 1:
                        # For display, show actual countdown
                        display_remaining = max(1, self._display_duration - rounds_passed)
                        duration_text = f"({display_remaining} turn{'s' if display_remaining != 1 else ''})"
                    else:
                        duration_text = "(1 turn)"
            else:
                # Not during own turn
                duration_text = f"({remaining} turn{'s' if remaining != 1 else ''})"
        
        # Use sign for positive values
        sign = "+" if self.amount > 0 else ""
        
        # Create the message
        if total_mod != self.amount:
            # Multiple effects on this stat - show both individual and total
            total_sign = "+" if total_mod > 0 else ""
            message = (
                f"{self.stat_type.name.title()} {sign}{self.amount} {duration_text} • "
                f"Total: {total_sign}{total_mod} • "
                f"Current value: {current_value}"
            )
        else:
            # Just this effect - simpler message
            message = f"{self.stat_type.name.title()} {sign}{self.amount} {duration_text} • Current value: {current_value}"
        
        # Return formatted message
        return [self.format_effect_message(message, emoji=self._get_emoji())]
    
    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process the end of a turn for this effect.
        
        This method:
        1. Handles duration checks and state transitions
        2. Creates appropriate messages for continuing or expiring effects
        """
        # Skip processing if not this character's turn
        if character.name != turn_name:
            return []
        
        self.debug(f"Turn End processing on round {round_number}")
        
        # Handle duration checks and state transitions
        should_expire, is_final, remaining = self.calculate_duration(round_number, turn_name)
        
        # Get current stat manager and values
        stat_manager = self._get_stat_manager(character)
        current_value = self._get_stat_value(character, self.stat_type)
        total_mod = stat_manager.get_total_modifier(self.stat_type)
        
        # Check if state should change
        if self.state == EffectState.ACTIVE:
            if should_expire:
                self.debug("Duration expired. Transitioning to EXPIRED.")
                self.state = EffectState.EXPIRED
                
                # Only create expiry message if this was the only/last effect of its kind
                if total_mod == self.amount:
                    # Remove the modifier
                    new_value = stat_manager.remove_modifier(self.stat_type, self.effect_id)
                    
                    # Generate expiry message
                    expiry_msg = self._format_expiry_message(character, current_value, new_value)
                    
                    # Add to feedback for proper display
                    self.add_feedback(character, expiry_msg, round_number, is_expiry=True)
                else:
                    # Other effects remain - just remove this one
                    stat_manager.remove_modifier(self.stat_type, self.effect_id)
                
                return []  # No immediate message
            
            elif is_final:
                self.debug("Final turn reached. Transitioning to EXPIRING.")
                self.state = EffectState.EXPIRING
                
                # Format message for final turn
                sign = "+" if self.amount > 0 else ""
                total_sign = "+" if total_mod > 0 else ""
                
                # Create message
                if total_mod != self.amount:
                    # Multiple effects - show both
                    message = (
                        f"{self.stat_type.name.title()} {sign}{self.amount} (final turn) • "
                        f"Total: {total_sign}{total_mod} • "
                        f"Current value: {current_value}"
                    )
                else:
                    # Just this effect
                    message = f"{self.stat_type.name.title()} {sign}{self.amount} (final turn) • Current value: {current_value}"
                
                return [self.format_effect_message(message, emoji=self._get_emoji())]
            
            else:
                # IMPROVED: Normal case - effect continues with better duration display
                sign = "+" if self.amount > 0 else ""
                total_sign = "+" if total_mod > 0 else ""
                
                # More precise remaining turns display
                if self.timing and self.timing.applied_during_own_turn:
                    # For "during own turn" effects, show accurate visual countdown
                    rounds_passed = round_number - self.timing.start_round
                    if rounds_passed == 0:
                        # Still in application round - show full duration
                        display_remaining = self._display_duration
                        duration_text = f"{display_remaining} turn{'s' if display_remaining != 1 else ''}"
                    else:
                        # For subsequent rounds, correctly count down
                        display_remaining = max(1, self._display_duration - rounds_passed)
                        duration_text = f"{display_remaining} turn{'s' if display_remaining != 1 else ''}"
                else:
                    # For NOT DURING effects, use the calculated remaining
                    duration_text = f"{remaining} turn{'s' if remaining != 1 else ''}"
                
                # Create message
                if total_mod != self.amount:
                    # Multiple effects - show both
                    message = (
                        f"{self.stat_type.name.title()} {sign}{self.amount} ({duration_text}) • "
                        f"Total: {total_sign}{total_mod} • "
                        f"Current value: {current_value}"
                    )
                else:
                    # Just this effect
                    message = f"{self.stat_type.name.title()} {sign}{self.amount} ({duration_text}) • Current value: {current_value}"
                
                return [self.format_effect_message(message, emoji=self._get_emoji())]
        
        elif self.state == EffectState.EXPIRING:
            # If already expiring, transition to expired
            self.debug("Was EXPIRING. Transitioning to EXPIRED.")
            self.state = EffectState.EXPIRED
            
            # Only create expiry message if this was the only/last effect of its kind
            if total_mod == self.amount:
                # Remove the modifier
                new_value = stat_manager.remove_modifier(self.stat_type, self.effect_id)
                
                # Generate expiry message
                expiry_msg = self._format_expiry_message(character, current_value, new_value)
                
                # Add to feedback for proper display
                self.add_feedback(character, expiry_msg, round_number, is_expiry=True)
            else:
                # Other effects remain - just remove this one
                stat_manager.remove_modifier(self.stat_type, self.effect_id)
            
            return []  # No immediate message
            
        return []  # No message for other states
    
    def on_expire(self, character) -> str:
        """
        Clean up when effect expires or is removed.
        
        This method:
        1. Removes the stat modifier
        2. Returns an empty string (message handled by feedback)
        """
        # Remove from stat manager if possible
        stat_manager = self._get_stat_manager(character)
        stat_manager.remove_modifier(self.stat_type, self.effect_id)
        
        # Let parent handle state transition
        super().on_expire(character)
        
        # Return empty string - message is sent via feedback
        return ""
    
    def _format_expiry_message(self, character, old_value: int, new_value: int) -> str:
        """Format a standardized expiry message"""
        # Create the main message
        message = f"{character.name}'s {self.stat_type.name.title()} returns to normal"
        
        # Add details
        details = []
        if self.amount > 0:
            details.append(f"Was +{self.amount}")
        elif self.amount < 0:
            details.append(f"Was {self.amount}")
        
        # Add value change information
        details.append(f"Value: {old_value} → {new_value}")
        
        # Format the message
        return self.format_effect_message(message, details, emoji=self._get_emoji())
    
    def _get_emoji(self) -> str:
        """Get appropriate emoji based on amount"""
        if self.amount > 0:
            return "💪⬆️"
        elif self.amount < 0:
            return "💪⬇️"
        return "💪"
    
    def _ensure_stat_manager(self, character) -> None:
        """Create stat manager for character if not present"""
        if not hasattr(character, 'stat_manager'):
            character.stat_manager = StatManager(character)
    
    def _get_stat_manager(self, character) -> StatManager:
        """Get or create stat manager for character"""
        self._ensure_stat_manager(character)
        return character.stat_manager
    
    def _get_stat_value(self, character, stat_type: StatType) -> int:
        """Get current stat value (modified)"""
        if hasattr(character, 'stats') and hasattr(character.stats, 'modified'):
            try:
                # Try direct key lookup
                if stat_type in character.stats.modified:
                    return character.stats.modified[stat_type]
                
                # Try as string
                stat_str = str(stat_type)
                for key, value in character.stats.modified.items():
                    if str(key) == stat_str:
                        return value
            except Exception as e:
                self.debug(f"Error getting stat value: {e}")
        
        # Default value if not found
        return 10
    
    def _get_base_stat_value(self, character, stat_type: StatType) -> int:
        """Get base stat value"""
        # Try to get from stat manager first if available
        if hasattr(character, 'stat_manager'):
            return character.stat_manager._get_base_value(stat_type)
        
        # Otherwise get directly
        if hasattr(character, 'stats') and hasattr(character.stats, 'base'):
            try:
                # Try direct key lookup
                if stat_type in character.stats.base:
                    return character.stats.base[stat_type]
                
                # Try as string
                stat_str = str(stat_type)
                for key, value in character.stats.base.items():
                    if str(key) == stat_str:
                        return value
            except Exception as e:
                self.debug(f"Error getting base stat value: {e}")
        
        # Default value if not found
        return 10
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            "stat_type": self.stat_type.value if hasattr(self.stat_type, 'value') else str(self.stat_type),
            "amount": self.amount,
            "effect_id": self.effect_id,
            "original_value": self.original_value,
            "base_value": self.base_value,
        })
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional['StatEffect']:
        """Create from saved dictionary data"""
        try:
            # Extract main parameters
            stat_type = data.get('stat_type', 'strength')
            amount = data.get('amount', 0)
            duration = data.get('duration')
            permanent = data.get('permanent', False)
            
            # Create new effect
            effect = cls(
                stat_type=stat_type,
                amount=amount,
                duration=duration,
                permanent=permanent
            )
            
            # Restore other properties
            effect.effect_id = data.get('effect_id', effect.effect_id)
            effect.original_value = data.get('original_value')
            effect.base_value = data.get('base_value')
            
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
            
            return effect
        except Exception as e:
            logger.error(f"Error creating StatEffect from dict: {e}", exc_info=True)
            return None