"""
Dice rolling utilities for handling various dice notation formats.
Supports standard dice notation (XdY), modifiers, and stat-based rolls.
"""

import re
import random
from typing import Tuple, List, Optional, Union
from core.character import StatType

class DiceRoller:
    """Handles dice rolling and calculation with various notations"""
    
    @staticmethod
    def roll_dice(dice_str: str, character: Optional['Character'] = None) -> Tuple[int, str]:
        """
        Roll dice based on notation. Returns (total, explanation)
        
        Supports:
        - Standard notation: "2d6", "1d20+5"
        - Multiple dice: "2d6+1d8"
        - Static modifiers: "+5", "-2" 
        - Stat modifiers: "str", "dex+2"
        - Combined: "2d6+str+5"
        - Negative dice: "-2d6" (subtract dice total)
        - Mixed expressions: "-2d6+int" (negative dice with stat modifier)
        - Regeneration formulas: "-2d6+wis" (e.g., for mana regeneration)
        """
        dice_str = dice_str.lower().replace(" ", "")
        
        # Handle pure numbers
        if dice_str.isdigit():
            return int(dice_str), str(dice_str)
        
        # Initialize tracking
        total = 0
        parts = []
        explanation = []
        
        # Check for complex expressions with embedded stat modifiers
        complex_expression = False
        for stat in ["str", "dex", "con", "int", "wis", "cha"]:
            if stat in dice_str and (("d" in dice_str) or any(op in dice_str for op in ["+", "-", "*", "/"])):
                complex_expression = True
                break
        
        # Special handling for complex expressions with embedded stat modifiers
        if complex_expression and character:
            # First, resolve all stat references
            for stat in ["str", "dex", "con", "int", "wis", "cha"]:
                if stat in dice_str:
                    mod = DiceRoller._get_stat_modifier(stat, character)
                    dice_str = re.sub(r'\b' + stat + r'\b', str(mod), dice_str)
                    explanation.append(f"({stat}: {mod})")
        
        # Split into components
        components = DiceRoller._split_components(dice_str)
        
        for comp in components:
            # Skip empty components
            if not comp:
                continue
                
            # Handle ability score modifiers (standalone)
            if not complex_expression and comp.lstrip("+-").lower() in ["str", "dex", "con", "int", "wis", "cha"]:
                if not character:
                    raise ValueError(f"Stat modifier '{comp}' used but no character provided")
                mod = DiceRoller._get_stat_modifier(comp.lstrip("+-"), character)
                if comp.startswith("-"):
                    mod = -mod
                total += mod
                parts.append(str(mod) if mod < 0 else f"+{mod}")
                explanation.append(f"({comp}: {mod})")
                continue
    
            # Handle standard numbers
            if comp.lstrip("+-").isdigit():
                num = int(comp)
                total += num
                parts.append(str(num) if num < 0 else f"+{num}")
                continue
    
            # Handle dice rolls, including negative dice
            match = re.match(r'([+-])?(\d+)d(\d+)', comp)
            if match:
                sign, num, sides = match.groups()
                num = int(num)
                sides = int(sides)
                
                # Apply sign to the number of dice
                negative_roll = sign == "-"
                
                # Roll the dice
                rolls = [random.randint(1, sides) for _ in range(num)]
                subtotal = sum(rolls)
                
                # Apply sign
                if negative_roll:
                    subtotal = -subtotal
                    
                total += subtotal
                parts.append(str(subtotal) if subtotal < 0 else f"+{subtotal}")
                roll_desc = f"({'-' if negative_roll else ''}{num}d{sides}: {rolls})"
                explanation.append(roll_desc)
                continue
    
            raise ValueError(f"Invalid dice component: {comp}")
    
        # Format explanation
        if explanation:
            return total, f"{total} {' '.join(explanation)}"
        return total, str(total)

    @staticmethod
    def _split_components(dice_str: str) -> List[str]:
        """Split dice string into components, preserving signs"""
        # Add space after + or - if not already present
        dice_str = re.sub(r'([+-])(?=\d|\w)', r'\1 ', dice_str)
        # Split by + or -, but keep the signs
        parts = re.split(r'\s*([+-])\s*', dice_str)
        # Recombine parts with their signs
        components = []
        current = parts[0]
        for i in range(1, len(parts), 2):
            sign = parts[i]
            value = parts[i + 1]
            components.append(current)
            current = sign + value
        components.append(current)
        return [c for c in components if c]

    @staticmethod
    def _get_stat_modifier(stat: str, character: 'Character') -> int:
        """Get ability score modifier for a stat"""
        stat_map = {
            'str': StatType.STRENGTH,
            'dex': StatType.DEXTERITY,
            'con': StatType.CONSTITUTION,
            'int': StatType.INTELLIGENCE,
            'wis': StatType.WISDOM,
            'cha': StatType.CHARISMA
        }
        stat_type = stat_map[stat]
        stat_value = character.stats.modified[stat_type]  # Use modified stats for rolls
        return (stat_value - 10) // 2

    @staticmethod
    def format_roll_result(total: int, explanation: str) -> str:
        """Format roll result for display"""
        if explanation and explanation != str(total):
            return f"`{explanation} = {total}`"
        return f"`{total}`"