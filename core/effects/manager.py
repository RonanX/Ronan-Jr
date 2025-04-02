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
    Process all effects for a character's turn with improved feedback handling.
    
    This function:
    1. Processes each effect's turn start phase
    2. Checks for effects that would skip the turn
    3. Processes each effect's turn end phase
    4. Properly removes expired effects
    5. Maintains effect feedback for reliable expiry messages
    
    Args:
        character: Character being processed
        round_number: Current round number
        turn_name: Name of character whose turn it is
        combat_logger: Optional combat logger
        
    Returns:
        Tuple of (was_turn_skipped, start_messages, end_messages)
    """
    start_messages = []
    end_messages = []
    was_skipped = False
    effects_to_remove = []
    
    try:
        # ===== TURN START PHASE =====
        
        # FIXED: Check for pending effect feedback at the START of processing
        if character.name == turn_name and hasattr(character, 'effect_feedback'):
            pending_feedback = character.get_pending_feedback()
            if pending_feedback:
                for feedback in pending_feedback:
                    if feedback.expiry_message and not feedback.displayed:
                        # Add to start messages so it shows at turn start
                        start_messages.append(feedback.expiry_message)
                
                # Mark feedback as displayed only on this character's turn
                if character.name == turn_name:
                    character.mark_feedback_displayed()
        
        # Only process effect logic on character's turn
        if character.name == turn_name:
            # Add round number for easier access in effects
            character.round_number = round_number
            
            # Process start of turn effects
            for effect in character.effects[:]:
                # Skip if already marked for removal
                if hasattr(effect, '_marked_for_expiry') and effect._marked_for_expiry:
                    effects_to_remove.append(effect)
                    continue
                
                # FIXED: Check also for MoveEffect marked_for_removal
                if hasattr(effect, 'marked_for_removal') and effect.marked_for_removal:
                    effects_to_remove.append(effect)
                    continue
                
                # Skip if state machine indicates effect should be removed
                if hasattr(effect, 'state_machine') and hasattr(effect.state_machine, 'should_be_removed') and effect.state_machine.should_be_removed:
                    effects_to_remove.append(effect)
                    continue
                
                # Call on_turn_start
                if hasattr(effect, 'on_turn_start'):
                    if inspect.iscoroutinefunction(effect.on_turn_start):
                        start_result = await effect.on_turn_start(character, round_number, turn_name)
                    else:
                        start_result = effect.on_turn_start(character, round_number, turn_name)
                    
                    # Add messages to collection
                    if start_result:
                        if isinstance(start_result, list):
                            start_messages.extend(start_result)
                        else:
                            start_messages.append(start_result)
                
                # Check for skip effect
                if hasattr(effect, 'skips_turn') and effect.skips_turn:
                    was_skipped = True
                
                # Check for is_expired directly
                if hasattr(effect, 'is_expired') and effect.is_expired:
                    effects_to_remove.append(effect)
                # Track effects marked for expiry during start phase
                elif hasattr(effect, '_marked_for_expiry') and effect._marked_for_expiry:
                    if effect not in effects_to_remove:
                        effects_to_remove.append(effect)
                # FIXED: Also check for MoveEffect marked_for_removal
                elif hasattr(effect, 'marked_for_removal') and effect.marked_for_removal:
                    if effect not in effects_to_remove:
                        effects_to_remove.append(effect)

            # FIXED: Process effects marked for removal after turn start
            for effect in effects_to_remove:
                if effect in character.effects:
                    # Call on_expire
                    if inspect.iscoroutinefunction(effect.on_expire):
                        expire_msg = await effect.on_expire(character)
                    else:
                        expire_msg = effect.on_expire(character)
                    
                    # Add expiry message to start messages if it exists
                    if expire_msg and expire_msg not in start_messages:
                        start_messages.append(expire_msg)
                    
                    # FIXED: Explicitly remove effect from character's list
                    character.effects.remove(effect)
            
            # Clear list to track end-phase removals separately
            effects_to_remove = []
            
        # ===== TURN END PHASE =====
        
        # Process end of turn effects
        if character.name == turn_name:
            for effect in character.effects[:]:
                # Skip if already in removal list
                if effect in effects_to_remove:
                    continue
                
                # Skip if state machine indicates effect should be removed
                if hasattr(effect, 'state_machine') and hasattr(effect.state_machine, 'should_be_removed') and effect.state_machine.should_be_removed:
                    effects_to_remove.append(effect)
                    continue
                
                # Call on_turn_end
                if hasattr(effect, 'on_turn_end'):
                    if inspect.iscoroutinefunction(effect.on_turn_end):
                        end_result = await effect.on_turn_end(character, round_number, turn_name)
                    else:
                        end_result = effect.on_turn_end(character, round_number, turn_name)
                    
                    # IMPROVED: Collect all end messages
                    if end_result:
                        if isinstance(end_result, list):
                            for msg in end_result:
                                if not msg:
                                    continue
                                end_messages.append(msg)
                        else:
                            end_messages.append(end_result)
                
                # Check for is_expired at end of turn
                if hasattr(effect, 'is_expired') and effect.is_expired:
                    effects_to_remove.append(effect)
                # Track effects marked for expiry during end phase
                elif hasattr(effect, '_marked_for_expiry') and effect._marked_for_expiry:
                    if effect not in effects_to_remove:
                        effects_to_remove.append(effect)
                # FIXED: Also check for MoveEffect marked_for_removal
                elif hasattr(effect, 'marked_for_removal') and effect.marked_for_removal:
                    if effect not in effects_to_remove:
                        effects_to_remove.append(effect)
            
            # FIXED: Process effect removal for end-phase expirations
            for effect in effects_to_remove:
                if effect in character.effects:
                    # FIXED: Check if it's a move effect and already added expiry message
                    if hasattr(effect, 'marked_for_removal') and effect.marked_for_removal:
                        # Call on_expire only if it hasn't already added to feedback
                        perform_expire = True
                        
                        if hasattr(character, 'effect_feedback'):
                            for feedback in character.effect_feedback:
                                if feedback.effect_name == effect.name and not feedback.displayed:
                                    # We already have pending feedback, don't call on_expire again
                                    perform_expire = False
                                    break
                        
                        if perform_expire:
                            # Call on_expire
                            if inspect.iscoroutinefunction(effect.on_expire):
                                expire_msg = await effect.on_expire(character)
                            else:
                                expire_msg = effect.on_expire(character)
                            
                            # Add expiry message to the list if it exists and not already there
                            if expire_msg and expire_msg not in end_messages:
                                end_messages.append(expire_msg)
                    else:
                        # Standard effect - always call on_expire
                        if inspect.iscoroutinefunction(effect.on_expire):
                            expire_msg = await effect.on_expire(character)
                        else:
                            expire_msg = effect.on_expire(character)
                        
                        # Add expiry message to the list if it exists
                        if expire_msg and expire_msg not in end_messages:
                            end_messages.append(expire_msg)
                    
                    # FIXED: Always remove the effect from character's list
                    character.effects.remove(effect)
            
            # Clean up round number
            if hasattr(character, 'round_number'):
                delattr(character, 'round_number')
            
            # FIXED: No need to append expiry messages here - already handled above
        
        return was_skipped, start_messages, end_messages
        
    except Exception as e:
        logger.error(f"Error processing effects: {str(e)}", exc_info=True)
        if hasattr(character, 'round_number'):
            delattr(character, 'round_number')
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