"""
src/core/effects/base.py

Base effect system classes and registry.
This module contains the core functionality that all effects build upon.

The effect system is designed to handle temporary and permanent status effects on characters.

IMPLEMENTATION MANDATES:
- All new effects MUST inherit from BaseEffect
- Use format_effect_message() for ALL message formatting
- Never add backticks manually - they're handled by the formatting system
- Always implement on_expire() for cleanup
- Always use process_duration() for duration tracking
- Always provide proper from_dict() methods for database storage
- Register ALL new effects in manager.py

The effect system is designed to be extensible but consistent.
Breaking these patterns will lead to inconsistent behavior.
"""

"""
Implementation Mandates:

1. Effect Processing:
   - ALL effect processing MUST go through manager.process_effects()
   - NEVER process effects directly in commands/
   - Individual effects only implement their specific behavior
   - Always use proper phase ('start' or 'end')

2. Message Formatting:
   - ALL effect messages MUST use BaseEffect.format_effect_message()
   - NEVER add raw backticks
   - NEVER format messages in commands/
   - Always pass details as list, not pre-formatted string

3. State Management:
   - ALL state changes MUST be tracked in the effect
   - NEVER modify character stats directly
   - Always use proper cleanup in on_expire()
   - Document any special state handling

4. New Effects:
   - MUST inherit from BaseEffect
   - MUST implement on_apply(), on_expire()
   - MUST use standard message formatting
   - MUST document any special behavior
   
These mandates ensure:
- Single source of truth for processing (manager.py)
- Consistent message formatting (base.py)
- Clean state management
- Maintainable codebase
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Any, Type, Tuple
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

"""
The effect system is designed to handle temporary and permanent status effects on characters.
Examples include:
- Combat effects like burning, bleeding, or stunned
- Resource effects like HP regeneration or mana drain
- Status effects like AC changes or condition effects
- Custom effects for specific character abilities

Key concepts:
- Effects have durations measured in combat rounds
- Effects can be permanent or temporary
- Effects can stack, expire, and be removed
- Effects process at specific times (turn start/end)
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Any, Type, Tuple
from enum import Enum
from datetime import datetime

class EffectCategory(str, Enum):
    """
    Main categories for organizing effects. Having categories helps with:
    - Organizing effects in the UI
    - Filtering effects by type
    - Applying category-specific logic
    
    Categories:
    - COMBAT: Effects that deal damage over time like burn, bleed, poison
    - RESOURCE: Effects that modify resources like HP/MP regeneration or drain
    - STATUS: Effects that change character state like stuns or AC modifiers
    - CUSTOM: Special effects with custom messages and behaviors
    """
    COMBAT = "combat"     # Damage-dealing effects (burn, bleed, etc)
    RESOURCE = "resource" # Resource modification (hp/mp regen, drain)
    STATUS = "status"     # Status changes (stun, AC changes) 
    CUSTOM = "custom"     # Custom message effects

@dataclass
class EffectTiming:
    """
    Tracks when an effect was applied and should expire.
    
    Key timing concepts:
    - start_round: The combat round when effect was applied
    - start_turn: The character whose turn it was when applied
    - duration: How many rounds the effect lasts (None = permanent)
    
    Effects expire at the end of the affected character's turn after
    duration has elapsed. This ensures they get their full duration
    regardless of when in the turn order they were applied.
    """
    def __init__(self, start_round: int, start_turn: str, duration: Optional[int] = None):
        self.start_round = start_round
        self.start_turn = start_turn
        self.duration = duration
    
    def should_expire(self, current_round: int, current_turn: str) -> bool:
        """
        Check if effect should expire based on current round and turn.
        
        Effects expire when:
        1. We're on the same character's turn as when effect was applied
        2. The required number of rounds have passed
        
        Fix: Don't expire effects in the same round they were applied.
        """
        if self.duration is None:
            return False
        
        # Different logic based on round
        if current_round == self.start_round:
            # Same round as when effect was applied - never expire immediately
            return False
        
        # Calculate completed rounds since effect start (without the +1 that caused early expiry)
        rounds_completed = current_round - self.start_round
        
        # Only expire on the character's turn and when duration has passed
        return rounds_completed >= self.duration and current_turn == self.start_turn
    
