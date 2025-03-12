"""
Effect system management functions for applying and processing effects.

Handles:
- Effect registration
- Effect application/removal
- Effect processing
- Combat logging integration
- Resource change tracking

IMPLEMENTATION MANDATES:
- All effect processing MUST use inspect.iscoroutinefunction()
- Always properly await async methods
- Maintain consistent return types (strings, never coroutines)
- Ensure compatibility with both sync and async methods
- Document async requirements clearly for future developers
"""

from typing import List, Tuple, Optional, Dict, Any
import inspect
import logging
import asyncio

from .base import BaseEffect, EffectRegistry, EffectCategory, CustomEffect
from .combat import (
    ResistanceEffect, VulnerabilityEffect, WeaknessEffect, TempHPEffect,
    BurnEffect, SourceHeatWaveEffect, TargetHeatWaveEffect, ShockEffect
)
from .resource import(
    DrainEffect, RegenEffect
)
from .status import ACEffect, FrostbiteEffect, SkipEffect
from .move import MoveEffect  # Add MoveEffect import

logger = logging.getLogger(__name__)

def register_effects():
    """Register all available effect types with the registry"""
    # Combat effects
    EffectRegistry.register_effect("resistance", ResistanceEffect)
    EffectRegistry.register_effect("vulnerability", VulnerabilityEffect)
    EffectRegistry.register_effect("weakness", WeaknessEffect)
    EffectRegistry.register_effect("temp_hp", TempHPEffect)
    EffectRegistry.register_effect("burn", BurnEffect)
    EffectRegistry.register_effect("shock", ShockEffect)
    EffectRegistry.register_effect("heatwave_source", SourceHeatWaveEffect)
    EffectRegistry.register_effect("heatwave_target", TargetHeatWaveEffect)
    
    # Resource effects
    EffectRegistry.register_effect("drain", DrainEffect)
    EffectRegistry.register_effect("regen", RegenEffect)
    
    # Status effects
    EffectRegistry.register_effect("ac", ACEffect)
    EffectRegistry.register_effect("frostbite", FrostbiteEffect)
    EffectRegistry.register_effect("skip", SkipEffect)
    EffectRegistry.register_effect("move", MoveEffect)
    
    # Custom effects
    EffectRegistry.register_effect("custom", CustomEffect)

async def apply_effect(
    character,
    effect: BaseEffect,
    round_number: int = 1,
    combat_logger = None
) -> str:
    """
    Apply an effect to a character and return the feedback message.
    
    This function properly handles both sync and async effect methods.
    
    Args:
        character: Character to affect
        effect: Effect to apply
        round_number: Current combat round
        combat_logger: Optional combat logger
        
    Returns:
        Feedback message as string
    """
    try:
        # Take a snapshot of character state before changes
        if combat_logger:
            combat_logger.snapshot_character_state(character)
            
        # Check for existing stacking effects
        if hasattr(effect, 'add_stacks'):
            for existing in character.effects:
                # Find matching effect types for stacking
                if isinstance(existing, type(effect)) and getattr(existing, 'name', '') == effect.name:
                    # Handle async or sync add_stacks method
                    if inspect.iscoroutinefunction(existing.add_stacks):
                        result = await existing.add_stacks(getattr(effect, 'stacks', 1), character)
                    else:
                        result = existing.add_stacks(getattr(effect, 'stacks', 1), character)
                    
                    # Log the stacking if we have a logger
                    if combat_logger:
                        combat_logger.add_event(
                            "EFFECT_STACKED",
                            message=result,
                            character=character.name,
                            details={
                                "effect": effect.name,
                                "stacks_added": getattr(effect, 'stacks', 1)
                            }
                        )
                    return result
        
        # No existing stacking effect found, apply new effect
        
        # Call on_apply method - shouldn't be async in base implementation
        # but we check just to be safe
        if inspect.iscoroutinefunction(effect.on_apply):
            message = await effect.on_apply(character, round_number)
        else:
            message = effect.on_apply(character, round_number)
        
        # Add to character's effects list
        character.effects.append(effect)
        
        # Special case for MoveEffect - process any stored async operations
        if isinstance(effect, MoveEffect):
            # Get attack messages (if any)
            attack_messages = await effect.process_async_results()
            if attack_messages:
                for msg in attack_messages:
                    if not message.endswith('\n' + msg):
                        message += f"\n{msg}"
        
        # Log the application if we have a logger
        if combat_logger:
            combat_logger.add_event(
                "EFFECT_APPLIED",
                message=message,
                character=character.name,
                details={
                    "effect": effect.name,
                    "duration": getattr(effect, 'duration', None)
                }
            )
            combat_logger.snapshot_character_state(character)
            
        return message
        
    except Exception as e:
        logger.error(f"Error applying effect: {str(e)}", exc_info=True)
        return f"Error applying {effect.name}: {str(e)}"

