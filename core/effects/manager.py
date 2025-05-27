"""
Effect system management functions for applying and processing effects with character linking support.

Handles:
- Effect registration
- Effect application/removal
- Effect processing with linked character support
- Combat logging integration
- Resource change tracking
- Effect feedback system

IMPLEMENTATION MANDATES:
- All effect processing MUST use the correct await/async patterns
- Always properly await async methods
- Maintain consistent return types (strings, never coroutines)
- Ensure compatibility with both sync and async methods
- Document async requirements clearly for future developers
- Handle linked character effect processing during parent turns
"""

from typing import List, Tuple, Optional, Dict, Any
from enum import Enum
import inspect
import logging
import asyncio

# Import the BaseEffect, states, and registry
from .base import BaseEffect, EffectState, EffectCategory, EffectRegistry
# Import specific effects needed for registration
from .burn_effect import BurnEffect # Keep for now
from .debug_effect import DebugEffect # Import the DebugEffect
from .ac import ACEffect # Import the ACEffect
from .stat import StatEffect # Import the new StatEffect


logger = logging.getLogger(__name__)

# Import CombatEventType from core.state if needed for logging
try:
    from core.state import CombatEventType
except ImportError:
    # Define a placeholder if core.state is not available or causes circular import
    class CombatEventType(Enum):
        STATUS_UPDATE = "status_update"
        EFFECT_APPLIED = "effect_applied"
        EFFECT_REMOVED = "effect_removed"
        RESOURCE_CHANGE = "resource_change"


def register_effects():
    """Register all available effect types with the registry"""
    # Register the DebugEffect
    EffectRegistry.register_effect("debug", DebugEffect)

    # Register existing effects
    EffectRegistry.register_effect("burn", BurnEffect)
    
    # Register the new StatEffect
    EffectRegistry.register_effect("stat", StatEffect)

    EffectRegistry.register_effect("ac", ACEffect)

    # Add other effect registrations here as they are updated/created
    # e.g., EffectRegistry.register_effect("stun", StunEffect)

