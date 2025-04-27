"""
Attack roll processing system.
Handles attack rolls against targets, including multi-target and AoE variants.
"""

from typing import List, Optional, Dict, Any, Tuple, Set
from dataclasses import dataclass
import logging
import re
from discord import Embed, Color
from .calculator import DiceCalculator
from .target_handler import TargetHandler, AttackResult, DamageComponent
from core.character import StatType
from core.effects.move.combat import BonusOnHit

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
    bonus_on_hit: Optional[BonusOnHit] = None  # Added BonusOnHit parameter

class AttackCalculator:
    """Handles attack rolls with targeting"""
    
    @staticmethod
    def format_attack_output(
        roll_formatted: str,
        attack_results: List[AttackResult],
        is_multi: bool = False,
        reason: Optional[str] = None,
        aoe_mode: str = 'single',
        bonus_message: Optional[str] = None
    ) -> str:
        """Format attack output with consistent styling"""
        logger.debug(f"\nFormatting attack output:")
        logger.debug(f"AoE Mode: {aoe_mode}")
        logger.debug(f"Is Multi: {is_multi}")
        logger.debug(f"Results: {len(attack_results)} targets")

        # Properly extract the roll expression from formatted output
        # This fixes the double dice emoji issue by extracting only what we need
        if roll_formatted.startswith('`🎲'):
            # Extract the content between the backticks, removing the emoji
            roll_content = roll_formatted.strip('`').lstrip('🎲 ')
        else:
            roll_content = roll_formatted
        
        # Handle no targets case (untargeted roll)
        if not attack_results or (len(attack_results) == 1 and not attack_results[0].target_name):
            parts = [f"`🎲 {roll_content}"]
            if reason:
                parts[0] += f" | 📝 {reason}"
            parts[0] += "`"
            return "".join(parts)

        # Handle multihit attack (multiple rolls against single target)
        if is_multi:
            # Multi-target mode with individual results
            hits = sum(1 for r in attack_results if r.hit)
            crits = sum(1 for r in attack_results if r.is_crit)
            
            # Start the output with the roll result - include original roll expression with result
            parts = [f"`🎲 {roll_content}"]
            
            # Add hit summary
            hit_parts = [f"Hits: {hits}/{len(attack_results)}"]
            if crits:
                hit_parts.append(f"💥 {crits} CRIT{'S' if crits > 1 else ''}!")
                
            # Add target name if all results have same target
            if all(r.target_name == attack_results[0].target_name for r in attack_results):
                hit_parts.append(f"→ {attack_results[0].target_name}")
                
            parts[0] += f" | {' '.join(hit_parts)}"
            
            # Calculate total damage by type
            if hits > 0:
                damage_by_type = {}
                for result in attack_results:
                    if result.hit and result.damage_rolls:
                        for damage, type_ in result.damage_rolls:
                            damage_by_type[type_] = damage_by_type.get(type_, 0) + damage
                
                # Show total damage if any
                if damage_by_type:
                    damage_parts = []
                    for type_, total in damage_by_type.items():
                        emoji = DAMAGE_TYPE_EMOJIS.get(type_.lower(), '⚔️')
                        damage_parts.append(f"{emoji} {total} {type_}")
                    parts[0] += f" | {' + '.join(damage_parts)}"
            
            # Add reason if provided
            if reason:
                parts[0] += f" | 📝 {reason}"
                
            # Close the formatting
            parts[0] += "`"
        
        # Handle AoE Single Mode (one roll applied to multiple targets)
        elif aoe_mode == 'single':
            # Get compact target results
            target_results = []
            for result in attack_results:
                icon = "💥" if result.is_crit else "✅" if result.hit else "❌"
                target_results.append(f"{result.target_name} {icon}")
            
            # Format the output - include original roll expression with result
            parts = [f"`🎲 {roll_content} | 🎯 {', '.join(target_results)}"]
            
            # Add damage only if at least one hit
            if any(r.hit for r in attack_results) and attack_results[0].damage_rolls:
                # Use the first hit's damage info since it's the same for all in single mode
                result = next((r for r in attack_results if r.hit), None)
                if result:
                    damage_parts = []
                    for dmg, type_ in result.damage_rolls:
                        emoji = DAMAGE_TYPE_EMOJIS.get(type_.lower(), '⚔️')
                        damage_parts.append(f"{emoji} {dmg} {type_}")
                    
                    # Show damage sum if multiple types
                    damage_str = ' + '.join(damage_parts)
                    if len(result.damage_rolls) > 1:
                        damage_str += f" = {result.total_damage} total"
                    parts[0] += f" | {damage_str} each"
            
            # Add reason if provided
            if reason:
                parts[0] += f" | 📝 {reason}"
                
            # Close the formatting
            parts[0] += "`"
        
        # Handle AoE Multi Mode (separate roll for each target) 
        else:  # aoe_mode == 'multi'
            # Header with hit summary - include original roll expression with result
            hits = sum(1 for r in attack_results if r.hit)
            crits = sum(1 for r in attack_results if r.is_crit)
            
            parts = [f"`🎲 {roll_content} | Hits: {hits}/{len(attack_results)}"]
            if crits > 0:
                parts[0] += f" | 💥 {crits} CRIT{'S' if crits > 1 else ''}"
            parts[0] += "`"
            
            # Add individual target results as bullets with their own formatting
            for result in attack_results:
                icon = "💥" if result.is_crit else "✅" if result.hit else "❌"
                target_line = [f"\n• `🎯 {result.target_name} | [{result.natural_roll}]+{result.attack_roll - result.natural_roll} = {result.attack_roll} {icon} AC {result.ac}"]
                
                if result.hit and result.damage_rolls:
                    damage_parts = []
                    for dmg, type_ in result.damage_rolls:
                        emoji = DAMAGE_TYPE_EMOJIS.get(type_.lower(), '⚔️')
                        damage_parts.append(f"{emoji} {dmg} {type_}")
                    
                    damage_str = ' + '.join(damage_parts)
                    if len(result.damage_rolls) > 1:
                        damage_str += f" = {result.total_damage} total"
                    target_line[0] += f" | {damage_str}"
                elif not result.hit:
                    target_line[0] += " | MISS"
                    
                target_line[0] += "`"
                parts.append("".join(target_line))
            
            # Add total damage if any hits
            if hits > 0:
                total_damage = sum(r.total_damage for r in attack_results if r.hit)
                if total_damage > 0:
                    parts.append(f"\n`Total Damage: {total_damage}" + (f" | 📝 {reason}`" if reason else "`"))
            # Add reason if not already added with total damage
            elif reason and not any(f"📝 {reason}" in p for p in parts):
                parts.append(f"\n`📝 {reason}`")
        
        # Add bonus message if provided - directly add without bullet point
        if bonus_message:
            parts.append(f"\n{bonus_message}")
            
        return "".join(parts)

    @staticmethod
    async def process_attack(params: AttackParameters) -> Tuple[str, Dict[str, Any]]:
        """
        Process an attack roll with targeting
        
        Returns:
          Tuple of (formatted_message, hit_results_dict) where:
          - formatted_message is the string to display
          - hit_results_dict is a dictionary of target names to hit data
        """
        try:
            # Initialize bonus tracker if provided
            bonus_on_hit = params.bonus_on_hit or BonusOnHit()
            
            # Validate parameters
            if 'multihit' in params.roll_expression.lower() and params.aoe_mode == 'multi':
                # Instead of raising an exception, return a formatted error message
                # and an empty hit data dictionary
                error_msg = "🚫 `Incompatible options: Multihit attacks cannot be used with multiple targets in 'multi' mode. Use 'single' mode instead.`"
                return error_msg, {}

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
                    # Return empty dict as hit results
                    return message, {}
                    
                else:
                    # Just a regular roll
                    total, formatted, _ = DiceCalculator.calculate_complex(
                        params.roll_expression,
                        params.character,
                        concise=True
                    )
                    # Return empty dict as hit results
                    return formatted, {}

            # Handle multihit attack
            if 'multihit' in params.roll_expression.lower():
                # Reset hit bonus tracker for new attack
                bonus_on_hit.reset()
                
                attack_total, attack_formatted, _ = DiceCalculator.calculate_complex(
                    params.roll_expression,
                    params.character,
                    concise=True
                )
                
                results = []
                hit_data = {}
                
                # Each roll in multihit is a separate attack
                rolls = TargetHandler.extract_all_rolls(attack_formatted)
                modified = TargetHandler.extract_modified_rolls(attack_formatted)
                
                # Ensure we have valid rolls extracted
                if not modified and len(rolls) > 0:
                    # If we couldn't extract modified rolls, use the original with stats
                    if params.character:
                        # Get appropriate stat modifier
                        stat_mod = 0
                        for stat_name in ["str", "dex", "int", "wis", "cha", "con"]:
                            if stat_name in params.roll_expression.lower():
                                stat_type = next((s for s in StatType if s.value.startswith(stat_name)), None)
                                if stat_type:
                                    value = params.character.stats.modified[stat_type]
                                    stat_mod = (value - 10) // 2
                                    break
                        
                        # Apply stat modifier to each roll
                        modified = [roll + stat_mod for roll in rolls]
                    else:
                        modified = rolls
                
                # Extract multihit modifier if present
                multihit_mod = 0
                multihit_match = re.search(r'multihit\s+(\d+)', params.roll_expression, re.IGNORECASE)
                if multihit_match:
                    multihit_mod = int(multihit_match.group(1))
                
                # Create a result for each hit
                for i, (roll, mod_roll) in enumerate(zip(rolls, modified)):
                    # Apply the multihit modifier
                    mod_roll += multihit_mod
                    
                    hit = mod_roll >= params.targets[0].defense.current_ac
                    is_crit = roll >= params.crit_range
                    
                    # Register hit for bonus tracking
                    if hit:
                        bonus_on_hit.register_hit()
                    
                    # Calculate damage if hit
                    damage_rolls = None
                    total_damage = 0
                    if hit and params.damage_str:
                        damage_components = TargetHandler.parse_damage_string(params.damage_str)
                        for comp in damage_components:
                            comp.character = params.character
                        damage_rolls = TargetHandler.calculate_damage(damage_components, is_crit)
                        total_damage = sum(dmg for dmg, _ in damage_rolls)
                    
                    result = AttackResult(
                        target_name=params.targets[0].name,
                        attack_roll=mod_roll,
                        natural_roll=roll,
                        ac=params.targets[0].defense.current_ac,
                        hit=hit,
                        is_crit=is_crit,
                        damage_rolls=damage_rolls,
                        total_damage=total_damage
                    )
                    
                    results.append(result)
                    
                    # Store in hit data for bonus tracking
                    if hit:
                        if params.targets[0].name not in hit_data:
                            hit_data[params.targets[0].name] = {'hit': True, 'damage': total_damage, 'is_crit': is_crit}
                
                # Apply bonus based on hits
                bonus_message = None
                if params.character and bonus_on_hit.has_any_bonuses():
                    bonus_message = bonus_on_hit.apply_bonuses(params.character)
                
                # Create summary message
                message = AttackCalculator.format_attack_output(
                    attack_formatted,
                    results,
                    True,
                    params.reason,
                    bonus_message=bonus_message
                )
                
                return message, hit_data

            # AoE single mode (one roll against multiple targets)
            if params.aoe_mode == 'single':
                # Reset hit bonus tracker for new attack
                bonus_on_hit.reset()
                
                # Make a single attack roll for all targets
                attack_total, attack_formatted, _ = DiceCalculator.calculate_complex(
                    params.roll_expression,
                    params.character,
                    concise=True
                )
                
                # Get natural roll
                natural_roll = TargetHandler.extract_natural_roll(attack_formatted)
                is_crit = natural_roll >= params.crit_range
                
                results = []
                hit_data = {}
                
                for target in params.targets:
                    hit = attack_total >= target.defense.current_ac
                    
                    # Register hit for bonus tracking
                    if hit:
                        bonus_on_hit.register_hit()
                    
                    # Calculate damage if hit
                    damage_rolls = None
                    total_damage = 0
                    if hit and params.damage_str:
                        damage_components = TargetHandler.parse_damage_string(params.damage_str)
                        for comp in damage_components:
                            comp.character = params.character
                        damage_rolls = TargetHandler.calculate_damage(damage_components, is_crit)
                        total_damage = sum(dmg for dmg, _ in damage_rolls)
                    
                    result = AttackResult(
                        target_name=target.name,
                        attack_roll=attack_total,
                        natural_roll=natural_roll,
                        ac=target.defense.current_ac,
                        hit=hit,
                        is_crit=is_crit,
                        damage_rolls=damage_rolls,
                        total_damage=total_damage
                    )
                    
                    results.append(result)
                    
                    # Store in hit data for bonus tracking
                    if hit:
                        hit_data[target.name] = {'hit': True, 'damage': total_damage, 'is_crit': is_crit}
                
                # Apply bonus based on hits
                bonus_message = None
                if params.character and bonus_on_hit.has_any_bonuses():
                    bonus_message = bonus_on_hit.apply_bonuses(params.character)
                
                message = AttackCalculator.format_attack_output(
                    attack_formatted,
                    results,
                    False,
                    params.reason,
                    'single',
                    bonus_message=bonus_message
                )
                
                return message, hit_data
                
            # AoE multi mode (separate roll for each target)
            else:  # params.aoe_mode == 'multi'
                # Reset hit bonus tracker for new attack
                bonus_on_hit.reset()
                
                results = []
                hit_data = {}
                all_attack_formatted = []
                
                # Make separate roll for each target and store the formatted results
                for target in params.targets:
                    # Make separate attack roll for each target
                    attack_total, attack_formatted, _ = DiceCalculator.calculate_complex(
                        params.roll_expression,
                        params.character,
                        concise=True
                    )
                    all_attack_formatted.append(attack_formatted)
                    
                    # Get natural roll
                    natural_roll = TargetHandler.extract_natural_roll(attack_formatted)
                    is_crit = natural_roll >= params.crit_range
                    
                    hit = attack_total >= target.defense.current_ac
                    
                    # Register hit for bonus tracking
                    if hit:
                        bonus_on_hit.register_hit()
                    
                    # Calculate damage if hit
                    damage_rolls = None
                    total_damage = 0
                    if hit and params.damage_str:
                        damage_components = TargetHandler.parse_damage_string(params.damage_str)
                        for comp in damage_components:
                            comp.character = params.character
                        damage_rolls = TargetHandler.calculate_damage(damage_components, is_crit)
                        total_damage = sum(dmg for dmg, _ in damage_rolls)
                    
                    result = AttackResult(
                        target_name=target.name,
                        attack_roll=attack_total,
                        natural_roll=natural_roll,
                        ac=target.defense.current_ac,
                        hit=hit,
                        is_crit=is_crit,
                        damage_rolls=damage_rolls,
                        total_damage=total_damage
                    )
                    
                    results.append(result)
                    
                    # Store in hit data for bonus tracking
                    if hit:
                        hit_data[target.name] = {'hit': True, 'damage': total_damage, 'is_crit': is_crit}
                
                # Apply bonus based on hits
                bonus_message = None
                if params.character and bonus_on_hit.has_any_bonuses():
                    bonus_message = bonus_on_hit.apply_bonuses(params.character)
                
                # Use first roll for the header, but each target will show their specific roll
                message = AttackCalculator.format_attack_output(
                    all_attack_formatted[0] if all_attack_formatted else params.roll_expression,
                    results,
                    False,
                    params.reason,
                    'multi',
                    bonus_message=bonus_message
                )
                
                return message, hit_data

        except Exception as e:
            logger.error(f"Error in process_attack: {str(e)}", exc_info=True)
            return str(e), {}