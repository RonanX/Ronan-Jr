"""Commands for managing natural resistances and vulnerabilities."""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
import logging

from utils.error_handler import handle_error
from core.effects.combat import DamageType

logger = logging.getLogger(__name__)

class NaturalDefenseCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="natural_resistance")
    @app_commands.describe(
        character="Character to modify",
        damage_type="Type of damage to add resistance to",
        percentage="Resistance percentage",
        remove="Remove this natural resistance instead of adding it"
    )
    async def natural_resistance(
        self,
        interaction: discord.Interaction,
        character: str,
        damage_type: str,
        percentage: int = 50,
        remove: bool = False
    ):
        """Add or remove natural damage resistance"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            damage_type = str(DamageType.from_string(damage_type))

            if remove:
                if damage_type in char.defense.natural_resistances:
                    del char.defense.natural_resistances[damage_type]
                    await self.bot.db.save_character(char)
                    await interaction.followup.send(
                        f"🛡️ `Removed natural {damage_type} resistance from {character}` 🛡️"
                    )
                else:
                    await interaction.followup.send(
                        f"❌ `{character} doesn't have natural {damage_type} resistance` ❌"
                    )
            else:
                char.defense.natural_resistances[damage_type] = percentage
                await self.bot.db.save_character(char)
                await interaction.followup.send(
                    f"🛡️ `Added {percentage}% natural {damage_type} resistance to {character}` 🛡️"
                )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="natural_vulnerability")
    @app_commands.describe(
        character="Character to modify",
        damage_type="Type of damage to add vulnerability to",
        percentage="Vulnerability percentage",
        remove="Remove this natural vulnerability instead of adding it"
    )
    async def natural_vulnerability(
        self,
        interaction: discord.Interaction,
        character: str,
        damage_type: str,
        percentage: int = 50,
        remove: bool = False
    ):
        """Add or remove natural damage vulnerability"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            damage_type = str(DamageType.from_string(damage_type))

            if remove:
                if damage_type in char.defense.natural_vulnerabilities:
                    del char.defense.natural_vulnerabilities[damage_type]
                    await self.bot.db.save_character(char)
                    await interaction.followup.send(
                        f"⚔️ `Removed natural {damage_type} vulnerability from {character}` ⚔️"
                    )
                else:
                    await interaction.followup.send(
                        f"❌ `{character} doesn't have natural {damage_type} vulnerability` ❌"
                    )
            else:
                char.defense.natural_vulnerabilities[damage_type] = percentage
                await self.bot.db.save_character(char)
                await interaction.followup.send(
                    f"⚔️ `Added {percentage}% natural {damage_type} vulnerability to {character}` ⚔️"
                )

        except Exception as e:
            await handle_error(interaction, e)

async def setup(bot):
    await bot.add_cog(NaturalDefenseCommands(bot))