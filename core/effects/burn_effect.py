"""
BurnEffect implementation for fire damage over time.

This is a simplified, template-based implementation that:
1. Applies damage at the start of each turn
2. Correctly tracks duration
3. Reliably shows expiry messages
4. Supports both fixed damage and dice notation
5. Uses the feedback system for reliable message display

This implementation follows the new template approach while maintaining
backward compatibility with existing code.
"""

from core.effects.base import BaseEffect, EffectCategory, EffectTiming
from typing import List, Optional, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

class BurnEffect(BaseEffect):
    """
    Applies fire damage at the start of each turn.
    
    This effect can be created in two ways:
    1. Directly: BurnEffect("1d6", duration=3)
    2. Via template: BaseEffect.create_dot("Burn", "1d6", "fire", duration=3, emoji="🔥")
    
    Features:
    - Simple, reliable implementation
    - Consistent duration tracking
    - Clear damage messaging
    - Proper expiry handling with feedback
    """
    def __init__(self, damage: str, duration: Optional[int] = None):
        """
        Initialize a burn effect.
        
        Args:
            damage: Amount of damage per turn (can be dice notation)
            duration: How many turns the effect lasts
        """
        super().__init__(
            name="Burn",
            duration=duration,
            permanent=False,
            category=EffectCategory.COMBAT,
            emoji="🔥"
        )
        
        # Store the template data to leverage template processing
        self._template_type = "dot"
        self._template_data = {
            "damage": damage,
            "damage_type": "fire",
            "last_damage": 0
        }
    
    @property
    def damage(self) -> str:
        """Get damage value from template data"""
        return self._template_data.get("damage", "1d4")
    
    @damage.setter
    def damage(self, value: str):
        """Set damage value in template data"""
        self._template_data["damage"] = value
    
    @property
    def last_damage(self) -> int:
        """Get last damage value from template data"""
        return self._template_data.get("last_damage", 0)
    
    @last_damage.setter
    def last_damage(self, value: int):
        """Set last damage value in template data"""
        self._template_data["last_damage"] = value
    
    def on_apply(self, character, round_number: int) -> str:
        """
        Apply burn effect with formatted message.
        
        Sets up timing system and returns application message.
        """
        self.initialize_timing(round_number, character.name)
        
        # Format duration text
        duration_text = ""
        if self.duration:
            turns = "turn" if self.duration == 1 else "turns"
            duration_text = f"for {self.duration} {turns}"
        elif self.permanent:
            duration_text = "permanently"
        
        # Return formatted message
        return self.format_effect_message(
            f"{character.name} is burning",
            [
                f"Taking {self.damage} fire damage per turn",
                duration_text
            ],
            emoji="🔥"
        )
    
    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process burn damage at start of affected character's turn.
        
        Applies damage and returns appropriate messages.
        """
        # Only process for the affected character's turn
        if character.name != turn_name:
            return []
        
        # FIXED: Skip if already marked for expiry or expiry message sent
        # This prevents double damage application
        if self._marked_for_expiry or self._expiry_message_sent:
            return []
        
        # FIXED: Check if this effect should expire on this turn
        # (for effects applied before the character's turn)
        _, _, should_expire_now = self.process_duration(round_number, turn_name)
        if should_expire_now:
            # Don't apply damage if we're going to expire this turn
            # Prevents double damage in scenario 2
            return []
        
        # Get damage info from template data
        damage_value = self._template_data["damage"]
        
        # Roll damage
        from utils.dice import DiceRoller
        if isinstance(damage_value, str) and ('d' in damage_value.lower()):
            damage_amount, _ = DiceRoller.roll_dice(damage_value, character)
        else:
            damage_amount = int(damage_value)
        
        # Store for reference
        self._template_data["last_damage"] = damage_amount
        
        # Create message details
        details = []
        
        # Handle temp HP
        absorbed = 0
        if character.resources.current_temp_hp > 0:
            absorbed = min(character.resources.current_temp_hp, damage_amount)
            character.resources.current_temp_hp -= absorbed
            damage_amount -= absorbed
        
        # Apply remaining damage to regular HP
        character.resources.current_hp = max(0, character.resources.current_hp - damage_amount)
        
        # Add damage details to message
        if absorbed > 0:
            details.append(f"{absorbed} absorbed by temp HP")
        details.append(f"HP: {character.resources.current_hp}/{character.resources.max_hp}")
        
        # Add duration info
        if not self.permanent and self.duration:
            # Calculate remaining turns
            turns_remaining, will_expire_next, _ = self.process_duration(round_number, turn_name)
            
            if will_expire_next or self._will_expire_next:
                details.append("Final turn - will expire after this turn")
            # Only show remaining duration for non-final turns
            elif turns_remaining is not None and turns_remaining > 0:
                s = "s" if turns_remaining != 1 else ""
                details.append(f"{turns_remaining} turn{s} remaining")
        
        # Return formatted message
        return [self.format_effect_message(
            f"{character.name} takes {damage_amount} fire damage from burn",
            details,
            emoji="🔥"
        )]

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process burn effect at end of affected character's turn.
        
        Handles duration tracking and expiry marking.
        """
        # Only process on character's own turn, skip for permanent effects
        if character.name != turn_name or self.permanent:
            return []
        
        # Use standardized duration tracking
        turns_remaining, will_expire_next, should_expire_now = self.process_duration(round_number, turn_name)
        
        # FIXED: Handle expiry - this needs to happen BEFORE marking for removal
        if should_expire_now:
            # Mark for expiry first
            self._marked_for_expiry = True
            
            # Create expiry message
            expiry_msg = self.format_effect_message(
                f"Burn effect has worn off from {character.name}",
                emoji="🔥"
            )
            
            # Add to feedback system for reliable display on next turn
            self._add_expiry_feedback(character, expiry_msg, round_number)
            
            # Set flag to prevent duplicate messages
            self._expiry_message_sent = True
            
            # FIXED: Return message for immediate display in end-of-turn embed
            return [expiry_msg]
        
        # Handle final turn warning
        if will_expire_next:
            self._will_expire_next = True
            return [self.format_effect_message(
                f"Burn effect continues",
                ["Final turn - will expire after this turn"],
                emoji="🔥"
            )]
        
        # Regular duration update
        if turns_remaining is not None and turns_remaining > 0:
            s = "s" if turns_remaining != 1 else ""
            return [self.format_effect_message(
                f"Burn effect continues",
                [f"{turns_remaining} turn{s} remaining"],
                emoji="🔥"
            )]
        
        return []

    def on_expire(self, character) -> str:
        """
        Clean up when effect expires or is removed.
        
        Creates expiry message and adds to feedback system.
        """
        # Get current round for feedback (fallback to 1 if not available)
        round_number = getattr(character, 'round_number', 1)
        
        # FIXED: Only generate a message if we haven't sent an expiry message yet
        if not self._expiry_message_sent:
            # Create expiry message
            expiry_msg = self.format_effect_message(
                f"Burn effect has worn off from {character.name}",
                emoji="🔥"
            )
            
            # Add to feedback system for reliable display
            self._add_expiry_feedback(character, expiry_msg, round_number)
            
            # Mark as sent to prevent duplicates
            self._expiry_message_sent = True
            
            return expiry_msg
        
        return ""
    
    def get_status_text(self, character) -> str:
        """Format status text for character sheet display"""
        lines = [f"🔥 **{self.name}**"]
        
        # Add damage info
        lines.append(f"• `Damage: {self.damage} fire per turn`")
        if self.last_damage:
            lines.append(f"• `Last damage: {self.last_damage}`")
        
        # Add duration info if available
        if self.timing and self.duration:
            if hasattr(character, 'round_number'):
                rounds_passed = character.round_number - self.timing.start_round
                remaining = max(0, self.duration - rounds_passed)
                
                # Calculate progress bar
                percentage = int((remaining / self.duration) * 100)
                blocks = min(10, max(0, int(percentage / 10)))
                bar = '█' * blocks + '░' * (10 - blocks)
                
                lines.append(f"• `Duration: {bar} ({remaining}/{self.duration} turns)`")
        elif self.permanent:
            lines.append("• `Permanent`")
        
        return "\n".join(lines)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        
        # Ensure template data exists for backward compatibility
        if not data.get('_template_data'):
            data["_template_data"] = {
                "damage": self.damage,
                "damage_type": "fire",
                "last_damage": getattr(self, 'last_damage', 0)
            }
        
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'BurnEffect':
        """Create from dictionary data"""
        # Get damage and duration
        if '_template_data' in data and 'damage' in data['_template_data']:
            damage = data['_template_data']['damage']
        else:
            damage = data.get('damage', "1d4")
        
        # Create new effect
        effect = cls(
            damage=damage,
            duration=data.get('duration')
        )
        
        # Restore template data if available
        if '_template_data' in data:
            effect._template_data = data['_template_data']
            
            # Ensure damage type is set
            if 'damage_type' not in effect._template_data:
                effect._template_data['damage_type'] = 'fire'
        
        # Restore timing information
        if timing_data := data.get('timing'):
            effect.timing = EffectTiming(**timing_data)
        
        # Restore state flags
        effect._marked_for_expiry = data.get('_marked_for_expiry', False)
        effect._will_expire_next = data.get('_will_expire_next', False)
        effect._application_round = data.get('_application_round')
        effect._application_turn = data.get('_application_turn')
        effect._expiry_message_sent = data.get('_expiry_message_sent', False)
        
        return effect