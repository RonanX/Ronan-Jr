"""
Parser for dice expressions.
Handles stat lookup and dice expression parsing with robust error handling.
"""

import re
from typing import List, Tuple, Optional, Dict, Any, Union
from dataclasses import dataclass
from .base import DieRoll, DieType
from .modifiers import ModifierFactory, DiceModifier, StaticModifier
from core.character import StatType
import logging

logger = logging.getLogger(__name__)

@dataclass
class ParsedRoll:
    """Result of parsing a dice expression"""
    roll: DieRoll
    modifiers: List[DiceModifier]
    original: str
    stat_refs: List[StatType] = None  # Changed to use StatType
    static_value: Optional[int] = None
    is_standalone: bool = False

class DiceParser:
    """Parses dice notation into roll objects"""
    
    # Regex patterns
    DICE_PATTERN = re.compile(r'^(\d+)?[dD](\d+)$')
    MODIFIER_PATTERN = re.compile(r'([kKrReEmM][lLhH]?\d+)')
    NUMBER_PATTERN = re.compile(r'^[+-]?\d+$')
    
    # Updated stat pattern to be more precise
    STAT_PATTERN = re.compile(
        r'\((str|dex|con|int|wis|cha)\)|'
        r'\b(strength|dexterity|constitution|intelligence|wisdom|charisma)\b',
        re.IGNORECASE
    )

    # Stat mapping using StatType enum
    STAT_MAP = {
        'str': StatType.STRENGTH,
        'dex': StatType.DEXTERITY,
        'con': StatType.CONSTITUTION,
        'int': StatType.INTELLIGENCE,
        'wis': StatType.WISDOM,
        'cha': StatType.CHARISMA,
        'strength': StatType.STRENGTH,
        'dexterity': StatType.DEXTERITY,
        'constitution': StatType.CONSTITUTION,
        'intelligence': StatType.INTELLIGENCE,
        'wisdom': StatType.WISDOM,
        'charisma': StatType.CHARISMA
    }

    @classmethod
    def get_stat_value(cls, stat_type: StatType, character: 'Character') -> int:
        """
        Get stat value from character, handling both dict and object formats.
        Returns the modifier value.
        """
        try:
            if isinstance(character.stats.modified, dict):
                # Dictionary format from database
                stat_key = stat_type.value
                stat_value = character.stats.modified.get(stat_key, 10)
            else:
                # Object format
                stat_value = getattr(character.stats.modified, stat_type.value, 10)
            
            # Calculate and return modifier
            return (stat_value - 10) // 2
            
        except Exception as e:
            logger.error(f"Error getting stat value: {e}")
            return 0

    @classmethod
    def _process_stats(cls, expression: str, character: Optional['Character']) -> Tuple[str, List[StatType], List[DiceModifier]]:
        """Process stat references and return (modified_expression, stat_refs, modifiers)"""
        if not character:
            return expression, [], []

        stat_refs = []
        modifiers = []
        modified_expr = expression

        # Find stat references
        matches = list(re.finditer(cls.STAT_PATTERN, expression))
        for match in matches:
            # Get the matched stat name (short or full)
            stat_name = (match.group(1) or match.group(2)).lower()
            
            if stat_name in cls.STAT_MAP:
                stat_type = cls.STAT_MAP[stat_name]
                
                # Get the modifier value
                mod_value = cls.get_stat_value(stat_type, character)
                
                stat_refs.append(stat_type)
                modifiers.append(StaticModifier(mod_value, '+'))
                
                # Replace in expression
                full_match = match.group(0)
                if full_match.startswith('('):
                    modified_expr = modified_expr.replace(full_match, str(mod_value))
                else:
                    # Handle cases where stat is used directly
                    modified_expr = re.sub(r'\b' + full_match + r'\b', str(mod_value), modified_expr)

        # Handle proficiency bonus
        if 'proficiency' in modified_expr.lower():
            prof_bonus = character.base_proficiency
            modified_expr = re.sub(r'\bproficiency\b', str(prof_bonus), modified_expr, flags=re.IGNORECASE)

        return modified_expr, stat_refs, modifiers

    @classmethod
    def _validate_expression(cls, expression: str) -> bool:
        """
        Validate dice expression format.
        Returns False if expression is invalid.
        """
        # Check for invalid operator combinations
        if re.search(r'[+\-*/]{2,}', expression):  # Multiple operators
            return False
        if re.search(r'[+\-*/]$', expression):  # Trailing operator
            return False
        
        # Check for malformed dice notation
        dice_parts = re.findall(r'\d*[dD]\d+', expression)
        for part in dice_parts:
            match = cls.DICE_PATTERN.match(part)
            if not match:
                return False
            sides = int(match.group(2))
            if sides <= 0:  # No zero-sided dice
                return False

        return True

    @classmethod
    def parse(cls, expression: str, character: Optional['Character'] = None) -> ParsedRoll:
        """Parse a dice expression into roll objects and modifiers"""
        original = expression
        expression = expression.strip()
        
        logger.debug(f"\n=== Starting parse of: {expression} ===")

        # Try natural language conversion first
        expression = cls._convert_natural_language(expression)

        # Handle pure number input
        if cls.NUMBER_PATTERN.match(expression):
            logger.debug(f"Found pure number input")
            return ParsedRoll(
                roll=DieRoll(count=1, sides=1),
                modifiers=[],
                original=original,
                static_value=int(expression),
                is_standalone=True
            )

        # Validate expression
        if not cls._validate_expression(expression):
            raise ValueError(f"Invalid dice expression: {original}")

        # Process stat modifiers
        expression, stat_refs, stat_modifiers = cls._process_stats(expression, character)

        # Find dice pattern
        dice_match = cls.DICE_PATTERN.search(expression)
        if not dice_match:
            raise ValueError(f"Invalid dice expression: {original}")

        # Create base roll
        count = int(dice_match.group(1)) if dice_match.group(1) else 1
        sides = int(dice_match.group(2))
        roll = DieRoll(count=count, sides=sides)

        # Get all modifiers
        modifiers = []
        
        # Handle special modifiers (k, r, e, m)
        for match in cls.MODIFIER_PATTERN.finditer(expression):
            if mod := ModifierFactory.create_from_str(match.group()):
                modifiers.append(mod)
        
        # Handle arithmetic modifiers
        parts = re.split(r'([+\-*/])', expression)
        current_op = '+'
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part in '+-*/':
                current_op = part
            else:
                try:
                    value = float(part)
                    modifiers.append(StaticModifier(value, current_op))
                except ValueError:
                    pass

        # Add stat modifiers
        modifiers.extend(stat_modifiers)

        return ParsedRoll(roll, modifiers, original, stat_refs)

    @classmethod
    def parse_complex(cls, expression: str, character: Optional['Character'] = None) -> List[ParsedRoll]:
        """Parse expression with multiple dice rolls"""
        logger.debug(f"\n=== Starting complex parse of: {expression} ===")
        
        # Split on plus signs that aren't part of modifiers
        parts = re.split(r'\+(?![^(]*\))', expression)
        
        results = []
        for part in parts:
            part = part.strip()
            if part:
                logger.debug(f"Parsing part: {part}")
                results.append(cls.parse(part, character))
                
        return results