async def apply_effect(
    character,
    effect: BaseEffect,
    round_number: int = 1,
    combat_logger=None,
    is_combat_active: bool = False,
    initiative_tracker=None
) -> str:
    """
    Apply an effect to a character, initialize its timing, and return the feedback message.
    Handles state transition from CREATED to ACTIVE.

    Args:
        character: Character to affect.
        effect (BaseEffect): The effect instance to apply.
        round_number (int): The current combat round number.
        combat_logger: Optional logger instance.
        is_combat_active (bool): Flag indicating if combat is currently active.
        initiative_tracker: Initiative tracker instance for determining turn context.

    Returns:
        str: Formatted feedback message from the effect's on_apply method.
    """
    try:
        # Ensure effect is in CREATED state
        if effect.state != EffectState.CREATED:
            logger.warning(f"Attempted to apply effect '{effect.name}' not in CREATED state ({effect.state.value}). Resetting.")
            effect.state = EffectState.CREATED # Reset state before applying

        # Snapshot state before applying
        if combat_logger:
            combat_logger.snapshot_character_state(character)

        # Check for existing stacking effects before adding
        for existing in character.effects:
            # Find matching effect types for stacking
            if (isinstance(existing, type(effect)) and 
                existing.name.lower() == effect.name.lower() and
                hasattr(existing, 'add_stacks')):
                
                # Let the existing effect handle stacking
                effect.debug(f"Found stackable effect {existing.name}, attempting stack")
                
                stack_msg = None
                # Handle async add_stacks if needed
                if inspect.iscoroutinefunction(existing.add_stacks):
                    stack_msg = await existing.add_stacks(
                        getattr(effect, 'stacks', 1),
                        character
                    )
                else:
                    stack_msg = existing.add_stacks(
                        getattr(effect, 'stacks', 1),
                        character
                    )
                
                if stack_msg:
                    # Log stacking event
                    if combat_logger:
                        combat_logger.add_event(
                            CombatEventType.EFFECT_APPLIED,
                            message=stack_msg,
                            character=character.name,
                            details={"effect": existing.name, "method": "stack"}
                        )
                    return stack_msg

        # SIMPLIFIED: Determine if effect is applied during character's own turn
        is_during_own_turn = False
        current_turn_name = None

        # Check if the effect already has a forced during/not during setting
        if hasattr(effect, 'is_during_own_turn') and effect.is_during_own_turn is not None:
            # RESPECT the explicitly set value instead of recalculating
            is_during_own_turn = effect.is_during_own_turn
            effect.debug(f"Using pre-set during_own_turn flag: {is_during_own_turn}")
            
            # Still determine current_turn_name for logging if needed
            if hasattr(effect, 'current_turn_name') and effect.current_turn_name:
                current_turn_name = effect.current_turn_name
            elif initiative_tracker is not None:
                # Use the existing logic to get current turn name
                if hasattr(initiative_tracker, 'current_turn') and initiative_tracker.current_turn:
                    if hasattr(initiative_tracker.current_turn, 'character_name'):
                        current_turn_name = initiative_tracker.current_turn.character_name
                elif (hasattr(initiative_tracker, 'turn_order') and 
                      hasattr(initiative_tracker, 'current_index') and 
                      initiative_tracker.turn_order and 
                      initiative_tracker.current_index < len(initiative_tracker.turn_order)):
                    
                    current_turn = initiative_tracker.turn_order[initiative_tracker.current_index]
                    if hasattr(current_turn, 'character_name'):
                        current_turn_name = current_turn.character_name
                else:
                    # Default when not in tracker
                    current_turn_name = character.name if is_during_own_turn else "unknown"
            else:
                # Default when not in tracker
                current_turn_name = character.name if is_during_own_turn else "unknown"
        else:
            # Original logic to determine is_during_own_turn and current_turn_name
            # Simple and direct method using initiative tracker if available
            if initiative_tracker is not None:
                # If we have a current_turn property with character_name, use it directly
                if hasattr(initiative_tracker, 'current_turn') and initiative_tracker.current_turn:
                    if hasattr(initiative_tracker.current_turn, 'character_name'):
                        current_turn_name = initiative_tracker.current_turn.character_name
                        is_during_own_turn = (current_turn_name == character.name)
                        effect.debug(f"Simple check: current_turn_name={current_turn_name}, character={character.name}, during={is_during_own_turn}")
                
                # Fallback: If we don't have current_turn but have turn_order and current_index
                elif (hasattr(initiative_tracker, 'turn_order') and 
                     hasattr(initiative_tracker, 'current_index') and 
                     initiative_tracker.turn_order and
                     initiative_tracker.current_index < len(initiative_tracker.turn_order)):
                    
                    current_turn = initiative_tracker.turn_order[initiative_tracker.current_index]
                    if hasattr(current_turn, 'character_name'):
                        current_turn_name = current_turn.character_name
                        is_during_own_turn = (current_turn_name == character.name)
                        effect.debug(f"Index-based check: current_turn_name={current_turn_name}, character={character.name}, during={is_during_own_turn}")
            
            # Default behavior when tracker isn't available
            if current_turn_name is None:
                if is_combat_active:
                    # In combat without known turn: safer to assume NOT during
                    is_during_own_turn = False
                    current_turn_name = "unknown"
                    effect.debug("No turn info available in combat, defaulting to NOT DURING")
                else:
                    # Not in combat: assume it's their turn for simpler duration
                    is_during_own_turn = True
                    current_turn_name = character.name
                    effect.debug("Not in combat, defaulting to DURING own turn")
        
        # CLEAR LOGGING: Log the final determination
        logger.info(f"EFFECT TIMING: Character={character.name}, CurrentTurn={current_turn_name}, During={is_during_own_turn}")
        
        # Store the timing info on the effect
        effect.is_during_own_turn = is_during_own_turn
        effect.current_turn_name = current_turn_name
        
        # Set combat flag on character if needed for timing logic
        if not hasattr(character, 'in_combat'):
            character.in_combat = is_combat_active

        # FIX: Special handling for duration=1 effects
        if (hasattr(effect, '_internal_duration') and 
            effect._internal_duration is not None and 
            effect._internal_duration < 2):
            # Safer comparison that handles None values
            if not effect.permanent and effect.duration == 1:
                if is_during_own_turn:
                    # For DURING effects with duration=1, internal should be 2
                    if hasattr(effect, '_internal_duration') and effect._internal_duration < 2:
                        effect._internal_duration = 2
                        effect._display_duration = 1  # Keep display as 1
                        effect.debug("FIXED: Duration=1 during own turn effect - set internal=2, display=1")
                else:
                    # For NOT DURING effects, internal and display should match
                    if hasattr(effect, '_internal_duration'):
                        effect._internal_duration = 1
                        effect._display_duration = 1
                        effect.debug("FIXED: Duration=1 not during effect - set both internal and display to 1")
        # FIX: For NOT DURING effects with any duration, ensure internal and display match
        elif not effect.permanent and not is_during_own_turn:
            if hasattr(effect, '_internal_duration') and hasattr(effect, '_display_duration'):
                # Make sure internal and display match for NOT DURING
                safe_duration = max(1, effect.duration) if effect.duration is not None else None
                if safe_duration is not None:
                    effect._internal_duration = safe_duration
                    effect._display_duration = safe_duration
                    effect.debug(f"FIXED: NOT DURING effect - set both durations to {safe_duration}")

        # Add effect to character
        character.effects.append(effect)
        
        # Call on_apply and get the message
        # Check if on_apply is an async method and await it properly
        if hasattr(effect, 'on_apply'):
            if asyncio.iscoroutinefunction(effect.on_apply):
                # Async version
                message = await effect.on_apply(character, round_number)
            else:
                # Non-async version
                message = effect.on_apply(character, round_number)
        else:
            message = f"{effect.name} applied to {character.name}."

        # FIX: Ensure the message correctly shows NOT DURING for non-during effects
        if not is_during_own_turn and "DURING turn" in message and "NOT DURING turn" not in message:
            # Replace "DURING turn" with "NOT DURING turn" in the message
            message = message.replace("DURING turn", "NOT DURING turn")
            effect.debug("Fixed message to correctly show NOT DURING")

        effect.debug(f"Added to character {character.name}. Current effects: {len(character.effects)}")

        # Log application
        if combat_logger:
            # Get timing info for logging, if available
            timing_details = {}
            if effect.timing:
                timing_details = {
                    "applied_during_own_turn": effect.timing.applied_during_own_turn,
                    "start_round": effect.timing.start_round,
                    "start_turn": effect.timing.start_turn_name
                }
            
            combat_logger.add_event(
                CombatEventType.EFFECT_APPLIED,
                message=message,
                character=character.name,
                details={
                    "effect": effect.name,
                    "duration": effect.duration,
                    "internal_duration": effect._internal_duration,
                    "state": effect.state.value,
                    "timing": timing_details
                }
            )
            # Snapshot state after applying
            combat_logger.snapshot_character_state(character)

        return message

    except Exception as e:
        logger.error(f"Error applying effect: {str(e)}", exc_info=True)
        return f"Error applying {effect.name}: {str(e)}"
            