async def remove_effect(
    character,
    effect_name: str,
    combat_logger = None
) -> str:
    """
    Remove a named effect from a character.
    
    Args:
        character: Character to affect
        effect_name: Name of effect to remove
        combat_logger: Optional combat logger
        
    Returns:
        Feedback message as string
    """
    try:
        # Take a snapshot of character state before changes
        if combat_logger:
            combat_logger.snapshot_character_state(character)
            
        # Find and remove the effect
        for effect in character.effects[:]:  # Copy list since we're modifying it
            if effect.name.lower() == effect_name.lower():
                # Call on_expire method - handle async or sync
                if inspect.iscoroutinefunction(effect.on_expire):
                    message = await effect.on_expire(character)
                else:
                    message = effect.on_expire(character)
                
                # Remove from character's effects list
                character.effects.remove(effect)
                
                # Log the removal if we have a logger
                if combat_logger:
                    combat_logger.add_event(
                        "EFFECT_REMOVED",
                        message=message,
                        character=character.name,
                        details={"effect": effect_name}
                    )
                    combat_logger.snapshot_character_state(character)
                    
                return message
                
        return f"No effect named '{effect_name}' found on {character.name}"
        
    except Exception as e:
        logger.error(f"Error removing effect: {str(e)}", exc_info=True)
        return f"Error removing {effect_name}: {str(e)}"

async def process_effects(
    character,
    round_number: int,
    turn_name: str,
    combat_logger = None
) -> Tuple[bool, List[str], List[str]]:
    """
    Process all effects for a character's turn.
    
    This function handles both sync and async effect methods properly.
    
    Args:
        character: Character to process
        round_number: Current round number
        turn_name: Name of character whose turn it is
        combat_logger: Optional combat logger
        
    Returns:
        Tuple of:
        - was_skipped: Whether turn should be skipped
        - start_messages: Messages from start of turn effects
        - end_messages: Messages from end of turn effects
    """
    # Take a snapshot of character state before processing
    if combat_logger:
        combat_logger.snapshot_character_state(character)
        
    start_messages = []
    end_messages = []
    was_skipped = False
    
    try:
        # Only process if it's this character's turn
        if character.name == turn_name:
            # Add character round number for easier access in effects
            character.round_number = round_number
            
            # Process start of turn effects
            for effect in character.effects[:]:  # Copy to avoid modification issues
                # Call on_turn_start if it exists
                if hasattr(effect, 'on_turn_start'):
                    # Check if method is async
                    if inspect.iscoroutinefunction(effect.on_turn_start):
                        start_result = await effect.on_turn_start(character, round_number, turn_name)
                    else:
                        start_result = effect.on_turn_start(character, round_number, turn_name)
                    
                    # Add messages to our collection
                    if start_result:
                        if isinstance(start_result, list):
                            start_messages.extend(start_result)
                        else:
                            start_messages.append(start_result)
                    
                    # Special case for MoveEffect - process any stored async operations
                    if isinstance(effect, MoveEffect):
                        attack_messages = await effect.process_async_results()
                        start_messages.extend(attack_messages)
                
                # Check if this effect causes the turn to be skipped
                if hasattr(effect, 'skips_turn') and effect.skips_turn:
                    was_skipped = True
            
            # Process end of turn effects
            for effect in character.effects[:]:  # Copy to avoid modification issues
                # Call on_turn_end if it exists
                if hasattr(effect, 'on_turn_end'):
                    # Check if method is async
                    if inspect.iscoroutinefunction(effect.on_turn_end):
                        end_result = await effect.on_turn_end(character, round_number, turn_name)
                    else:
                        end_result = effect.on_turn_end(character, round_number, turn_name)
                    
                    # Add messages to our collection
                    if end_result:
                        if isinstance(end_result, list):
                            end_messages.extend(end_result)
                        else:
                            end_messages.append(end_result)
                    
                    # Special case for MoveEffect - process any stored async operations
                    if isinstance(effect, MoveEffect):
                        attack_messages = await effect.process_async_results()
                        if attack_messages:
                            end_messages.extend(attack_messages)
                
                # Check if effect should expire
                should_expire = False
                
                # If effect doesn't handle its own expiry
                if not getattr(effect, '_handles_own_expiry', False):
                    # Check timing-based expiry
                    if hasattr(effect, 'timing') and effect.timing:
                        should_expire = effect.timing.should_expire(round_number, turn_name)
                else:
                    # For effects that handle their own expiry (like moves)
                    if hasattr(effect, 'is_expired'):
                        if callable(getattr(effect, 'is_expired')):
                            should_expire = effect.is_expired()
                        else:
                            should_expire = effect.is_expired
                
                # Handle expiry if needed
                if should_expire:
                    # Call on_expire - handle async or sync
                    if inspect.iscoroutinefunction(effect.on_expire):
                        expire_msg = await effect.on_expire(character)
                    else:
                        expire_msg = effect.on_expire(character)
                    
                    if expire_msg:
                        end_messages.append(expire_msg)
                    
                    # Remove effect from character
                    if effect in character.effects:  # Check still exists
                        character.effects.remove(effect)
                        
                    # Log effect removal if we have a logger
                    if combat_logger and expire_msg:
                        combat_logger.add_event(
                            "EFFECT_EXPIRED",
                            message=expire_msg,
                            character=character.name,
                            details={"effect": effect.name}
                        )
            
            # Clean up the character round number
            if hasattr(character, 'round_number'):
                delattr(character, 'round_number')
        
        # Take another snapshot after processing
        if combat_logger:
            combat_logger.snapshot_character_state(character)
            
        return was_skipped, start_messages, end_messages
        
    except Exception as e:
        logger.error(f"Error processing effects: {str(e)}", exc_info=True)
        
        # Clean up the character round number in case of error
        if hasattr(character, 'round_number'):
            delattr(character, 'round_number')
            
        # Return empty results on error
        return False, [], []

