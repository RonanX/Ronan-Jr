"""
Handles display of character resistances and vulnerabilities
"""

from typing import Dict, List, Optional
from discord import Embed, ButtonStyle
from discord.ui import View, Button
from core.character import Character
from core.effects.combat import DamageType

class ResistanceViewer:
    """Shows detailed resistance information for a character"""
    
    @staticmethod
    def create_defense_embed(character: Character) -> Embed:
        """Create an embed showing all character defenses"""
        embed = Embed(
            title=f"{character.name}'s Defenses",
            color=0x3498db  # Blue color
        )
        
        # Get all damage types the character has any interaction with
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
                    text = f"**{dmg_type.title()}:** {total}%"
                    if natural > 0 and effect > 0:
                        text += f" (Natural: {natural}% + Effect: {effect}%)"
                    elif natural > 0:
                        text += f" (Natural)"
                    elif effect > 0:
                        text += f" (Effect)"
                    resistance_text.append(text)
                    
            if resistance_text:
                embed.add_field(
                    name="🛡️ Resistances",
                    value="\n".join(resistance_text),
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
                    text = f"**{dmg_type.title()}:** {total}%"
                    if natural > 0 and effect > 0:
                        text += f" (Natural: {natural}% + Effect: {effect}%)"
                    elif natural > 0:
                        text += f" (Natural)"
                    elif effect > 0:
                        text += f" (Effect)"
                    vulnerability_text.append(text)
                    
            if vulnerability_text:
                embed.add_field(
                    name="⚔️ Vulnerabilities",
                    value="\n".join(vulnerability_text),
                    inline=False
                )
                
        # Add base defensive stats
        defense_info = [
            f"**Base AC:** {character.defense.base_ac}",
            f"**Current AC:** {character.defense.current_ac}"
        ]
        
        if character.defense.ac_modifiers:
            mods = [str(mod) for mod in character.defense.ac_modifiers]
            defense_info.append(f"**AC Modifiers:** {', '.join(mods)}")
            
        embed.add_field(
            name="🛡️ Defensive Stats",
            value="\n".join(defense_info),
            inline=False
        )
        
        # Add empty field if no resistances or vulnerabilities
        if not resistance_types and not vulnerability_types:
            embed.add_field(
                name="No Defenses",
                value="This character has no active resistances or vulnerabilities.",
                inline=False
            )
            
        return embed