async def remove_effect(
    character,
    effect_name: str,
    combat_logger=None
) -> str:
    """
    Forcefully remove a named effect from a character and trigger its on_expire logic.

    Args:
        character: Character to affect.
        effect_name (str): Name of the effect to remove (case-insensitive).
        combat_logger: Optional combat logger instance.

    Returns:
        str: Feedback message indicating success or failure.
    """
    try:
        effect_to_remove = None
        effect_name_lower = effect_name.lower()

        # Find the effect using case-insensitive matching
        for effect in character.effects:
            if effect.name.lower() == effect_name_lower:
                effect_to_remove = effect
                break

        if not effect_to_remove:
            return f"No effect named '{effect_name}' found on {character.name}."

        effect_to_remove.debug(f"Force removal initiated for {effect_name}.")

        # Snapshot state before removal
        if combat_logger:
            combat_logger.snapshot_character_state(character)

        # Call on_expire (synchronous in new BaseEffect)
        cleanup_message = effect_to_remove.on_expire(character)

        # Remove from character's effects list *after* on_expire
        if effect_to_remove in character.effects:
             character.effects.remove(effect_to_remove)
             effect_to_remove.debug("Removed from character's effect list.")

        # Generate final message
        message = f"Effect '{effect_name}' removed from {character.name}."
        if cleanup_message: # Append if on_expire returned something specific
             message += f" {cleanup_message}"

        # Log removal
        if combat_logger:
            combat_logger.add_event(
                CombatEventType.EFFECT_REMOVED,
                message=message,
                character=character.name,
                details={"effect": effect_name, "method": "manual"}
            )
            # Snapshot state after removal
            combat_logger.snapshot_character_state(character)

        return message

    except Exception as e:
        logger.error(f"Error removing effect: {str(e)}", exc_info=True)
        return f"Error removing {effect_name}: {str(e)}"

