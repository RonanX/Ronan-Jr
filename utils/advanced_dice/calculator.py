"""
Calculator for dice expressions with improved advantage/disadvantage handling.
"""

from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass
import re
import random
from .base import DieRoll, RollResult, DicePool, DieType
from core.character import StatType
from ..stat_helper import StatHelper
import logging

logger = logging.getLogger(__name__)

@dataclass
class RollBreakdown:
    """Detailed breakdown of a roll"""
    original_expression: str
    rolls: List[int]
    modified_rolls: List[int]
    selected_roll: Optional[int] = None
    modifiers_applied: List[str] = None
    final_result: int = 0
    multihit_results: Optional[List[int]] = None
    is_standalone: bool = False
    roll_type: Optional[str] = None
    advantage_state: Optional[str] = None
    stat_mods: Dict[str, int] = None  # Track stat modifiers separately

class DiceCalculator:
    """Handles calculation and formatting of dice rolls"""
    
    # Class-level pattern definitions
    DICE_PATTERN = re.compile(r'(\d+)?[dD](\d+)')
    MODIFIER_PATTERN = re.compile(r'([kKrReEmM][lLhH]?\d+)')
    NUMBER_PATTERN = re.compile(r'^[+-]?\d+$')
    ADVANTAGE_PATTERN = re.compile(r'\badvantage\b', re.IGNORECASE)
    DISADVANTAGE_PATTERN = re.compile(r'\bdisadvantage\b', re.IGNORECASE)
    MULTIHIT_PATTERN = re.compile(r'\bmultihit\s+(\d+)\b', re.IGNORECASE)
    
    @classmethod
    def calculate(cls, expression: str, character: Optional['Character'] = None) -> RollBreakdown:
        """Calculate results of a roll expression with improved advantage handling"""
        try:
            logger.debug(f"Calculating roll: {expression}")
            
            # Initialize breakdown with stat tracking
            breakdown = RollBreakdown(
                original_expression=expression,
                rolls=[],
                modified_rolls=[],
                modifiers_applied=[],
                stat_mods={}  # Track stat modifiers
            )

            # Handle pure numbers first
            if cls.NUMBER_PATTERN.match(expression):
                value = int(expression)
                return RollBreakdown(
                    original_expression=expression,
                    rolls=[value],
                    modified_rolls=[value],
                    final_result=value,
                    is_standalone=True,
                    modifiers_applied=[],
                    stat_mods={}
                )

            #print("\n=== Stat Modifier Processing Start ===")
            #print(f"Original expression: {expression}")
            #print(f"Character provided: {character.name if character else None}")
            
            total_stat_mod = 0
            for stat_type in StatType:
                # Map full names to short versions
                short_names = {
                    'strength': 'str',
                    'dexterity': 'dex',
                    'constitution': 'con',
                    'intelligence': 'int',
                    'wisdom': 'wis',
                    'charisma': 'cha'
                }
                short_name = short_names.get(stat_type.value)
                if not short_name:
                    continue
                
                # Look for both +stat and -stat patterns
                stat_pattern = f'[+\-]?{short_name}\\b'
                #print(f"Looking for pattern: {stat_pattern} in {expression}")
                if re.search(stat_pattern, expression, re.IGNORECASE):
                    if not character:
                        raise ValueError(f"Stat modifier used but no character provided")
                    
                    #print(f"\nProcessing {stat_type.value}:")
                    #print(f"  Found in expression: {re.findall(stat_pattern, expression, re.IGNORECASE)}")
                    
                    # Use exact same logic as debug output
                    value = character.stats.modified[stat_type]
                    mod = (value - 10) // 2
                    #print(f"  Character stat value: {value}")
                    #print(f"  Calculated modifier: {mod}")
                    
                    total_stat_mod += mod
                    breakdown.stat_mods[stat_type.value] = mod
                    
                    #print(f"  Running total_stat_mod: {total_stat_mod}")
                    #print(f"  Current breakdown.stat_mods: {breakdown.stat_mods}")

            #print("\n=== Final Results ===")
            #print(f"Total stat modifier: {total_stat_mod}")
            #print(f"Final breakdown.stat_mods: {breakdown.stat_mods}")
            #print(f"Current breakdown.final_result: {breakdown.final_result}")
            #print("=== Stat Modifier Processing End ===\n")

            # Parse dice expression
            dice_match = cls.DICE_PATTERN.search(expression)
            if not dice_match:
                raise ValueError(f"Invalid dice expression: {expression}")

            # Get base roll parameters
            count = int(dice_match.group(1) or '1')
            sides = int(dice_match.group(2))

            # Check for special roll types
            has_advantage = bool(cls.ADVANTAGE_PATTERN.search(expression))
            has_disadvantage = bool(cls.DISADVANTAGE_PATTERN.search(expression))
            multihit_match = cls.MULTIHIT_PATTERN.search(expression)

            if has_advantage and has_disadvantage:
                raise ValueError("Cannot have both advantage and disadvantage")

            # Handle advantage/disadvantage
            if has_advantage or has_disadvantage:
                rolls = [random.randint(1, sides) for _ in range(2)]
                breakdown.rolls = rolls.copy()
                
                selected_roll = max(rolls) if has_advantage else min(rolls)
                breakdown.selected_roll = selected_roll
                breakdown.modified_rolls = [selected_roll + total_stat_mod]  # Apply stat mod
                breakdown.final_result = selected_roll + total_stat_mod
                breakdown.advantage_state = 'advantage' if has_advantage else 'disadvantage'
                breakdown.roll_type = breakdown.advantage_state

            # Handle multihit
            elif multihit_match:
                modifier = int(multihit_match.group(1))
                rolls = [random.randint(1, sides) for _ in range(count)]
                breakdown.rolls = rolls.copy()
                
                # Apply modifier and stats to each roll
                modified_rolls = [r + modifier + total_stat_mod for r in rolls]
                breakdown.modified_rolls = modified_rolls
                breakdown.multihit_results = modified_rolls
                breakdown.final_result = sum(modified_rolls)
                breakdown.roll_type = 'multihit'

            # Normal roll
            else:
                rolls = [random.randint(1, sides) for _ in range(count)]
                breakdown.rolls = rolls.copy()
                breakdown.final_result = sum(rolls) + total_stat_mod
                breakdown.modified_rolls = [breakdown.final_result]

            # Apply any remaining arithmetic modifiers
            extra_mods = []
            for match in re.finditer(r'[+\-]\d+', expression):
                mod = int(match.group())
                breakdown.final_result += mod
                extra_mods.append(str(mod) if mod < 0 else f"+{mod}")
            
            if extra_mods:
                breakdown.modifiers_applied.extend(extra_mods)

            return breakdown

        except Exception as e:
            logger.error(f"Error in calculate: {e}")
            raise

    @classmethod
    def format_roll(cls, breakdown: RollBreakdown, concise: bool = False) -> str:
        """Format roll results with improved clarity"""
        try:
            parts = [f"🎲 `{breakdown.original_expression}: "]
            
            # Handle flat numbers
            if breakdown.is_standalone:
                parts.append(str(breakdown.final_result))
                parts.append("`")
                return "".join(parts)
            
            # Show original rolls
            if breakdown.rolls:
                parts.append(f"[{','.join(map(str, breakdown.rolls))}]")
            
            # Add stat modifiers first
            if breakdown.stat_mods:
                for stat, mod in breakdown.stat_mods.items():
                    parts.append(f"{'+' if mod >= 0 else ''}{mod}")
            
            # Add advantage/disadvantage handling
            if breakdown.advantage_state:
                parts.append(f" → {breakdown.selected_roll} ({breakdown.advantage_state})")
            
            # Add multihit results
            elif breakdown.multihit_results:
                parts.append(f" → [{','.join(map(str, breakdown.multihit_results))}]")
            
            # Add remaining modifiers
            if breakdown.modifiers_applied:
                parts.extend(breakdown.modifiers_applied)
            
            # Add final result for normal rolls
            if not (breakdown.advantage_state or breakdown.multihit_results):
                parts.append(f" = {breakdown.final_result}")
            
            # Close formatting
            parts.append("`")
            return "".join(parts)
            
        except Exception as e:
            logger.error(f"Error formatting roll: {e}")
            raise

    @classmethod
    def calculate_complex(cls, expression: str, character: Optional['Character'] = None, 
                         concise: bool = False) -> Tuple[int, str, Optional[str]]:
        """Calculate a complex expression with proper formatting"""
        try:
            # Calculate the roll
            breakdown = cls.calculate(expression, character)
            
            # Format the output
            formatted = cls.format_roll(breakdown, concise)
            
            # Prepare detailed log if needed
            detailed = None if concise else formatted
            
            return breakdown.final_result, formatted, detailed
            
        except Exception as e:
            logger.error(f"Error calculating complex expression: {e}")
            raise ValueError(f"Error: {str(e)}")