def get_effect_summary(character) -> List[str]:
    """
    Get a formatted list of all active effects on a character.
    
    This is a synchronous function that doesn't need async since
    it's only displaying information, not processing effects.
    
    Args:
        character: Character to summarize effects for
        
    Returns:
        List of formatted effect summary strings
    """
    if not character.effects:
        return [f"{character.name} has no active effects."]
        
    summary = []
    
    # Group effects by category for better organization
    combat_effects = [e for e in character.effects if getattr(e, 'category', None) == EffectCategory.COMBAT]
    status_effects = [e for e in character.effects if getattr(e, 'category', None) == EffectCategory.STATUS]
    resource_effects = [e for e in character.effects if getattr(e, 'category', None) == EffectCategory.RESOURCE]
    custom_effects = [e for e in character.effects if getattr(e, 'category', None) == EffectCategory.CUSTOM]
    
    # Add combat effects section
    if combat_effects:
        summary.append("Combat Effects:")
        for effect in combat_effects:
            summary.append(effect.get_status_text(character))
            
    # Add status effects section
    if status_effects:
        if summary: summary.append("")  # Add spacing
        summary.append("Status Effects:")
        for effect in status_effects:
            summary.append(effect.get_status_text(character))
            
    # Add resource effects section
    if resource_effects:
        if summary: summary.append("")
        summary.append("Resource Effects:")
        for effect in resource_effects:
            summary.append(effect.get_status_text(character))
            
    # Add custom effects section
    if custom_effects:
        if summary: summary.append("")
        summary.append("Custom Effects:")
        for effect in custom_effects:
            summary.append(effect.get_status_text(character))
            
    return summary

async def log_resource_change(
    character,
    resource_type: str,
    old_value: int,
    new_value: int,
    reason: str,
    combat_logger = None
) -> None:
    """
    Log resource changes to the combat log.
    
    Args:
        character: Character affected
        resource_type: Type of resource (hp, mp, temp_hp)
        old_value: Previous value
        new_value: New value
        reason: Reason for the change
        combat_logger: Optional combat logger
    """
    if not combat_logger:
        return
        
    # Calculate the change
    change = new_value - old_value
    if change == 0:
        return  # No change to log
        
    # Select appropriate emoji based on resource and direction
    emoji = {
        "hp": "❤️" if change > 0 else "💔",
        "mp": "💙" if change > 0 else "💢",
        "temp_hp": "🛡️" if change > 0 else "💥"
    }.get(resource_type.lower(), "✨")
    
    # Format the message
    msg = (
        f"{character.name}'s {resource_type.upper()}: "
        f"{old_value} → {new_value} "
        f"({'+'if change > 0 else ''}{change})"
    )
    
    # Log the event
    combat_logger.add_event(
        "RESOURCE_CHANGE",
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