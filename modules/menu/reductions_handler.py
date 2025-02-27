"""Handles display of character resistances and vulnerabilities."""

from discord import Embed, Color
from typing import Dict, List, Tuple, Any

class ReductionsHandler:
    @staticmethod
    def create_reductions_embed(character_name: str, 
                            natural_res: Dict[str, int],
                            natural_vul: Dict[str, int],
                            effect_res: Dict[str, int],
                            effect_vul: Dict[str, int]) -> Embed:
        """Create embed showing all resistances and vulnerabilities"""
        embed = Embed(
            title=f"{character_name}'s Damage Modifiers",
            color=Color.blue()
        )

        # Natural Resistances
        if natural_res:
            natural_res_text = "\n".join([
                f"🛡️ `{dtype}`: `{pct}%`"
                for dtype, pct in natural_res.items()
            ])
            embed.add_field(
                name="Natural Resistances",
                value=natural_res_text,
                inline=False
            )

        # Effect-based Resistances
        if effect_res:
            effect_res_text = "\n".join([
                f"✨ `{dtype}`: `{pct}%`"
                for dtype, pct in effect_res.items()
            ])
            embed.add_field(
                name="Temporary Resistances",
                value=effect_res_text,
                inline=False
            )

        # Natural Vulnerabilities
        if natural_vul:
            natural_vul_text = "\n".join([
                f"⚔️ `{dtype}`: `{pct}%`"
                for dtype, pct in natural_vul.items()
            ])
            embed.add_field(
                name="Natural Vulnerabilities",
                value=natural_vul_text,
                inline=False
            )

        # Effect-based Vulnerabilities
        if effect_vul:
            effect_vul_text = "\n".join([
                f"✨ `{dtype}`: `{pct}%`"
                for dtype, pct in effect_vul.items()
            ])
            embed.add_field(
                name="Temporary Vulnerabilities",
                value=effect_vul_text,
                inline=False
            )

        # If no modifiers exist
        if not any([natural_res, natural_vul, effect_res, effect_vul]):
            embed.description = "No damage modifiers active."

        return embed