"""
Move-specific effect management system with character linking support.

Handles:
- Move effect application with parent/child resource options
- Effect processing for linked characters during parent turns
- Resource cost handling (use parent or child resources)
- Combat logging integration
"""

import logging
from typing import Optional, List, Dict, Any, Tuple, Set

# Import CombatEventType from the correct location
try:
    from core.state import CombatEventType
except ImportError:
    try:
        from modules.combat.logger import CombatEventType
    except ImportError:
        # Define a minimal enum if neither import works
        from enum import Enum
        class CombatEventType(Enum):
            EFFECT_APPLIED = "effect_applied"
            EFFECT_REMOVED = "effect_removed"
            STATUS_UPDATE = "status_update"

from .base import MovePhase

logger = logging.getLogger(__name__)

class ResourceOptions:
    """Configuration for how move resources should be handled for linked characters"""
    
    def __init__(self, use_parent_resources: bool = False, 
                 use_parent_mp: bool = None, 
                 use_parent_hp: bool = None,
                 use_parent_stars: bool = None):
        """
        Initialize resource options for linked character moves.
        
        Args:
            use_parent_resources: If True, use parent for all resources (overrides specific options)
            use_parent_mp: If True, use parent's MP for costs (default: use child's MP)
            use_parent_hp: If True, use parent's HP for costs (default: use child's HP)  
            use_parent_stars: If True, use parent's action stars (default: use child's stars)
        """
        self.use_parent_resources = use_parent_resources
        
        # If use_parent_resources is True, override all specific options
        if use_parent_resources:
            self.use_parent_mp = True
            self.use_parent_hp = True
            self.use_parent_stars = True
        else:
            self.use_parent_mp = use_parent_mp if use_parent_mp is not None else False
            self.use_parent_hp = use_parent_hp if use_parent_hp is not None else False
            self.use_parent_stars = use_parent_stars if use_parent_stars is not None else False
    
    def get_resource_character(self, child_char, parent_char, resource_type: str):
        """
        Get the character whose resources should be used for a given resource type.
        
        Args:
            child_char: The child character using the move
            parent_char: The parent character  
            resource_type: 'mp', 'hp', or 'stars'
            
        Returns:
            Character object whose resources should be used
        """
        if resource_type == 'mp' and self.use_parent_mp:
            return parent_char
        elif resource_type == 'hp' and self.use_parent_hp:
            return parent_char
        elif resource_type == 'stars' and self.use_parent_stars:
            return parent_char
        else:
            return child_char
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/serialization"""
        return {
            "use_parent_resources": self.use_parent_resources,
            "use_parent_mp": self.use_parent_mp,
            "use_parent_hp": self.use_parent_hp,
            "use_parent_stars": self.use_parent_stars
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ResourceOptions':
        """Create from dictionary data"""
        return cls(
            use_parent_resources=data.get("use_parent_resources", False),
            use_parent_mp=data.get("use_parent_mp", None),
            use_parent_hp=data.get("use_parent_hp", None),
            use_parent_stars=data.get("use_parent_stars", None)
        )

async def apply_move_effect_with_linking(
    character,
    effect,
    round_number: int = 1,
    combat_logger=None,
    is_combat_active: bool = False,
    initiative_tracker=None,
    resource_options: Optional[ResourceOptions] = None,
    game_state=None
) -> str:
    """
    Apply a move effect with enhanced timing and linking support.
    
    Args:
        character: Character receiving the effect
        effect: MoveEffect to apply
        round_number: Current round number
        combat_logger: Optional combat logger
        is_combat_active: Whether combat is active
        initiative_tracker: Initiative tracker instance
        resource_options: How to handle resources for linked characters
        game_state: Game state to get parent/child relationships
        
    Returns:
        str: Feedback message
    """
    try:
        # Default resource options if none provided
        if resource_options is None:
            resource_options = ResourceOptions()
        
        # Check if this is a linked child character and get parent if so
        parent_char = None
        if game_state and hasattr(character, 'parent_name') and character.parent_name:
            parent_char = game_state.get_character(character.parent_name)
            if parent_char:
                logger.info(f"Move effect on linked child {character.name}, parent: {parent_char.name}")
        
        # Handle resource costs based on linking configuration
        if parent_char and hasattr(effect, 'move_data'):
            # Get resource costs from move data
            mp_cost = getattr(effect.move_data, 'mp_cost', 0)
            hp_cost = getattr(effect.move_data, 'hp_cost', 0)
            star_cost = getattr(effect.move_data, 'star_cost', 0)
            
            # Determine which character pays each resource cost
            mp_character = resource_options.get_resource_character(character, parent_char, 'mp')
            hp_character = resource_options.get_resource_character(character, parent_char, 'hp')
            star_character = resource_options.get_resource_character(character, parent_char, 'stars')
            
            logger.info(f"Resource assignment - MP: {mp_character.name}, HP: {hp_character.name}, Stars: {star_character.name}")
            
            # Apply resource costs to appropriate characters
            resource_messages = []
            
            if mp_cost > 0:
                old_mp = mp_character.resources.current_mp
                mp_character.resources.current_mp = max(0, old_mp - mp_cost)
                resource_messages.append(f"💙 {mp_character.name} MP: -{mp_cost} ({mp_character.resources.current_mp}/{mp_character.resources.max_mp})")
            
            if hp_cost > 0:
                old_hp = hp_character.resources.current_hp
                hp_character.resources.current_hp = max(0, old_hp - hp_cost)
                resource_messages.append(f"❤️ {hp_character.name} HP: -{hp_cost} ({hp_character.resources.current_hp}/{hp_character.resources.max_hp})")
            
            if star_cost > 0 and hasattr(star_character, 'action_stars'):
                star_character.action_stars.use_stars(star_cost)
                current_stars = star_character.action_stars.current_stars
                max_stars = star_character.action_stars.max_stars
                resource_messages.append(f"⭐ {star_character.name} Stars: -{star_cost} ({current_stars}/{max_stars})")
            
            # Store resource usage info on the effect for reference
            if hasattr(effect, 'set_resource_usage'):
                effect.set_resource_usage(mp_character, hp_character, star_character, resource_messages)
        
        # Apply the move effect using the standard function
        message = await apply_move_effect(
            character=character,
            effect=effect,
            round_number=round_number,
            combat_logger=combat_logger,
            is_combat_active=is_combat_active,
            initiative_tracker=initiative_tracker
        )
        
        # Add resource usage information to the message if linking was used
        if parent_char and hasattr(effect, 'resource_usage_messages'):
            resource_info = " | ".join(effect.resource_usage_messages)
            if resource_info:
                message += f"\n🔗 Resource usage: {resource_info}"
        
        return message
        
    except Exception as e:
        logger.error(f"Error applying move effect with linking: {str(e)}", exc_info=True)
        return f"Error applying {effect.name}: {str(e)}"

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
            combat_logger.add_event(
                CombatEventType.EFFECT_APPLIED,
                message=message,
                character=character.name,
                details={
                    "effect": effect.name,
                    "during_own_turn": is_during_own_turn,
                    "timing": effect.timing_handler.__dict__ if hasattr(effect, 'timing_handler') else {}
                }
            )
        
        return message
        
    except Exception as e:
        logger.error(f"Error applying move effect: {str(e)}", exc_info=True)
        return f"Error applying {effect.name}: {str(e)}"

async def process_move_effects_with_linking(
    character,
    round_number: int,
    turn_name: str,
    which: str = "both",
    combat_logger=None,
    game_state=None
) -> List[str]:
    """
    Process move effects with character linking support.
    
    When processing a parent character's turn, also processes move effects for all linked children.
    Child character move effects are processed and their messages included in the parent's turn.
    
    Args:
        character: Character whose turn it is (parent character)
        round_number: Current round number
        turn_name: Current turn character name
        which: Which processing to perform ("start", "end", or "both")
        combat_logger: Optional combat logger
        game_state: Game state object to get linked characters
        
    Returns:
        List[str]: Messages from effect processing
    """
    # Process the main character's move effects first
    main_messages = await process_move_effects(character, round_number, turn_name, which)
    
    # Check if this character has linked children and we have game_state
    if game_state and hasattr(character, 'child_names') and character.child_names:
        logger.info(f"Processing move effects for {len(character.child_names)} linked children of {character.name}")
        
        for child_name in character.child_names:
            try:
                # Get the child character
                child_char = game_state.get_character(child_name)
                if not child_char:
                    logger.warning(f"Linked child character '{child_name}' not found in game state")
                    continue
                
                logger.info(f"Processing linked child move effects: {child_name}")
                
                # Process child's move effects using the child's turn name for their effects
                # but they'll be displayed during the parent's turn
                child_messages = await process_move_effects(child_char, round_number, child_name, which)
                
                # Add child messages to the main message list with prefixes
                for msg in child_messages:
                    if msg:
                        # Add prefix to indicate this is from a linked character
                        prefixed_msg = f"🔗 {child_name}: {msg}" if not msg.startswith(f"{child_name}") else f"🔗 {msg}"
                        main_messages.append(prefixed_msg)
                
            except Exception as e:
                logger.error(f"Error processing linked child move effects {child_name}: {e}", exc_info=True)
                main_messages.append(f"🔗 Error processing {child_name} move effects: {str(e)}")
    
    return main_messages

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

def create_resource_options_for_child(use_parent_resources: bool = False, **kwargs) -> ResourceOptions:
    """
    Convenience function to create resource options for a linked child character.
    
    Args:
        use_parent_resources: Use parent for all resources
        **kwargs: Specific resource options (use_parent_mp, use_parent_hp, use_parent_stars)
        
    Returns:
        ResourceOptions instance
    """
    return ResourceOptions(use_parent_resources=use_parent_resources, **kwargs)

def apply_resource_costs_with_linking(
    child_char,
    parent_char,
    mp_cost: int = 0,
    hp_cost: int = 0,
    star_cost: int = 0,
    resource_options: Optional[ResourceOptions] = None
) -> List[str]:
    """
    Apply resource costs according to linking configuration.
    
    Args:
        child_char: The child character using the move
        parent_char: The parent character
        mp_cost: MP cost to apply
        hp_cost: HP cost to apply  
        star_cost: Star cost to apply
        resource_options: Configuration for which character pays costs
        
    Returns:
        List of messages describing resource changes
    """
    if resource_options is None:
        resource_options = ResourceOptions()
    
    messages = []
    
    # Apply MP cost
    if mp_cost > 0:
        mp_char = resource_options.get_resource_character(child_char, parent_char, 'mp')
        old_mp = mp_char.resources.current_mp
        mp_char.resources.current_mp = max(0, old_mp - mp_cost)
        messages.append(f"💙 {mp_char.name} MP: -{mp_cost} ({mp_char.resources.current_mp}/{mp_char.resources.max_mp})")
    
    # Apply HP cost
    if hp_cost > 0:
        hp_char = resource_options.get_resource_character(child_char, parent_char, 'hp')
        old_hp = hp_char.resources.current_hp
        hp_char.resources.current_hp = max(0, old_hp - hp_cost)
        messages.append(f"❤️ {hp_char.name} HP: -{hp_cost} ({hp_char.resources.current_hp}/{hp_char.resources.max_hp})")
    
    # Apply star cost
    if star_cost > 0:
        star_char = resource_options.get_resource_character(child_char, parent_char, 'stars')
        if hasattr(star_char, 'action_stars'):
            star_char.action_stars.use_stars(star_cost)
            current_stars = star_char.action_stars.current_stars
            max_stars = star_char.action_stars.max_stars
            messages.append(f"⭐ {star_char.name} Stars: -{star_cost} ({current_stars}/{max_stars})")
    
    return messages