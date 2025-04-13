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

from core.effects.base import BaseEffect, EffectCategory, EffectState
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
        
        # Enhanced duration tracking
        self._internal_duration = duration  # For internal tracking (may be adjusted)
        self._displayed_duration = duration  # For user-facing display
        
        # Turn-based duration adjustment tracking
        self._applied_during_own_turn = False  # Whether effect was applied during character's own turn
        self._duration_adjusted = False  # Whether duration has been adjusted for turn timing
        self._debug_mode = False  # Enable for detailed debugging output
    
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
    
    def debug_print(self, message: str) -> None:
        """Print debug message if debug mode is enabled"""
        if self._debug_mode:
            print(f"[BurnEffect] {message}")
    
    def initialize_timing(self, round_number: int, character_name: str) -> None:
        """
        Set up timing tracking with turn-based duration adjustment.
        
        Also checks if this effect is being applied during the character's own turn,
        which affects duration tracking.
        """
        # Initialize base timing with standard duration
        super().initialize_timing(round_number, character_name)
        
        # Check if we're in combat and this is the character's own turn
        self._check_if_during_own_turn(character_name)
    
    def _check_if_during_own_turn(self, character_name: str) -> None:
        """
        Check if this effect is being applied during the character's own turn.
        This affects how duration is tracked.
        """
        # Default to not during own turn
        self._applied_during_own_turn = False
        
        # Find character by name in available objects
        import inspect
        frame = inspect.currentframe()
        current_character = None
        
        while frame:
            if 'character' in frame.f_locals:
                current_character = frame.f_locals['character']
                break
            frame = frame.f_back
        
        if not current_character:
            return
            
        # Try to get the initiative tracker from character's game_state
        if hasattr(current_character, 'game_state') and hasattr(current_character.game_state, 'initiative_tracker'):
            tracker = current_character.game_state.initiative_tracker
            if tracker.state != "inactive":  # Check if combat is active
                # Check if it's this character's turn
                if (hasattr(tracker, 'current_turn') and tracker.current_turn and 
                    tracker.current_turn.character_name == character_name):
                    self.debug_print(f"Effect applied during character's own turn")
                    self._applied_during_own_turn = True
                    
                    # If effect has duration, perform the adjustment
                    if self._internal_duration and not self.permanent:
                        # Increment internal duration by 1 but keep displayed duration unchanged
                        self._internal_duration += 1
                        self._duration_adjusted = True
                        self.debug_print(f"Adjusted internal duration to {self._internal_duration}, display remains {self._displayed_duration}")
    
    def on_apply(self, character, round_number: int) -> str:
        """
        Apply burn effect with formatted message.
        
        Sets up timing tracking and transitions to ACTIVE state.
        Ensures damage is not applied in the same turn it was applied.
        Returns application message.
        """
        # Initialize timing and transition to ACTIVE state
        self.initialize_timing(round_number, character.name)
        self.activate()  # Transition from PENDING to ACTIVE
        
        # Set start round and turn
        self._application_round = round_number
        self._application_turn = character.name
        
        # For effect applied DURING character's turn
        # Increment internal duration by 1 (but display the original duration)
        # This ensures it lasts through the proper number of turns
        if character.name == getattr(character, 'turn_name', character.name):
            self._applied_during_own_turn = True
            if self._internal_duration and not self.permanent:
                self._internal_duration += 1
                self._duration_adjusted = True
                self.debug_print(f"Applied during own turn: Adjusted duration to {self._internal_duration}, display remains {self._displayed_duration}")
        
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
    
    def process_duration(self, round_number: int, turn_name: str) -> Tuple[int, bool, bool]:
        """
        Enhanced duration calculation with turn-based adjustment support.
        
        Returns:
        - turns_remaining: How many turns remain (displayable value)
        - will_expire_next: Whether effect will expire next turn
        - should_expire_now: Whether effect should expire now
        """
        if self.permanent or not self.timing:
            return (None, False, False)
            
        # Skip processing if not on the character's turn
        if turn_name != self.timing.start_turn:
            return (None, False, False)
            
        # Calculate elapsed turns
        turns_elapsed = round_number - self.timing.start_round
        
        # Special case for effects applied BEFORE character's turn in same round
        # These should expire at the end of the CURRENT turn
        if (self._application_round == self.timing.start_round and 
            self._application_turn != self.timing.start_turn):
            # Should expire at the end of the current turn
            return (0, False, True)  # Should expire now
        
        # For effects applied DURING character's turn,
        # the first round doesn't count toward duration
        first_turn_processing = (round_number == self._application_round and 
                                turn_name == self._application_turn)
        
        # Calculate true remaining turns based on when effect was applied
        if first_turn_processing:
            # During first processing, full duration remains
            internal_remaining = self._internal_duration
        else:
            # For subsequent turns, account for elapsed turns correctly
            internal_remaining = max(0, self._internal_duration - turns_elapsed)
        
        # Calculate displayed remaining turns
        # If duration was adjusted due to application during own turn,
        # displayed remaining is one less than internal
        if self._duration_adjusted and internal_remaining > 0:
            display_remaining = internal_remaining - 1
        else:
            display_remaining = internal_remaining
        
        # Calculate expiry states
        will_expire_next = (internal_remaining == 1)
        
        # Effect should expire now if duration is complete and not first turn
        should_expire_now = (internal_remaining == 0 and not first_turn_processing)
        
        self.debug_print(f"Duration calculation: internal={internal_remaining}, display={display_remaining}, " +
                        f"will_expire={will_expire_next}, should_expire={should_expire_now}")
        
        return (display_remaining, will_expire_next, should_expire_now)
    
    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process burn damage at start of affected character's turn.
        
        Only applies damage if effect is in ACTIVE state and not in the
        same turn it was applied. Uses state-based checks to prevent duplicate damage.
        
        CRITICAL: Never expires effects in turn start phase - only marks for expiry.
        """
        # Only process for the affected character's turn
        if character.name != turn_name:
            return []
        
        # Skip if not in ACTIVE state - only ACTIVE effects deal damage
        if self.state != EffectState.ACTIVE:
            return []
        
        # Skip damage if this was just applied during the character's own turn
        # and it's still the same round
        if (round_number == self._application_round and 
            turn_name == self._application_turn):
            self.debug_print(f"Skipping damage on application turn")
            return []
        
        # Check if this effect should expire on this turn
        # (for effects applied before the character's turn)
        _, _, should_expire_now = self.process_duration(round_number, turn_name)
        if should_expire_now:
            # Don't apply damage if we're going to expire this turn
            # Instead, queue the effect for expiry at end of turn ONLY
            self.mark_expiring()  # Transition to EXPIRING state
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
        
        # Add duration info based on state and remaining turns
        if not self.permanent and self.duration:
            # Calculate remaining turns
            turns_remaining, will_expire_next, _ = self.process_duration(round_number, turn_name)
            
            # Set state to EXPIRING if this is the final turn
            if will_expire_next and self.state == EffectState.ACTIVE:
                self.mark_expiring()  # Transition to EXPIRING state
                details.append("Final turn - will expire after this turn")
            # Only show remaining duration for non-expiring effects
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
        
        Uses state-based transitions to handle expiry and duration tracking.
        """
        # Only process on character's own turn, skip for permanent effects
        if character.name != turn_name or self.permanent:
            return []
        
        # Use standardized duration tracking
        turns_remaining, will_expire_next, should_expire_now = self.process_duration(round_number, turn_name)
        
        # State transition: ACTIVE -> EXPIRING -> EXPIRED
        if should_expire_now:
            # First transition to EXPIRING if not already
            if self.state == EffectState.ACTIVE:
                self.mark_expiring()  # Sets _marked_for_expiry = True
            
            # Then transition to EXPIRED
            self.expire()  # Sets state to EXPIRED
            
            # Create expiry message
            expiry_msg = self.format_effect_message(
                f"Burn effect has worn off from {character.name}",
                emoji="🔥"
            )
            
            # Add to feedback system for reliable display on next turn
            self._add_expiry_feedback(character, expiry_msg, round_number)
            
            # Transition to FEEDBACK state to mark as processed
            self.mark_feedback_sent()  # Sets _expiry_message_sent = True
            
            # Return message for immediate display in end-of-turn embed
            return [expiry_msg]
        
        # Handle final turn warning (will expire next turn)
        if will_expire_next and self.state == EffectState.ACTIVE:
            # Transition to EXPIRING state
            self.mark_expiring()  # Sets _will_expire_next = True
            
            return [self.format_effect_message(
                f"Burn effect continues",
                ["Final turn - will expire after this turn"],
                emoji="🔥"
            )]
        
        # Regular duration update (only for ACTIVE state)
        if self.state == EffectState.ACTIVE and turns_remaining is not None and turns_remaining > 0:
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
        
        Uses state-based approach to ensure proper cleanup and prevent duplicate messages.
        This can be called either through natural expiry or forced removal.
        """
        # Get current round for feedback (fallback to 1 if not available)
        round_number = getattr(character, 'round_number', 1)
        
        # Only generate a message if not in FEEDBACK state
        if self.state != EffectState.FEEDBACK:
            # Create expiry message
            expiry_msg = self.format_effect_message(
                f"Burn effect has worn off from {character.name}",
                emoji="🔥"
            )
            
            # Ensure proper state transition sequence
            if self.state == EffectState.ACTIVE:
                # For direct removal without going through normal expiry
                self.mark_expiring()  # ACTIVE -> EXPIRING
                self.expire()         # EXPIRING -> EXPIRED
            elif self.state == EffectState.EXPIRING:
                # For effects that were already marked as expiring
                self.expire()         # EXPIRING -> EXPIRED
            
            # Add to feedback system for reliable display
            self._add_expiry_feedback(character, expiry_msg, round_number)
            
            # Transition to FEEDBACK state
            self.mark_feedback_sent()
            
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
        """
        Convert to dictionary for storage.
        
        Includes state tracking for proper database serialization.
        """
        data = super().to_dict()
        
        # Ensure template data exists for backward compatibility
        if not data.get('_template_data'):
            data["_template_data"] = {
                "damage": self.damage,
                "damage_type": "fire",
                "last_damage": getattr(self, 'last_damage', 0)
            }
        
        # Store enhanced duration tracking fields
        data.update({
            "_internal_duration": self._internal_duration,
            "_displayed_duration": self._displayed_duration,
            "_applied_during_own_turn": self._applied_during_own_turn,
            "_duration_adjusted": self._duration_adjusted,
            "_state": self.state.value  # Store the enum value as a string
        })
        
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'BurnEffect':
        """
        Create from dictionary data.
        
        Restores state tracking for proper effect lifecycle management.
        """
        # Get damage and duration
        if '_template_data' in data and 'damage' in data['_template_data']:
            damage = data['_template_data']['damage']
        else:
            damage = data.get('damage', "1d4")
        
        # Create new effect (starts in PENDING state)
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
            effect.timing = EffectProcessTiming(**timing_data)
        
        # Restore legacy state flags for backward compatibility
        effect._marked_for_expiry = data.get('_marked_for_expiry', False)
        effect._will_expire_next = data.get('_will_expire_next', False)
        effect._application_round = data.get('_application_round')
        effect._application_turn = data.get('_application_turn')
        effect._expiry_message_sent = data.get('_expiry_message_sent', False)
        
        # Restore the state enum value if available
        # For backward compatibility, determine state from flags if not stored
        if '_state' in data:
            # Import here to avoid circular imports
            from core.effects.base import EffectState
            state_value = data['_state']
            
            # Get the enum value by string
            for state in EffectState:
                if state.value == state_value:
                    effect._state = state
                    break
        else:
            # For backward compatibility, infer state from legacy flags
            from core.effects.base import EffectState
            if effect._expiry_message_sent:
                effect._state = EffectState.FEEDBACK
            elif effect._marked_for_expiry:
                effect._state = EffectState.EXPIRED
            elif effect._will_expire_next:
                effect._state = EffectState.EXPIRING
            else:
                # Default to ACTIVE if effect has timing info (was applied)
                effect._state = EffectState.ACTIVE if effect.timing else EffectState.PENDING
        
        return effect
