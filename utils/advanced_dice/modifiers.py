"""
Modifiers for dice rolls.
Handles various ways to modify dice rolls including advantage, 
exploding dice, rerolls, and other special cases.
"""

from typing import List, Optional, Callable
from enum import Enum, auto
import random

class ModifierType(Enum):
    """Types of dice roll modifiers"""
    KEEP = auto()       # Keep certain dice (advantage/disadvantage)
    EXPLODE = auto()    # Exploding dice
    REROLL = auto()     # Reroll certain values
    MULTIHIT = auto()   # Multi-hit attacks
    STATIC = auto()     # Static number modifier

class DiceModifier:
    """Base class for dice modifiers"""
    def __init__(self, type_: ModifierType, priority: int = 0):
        self.type = type_
        self.priority = priority
    
    def apply(self, results: List[int], sides: Optional[int] = None) -> List[int]:
        """Apply the modifier to roll results"""
        return results

    def __str__(self) -> str:
        return self.type.name.lower()

class KeepModifier(DiceModifier):
    """Keeps highest or lowest N dice"""
    def __init__(self, count: int, keep_highest: bool = True):
        super().__init__(ModifierType.KEEP, priority=100)
        self.count = count
        self.keep_highest = keep_highest
    
    def apply(self, results: List[int], sides: Optional[int] = None) -> List[int]:
        """Keep highest/lowest N results"""
        results.sort(reverse=self.keep_highest)
        return results[:self.count]
    
    def __str__(self) -> str:
        return f"{'k' if self.keep_highest else 'kl'}{self.count}"

class ExplodeModifier(DiceModifier):
    """Makes dice explode on certain values"""
    def __init__(self, value: int, max_explosions: int = 3):
        super().__init__(ModifierType.EXPLODE, priority=90)
        self.value = value
        self.max_explosions = max_explosions
    
    def apply(self, results: List[int], sides: Optional[int] = None) -> List[int]:
        """Apply explosions to qualifying rolls"""
        if not sides:
            return results  # Can't explode without knowing dice sides
            
        final_results = results.copy()
        explosion_count = 0
        
        # Check each result for explosion
        for result in results:
            if result >= self.value and explosion_count < self.max_explosions:
                while result >= self.value and explosion_count < self.max_explosions:
                    new_roll = random.randint(1, sides)
                    final_results.append(new_roll)
                    result = new_roll
                    explosion_count += 1
                    
        return final_results
    
    def __str__(self) -> str:
        return f"e{self.value}"

class RerollModifier(DiceModifier):
    """Rerolls dice that meet certain conditions"""
    def __init__(self, threshold: int, below: bool = True, reroll_once: bool = True):
        super().__init__(ModifierType.REROLL, priority=80)
        self.threshold = threshold
        self.below = below
        self.reroll_once = reroll_once
    
    def apply(self, results: List[int], sides: Optional[int] = None) -> List[int]:
        """Reroll dice that meet the condition"""
        if not sides:
            return results  # Can't reroll without knowing dice sides
            
        final_results = []
        
        for result in results:
            if (self.below and result <= self.threshold) or (not self.below and result >= self.threshold):
                new_result = random.randint(1, sides)
                if self.reroll_once:
                    final_results.append(new_result)
                else:
                    while (self.below and new_result <= self.threshold) or (not self.below and new_result >= self.threshold):
                        new_result = random.randint(1, sides)
                    final_results.append(new_result)
            else:
                final_results.append(result)
                
        return final_results
    
    def __str__(self) -> str:
        operator = "<=" if self.below else ">="
        return f"r{operator}{abs(self.threshold)}"

class MultihitModifier(DiceModifier):
    """Handles multi-hit attacks with modifiers"""
    def __init__(self, bonus: int):
        super().__init__(ModifierType.MULTIHIT, priority=70)
        self.bonus = bonus
    
    def apply(self, results: List[int], sides: Optional[int] = None) -> List[int]:
        """Apply bonus to each hit"""
        return [r + self.bonus for r in results]
    
    def __str__(self) -> str:
        return f"m{self.bonus}"

