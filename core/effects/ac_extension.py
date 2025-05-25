"""
Enhanced AC extension module that consolidates AC effect messages and improves feedback clarity.

This module provides three key improvements:
1. Consolidates multiple AC effect messages into a single message
2. Improves turn end feedback to better show changes
3. Makes initial apply messages more concise

IMPLEMENTATION MANDATES:
- Never change the AC effect calculation mechanics, only message display
- Preserve all function signatures and return types
- Process both turn start and turn end message consolidation
- Handle mixed positive/negative effects
- Support permanent effects and final turn messages
"""

from typing import List, Optional, Dict, Any, Tuple
import logging
import re

logger = logging.getLogger(__name__)

# Original function references
original_process_effects = None
original_apply_effect = None
extension_applied = False  # Guard to prevent multiple applications

async def enhanced_process_effects(
    character, 
    round_number: int, 
    turn_name: str,
    combat_logger = None
) -> Tuple[bool, List[str], List[str]]:
    """
    Enhanced version of process_effects that consolidates AC effect messages.
    Maintains original function signature and adds AC message consolidation.
    
    Args:
        character: The character whose effects are being processed
        round_number: Current combat round number
        turn_name: Name of the character whose turn it is
        combat_logger: Optional logger instance
        
    Returns:
        Tuple[bool, List[str], List[str]]:
            - was_turn_skipped: True if turn should be skipped
            - start_messages: Messages for turn start
            - end_messages: Messages for turn end
    """
    global original_process_effects
    
    if original_process_effects is None:
        logger.error("Original process_effects function not found")
        return False, [], []
    
    # Call the original function to get the original behavior
    was_skipped, start_messages, end_messages = await original_process_effects(
        character, round_number, turn_name, combat_logger
    )
    
    # Only consolidate messages if not skipped and they belong to this character
    if not was_skipped and character.name == turn_name:
        # Consolidate start messages if any exist
        if start_messages:
            start_messages = consolidate_ac_messages(character, start_messages, is_start=True)
            
        # Consolidate end messages if any exist
        if end_messages:
            end_messages = consolidate_ac_messages(character, end_messages, is_start=False)
    
    # Return the same tuple format as the original function
    return was_skipped, start_messages, end_messages

async def enhanced_apply_effect(
    character,
    effect,
    round_number: int = 1,
    combat_logger = None,
    is_combat_active: bool = False,
    initiative_tracker = None
) -> str:
    """
    Enhanced version of apply_effect that improves AC effect apply messages.
    
    Args:
        character: Character to affect
        effect: The effect to apply
        round_number: Current combat round
        combat_logger: Optional logger instance
        is_combat_active: Flag indicating if combat is active
        initiative_tracker: Initiative tracker for determining turn context
        
    Returns:
        str: Formatted message about effect application
    """
    global original_apply_effect
    
    if original_apply_effect is None:
        logger.error("Original apply_effect function not found")
        # Fall back to importing the original
        try:
            from core.effects.manager import apply_effect as original
            original_apply_effect = original
        except ImportError:
            logger.error("Failed to import original apply_effect")
            return f"Error applying effect: Initialization error"
    
    # First, apply the effect normally
    message = await original_apply_effect(
        character=character,
        effect=effect,
        round_number=round_number,
        combat_logger=combat_logger,
        is_combat_active=is_combat_active,
        initiative_tracker=initiative_tracker
    )
    
    # With the improved AC.py, we don't need to modify the apply message here anymore
    return message

