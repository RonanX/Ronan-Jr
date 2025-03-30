"""
Calculator for dice expressions with improved advantage/disadvantage handling.
Now with roll modifier effect support and fixed multihit advantage.
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
    advantage_count: int = 1  # Added to track advantage level
    stat_mods: Dict[str, int] = None  # Track stat modifiers separately
    pre_advantage_rolls: Optional[List[int]] = None  # Store rolls after modifiers but before advantage selection

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
    def apply_roll_modifiers(cls, expression: str, character: 'Character') -> Tuple[str, List[str], bool]:
        """
        Check for and apply roll modifiers from character effects.
        
        Returns:
        - Modified expression
        - List of applied modifier messages
        - Whether any "next roll only" effects were used
        """
        if not character or not hasattr(character, 'custom_parameters'):
            return expression, [], False
            
        # Check if roll_modifiers exist in custom parameters
        roll_modifiers = character.custom_parameters.get('roll_modifiers', [])
        if not roll_modifiers:
            return expression, [], False
            
        # Initialize tracking
        applied_messages = []
        used_next_roll = False
        
        # Track current advantage/disadvantage state
        has_advantage = cls.ADVANTAGE_PATTERN.search(expression) is not None
        has_disadvantage = cls.DISADVANTAGE_PATTERN.search(expression) is not None
        
        # Extract advantage/disadvantage count if specified
        adv_count = 0
        if has_advantage:
            adv_match = re.search(r'advantage\s+(\d+)', expression, re.IGNORECASE)
            if adv_match:
                adv_count = int(adv_match.group(1))
            else:
                adv_count = 1
                
        disadv_count = 0
        if has_disadvantage:
            disadv_match = re.search(r'disadvantage\s+(\d+)', expression, re.IGNORECASE)
            if disadv_match:
                disadv_count = int(disadv_match.group(1))
            else:
                disadv_count = 1
                
        # Process each roll modifier
        for modifier in roll_modifiers[:]:  # Copy the list since we might modify it
            if not hasattr(modifier, 'modifier_type'):
                continue
                
            # Apply based on modifier type
            modifier_type = modifier.modifier_type.value
            
            if modifier_type == 'bonus':
                # Add numeric bonus - handle both positive and negative
                sign = "+" if modifier.value >= 0 else ""
                new_expr = expression + f"{sign}{modifier.value}"
                expression = new_expr
                applied_messages.append(f"Applied {sign}{modifier.value} from {modifier.name}")
                
            elif modifier_type == 'advantage':
                # Apply advantage effect
                if has_disadvantage:
                    # If roll already has disadvantage, reduce it
                    if modifier.value >= disadv_count:
                        # Disadvantage is completely canceled
                        expression = expression.replace('disadvantage', '').strip()
                        if ' disadvantage' in expression:
                            expression = expression.replace(' disadvantage', '')
                        has_disadvantage = False
                        disadv_count = 0
                        has_advantage = True
                        adv_count = modifier.value - disadv_count
                        if adv_count > 0:
                            expression += f" advantage {adv_count}"
                        applied_messages.append(f"Disadvantage canceled and converted to Advantage {adv_count} by {modifier.name}")
                    else:
                        # Disadvantage is reduced but not canceled
                        remaining = disadv_count - modifier.value
                        expression = expression.replace(f"disadvantage {disadv_count}", f"disadvantage {remaining}")
                        if "disadvantage" in expression and not "disadvantage " in expression:
                            expression = expression.replace("disadvantage", f"disadvantage {remaining}")
                        disadv_count = remaining
                        applied_messages.append(f"Disadvantage reduced to {remaining} by {modifier.name}")
                elif has_advantage:
                    # Increase existing advantage
                    new_adv_count = adv_count + modifier.value
                    if "advantage " in expression:
                        expression = expression.replace(f"advantage {adv_count}", f"advantage {new_adv_count}")
                    else:
                        expression = expression.replace("advantage", f"advantage {new_adv_count}")
                    adv_count = new_adv_count
                    applied_messages.append(f"Advantage increased to {new_adv_count} by {modifier.name}")
                else:
                    # Add new advantage
                    adv_value = modifier.value
                    expression += f" advantage {adv_value}" if adv_value > 1 else " advantage"
                    has_advantage = True
                    adv_count = adv_value
                    applied_messages.append(f"Added Advantage {adv_value} from {modifier.name}")
                    
            elif modifier_type == 'disadvantage':
                # Apply disadvantage effect
                if has_advantage:
                    # If roll already has advantage, reduce it
                    if modifier.value >= adv_count:
                        # Advantage is completely canceled
                        expression = expression.replace('advantage', '').strip()
                        if ' advantage' in expression:
                            expression = expression.replace(' advantage', '')
                        has_advantage = False
                        adv_count = 0
                        has_disadvantage = True
                        disadv_count = modifier.value - adv_count
                        if disadv_count > 0:
                            expression += f" disadvantage {disadv_count}"
                        applied_messages.append(f"Advantage canceled and converted to Disadvantage {disadv_count} by {modifier.name}")
                    else:
                        # Advantage is reduced but not canceled
                        remaining = adv_count - modifier.value
                        expression = expression.replace(f"advantage {adv_count}", f"advantage {remaining}")
                        if "advantage" in expression and not "advantage " in expression:
                            expression = expression.replace("advantage", f"advantage {remaining}")
                        adv_count = remaining
                        applied_messages.append(f"Advantage reduced to {remaining} by {modifier.name}")
                elif has_disadvantage:
                    # Increase existing disadvantage
                    new_disadv_count = disadv_count + modifier.value
                    if "disadvantage " in expression:
                        expression = expression.replace(f"disadvantage {disadv_count}", f"disadvantage {new_disadv_count}")
                    else:
                        expression = expression.replace("disadvantage", f"disadvantage {new_disadv_count}")
                    disadv_count = new_disadv_count
                    applied_messages.append(f"Disadvantage increased to {new_disadv_count} by {modifier.name}")
                else:
                    # Add new disadvantage
                    disadv_value = modifier.value
                    expression += f" disadvantage {disadv_value}" if disadv_value > 1 else " disadvantage"
                    has_disadvantage = True
                    disadv_count = disadv_value
                    applied_messages.append(f"Added Disadvantage {disadv_value} from {modifier.name}")
            
            # Mark next roll only effects as used
            if hasattr(modifier, 'next_roll_only') and modifier.next_roll_only:
                # Mark the effect as used
                if hasattr(modifier, 'mark_used'):
                    modifier.mark_used()
                    used_next_roll = True
        
        # Clean up expression - ensure proper spacing
        expression = ' '.join(expression.split())
        
        return expression, applied_messages, used_next_roll
    
    @classmethod
    def calculate(cls, expression: str, character: Optional['Character'] = None) -> RollBreakdown:
        """Calculate results of a roll expression with improved advantage handling"""
        try:
            logger.debug(f"Calculating roll: {expression}")
            
            # Apply roll modifiers from character effects if available
            if character:
                modified_expression, applied_modifiers, used_next_roll = cls.apply_roll_modifiers(expression, character)
                if modified_expression != expression:
                    logger.debug(f"Modified expression due to roll modifiers: {modified_expression}")
                    logger.debug(f"Applied modifiers: {applied_modifiers}")
                    expression = modified_expression
            
            # Initialize breakdown with stat tracking
            breakdown = RollBreakdown(
                original_expression=expression,
                rolls=[],
                modified_rolls=[],
                modifiers_applied=[],
                stat_mods={},  # Track stat modifiers
                pre_advantage_rolls=[],  # Store rolls after modifiers but before advantage selection
                advantage_count=1  # Default advantage count
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
                    stat_mods={},
                    pre_advantage_rolls=[],
                    advantage_count=1
                )
    
            # Process stat modifiers
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
                if re.search(stat_pattern, expression, re.IGNORECASE):
                    if not character:
                        raise ValueError(f"Stat modifier used but no character provided")
                    
                    # Use exact same logic as debug output
                    value = character.stats.modified[stat_type]
                    mod = (value - 10) // 2
                    
                    total_stat_mod += mod
                    breakdown.stat_mods[stat_type.value] = mod
    
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
            
            # Extract advantage/disadvantage count if specified (e.g., "advantage 2")
            adv_count = 1
            if has_advantage:
                adv_match = re.search(r'advantage\s+(\d+)', expression, re.IGNORECASE)
                if adv_match:
                    adv_count = int(adv_match.group(1))
                breakdown.advantage_count = adv_count  # Store for formatting
            
            disadv_count = 1
            if has_disadvantage:
                disadv_match = re.search(r'disadvantage\s+(\d+)', expression, re.IGNORECASE)
                if disadv_match:
                    disadv_count = int(disadv_match.group(1))
                breakdown.advantage_count = disadv_count  # Store for formatting
    
            if has_advantage and has_disadvantage:
                raise ValueError("Cannot have both advantage and disadvantage")
    
            # Handle multihit with advantage/disadvantage - THE FIXED VERSION
            if multihit_match and (has_advantage or has_disadvantage):
                modifier = int(multihit_match.group(1))
                
                # ===== FIX FOR MULTIHIT WITH ADVANTAGE =====
                # With multihit, we roll multiple separate attacks, not multiple dice for one attack.
                # For example, with 3d20 multihit advantage, we want 3 separate advantage rolls.
                
                # First, determine advantage dice count
                advantage_dice = adv_count + 1 if has_advantage else disadv_count + 1
                
                # For each multihit (count), roll advantage_dice and select best/worst
                all_rolls = []
                selected_rolls = []
                
                for _ in range(count):
                    # Roll advantage_dice for each attack
                    hit_rolls = [random.randint(1, sides) for _ in range(advantage_dice)]
                    all_rolls.extend(hit_rolls)
                    
                    # Select highest or lowest based on advantage/disadvantage
                    if has_advantage:
                        selected = max(hit_rolls)
                    else:  # disadvantage
                        selected = min(hit_rolls)
                    
                    selected_rolls.append(selected)
                
                # Store all rolls and selected rolls
                breakdown.rolls = all_rolls
                breakdown.pre_advantage_rolls = selected_rolls
                
                # Apply modifier and stats to each selected roll
                modified_rolls = [r + modifier + total_stat_mod for r in selected_rolls]
                
                # Store results
                breakdown.modified_rolls = modified_rolls
                breakdown.multihit_results = modified_rolls
                breakdown.final_result = sum(modified_rolls)
                breakdown.roll_type = 'multihit'
                breakdown.advantage_state = 'advantage' if has_advantage else 'disadvantage'
            
            # Handle regular advantage/disadvantage (not multihit)
            elif has_advantage or has_disadvantage:
                # Roll adv_count+1 dice instead of always 2
                dice_to_roll = adv_count + 1 if has_advantage else disadv_count + 1
                rolls = [random.randint(1, sides) for _ in range(dice_to_roll)]
                breakdown.rolls = rolls.copy()
                
                selected_roll = max(rolls) if has_advantage else min(rolls)
                breakdown.selected_roll = selected_roll
                breakdown.modified_rolls = [selected_roll + total_stat_mod]  # Apply stat mod
                breakdown.final_result = selected_roll + total_stat_mod
                breakdown.advantage_state = 'advantage' if has_advantage else 'disadvantage'
                breakdown.roll_type = breakdown.advantage_state
    
            # Handle regular multihit
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
            
            # Handle multihit with advantage/disadvantage
            if breakdown.advantage_state and breakdown.multihit_results:
                if hasattr(breakdown, 'pre_advantage_rolls') and breakdown.pre_advantage_rolls:
                    # Show the selected rolls (post-advantage, pre-modifier)
                    parts.append(f" → [{','.join(map(str, breakdown.pre_advantage_rolls))}]")
                    
                    # Include advantage count if > 1
                    adv_display = f"{breakdown.advantage_state}"
                    if breakdown.advantage_count > 1:
                        adv_display += f" {breakdown.advantage_count}"
                    parts.append(f" → [{','.join(map(str, breakdown.multihit_results))}] ({adv_display})")
                else:
                    # Fallback for compatibility with older data
                    parts.append(f" → [{','.join(map(str, breakdown.multihit_results))}] ({breakdown.advantage_state})")
            
            # Regular advantage/disadvantage (not multihit)
            elif breakdown.advantage_state and not breakdown.multihit_results:
                # Include advantage count if > 1
                adv_display = f"{breakdown.advantage_state}"
                if breakdown.advantage_count > 1:
                    adv_display += f" {breakdown.advantage_count}"
                parts.append(f" → {breakdown.selected_roll} ({adv_display})")
            
            # Add multihit results (regular multihit)
            elif breakdown.multihit_results:
                parts.append(f" → [{','.join(map(str, breakdown.multihit_results))}]")
            
            # Add remaining modifiers
            if breakdown.modifiers_applied:
                parts.extend(breakdown.modifiers_applied)
            
            # Add final result for normal rolls (non-multihit, non-advantage)
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
            
            # If we used any next_roll_only effects, save the character
            if character and hasattr(character, 'custom_parameters'):
                roll_modifiers = character.custom_parameters.get('roll_modifiers', [])
                # Check if any were marked as used
                used_effects = [mod for mod in roll_modifiers if hasattr(mod, 'used') and mod.used]
                if used_effects:
                    # Remove used one-time effects
                    character.custom_parameters['roll_modifiers'] = [
                        mod for mod in roll_modifiers 
                        if not (hasattr(mod, 'next_roll_only') and 
                               mod.next_roll_only and 
                               hasattr(mod, 'used') and 
                               mod.used)
                    ]
                    
                    # If this was implemented in a command context, we'd save the character here
                    # but since we're in calculator.py, we'll let the calling code handle that
                    
            return breakdown.final_result, formatted, detailed
            
        except Exception as e:
            logger.error(f"Error calculating complex expression: {e}")
            raise ValueError(f"Error: {str(e)}")