class StaticModifier(DiceModifier):
    """Arithmetic modifier for dice results"""
    def __init__(self, value: float, operator: str = '+'):
        # Set priority based on operator (multiplication/division before addition/subtraction)
        priority = 10 if operator in ['*', '/'] else 0
        super().__init__(ModifierType.STATIC, priority=priority)
        self.value = value
        self.operator = operator
    
    def apply(self, results: List[int], sides: Optional[int] = None) -> List[int]:
        """Apply arithmetic operation to results"""
        modified = []
        for r in results:
            if self.operator == '+':
                result = r + self.value
            elif self.operator == '-':
                result = r - self.value
            elif self.operator == '*':
                result = r * self.value
            elif self.operator == '/':
                result = r / self.value
            # Round to nearest integer
            modified.append(round(result))
        return modified
    
    def __str__(self) -> str:
        # Handle decimal values
        value_str = str(int(self.value)) if self.value.is_integer() else f"{self.value}"
        if self.operator == '+' and self.value >= 0:
            return f"+{value_str}"
        return f"{self.operator}{value_str}"

class ModifierFactory:
    """Creates modifiers from strings"""
    
    @staticmethod
    def create_from_str(modifier_str: str) -> Optional[DiceModifier]:
        """
        Create a modifier from a string
        
        Examples:
            "k1" -> KeepModifier(1, True)     # Keep highest
            "kl1" -> KeepModifier(1, False)   # Keep lowest
            "e6" -> ExplodeModifier(6)        # Explode on 6
            "r1" -> RerollModifier(1)         # Reroll 1s
            "m2" -> MultihitModifier(2)       # +2 to each hit
            "+3" -> StaticModifier(3)         # Static +3
        """
        try:
            # Handle common error cases first
            if not modifier_str or len(modifier_str) < 2:
                return None

            # Keep modifiers
            if modifier_str.startswith('k'):
                keep_highest = not modifier_str.startswith('kl')
                if keep_highest:
                    count = int(modifier_str[1:])
                else:
                    count = int(modifier_str[2:])
                return KeepModifier(count, keep_highest)
            
            # Exploding dice
            if modifier_str.startswith('e'):
                value = int(modifier_str[1:])
                if value <= 0:
                    return None
                return ExplodeModifier(value)
            
            # Reroll
            if modifier_str.startswith('r'):
                value = int(modifier_str[1:])
                if value <= 0:
                    return None
                return RerollModifier(value)
            
            # Multi-hit
            if modifier_str.startswith('m'):
                bonus = int(modifier_str[1:])
                return MultihitModifier(bonus)
            
            # Static/arithmetic modifiers
            if modifier_str[0] in '+-*/':
                operator = modifier_str[0]
                try:
                    value = float(modifier_str[1:])
                    if value == 0 and operator in '*/':  # Prevent division by zero
                        return None
                    return StaticModifier(value, operator)
                except ValueError:
                    return None
            
            # Handle positive numbers without explicit +
            try:
                if modifier_str.replace('.', '').isdigit():
                    return StaticModifier(float(modifier_str))
            except ValueError:
                pass
            
        except (ValueError, IndexError):
            return None
            
        return None
    
# Example usage:
if __name__ == "__main__":
    # Create some modifiers
    advantage = KeepModifier(1, keep_highest=True)
    explode = ExplodeModifier(6)
    reroll = RerollModifier(1)
    multihit = MultihitModifier(2)
    
    # Test parsing
    factory = ModifierFactory()
    mods = [
        factory.create_from_str("k1"),    # Advantage
        factory.create_from_str("kl1"),   # Disadvantage
        factory.create_from_str("e6"),    # Explode on 6
        factory.create_from_str("r1"),    # Reroll 1s
        factory.create_from_str("m2"),    # Multi-hit +2
        factory.create_from_str("+3")     # Static +3
    ]
    
    for mod in mods:
        if mod:
            print(f"Created: {mod}")