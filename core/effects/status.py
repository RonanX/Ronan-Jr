"""
src/core/effects/status.py:

Status effects that modify character attributes or apply conditions.

IMPLEMENTATION MANDATES:
- Use ACManager for ALL AC modifications - never modify AC directly
- Each AC effect must have a unique effect_id
- All stacking effects must handle proper cleanup
- Status effects should use EffectCategory.STATUS
- Status effects should prioritize conditional logic over raw stat changes
- Always handle both permanent and temporary versions of effects
"""

from datetime import datetime
from typing import Optional, List
import logging
from .base import BaseEffect, EffectCategory, EffectProcessTimingInfo
# Import AC classes from ac module
from .ac import ACManager, ACEffect

logger = logging.getLogger(__name__)

class FrostbiteEffect(BaseEffect):
    """
    Accumulating ice that slows movement and attacks.
    At 3 stacks, freezes the target solid.
    
    Features:
    - Slows movement speed (-5 ft per stack)
    - Applies penalties to STR/DEX saves (-1 per stack)
    - At 3+ stacks, causes target to skip their turn (frozen)
    - Uses ACEffect to modify AC at high stacks
    """
    def __init__(self, stacks: int = 1, duration: Optional[int] = 2):
        super().__init__(
            name="Frostbite",
            duration=duration,  # Default 2 turn duration
            permanent=False,
            category=EffectCategory.STATUS
        )
        self.stacks = min(stacks, 3)  # Maximum 3 stacks
        self.last_stack_reduction = 0  # Track when stacks were last reduced
        self.effect_id = f"frostbite_ac_{id(self)}"  # Unique ID for AC manager
        self.skip_applied = False  # Track if we've applied a skip effect
        self.turns_active = 0  # Track how many turns this effect has been active

    def on_apply(self, character, round_number: int) -> str:
        """Apply initial frostbite effect"""
        self.initialize_timing(round_number, character.name)
        
        # Apply penalties based on stacks
        messages = []
        details = [
            f"Movement: -{self.stacks * 5} ft",
            f"STR/DEX Saves: -{self.stacks}",
            f"Duration: {self.duration} turns"
        ]
        
        messages.append(self.format_effect_message(
            f"{character.name} is afflicted by Frostbite {self.stacks}/3",
            details,
            emoji="❄️"
        ))
        
        # Check for freeze threshold
        if self.stacks >= 3:
            # Set AC to 5 through AC manager with high priority
            character.modify_ac(self.effect_id, 5 - character.defense.base_ac, priority=100)
            
            # Add skip effect for 1 turn if not already applied
            if not self.skip_applied:
                skip = SkipEffect(duration=1, reason="Frostbite III")
                character.add_effect(skip, round_number)
                self.skip_applied = True
            
            messages.append(self.format_effect_message(
                f"{character.name} is frozen solid!",
                ["Cannot take actions",
                 "AC reduced to 5",
                 "Attacks have advantage"],
                emoji="❄️"
            ))
            
        return "\n".join(messages)

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process start of turn effects"""
        if character.name != turn_name:
            return []

        messages = []
        details = []
        
        # Add duration info based on tracking, not calculated
        remaining_turns = max(0, self.duration - self.turns_active)
        if remaining_turns > 0:
            details.append(f"{remaining_turns} turn{'s' if remaining_turns != 1 else ''} remaining")
        
        # Show frozen state if applicable
        if self.stacks >= 3:
            details.extend([
                "Cannot take actions or reactions",
                "AC reduced to 5",
                "Automatically fails STR/DEX saves",
                "Vulnerable to critical hits"
            ])
            
            messages.append(self.format_effect_message(
                "Frozen Solid",
                details,
                emoji="❄️"
            ))
        else:
            details.extend([
                f"Movement: -{self.stacks * 5} ft",
                f"STR/DEX Saves: -{self.stacks}"
            ])
            
            messages.append(self.format_effect_message(
                f"Frostbite Penalties ({self.stacks}/3)",
                details,
                emoji="❄️"
            ))
            
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process duration tracking and stack reduction"""
        if character.name != turn_name:
            return []
            
        messages = []
        
        # Increment our active turns counter
        self.turns_active += 1
        
        # Check if we've reached our duration limit
        if self.turns_active >= self.duration:
            # Mark for expiry
            self._marked_for_expiry = True
            
            # Clean up AC effects if applied
            if self.stacks >= 3 and self.effect_id in getattr(character.ac_manager, 'modifiers', {}):
                character.remove_ac_modifier(self.effect_id)
            
            messages.append(self.format_effect_message(
                f"Frostbite will wear off from {character.name}",
                emoji="❄️"
            ))
            return messages
            
        # If we have 3 stacks, check if we should reduce them after skip turn
        if self.stacks >= 3 and self.skip_applied:
            self.stacks -= 1
            self.skip_applied = False  # Reset skip tracking
            if self.effect_id in getattr(character.ac_manager, 'modifiers', {}):
                character.remove_ac_modifier(self.effect_id)
            messages.append(self.format_effect_message(
                f"Frostbite reduced to {self.stacks}/3 stacks",
                [f"Character unfreezes but remains affected"],
                emoji="❄️"
            ))
        # Otherwise handle normal stack reduction (every turn)
        elif self.stacks > 0 and round_number > self.last_stack_reduction:
            old_stacks = self.stacks
            self.stacks -= 1
            self.last_stack_reduction = round_number
            
            if self.stacks <= 0:
                # Mark for expiry if no stacks left
                self._marked_for_expiry = True
                messages.append(self.format_effect_message(
                    f"Frostbite will wear off from {character.name}",
                    emoji="❄️"
                ))
            else:
                messages.append(self.format_effect_message(
                    f"Frostbite reduced to {self.stacks}/3 stacks",
                    [f"Movement: -{self.stacks * 5} ft",
                     f"STR/DEX Saves: -{self.stacks}"],
                    emoji="❄️"
                ))
                
        # Show remaining turns if any stacks remain and not marked for removal
        remaining_turns = max(0, self.duration - self.turns_active)
        if remaining_turns > 0 and self.stacks > 0 and not self._marked_for_expiry:
            messages.append(self.format_effect_message(
                f"Frostbite continues",
                [f"{remaining_turns} {'turn' if remaining_turns == 1 else 'turns'} remaining"],
                emoji="❄️"
            ))
            
        return messages

    def on_expire(self, character) -> str:
        """
        Clean up effect when it expires.
        Ensures proper cleanup of AC modifications and other state changes.
        """
        # Remove AC modification through manager if it exists
        # First check if character has an ac_manager attribute
        if hasattr(character, 'ac_manager'):
            if self.effect_id in character.ac_manager.modifiers:
                character.remove_ac_modifier(self.effect_id)
        # Otherwise use the character's direct method if available
        elif hasattr(character, 'remove_ac_modifier'):
            character.remove_ac_modifier(self.effect_id)
        # Fallback for direct AC reset if neither is available
        else:
            # Just ensure AC is restored to base if frozen
            if self.stacks >= 3:
                character.defense.current_ac = character.defense.base_ac
        
        # Reset stacks to ensure complete cleanup
        self.stacks = 0
        self.skip_applied = False
        
        # Create appropriate message based on severity
        if self.stacks >= 3:
            return self.format_effect_message(
                f"{character.name} has thawed out",
                emoji="❄️"
            )
        return self.format_effect_message(
            f"Frostbite has worn off from {character.name}",
            emoji="❄️"
        )

    def add_stacks(self, amount: int, character) -> str:
        """Add frostbite stacks"""
        old_stacks = self.stacks
        self.stacks = min(3, self.stacks + amount)
        
        messages = []
        
        # If newly frozen
        if old_stacks < 3 and self.stacks >= 3:
            # Update AC through manager
            character.modify_ac(self.effect_id, 5 - character.defense.base_ac, priority=100)
            
            # Add skip effect if not already applied
            if not self.skip_applied:
                skip = SkipEffect(duration=1, reason="Frostbite III")
                character.add_effect(skip)
                self.skip_applied = True
            
            messages.append(self.format_effect_message(
                f"{character.name} is frozen solid!",
                ["Movement halted",
                 "AC reduced to 5",
                 "Cannot take actions"],
                emoji="❄️"
            ))
        else:
            messages.append(self.format_effect_message(
                f"Frostbite increased to {self.stacks}/3 on {character.name}",
                [f"Movement: -{self.stacks * 5} ft",
                 f"STR/DEX Saves: -{self.stacks}"],
                emoji="❄️"
            ))
            
        # Reset duration when stacks are added
        if hasattr(self, 'timing'):
            self.timing.duration = self.duration
            
        # Reset turns active counter when adding stacks
        self.turns_active = 0
            
        return "\n".join(messages)
        
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            'stacks': self.stacks,
            'effect_id': self.effect_id,
            'last_stack_reduction': self.last_stack_reduction,
            'skip_applied': self.skip_applied,
            'turns_active': self.turns_active
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'FrostbiteEffect':
        """Create from saved dictionary data"""
        effect = cls(
            stacks=data.get('stacks', 1),
            duration=data.get('duration', 2)
        )
        if timing_data := data.get('timing'):
            effect.timing = EffectProcessTiming(**timing_data)
        effect.effect_id = data.get('effect_id', f"frostbite_ac_{id(effect)}")
        effect.last_stack_reduction = data.get('last_stack_reduction', 0)
        effect.skip_applied = data.get('skip_applied', False)
        effect.turns_active = data.get('turns_active', 0)
        
        # Restore marked for expiry flag if it exists
        if '_marked_for_expiry' in data:
            effect._marked_for_expiry = data['_marked_for_expiry']
            
        return effect
    
