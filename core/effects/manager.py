"""
Effect system management functions for applying and processing effects.

Handles:
- Effect registration
- Effect application/removal
- Effect processing
- Combat logging integration
- Resource change tracking
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

from typing import List, Tuple, Optional, Dict, Any
from modules.combat.logger import CombatEventType
from .base import BaseEffect, EffectRegistry, EffectCategory, CustomEffect
from .combat import (
    ResistanceEffect, VulnerabilityEffect, WeaknessEffect, TempHPEffect,
    BurnEffect, SourceHeatWaveEffect, TargetHeatWaveEffect
)
from .status import ACEffect, FrostbiteEffect, SkipEffect
from .move import MoveEffect  # Add MoveEffect import
import logging

logger = logging.getLogger(__name__)

def register_effects():
    """Register all available effect types with the registry"""
    # Combat effects
    EffectRegistry.register_effect("resistance", ResistanceEffect)
    EffectRegistry.register_effect("vulnerability", VulnerabilityEffect)
    EffectRegistry.register_effect("weakness", WeaknessEffect)
    EffectRegistry.register_effect("temp_hp", TempHPEffect)
    EffectRegistry.register_effect("burn", BurnEffect)
    EffectRegistry.register_effect("heatwave_source", SourceHeatWaveEffect)
    EffectRegistry.register_effect("heatwave_target", TargetHeatWaveEffect)
    
    # Status effects
    EffectRegistry.register_effect("ac", ACEffect)
    EffectRegistry.register_effect("frostbite", FrostbiteEffect)
    EffectRegistry.register_effect("skip", SkipEffect)
    EffectRegistry.register_effect("move", MoveEffect)  # Register move effect
    
    # Custom effects
    EffectRegistry.register_effect("custom", CustomEffect)

def apply_effect(
    character,
    effect: BaseEffect,
    round_number: int = 1,
    combat_logger = None
) -> str:
    """Apply an effect with proper state tracking"""
    try:
        if combat_logger:
            combat_logger.snapshot_character_state(character)
            
        # Handle stacking effects
        if hasattr(effect, 'add_stacks'):
            existing = next(
                (e for e in character.effects if isinstance(e, type(effect))),
                None
            )
            if existing:
                result = existing.add_stacks(
                    getattr(effect, 'stacks', 1),
                    character
                )
                if combat_logger:
                    combat_logger.add_event(
                        CombatEventType.EFFECT_APPLIED,
                        message=result,
                        character=character.name,
                        details={
                            "effect": effect.name,
                            "stacks": getattr(effect, 'stacks', 1),
                            "total_stacks": getattr(existing, 'stacks', 1)
                        }
                    )
                return result
                
        # Add new effect
        message = character.add_effect(effect, round_number)
        
        if combat_logger:
            combat_logger.add_event(
                CombatEventType.EFFECT_APPLIED,
                message=message,
                character=character.name,
                details={
                    "effect": effect.name,
                    "duration": effect.duration,
                    "permanent": effect.permanent
                }
            )
            combat_logger.snapshot_character_state(character)
            
        return message
        
    except Exception as e:
        logger.error(f"Error applying effect: {e}", exc_info=True)
        return f"Error applying {effect.name}"

def remove_effect(
    character,
    effect_name: str,
    combat_logger = None
) -> str:
    """Remove a named effect with proper cleanup"""
    try:
        if combat_logger:
            combat_logger.snapshot_character_state(character)
            
        # Find and remove effect
        for effect in character.effects[:]:
            if effect.name.lower() == effect_name.lower():
                message = effect.on_expire(character)
                character.effects.remove(effect)
                
                if combat_logger:
                    combat_logger.add_event(
                        CombatEventType.EFFECT_EXPIRED,
                        message=message,
                        character=character.name,
                        details={"effect": effect_name}
                    )
                    combat_logger.snapshot_character_state(character)
                    
                return message
                
        return f"No effect named '{effect_name}' found"
        
    except Exception as e:
        logger.error(f"Error removing effect: {e}", exc_info=True)
        return f"Error removing {effect_name}"

def process_effects(
    character,
    round_number: int,
    turn_name: str,
    combat_logger = None
) -> Tuple[bool, List[str], List[str]]:
    """
    Process all effects for a character's turn.
    
    Args:
        character: Character to process
        round_number: Current round number
        turn_name: Name of character whose turn it is
        combat_logger: Optional combat logger
        
    Returns:
        Tuple of:
        - was_skipped: Whether turn should be skipped
        - start_messages: Messages from start of turn
        - end_messages: Messages from end of turn

    MAIN ORCHESTRATOR for processing ALL effects on a character.
    This is the PRIMARY entry point for effect processing.
    
    Handles:
    - Turn start/end phases
    - Effect expiry
    - Status tracking
    - Combat logging
    - Message collection
    
    Returns:
    - was_skipped: Whether turn should be skipped
    - start_messages: Messages from turn start
    - end_messages: Messages from turn end
    
    ALWAYS USE THIS for processing effects from commands/systems!
    """
    if combat_logger:
        combat_logger.snapshot_character_state(character)
        
    start_messages = []
    end_messages = []
    was_skipped = False
    
    try:
        # Only process if it's this character's turn
        if character.name == turn_name:
            # Start of turn
            for effect in character.effects[:]:
                # Process start of turn effects
                if start_msgs := effect.on_turn_start(character, round_number, turn_name):
                    if isinstance(start_msgs, list):
                        start_messages.extend(start_msgs)
                    else:
                        start_messages.append(start_msgs)
                        
                # Check for skip effects
                if hasattr(effect, 'skips_turn') and effect.skips_turn:
                    was_skipped = True
                    
            # End of turn 
            for effect in character.effects[:]:
                # Process end of turn
                if end_msgs := effect.on_turn_end(character, round_number, turn_name):
                    if isinstance(end_msgs, list):
                        end_messages.extend(end_msgs)
                    else:
                        end_messages.append(end_msgs)
                        
                # Check expiry (if not handling own expiry)
                if not effect._handles_own_expiry:
                    if effect.timing and effect.timing.should_expire(round_number, turn_name):
                        if expire_msg := effect.on_expire(character):
                            end_messages.append(expire_msg)
                        character.effects.remove(effect)
                        
        if combat_logger:
            combat_logger.snapshot_character_state(character)
            
        return was_skipped, start_messages, end_messages
        
    except Exception as e:
        logger.error(f"Error processing effects: {e}", exc_info=True)
        return False, [], []

def get_effect_summary(character) -> List[str]:
    """Get a formatted list of all active effects on a character"""
    if not character.effects:
        return [f"{character.name} has no active effects."]
        
    summary = []
    # Group effects by category
    combat_effects = [e for e in character.effects if e.category == EffectCategory.COMBAT]
    status_effects = [e for e in character.effects if e.category == EffectCategory.STATUS]
    resource_effects = [e for e in character.effects if e.category == EffectCategory.RESOURCE]
    custom_effects = [e for e in character.effects if e.category == EffectCategory.CUSTOM]
    
    if combat_effects:
        summary.append("Combat Effects:")
        for effect in combat_effects:
            summary.append(effect.get_status_text(character))
            
    if status_effects:
        if summary: summary.append("")  # Add spacing
        summary.append("Status Effects:")
        for effect in status_effects:
            summary.append(effect.get_status_text(character))
            
    if resource_effects:
        if summary: summary.append("")
        summary.append("Resource Effects:")
        for effect in resource_effects:
            summary.append(effect.get_status_text(character))
            
    if custom_effects:
        if summary: summary.append("")
        summary.append("Custom Effects:")
        for effect in custom_effects:
            summary.append(effect.get_status_text(character))
            
    return summary

def log_resource_change(
    character,
    resource_type: str,
    old_value: int,
    new_value: int,
    reason: str,
    combat_logger = None
) -> None:
    """
    Helper function to log resource changes (HP, MP, temp HP)
    
    Args:
        character: Character being affected
        resource_type: Type of resource (hp, mp, temp_hp)
        old_value: Previous value
        new_value: New value
        reason: Reason for change
        combat_logger: Optional CombatLogger instance
    """
    if not combat_logger:
        return
        
    change = new_value - old_value
    if change == 0:
        return
        
    emoji = {
        "hp": "❤️" if change > 0 else "💔",
        "mp": "💙" if change > 0 else "💢",
        "temp_hp": "🛡️" if change > 0 else "💥"
    }.get(resource_type.lower(), "✨")
    
    msg = (
        f"{character.name}'s {resource_type.upper()}: "
        f"{old_value} → {new_value} "
        f"({'+'if change > 0 else ''}{change})"
    )
    
    combat_logger.add_event(
        CombatEventType.RESOURCE_CHANGE,
        message=f"{emoji} {msg}",
        character=character.name,
        details={
            "resource": resource_type,
            "old_value": old_value,
            "new_value": new_value,
            "change": change,
            "reason": reason
        }
    )