async def process_effects_with_linking(
    character,
    round_number: int,
    turn_name: str,
    combat_logger=None,
    game_state=None
) -> Tuple[bool, List[str], List[str]]:
    """
    Enhanced effect processing that handles character linking.
    
    When processing a parent character's turn, also processes effects for all linked children.
    Child character effects are processed and their messages included in the parent's turn.
    
    Args:
        character: The character whose turn it is (parent character)
        round_number: Current combat round
        turn_name: Name of character whose turn it is
        combat_logger: Optional combat logger
        game_state: Game state object to get linked characters
        
    Returns:
        Tuple[bool, List[str], List[str]]: (was_skipped, start_messages, end_messages)
    """
    # Process the main character's effects first
    was_skipped, start_messages, end_messages = await process_effects(
        character, round_number, turn_name, combat_logger
    )
    
    # Check if this character has linked children and we have game_state
    if game_state and hasattr(character, 'child_names') and character.child_names:
        logger.info(f"Processing effects for {len(character.child_names)} linked children of {character.name}")
        
        for child_name in character.child_names:
            try:
                # Get the child character
                child_char = game_state.get_character(child_name)
                if not child_char:
                    logger.warning(f"Linked child character '{child_name}' not found in game state")
                    continue
                
                logger.info(f"Processing linked child effects: {child_name}")
                
                # Process child's effects using the parent's turn name
                # This ensures the child's effects are processed as if it's their turn
                child_skipped, child_start_msgs, child_end_msgs = await process_effects(
                    child_char, round_number, child_name, combat_logger
                )
                
                # Add child messages to the parent's message lists with prefixes
                if child_start_msgs:
                    for msg in child_start_msgs:
                        if msg:
                            # Add prefix to indicate this is from a linked character
                            prefixed_msg = f"🔗 {child_name}: {msg}" if not msg.startswith(f"{child_name}") else f"🔗 {msg}"
                            start_messages.append(prefixed_msg)
                
                if child_end_msgs:
                    for msg in child_end_msgs:
                        if msg:
                            # Add prefix to indicate this is from a linked character
                            prefixed_msg = f"🔗 {child_name}: {msg}" if not msg.startswith(f"{child_name}") else f"🔗 {msg}"
                            end_messages.append(prefixed_msg)
                
                # If any child is skipped, we don't skip the parent's turn
                # The child skip status is just informational at this point
                if child_skipped:
                    logger.info(f"Linked child {child_name} would be skipped, but parent turn continues")
                
            except Exception as e:
                logger.error(f"Error processing linked child {child_name}: {e}", exc_info=True)
                end_messages.append(f"🔗 Error processing {child_name}: {str(e)}")
    
    return was_skipped, start_messages, end_messages

