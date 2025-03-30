"""
Effect system management functions for applying and processing effects.

Handles:
- Effect registration
- Effect application/removal
- Effect processing
- Combat logging integration
- Resource change tracking
- Effect feedback system

IMPLEMENTATION MANDATES:
- All effect processing MUST use inspect.iscoroutinefunction()
- Always properly await async methods
- Maintain consistent return types (strings, never coroutines)
- Ensure compatibility with both sync and async methods
- Document async requirements clearly for future developers
"""

from typing import List, Tuple, Optional, Dict, Any
from enum import Enum
import inspect
import logging
import asyncio

from .base import BaseEffect, EffectRegistry, EffectCategory, CustomEffect
from .burn_effect import BurnEffect

# We'll import other effects as needed
# This is just to demonstrate registration

logger = logging.getLogger(__name__)

class EffectLifecycle(str, Enum):
    """
    Tracks effect lifecycle stages.
    This is maintained for backward compatibility with systems that might use it.
    New code should directly use elapsed turns vs duration in effect classes.
    """
    ACTIVE = "active"
    FINAL_TURN = "final_turn"
    READY_TO_EXPIRE = "ready_to_expire"
    EXPIRED = "expired"

def register_effects():
    """Register all available effect types with the registry"""
    # Combat effects
    EffectRegistry.register_effect("burn", BurnEffect)
    
    # Add other effect registrations here
    # EffectRegistry.register_effect("resistance", ResistanceEffect)
    # EffectRegistry.register_effect("vulnerability", VulnerabilityEffect)
    # etc.
    
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
        if hasattr(effect, 'process_async_results'):
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
    Process all effects for a character's turn with improved expiry message handling.
    
    This function handles both sync and async effect methods properly.
    Also processes effect feedback for reliable expiry messages.
    
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
    effects_to_remove = []  # Track effects to remove at the end
    print(f"DEBUG: Processing effects for {character.name} in round {round_number}, turn: {turn_name}")
    print(f"DEBUG: Character has {len(character.effects)} active effects")
    
    try:
        # Check for pending effect feedback from previous turn
        if character.name == turn_name:
            pending_feedback = character.get_pending_feedback()
            if pending_feedback:
                print(f"DEBUG: Found {len(pending_feedback)} pending feedback messages")
                for feedback in pending_feedback:
                    if feedback.expiry_message and not feedback.displayed:
                        # Add feedback message to start_messages or end_messages based on timing
                        # If feedback is from this character's turn, add to start_messages
                        # Otherwise add to end_messages
                        if feedback.turn_expired == character.name:
                            start_messages.append(feedback.expiry_message)
                        else:
                            end_messages.append(feedback.expiry_message)
                
                # Mark all feedback as displayed
                character.mark_feedback_displayed()
                
                # Clear displayed feedback (optional, can be done later)
                character.clear_old_feedback()
        
        # Only process if it's this character's turn
        if character.name == turn_name:
            # Add character round number for easier access in effects
            character.round_number = round_number
            
            # Process start of turn effects
            for effect in character.effects[:]:  # Copy to avoid modification issues
                # Skip processing if effect is already marked for removal
                if hasattr(effect, '_marked_for_expiry') and effect._marked_for_expiry:
                    print(f"DEBUG: Effect {effect.name} already marked for expiry, tracking for removal")
                    effects_to_remove.append(effect)
                    continue
                    
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
                    if hasattr(effect, 'process_async_results'):
                        attack_messages = await effect.process_async_results()
                        start_messages.extend(attack_messages)
                
                # Check if this effect causes the turn to be skipped
                if hasattr(effect, 'skips_turn') and effect.skips_turn:
                    was_skipped = True
                    
                # Check if effect was marked for expiry during start phase
                if hasattr(effect, '_marked_for_expiry') and effect._marked_for_expiry:
                    if not effect in effects_to_remove:
                        print(f"DEBUG: Effect {effect.name} marked for expiry during start phase")
                        effects_to_remove.append(effect)
            
            # Process end of turn effects
            for effect in character.effects[:]:  # Copy to avoid modification issues
                # Skip processing if effect is already marked for removal
                if effect in effects_to_remove:
                    continue
                    
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
                    if hasattr(effect, 'process_async_results'):
                        attack_messages = await effect.process_async_results()
                        if attack_messages:
                            end_messages.extend(attack_messages)
                            
                # Check if effect should expire after on_turn_end processing
                if hasattr(effect, '_marked_for_expiry') and effect._marked_for_expiry:
                    if not effect in effects_to_remove:  # Avoid duplicate processing
                        print(f"DEBUG: Effect {effect.name} marked for expiry during end phase")
                        effects_to_remove.append(effect)
            
            # Process effect removal and generate expiry messages
            for effect in effects_to_remove:
                if effect in character.effects:  # Check that it still exists
                    # Call on_expire - handle async or sync
                    expire_msg = ""
                    if inspect.iscoroutinefunction(effect.on_expire):
                        expire_msg = await effect.on_expire(character)
                    else:
                        expire_msg = effect.on_expire(character)
                    
                    # Add the expiry message if it's not empty and not already in the messages
                    if expire_msg:
                        print(f"DEBUG: Adding expiry message: {expire_msg}")
                        # Add to end messages for end-of-turn expiry
                        if expire_msg not in end_messages:
                            end_messages.append(expire_msg)
                    
                    print(f"DEBUG: Removing effect {effect.name} from {character.name}")
                    # Remove from character's effects list
                    character.effects.remove(effect)
            
            # Clean up the character round number
            if hasattr(character, 'round_number'):
                delattr(character, 'round_number')
        
        # Take another snapshot after processing
        if combat_logger:
            combat_logger.snapshot_character_state(character)
            
        print(f"DEBUG: Returning: was_skipped={was_skipped}, start_msgs={len(start_messages)}, end_msgs={len(end_messages)}")
        return was_skipped, start_messages, end_messages
        
    except Exception as e:
        logger.error(f"Error processing effects: {str(e)}", exc_info=True)
        print(f"DEBUG: Error processing effects: {str(e)}")
        
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
    
    # Add pending effect feedback if any exists
    pending_feedback = [f for f in character.effect_feedback if not f.displayed]
    if pending_feedback:
        if summary: summary.append("")
        summary.append("Recent Effect Updates:")
        for feedback in pending_feedback:
            # Simply append the expiry message, which is already formatted
            summary.append(f"• {feedback.effect_name} has worn off")
            
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