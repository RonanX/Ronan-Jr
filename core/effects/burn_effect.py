"""
Burn Effect (DoT) implementation with clean user output and accurate duration tracking.
"""

from typing import Any, Dict, List, Optional, Tuple
import logging
import time
import random

from .base import BaseEffect, EffectState, EffectCategory, EffectProcessTimingInfo

logger = logging.getLogger(__name__)

# Counter for unique effect IDs
_burn_effect_counter = 0

class BurnEffect(BaseEffect):
    """
    Fire damage over time effect with accurate duration tracking.
    
    Features:
    - Correctly handles "during" vs "not during" application
    - Proper expiry message handling
    - Clean user-facing messages
    """
    
    def __init__(
        self,
        name: str = "Burn",
        duration: Optional[int] = 3,
        damage_formula: str = "1d4",
        permanent: bool = False,
        unique_id: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize burn effect with damage formula and duration.
        """
        global _burn_effect_counter
        
        # Create a unique effect ID if not provided
        if unique_id is None:
            # Combine counter and timestamp for uniqueness
            _burn_effect_counter += 1
            unique_id = f"{_burn_effect_counter}_{int(time.time())}_{random.randint(1000, 9999)}"
        
        # Store basic name for display purposes
        self.base_name = name
        self.damage_formula = damage_formula
        
        # Create clean display name (without unique ID)
        self.display_name = f"{name} ({damage_formula})"
        
        # Create a unique internal name that includes the unique ID
        internal_name = f"{name} ({damage_formula}) #{unique_id}"
        
        # Initialize base effect
        super().__init__(
            name=internal_name,
            duration=None if permanent else duration,
            permanent=permanent,
            category=EffectCategory.COMBAT,
            description=f"Deals {damage_formula} fire damage each turn",
            process_timing="both",  # Process at start AND end of turn
            emoji="🔥",
            debug_mode=True  # Enable debug logging
        )
        
        # Store burn-specific data
        self.unique_id = unique_id
        self.is_dice = self._is_dice_formula(damage_formula)
        
        # Track last damage roll
        self.last_damage_roll = None
        
        # Flag to track if we've added expiry feedback to prevent duplicates
        self._expiry_feedback_added = False
    
    def _is_dice_formula(self, formula: str) -> bool:
        """Check if a string is a dice formula (e.g., "d6", "2d8", "1d20+2")"""
        if not isinstance(formula, str):
            return False
        
        # Normalize "d4" to "1d4"
        formula = formula.lower()
        if formula.startswith('d') and len(formula) > 1 and formula[1:].isdigit():
            formula = '1' + formula
            
        # Simple regex-free check for dice pattern
        parts = formula.replace('+', ' ').replace('-', ' ').split()
        for part in parts:
            if 'd' in part:
                dice_parts = part.split('d')
                if len(dice_parts) == 2:
                    if (dice_parts[0].isdigit() or not dice_parts[0]) and dice_parts[1].isdigit():
                        return True
        return False
    
    def get_display_name(self, context="default"):
        """
        Get appropriate display name based on context.
        
        Args:
            context (str): The context where the name will be displayed
                - "damage": For damage messages (simplest form)
                - "expiry": For expiry messages (clean format)
                - "status": For status updates (with formula)
                - "default": Default display name
        """
        if context == "damage":
            return "Burn"  # Simplest form for damage messages
        elif context == "expiry":
            return f"{self.base_name} ({self.damage_formula})"  # Clean format for expiry
        elif context == "status":
            return self.display_name  # Full display name
        else:
            return self.display_name  # Full display name for most contexts

    def on_apply(self, character, round_number: int) -> str:
        """Called when effect is first applied to a character."""
        # First let the base class handle state transition and timing initialization
        apply_msg = super().on_apply(character, round_number)
        
        # Log detailed timing information for debugging only
        applied_during = "DURING" if self.timing and self.timing.applied_during_own_turn else "NOT DURING"
        internal_dur = self._internal_duration
        display_dur = self._display_duration
        
        self.debug(f"Applied on round {round_number}, {character.name}'s turn: {applied_during}")
        self.debug(f"Duration: Display={display_dur}, Internal={internal_dur}, Permanent={self.permanent}")

        # Create a clean message for user display
        details = []
        
        # Duration info
        if self.permanent:
            details.append("Permanent effect")
        else:
            details.append(f"Duration: {self._display_duration} turns")
        
        # Add damage info
        details.append(f"Damage: {self.damage_formula} fire each turn")
        
        # Add application timing but in a simplified way for users
        if self.timing and self.timing.applied_during_own_turn:
            details.append(f"Applied: DURING turn")
        else:
            details.append(f"Applied: NOT DURING turn")

        # Add internal duration only in debug logs, not user message
        if self.debug_mode and not self.permanent:
            self.debug(f"Internal duration: {self._internal_duration}")

        # Use the base class formatter to create a consistent message
        return self.format_effect_message(
            f"{character.name} is burning!",
            details=details,
            emoji=self.emoji
        )

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Apply burn damage at the start of the character's turn."""
        # Only process if it's the character's turn and effect is active
        if character.name != turn_name or self.state != EffectState.ACTIVE:
            return []

        self.debug(f"Turn Start processing on round {round_number}. State: {self.state.value}")
        messages = []

        # Apply damage
        try:
            # Use dice calculator if available
            from utils.advanced_dice.calculator import DiceCalculator
            calc = DiceCalculator()
            result = calc.calculate(self.damage_formula)
            damage = result.final_result
            self.last_damage_roll = damage
            
            # Apply damage to character
            old_hp = character.resources.current_hp
            character.resources.current_hp = max(0, old_hp - damage)
            
            self.debug(f"Dealt {damage} damage to {character.name}. HP: {old_hp} → {character.resources.current_hp}")
            
            # Create damage message
            message = self.format_effect_message(
                f"{character.name} takes {damage} fire damage from {self.get_display_name('damage')}! HP: {character.resources.current_hp}/{character.resources.max_hp}",
                emoji=self.emoji
            )
            
            messages.append(message)
            
        except Exception as e:
            self.debug(f"Error applying damage: {e}")
            # Fallback to minimal damage
            damage = 1
            character.resources.current_hp = max(0, character.resources.current_hp - damage)
            messages.append(self.format_effect_message(
                f"{character.name} takes {damage} fire damage from {self.get_display_name('damage')}!",
                emoji=self.emoji
            ))
            
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Called at the end of the character's turn to update duration and status."""
        # Skip processing if not this character's turn
        if character.name != turn_name:
            return []
        
        self.debug(f"Turn End processing on round {round_number}. State: {self.state.value}")
        messages = []

        # Skip permanent effects
        if self.permanent:
            messages.append(self.format_effect_message(
                f"{self.get_display_name('status')} continues",
                details=["Permanent effect"],
                emoji=self.emoji
            ))
            return messages
        
        # Calculate duration status manually instead of using base class
        should_expire = False
        is_final = False
        display_remaining = None
        
        if self.timing:
            if self.timing.applied_during_own_turn:
                # For DURING effects, calculate based on rounds passed
                rounds_passed = round_number - self.timing.start_round
                self.turns_elapsed = rounds_passed
                
                # Check if should expire
                if self._internal_duration is not None and rounds_passed >= self._internal_duration:
                    should_expire = True
                elif self._internal_duration is not None and rounds_passed == self._internal_duration - 1:
                    is_final = True
                    
                # Calculate display remaining
                if self._display_duration is not None:
                    display_remaining = max(0, self._display_duration - rounds_passed)
                    # Adjust for display
                    if self._display_duration > 1 and display_remaining > 1 and self.state == EffectState.ACTIVE:
                        display_remaining = max(1, display_remaining - 1)
            else:
                # For NOT DURING effects
                self.turns_elapsed += 1
                
                # Check if should expire
                if self._internal_duration is not None and self.turns_elapsed >= self._internal_duration:
                    should_expire = True
                elif self._internal_duration is not None and self.turns_elapsed == self._internal_duration - 1:
                    is_final = True
                    
                # Calculate display remaining
                if self._display_duration is not None:
                    display_remaining = max(0, self._display_duration - self.turns_elapsed)
                    # Adjust for display
                    if self._display_duration > 1 and display_remaining > 1 and self.state == EffectState.ACTIVE:
                        display_remaining = max(1, display_remaining - 1)
        
        # Handle expiry
        if should_expire:
            # Change state to EXPIRED
            self.state = EffectState.EXPIRED
            
            # Add clean expiry message to feedback
            expiry_msg = self.format_effect_message(
                f"{self.get_display_name('expiry')} has worn off",
                emoji=self.emoji
            )
            
            if hasattr(character, 'add_effect_feedback'):
                character.add_effect_feedback(
                    effect_name=self.base_name,
                    expiry_message=expiry_msg,
                    round_expired=round_number,
                    turn_expired=character.name
                )
                self._expiry_feedback_added = True
        else:
            # Add status message for continuing effect
            if is_final:
                messages.append(self.format_effect_message(
                    f"{self.get_display_name('status')} continues",
                    details=["Final turn"],
                    emoji=self.emoji
                ))
            elif display_remaining is not None and display_remaining > 0:
                # Format plural correctly
                s = "s" if display_remaining != 1 else ""
                messages.append(self.format_effect_message(
                    f"{self.get_display_name('status')} continues",
                    details=[f"{display_remaining} turn{s} remaining"],
                    emoji=self.emoji
                ))
        
        return messages

    def on_expire(self, character) -> str:
        """Called when the effect is removed."""
        # Just set state to REMOVED and return empty string
        self.state = EffectState.REMOVED
        
        # Only add clean expiry message if not already added and not from duration expiry
        if not self._expiry_feedback_added:
            expiry_msg = self.format_effect_message(
                f"{self.get_display_name('expiry')} has worn off",
                emoji=self.emoji
            )
            
            if hasattr(character, 'add_effect_feedback'):
                character.add_effect_feedback(
                    effect_name=self.base_name,
                    expiry_message=expiry_msg,
                    round_expired=getattr(character, 'round_number', 0),
                    turn_expired=character.name
                )
        
        # Return empty string to prevent any messages from being displayed
        return ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        data = super().to_dict()
        
        # Add BurnEffect-specific fields
        data.update({
            "damage_formula": self.damage_formula,
            "last_damage_roll": self.last_damage_roll,
            "unique_id": self.unique_id,
            "base_name": self.base_name,
            "display_name": self.display_name,
            "is_dice": self.is_dice,
            "_expiry_feedback_added": self._expiry_feedback_added,
        })
        
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional['BurnEffect']:
        """Reconstruct from dictionary data."""
        try:
            # Extract damage formula and unique ID
            damage_formula = data.get('damage_formula', '1d4')
            unique_id = data.get('unique_id')
            
            # Extract base name - try stored value first
            base_name = data.get('base_name', 'Burn')
            
            # If base_name not found, try to extract from full name
            if not base_name and 'name' in data:
                full_name = data.get('name', 'Burn')
                if ' (' in full_name and ')' in full_name:
                    base_name = full_name.split(' (')[0]
                else:
                    base_name = 'Burn'
            
            # Create new effect with preserved unique_id
            effect = cls(
                name=base_name,
                duration=data.get('duration'),
                damage_formula=damage_formula,
                permanent=data.get('permanent', False),
                unique_id=unique_id
            )
            
            # Restore display name if available
            if 'display_name' in data:
                effect.display_name = data.get('display_name')
            
            # Restore state
            if 'state' in data:
                effect.state = EffectState(data['state'])
            
            # Restore timing info
            timing_data = data.get('timing_info')
            if timing_data:
                effect.timing = EffectProcessTimingInfo(**timing_data)
            
            # Restore tracking fields
            if '_internal_duration' in data:
                effect._internal_duration = data.get('_internal_duration')
            
            if '_display_duration' in data:
                effect._display_duration = data.get('_display_duration')
                
            # Explicitly restore timing application info for proper duration handling
            if timing_data and 'applied_during_own_turn' in timing_data:
                applied_during = timing_data.get('applied_during_own_turn')
                effect.debug(f"Restored application timing: during_own={applied_during}")
            
            effect.turns_elapsed = data.get('turns_elapsed', 0)
            effect.last_damage_roll = data.get('last_damage_roll')
            
            # Restore burn-specific properties
            effect.is_dice = data.get('is_dice', effect._is_dice_formula(damage_formula))
            
            # Restore feedback tracking
            effect._expiry_feedback_added = data.get('_expiry_feedback_added', False)
            
            # Debug restoration
            effect.debug(f"Restored from dict. State={effect.state.value}, Internal={effect._internal_duration}, Display={effect._display_duration}")
            if effect.timing:
                during = "DURING" if effect.timing.applied_during_own_turn else "NOT DURING"
                effect.debug(f"Timing restored: {during} own turn, Turns elapsed: {effect.turns_elapsed}")
            
            return effect
        except Exception as e:
            logger.error(f"Error reconstructing BurnEffect from dict: {e}", exc_info=True)
            return None

    def dump_state(self, indent="") -> str:
        """Generate a detailed state dump for debugging."""
        lines = [
            f"{indent}BurnEffect State Dump:",
            f"{indent}  Name: {self.name}",
            f"{indent}  Display Name: {self.display_name}",
            f"{indent}  State: {self.state.value}",
            f"{indent}  Damage Formula: {self.damage_formula}",
            f"{indent}  Is Dice: {self.is_dice}",
            f"{indent}  Permanent: {self.permanent}",
        ]
        
        # Add duration info
        if self.permanent:
            lines.append(f"{indent}  Duration: Permanent")
        else:
            lines.append(f"{indent}  Display Duration: {self._display_duration}")
            lines.append(f"{indent}  Internal Duration: {self._internal_duration}")
            lines.append(f"{indent}  Turns Elapsed: {self.turns_elapsed}")
        
        # Add timing info
        if self.timing:
            lines.append(f"{indent}  Applied During Own Turn: {self.timing.applied_during_own_turn}")
            lines.append(f"{indent}  Start Round: {self.timing.start_round}")
            lines.append(f"{indent}  Start Turn: {self.timing.start_turn_name}")
        
        return "\n".join(lines)