class SkipEffect(BaseEffect):
    """Forces a character to skip their turn"""
    def __init__(self, duration: int = 1, reason: Optional[str] = None):
        super().__init__(
            name="Skip Turn",
            duration=duration,
            permanent=False,
            category=EffectCategory.STATUS
        )
        self.reason = reason
        self.turns_remaining = duration
        self.skips_turn = True  # Special flag checked by initiative.py
        self.turns_skipped = 0  # Count how many turns we've skipped

    def on_apply(self, character, round_number: int) -> str:
        """Initialize timing and provide feedback"""
        self.initialize_timing(round_number, character.name)
        
        # Format base message
        msg = f"⏭️ `{character.name}'s turns will be skipped"
        if self.duration > 1:
            msg += f" for {self.duration} rounds"
        msg += "`"
        
        # Add reason if provided
        if self.reason:
            msg += f"\n• `{self.reason}`"
            
        return msg

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process skip at start of affected character's turn"""
        if character.name == turn_name:
            # Only skip if we haven't hit our duration yet
            if self.turns_skipped < self.duration:
                self.turns_skipped += 1
                
                # For the final turn, add a different message
                if self.turns_skipped == self.duration:
                    details = ["Last skipped turn"]
                    if self.reason:
                        details.append(self.reason)
                    return [self.format_effect_message(
                        f"{character.name}'s turn is skipped!",
                        details,
                        emoji="⏭️"
                    )]
                else:
                    # For standard turns, show remaining skips
                    remaining = self.duration - self.turns_skipped
                    details = [f"{remaining} {'skips' if remaining > 1 else 'skip'} remaining"]
                    if self.reason:
                        details.append(self.reason)
                    return [self.format_effect_message(
                        f"{character.name}'s turn is skipped!",
                        details,
                        emoji="⏭️"
                    )]
            else:
                # If we've skipped enough turns, no longer skip
                self.skips_turn = False
                
            return []
        return []

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Update duration tracking and mark for removal if needed"""
        if character.name != turn_name:
            return []
        
        # If we've skipped all our turns, mark for removal
        if self.turns_skipped >= self.duration:
            self._marked_for_expiry = True
            return [self.format_effect_message(
                f"Skip effect will wear off from {character.name}",
                emoji="⏭️"
            )]
            
        return []

    def on_expire(self, character) -> str:
        """Clean up message when effect expires"""
        return self.format_effect_message(
            f"Skip effect has worn off from {character.name}",
            emoji="⏭️"
        )

    def get_status_text(self, character) -> str:
        """Format status text for display"""
        remaining = self.duration - self.turns_skipped
        base = f"⏭️ **Turn Skip** ({remaining} {'turn' if remaining == 1 else 'turns'} remaining)"
        if self.reason:
            return f"{base}\n• `{self.reason}`"
        return base
        
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            "reason": self.reason,
            "turns_skipped": self.turns_skipped,
            "turns_remaining": self.turns_remaining
        })
        return data
        
    @classmethod
    def from_dict(cls, data: dict) -> 'SkipEffect':
        """Create from dictionary data"""
        effect = cls(
            duration=data.get('duration', 1),
            reason=data.get('reason')
        )
        effect.turns_skipped = data.get('turns_skipped', 0)
        effect.turns_remaining = data.get('turns_remaining', effect.duration)
        
        # Restore timing if it exists
        if timing_data := data.get('timing'):
            effect.timing = EffectProcessTiming(**timing_data)
            
        # Restore marked for expiry flag
        if '_marked_for_expiry' in data:
            effect._marked_for_expiry = data['_marked_for_expiry']
            
        return effect
