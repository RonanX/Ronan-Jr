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
from .base import BaseEffect, EffectCategory, EffectTiming

logger = logging.getLogger(__name__)

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

class ACEffect(BaseEffect):
    """Handles AC modifications with stacking"""
    def __init__(self, amount: int, duration: Optional[int] = None, permanent: bool = False):
        name = f"AC {'Boost' if amount > 0 else 'Reduction'}"
        super().__init__(
            name=name,
            duration=duration,
            permanent=permanent,
            category=EffectCategory.STATUS
        )
        self.amount = amount
        self.effect_id = f"ac_mod_{id(self)}"  # Unique ID for each instance

    def on_apply(self, character, round_number: int) -> str:
        """Apply AC modification"""
        self.initialize_timing(round_number, character.name)
        
        # Apply through AC manager
        character.modify_ac(self.effect_id, self.amount)
        
        sign = '+' if self.amount > 0 else ''
        details = []

        # Add duration info
        if self.permanent:
            details.append("Effect is permanent")
        elif self.duration:
            details.append(f"Duration: {self.duration} turns")

        # Add current AC
        details.append(f"Current AC: {character.defense.current_ac}")
        
        return self.format_effect_message(
            f"{character.name}'s AC modified by {sign}{self.amount}",
            details
        )

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Show current AC modification"""
        if character.name != turn_name:
            return []
            
        sign = '+' if self.amount > 0 else ''
        # Let effect formatter handle backticks
        return [self.format_effect_message(
            f"AC Modified: {sign}{self.amount}",
            [f"Current AC: {character.defense.current_ac}"]
        )]

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process duration and show remaining time"""
        if character.name != turn_name or self.permanent:
            return []
            
        # Get duration status
        turns_remaining, should_expire = self.process_duration(round_number, turn_name)
        
        if should_expire:
            # Mark for removal at end of turn
            if hasattr(self, 'timing'):
                self.timing.duration = 0
                # Let effect formatter handle backticks
                return [self.format_effect_message(
                    f"AC modification will wear off",
                    [f"Current AC: {character.defense.current_ac}"]
                )]
        elif turns_remaining > 0:
            # Show remaining duration
            sign = '+' if self.amount > 0 else ''
            # Let effect formatter handle backticks
            return [self.format_effect_message(
                f"AC modification continues", 
                [f"{turns_remaining} {'turn' if turns_remaining == 1 else 'turns'} remaining"]
            )]
            
        return []

    def on_expire(self, character) -> str:
        """Clean up AC modification"""
        character.remove_ac_modifier(self.effect_id)
        sign = '+' if self.amount > 0 else ''
        # Let effect formatter handle backticks
        return self.format_effect_message(
            f"AC modification expired from {character.name}",
            [f"Was {sign}{self.amount}"]
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            'amount': self.amount,
            'effect_id': self.effect_id
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'ACEffect':
        """Create from saved dictionary data"""
        effect = cls(
            amount=data.get('amount', 0),
            duration=data.get('duration'),
            permanent=data.get('permanent', False)
        )
        if timing_data := data.get('timing'):
            effect.timing = EffectTiming(**timing_data)
        effect.effect_id = data.get('effect_id', f"ac_mod_{id(effect)}")
        return effect

class FrostbiteEffect(BaseEffect):
    """
    Frostbite effect that stacks up to 3 times:
    - Each stack reduces movement and saving throws
    - At 3 stacks, target is fully frozen
    - Stacks automatically reduce over time
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

    def on_apply(self, character, round_number: int) -> str:
        """Apply initial frostbite effect"""
        self.initialize_timing(round_number, character.name)
        
        # Apply penalties based on stacks
        messages = []
        messages.append(self.format_effect_message(
            f"{character.name} is afflicted by Frostbite {self.stacks}/3",
            [f"Movement: -{self.stacks * 5} ft",
             f"STR/DEX Saves: -{self.stacks}",
             f"Duration: {self.duration} turns"]
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
                 "Attacks have advantage"]
            ))
            
        return "\n".join(messages)

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process start of turn effects"""
        if character.name != turn_name:
            return []

        messages = []
        
        # Show frozen state if applicable
        if self.stacks >= 3:
            messages.append(self.format_effect_message(
                "Frozen Solid",
                ["Cannot take actions or reactions",
                 "AC reduced to 5",
                 "Automatically fails STR/DEX saves",
                 "Vulnerable to critical hits"]
            ))
        else:
            messages.append(self.format_effect_message(
                f"Frostbite Penalties ({self.stacks}/3)",
                [f"Movement: -{self.stacks * 5} ft",
                 f"STR/DEX Saves: -{self.stacks}"]
            ))
            
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process duration tracking and stack reduction"""
        if character.name != turn_name:
            return []
            
        messages = []
        
        # Process duration tracking first
        turns_remaining, should_expire = self.process_duration(round_number, turn_name)
        
        # If effect should expire
        if should_expire:
            self.stacks = 0  # Clear stacks to ensure cleanup
            if self.effect_id in getattr(character.ac_manager, 'modifiers', {}):
                character.remove_ac_modifier(self.effect_id)
            messages.append(self.format_effect_message(
                f"Frostbite will wear off from {character.name}"
            ))
            return messages
            
        # If we have 3 stacks, check if we should reduce them after skip turn
        if self.stacks >= 3 and self.skip_applied:
            self.stacks -= 1
            self.skip_applied = False  # Reset skip tracking
            if self.effect_id in getattr(character.ac_manager, 'modifiers', {}):
                character.remove_ac_modifier(self.effect_id)
            messages.append(self.format_effect_message(
                f"Frostbite reduced to {self.stacks}/3 stacks"
            ))
        # Otherwise handle normal stack reduction (every turn)
        elif self.stacks > 0 and round_number > self.last_stack_reduction:
            old_stacks = self.stacks
            self.stacks -= 1
            self.last_stack_reduction = round_number
            
            if self.stacks <= 0:
                messages.append(self.format_effect_message(
                    f"Frostbite will wear off from {character.name}"
                ))
            else:
                messages.append(self.format_effect_message(
                    f"Frostbite reduced to {self.stacks}/3 stacks"
                ))
                
        # Show remaining turns if any
        if turns_remaining > 0 and self.stacks > 0:
            messages.append(self.format_effect_message(
                f"Frostbite continues",
                [f"{turns_remaining} {'turn' if turns_remaining == 1 else 'turns'} remaining"]
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
            return self.format_effect_message(f"{character.name} has thawed out")
        return self.format_effect_message(f"Frostbite has worn off from {character.name}")

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
                 "Cannot take actions"]
            ))
        else:
            messages.append(self.format_effect_message(
                f"Frostbite increased to {self.stacks}/3 on {character.name}",
                [f"Movement: -{self.stacks * 5} ft",
                 f"STR/DEX Saves: -{self.stacks}"]
            ))
            
        # Reset duration when stacks are added
        if hasattr(self, 'timing'):
            self.timing.duration = self.duration
            
        return "\n".join(messages)
        
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            'stacks': self.stacks,
            'effect_id': self.effect_id,
            'last_stack_reduction': self.last_stack_reduction,
            'skip_applied': self.skip_applied
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
            effect.timing = EffectTiming(**timing_data)
        effect.effect_id = data.get('effect_id', f"frostbite_ac_{id(effect)}")
        effect.last_stack_reduction = data.get('last_stack_reduction', 0)
        effect.skip_applied = data.get('skip_applied', False)
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

    def on_apply(self, character, round_number: int) -> str:
        self.initialize_timing(round_number, character.name)
        msg = f"⏭️ `{character.name}'s turns will be skipped"
        if self.duration > 1:
            msg += f" for {self.duration} rounds"
        msg += "`"
        if self.reason:
            msg += f"\n╰─ `{self.reason}`"
        return msg

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process skip at start of affected character's turn"""
        if character.name == turn_name:
            messages = [f"⏭️ `{character.name}'s turn is skipped!`"]
            if self.reason:
                messages.append(f"╰─ `{self.reason}`")
            return messages
        return []

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Update duration tracking"""
        if character.name != turn_name:
            return []
            
        messages = []
        rounds_completed = round_number - self.timing.start_round
        if turn_name == self.timing.start_turn:
            rounds_completed += 1
            
        self.turns_remaining = max(0, self.duration - rounds_completed)
            
        if self.turns_remaining <= 0:
            messages.append(f"⏭️ `Skip effect will wear off from {character.name}`")
            self._mark_for_removal()
            
        return messages

    def _mark_for_removal(self):
        """Mark effect for removal at end of turn"""
        if hasattr(self, 'timing'):
            self.timing.duration = 0

    def get_status_text(self, character) -> str:
        base = f"⏭️ **Turn Skip** ({self.turns_remaining} {'turn' if self.turns_remaining == 1 else 'turns'} remaining)"
        if self.reason:
            return f"{base}\n╰─ `{self.reason}`"
        return base