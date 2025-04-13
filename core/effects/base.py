"""
Core Effects System (base.py) - Reworked

This module provides the foundational classes and logic for the game's effect system.
It defines the BaseEffect class, state management, duration tracking, and message formatting.

Key Design Principles:
- Unified State Model: Clear states (CREATED, ACTIVE, EXPIRING, EXPIRED, REMOVED).
- Event-Driven Lifecycle: Consistent hooks (on_apply, on_turn_start, on_turn_end, on_expire).
- Simplified Duration Logic: Handles 'during' vs 'not during' application consistently.
- Centralized Message Handling: Standard formatting and feedback integration.
- Debuggability: Built-in debug logging.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Type, Tuple, Union
from enum import Enum
import logging
import inspect
import re

logger = logging.getLogger(__name__)

class EffectState(Enum):
    """
    Defines the possible states of an effect during its lifecycle.
    """
    CREATED = "created"      # Initial state, not yet applied
    ACTIVE = "active"        # Effect is currently active and processing
    EXPIRING = "expiring"    # Marked for expiry on the next turn end
    EXPIRED = "expired"      # Duration has completed, ready for removal
    REMOVED = "removed"      # Effect has been fully removed and cleaned up

class EffectCategory(str, Enum):
    """Categorizes effects for organization and potential filtering."""
    COMBAT = "combat"        # Damage-dealing effects (burn, bleed, etc)
    RESOURCE = "resource"    # Resource modification (hp/mp regen, drain)
    STATUS = "status"        # Status changes (stun, AC changes, buffs/debuffs)
    CUSTOM = "custom"        # Effects with unique behavior or messaging

# Renamed from EffectProcessTiming
class EffectProcessTiming(Enum):
    START = "start"
    END = "end"
    BOTH = "both"

# --- Base Effect Class ---

@dataclass
class EffectProcessTimingInfo:
    """Stores timing information for an effect."""
    start_round: int
    start_turn_name: str
    applied_during_own_turn: bool = False

class BaseEffect:
    """
    Base class for all effects in the game.

    Provides core functionality:
    - State management (CREATED, ACTIVE, EXPIRING, EXPIRED, REMOVED)
    - Duration tracking with handling for 'during' vs 'not during' application
    - Standard lifecycle hooks (on_apply, on_turn_start, on_turn_end, on_expire)
    - Consistent message formatting
    - Debug logging support
    - Database serialization hooks (to_dict, from_dict - though subclasses implement details)
    """
    def __init__(
        self,
        name: str,
        duration: Optional[int] = None,
        permanent: bool = False,
        category: Optional[EffectCategory] = EffectCategory.CUSTOM,
        description: Optional[str] = None,
        process_timing: str = "both", # "start", "end", or "both"
        emoji: Optional[str] = "✨",
        debug_mode: bool = False
    ):
        """
        Initialize a new effect instance.

        Args:
            name (str): Display name of the effect.
            duration (Optional[int]): How many turns the effect lasts. None means permanent.
            permanent (bool): If True, the effect never expires by duration.
            category (Optional[EffectCategory]): The category this effect belongs to.
            description (Optional[str]): A brief description for UI/display.
            process_timing (str): When the effect logic runs ('start', 'end', 'both').
            emoji (Optional[str]): Default emoji for messages.
            debug_mode (bool): Enable detailed logging for this effect instance.
        """
        self.name = name
        self._display_duration = duration # The duration shown to the user
        self.permanent = permanent
        self.category = category
        self.description = description
        try:
            # Validate process_timing against the Enum
            self.process_timing = EffectProcessTiming(process_timing.lower()).value
        except ValueError:
            self.debug(f"Warning: Invalid process_timing '{process_timing}'. Defaulting to 'both'.")
            self.process_timing = EffectProcessTiming.BOTH.value
        self.emoji = emoji
        self.debug_mode = debug_mode
        self.debug_log = []

        # --- State and Timing ---
        self.state = EffectState.CREATED
        self.timing: Optional[EffectProcessTimingInfo] = None
        self._internal_duration = duration # Adjusted duration for internal tracking
        self.turns_elapsed = 0 # How many *of the character's* turns have passed since application

        if self.permanent:
            self._internal_duration = None # Permanent effects have no internal duration limit
            self._display_duration = None

        self.debug(f"Initialized: Duration(Display={self._display_duration}, Internal={self._internal_duration}), Permanent={self.permanent}, Timing={self.process_timing}")

    # --- Properties ---

    @property
    def duration(self) -> Optional[int]:
        """Returns the display duration of the effect."""
        return self._display_duration

    # --- Debugging ---

    def debug(self, message: str):
        """Log a debug message if debug_mode is enabled."""
        if self.debug_mode:
            log_msg = f"[{self.name}|{self.state.value}] {message}"
            self.debug_log.append(log_msg)
            # Optionally print to console immediately for real-time debugging
            # print(log_msg)

    # --- Lifecycle Methods (Subclasses Override These) ---

    def on_apply(self, character, round_number: int) -> str:
        """
        Called when the effect is first applied to a character.
        Handles state transition, timing initialization, and duration adjustment.
        Subclasses should call super().on_apply() first if overriding.

        Returns:
            str: Formatted message indicating the effect was applied.
        """
        if self.state != EffectState.CREATED:
            self.debug(f"Warning: on_apply called on effect not in CREATED state ({self.state.value})")

        # 1. Initialize Timing
        self._initialize_timing(character, round_number)
        
        # 2. Verify timing was set properly
        if not self.timing:
            # If timing wasn't set, create a default timing object
            is_during_own = False
            if hasattr(self, 'is_during_own_turn'):
                is_during_own = self.is_during_own_turn
                
            self.timing = EffectProcessTimingInfo(
                start_round=round_number,
                start_turn_name=character.name,
                applied_during_own_turn=is_during_own
            )
            self.debug(f"Created default timing info (DURING={is_during_own})")

        # 3. Skip duration adjustment for permanent effects
        if not self.permanent and self._internal_duration is not None:
            applied_during_own = self.timing.applied_during_own_turn
            
            if applied_during_own:
                # Special case for duration=1
                if self._display_duration == 1:
                    # For duration=1 applied during own turn, we set internal to 2
                    # This ensures it doesn't expire on the same turn
                    self._internal_duration = 2
                    self.debug(f"Special case: Duration=1 applied during own turn. Internal duration set to 2")
                else:
                    # Normal case: Add 1 to internal duration to account for "free" application turn
                    self._internal_duration = self._display_duration + 1
                    self.debug(f"Applied during own turn. Internal duration set to {self._internal_duration}")
            else:
                # FIXED: For NOT during own turn, internal and display durations should be the same
                # Just ensure duration is at least 1
                self._internal_duration = max(1, self._display_duration)
                self._display_duration = self._internal_duration  # Keep them in sync
                self.debug(f"Applied NOT during own turn. Internal and display durations both set to {self._internal_duration}")

        # 4. Transition State
        self.state = EffectState.ACTIVE
        self.debug(f"Transitioned to ACTIVE. StartRound={self.timing.start_round}, StartTurn={self.timing.start_turn_name}")

        # 5. Generate Base Apply Message
        duration_text = "Permanent" if self.permanent else f"{self._display_duration} turns"

        # Include timing info in the apply message for clarity
        applied_during_text = "DURING" if self.timing and self.timing.applied_during_own_turn else "NOT DURING"
        
        details = [
            f"Duration: {duration_text}",
            f"Timing: {self.process_timing}",
            f"Applied: {applied_during_text} turn"
        ]
        
        # Add internal duration in debug mode
        if self.debug_mode and self._internal_duration is not None and not self.permanent:
            details.append(f"Internal Duration: {self._internal_duration}")

        return self.format_effect_message(
            f"{self.name} applied to {character.name}",
            details=details,
            emoji=self.emoji
        )
    
    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Called at the start of *every* character's turn.
        Base implementation checks if it's the correct turn and state to process.
        Subclasses override to add specific start-of-turn logic.

        Returns:
            List[str]: A list of messages generated during processing.
        """
        # Only process on the affected character's turn and if ACTIVE
        if character.name != turn_name or self.state != EffectState.ACTIVE:
            return []

        self.debug(f"Processing Turn Start (Round {round_number})")
        # Base implementation provides the hook for subclasses.
        return [] # Subclasses will add messages here

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Called at the end of *every* character's turn.
        Base implementation handles duration checking and state transitions (ACTIVE -> EXPIRING -> EXPIRED).
        Subclasses override to add specific end-of-turn logic *before* calling super().on_turn_end().

        Returns:
            List[str]: A list of messages, potentially including expiry messages.
        """
        # Only process on the affected character's turn
        if character.name != turn_name:
            return []

        self.debug(f"Processing Turn End (Round {round_number})")

        # --- Duration Check and State Transition ---
        if not self.permanent and self.timing:
            # Use the corrected calculate_duration method
            should_expire, is_final_turn, turns_remaining_display = self.calculate_duration(round_number, turn_name)

            if self.state == EffectState.ACTIVE:
                if should_expire:
                    self.debug("Duration expired. Transitioning to EXPIRED.")
                    self.state = EffectState.EXPIRED
                    expiry_msg = self.format_effect_message(f"{self.name} has worn off", emoji=self.emoji)
                    
                    # Only add to feedback, don't return directly to avoid duplication
                    self.add_feedback(character, expiry_msg, round_number, is_expiry=True)
                    return []  # Return empty list instead of including expiry message
                elif is_final_turn:
                    self.debug("Final turn reached. Transitioning to EXPIRING.")
                    self.state = EffectState.EXPIRING
                    return [self.format_effect_message(f"{self.name} continues", details=["Final turn"], emoji=self.emoji)]
                else:
                    if turns_remaining_display is not None:
                         s = "s" if turns_remaining_display != 1 else ""
                         return [self.format_effect_message(f"{self.name} continues", details=[f"{turns_remaining_display} turn{s} remaining"], emoji=self.emoji)]

            elif self.state == EffectState.EXPIRING:
                # If it was already expiring, it should now be expired after this turn end processing
                self.debug("Was EXPIRING. Transitioning to EXPIRED.")
                self.state = EffectState.EXPIRED
                expiry_msg = self.format_effect_message(f"{self.name} has worn off", emoji=self.emoji)
                
                # Only add to feedback, don't return directly to avoid duplication
                self.add_feedback(character, expiry_msg, round_number, is_expiry=True)
                return []  # Return empty list to avoid duplicate messages

        # If permanent or duration hasn't expired, return empty list
        return []

    def on_expire(self, character) -> str:
        """
        Called when the effect is finally removed (either by duration or force).
        Handles state transition to REMOVED and performs cleanup.
        Subclasses override to add specific cleanup logic *before* calling super().on_expire().

        Returns:
            str: A final confirmation message (often empty unless specific cleanup occurs).
        """
        self.debug("Processing Expiry/Removal.")
        if self.state == EffectState.REMOVED:
            self.debug("Already removed.")
            return ""

        # Final State Transition
        self.state = EffectState.REMOVED
        self.debug("Transitioned to REMOVED.")

        # Base returns empty string; expiry message handled in on_turn_end via feedback.
        return ""

    # --- Internal Helper Methods ---

    def add_feedback(self, character, message: str, round_number: int, is_expiry: bool = False):
        """Adds a message to the character's feedback queue."""
        if hasattr(character, 'add_effect_feedback'):
            self.debug(f"Adding feedback: '{message}' (Expiry={is_expiry})")
            character.add_effect_feedback(
                effect_name=self.name,
                expiry_message=message,
                round_expired=round_number,
                turn_expired=character.name
            )
        else:
            self.debug("Character object does not support add_effect_feedback.")

    def _initialize_timing(self, character, round_number: int):
        """Sets up the timing info when the effect is applied."""
        if self.timing:
            self.debug("Warning: Timing already initialized.")
            return

        # Determine if applied during character's own turn
        applied_during_own = False
        
        # First, check if this information was directly provided by apply_effect
        if hasattr(self, 'is_during_own_turn'):
            applied_during_own = self.is_during_own_turn
            current_turn = getattr(self, 'current_turn_name', None)
            self.debug(f"Using direct tracker info: current_turn={current_turn}, during_own_turn={applied_during_own}")
        else:
            # If no direct info is available, use combat flag if possible
            if hasattr(character, 'in_combat') and character.in_combat:
                # Default to NOT DURING in combat (safer assumption)
                applied_during_own = False
                self.debug("No direct tracker info, in combat - defaulting to NOT DURING")
            else:
                # Default to DURING outside combat (simpler duration calculation)
                applied_during_own = True
                self.debug("No direct tracker info, not in combat - defaulting to DURING")

        # Create timing info
        self.timing = EffectProcessTimingInfo(
            start_round=round_number,
            start_turn_name=character.name,
            applied_during_own_turn=applied_during_own
        )
        
        self.debug(f"Timing initialized: Round={round_number}, Applied During Own={applied_during_own}")
        self.turns_elapsed = 0
        
    def calculate_duration(self, current_round: int, current_turn_name: str) -> Tuple[bool, bool, Optional[int]]:
        """
        Calculates if the effect's duration has expired based on application timing.
        
        The core logic handles two cases:
        1. Applied DURING own turn: Duration ticks start on the NEXT round
        2. Applied NOT DURING own turn: Duration ticks start in the CURRENT round
        
        Returns:
            Tuple[bool, bool, Optional[int]]: (should_expire_now, is_final_turn, display_turns_remaining)
        """
        # Handle permanent effects or effects without duration
        if self.permanent or not self.timing or self._internal_duration is None:
            self.debug("Calc Duration: Permanent or no timing/internal duration.")
            return False, False, None

        # Get timing information
        start_round = self.timing.start_round
        start_turn_name = self.timing.start_turn_name
        applied_during_own = self.timing.applied_during_own_turn

        # --- Calculate Elapsed Turns ---
        # Different turn, different character - no elapsed time change
        if current_turn_name != start_turn_name:
            # If this isn't the affected character's turn, duration doesn't tick
            # We just return the current elapsed value without changing it
            elapsed_turns = self.turns_elapsed
            self.debug(f"Calc Duration: Not {start_turn_name}'s turn (Current: {current_turn_name})")
            self.debug(f"  Keeping elapsed turns at {elapsed_turns}")
        else:
            # This IS the affected character's turn, so we need to calculate elapsed time
            rounds_passed = current_round - start_round
            
            # CASE 1: Applied DURING own turn
            if applied_during_own:
                # Duration ticks start in the NEXT round
                # For round_passed = 0 (same round): elapsed = 0 (no ticks yet)
                # For round_passed = 1 (next round): elapsed = 1 (first tick)
                elapsed_turns = max(0, rounds_passed)
                self.debug(f"Calc Duration: Applied DURING own turn in round {start_round}")
                self.debug(f"  Current round: {current_round}, Rounds passed: {rounds_passed}")
                self.debug(f"  Elapsed turns: {elapsed_turns} (Ticks start NEXT round)")
            
            # CASE 2: Applied NOT DURING own turn
            else:
                # FIXED: For NOT DURING, just increment by rounds passed.
                # For round_passed = 0 (same round): elapsed = 0 (no ticks yet)
                # For round_passed = 1 (next round): elapsed = 1 (first tick)
                elapsed_turns = max(0, rounds_passed)
                self.debug(f"Calc Duration: Applied NOT DURING own turn in round {start_round}")
                self.debug(f"  Current round: {current_round}, Rounds passed: {rounds_passed}")
                self.debug(f"  Elapsed turns: {elapsed_turns} (Same ticking as DURING)")

            # Update internal tracking
            self.turns_elapsed = elapsed_turns

        # --- Calculate Remaining Durations ---
        internal_remaining = max(0, self._internal_duration - elapsed_turns)
        should_expire_now = internal_remaining <= 0
        is_final_turn = internal_remaining == 1

        # IMPROVED: SPECIAL HANDLING FOR DURATION=1 EFFECTS
        if self._display_duration == 1 and applied_during_own:
            # For effects with duration=1 applied during own turn
            if current_round == start_round:
                # Still in application round - don't expire yet
                should_expire_now = False
                is_final_turn = False
                internal_remaining = 2  # Force it to last until next round
                self.debug("Special case: duration=1 applied during own turn, still in application round")
            elif current_round == start_round + 1 and elapsed_turns < 2:
                # Now in next round but elapsed turns aren't enough yet
                # This turn should be the "final turn" warning
                should_expire_now = False
                is_final_turn = True
                internal_remaining = 1
                self.debug("Special case: duration=1 applied during own turn, now in next round (final turn)")
        
        # Calculate display remaining turns (what the user actually sees)
        display_remaining = None
        
        if self._display_duration is not None:
            if applied_during_own:
                # IMPROVED: For "during own turn" effects, display remaining should:
                # 1. Equal display_duration in application round
                # 2. Start decrementing once internal duration reaches display duration
                if elapsed_turns == 0:
                    # In application round, show full display duration
                    display_remaining = self._display_duration
                    self.debug(f"Display remaining (during application round): {display_remaining}")
                else:
                    # Only start decrementing display once internal and display sync up
                    # (this handles "3 internal, 2 display" situation)
                    if self._internal_duration > self._display_duration:
                        # Check if we're still in the "buffer" period where internal > display
                        remaining_buffer = self._internal_duration - self._display_duration
                        if elapsed_turns <= remaining_buffer:
                            # Still in buffer period, display remains unchanged
                            display_remaining = self._display_duration
                            self.debug(f"Display remaining (in buffer period): {display_remaining}")
                        else:
                            # Past buffer period, display decrements normally
                            display_elapsed = elapsed_turns - remaining_buffer
                            display_remaining = max(0, self._display_duration - display_elapsed)
                            self.debug(f"Display remaining (past buffer): {display_remaining}")
                    else:
                        # No buffer, display decrements normally
                        display_remaining = max(0, self._display_duration - elapsed_turns)
            else:
                # FIXED: For NOT DURING effects, display and internal are in sync
                # So display_remaining is simply derived directly from elapsed turns
                display_remaining = max(0, self._display_duration - elapsed_turns)
                self.debug(f"Display remaining (not during): {display_remaining}")

        # Debug final calculation details
        self.debug(f"Duration Calculation Results:")
        self.debug(f"  Internal Duration: {self._internal_duration}, Elapsed: {elapsed_turns}")
        self.debug(f"  Internal Remaining: {internal_remaining}")
        self.debug(f"  Display Remaining: {display_remaining}")
        self.debug(f"  Should Expire Now: {should_expire_now}")
        self.debug(f"  Is Final Turn: {is_final_turn}")
        
        return should_expire_now, is_final_turn, display_remaining
    
    # --- Message Formatting ---

    def format_effect_message(
        self,
        message: str,
        details: Optional[List[str]] = None,
        emoji: Optional[str] = None
    ) -> str:
        """
        Formats an effect message with consistent styling (emoji, backticks).

        Args:
            message (str): The main message text.
            details (Optional[List[str]]): Bullet point details.
            emoji (Optional[str]): Emoji override. Uses effect's default if None.

        Returns:
            str: The fully formatted message string.
        """
        message = message.strip('` ')
        final_emoji = emoji if emoji is not None else self.emoji if self.emoji is not None else "✨"
        formatted = f"{final_emoji} `{message}` {final_emoji}"
        if details:
            detail_lines = []
            for detail in details:
                if detail := str(detail).strip('` '):
                    prefix = "• " if not detail.startswith("•") else ""
                    detail_lines.append(f"{prefix}`{detail}`")
            if detail_lines:
                formatted += "\n" + "\n".join(detail_lines)
        return formatted

    # --- Serialization ---

    def to_dict(self) -> dict:
        """
        Converts the effect's state to a dictionary for database storage.
        Subclasses MUST override and call super().to_dict().
        """
        if not self.timing:
             self.debug("Warning: to_dict called before timing initialized.")

        return {
            "type": self.__class__.__name__,
            "name": self.name,
            "duration": self._display_duration,
            "permanent": self.permanent,
            "category": self.category.value if self.category else None,
            "description": self.description,
            "process_timing": self.process_timing,
            "emoji": self.emoji,
            "state": self.state.value,
            "timing_info": {
                 "start_round": self.timing.start_round,
                 "start_turn_name": self.timing.start_turn_name,
                 "applied_during_own_turn": self.timing.applied_during_own_turn
            } if self.timing else None,
            "_internal_duration": self._internal_duration,
            "turns_elapsed": self.turns_elapsed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Optional['BaseEffect']:
        """
        Reconstructs an effect instance from a dictionary (e.g., loaded from DB).
        Subclasses MUST override and call super().from_dict() or handle manually.
        """
        try:
            effect = cls(
                name=data['name'],
                duration=data.get('duration'),
                permanent=data.get('permanent', False),
                category=EffectCategory(data['category']) if data.get('category') else EffectCategory.CUSTOM,
                description=data.get('description'),
                process_timing=data.get('process_timing', 'both'),
                emoji=data.get('emoji', "✨")
            )

            effect.state = EffectState(data.get('state', EffectState.CREATED.value))
            timing_data = data.get('timing_info')
            if timing_data:
                 effect.timing = EffectProcessTimingInfo(**timing_data)
            
            # Get the timing info to determine how to fix durations
            applied_during_own = timing_data.get('applied_during_own_turn', True) if timing_data else True
            
            # Handle duration restoration based on during/not during
            if applied_during_own:
                # For DURING effects, adjust internal duration if needed
                effect._internal_duration = data.get('_internal_duration', effect._display_duration)
                if effect._display_duration == 1 and effect._internal_duration < 2:
                    effect._internal_duration = 2
                    effect.debug("Fixed: Duration=1 during own turn had invalid internal duration. Set to 2.")
                elif effect._display_duration and effect._internal_duration < effect._display_duration:
                    effect._internal_duration = effect._display_duration + 1
                    effect.debug(f"Fixed: DURING effect had internal duration < display. Set to {effect._internal_duration}")
            else:
                # For NOT DURING effects, ensure internal and display are the same
                display_duration = data.get('duration')
                if display_duration is not None:
                    internal_duration = max(1, display_duration)  # Ensure it's at least 1
                    effect._internal_duration = internal_duration
                    effect._display_duration = internal_duration
                    effect.debug(f"Fixed: NOT DURING effect - set both internal and display to {internal_duration}")

            effect.turns_elapsed = data.get('turns_elapsed', 0)
            effect.debug(f"Restored from dict. State={effect.state.value}, InternalDuration={effect._internal_duration}, Display={effect._display_duration}")
            return effect
        except KeyError as e:
            logger.error(f"Missing key in effect data for {cls.__name__}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reconstructing {cls.__name__} from dict: {e}", exc_info=True)
            return None

# --- Effect Registry ---

class EffectRegistry:
    """
    Central registry for managing all available effect types.
    Allows creating effects by name and reconstructing them from saved data.
    """
    _effects: Dict[str, Type[BaseEffect]] = {}

    @classmethod
    def register_effect(cls, name: str, effect_class: Type[BaseEffect]):
        """Register an effect class with a given name."""
        if not issubclass(effect_class, BaseEffect):
            raise TypeError(f"{effect_class.__name__} must inherit from BaseEffect")
        cls._effects[name.lower()] = effect_class
        logger.info(f"Registered effect type: {name} -> {effect_class.__name__}")

    @classmethod
    def create_effect(cls, name: str, *args, **kwargs) -> Optional[BaseEffect]:
        """Create an instance of a registered effect by name."""
        effect_class = cls._effects.get(name.lower())
        if effect_class:
            try:
                return effect_class(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error creating effect '{name}': {e}", exc_info=True)
                return None
        else:
            logger.warning(f"Effect type '{name}' not found in registry.")
            return None

    @classmethod
    def from_dict(cls, data: dict) -> Optional[BaseEffect]:
        """
        Reconstruct an effect instance from dictionary data using the registry.
        """
        effect_type_name = data.get('type')
        if not effect_type_name:
            logger.error("Effect data missing 'type' field.")
            return None

        effect_class = None
        for registered_name, registered_class in cls._effects.items():
             if registered_class.__name__ == effect_type_name:
                  effect_class = registered_class
                  break

        if effect_class:
            try:
                # Use the class's from_dict method if it exists and is overridden
                if hasattr(effect_class, 'from_dict') and effect_class.from_dict.__func__ is not BaseEffect.from_dict.__func__:
                     instance = effect_class.from_dict(data)
                     if instance: instance.debug("Restored using specific class from_dict")
                     return instance
                else:
                     # Otherwise, use BaseEffect's from_dict logic
                     instance = BaseEffect.from_dict.__func__(effect_class, data)
                     if instance: instance.debug("Restored using BaseEffect from_dict")
                     return instance
            except Exception as e:
                logger.error(f"Error calling from_dict for {effect_type_name}: {e}", exc_info=True)
                return None
        else:
            logger.warning(f"Effect class '{effect_type_name}' not found in registry during from_dict.")
            return None

    @classmethod
    def get_registered_effects(cls) -> Dict[str, Type[BaseEffect]]:
        """Return a copy of the registered effects."""
        return cls._effects.copy()