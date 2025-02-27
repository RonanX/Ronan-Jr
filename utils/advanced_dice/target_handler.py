"""
Target Handler for dice rolling system.
Handles AC checking, damage calculations, and multi-target support.
"""

from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
import re
import logging
from .calculator import DiceCalculator 

logger = logging.getLogger(__name__)

@dataclass
class DamageComponent:
    """Individual damage roll with type"""
    roll_expression: str
    damage_type: str
    character: Optional['Character'] = None

@dataclass
class AttackResult:
    """Result of an attack roll"""
    target_name: str
    attack_roll: int
    natural_roll: int
    ac: int
    hit: bool
    is_crit: bool
    damage_rolls: Optional[List[Tuple[int, str]]] = None  # [(damage, type)]
    total_damage: Optional[int] = None

class TargetHandler:
    """Handles target processing and damage calculations"""

    # Keep the emoji definitions unchanged
    DAMAGE_EMOJIS = {
        'slashing': '🗡️',
        'piercing': '🏹',
        'bludgeoning': '🔨',
        'fire': '🔥',
        'cold': '❄️',
        'lightning': '⚡',
        'thunder': '💥',
        'acid': '💧',
        'poison': '☠️',
        'psychic': '🧠',
        'radiant': '✨',
        'necrotic': '💀',
        'force': '🌟',
        'divine': '🙏',
        'unspecified': '⚔️'
    }

    @staticmethod
    def extract_natural_roll(formatted_str: str) -> int:
        """Extract natural roll from formatted string"""
        # First check for plain numbers (e.g. "15: 15")
        if ":" in formatted_str:
            parts = formatted_str.split(":")
            if len(parts) == 2 and parts[1].strip().isdigit():
                return int(parts[1].strip())
                
        # Then check for roll notation [X]
        match = re.search(r'\[(\d+)(?:,|\])', formatted_str)
        if match:
            return int(match.group(1))
            
        logger.debug(f"No natural roll in expression: {formatted_str}")
        return 0
        
    @staticmethod
    def extract_all_rolls(formatted_str: str) -> List[int]:
        """Extract all original roll values from [X,Y,Z] pattern"""
        match = re.search(r'\[([\d,\s]+)\]', formatted_str)
        if match:
            rolls_str = match.group(1)
            return [int(x.strip()) for x in rolls_str.split(',')]
        return []
        
    @staticmethod
    def extract_modified_rolls(formatted_str: str) -> List[int]:
        """Extract modified roll values after → [X,Y,Z] pattern"""
        match = re.search(r'→\s*\[([\d,\s]+)\]', formatted_str)
        if match:
            rolls_str = match.group(1)
            return [int(x.strip()) for x in rolls_str.split(',')]
        return []

    @staticmethod
    def parse_damage_string(damage_str: str) -> List[DamageComponent]:
        """Parse damage string into components"""
        if not damage_str:
            return []

        components = []
        for part in damage_str.split(','):
            parts = part.strip().rsplit(' ', 1)
            if len(parts) == 2:
                components.append(DamageComponent(
                    roll_expression=parts[0].strip(),
                    damage_type=parts[1].strip().lower()
                ))
            else:
                components.append(DamageComponent(
                    roll_expression=parts[0].strip(),
                    damage_type="unspecified"
                ))
        return components

    @staticmethod
    def format_damage_output(damage_rolls: List[Tuple[int, str]], total: Optional[int] = None) -> str:
        """Format damage output with emoji and optional total"""
        if not damage_rolls:
            return "MISS"

        damage_parts = []
        for damage, type_ in damage_rolls:
            emoji = TargetHandler.DAMAGE_EMOJIS.get(type_.lower(), '⚔️')
            damage_parts.append(f"{emoji} {damage} {type_}")

        result = " + ".join(damage_parts)
        if total is not None and len(damage_rolls) > 1:
            result += f" = {total} total"
        
        return result

    @staticmethod
    def format_attack_output(
        roll_formatted: str,
        attack_results: List[AttackResult],
        is_multi: bool = False,
        reason: Optional[str] = None,
        aoe_mode: str = 'single'
    ) -> str:
        """Format attack output with consistent styling"""
        logger.debug(f"\nFormatting attack output:")
        logger.debug(f"AoE Mode: {aoe_mode}")
        logger.debug(f"Is Multi: {is_multi}")
        logger.debug(f"Results: {len(attack_results)} targets")

        parts = [roll_formatted.rstrip('`')]  # Remove trailing backtick

        # Handle AoE Single Mode
        if aoe_mode == 'single' and not is_multi:
            logger.debug("Processing AoE Single mode")
            
            # Process all targets in a single line
            target_parts = []
            hit_exists = False
            
            for result in attack_results:
                status = "✅" if result.hit else "❌"
                target_parts.append(f"{result.target_name} ({status} AC {result.ac})")
                if result.hit:
                    hit_exists = True

            # Add targets to output
            parts.append(f" | 🎯 {', '.join(target_parts)}")

            # Add damage for hits
            if hit_exists and attack_results[0].damage_rolls:
                damage_str = TargetHandler.format_damage_output(
                    attack_results[0].damage_rolls,
                    attack_results[0].total_damage
                )
                parts.append(f" | {damage_str} each")
            elif not hit_exists:
                parts.append(" | MISS")

        # Handle Multi-hit attacks
        elif is_multi:
            logger.debug("Processing Multi-hit mode")
            hits = sum(1 for r in attack_results if r.hit)
            crits = sum(1 for r in attack_results if r.is_crit)
            
            # Add hit summary
            status_parts = [f"Hits: {hits}/{len(attack_results)}"]
            if crits > 0:
                status_parts.append(f"💥 {crits} CRIT{'S' if crits > 1 else ''}!")
            parts.append(f" | {' '.join(status_parts)} → {attack_results[0].target_name}")

            # Calculate total damage by type
            damage_by_type = {}
            for result in attack_results:
                if result.hit and result.damage_rolls:
                    for damage, type_ in result.damage_rolls:
                        damage_by_type[type_] = damage_by_type.get(type_, 0) + damage

            # Show total damage
            if damage_by_type:
                damage_parts = []
                for type_, total in damage_by_type.items():
                    emoji = TargetHandler.DAMAGE_EMOJIS.get(type_.lower(), '⚔️')
                    damage_parts.append(f"{emoji} {total} {type_}")
                parts.append(f" | {' + '.join(damage_parts)}")

        # Handle AoE Multi Mode
        else:  # aoe_mode == 'multi'
            logger.debug("Processing AoE Multi mode")
            hits = sum(1 for r in attack_results if r.hit)
            parts.append(f" | Hits: {hits}/{len(attack_results)}")

            # Add individual target results
            for result in attack_results:
                status = "💥" if result.is_crit else "✅" if result.hit else "❌"
                target_line = [f"\n• 🎯 {result.target_name} {status} AC {result.ac}"]

                if result.hit and result.damage_rolls:
                    damage_str = TargetHandler.format_damage_output(
                        result.damage_rolls,
                        result.total_damage
                    )
                    target_line.append(f" | {damage_str}")
                else:
                    target_line.append(" | MISS")
                
                parts.append("".join(target_line))

            # Show total damage if any hits
            if hits > 0:
                total_damage = sum(r.total_damage for r in attack_results if r.hit and r.total_damage is not None)
                if total_damage > 0:
                    parts.append(f"\nTotal Damage: {total_damage}")

        # Add reason if provided
        if reason:
            parts.append(f" | 📝 {reason}")

        # Close formatting
        parts.append("`")
        return "".join(parts)

    @staticmethod
    def calculate_damage(
        components: List[DamageComponent],
        is_crit: bool = False
    ) -> List[Tuple[int, str]]:
        """Calculate damage for each component"""
        results = []
        
        for comp in components:
            # Regular damage roll
            total, _, _ = DiceCalculator.calculate_complex(
                comp.roll_expression, 
                comp.character,
                concise=True
            )
            
            # Handle critical hits - roll damage dice again
            if is_crit:
                # Only double the dice part for crits, not static modifiers
                dice_match = re.match(r'(\d+)?[dD](\d+)', comp.roll_expression)
                if dice_match:
                    dice_expr = dice_match.group(0)
                    crit_total, _, _ = DiceCalculator.calculate_complex(
                        dice_expr,
                        comp.character,
                        concise=True
                    )
                    total += crit_total
                
            results.append((total, comp.damage_type))
            
        return results

    @staticmethod
    def process_attack(
        roll_expression: str,
        targets: List['Character'],
        damage_str: Optional[str] = None,
        crit_range: int = 20,
        character: Optional['Character'] = None,
        aoe_mode: str = 'single'
    ) -> Tuple[List[AttackResult], str]:
        """Process a complete attack roll"""
        try:
            logger.debug(f"\nProcessing attack:")
            logger.debug(f"Expression: {roll_expression}")
            logger.debug(f"AoE Mode: {aoe_mode}")
            logger.debug(f"Crit Range: {crit_range}")
            logger.debug(f"Targets: {[t.name for t in targets]}")

            # Get attack roll
            attack_total, formatted_roll, _ = DiceCalculator.calculate_complex(
                roll_expression,
                character,
                concise=True
            )

            # Get natural roll for crit check
            natural_roll = TargetHandler.extract_natural_roll(formatted_roll)
            
            results = []
            for target in targets:
                # Check for critical hit
                is_crit = natural_roll >= crit_range
                hit = attack_total >= target.defense.current_ac or is_crit  # Crits always hit

                # Calculate damage if hit
                damage_rolls = None
                total_damage = 0
                if hit and damage_str:
                    damage_components = TargetHandler.parse_damage_string(damage_str)
                    for comp in damage_components:
                        comp.character = character
                    damage_rolls = TargetHandler.calculate_damage(damage_components, is_crit)
                    total_damage = sum(dmg for dmg, _ in damage_rolls)

                results.append(AttackResult(
                    target_name=target.name,
                    attack_roll=attack_total,
                    natural_roll=natural_roll,
                    ac=target.defense.current_ac,
                    hit=hit,
                    is_crit=is_crit,
                    damage_rolls=damage_rolls,
                    total_damage=total_damage
                ))

            return results, formatted_roll

        except Exception as e:
            logger.error(f"Error processing attack: {e}")
            raise