def consolidate_ac_messages(character, messages: List[str], is_start: bool = True) -> List[str]:
    """
    Consolidate multiple AC effect messages into a single, clean message.
    
    Args:
        character: Character with AC effects
        messages: List of original messages
        is_start: Whether these are turn start (True) or turn end (False) messages
        
    Returns:
        Consolidated message list
    """
    try:
        # Try to import ACEffect for type checking
        from core.effects.ac import ACEffect
        
        # Early return if no messages
        if not messages:
            return messages
            
        # Find all AC effect instances on the character
        ac_effects = []
        try:
            # Get all active AC effects
            ac_effects = [
                effect for effect in character.effects 
                if isinstance(effect, ACEffect) and effect.state.value == "active"
            ]
            
            # If we don't have any AC effects, return original messages
            if not ac_effects:
                return messages
                
            logger.debug(f"Found {len(ac_effects)} AC effects for {character.name}")
        except ImportError as e:
            logger.error(f"Could not import ACEffect class: {e}")
            return messages

        # Enhanced pattern to identify both consolidated and non-consolidated AC messages
        ac_patterns = [
            r"AC [+-]\d+",                              # Consolidated pattern 
            r"AC (?:Boost|Reduction)",                  # Non-consolidated pattern
            r"armor (strengthens|weakens|returns)",     # Apply/expire patterns
            r"AC modified by [+-]\d+",                  # Non-consolidated details
            r"Current AC: \d+"                          # AC value pattern
        ]
        
        # Find all AC related messages
        ac_messages_indices = []
        for i, msg in enumerate(messages):
            if any(re.search(pattern, msg, re.IGNORECASE) for pattern in ac_patterns):
                ac_messages_indices.append(i)
                
        # If less than 2 AC messages, don't consolidate
        if len(ac_messages_indices) < 2:
            return messages
            
        # Calculate total AC modification
        total_amount = sum(effect.amount for effect in ac_effects)
        
        # Find minimum duration among non-permanent effects
        min_duration = None
        has_permanent = False
        
        for effect in ac_effects:
            if effect.permanent:
                has_permanent = True
                continue
            
            # Calculate remaining turns for display
            if hasattr(effect, 'calculate_duration'):
                _, is_final, remaining = effect.calculate_duration(
                    getattr(character, 'round_number', 1), 
                    character.name
                )
                
                # Update the minimum duration
                if remaining is not None and (min_duration is None or remaining < min_duration):
                    min_duration = remaining
                
                # Mark if any effect is in final turn
                if is_final and (min_duration is None or min_duration > 1):
                    min_duration = 1
            elif hasattr(effect, '_display_duration'):
                # Fallback to display duration
                display_duration = effect._display_duration
                if display_duration is not None and (min_duration is None or display_duration < min_duration):
                    min_duration = display_duration
                    
        # Determine duration text with more descriptive phrasing
        if has_permanent and (min_duration is None or min_duration == 0):
            duration_text = "(permanent)"
        elif min_duration == 0:
            duration_text = "(expiring now)" 
        elif min_duration == 1:
            # More descriptive final turn text for different phases
            if is_start:
                duration_text = "(expiring this turn)"
            else:
                duration_text = "(final turn)"
        else:
            duration_text = f"({min_duration} turns)"
        
        # Get the current AC
        current_ac = character.defense.current_ac if hasattr(character, 'defense') else "?"
        
        # Choose emoji and sign based on total amount
        if total_amount > 0:
            emoji = "🛡️⬆️"
            sign = "+"
        elif total_amount < 0:
            emoji = "🛡️⬇️" 
            sign = ""  # Negative number already has sign
        else:
            emoji = "🛡️"
            sign = ""
        
        # Create the consolidated message
        ac_message = f"AC {sign}{total_amount} {duration_text} • Current AC: {current_ac}"
        
        # Format message with emoji
        consolidated_msg = f"{emoji} `{ac_message}` {emoji}"
        
        # Debug log the consolidated message
        logger.debug(f"Created consolidated AC message: {consolidated_msg}")
        
        # Remove AC messages in reverse order to avoid index issues
        for idx in sorted(ac_messages_indices, reverse=True):
            if idx < len(messages):
                messages.pop(idx)
                
        # Add the consolidated message at the beginning for prominence
        if ac_messages_indices:
            messages.insert(0, consolidated_msg)
            logger.info(f"Consolidated {len(ac_messages_indices)} AC messages into one for {character.name}")
        
        return messages
    
    except Exception as e:
        # In case of any error, return the original messages to be safe
        logger.error(f"Error consolidating AC messages: {e}", exc_info=True)
        return messages

def apply_ac_extension():
    """
    Apply the AC extension by monkey-patching the process_effects function
    and the apply_effect function.
    """
    global original_process_effects, original_apply_effect, extension_applied
    
    # Prevent applying the extension multiple times
    if extension_applied:
        logger.info("AC extension already applied, skipping")
        return True
    
    # Import the effects manager module
    try:
        import core.effects.manager as manager
        
        # Save reference to the original functions
        if original_process_effects is None and hasattr(manager, 'process_effects'):
            original_process_effects = manager.process_effects
            
        if original_apply_effect is None and hasattr(manager, 'apply_effect'):
            original_apply_effect = manager.apply_effect
            
        # Replace with our enhanced versions
        if original_process_effects is not None:
            manager.process_effects = enhanced_process_effects
            
        if original_apply_effect is not None:
            manager.apply_effect = enhanced_apply_effect
        
        # Mark as applied to prevent double application
        extension_applied = True
        
        logger.info("AC extension applied successfully: Enhanced process_effects and apply_effect")
        return True
    except ImportError as e:
        logger.error(f"Failed to apply AC extension: {e}")
        return False