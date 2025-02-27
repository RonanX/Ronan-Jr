"""
Skill Check Context Menu Handler (src/modules/menu/skill_check_handler.py)

Provides context menu integration for quick skill checks and saves.
Allows right-clicking on character messages to perform various checks.
"""

import discord
from discord import app_commands
from typing import Optional, List
import logging

from core.character import Character, StatType
from commands.skillcheck import (
    CheckType, Advantage, SKILL_ABILITIES,
    build_roll_expression, format_check_result
)
from utils.advanced_dice.calculator import DiceCalculator

logger = logging.getLogger(__name__)

class SkillCheckContextMenu:
    """Handles context menu commands for skill checks"""

    def __init__(self, bot):
        self.bot = bot
        
        # Create context menu commands
        self.save_command = app_commands.ContextMenu(
            name='Make Save',
            callback=self.handle_save_context
        )
        self.ability_command = app_commands.ContextMenu(
            name='Make Ability Check',
            callback=self.handle_ability_context
        )
        self.skill_command = app_commands.ContextMenu(
            name='Make Skill Check',
            callback=self.handle_skill_context
        )
        
        # Add commands to bot
        self.bot.tree.add_command(self.save_command)
        self.bot.tree.add_command(self.ability_command)
        self.bot.tree.add_command(self.skill_command)

    async def extract_character(self, message: discord.Message) -> Optional[Character]:
        """Try to extract character name from message and get character"""
        # First try to find a character name in the message content
        words = message.content.split()
        for word in words:
            char = self.bot.game_state.get_character(word)
            if char:
                return char
                
        # If that fails, check if the message is from an embed with character info
        if message.embeds:
            embed = message.embeds[0]
            if embed.title:
                # Try to extract name from common embed formats
                # Example: "🎲 Gandalf's Skill Check" -> "Gandalf"
                possible_names = embed.title.split("'s")[0].split()
                for name in possible_names:
                    # Strip common emoji
                    name = name.strip("🎲💀🛡️⚔️✨")
                    char = self.bot.game_state.get_character(name)
                    if char:
                        return char
                        
        return None

    async def handle_save_context(self, interaction: discord.Interaction, message: discord.Message):
        """Handle save context menu command"""
        try:
            # Get character
            character = await self.extract_character(message)
            if not character:
                await interaction.response.send_message(
                    "Couldn't find a character in this message.",
                    ephemeral=True
                )
                return

            # Create save selection view
            view = SaveSelectionView(character)
            await view.start(interaction)

        except Exception as e:
            logger.error(f"Error in save context menu: {e}", exc_info=True)
            await interaction.response.send_message(
                "Error processing save context menu.",
                ephemeral=True
            )

    async def handle_ability_context(self, interaction: discord.Interaction, message: discord.Message):
        """Handle ability check context menu command"""
        try:
            # Get character
            character = await self.extract_character(message)
            if not character:
                await interaction.response.send_message(
                    "Couldn't find a character in this message.",
                    ephemeral=True
                )
                return

            # Create ability selection view
            view = AbilitySelectionView(character)
            await view.start(interaction)

        except Exception as e:
            logger.error(f"Error in ability context menu: {e}", exc_info=True)
            await interaction.response.send_message(
                "Error processing ability context menu.",
                ephemeral=True
            )

    async def handle_skill_context(self, interaction: discord.Interaction, message: discord.Message):
        """Handle skill check context menu command"""
        try:
            # Get character
            character = await self.extract_character(message)
            if not character:
                await interaction.response.send_message(
                    "Couldn't find a character in this message.",
                    ephemeral=True
                )
                return

            # Create skill selection view
            view = SkillSelectionView(character)
            await view.start(interaction)

        except Exception as e:
            logger.error(f"Error in skill context menu: {e}", exc_info=True)
            await interaction.response.send_message(
                "Error processing skill context menu.",
                ephemeral=True
            )

