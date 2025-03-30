"""
BurnEffect implementation for fire damage over time.

Features:
- Applies damage at the start of each turn
- Shows remaining duration consistently 
- Supports both fixed damage and dice notation
- Properly handles expiry timing
- Includes debug testing utility
- Uses feedback system for reliable expiry messages
"""

from core.effects.base import BaseEffect, EffectCategory, EffectTiming
from typing import List, Optional, Dict, Any, Tuple
import logging
import asyncio
from discord.ext import commands
import discord

logger = logging.getLogger(__name__)


class BurnEffect(BaseEffect):
    """
    Applies fire damage at the start of each turn.
    
    Features:
    - Supports both flat damage values and dice expressions
    - Clearly shows damage and remaining duration
    - Proper turn-based duration tracking
    - Consistent messaging
    - Reliable expiry messages with feedback system
    """
    def __init__(self, damage: str, duration: Optional[int] = None):
        super().__init__(
            name="Burn",
            duration=duration,
            permanent=False,
            category=EffectCategory.COMBAT,
            emoji="🔥"  # Use custom emoji for all burn messages
        )
        self.damage = damage
        self.last_damage = 0  # Track last damage dealt for messages
        self._damage_applied_this_turn = False
        self._expiry_message_sent = False  # Track if expiry message already sent
        
    def _roll_damage(self, character) -> int:
        """Roll damage if dice notation, otherwise return static value"""
        # Import here to avoid circular imports
        from utils.dice import DiceRoller
        
        if isinstance(self.damage, str) and ('d' in self.damage.lower() or 'D' in self.damage):
            total, _ = DiceRoller.roll_dice(self.damage, character)
            return total
        return int(self.damage)

    def on_apply(self, character, round_number: int) -> str:
        """Apply burn effect with formatted message"""
        self.initialize_timing(round_number, character.name)
        
        # Format duration text
        duration_text = ""
        if self.duration:
            turns = "turn" if self.duration == 1 else "turns"
            duration_text = f"for {self.duration} {turns}"
        elif self.permanent:
            duration_text = "permanently"
        
        # Return formatted message using base class method
        return self.format_effect_message(
            f"{character.name} is burning",
            [
                f"Taking {self.damage} fire damage per turn",
                duration_text
            ],
            emoji="🔥"
        )

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process burn damage at start of affected character's turn"""
        if character.name != turn_name:
            return []
        
        # Reset damage tracking for new turn
        self._damage_applied_this_turn = False
        
        # Skip processing if already marked for expiry
        if self._marked_for_expiry or self._expiry_message_sent:
            return []
        
        # Calculate elapsed turns
        elapsed_turns = 0 if round_number == self.timing.start_round else round_number - self.timing.start_round
        
        # Apply damage
        damage = self._roll_damage(character)
        self.last_damage = damage
        self._damage_applied_this_turn = True
        
        # Create message details
        details = []
        
        # Handle temp HP
        absorbed = 0
        if character.resources.current_temp_hp > 0:
            absorbed = min(character.resources.current_temp_hp, damage)
            character.resources.current_temp_hp -= absorbed
            damage -= absorbed
        
        # Apply remaining damage to regular HP
        character.resources.current_hp = max(0, character.resources.current_hp - damage)
        
        # Add damage details to message
        if absorbed > 0:
            details.append(f"{absorbed} absorbed by temp HP")
        details.append(f"HP: {character.resources.current_hp}/{character.resources.max_hp}")
        
        # Add duration info
        if not self.permanent and self.duration:
            remaining_turns = max(0, self.duration - elapsed_turns)
            
            # Check if this is the final turn
            if remaining_turns <= 1 or self._will_expire_next:
                details.append("Final turn - will expire after this turn")
        
        # Return formatted message
        return [self.format_effect_message(
            f"{character.name} takes {self.last_damage} fire damage from burn",
            details,
            emoji="🔥"
        )]

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Handle duration tracking at end of turn"""
        # Only process on character's own turn, skip for permanent effects
        if character.name != turn_name or self.permanent:
            return []
            
        # Standard duration tracking logic
        turns_remaining, will_expire_next, should_expire_now = self.process_duration(round_number, turn_name)
        
        # Handle expiry with better messaging
        if should_expire_now:
            if not self._expiry_message_sent:
                self._expiry_message_sent = True
                self._marked_for_expiry = True
                
                # Create expiry message
                expiry_msg = self.format_effect_message(
                    f"Burn effect has worn off from {character.name}",
                    emoji="🔥"
                )
                
                # Add to feedback system for reliable display even after effect is removed
                character.add_effect_feedback(
                    effect_name=self.name,
                    expiry_message=expiry_msg,
                    round_expired=round_number,
                    turn_expired=character.name
                )
                
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
        Clean message when effect expires.
        Also adds effect feedback for reliable expiry message display.
        """
        # Get current round for feedback (fallback to 1 if not available)
        round_number = getattr(character, 'round_number', 1)
        
        # Only generate a message if we haven't sent an expiry message yet
        if not self._expiry_message_sent:
            self._expiry_message_sent = True
            
            # Create expiry message
            expiry_msg = self.format_effect_message(
                f"Burn effect has worn off from {character.name}",
                emoji="🔥"
            )
            
            # Add to feedback system for reliable display
            character.add_effect_feedback(
                effect_name=self.name,
                expiry_message=expiry_msg,
                round_expired=round_number,
                turn_expired=character.name
            )
            
            return expiry_msg
        return ""
        
    def get_status_text(self, character) -> str:
        """Format status text for character sheet display"""
        lines = [f"🔥 **{self.name}**"]
        
        # Add damage info
        lines.append(f"• `Damage: {self.damage} per turn`")
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
        data.update({
            "damage": self.damage,
            "last_damage": self.last_damage,
            "_damage_applied_this_turn": getattr(self, '_damage_applied_this_turn', False),
            "_expiry_message_sent": getattr(self, '_expiry_message_sent', False)
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'BurnEffect':
        """Create from dictionary data"""
        effect = cls(
            damage=data.get('damage', "1d4"),
            duration=data.get('duration')
        )
        effect.last_damage = data.get('last_damage', 0)
        effect._damage_applied_this_turn = data.get('_damage_applied_this_turn', False)
        effect._expiry_message_sent = data.get('_expiry_message_sent', False)
        
        # Restore timing if it exists
        if timing_data := data.get('timing'):
            effect.timing = EffectTiming(**timing_data)
        
        # Restore state flags for compatibility
        effect._marked_for_expiry = data.get('_marked_for_expiry', False)
        effect._will_expire_next = data.get('_will_expire_next', False)
            
        return effect