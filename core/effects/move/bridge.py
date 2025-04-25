"""
Bridge utilities for connecting async move effects with the sync effect system.
"""

import asyncio
import logging
from typing import List, Optional, Callable, Any

logger = logging.getLogger(__name__)

class MoveEffectBridge:
    """Helper class for bridging async operations with sync effect system"""
    
    @staticmethod
    async def execute_pending_for_character(character, bot=None) -> List[str]:
        """
        Execute all pending operations for effects on a character.
        Should be called after effect processing.
        
        Args:
            character: The character whose effects have pending operations
            bot: Optional bot instance for logging
        
        Returns:
            List[str]: Messages from all executed operations
        """
        all_messages = []
        expiry_messages = []
        
        # Get all effects with execute_pending_operations method
        pending_effects = [
            effect for effect in character.effects 
            if hasattr(effect, 'execute_pending_operations')
        ]
        
        # Track effects to remove after execution
        effects_to_remove = []
        
        # Debug output
        if pending_effects:
            print(f"[MoveEffectBridge] Executing pending operations for {len(pending_effects)} moves on {character.name}")
        
        # Execute all pending operations
        for effect in pending_effects:
            try:
                # Call the execute_pending_operations method
                messages = await effect.execute_pending_operations()
                
                if messages:
                    if isinstance(messages, list):
                        all_messages.extend(messages)
                    else:
                        all_messages.append(messages)
                
                # Check if the effect should be removed after execution
                if hasattr(effect, 'is_expired') and effect.is_expired:
                    effects_to_remove.append(effect)
            except Exception as e:
                print(f"[MoveEffectBridge] Error executing pending operations for {effect.name}: {e}")
        
        # Process removals if needed
        for effect in effects_to_remove:
            if effect in character.effects:
                try:
                    # Call on_expire for final cleanup
                    if hasattr(effect, 'on_expire'):
                        expiry_msg = effect.on_expire(character)
                        if expiry_msg:
                            # Add to effect feedback for proper display in initiative
                            if hasattr(character, 'effect_feedback') and hasattr(character.effect_feedback, 'add_feedback'):
                                character.effect_feedback.add_feedback(
                                    round_number=getattr(character, 'round_number', 1),
                                    effect_name=effect.name,
                                    expiry_message=expiry_msg,
                                    is_expiry=True
                                )
                            expiry_messages.append(expiry_msg)
                    
                    # Remove from the character's list
                    print(f"[MoveEffectBridge] Removing expired effect: {effect.name}")
                    character.effects.remove(effect)
                except Exception as e:
                    print(f"[MoveEffectBridge] Error removing expired effect {effect.name}: {e}")
        
        # Add expiry messages to return list
        all_messages.extend(expiry_messages)
        return all_messages

    @staticmethod
    async def process_effects_wrapper(original_process_effects, character, round_number, turn_name, combat_logger=None):
        """
        Process effects with enhanced expiry message handling.
        """
        try:
            # Mark any effects that need to be removed
            effects_to_remove = []
            for effect in character.effects:
                if hasattr(effect, 'is_expired') and effect.is_expired:
                    effects_to_remove.append(effect)
            
            # Call the original function
            was_skipped, start_msgs, end_msgs = await original_process_effects(
                character, round_number, turn_name, combat_logger
            )
            
            # Process expiry messages for effects that are being removed
            expiry_msgs = []
            for effect in effects_to_remove:
                if effect in character.effects:  # Check if it's still in the list
                    try:
                        # Generate expiry message
                        if hasattr(effect, 'on_expire'):
                            expiry_msg = effect.on_expire(character)
                            if expiry_msg:
                                expiry_msgs.append(expiry_msg)
                                
                                # Add to effect feedback for proper display
                                if hasattr(character, 'effect_feedback') and hasattr(character.effect_feedback, 'add_feedback'):
                                    character.effect_feedback.add_feedback(
                                        round_number=round_number,
                                        effect_name=effect.name,
                                        expiry_message=expiry_msg,
                                        is_expiry=True
                                    )
                        
                        # Remove the effect
                        character.effects.remove(effect)
                        print(f"[MoveEffectBridge] Removed expired effect: {effect.name}")
                    except Exception as e:
                        print(f"[MoveEffectBridge] Error processing expiry for {effect.name}: {e}")
            
            # Execute pending operations
            pending_msgs = await MoveEffectBridge.execute_pending_for_character(character)
            
            # Add all messages to appropriate lists
            if expiry_msgs:
                # Add expiry messages to end_msgs to ensure they appear in the Effect Update embed
                end_msgs.extend([{'effect_name': 'expiry', 'message': msg, 'is_expiry': True} for msg in expiry_msgs])
            if pending_msgs:
                start_msgs.extend(pending_msgs)
            
            # Return the combined results
            return was_skipped, start_msgs, end_msgs
            
        except Exception as e:
            print(f"[MoveEffectBridge] Error in process_effects_wrapper: {e}")
            # Fall back to the original function
            return await original_process_effects(character, round_number, turn_name, combat_logger)

def register_with_bot(bot):
    """
    Register the MoveEffectBridge with the bot's initiative system.
    Call this during bot initialization.
    
    Args:
        bot: The GameBot instance
    """
    # Store the original process_effects function
    from core.effects.manager import process_effects
    original_process_effects = process_effects
    
    # Replace the bot's process_effects reference with our wrapper
    bot.process_effects = lambda character, round_number, turn_name, combat_logger=None: MoveEffectBridge.process_effects_wrapper(
        original_process_effects, character, round_number, turn_name, combat_logger
    )
    
    logger.info("Move effect bridge registered successfully")
    return bot.process_effects
