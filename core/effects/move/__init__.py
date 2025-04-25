"""
Move Effect System Implementation with Independent State Machine

This package contains a specialized implementation of the move effect system,
with its own state handling separate from the main BaseEffect system.
"""

# Import and re-export main classes
from .effect import MoveEffect
from .base import MovePhase, MoveEffectTiming
from .state import MoveState, RollTiming, MoveStateMachine
from .combat import CombatProcessor, BonusOnHit
from .saves import SavingThrowProcessor
from .manager import apply_move_effect, process_move_effects

# Make these classes available when importing from core.effects.move
__all__ = [
    'MoveEffect', 
    'MoveState',
    'MovePhase',
    'RollTiming',
    'MoveStateMachine',
    'CombatProcessor',
    'BonusOnHit',
    'SavingThrowProcessor',
    'apply_move_effect',
    'process_move_effects',
    'MoveEffectTiming'
]