async def process_effects(
    character,
    round_number: int,
    turn_name: str, # Name of the character whose turn it currently is
    combat_logger=None
) -> Tuple[bool, List[str], List[str]]:
    """
    Process all active effects for a character at the start and end of their turn.
    Uses the BaseEffect lifecycle methods and state model.

    Args:
        character: The character whose effects are being processed.
        round_number (int): The current combat round number.
        turn_name (str): The name of the character whose turn it is.
        combat_logger: Optional logger instance.

    Returns:
        Tuple[bool, List[str], List[str]]:
            - was_turn_skipped (bool): True if an effect caused the turn to be skipped.
            - start_messages (List[str]): Messages generated during the turn start phase.
            - end_messages (List[str]): Messages generated during the turn end phase (including expiry).
    """
    start_messages = []
    end_messages = []
    was_skipped = False
    effects_to_remove = [] # Track effects that reach EXPIRED state

    # Only process effects for the character whose turn it is
    if character.name != turn_name:
        return False, [], [] # Not this character's turn

    # Store combat information for effect processing
    character.round_number = round_number
    character.turn_name = turn_name # Store whose turn it is for effect logic
    character.in_combat = True # Mark as in combat for timing logic

    try:
        # IMPROVED: First, check and fix any effects with duration issues
        for effect in character.effects[:]:
            if not hasattr(effect, 'timing') or not hasattr(effect, '_internal_duration') or effect.permanent:
                continue
                
            # Fix for NOT DURING effects to ensure internal and display durations match
            if not effect.timing.applied_during_own_turn:
                if hasattr(effect, '_display_duration') and effect._display_duration is not None:
                    # For NOT DURING, make sure internal and display are the same
                    safe_duration = max(1, effect._display_duration)
                    if effect._internal_duration != safe_duration:
                        effect._internal_duration = safe_duration
                        effect._display_duration = safe_duration
                        effect.debug(f"FIXED: NOT DURING effect had mismatched durations. Set both to {safe_duration}")
            
            # Fix for duration=1 "during" effects with insufficient internal duration
            elif effect.timing.applied_during_own_turn and effect._display_duration == 1:
                if effect._internal_duration < 2:
                    effect._internal_duration = 2
                    effect.debug(f"FIXED: Duration=1 during own turn effect had internal duration < 2")

        # IMPROVED: Process pending feedback at start, but don't display it yet
        pending_feedback_msgs = []
        if hasattr(character, 'effect_feedback') and character.get_pending_feedback():
            pending_feedback = character.get_pending_feedback()
            for feedback in pending_feedback:
                if feedback.expiry_message and not feedback.displayed:
                    # Don't add to start_messages directly to avoid duplication
                    pending_feedback_msgs.append(feedback.expiry_message)
            
            # Don't mark as displayed yet - do this after processing all start effects

        # --- Turn Start Phase ---
        character.effect_processing_phase = 'start' # Mark phase for effects
        for effect in character.effects[:]: # Iterate over a copy
            # Skip effects not in ACTIVE state or not meant for start processing
            if effect.state != EffectState.ACTIVE or effect.process_timing not in ["start", "both"]:
                continue
            try:
                # Call on_turn_start (synchronous in new BaseEffect)
                start_result = effect.on_turn_start(character, round_number, turn_name)
                if start_result:
                    # Ensure result is a list and filter out empty messages
                    start_messages.extend(msg for msg in start_result if msg)

                # Check for skip condition
                if hasattr(effect, 'causes_skip') and effect.causes_skip:
                    was_skipped = True
                    effect.debug("Causes turn skip.")
                    
                # For backwards compatibility with specific effect types
                if hasattr(effect, 'skip') and effect.skip:
                    was_skipped = True
                    effect.debug("Causes turn skip (legacy attribute).")

            except Exception as e:
                logger.error(f"Error processing on_turn_start for {effect.name}: {e}", exc_info=True)
                start_messages.append(f"Error in {effect.name} (start): {e}")

        # Now add feedback messages AFTER all start effects are processed
        # But only add them if they weren't already added by effect processing
        for msg in pending_feedback_msgs:
            if msg not in start_messages:
                start_messages.append(msg)

        # Now mark feedback as displayed
        if hasattr(character, 'effect_feedback'):
            character.mark_feedback_displayed()
            # FIX: Clear old feedback after marking as displayed
            if hasattr(character, 'clear_old_feedback'):
                character.clear_old_feedback()

        # --- Turn End Phase ---
        character.effect_processing_phase = 'end' # Mark phase for effects
        if not was_skipped:
            for effect in character.effects[:]: # Iterate over a copy again
                 # Skip effects not in ACTIVE/EXPIRING or not meant for end processing
                if effect.state not in [EffectState.ACTIVE, EffectState.EXPIRING] or \
                   effect.process_timing not in ["end", "both"]:
                    continue
                try:
                    # Call on_turn_end (synchronous in new BaseEffect)
                    # This method now handles duration checks and state transitions
                    end_result = effect.on_turn_end(character, round_number, turn_name)
                    if end_result:
                        # Ensure result is a list and filter out empty messages
                        end_messages.extend(msg for msg in end_result if msg)

                    # Check if the effect reached EXPIRED state during on_turn_end
                    if effect.state == EffectState.EXPIRED:
                        if effect not in effects_to_remove:
                            effects_to_remove.append(effect)
                            effect.debug("Marked for removal after end phase processing.")

                except Exception as e:
                    logger.error(f"Error processing on_turn_end for {effect.name}: {e}", exc_info=True)
                    end_messages.append(f"Error in {effect.name} (end): {e}")

        # --- Process Removals ---
        if effects_to_remove:
            character.effect_processing_phase = 'expire' # Mark phase
            for effect in effects_to_remove:
                if effect in character.effects:
                    try:
                        # Call on_expire for final cleanup (synchronous)
                        cleanup_msg = effect.on_expire(character)
                        if cleanup_msg and cleanup_msg not in end_messages: 
                             # Only add if not already added
                             end_messages.append(cleanup_msg)
                        # Remove from the character's list
                        character.effects.remove(effect)
                        effect.debug("Removed from character list.")
                    except Exception as e:
                        logger.error(f"Error processing on_expire for {effect.name}: {e}", exc_info=True)
                        end_messages.append(f"Error expiring {effect.name}: {e}")

        # --- Process Pending Feedback for End of Turn ---
        # This ensures expiry messages generated by on_turn_end are included in end_messages
        end_feedback_msgs = []
        if hasattr(character, 'effect_feedback'):
            pending_feedback = character.get_pending_feedback()
            if pending_feedback:
                character.effect_processing_phase = 'feedback' # Mark phase
                for feedback in pending_feedback:
                    if feedback.expiry_message and not feedback.displayed:
                        # Add to a separate list to check for duplicates
                        end_feedback_msgs.append(feedback.expiry_message)
                
                # Mark feedback as displayed and clear it
                character.mark_feedback_displayed()
                if hasattr(character, 'clear_old_feedback'):
                    character.clear_old_feedback()

        # IMPROVED: Add feedback messages that don't duplicate what we already have
        for msg in end_feedback_msgs:
            if msg not in end_messages:
                end_messages.append(msg)

    except Exception as e:
        logger.error(f"General error processing effects for {character.name}: {e}", exc_info=True)
        end_messages.append(f"Error processing effects: {e}") # Add error to messages
    finally:
        # Clean up temporary attributes
        if hasattr(character, 'round_number'):
            delattr(character, 'round_number')
        if hasattr(character, 'turn_name'):
            delattr(character, 'turn_name')
        if hasattr(character, 'effect_processing_phase'):
            delattr(character, 'effect_processing_phase')
        # Leave in_combat flag alone as it might be needed by other systems

    # Log collected messages
    if combat_logger:
         if start_messages:
              combat_logger.add_event(CombatEventType.STATUS_UPDATE, "\n".join(start_messages), character.name, round_number=round_number)
         if end_messages:
              combat_logger.add_event(CombatEventType.STATUS_UPDATE, "\n".join(end_messages), character.name, round_number=round_number)

    return was_skipped, start_messages, end_messages

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
    # Filter out effects that are already removed
    active_effects = [e for e in character.effects if e.state != EffectState.REMOVED]

    if not active_effects:
        return [f"{character.name} has no active effects."]

    summary = []

    # Group effects by category for better organization
    categories = {cat: [] for cat in EffectCategory}
    for effect in active_effects:
        cat = effect.category if effect.category else EffectCategory.CUSTOM
        if cat in categories:
             categories[cat].append(effect)
        else: # Handle potential unknown categories gracefully
             if EffectCategory.CUSTOM not in categories: categories[EffectCategory.CUSTOM] = []
             categories[EffectCategory.CUSTOM].append(effect)


    # Display effects by category
    for category, effects_in_category in categories.items():
        if effects_in_category:
            if summary: summary.append("") # Add spacing
            summary.append(f"**{category.value.capitalize()} Effects:**")
            for effect in effects_in_category:
                 # Use get_status_text if available, otherwise basic info
                 if hasattr(effect, 'get_status_text'):
                      status_text = effect.get_status_text(character)
                      if status_text:
                          summary.append(status_text)
                 else:
                      # Improved basic display with emoji and key info
                      emoji = effect.emoji if effect.emoji else "✨"
                      
                      # Show when effect will expire based on state and duration
                      status = ""
                      duration_str = ""
                      
                      if effect.state == EffectState.EXPIRING:
                          status = "(Expiring next turn)"
                      elif effect.state == EffectState.EXPIRED:
                          status = "(Expired)"
                      elif effect.permanent:
                          duration_str = "Permanent"
                      elif effect.duration is not None:
                          # Fixed: Calculate remaining turns consistently with on_turn_end
                          if hasattr(effect, 'timing') and effect.timing:
                              # Check if this effect is applied during own turn
                              applied_during_own = effect.timing.applied_during_own_turn
                              
                              if applied_during_own:
                                  # For DURING effects, we need to properly handle the offset
                                  if hasattr(effect, 'turns_elapsed'):
                                      # Calculate rounds passed and use that for display countdown
                                      if character.name == effect.timing.start_turn_name:
                                          rounds_passed = 0
                                          if hasattr(character, 'round_number') and effect.timing.start_round:
                                              rounds_passed = character.round_number - effect.timing.start_round
                                              
                                          # For display, we use rounds_passed directly
                                          remaining = max(0, effect.duration - rounds_passed)
                                          
                                          # FIX: Subtract 1 from remaining for effects with initial duration > 1
                                          # This aligns display with the actual expiration schedule
                                          if effect.duration > 1 and remaining > 1 and effect.state == EffectState.ACTIVE:
                                              remaining = max(1, remaining - 1)
                                              effect.debug(f"Adjusted display duration: {remaining} turns remaining")
                                          
                                          duration_str = f"{remaining} turn{'' if remaining == 1 else 's'} remaining"
                                      else:
                                          # Use turns_elapsed but with during-own-turn offset
                                          display_elapsed = max(0, effect.turns_elapsed - 1)
                                          remaining = max(0, effect.duration - display_elapsed)
                                          
                                          # FIX: Subtract 1 from remaining for effects with initial duration > 1
                                          if effect.duration > 1 and remaining > 1 and effect.state == EffectState.ACTIVE:
                                              remaining = max(1, remaining - 1)
                                              effect.debug(f"Adjusted display duration: {remaining} turns remaining")
                                          
                                          duration_str = f"{remaining} turn{'' if remaining == 1 else 's'} remaining"
                              else:
                                  # For NOT DURING effects, no offset is needed
                                  remaining = max(0, effect.duration - effect.turns_elapsed)
                                  
                                  # FIX: Subtract 1 from remaining for effects with initial duration > 1
                                  if effect.duration > 1 and remaining > 1 and effect.state == EffectState.ACTIVE:
                                      remaining = max(1, remaining - 1)
                                      effect.debug(f"Adjusted display duration: {remaining} turns remaining")
                                  
                                  duration_str = f"{remaining} turn{'' if remaining == 1 else 's'} remaining"
                          else:
                              # Fallback for effects without timing info
                              duration_str = f"{effect.duration} turns"
                      
                      summary.append(f"• {emoji} `{effect.name}` {duration_str} {status}")

    # Add pending effect feedback if any exists
    if hasattr(character, 'effect_feedback'):
        pending_feedback = [f for f in character.effect_feedback if not f.displayed]
        if pending_feedback:
            if summary: summary.append("")
            summary.append("**Recent Effect Updates:**")
            for feedback in pending_feedback:
                # Simply append the expiry message, which is already formatted
                summary.append(f"• `{feedback.effect_name} has worn off`") # Add backticks for consistency

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
        CombatEventType.RESOURCE_CHANGE,
        message=f"{emoji} `{msg}`", # Add backticks for consistency
        character=character.name,
        details={
            "resource": resource_type,
            "old_value": old_value,
            "new_value": new_value,
            "change": change,
            "reason": reason
        }
    )