"""
UI components for the combat system. Handles visual representation of combat state.
"""

import discord
from typing import List, Dict, Optional

class ExpiredEffectEmbed(discord.Embed):
    """Special embed for expired effects"""
    def __init__(self, message: str):
        super().__init__(
            title="Effects Expired",
            description=message,
            color=discord.Color.red()
        )