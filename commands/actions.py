"""
Action command system for standard actions.
Provides access to common actions like attack, dodge, dash, etc.
"""

import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class ActionCommands(commands.GroupCog, name="action"):
    """Commands for standard action usage"""
    
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
    
    @app_commands.command(name="use", description="Use a standard action")
    @app_commands.describe(
        character="Character using the action"
    )
    async def use_action(
        self,
        interaction: discord.Interaction,
        character: str
    ):
        """Use a standard action like attack, dodge, etc."""
        try:
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.response.send_message(f"Character '{character}' not found.", ephemeral=True)
                return
            
            # Defer response to avoid timeout
            await interaction.response.defer(ephemeral=True)
                
            # Get the action handler
            from modules.menu.action_handler import ActionHandler
            handler = ActionHandler(self.bot)
            
            # Show the action menu
            await handler.show_action_menu(interaction, char)
            
        except Exception as e:
            logger.error(f"Error in use_action command: {e}", exc_info=True)
            await interaction.followup.send(
                f"An error occurred: {str(e)}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(ActionCommands(bot))