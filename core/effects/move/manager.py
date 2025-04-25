"""
Move-specific effect management system.
"""

import logging
from typing import Optional, List, Dict, Any, Tuple

from .base import MovePhase

logger = logging.getLogger(__name__)

async def apply_move_effect(
    character,
    effect,
    round_number: int = 1,
    combat_logger=None,
    is_combat_active: bool = False,
    initiative_tracker=None
) -> str:
    """
    Apply a move effect with enhanced timing handling.
    
    Args:
        character: Character receiving the effect
        effect: MoveEffect to apply
        round_number: Current round number
        combat_logger: Optional combat logger
        is_combat_active: Whether combat is active
        initiative_tracker: Initiative tracker instance
        
    Returns:
        str: Feedback message
    """
    try:
        # Determine if this is the character's turn
        is_during_own_turn = False
        current_turn_name = None
        
        if initiative_tracker is not None:
            # Check if in combat with an active turn
            if hasattr(initiative_tracker, 'current_turn') and initiative_tracker.current_turn:
                if hasattr(initiative_tracker.current_turn, 'character_name'):
                    current_turn_name = initiative_tracker.current_turn.character_name
                    is_during_own_turn = (current_turn_name == character.name)
        
        logger.info(f"MOVE EFFECT: Character={character.name}, CurrentTurn={current_turn_name}, During={is_during_own_turn}")
        
        # Store timing info in the effect
        if hasattr(effect, 'timing_handler'):
            # If force_during is set, use that value
            if hasattr(effect, 'is_during_own_turn') and effect.is_during_own_turn is not None:
                effect.timing_handler.adjust_timing(effect.is_during_own_turn)
                logger.info(f"Using forced timing: {effect.is_during_own_turn}")
            else:
                # Otherwise use detected timing
                effect.timing_handler.adjust_timing(is_during_own_turn)
                logger.info(f"Using detected timing: {is_during_own_turn}")
        
        # Add to character
        character.effects.append(effect)
        
        # Apply and get message - changed from await to regular call since it's not async anymore
        message = effect.on_apply(character, round_number)
        
        # Process any pending async operations for instant effects
        if hasattr(effect, 'execute_pending_operations'):
            pending_messages = await effect.execute_pending_operations()
            if pending_messages:
                # Add to message
                if isinstance(pending_messages, list):
                    for msg in pending_messages:
                        message += f"\n{msg}"
                else:
                    message += f"\n{pending_messages}"
        
        # Log in combat logger if available
        if combat_logger:
            from core.combat_logger import CombatEventType
            combat_logger.add_event(
                CombatEventType.EFFECT_APPLIED,
                message=message,
                character=character.name,
                details={
                    "effect": effect.name,
                    "during_own_turn": is_during_own_turn
                }
            )
            
        return message
        
    except Exception as e:
        logger.error(f"Error applying move effect: {str(e)}", exc_info=True)
        return f"Error applying {effect.name}: {str(e)}"

async def process_move_effects(character, round_number: int, turn_name: str, which: str = "both") -> List[str]:
    """
    Process move effects with proper phase handling.
    
    Args:
        character: Character to process effects for
        round_number: Current round number
        turn_name: Current turn character name
        which: Which processing to perform ("start", "end", or "both")
        
    Returns:
        List[str]: Messages from effect processing
    """
    messages = []
    effects_to_remove = []
    
    # Find move effects
    move_effects = [e for e in character.effects if hasattr(e, 'timing_handler')]
    logger.info(f"Processing {len(move_effects)} move effects for {character.name}, {which} of turn")
    
    try:
        # Process start of turn effects
        if which in ["start", "both"]:
            for effect in move_effects:
                try:
                    start_result = effect.on_turn_start(character, round_number, turn_name)
                    if start_result:
                        if isinstance(start_result, list):
                            messages.extend(start_result)
                        else:
                            messages.append(start_result)
                            
                    # Process any pending async operations (like attack rolls)
                    if hasattr(effect, 'execute_pending_operations'):
                        async_results = await effect.execute_pending_operations()
                        if async_results:
                            if isinstance(async_results, list):
                                messages.extend(async_results)
                            else:
                                messages.append(async_results)
                            
                except Exception as e:
                    error_msg = f"Error in {effect.name} (start): {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    messages.append(error_msg)
        
        # Process end of turn effects
        if which in ["end", "both"]:
            for effect in move_effects:
                try:
                    end_result = effect.on_turn_end(character, round_number, turn_name)
                    if end_result:
                        if isinstance(end_result, list):
                            messages.extend(end_result)
                        else:
                            messages.append(end_result)
                    
                    # Check if effect should be removed
                    if effect.is_expired:
                        effects_to_remove.append(effect)
                        
                except Exception as e:
                    error_msg = f"Error in {effect.name} (end): {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    messages.append(error_msg)
        
        # Remove expired effects
        for effect in effects_to_remove:
            if effect in character.effects:
                try:
                    expire_msg = effect.on_expire(character)
                    if expire_msg:
                        messages.append(expire_msg)
                    character.effects.remove(effect)
                except Exception as e:
                    logger.error(f"Error removing effect {effect.name}: {str(e)}", exc_info=True)
    
    except Exception as e:
        logger.error(f"Error processing move effects: {str(e)}", exc_info=True)
        messages.append(f"Error processing effects: {str(e)}")
    
    return messages
