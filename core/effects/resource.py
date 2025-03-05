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
        """Initial application of drain effect - no immediate drain"""
        self.initialize_timing(round_number, character.name)
        
        details = []
        if self.duration:
            details.append(f"Duration: {self.duration} turns")
        details.append(f"Drains {self.amount} {self.resource_type.upper()} per turn")
        if self.siphon_target:
            details.append(f"Transfers to {self.siphon_target}")
            
        return f"{self.emoji[0]} `{character.name} afflicted by {self.name}`{f' {self.emoji[1]}' if self.siphon_target else ''}\n" + \
               "\n".join(f"• `{detail}`" for detail in details)

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process drain at start of affected character's turn"""
        if character.name != turn_name:
            return []
            
        # Calculate and apply drain
        amount = self._calculate_drain(character)
        self.last_amount = amount
        drained, new_value = self._apply_drain(character, amount)
        self.total_drained += drained
        
        if drained <= 0:
            return []
            
        # Format drain message
        details = [f"Current {self.resource_type.upper()}: {new_value}"]
        if self.total_drained > drained:
            details.append(f"Total drained: {self.total_drained}")
            
        message = f"{self.emoji[0]} `{character.name} loses {drained} {self.resource_type.upper()}`"
        
        # Handle siphon
        if self.siphon_target and self.game_state:
            target = self.game_state.get_character(self.siphon_target)
            if target:
                received, new_target_value = self._apply_siphon(target, drained)
                if received > 0:
                    message += f" {self.emoji[1]}"
                    details.append(
                        f"{target.name} received {received} "
                        f"({new_target_value} now)"
                    )
        
        return [message + "\n" + "\n".join(f"• `{detail}`" for detail in details)]

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Track duration and show remaining time"""
        if character.name == turn_name and not self.permanent:
            turns_remaining, should_expire = self.process_duration(round_number, turn_name)
            
            if should_expire:
                # Mark for cleanup by setting duration to 0
                if hasattr(self, 'timing'):
                    self.timing.duration = 0
                msg = f"{self.name} effect wearing off"
                if self.total_drained > 0:
                    msg += f" (Total drained: {self.total_drained})"
                return [self.format_effect_message(msg)]
            
            if turns_remaining > 0:
                plural = "s" if turns_remaining != 1 else ""
                details = [f"{turns_remaining} turn{plural} remaining"]
                if self.last_amount > 0:
                    details.append(f"Next drain: {self.amount}")
                return [f"{self.emoji[0]} `{self.name} continues`\n" + \
                       "\n".join(f"• `{detail}`" for detail in details)]
        return []

    def on_expire(self, character) -> str:
        """Clean up effect state"""
        msg = f"{self.name} effect expires from {character.name}"
        if self.total_drained > 0:
            msg += f" (Total drained: {self.total_drained})"
        return self.format_effect_message(msg)

    def get_status_text(self, character) -> str:
        """Format effect for status display"""
        lines = [f"{self.emoji[0]} **{self.name}**"]
        
        # Basic effect info
        if isinstance(self.amount, str):
            lines.append(f"• Amount per turn: `{self.amount}`")
        else:
            lines.append(f"• Amount: `{self.amount}`")
            
        # Show progress if any resources drained
        if self.total_drained > 0:
            lines.append(f"• Total drained: `{self.total_drained}`")
            if self.last_amount > 0:
                lines.append(f"• Last drain: `{self.last_amount}`")
                
        # Show siphon target if any
        if self.siphon_target:
            lines.append(f"• Transferring to: `{self.siphon_target}`")
            
        # Duration info
        if self.duration:
            lines.append(f"• Duration: `{self.duration} turns`")
            
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