class BaseEffect:
    """
    Base class that all effects inherit from. Provides core effect functionality:
    
    Key features:
    - Timing system for duration tracking
    - Standard lifecycle hooks (apply, turn start/end, expire)
    - Status text formatting
    - Database serialization
    - Stack management helpers
    - Message formatting utilities
    
    To create a new effect type:
    1. Inherit from this class
    2. Override relevant lifecycle methods
    3. Add effect-specific attributes and logic
    4. Register with EffectRegistry
    """
    def __init__(
        self, 
        name: str,
        duration: Optional[int] = None,
        permanent: bool = False,
        category: EffectCategory = None,
        description: Optional[str] = None,
        handles_own_expiry: bool = False,
        emoji: Optional[str] = None
    ):
        """
        Initialize a new effect instance.
        
        Parameters:
        - name: Display name of the effect
        - duration: How many rounds it lasts (None = permanent)
        - permanent: If True, effect never expires
        - category: Which EffectCategory it belongs to
        - description: Optional description for UI display
        - handles_own_expiry: If True, effect manages its own expiry logic
        - emoji: Optional custom emoji for messages
        """
        self.name = name
        self.category = category
        self.description = description
        self.permanent = permanent
        self._duration = duration  # Store as protected variable
        self.timing: Optional[EffectTiming] = None
        self._handles_own_expiry = handles_own_expiry  # Flag for special effects
        self._marked_for_expiry = False  # Flag to mark for expiry
        self._will_expire_next = False   # Signals that effect will expire next turn
        self._custom_emoji = emoji       # Custom emoji override
        
        # New tracking fields for improved duration handling
        self._application_round = None   # When effect was first applied
        self._application_turn = None    # Whose turn it was when applied
        self._expiry_message_sent = False  # Track if expiry message has been sent
    
    @property
    def duration(self) -> Optional[int]:
        """
        Duration property to ensure it's always accessible.
        Returns None for permanent effects.
        """
        return self._duration
    
    def initialize_timing(self, round_number: int, character_name: str) -> None:
        """
        Set up timing tracking when effect is first applied.
        Creates an EffectTiming instance to track when effect should expire.
        """
        self.timing = EffectTiming(
            start_round=round_number,
            start_turn=character_name,
            duration=None if self.permanent else self._duration
        )
        
        # Store application info for improved duration handling
        self._application_round = round_number
        self._application_turn = character_name
    
    def on_apply(self, character, round_number: int) -> str:
        """
        Called when effect is first applied to a character.
        
        Steps:
        1. Initialize timing tracking
        2. Apply initial effect (in subclasses)
        3. Return feedback message
        
        Override in subclasses to add custom apply logic.
        """
        self.initialize_timing(round_number, character.name)
        return f"✨ {self.name} applied to {character.name}"

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Called at start of any character's turn.
        
        Common uses:
        - Applying DOT damage
        - Triggering status effects
        - Processing stacks
        
        Returns list of effect messages to display.
        Override in subclasses to add turn start behavior.
        """
        # Default implementation: show status message on affected character's turn
        if character.name == turn_name:
            return [self.get_turn_start_message(character, round_number)]
        return []

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Called at end of any character's turn.
        
        Common uses:
        - Updating durations
        - Cleaning up expired effects
        - Processing end-of-turn triggers
        
        Returns list of effect messages to display.
        Override in subclasses to add turn end behavior.
        """
        # Only process on character's turn, skip permanent effects
        if character.name != turn_name or self.permanent:
            return []
            
        # Use standardized duration tracking
        turns_remaining, will_expire_next, should_expire_now = self.process_duration(
            round_number, turn_name
        )
        
        # Handle expiry with standardized flag
        if should_expire_now:
            if not self._expiry_message_sent:
                self._expiry_message_sent = True
                self._marked_for_expiry = True
                return [self.format_effect_message(
                    f"{self.name} has worn off from {character.name}"
                )]
        
        # Handle final turn warning
        if will_expire_next:
            self._will_expire_next = True
            return [self.format_effect_message(
                f"{self.name} continues",
                [f"Final turn - will expire after this turn"]
            )]
            
        # Regular duration update
        if turns_remaining is not None and turns_remaining > 0:
            s = "s" if turns_remaining != 1 else ""
            return [self.format_effect_message(
                f"{self.name} continues",
                [f"{turns_remaining} turn{s} remaining"]
            )]
            
        return []

    def on_expire(self, character) -> str:
        """
        Called when effect expires naturally or is removed.
        
        Common uses:
        - Cleaning up effect state
        - Reverting modified stats
        - Generating expiry message
        
        Override in subclasses to add cleanup logic.
        """
        return f"✨ {self.name} has worn off from {character.name}"

    def get_status_text(self, character) -> str:
        """Get formatted status text for effect list display"""
        # Get base info
        lines = [f"**{self.name}**"]
        
        # Add duration info
        if self.timing and self.timing.duration is not None:
            if hasattr(character, 'round_number'):
                rounds_passed = character.round_number - self.timing.start_round
                remaining = max(0, self.timing.duration - rounds_passed)
                lines.append(f"• `{remaining} turn{'s' if remaining != 1 else ''} remaining`")
        elif self.permanent:
            lines.append("• `Permanent`")
            
        # Add description if available
        if self.description:
            # Split description into bullets if it contains semicolons
            if ';' in self.description:
                for bullet in self.description.split(';'):
                    if bullet := bullet.strip():
                        lines.append(f"• `{bullet}`")
            else:
                lines.append(f"• `{self.description}`")
                
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """
        Convert effect to dictionary for database storage.
        
        Stores:
        - Effect type and name
        - Category and description
        - Duration and permanent status
        - Timing information
        - All expiry state flags
        
        Override in subclasses to store additional attributes.
        """
        return {
            "type": self.__class__.__name__,
            "name": self.name,
            "category": self.category.value if self.category else None,
            "description": self.description,
            "duration": self._duration,
            "permanent": self.permanent,
            "timing": self.timing.__dict__ if self.timing else None,
            "_marked_for_expiry": self._marked_for_expiry,
            "_will_expire_next": self._will_expire_next,
            "_custom_emoji": self._custom_emoji,
            "_handles_own_expiry": self._handles_own_expiry,
            "_application_round": self._application_round,
            "_application_turn": self._application_turn,
            "_expiry_message_sent": self._expiry_message_sent
        }

    @property
    def is_expired(self) -> bool:
        """
        Check if effect has expired based on timing.
        
        An effect is expired if:
        1. It's explicitly marked for expiry OR
        2. It's not permanent AND
        3. It has timing tracking AND
        4. Its duration has completed
        
        Effects that handle their own expiry (like compound moves)
        will return False and handle expiry in their own logic.
        """
        if self._handles_own_expiry:
            return False
            
        # Marked for expiry
        if self._marked_for_expiry:
            return True
            
        # Not expired if permanent
        if self.permanent:
            return False
            
        # Not expired if no timing tracking
        if not self.timing:
            return False
            
        # Not expired if duration is None
        if self.timing.duration is None:
            return False
            
        # Check if duration completed
        return self.timing.duration <= 0
    
    def process_duration(self, round_number: int, turn_name: str) -> Tuple[int, bool, bool]:
        """
        Improved duration calculation that accounts for application timing.
        
        Returns:
        - turns_remaining: How many turns remain after this one
        - will_expire_next: Whether effect will expire next turn
        - should_expire_now: Whether effect should expire now
        
        This method standardizes duration tracking across all effects.
        """
        if self.permanent or not self.timing:
            return (None, False, False)
            
        # Skip processing if not on the character's turn
        if turn_name != self.timing.start_turn:
            return (None, False, False)
            
        # Calculate elapsed turns
        turns_elapsed = round_number - self.timing.start_round
        
        # Special case: For effects applied BEFORE character's turn but in the same round,
        # they should expire at the end of their first turn
        if (self._application_round == self.timing.start_round and 
            self._application_turn != self.timing.start_turn and 
            turns_elapsed >= 1):
            return (0, False, True)  # Should expire now
        
        # Special case: For effects applied DURING character's turn,
        # we don't count the first turn_end processing toward duration
        first_turn_processing = (round_number == self._application_round and 
                                turn_name == self._application_turn)
                                
        # Calculate remaining turns, adjust for first turn special case
        turns_remaining = max(0, self.duration - turns_elapsed)
        if not first_turn_processing:
            turns_remaining -= 1
        
        # Determine expiry state
        will_expire_next = turns_remaining == 0 
        should_expire_now = turns_remaining < 0 or (turns_elapsed >= self.duration and not first_turn_processing)
        
        # Debug output for duration tracking (commented out)
        # print(f"DURATION DEBUG: effect={self.name}, elapsed={turns_elapsed}, duration={self.duration}")
        # print(f"DURATION DEBUG: first_turn={first_turn_processing}, remaining={turns_remaining}")
        # print(f"DURATION DEBUG: will_expire={will_expire_next}, should_expire={should_expire_now}")
        
        return (turns_remaining, will_expire_next, should_expire_now)
    
    def get_turn_start_message(self, character, round_number: int) -> str:
        """
        Get standardized turn start message.
        
        This helper creates consistent status messages for effects
        that don't need custom formatting.
        """
        # Skip for permanent effects
        if self.permanent:
            return self.format_effect_message(
                f"{self.name} is active on {character.name}",
                ["Permanent effect"]
            )
        
        # Calculate remaining turns
        turns_remaining = None
        will_expire_after_turn = False
        
        if self.timing and self.timing.duration:
            # Calculate based on rounds elapsed
            turns_remaining, will_expire_next, should_expire_now = self.process_duration(round_number, character.name)
            will_expire_after_turn = self._will_expire_next
        
        # Format the details
        details = []
        
        # If the description exists, add it first
        if self.description:
            details.append(self.description)
        
        # Add duration info
        if will_expire_after_turn:
            details.append("Final turn - will expire after this turn")
        elif turns_remaining is not None:
            details.append(f"{turns_remaining+1} turn{'s' if turns_remaining != 0 else ''} remaining")
        
        # Return the formatted message
        return self.format_effect_message(
            f"{self.name} active",
            details
        )
    
    def get_turn_end_message(self, character, turns_remaining: int, will_expire_next: bool) -> str:
        """
        Get standardized turn end message.
        
        This helper creates consistent duration messages based on remaining turns.
        """
        # Only show continuing message - expiry is handled separately
        if turns_remaining is not None and turns_remaining > 0:
            # Still has duration left
            s = "s" if turns_remaining != 1 else ""
            return self.format_effect_message(
                f"{self.name} continues on {character.name}",
                [f"{turns_remaining} turn{s} remaining"]
            )
        
        # Default case - generic continue message
        return self.format_effect_message(
            f"{self.name} continues on {character.name}"
        )
        
    def handle_duration_tracking(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Standardized duration tracking for all effects.
        Legacy helper maintained for compatibility with old effects.
        New effects should use process_duration directly.
        
        Returns duration messages or empty list if not applicable.
        """
        # Skip for permanent effects or when not on character's turn 
        if self.permanent or character.name != turn_name:
            return []
            
        # Process duration tracking
        turns_remaining, will_expire_next, should_expire_now = self.process_duration(round_number, turn_name)
        messages = []
        
        # Handle expiry with standardized flag
        if should_expire_now:
            if not self._expiry_message_sent:
                self._expiry_message_sent = True
                self._marked_for_expiry = True
                return [self.format_effect_message(
                    f"{self.name} has worn off from {character.name}"
                )]
        
        # Handle final turn warning
        if will_expire_next:
            self._will_expire_next = True
            return [self.format_effect_message(
                f"{self.name} continues",
                [f"Final turn - will expire after this turn"]
            )]
            
        # Regular duration update
        if turns_remaining is not None and turns_remaining > 0:
            s = "s" if turns_remaining != 1 else ""
            messages.append(self.format_effect_message(
                f"{self.name} continues",
                [f"{turns_remaining} turn{s} remaining"]
            ))
            
        return messages

    def format_effect_message(
        self,
        message: str,
        details: Optional[List[str]] = None,
        emoji: Optional[str] = None
    ) -> str:
        """
        Format effect message with consistent styling.
        Single source of truth for message formatting.
        
        Args:
            message: Main message text
            details: Optional bullet point details
            emoji: Optional emoji override (uses category default if None)
            
        Returns:
            Formatted message with proper backticks and emoji
        """
        # Strip any existing backticks to prevent doubles
        message = message.strip('` ')
        
        # Get emoji based on category if not provided
        if not emoji:
            emoji = self._custom_emoji or {
                EffectCategory.COMBAT: "⚔️",
                EffectCategory.RESOURCE: "💫",
                EffectCategory.STATUS: "✨",
                EffectCategory.CUSTOM: "✨"
            }.get(self.category, "✨")
            
        # Format main message
        formatted = f"{emoji} `{message}` {emoji}"
        
        # Add details if provided
        if details:
            # Clean and format each detail
            detail_lines = []
            for detail in details:
                if detail := detail.strip('` '):
                    detail_lines.append(f"• `{detail}`")
            if detail_lines:
                formatted += "\n" + "\n".join(detail_lines)
                
        return formatted
    
    def is_move_effect(self) -> bool:
        """Check if this is a move effect (for special handling)"""
        return hasattr(self, 'state') and hasattr(self, 'phases')

    def process_stack_reduction(self, current_round: int, last_reduction_round: int,
                            reduction_interval: int) -> Tuple[bool, int]:
        """
        Handle standard stack reduction logic for stacking effects.
        
        Used for effects that reduce stacks over time, like:
        - Poison stacks falling off
        - Buff stacks decreasing
        - Resource generation slowing
        
        Parameters:
        - current_round: Current combat round
        - last_reduction_round: When stacks were last reduced
        - reduction_interval: Rounds between reductions
        
        Returns:
        - should_reduce: Whether to reduce stacks now
        - rounds_until_next: Rounds until next reduction
        """
        rounds_since_reduction = current_round - last_reduction_round
        if rounds_since_reduction >= reduction_interval:
            return (True, reduction_interval)
        return (False, reduction_interval - rounds_since_reduction)

    def format_duration_message(self, turns_remaining: int) -> str:
        """
        Format standard duration remaining message.
        
        Examples:
        - "Effect will continue for 1 more round"
        - "Effect will continue for 3 more rounds"
        
        Returns None if no turns remaining.
        """
        if turns_remaining <= 0:
            return None
        rounds_text = "round" if turns_remaining == 1 else "rounds"
        return f"Effect will continue for {turns_remaining} more {rounds_text}"

    def process_turn(
        self,
        character,
        round_number: int,
        turn_name: str,
        phase: str = 'start'
    ) -> List[str]:
        """
        Process effect for a specific turn phase.
        Handles both regular effects and move effects properly.
        
        Args:
            character: Character being affected
            round_number: Current round number
            turn_name: Name of character whose turn it is
            phase: Which phase to process ('start' or 'end')
            
        Returns:
            List of formatted message strings

        INDIVIDUAL effect processing for a SINGLE effect.
        This is called BY manager.process_effects, not directly.
        
        Handles:
        - Individual effect logic
        - Phase-specific behavior
        - Move effect states
        - Message formatting
        
        DO NOT call this directly - use manager.process_effects instead!
        """
        messages = []
        
        # Handle move effects specially
        if self.is_move_effect():
            if phase == 'start':
                # Move effect turn start processing
                if msg := self.on_turn_start(character, round_number, turn_name):
                    messages.extend(msg if isinstance(msg, list) else [msg])
                    
            elif phase == 'end':
                # Move effect turn end + state transition
                if msg := self.on_turn_end(character, round_number, turn_name):
                    messages.extend(msg if isinstance(msg, list) else [msg])
                    
                # Let move effect handle its own state transitions
                if hasattr(self, '_transition_state'):
                    if transition_msg := self._transition_state():
                        messages.append(self.format_effect_message(transition_msg))
                        
        else:
            # Regular effect processing
            if phase == 'start':
                if msg := self.on_turn_start(character, round_number, turn_name):
                    messages.extend(msg if isinstance(msg, list) else [msg])
                    
            elif phase == 'end':
                if msg := self.on_turn_end(character, round_number, turn_name):
                    messages.extend(msg if isinstance(msg, list) else [msg])
                    
                # Handle expiry in end phase for regular effects
                if not self._handles_own_expiry:
                    if self._marked_for_expiry or (self.timing and self.timing.should_expire(round_number, turn_name)):
                        if msg := self.on_expire(character):
                            messages.append(msg)
                        character.effects.remove(self)
                        
        return messages

class CustomEffect(BaseEffect):
    """
    Special effect type for custom messages and reminders.
    
    Used for:
    - Character-specific abilities
    - Story-related status effects 
    - Custom condition tracking
    - Any effect needing custom messages
    
    Features:
    - Multiple detail bullets
    - Duration tracking
    - Permanent option
    - Description parsing
    - Turn start/end messages
    """
    def __init__(
        self, 
        name: str, 
        duration: Optional[int], 
        description: str, 
        permanent: bool = False,
        bullets: Optional[List[str]] = None
    ):
        """
        Initialize custom effect.
        
        Parameters:
        - name: Effect name
        - duration: How many rounds it lasts
        - description: Main effect description
        - permanent: Whether it expires
        - bullets: List of detail points
        
        Note: If description contains semicolons, it's split into bullets
        """
        super().__init__(
            name=name, 
            duration=duration, 
            permanent=permanent, 
            category=EffectCategory.CUSTOM, 
            description=description
        )
        self.bullets = bullets or []
        # Split description into bullets if it contains semicolons
        if description and ';' in description:
            self.bullets = [b.strip() for b in description.split(';')]

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Display effect details at start of turn"""
        if character.name != turn_name:
            return []
            
        details = []
        if self.bullets:
            details.extend(self.bullets)
        elif self.description:
            details.append(self.description)
            
        # Add remaining turns if duration is set
        if self.duration and not self.permanent:
            turns_remaining, will_expire_next, _ = self.process_duration(round_number, turn_name)
            if will_expire_next:
                details.append("Final turn - will expire after this turn")
            elif turns_remaining is not None and turns_remaining >= 0:
                plural = "s" if turns_remaining != 0 else ""
                details.append(f"{turns_remaining+1} turn{plural} remaining")
            
        return [self.format_effect_message(
            f"{self.name}",
            details
        )]

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Track duration and show remaining time"""
        # Only process on character's own turn, skip for permanent effects
        if character.name != turn_name or self.permanent:
            return []
            
        # Use standardized duration tracking
        turns_remaining, will_expire_next, should_expire_now = self.process_duration(round_number, turn_name)
        
        # Handle expiry with standardized flag
        if should_expire_now:
            if not self._expiry_message_sent:
                self._expiry_message_sent = True
                self._marked_for_expiry = True
                return [self.format_effect_message(
                    f"{self.name} has worn off from {character.name}"
                )]
        
        # Handle final turn warning
        if will_expire_next:
            self._will_expire_next = True
            return [self.format_effect_message(
                f"{self.name} continues",
                [f"Final turn - will expire after this turn"]
            )]
            
        # Regular duration update
        if turns_remaining is not None and turns_remaining > 0:
            s = "s" if turns_remaining != 1 else ""
            return [self.format_effect_message(
                f"{self.name} continues",
                [f"{turns_remaining} turn{s} remaining"]
            )]
                
        return []

    def on_expire(self, character) -> str:
        """Handle effect expiry"""
        return self.format_effect_message(
            f"{self.name} has worn off from {character.name}"
        )

    def get_status_text(self, character) -> str:
        """
        Get formatted status display text.
        
        Format:
        Effect Name:
        • Bullet 1
        • Bullet 2
        • Duration info
        
        Handles both bullet points and single description.
        """
        lines = [f"✨ **{self.name}**"]
        
        # Add bullets or description
        if self.bullets:
            for bullet in self.bullets:
                lines.append(f"• `{bullet}`")
        elif self.description:
            lines.append(f"• `{self.description}`")
            
        # Add duration info
        if self.duration and self.duration > 0:
            if hasattr(self, 'timing'):
                # Calculate remaining duration if we have timing info
                rounds_passed = 0
                if self.timing.start_round:
                    rounds_passed = character.round_number - self.timing.start_round
                remaining = max(0, self.duration - rounds_passed)
                lines.append(f"• `{remaining} turn{'s' if remaining != 1 else ''} remaining`")
            else:
                lines.append(f"• `{self.duration} turn{'s' if self.duration != 1 else ''} duration`")
        elif self.permanent:
            lines.append("• `Permanent`")
            
        return "\n".join(lines)
    
    def to_dict(self) -> dict:
        """
        Convert to dictionary for storage.
        Adds bullets to base effect data.
        """
        data = super().to_dict()
        data.update({
            "bullets": self.bullets,
            "description": self.description
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'CustomEffect':
        """Create from dictionary data"""
        effect = cls(
            name=data.get('name', 'Custom Effect'),
            duration=data.get('duration'),
            description=data.get('description', ''),
            permanent=data.get('permanent', False),
            bullets=data.get('bullets', [])
        )
        if timing_data := data.get('timing'):
            effect.timing = EffectTiming(**timing_data)
        effect._marked_for_expiry = data.get('_marked_for_expiry', False)
        effect._will_expire_next = data.get('_will_expire_next', False)
        effect._application_round = data.get('_application_round')
        effect._application_turn = data.get('_application_turn')
        effect._expiry_message_sent = data.get('_expiry_message_sent', False)
        return effect

    def can_affect(self, character) -> Tuple[bool, Optional[str]]:
        """
        Check if this effect can be applied to a character.
        
        Returns:
        - (True, None) if effect can be applied
        - (False, reason) if character is immune
        
        Example reasons:
        - "Already afflicted by Frozen"
        - "Immune to Fire effects"
        - "Protected by Greater Ward"
        
        Override in subclasses to add immunity checks.
        """
        return True, None  # Base implementation: no immunities

class EffectRegistry:
    """
    Central registry for managing effect types.
    
    Purpose:
    - Store and manage all available effect types
    - Create new effect instances
    - Reconstruct effects from database data
    
    The registry acts like a factory - you register effect classes,
    then use it to create instances of those effects. This centralizes
    effect management and makes it easy to:
    - Add new effect types
    - Create effects by name
    - Load effects from saved data
    - Ensure consistency
    """
    """
    Central registry for managing effect types.
    
    Purpose:
    - Register new effect types
    - Create effect instances
    - Recreate effects from database
    
    Usage:
    1. Register effect classes with register_effect()
    2. Create instances with create_effect()
    3. Load from database with from_dict()
    """
    # Dictionary mapping effect names to their classes
    _effects = {}  # Format: {'effect_name': EffectClass}

    @classmethod
    def register_effect(cls, name: str, effect_class) -> None:
        """
        Register a new effect type in the registry.
        
        This is how new effects are made available to the system.
        Always register effects before trying to create them.
        
        Parameters:
        - name: Name to reference this effect by (converted to lowercase)
        - effect_class: The class that implements the effect
        
        Example:
        ```python
        # Register a burn effect
        EffectRegistry.register_effect('burn', BurnEffect)
        
        # Later, create instances by name
        burn = EffectRegistry.create_effect('burn', duration=3)
        ```
        """
        cls._effects[name.lower()] = effect_class

    @classmethod
    def create_effect(cls, name: str, *args, **kwargs) -> Optional[BaseEffect]:
        """
        Create a new instance of a registered effect type.
        
        This is the main way to create new effects. Instead of creating
        effect instances directly, use this method to ensure the effect
        type exists and is properly initialized.
        
        Parameters:
        - name: Name of the registered effect type
        - *args: Positional arguments to pass to effect constructor
        - **kwargs: Keyword arguments to pass to effect constructor
        
        Returns:
        - New effect instance if type exists
        - None if effect type not found
        
        Example:
        ```python
        # Create a 3-turn burn effect
        burn = EffectRegistry.create_effect('burn', 
                                          duration=3,
                                          damage='1d6')
        
        # Create a permanent resistance effect
        resist = EffectRegistry.create_effect('resistance',
                                            damage_type='fire',
                                            percentage=50,
                                            permanent=True)
        ```
        """
        effect_class = cls._effects.get(name.lower())
        if effect_class:
            return effect_class(*args, **kwargs)
        return None

    @classmethod
    def from_dict(cls, data: dict) -> Optional[BaseEffect]:
        """
        Reconstruct an effect instance from database dictionary data.
        
        This method handles converting saved effect data back into
        working effect instances. It's used when:
        - Loading characters from database
        - Restoring game state
        - Reconstructing effects after updates
        
        Process:
        1. Look up the effect class by type name
        2. If effect has custom from_dict(), use that
        3. Otherwise, create new instance and restore data:
           - Initialize with default values
           - Restore basic effect attributes
           - Restore timing information
           - Restore effect-specific attributes
        
        Parameters:
        - data: Dictionary of effect data from database
        
        Returns:
        - Reconstructed effect instance if successful
        - None if effect type not found
        """
        
        print(f"\nReconstructing effect:")
        print(f"  Data received: {data}")
        
        # Find effect class
        effect_type = data.get('type')
        print(f"  Looking for effect type: {effect_type}")
        effect_class = next(
            (effect_class for effect_class in cls._effects.values() 
            if effect_class.__name__ == effect_type),
            None
        )
        
        # If no matching effect class found, we can't reconstruct it
        if not effect_class:
            print(f"  No matching effect class found for type: {effect_type}")
            return None
            
        print(f"  Found effect class: {effect_class.__name__}")
        
        # If effect has custom loading logic, use that instead
        if hasattr(effect_class, 'from_dict'):
            print("  Using effect's custom from_dict method")
            reconstructed = effect_class.from_dict(data)
            print(f"  Reconstructed effect: {reconstructed.__dict__ if reconstructed else None}")
            return reconstructed
            
        try:
            # Create base instance
            print("  Creating base instance")
            effect = effect_class.__new__(effect_class)
            
            # Get required init params from data
            params = {}
            if 'source_character' in data:
                params['source_character'] = data['source_character']
            if 'stacks' in data:
                params['stacks'] = data['stacks']
            if 'duration' in data:
                params['duration'] = data['duration']
            
            print(f"  Init params: {params}")
            
            # Initialize with available params
            effect_class.__init__(effect, **params)
            
            # Initialize base effect attributes
            BaseEffect.__init__(
                effect,
                name=data['name'],
                duration=data.get('duration'),
                permanent=data.get('permanent', False),
                category=EffectCategory(data['category']) if data.get('category') else None,
                description=data.get('description')
            )
            
            # Restore timing information if it was saved
            if timing_data := data.get('timing'):
                print(f"  Restoring timing: {timing_data}")
                effect.timing = EffectTiming(**timing_data)
            
            # Restore effect flags
            effect._marked_for_expiry = data.get('_marked_for_expiry', False)
            effect._will_expire_next = data.get('_will_expire_next', False)
            effect._custom_emoji = data.get('_custom_emoji')
            effect._application_round = data.get('_application_round')
            effect._application_turn = data.get('_application_turn')
            effect._expiry_message_sent = data.get('_expiry_message_sent', False)
                
            # Restore any additional effect-specific attributes
            for key, value in data.items():
                if key not in ['name', 'type', 'duration', 'permanent', 'category', 
                            'description', 'timing', 'source_character', 'stacks',
                            '_marked_for_expiry', '_will_expire_next', '_custom_emoji',
                            '_application_round', '_application_turn', '_expiry_message_sent']:
                    print(f"  Restoring attribute: {key} = {value}")
                    setattr(effect, key, value)
                    
            print(f"  Final reconstructed effect: {effect.__dict__}")
            return effect
            
        except Exception as e:
            logger.error(f"Failed to reconstruct effect {effect_type}: {str(e)}")
            print(f"  Error during reconstruction: {str(e)}")
            return None