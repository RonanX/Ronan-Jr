# Import Note: Update main.py to remove resistance_viewer import
# and update any command files to reference DefenseHandler instead

"""
Unified defense handler that manages resistances, vulnerabilities, and AC display.
Handles all defense-related UI and calculations.

Features:
- Defense stat tracking and display
- Resistance/vulnerability management
- Damage calculation formatting
- Real-time defense updates
"""

from discord import Embed, Color
from typing import Dict, List, Optional, Tuple, Any
import logging
from utils.constants import EMOJI_MAP
from utils.formatting import (
    format_modifier, format_resources,
    format_effect_list, format_stat_block
)

logger = logging.getLogger(__name__)

class DefenseHandler:
    """Handles all defense-related UI and calculations"""

    # Damage type emojis - could be moved to constants.py
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
    def create_defense_embed(character: 'Character') -> Embed:
        """Create comprehensive defense info embed"""
        embed = Embed(
            title=f"{character.name}'s Defenses",
            color=Color.blue()
        )

        # Core Defense Stats
        core_stats = []
        
        # Base and current AC with modifiers
        ac_text = f"**Base AC:** {character.defense.base_ac}"
        if character.defense.current_ac != character.defense.base_ac:
            ac_text += f"\n**Current AC:** {character.defense.current_ac}"
            if character.defense.ac_modifiers:
                ac_text += f" ({', '.join(f'{mod:+d}' for mod in character.defense.ac_modifiers)})"
        core_stats.append(ac_text)
        
        # Temporary HP if any
        if character.resources.current_temp_hp > 0:
            core_stats.append(
                f"**Temporary HP:** {character.resources.current_temp_hp}/{character.resources.max_temp_hp}"
            )
        
        if core_stats:
            embed.add_field(
                name="🛡️ Core Defenses",
                value="\n".join(core_stats),
                inline=False
            )

        # Get all damage types with any interaction
        resistance_types = set(character.defense.natural_resistances.keys()) | \
                         set(character.defense.damage_resistances.keys())
        vulnerability_types = set(character.defense.natural_vulnerabilities.keys()) | \
                            set(character.defense.damage_vulnerabilities.keys())

        # Format resistances
        if resistance_types:
            resistance_text = []
            for dmg_type in sorted(resistance_types):
                natural = character.defense.natural_resistances.get(dmg_type, 0)
                effect = character.defense.damage_resistances.get(dmg_type, 0)
                total = character.defense.get_total_resistance(dmg_type)
                
                if natural > 0 or effect > 0:
                    text = [f"**{dmg_type.title()}:** {total}%"]
                    
                    # Add breakdown if multiple sources
                    if natural > 0 and effect > 0:
                        text.append(f"• Natural: {natural}%")
                        text.append(f"• Effect: {effect}%")
                    elif natural > 0:
                        text.append("• Natural resistance")
                    elif effect > 0:
                        text.append("• From effects")
                        
                    resistance_text.append("\n".join(text))
                    
            if resistance_text:
                embed.add_field(
                    name="🛡️ Resistances",
                    value="\n\n".join(resistance_text),
                    inline=False
                )

        # Format vulnerabilities
        if vulnerability_types:
            vulnerability_text = []
            for dmg_type in sorted(vulnerability_types):
                natural = character.defense.natural_vulnerabilities.get(dmg_type, 0)
                effect = character.defense.damage_vulnerabilities.get(dmg_type, 0)
                total = character.defense.get_total_vulnerability(dmg_type)
                
                if natural > 0 or effect > 0:
                    text = [f"**{dmg_type.title()}:** {total}%"]
                    
                    # Add breakdown if multiple sources
                    if natural > 0 and effect > 0:
                        text.append(f"• Natural: {natural}%")
                        text.append(f"• Effect: {effect}%")
                    elif natural > 0:
                        text.append("• Natural vulnerability")
                    elif effect > 0:
                        text.append("• From effects")
                        
                    vulnerability_text.append("\n".join(text))
                    
            if vulnerability_text:
                embed.add_field(
                    name="⚔️ Vulnerabilities",
                    value="\n\n".join(vulnerability_text),
                    inline=False
                )

        # Add empty field if no defenses
        if not resistance_types and not vulnerability_types:
            embed.add_field(
                name="No Special Defenses",
                value="This character has no active resistances or vulnerabilities.",
                inline=False
            )

        return embed

    @staticmethod
    def format_damage_message(
        character_name: str,
        damage_results: List[Tuple[int, str, int, int, int]],  # [(original, type, final, absorbed, increase)]
        final_hp: int,
        max_hp: int
    ) -> str:
        """
        Create a natural-language damage message.
        Returns a single line describing what happened.
        """
        messages = []
        total_absorbed = sum(absorbed for _, _, _, absorbed, _ in damage_results)
        total_original = sum(orig for orig, _, _, _, _ in damage_results)
        total_final = sum(final for _, _, final, _, _ in damage_results)
        
        # Start with character name
        msg = [f"`{character_name}`"]
        
        # Single damage type case
        if len(damage_results) == 1:
            orig, dmg_type, final, absorbed, increase = damage_results[0]
            
            if absorbed > 0:
                msg.append(f"took `{orig}` {dmg_type} damage")
                msg.append(f"`{absorbed}` was absorbed by their shield")
                if final != (orig - absorbed):
                    if increase > 0:
                        msg.append(f"and the rest was amplified to `{final}` by their vulnerability")
                    else:
                        msg.append(f"and the rest was reduced to `{final}` by their resistance")
            else:
                msg.append(f"took `{orig}` {dmg_type} damage")
                if final != orig:
                    if increase > 0:
                        msg.append(f"amplified to `{final}` by their vulnerability")
                    else:
                        msg.append(f"reduced to `{final}` by their resistance")
        
        # Multiple damage types
        else:
            damages = [f"`{orig}` {dtype}" for orig, dtype, _, _, _ in damage_results]
            msg.append(f"took {' and '.join(damages)} damage")
            
            if total_absorbed > 0:
                msg.append(f"`{total_absorbed}` was absorbed by their shield")
            
            if total_final != (total_original - total_absorbed):
                msg.append(f"for a total of `{total_final}` after resistances and vulnerabilities")
        
        # Add final HP
        msg.append(f"(`{final_hp}/{max_hp}` HP)")
        
        return " • ".join(msg)

    @staticmethod
    def format_resistance_output(
        resistance_type: str,
        percentage: int,
        is_natural: bool = False,
        is_vulnerability: bool = False
    ) -> str:
        """Format resistance/vulnerability info for display"""
        type_str = resistance_type.title()
        mod_str = "Vulnerability" if is_vulnerability else "Resistance"
        source_str = "Natural" if is_natural else "Effect"
        
        emoji = DefenseHandler.DAMAGE_EMOJIS.get(resistance_type.lower(), '⚔️')
        return f"{emoji} {type_str} {mod_str} ({percentage}% from {source_str})"

    @staticmethod
    def get_total_defense_info(character: 'Character') -> Dict[str, Any]:
        """Get complete defense information for a character"""
        return {
            'ac': {
                'base': character.defense.base_ac,
                'current': character.defense.current_ac,
                'modifiers': character.defense.ac_modifiers
            },
            'temp_hp': {
                'current': character.resources.current_temp_hp,
                'max': character.resources.max_temp_hp
            },
            'resistances': {
                'natural': character.defense.natural_resistances,
                'effect': character.defense.damage_resistances
            },
            'vulnerabilities': {
                'natural': character.defense.natural_vulnerabilities,
                'effect': character.defense.damage_vulnerabilities
            }
        }