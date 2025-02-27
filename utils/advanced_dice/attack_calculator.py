"""
Attack roll processing system.
Handles attack rolls against targets, including multi-target and AoE variants.
"""

import logging
import re
from typing import List, Optional, Dict, Any, Tuple, Set
from dataclasses import dataclass
from discord import Embed, Color
from .calculator import DiceCalculator
from .target_handler import TargetHandler, AttackResult, DamageComponent

logger = logging.getLogger(__name__)

DAMAGE_TYPE_EMOJIS = {
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

@dataclass
class AttackParameters:
    """Parameters for an attack roll"""
    roll_expression: str
    character: Optional['Character'] = None
    targets: Optional[List['Character']] = None
    damage_str: Optional[str] = None
    crit_range: int = 20
    aoe_mode: str = 'single'
    reason: Optional[str] = None

class AttackCalculator:
    """Handles attack rolls with targeting"""
    
    @staticmethod
    def format_attack_output(
        roll_formatted: str,
        attack_results: List[AttackResult],
        is_multi: bool = False,
        reason: Optional[str] = None
    ) -> str:
        """Format attack output with consistent styling"""
        # Start with the roll result (preserve stat mods)
        parts = [roll_formatted.rstrip('`')]
        
        if is_multi:
            # Multi-target mode with individual results
            hits = sum(1 for r in attack_results if r.hit)
            crits = sum(1 for r in attack_results if r.is_crit)
            
            # Add hit summary
            hit_parts = [f"Hits: {hits}/{len(attack_results)}"]
            if crits:
                hit_parts.append(f"💥 {crits} CRIT{'S' if crits > 1 else ''}!")
            parts.append(f" | {' '.join(hit_parts)}")
            
            # Add individual target results
            for result in attack_results:
                icon = "💥" if result.is_crit else "✅" if result.hit else "❌"
                target_line = [f"• 🎯 {result.target_name} {icon} AC {result.ac}"]
                
                if result.hit and result.damage_rolls:
                    damage_parts = []
                    for dmg, type_ in result.damage_rolls:
                        emoji = DAMAGE_TYPE_EMOJIS.get(type_.lower(), '⚔️')
                        damage_parts.append(f"{emoji} {dmg} {type_}")
                    
                    # Show individual damage sum if multiple types
                    damage_str = ' + '.join(damage_parts)
                    if len(result.damage_rolls) > 1:
                        damage_str += f" = {result.total_damage} total"
                    target_line.append(f" | {damage_str}")
                elif not result.hit:
                    target_line.append(" | MISS")
                    
                parts.append("\n" + " ".join(target_line))
            
            # Add total damage if any hits
            if hits and any(r.damage_rolls for r in attack_results if r.hit):
                total_damage = sum(r.total_damage for r in attack_results if r.hit)
                parts.append(f"\nTotal Damage: {total_damage}")
                
        else:
            # Single target or AoE single roll
            result = attack_results[0]
            
            # Add hit status and target
            status = []
            if result.hit:
                if result.is_crit:
                    status.append("💥 **CRITICAL HIT!**")
                else:
                    status.append("✅ **HIT!**")
            else:
                status.append("❌ **MISS!**")
            
            if result.target_name:
                status.append(f"→ 🎯 {result.target_name} AC {result.ac}")
            
            parts.append(f" | {' '.join(status)}")
            
            # Add damage for hits
            if result.hit and result.damage_rolls:
                damage_parts = []
                for dmg, type_ in result.damage_rolls:
                    emoji = DAMAGE_TYPE_EMOJIS.get(type_.lower(), '⚔️')
                    damage_parts.append(f"{emoji} {dmg} {type_}")
                
                # Show damage sum if multiple types
                damage_str = ' + '.join(damage_parts)
                if len(result.damage_rolls) > 1:
                    damage_str += f" = {result.total_damage} total"
                parts.append(f" | {damage_str}")
        
        # Add reason if provided
        if reason:
            parts.append(f" | 📝 {reason}")
            
        # Close the formatting
        parts.append("`")
        
        return "".join(parts)

    @staticmethod
    def format_multihit_details(
        results: List[AttackResult],
        damage_str: Optional[str] = None
    ) -> str:
        """Format detailed output for multi-hit attacks"""
        parts = []
        
        # Add hit summary and basic info
        hits = sum(1 for r in results if r.hit)
        crits = sum(1 for r in results if r.is_crit)
        
        summary = [f"Hits: {hits}/{len(results)}"]
        if crits:
            summary.append(f"Crits: {crits}")
        parts.append(" | ".join(summary))
        
        # Add individual hit results
        total_damage = 0
        for i, result in enumerate(results, 1):
            status = "💥 CRIT!" if result.is_crit else "✅ HIT!" if result.hit else "❌ MISS"
            hit_line = [f"Hit {i}: {result.attack_roll} → {status}"]
            
            if result.hit and result.damage_rolls:
                damage_parts = []
                for dmg, type_ in result.damage_rolls:
                    emoji = DAMAGE_TYPE_EMOJIS.get(type_.lower(), '⚔️')
                    damage_parts.append(f"{emoji} {dmg} {type_}")
                hit_line.append(f"Damage: {' + '.join(damage_parts)}")
                total_damage += result.total_damage
                
            parts.append(" | ".join(hit_line))
            
        # Add total damage
        if total_damage > 0:
            parts.append(f"\nTotal Damage: {total_damage}")
            
        return "\n".join(parts)

    @staticmethod
    def process_attack(params: AttackParameters) -> Tuple[str, Optional[Embed]]:
        """Process an attack roll with targeting - Made synchronous for simpler integration"""
        try:
            # Validate parameters
            if 'multihit' in params.roll_expression.lower() and params.aoe_mode == 'multi':
                raise ValueError("Multihit attacks cannot be used with AoE multi mode")

            # Just do a regular roll if no targets
            if not params.targets:
                if params.damage_str:
                    # Attack roll
                    attack_total, attack_formatted, _ = DiceCalculator.calculate_complex(
                        params.roll_expression,
                        params.character,
                        concise=True
                    )
                    
                    # Get natural roll
                    natural_roll = TargetHandler.extract_natural_roll(attack_formatted)
                    is_crit = natural_roll >= params.crit_range
                    
                    # Calculate damage
                    damage_components = TargetHandler.parse_damage_string(params.damage_str)
                    for comp in damage_components:
                        comp.character = params.character
                        
                    damage_rolls = TargetHandler.calculate_damage(damage_components, is_crit)
                    total_damage = sum(dmg for dmg, _ in damage_rolls)
                    
                    # Format attack result
                    attack_result = AttackResult(
                        target_name="",
                        attack_roll=attack_total,
                        natural_roll=natural_roll,
                        ac=0,
                        hit=True,
                        is_crit=is_crit,
                        damage_rolls=damage_rolls,
                        total_damage=total_damage
                    )
                    
                    message = AttackCalculator.format_attack_output(
                        attack_formatted,
                        [attack_result],
                        False,
                        params.reason
                    )
                    return message, None
                    
                else:
                    # Just a regular roll
                    total, formatted, _ = DiceCalculator.calculate_complex(
                        params.roll_expression,
                        params.character,
                        concise=True
                    )
                    return formatted, None

            # Handle multihit attack
            if 'multihit' in params.roll_expression.lower():
                attack_total, attack_formatted, _ = DiceCalculator.calculate_complex(
                    params.roll_expression,
                    params.character,
                    concise=True
                )
                
                results = []
                # Each roll in multihit is a separate attack
                rolls = TargetHandler.extract_all_rolls(attack_formatted)
                modified = TargetHandler.extract_modified_rolls(attack_formatted)
                
                for roll, mod_roll in zip(rolls, modified):
                    hit = mod_roll >= params.targets[0].defense.current_ac
                    is_crit = roll >= params.crit_range
                    
                    # Calculate damage if hit
                    damage_rolls = None
                    total_damage = 0
                    if hit and params.damage_str:
                        damage_components = TargetHandler.parse_damage_string(params.damage_str)
                        for comp in damage_components:
                            comp.character = params.character
                        damage_rolls = TargetHandler.calculate_damage(damage_components, is_crit)
                        total_damage = sum(dmg for dmg, _ in damage_rolls)
                    
                    results.append(AttackResult(
                        target_name=params.targets[0].name,
                        attack_roll=mod_roll,
                        natural_roll=roll,
                        ac=params.targets[0].defense.current_ac,
                        hit=hit,
                        is_crit=is_crit,
                        damage_rolls=damage_rolls,
                        total_damage=total_damage
                    ))
                
                # Create summary message
                message = AttackCalculator.format_attack_output(
                    attack_formatted,
                    results,
                    True,
                    params.reason
                )
                
                # Create detailed embed
                embed = Embed(color=Color.blue())
                embed.add_field(
                    name="🎲 Attack Details",
                    value=AttackCalculator.format_multihit_details(results, params.damage_str),
                    inline=False
                )
                
                return message, embed

            # Normal attack processing
            attack_total, attack_formatted, _ = DiceCalculator.calculate_complex(
                params.roll_expression,
                params.character,
                concise=True
            )
            
            # Get natural roll
            natural_roll = TargetHandler.extract_natural_roll(attack_formatted)
            is_crit = natural_roll >= params.crit_range
            
            results = []
            for target in params.targets:
                hit = attack_total >= target.defense.current_ac
                
                # Calculate damage if hit
                damage_rolls = None
                total_damage = 0
                if hit and params.damage_str:
                    damage_components = TargetHandler.parse_damage_string(params.damage_str)
                    for comp in damage_components:
                        comp.character = params.character
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
            
            # Format message based on mode
            message = AttackCalculator.format_attack_output(
                attack_formatted,
                results,
                params.aoe_mode == 'multi',
                params.reason
            )
            
            return message, None

        except Exception as e:
            logger.error(f"Error in process_attack: {str(e)}", exc_info=True)
            return str(e), None