"""
UI handler for displaying character action information.
Currently shows action stars, will later incorporate move system.
"""

from discord import Embed, Color
from core.character import Character
from typing import Optional

class ActionHandler:
    """Handles display of action-related information"""
    
    @staticmethod
    def create_action_embed(character: Character) -> Embed:
        """Create embed showing action information"""
        embed = Embed(
            title=f"{character.name}'s Actions",
            color=Color.blue()
        )

        # Star display
        current_stars = getattr(character.action_stars, 'current_stars', 5)
        max_stars = getattr(character.action_stars, 'max_stars', 5)
        
        # Create visual star meter
        filled_stars = "⭐" * current_stars
        empty_stars = "⚫" * (max_stars - current_stars)
        star_meter = f"{filled_stars}{empty_stars}"
        
        embed.add_field(
            name="Action Stars",
            value=f"`{current_stars}/{max_stars}`\n{star_meter}",
            inline=False
        )

        # Show any used moves (to be expanded later)
        used_moves = getattr(character.action_stars, 'used_moves', [])
        if used_moves:
            moves_list = "\n".join(f"• {move}" for move in used_moves)
            embed.add_field(
                name="Used Moves",
                value=moves_list,
                inline=False
            )
        
        # Placeholder for future move system
        embed.set_footer(text="Full moveset system coming soon!")
        
        return embed