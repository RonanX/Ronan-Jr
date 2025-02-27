"""
Base classes for advanced dice rolling system.
Handles complex dice operations with modifiers and special rules.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum, auto
import random

class DieType(Enum):
    """Types of dice rolls"""
    NORMAL = auto()      # Standard dice roll
    ADVANTAGE = auto()   # Roll with advantage
    DISADVANTAGE = auto() # Roll with disadvantage
    CRITICAL = auto()    # Critical roll (usually doubles dice)

@dataclass
class DieRoll:
    """Represents a single die or group of dice"""
    count: int           # Number of dice
    sides: int          # Sides per die
    modifier: int = 0    # Static modifier
    roll_type: DieType = DieType.NORMAL
    
    # Roll configuration
    explode_on: Optional[int] = None  # Value that triggers exploding
    reroll_below: Optional[int] = None  # Reroll if result is below this
    keep_highest: Optional[int] = None  # Keep N highest results
    keep_lowest: Optional[int] = None   # Keep N lowest results
    multihit: Optional[int] = None      # Multi-hit modifier
    
    def roll(self, max_explosions: int = 3) -> List[int]:
        """Roll the dice with all applicable modifiers"""
        results = []
        explosion_count = 0
        
        # Initial rolls
        for _ in range(self.count):
            value = random.randint(1, self.sides)
            
            # Handle rerolls
            if self.reroll_below is not None and value <= self.reroll_below:
                value = random.randint(1, self.sides)
                
            results.append(value)
            
            # Handle exploding dice
            if self.explode_on and value >= self.explode_on:
                while value >= self.explode_on and explosion_count < max_explosions:
                    value = random.randint(1, self.sides)
                    results.append(value)
                    explosion_count += 1
        
        # Handle keeping highest/lowest (advantage/disadvantage)
        if self.keep_highest:
            results.sort(reverse=True)
            results = results[:self.keep_highest]
        elif self.keep_lowest:
            results.sort()
            results = results[:self.keep_lowest]
        
        return results

    def get_total(self) -> int:
        """Get total of roll including modifier"""
        results = self.roll()
        return sum(results) + self.modifier
    
    def get_multihit_totals(self) -> List[int]:
        """Get individual totals for multi-hit rolls"""
        if not self.multihit:
            return [self.get_total()]
            
        results = self.roll()
        if self.keep_highest or self.keep_lowest:
            # For advantage/disadvantage, apply to each hit
            totals = []
            chunk_size = 2 if self.roll_type in [DieType.ADVANTAGE, DieType.DISADVANTAGE] else 1
            for i in range(0, len(results), chunk_size):
                chunk = results[i:i+chunk_size]
                total = max(chunk) if self.keep_highest else min(chunk)
                totals.append(total + self.modifier + self.multihit)
            return totals
        else:
            # Normal multi-hit
            return [r + self.modifier + self.multihit for r in results]

    def __str__(self) -> str:
        """String representation of the roll"""
        parts = [f"{self.count}d{self.sides}"]
        
        # Add modifiers
        if self.modifier:
            parts.append(f"{'+' if self.modifier > 0 else ''}{self.modifier}")
        if self.roll_type != DieType.NORMAL:
            parts.append(self.roll_type.name.lower())
        if self.explode_on:
            parts.append(f"e{self.explode_on}")
        if self.reroll_below:
            parts.append(f"r{self.reroll_below}")
        if self.multihit:
            parts.append(f"m{self.multihit}")
        
        return "".join(parts)

class RollResult:
    """Stores the results of a dice roll with explanation"""
    def __init__(self, 
                 total: int,
                 rolls: List[int],
                 expression: str,
                 breakdown: str = "",
                 multihit_results: Optional[List[int]] = None):
        self.total = total
        self.rolls = rolls
        self.expression = expression
        self.breakdown = breakdown or str(total)
        self.multihit_results = multihit_results or []
    
    def __str__(self) -> str:
        if self.multihit_results:
            hits = [f"Hit {i+1}: {result}" for i, result in enumerate(self.multihit_results)]
            return f"{self.expression}\n" + "\n".join(hits)
        return f"{self.expression} = {self.breakdown} = {self.total}"

class DicePool:
    """Manages a collection of dice rolls"""
    def __init__(self):
        self.rolls: List[DieRoll] = []
        self.results: Dict[str, RollResult] = {}
    
    def add_roll(self, roll: DieRoll, name: str = "") -> None:
        """Add a roll to the pool"""
        self.rolls.append(roll)
        if name:
            # Handle multi-hit rolls
            if roll.multihit is not None:
                totals = roll.get_multihit_totals()
                result = RollResult(
                    sum(totals),
                    roll.roll(),
                    str(roll),
                    multihit_results=totals
                )
            else:
                # Normal roll
                result = RollResult(
                    roll.get_total(),
                    roll.roll(),
                    str(roll)
                )
            self.results[name] = result
    
    def get_result(self, name: str) -> Optional[RollResult]:
        """Get a named roll result"""
        return self.results.get(name)
    
    def clear(self) -> None:
        """Clear all rolls"""
        self.rolls.clear()
        self.results.clear()

# Example usage:
if __name__ == "__main__":
    # Create a basic roll (2d6+3)
    basic = DieRoll(count=2, sides=6, modifier=3)
    print(f"Basic roll: {basic.get_total()}")
    
    # Advantage roll (2d20kh1)
    advantage = DieRoll(
        count=2,
        sides=20,
        roll_type=DieType.ADVANTAGE,
        keep_highest=1
    )
    print(f"Advantage: {advantage.get_total()}")
    
    # Multi-hit roll (3d6m2 - three attacks with +2 each)
    multihit = DieRoll(count=3, sides=6, multihit=2)
    print(f"Multi-hit results: {multihit.get_multihit_totals()}")