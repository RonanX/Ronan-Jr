"""
Standard action costs and definitions.
For use in combat system and move validation.
"""

from dataclasses import dataclass
from typing import Optional, Dict, List
from enum import Enum

class ActionType(str, Enum):
    """Types of standard actions"""
    MOVEMENT = "movement"
    COMBAT = "combat"
    UTILITY = "utility"

@dataclass
class StandardAction:
    """Definition of a standard action"""
    name: str
    type: ActionType
    star_cost: int
    description: str
    can_chain: bool = False
    chain_targets: Optional[List[str]] = None  # Names of moves this can chain into

# Dictionary of all standard actions with costs
STANDARD_ACTIONS: Dict[str, StandardAction] = {
    # Movement Actions (1★)
    "dash": StandardAction(
        name="Dash",
        type=ActionType.MOVEMENT,
        star_cost=1,
        description="Double movement speed this turn"
    ),
    "shove": StandardAction(
        name="Shove",
        type=ActionType.MOVEMENT,
        star_cost=1,
        description="Push target 5ft or prone (STR check vs target)"
    ),
    "disengage": StandardAction(
        name="Disengage",
        type=ActionType.MOVEMENT,
        star_cost=1,
        description="Avoid opportunity attacks during movement"
    ),
    "hide": StandardAction(
        name="Hide",
        type=ActionType.MOVEMENT,
        star_cost=1,
        description="Attempt to hide (requires cover/concealment)"
    ),

    # Basic Combat Actions
    "light_attack": StandardAction(
        name="Light Attack",
        type=ActionType.COMBAT,
        star_cost=1,
        description="Quick strike that can chain into other moves",
        can_chain=True,
        chain_targets=["light_attack", "medium_attack", "heavy_attack"]
    ),
    "medium_attack": StandardAction(
        name="Medium Attack",
        type=ActionType.COMBAT,
        star_cost=2,
        description="Balanced attack that can chain into other moves",
        can_chain=True,
        chain_targets=["light_attack", "medium_attack"]
    ),
    "heavy_attack": StandardAction(
        name="Heavy Attack",
        type=ActionType.COMBAT,
        star_cost=3,
        description="Powerful strike that usually ends combinations",
        can_chain=False  # Some special heavy attacks might override this
    ),
    "ultimate": StandardAction(
        name="Ultimate",
        type=ActionType.COMBAT,
        star_cost=5,
        description="Maximum power attack that uses all stars",
        can_chain=False
    ),

    # Utility Actions
    "dodge": StandardAction(
        name="Dodge",
        type=ActionType.UTILITY,
        star_cost=2,
        description="Attacks against you have disadvantage"
    ),
    "use_item": StandardAction(
        name="Use Item",
        type=ActionType.UTILITY,
        star_cost=1,
        description="Use a special item or object"
    ),
}

def get_action_cost(action_name: str) -> Optional[int]:
    """Get star cost for a standard action"""
    action = STANDARD_ACTIONS.get(action_name.lower())
    return action.star_cost if action else None

def get_action_info(action_name: str) -> Optional[StandardAction]:
    """Get full info for a standard action"""
    return STANDARD_ACTIONS.get(action_name.lower())

def can_chain_into(from_action: str, to_action: str) -> bool:
    """Check if one action can chain into another"""
    action = STANDARD_ACTIONS.get(from_action.lower())
    if not action or not action.can_chain:
        return False
    return to_action.lower() in (action.chain_targets or [])