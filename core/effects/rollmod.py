"""
Roll modifier effect that can buff or debuff dice rolls.
Supports advantage/disadvantage and numeric modifiers.
"""

from typing import Optional, List, Dict, Any
from .base import BaseEffect, EffectCategory
from enum import Enum

class RollModifierType(Enum):
    """Types of roll modifiers"""
    BONUS = "bonus"           # Numeric bonus/penalty
    ADVANTAGE = "advantage"   # Roll with advantage
    DISADVANTAGE = "disadvantage"  # Roll with disadvantage

class RollModifierEffect(BaseEffect):
    """
    Effect that modifies dice rolls for a character.
    
    Can provide:
    - Numeric bonus/penalty to rolls
    - Advantage on rolls
    - Disadvantage on rolls
    
    Can be applied:
    - For a set duration
    - Only to the next roll
    """
    
    def __init__(
        self,
        name: str,
        modifier_type: RollModifierType,
        value: int = 0,
        duration: Optional[int] = None,
        next_roll_only: bool = False,
        permanent: bool = False,
        description: Optional[str] = None,
        category: EffectCategory = EffectCategory.STATUS
    ):
        """Initialize a roll modifier effect."""
        super().__init__(
            name=name,
            duration=duration,
            permanent=permanent,
            category=category,
            description=description
        )
        
        self.modifier_type = modifier_type
        self.value = value
        self.next_roll_only = next_roll_only
        self.used = False  # Track if this has been used (for next_roll_only)
        
    def get_emoji(self) -> str:
        """Get the appropriate emoji for this modifier type"""
        if self.modifier_type == RollModifierType.BONUS:
            return "🎲" if self.value >= 0 else "⚠️"
        elif self.modifier_type == RollModifierType.ADVANTAGE:
            return "🎯"
        elif self.modifier_type == RollModifierType.DISADVANTAGE:
            return "🎪"
        return "✨"
        
    def on_apply(self, character, round_number: int) -> str:
        """Apply the effect to the character"""
        self.initialize_timing(round_number, character.name)
        
        # Format the message
        if self.modifier_type == RollModifierType.BONUS:
            sign = "+" if self.value >= 0 else ""
            mod_text = f"{sign}{self.value}"
        else:
            # For advantage/disadvantage, if value > 1, show stacking effect
            mod_text = f"{self.modifier_type.value}"
            if self.value > 1:
                mod_text += f" {self.value}"
        
        duration_text = ""
        if self.next_roll_only:
            duration_text = " on next roll"
        elif self.permanent:
            duration_text = " permanently"
        elif self.duration:
            duration_text = f" for {self.duration} turns"
            
        emoji = self.get_emoji()
        return self.format_effect_message(
            f"{character.name} gains {mod_text} to rolls{duration_text}",
            emoji=emoji
        )
        
    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Display active roll modifiers at start of turn"""
        # Only show message on character's turn
        if character.name != turn_name:
            return []
        
        # For next roll only modifiers, always show a reminder
        if self.next_roll_only and not self.used:
            details = []
            
            # Format modifier text
            if self.modifier_type == RollModifierType.BONUS:
                sign = "+" if self.value >= 0 else ""
                mod_text = f"{sign}{self.value}"
            else:
                mod_text = f"{self.modifier_type.value}"
                if self.value > 1:
                    mod_text += f" {self.value}"
            
            details.append(f"{mod_text} will apply to next roll")
            details.append("Will expire after use")
            
            emoji = self.get_emoji()
            return [self.format_effect_message(
                f"{self.name} active",
                details=details,
                emoji=emoji
            )]
        
        # For duration-based modifiers, show status at turn start
        elif not self.next_roll_only and not self.permanent:
            details = []
            
            # Format modifier text
            if self.modifier_type == RollModifierType.BONUS:
                sign = "+" if self.value >= 0 else ""
                mod_text = f"{sign}{self.value}"
            else:
                mod_text = f"{self.modifier_type.value}"
                if self.value > 1:
                    mod_text += f" {self.value}"
            
            # Calculate remaining turns
            turns_remaining, _ = self.process_duration(round_number, turn_name)
            
            if turns_remaining is not None and turns_remaining > 0:
                details.append(f"{mod_text} to all rolls")
                details.append(f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining")
                
                emoji = self.get_emoji()
                return [self.format_effect_message(
                    f"{self.name} active",
                    details=details,
                    emoji=emoji
                )]
        
        return []
            
    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Check if next_roll_only effect was used or if duration expired"""
        # Only process on character's turn
        if character.name != turn_name:
            return []
        
        # Handle next_roll_only effects - check if it was used
        if self.next_roll_only and self.used:
            # Will be removed in process_effects after this
            return [self.format_effect_message(
                f"{self.name} consumed",
                [f"Effect used on a roll this turn"]
            )]
            
        # Handle duration expiry for normal effects
        if not self.next_roll_only and not self.permanent:
            turns_remaining, should_expire = self.process_duration(round_number, turn_name)
            
            if not should_expire and turns_remaining is not None and turns_remaining > 0:
                # Show remaining duration
                return [self.format_effect_message(
                    f"{self.name} continues",
                    [f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"]
                )]
        
        return []
        
    def on_expire(self, character) -> str:
        """Handle expiry cleanup"""
        # Format expiry message based on usage
        if self.next_roll_only and self.used:
            return self.format_effect_message(f"{self.name} effect consumed")
        elif self.next_roll_only:
            return self.format_effect_message(f"{self.name} expired without being used")
        else:
            return self.format_effect_message(f"{self.name} has expired from {character.name}")
        
    def mark_used(self):
        """Mark this effect as used (for next_roll_only)"""
        if self.next_roll_only:
            self.used = True
            
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            "modifier_type": self.modifier_type.value,
            "value": self.value,
            "next_roll_only": self.next_roll_only,
            "used": self.used
        })
        return data
        
    @classmethod
    def from_dict(cls, data: dict) -> 'RollModifierEffect':
        """Create from dictionary data"""
        # Extract required parameters
        name = data.get('name', 'Roll Modifier')
        
        # Convert string to enum
        modifier_type_str = data.get('modifier_type', 'bonus')
        modifier_type = None
        for t in RollModifierType:
            if t.value == modifier_type_str:
                modifier_type = t
                break
        if not modifier_type:
            modifier_type = RollModifierType.BONUS
            
        # Create effect
        effect = cls(
            name=name,
            modifier_type=modifier_type,
            value=data.get('value', 0),
            next_roll_only=data.get('next_roll_only', False),
            permanent=data.get('permanent', False),
            description=data.get('description')
        )
        
        # Set timing if available
        if timing_data := data.get('timing'):
            from .base import EffectTiming
            effect.timing = EffectTiming(**timing_data)
            
        # Set used state
        effect.used = data.get('used', False)
        
        return effect