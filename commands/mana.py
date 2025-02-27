"""
Mana manipulation commands.
Handles adding, subtracting, and setting mana points with support for dice rolls.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
import logging
import random

from utils.dice import DiceRoller
from utils.error_handler import handle_error
from modules.combat.logger import CombatEventType

logger = logging.getLogger(__name__)

class ManaCommands(commands.GroupCog, name="mana"):
    """Commands for manipulating character MP"""
    
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
        
        # List of reasons for mana gain for more natural messages
        self.gain_reasons = [
            "from meditation",
            "from mana regeneration",
            "from a magical source",
            "from resting",
            "from an arcane surge",
            "from inner focus"
        ]

    @app_commands.command(name="add")
    @app_commands.describe(
        name="Character receiving MP",
        amount="Amount to add (can use dice and stat modifiers)",
        reason="Reason for adding MP (optional)"
    )
    async def add_mana(
        self,
        interaction: discord.Interaction,
        name: str,
        amount: str,
        reason: Optional[str] = None
    ):
        """Add MP to a character"""
        try:
            # Get character
            char = self.bot.game_state.get_character(name)
            if not char:
                await interaction.response.send_message(
                    f"Character '{name}' not found.",
                    ephemeral=True
                )
                return

            # Roll amount
            mp_amount, roll_exp = DiceRoller.roll_dice(amount, char)
            if mp_amount <= 0:
                await interaction.response.send_message(
                    "Amount must be positive.",
                    ephemeral=True
                )
                return

            # Get combat logger if in combat
            combat_logger = None
            if hasattr(self.bot, 'initiative_tracker'):
                combat_logger = self.bot.initiative_tracker.logger

            if combat_logger:
                combat_logger.snapshot_character_state(char)

            # Apply MP
            old_mp = char.resources.current_mp
            char.resources.current_mp = min(
                char.resources.max_mp,
                char.resources.current_mp + mp_amount
            )
            gained = char.resources.current_mp - old_mp

            # Show roll details privately
            await interaction.response.send_message(
                f"🎲 MP roll: {DiceRoller.format_roll_result(mp_amount, roll_exp)}",
                ephemeral=True
            )

            # Print debug info
            print(f"Command: /mana add {name} {amount}{' --reason \"'+reason+'\"' if reason else ''}")

            # Create main message content
            main_content = f"{char.name} gains {gained} MP"
            
            # Add reason if provided, otherwise occasionally add a natural reason
            if reason:
                main_content += f" {reason}"
            elif random.random() < 0.3:  # 30% chance to add flavor
                main_content += f" {random.choice(self.gain_reasons)}"
            
            # Create human-readable message with backticks
            message = f"💙 `{main_content}`. MP: {char.resources.current_mp}/{char.resources.max_mp}"

            # Log if in combat
            if combat_logger:
                combat_logger.add_event(
                    CombatEventType.RESOURCE_CHANGE,
                    message=f"Gains {gained} MP",
                    character=char.name,
                    details={
                        "resource": "mp",
                        "amount": gained,
                        "old_value": old_mp,
                        "new_value": char.resources.current_mp,
                        "reason": reason
                    }
                )
                combat_logger.snapshot_character_state(char)

            await interaction.channel.send(message)
            await self.bot.db.save_character(char)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="sub")
    @app_commands.describe(
        name="Character losing MP",
        amount="Amount to subtract (can use dice and stat modifiers)",
        reason="Reason for removing MP (optional)"
    )
    async def sub_mana(
        self,
        interaction: discord.Interaction,
        name: str,
        amount: str,
        reason: Optional[str] = None
    ):
        """Subtract MP from a character"""
        try:
            # Get character
            char = self.bot.game_state.get_character(name)
            if not char:
                await interaction.response.send_message(
                    f"Character '{name}' not found.",
                    ephemeral=True
                )
                return

            # Roll amount
            mp_amount, roll_exp = DiceRoller.roll_dice(amount, char)
            if mp_amount <= 0:
                await interaction.response.send_message(
                    "Amount must be positive.",
                    ephemeral=True
                )
                return

            # Get combat logger if in combat
            combat_logger = None
            if hasattr(self.bot, 'initiative_tracker'):
                combat_logger = self.bot.initiative_tracker.logger

            if combat_logger:
                combat_logger.snapshot_character_state(char)

            # Apply MP reduction
            old_mp = char.resources.current_mp
            char.resources.current_mp = max(0, char.resources.current_mp - mp_amount)
            lost = old_mp - char.resources.current_mp

            # Show roll details privately
            await interaction.response.send_message(
                f"🎲 MP roll: {DiceRoller.format_roll_result(mp_amount, roll_exp)}",
                ephemeral=True
            )

            # Print debug info
            print(f"Command: /mana sub {name} {amount}{' --reason \"'+reason+'\"' if reason else ''}")

            # Create main message content
            main_content = f"{char.name} spends {lost} MP"
            
            # Add reason if provided
            if reason:
                main_content += f" on {reason}"
            else:
                main_content += " on an ability"
            
            # Create human-readable message with backticks
            message = f"💙 `{main_content}`. MP: {char.resources.current_mp}/{char.resources.max_mp}"

            # Log if in combat
            if combat_logger:
                combat_logger.add_event(
                    CombatEventType.RESOURCE_CHANGE,
                    message=f"Loses {lost} MP",
                    character=char.name,
                    details={
                        "resource": "mp",
                        "amount": -lost,
                        "old_value": old_mp,
                        "new_value": char.resources.current_mp,
                        "reason": reason
                    }
                )
                combat_logger.snapshot_character_state(char)

            await interaction.channel.send(message)
            await self.bot.db.save_character(char)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="set")
    @app_commands.describe(
        name="Character to modify",
        value="New MP value",
        reason="Reason for setting MP (optional)"
    )
    async def set_mana(
        self,
        interaction: discord.Interaction,
        name: str,
        value: int,
        reason: Optional[str] = None
    ):
        """Set a character's MP to a specific value"""
        try:
            # Get character
            char = self.bot.game_state.get_character(name)
            if not char:
                await interaction.response.send_message(
                    f"Character '{name}' not found.",
                    ephemeral=True
                )
                return

            if value < 0:
                await interaction.response.send_message(
                    "MP value cannot be negative.",
                    ephemeral=True
                )
                return

            # Get combat logger if in combat
            combat_logger = None
            if hasattr(self.bot, 'initiative_tracker'):
                combat_logger = self.bot.initiative_tracker.logger

            if combat_logger:
                combat_logger.snapshot_character_state(char)

            # Set MP
            old_mp = char.resources.current_mp
            char.resources.current_mp = min(char.resources.max_mp, value)
            change = char.resources.current_mp - old_mp

            # Print debug info
            print(f"Command: /mana set {name} {value}{' --reason \"'+reason+'\"' if reason else ''}")

            # Create main message content
            main_content = f"{char.name}'s MP set to {char.resources.current_mp}/{char.resources.max_mp}"
            
            # Add change information if significant
            if change > 0:
                main_content += f" (+{change})"
            elif change < 0:
                main_content += f" ({change})"
            
            # Create human-readable message with backticks
            message = f"💙 `{main_content}`"
                
            # Add reason if provided
            if reason:
                message += f" ({reason})"

            # Log if in combat
            if combat_logger:
                combat_logger.add_event(
                    CombatEventType.RESOURCE_CHANGE,
                    message=f"MP set to {char.resources.current_mp}",
                    character=char.name,
                    details={
                        "resource": "mp",
                        "amount": change,
                        "old_value": old_mp,
                        "new_value": char.resources.current_mp,
                        "reason": reason
                    }
                )
                combat_logger.snapshot_character_state(char)

            await interaction.response.send_message(message)
            await self.bot.db.save_character(char)

        except Exception as e:
            await handle_error(interaction, e)

async def setup(bot):
    await bot.add_cog(ManaCommands(bot))