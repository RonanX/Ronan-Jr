"""
Move-specific effect management system with character linking support.

Handles:
- Move effect application with parent/child resource options
- Effect processing for linked characters during parent turns
- Resource cost handling (use parent or child resources)
- Combat logging integration
- Separate processing from BaseEffect system
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

from .timing import MovePhase
from .effect import MoveEffect

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
    effect: MoveEffect,
    round_number: int = 1,
    combat_logger=None,
    initiative_tracker=None
) -> str:
    """
    Apply a move effect with proper timing handling.
    
    Args:
        character: Character receiving the effect
        effect: MoveEffect to apply
        round_number: Current round number
        combat_logger: Optional combat logger
        initiative_tracker: Initiative tracker instance
        
    Returns:
        str: Feedback message
    """
    try:
        # Determine if this is the character's turn
        is_during_own_turn = False
        current_turn_name = "unknown"
        
        if initiative_tracker is not None:
            if hasattr(initiative_tracker, 'current_turn') and initiative_tracker.current_turn:
                if hasattr(initiative_tracker.current_turn, 'character_name'):
                    current_turn_name = initiative_tracker.current_turn.character_name
                    is_during_own_turn = (current_turn_name == character.name)
                    print(f"[MoveManager] Initiative detected: current_turn={current_turn_name}, character={character.name}, during_own_turn={is_during_own_turn}")
                else:
                    print(f"[MoveManager] Initiative tracker has no character_name")
            else:
                print(f"[MoveManager] Initiative tracker has no current_turn")
        else:
            print(f"[MoveManager] No initiative tracker provided")
        
        logger.info(f"MOVE EFFECT: Character={character.name}, CurrentTurn={current_turn_name}, During={is_during_own_turn}")
        
        # Store timing context on the effect
        effect.is_during_own_turn = is_during_own_turn
        effect.current_turn_name = current_turn_name
        effect.created_round = round_number  # Track when effect was created
        
        print(f"[MoveManager] Effect created in round {round_number}, during_own_turn={is_during_own_turn}")
        
        # Add to character
        character.effects.append(effect)
        
        # Apply and get message
        message = effect.on_apply(character, round_number)
        
        # Log in combat logger if available
        if combat_logger:
            combat_logger.add_event(
                "effect_applied",
                message=message,
                character=character.name,
                details={
                    "effect": effect.name,
                    "during_own_turn": is_during_own_turn,
                    "phase": effect.timing.current_phase.value,
                    "timing": effect.timing.to_dict()
                }
            )
        
        return message
        
    except Exception as e:
        logger.error(f"Error applying move effect: {str(e)}", exc_info=True)
        return f"Error applying {effect.name}: {str(e)}"

async def process_move_effects(
    character, 
    round_number: int, 
    turn_name: str,
    combat_logger=None
) -> Tuple[bool, List[str], List[str]]:
    """
    Process move effects with start-decrement, end-transition-remove pattern.
    
    Turn Start: Decrements durations and flags for transitions/removal
    Turn End: Executes transitions, shows status, removes flagged effects
    """
    start_messages = []
    end_messages = []
    was_skipped = False
    
    # Find move effects only
    move_effects = [
        e for e in character.effects 
        if hasattr(e, '__class__') and e.__class__.__name__ == 'MoveEffect'
    ]
    
    if not move_effects:
        return False, [], []
    
    logger.info(f"Processing {len(move_effects)} move effects for {character.name}")
    
    try:
        # --- Turn Start Phase: Decrement & Flag Only ---
        character.move_effect_processing_phase = 'start'
        
        for effect in move_effects:
            try:
                # 🕐 TIMING ONLY: Decrement durations and set flags
                start_result = effect.on_turn_start(character, round_number, turn_name)
                if start_result:
                    if isinstance(start_result, list):
                        start_messages.extend(msg for msg in start_result if msg)
                    else:
                        start_messages.append(start_result)
                        
            except Exception as e:
                logger.error(f"Error processing move effect {effect.name} (start): {e}", exc_info=True)
                start_messages.append(f"Error in {effect.name} (start): {e}")
        
        # --- Turn End Phase: Execute Transitions & Removals ---
        character.move_effect_processing_phase = 'end'
        
        effects_to_remove = []
        for effect in move_effects:
            try:
                # 🔄 TRANSITIONS & STATUS: Execute flagged transitions and show status
                end_result = effect.on_turn_end(character, round_number, turn_name)
                if end_result:
                    if isinstance(end_result, list):
                        end_messages.extend(msg for msg in end_result if msg)
                    else:
                        end_messages.append(end_result)
                
                # 🏷️ CHECK REMOVAL FLAGS: Collect effects flagged for removal
                if effect.is_expired:
                    effects_to_remove.append(effect)
                    
            except Exception as e:
                logger.error(f"Error processing move effect {effect.name} (end): {e}", exc_info=True)
                end_messages.append(f"Error in {effect.name} (end): {e}")
        
        # --- Process Removals: Clean up flagged effects ---
        if effects_to_remove:
            character.move_effect_processing_phase = 'expire'
            
            for effect in effects_to_remove:
                if effect in character.effects:
                    try:
                        # Call on_expire for cleanup
                        expire_msg = effect.on_expire(character)
                        if expire_msg:
                            # Add expiry message to end messages
                            end_messages.append(expire_msg)
                        
                        # Remove from character's effects
                        character.effects.remove(effect)
                        effect.debug(f"Removed from character list")
                        
                    except Exception as e:
                        logger.error(f"Error expiring move effect {effect.name}: {e}", exc_info=True)
                        end_messages.append(f"Error expiring {effect.name}: {e}")
    
    except Exception as e:
        logger.error(f"Error processing move effects: {e}", exc_info=True)
        end_messages.append(f"Error processing move effects: {e}")
    finally:
        # Clean up temporary attributes
        if hasattr(character, 'move_effect_processing_phase'):
            delattr(character, 'move_effect_processing_phase')
    
    return was_skipped, start_messages, end_messages

async def process_move_effects_with_linking(
    character,
    round_number: int,
    turn_name: str,
    combat_logger=None,
    game_state=None
) -> Tuple[bool, List[str], List[str]]:
    """
    Process move effects with character linking support.
    
    When processing a parent character's turn, also processes move effects for all linked children.
    """
    # Process the main character's move effects first
    was_skipped, start_messages, end_messages = await process_move_effects(
        character, round_number, turn_name, combat_logger
    )
    
    # Check if this character has linked children
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
                
                # Process child's move effects using the child's name as turn name
                child_skipped, child_start_msgs, child_end_msgs = await process_move_effects(
                    child_char, round_number, child_name, combat_logger
                )
                
                # Add child messages with prefixes
                for msg in child_start_msgs:
                    if msg:
                        prefixed_msg = f"🔗 {child_name}: {msg}" if not msg.startswith(f"{child_name}") else f"🔗 {msg}"
                        start_messages.append(prefixed_msg)
                
                for msg in child_end_msgs:
                    if msg:
                        prefixed_msg = f"🔗 {child_name}: {msg}" if not msg.startswith(f"{child_name}") else f"🔗 {msg}"
                        end_messages.append(prefixed_msg)
                
                # Child skip status is informational only
                if child_skipped:
                    logger.info(f"Linked child {child_name} would be skipped, but parent turn continues")
                
            except Exception as e:
                logger.error(f"Error processing linked child move effects {child_name}: {e}", exc_info=True)
                end_messages.append(f"🔗 Error processing {child_name} move effects: {str(e)}")
    
    return was_skipped, start_messages, end_messages

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