class SaveSelectionView(discord.ui.View):
    """View for selecting saving throw type"""
    def __init__(self, character: Character):
        super().__init__()
        self.character = character

        # Add save type selection
        self.add_item(discord.ui.Select(
            placeholder="Select Save Type",
            options=[
                discord.SelectOption(
                    label=stat.value.capitalize(),
                    value=stat.value,
                    description=f"Make a {stat.value.capitalize()} saving throw"
                )
                for stat in StatType
            ],
            custom_id="save_select"
        ))
        
        # Add advantage selection
        self.add_item(discord.ui.Select(
            placeholder="Roll Type",
            options=[
                discord.SelectOption(
                    label="Normal",
                    value="normal",
                    description="Roll normally"
                ),
                discord.SelectOption(
                    label="Advantage",
                    value="advantage",
                    description="Roll with advantage"
                ),
                discord.SelectOption(
                    label="Disadvantage",
                    value="disadvantage",
                    description="Roll with disadvantage"
                )
            ],
            custom_id="advantage_select"
        ))

    async def start(self, interaction: discord.Interaction):
        """Show the save selection view"""
        embed = discord.Embed(
            title=f"Save Selection - {self.character.name}",
            description="Select the type of save to make",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Handle select interactions"""
        if interaction.data["custom_id"] == "save_select":
            stat = interaction.data["values"][0]
            advantage = Advantage.NORMAL
            
            # Build roll expression
            expression = build_roll_expression(self.character, CheckType.SAVE, stat, advantage)
            
            # Roll and calculate
            total, _, breakdown = DiceCalculator.calculate_complex(
                expression,
                character=self.character,
                concise=False
            )

            # Format and send result
            embed = await format_check_result(
                total,
                self.character,
                CheckType.SAVE,
                stat,
                None,  # No DC
                advantage,
                None,  # No reason
                breakdown
            )
            
            await interaction.response.edit_message(embed=embed, view=None)
            return True
            
        elif interaction.data["custom_id"] == "advantage_select":
            # Store advantage selection for next roll
            self.advantage = Advantage(interaction.data["values"][0])
            return True
            
        return False

class AbilitySelectionView(discord.ui.View):
    """View for selecting ability check type"""
    def __init__(self, character: Character):
        super().__init__()
        self.character = character

        # Add ability score selection
        self.add_item(discord.ui.Select(
            placeholder="Select Ability",
            options=[
                discord.SelectOption(
                    label=stat.value.capitalize(),
                    value=stat.value,
                    description=f"Make a {stat.value.capitalize()} check"
                )
                for stat in StatType
            ],
            custom_id="ability_select"
        ))
        
        # Add advantage selection
        self.add_item(discord.ui.Select(
            placeholder="Roll Type",
            options=[
                discord.SelectOption(
                    label="Normal",
                    value="normal",
                    description="Roll normally"
                ),
                discord.SelectOption(
                    label="Advantage",
                    value="advantage",
                    description="Roll with advantage"
                ),
                discord.SelectOption(
                    label="Disadvantage",
                    value="disadvantage",
                    description="Roll with disadvantage"
                )
            ],
            custom_id="advantage_select"
        ))

    async def start(self, interaction: discord.Interaction):
        """Show the ability selection view"""
        embed = discord.Embed(
            title=f"Ability Check Selection - {self.character.name}",
            description="Select the ability to check",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Handle select interactions"""
        if interaction.data["custom_id"] == "ability_select":
            stat = interaction.data["values"][0]
            advantage = getattr(self, 'advantage', Advantage.NORMAL)
            
            # Build roll expression
            expression = build_roll_expression(self.character, CheckType.ABILITY, stat, advantage)
            
            # Roll and calculate
            total, _, breakdown = DiceCalculator.calculate_complex(
                expression,
                character=self.character,
                concise=False
            )

            # Format and send result
            embed = await format_check_result(
                total,
                self.character,
                CheckType.ABILITY,
                stat,
                None,  # No DC
                advantage,
                None,  # No reason
                breakdown
            )
            
            await interaction.response.edit_message(embed=embed, view=None)
            return True
            
        elif interaction.data["custom_id"] == "advantage_select":
            # Store advantage selection for next roll
            self.advantage = Advantage(interaction.data["values"][0])
            return True
            
        return False

class SkillSelectionView(discord.ui.View):
    """View for selecting skill check type"""
    def __init__(self, character: Character):
        super().__init__()
        self.character = character

        # Add skill selection
        self.add_item(discord.ui.Select(
            placeholder="Select Skill",
            options=[
                discord.SelectOption(
                    label=skill.capitalize(),
                    value=skill,
                    description=f"{ability.value.capitalize()}-based skill"
                )
                for skill, ability in SKILL_ABILITIES.items()
            ],
            custom_id="skill_select"
        ))
        
        # Add advantage selection
        self.add_item(discord.ui.Select(
            placeholder="Roll Type",
            options=[
                discord.SelectOption(
                    label="Normal",
                    value="normal",
                    description="Roll normally"
                ),
                discord.SelectOption(
                    label="Advantage",
                    value="advantage",
                    description="Roll with advantage"
                ),
                discord.SelectOption(
                    label="Disadvantage",
                    value="disadvantage",
                    description="Roll with disadvantage"
                )
            ],
            custom_id="advantage_select"
        ))

    async def start(self, interaction: discord.Interaction):
        """Show the skill selection view"""
        embed = discord.Embed(
            title=f"Skill Check Selection - {self.character.name}",
            description="Select the skill to check",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Handle select interactions"""
        if interaction.data["custom_id"] == "skill_select":
            skill = interaction.data["values"][0]
            advantage = getattr(self, 'advantage', Advantage.NORMAL)
            
            # Build roll expression
            expression = build_roll_expression(self.character, CheckType.SKILL, skill, advantage)
            
            # Roll and calculate
            total, _, breakdown = DiceCalculator.calculate_complex(
                expression,
                character=self.character,
                concise=False
            )

            # Format and send result
            embed = await format_check_result(
                total,
                self.character,
                CheckType.SKILL,
                skill,
                None,  # No DC
                advantage,
                None,  # No reason
                breakdown
            )
            
            await interaction.response.edit_message(embed=embed, view=None)
            return True
            
        elif interaction.data["custom_id"] == "advantage_select":
            # Store advantage selection for next roll
            self.advantage = Advantage(interaction.data["values"][0])
            return True
            
        return False

async def setup(bot):
    """Add context menu commands to bot"""
    menu_handler = SkillCheckContextMenu(bot)