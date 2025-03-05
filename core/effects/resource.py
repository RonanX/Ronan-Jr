"""
Resource-based effects like drains and regeneration.
"""

from typing import Optional, List, Dict, Union, Tuple
from .base import BaseEffect, EffectCategory, EffectTiming
from utils.dice import DiceRoller
import logging

logger = logging.getLogger(__name__)

class DrainEffect(BaseEffect):
    """
    Effect that drains HP/MP from targets, optionally siphoning it to another character.
    
    Features:
    - Drain occurs only on affected character's turn
    - Support for dice notation or flat values
    - Optional siphon target for resource transfer
    - Duration tracking for DoT effects
    - Combat logging integration
    - Proper message formatting through base class
    """
    def __init__(
        self, 
        amount: Union[str, int],
        resource_type: str,
        siphon_target: Optional[str] = None,
        duration: Optional[int] = None,
        game_state = None
    ):
        name = f"{resource_type.upper()} {'Siphon' if siphon_target else 'Drain'}"
        super().__init__(
            name=name,
            duration=duration,
            permanent=False,
            category=EffectCategory.RESOURCE
        )
        self.amount = amount
        self.resource_type = resource_type.lower()
        self.siphon_target = siphon_target
        self.game_state = game_state
        self.total_drained = 0
        self.last_amount = 0
        
        # Emoji mapping for resource types
        self.emoji = {
            "hp": ("💔", "💜"),  # (drain, siphon)
            "mp": ("💨", "✨")
        }.get(self.resource_type.lower(), ("✨", "✨"))

    def _calculate_drain(self, character) -> int:
        """Calculate drain amount from dice or static value"""
        if isinstance(self.amount, str) and ('d' in self.amount.lower()):
            total, _ = DiceRoller.roll_dice(self.amount, character)
            return total
        return int(self.amount)

    def _apply_drain(self, character, amount: int) -> Tuple[int, int]:
        """
        Apply resource drain and return (amount_drained, new_value)
        """
        if self.resource_type == "hp":
            old_value = character.resources.current_hp
            new_value = max(0, old_value - amount)
            character.resources.current_hp = new_value
            return (old_value - new_value, new_value)
        else:  # MP
            old_value = character.resources.current_mp
            new_value = max(0, old_value - amount)
            character.resources.current_mp = new_value
            return (old_value - new_value, new_value)

    def _apply_siphon(self, character, amount: int) -> Tuple[int, int]:
        """
        Give drained resources to target and return (amount_given, new_value)
        """
        if self.resource_type == "hp":
            old_value = character.resources.current_hp
            new_value = min(
                character.resources.max_hp,
                old_value + amount
            )
            character.resources.current_hp = new_value
            return (new_value - old_value, new_value)
        else:  # MP
            old_value = character.resources.current_mp
            new_value = min(
                character.resources.max_mp,
                old_value + amount
            )
            character.resources.current_mp = new_value
            return (new_value - old_value, new_value)

    def on_apply(self, character, round_number: int) -> str:
        """Initial application of drain effect with improved formatting"""
        self.initialize_timing(round_number, character.name)
        
        # Create details list
        details = []
        
        # Add drain details
        if isinstance(self.amount, str) and 'd' in self.amount.lower():
            details.append(f"Drains {self.amount} {self.resource_type.upper()} per turn")
        else:
            details.append(f"Drains {self.amount} {self.resource_type.upper()} per turn")
            
        # Add siphon info
        if self.siphon_target:
            details.append(f"Transfers to {self.siphon_target}")
            
        # Add duration info
        if self.duration:
            turns = "turn" if self.duration == 1 else "turns"
            details.append(f"Duration: {self.duration} {turns}")
        elif self.permanent:
            details.append("Duration: Permanent")
            
        # Format with proper emojis
        emoji_pair = f"{self.emoji[0]}" + (f" {self.emoji[1]}" if self.siphon_target else "")
        
        return self.format_effect_message(
            f"{character.name} afflicted by {self.name}",
            details,
            emoji=emoji_pair
        )

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process drain at start of affected character's turn with improved formatting"""
        if character.name != turn_name:
            return []
            
        # Calculate and apply drain
        amount = self._calculate_drain(character)
        self.last_amount = amount
        drained, new_value = self._apply_drain(character, amount)
        self.total_drained += drained
        
        # Skip if no actual drain occurred
        if drained <= 0:
            return []
            
        # Format drain message with details
        details = []
        resource_label = "HP" if self.resource_type == "hp" else "MP"
        
        # Add updated resource value
        details.append(f"Current {resource_label}: {new_value}")
        
        # Add tracking info for ongoing effects
        if self.total_drained > drained:
            details.append(f"Total drained: {self.total_drained}")
            
        # Add duration info if applicable
        if not self.permanent and self.duration:
            rounds_completed = round_number - self.timing.start_round
            turns_remaining = max(0, self.duration - rounds_completed)
            if turns_remaining > 0:
                details.append(f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining")
            
        # Create message
        emoji = self.emoji[0]
        message = self.format_effect_message(
            f"{character.name} loses {drained} {resource_label}",
            details,
            emoji=emoji
        )
        
        # Handle siphon (if any)
        siphon_message = None
        if self.siphon_target and self.game_state:
            target = self.game_state.get_character(self.siphon_target)
            if target:
                received, new_target_value = self._apply_siphon(target, drained)
                if received > 0:
                    emoji = self.emoji[1]
                    siphon_message = self.format_effect_message(
                        f"{target.name} receives {received} {resource_label}",
                        [f"Current {resource_label}: {new_target_value}"],
                        emoji=emoji
                    )
        
        # Return message(s)
        if siphon_message:
            return [message, siphon_message]
        return [message]

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Track duration and show remaining time with improved formatting"""
        if character.name != turn_name or self.permanent:
            return []
            
        # Get duration status
        turns_remaining, should_expire = self.process_duration(round_number, turn_name)
        
        # Message if expiring after this turn
        if should_expire:
            if self.total_drained > 0:
                suffix = f" (Total drained: {self.total_drained} {self.resource_type.upper()})"
            else:
                suffix = ""
                
            # Format using base method
            return [self.format_effect_message(
                f"{self.name} effect will wear off{suffix}",
                emoji=self.emoji[0]
            )]
        
        # Show continue message if still active
        elif turns_remaining > 0:
            details = [f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"]
            
            # Add preview of next drain
            if isinstance(self.amount, str) and 'd' in self.amount.lower():
                details.append(f"Next drain: {self.amount}")
            else:
                details.append(f"Next drain: {self.amount}")
                
            # Format using base method
            return [self.format_effect_message(
                f"{self.name} continues",
                details,
                emoji=self.emoji[0]
            )]
            
        return []

    def on_expire(self, character) -> str:
        """Clean up effect state with improved message"""
        # Create summary message with total drained if any
        if self.total_drained > 0:
            suffix = f" (Total drained: {self.total_drained} {self.resource_type.upper()})"
        else:
            suffix = ""
            
        return self.format_effect_message(
            f"{self.name} effect has worn off from {character.name}{suffix}",
            emoji=self.emoji[0]
        )

    def get_status_text(self, character) -> str:
        """Format effect for status display"""
        emoji = self.emoji[0]
        if self.siphon_target:
            emoji += f" {self.emoji[1]}"
            
        lines = [f"{emoji} **{self.name}**"]
        
        # Add drain info
        lines.append(f"• `Amount per turn: {self.amount}`")
        if self.total_drained > 0:
            lines.append(f"• `Total drained: {self.total_drained}`")
            if self.last_amount > 0:
                lines.append(f"• `Last drain: {self.last_amount}`")
                
        # Add siphon target if any
        if self.siphon_target:
            lines.append(f"• `Transferring to: {self.siphon_target}`")
            
        # Add duration info
        if self.timing and self.timing.duration is not None:
            if hasattr(character, 'round_number'):
                rounds_passed = character.round_number - self.timing.start_round
                remaining = max(0, self.timing.duration - rounds_passed)
                lines.append(f"• `{remaining} turn{'s' if remaining != 1 else ''} remaining`")
        elif self.permanent:
            lines.append("• `Permanent`")
            
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            "amount": self.amount,
            "resource_type": self.resource_type,
            "siphon_target": self.siphon_target,
            "total_drained": self.total_drained,
            "last_amount": self.last_amount
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'DrainEffect':
        """Create from dictionary data"""
        effect = cls(
            amount=data.get('amount', 0),
            resource_type=data.get('resource_type', 'hp'),
            siphon_target=data.get('siphon_target'),
            duration=data.get('duration')
        )
        effect.total_drained = data.get('total_drained', 0)
        effect.last_amount = data.get('last_amount', 0)
        
        # Restore timing if it exists
        if timing_data := data.get('timing'):
            effect.timing = EffectTiming(**timing_data)
            
        return effect