"""Healing and restoration commands for character resources."""

import discord
from discord import app_commands
from discord.ext import commands
import logging
import random
from typing import Optional, Tuple

from utils.error_handler import handle_error
from utils.formatting import MessageFormatter
from modules.combat.logger import CombatEventType
from utils.dice import DiceRoller

logger = logging.getLogger(__name__)

def process_healing(
    character: 'Character',
    amount: int,
    resource_type: str = "hp",
    full_restore: bool = False
) -> Tuple[int, int]:
    """
    Process healing amount and return amount healed
    
    Args:
        character: Character to heal
        amount: Amount to heal (ignored if full_restore is True)
        resource_type: Type of resource to restore ("hp" or "mp")
        full_restore: Whether to restore to full
        
    Returns:
        Tuple of (amount_healed, new_value)
    """
    if resource_type == "hp":
        old_value = character.resources.current_hp
        if full_restore:
            character.resources.current_hp = character.resources.max_hp
        else:
            character.resources.current_hp = min(
                character.resources.max_hp,
                character.resources.current_hp + amount
            )
        healed = character.resources.current_hp - old_value
        return healed, character.resources.current_hp
    else:  # MP
        old_value = character.resources.current_mp
        if full_restore:
            character.resources.current_mp = character.resources.max_mp
        else:
            character.resources.current_mp = min(
                character.resources.max_mp,
                character.resources.current_mp + amount
            )
        restored = character.resources.current_mp - old_value
        return restored, character.resources.current_mp

class HealingCommands(commands.Cog):
    """Commands for healing and resource restoration"""
    def __init__(self, bot):
        self.bot = bot
        
        # List of healing verbs for more natural messages
        self.healing_verbs = [
            "heals for",
            "recovers",
            "restores",
            "regains",
            "mends"
        ]

    @app_commands.command(name="heal")
    @app_commands.describe(
        character="Character to heal",
        amount="Amount to heal (can use dice)",
        resource="Resource to restore (HP/MP)",
        reason="Reason for healing (optional)"
    )
    @app_commands.choices(
        resource=[
            app_commands.Choice(name="Hit Points (HP)", value="hp"),
            app_commands.Choice(name="Mana Points (MP)", value="mp")
        ]
    )
    async def heal(
        self,
        interaction: discord.Interaction,
        character: str,
        amount: str,
        resource: app_commands.Choice[str],
        reason: Optional[str] = None
    ):
        """Heal a character or restore MP"""
        try:
            await interaction.response.defer()

            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(
                    f"❌ Character '{character}' not found.",
                    ephemeral=True
                )
                return

            # Roll healing amount
            try:
                heal_amount, roll_exp = DiceRoller.roll_dice(amount)
            except ValueError as e:
                await interaction.followup.send(
                    f"❌ Invalid amount format: {e}",
                    ephemeral=True
                )
                return

            # Get combat logger if in combat
            combat_logger = None
            if hasattr(self.bot, 'initiative_tracker'):
                combat_logger = self.bot.initiative_tracker.logger

            if combat_logger:
                combat_logger.snapshot_character_state(char)

            # Process healing
            amount_restored, new_value = process_healing(
                char,
                heal_amount,
                resource.value
            )

            # Show roll details privately
            roll_embed = discord.Embed(
                title="🎲 Healing Roll",
                description=DiceRoller.format_roll_result(heal_amount, roll_exp),
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=roll_embed, ephemeral=True)

            # Print debug info
            print(f"Command: /heal {character} {amount} {resource.value}{' --reason \"'+reason+'\"' if reason else ''}")

            # Create main message content
            emoji = "💚" if resource.value == "hp" else "💙"
            resource_name = "HP" if resource.value == "hp" else "MP"
            
            # Choose a random healing verb for variety
            verb = random.choice(self.healing_verbs)
            
            # Create main content
            main_content = f"{char.name} {verb} {amount_restored} {resource_name}"
            
            # Add reason if provided
            if reason:
                main_content += f" from {reason}"
            
            # Create the message with backticks
            message = f"{emoji} `{main_content}`. {resource_name}: {new_value}/{char.resources.max_hp if resource.value == 'hp' else char.resources.max_mp}"

            # Log healing if in combat
            if combat_logger:
                event_type = (
                    CombatEventType.HEALING_DONE 
                    if resource.value == "hp" 
                    else CombatEventType.RESOURCE_CHANGE
                )
                
                combat_logger.add_event(
                    event_type,
                    message=f"Restored {amount_restored} {resource_name}",
                    character=char.name,
                    details={
                        "amount": amount_restored,
                        "roll": roll_exp,
                        "old_value": new_value - amount_restored,
                        "new_value": new_value,
                        "reason": reason,
                        "resource": resource.value
                    }
                )
                combat_logger.snapshot_character_state(char)

            # Save character
            await self.bot.db.save_character(char)
            await interaction.channel.send(message)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(
        name="senzu",
        description="Fully restore a character's HP and MP"
    )
    @app_commands.describe(
        character="The character to restore",
        reason="Reason for using senzu (optional)"
    )
    async def senzu(
        self,
        interaction: discord.Interaction,
        character: str,
        reason: Optional[str] = None
    ) -> None:
        """Full HP and MP restoration"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(
                    f"❌ Character '{character}' not found.",
                    ephemeral=True
                )
                return

            # Get combat logger if in combat
            combat_logger = None
            if hasattr(self.bot, 'initiative_tracker'):
                combat_logger = self.bot.initiative_tracker.logger

            if combat_logger:
                combat_logger.snapshot_character_state(char)

            # Process full restoration
            hp_restored, new_hp = process_healing(char, 0, "hp", full_restore=True)
            mp_restored, new_mp = process_healing(char, 0, "mp", full_restore=True)

            # Create feedback embed
            embed = discord.Embed(
                title="💚 Senzu Bean Used! 💚",
                description=f"*{char.name} ate a senzu bean...*",
                color=discord.Color.green()
            )

            # Add HP restoration
            if hp_restored > 0:
                old_hp = new_hp - hp_restored
                embed.add_field(
                    name="HP Restored",
                    value=f"`{hp_restored:+} ({old_hp} → {new_hp})`",
                    inline=True
                )

            # Add MP restoration
            if mp_restored > 0:
                old_mp = new_mp - mp_restored
                embed.add_field(
                    name="MP Restored",
                    value=f"`{mp_restored:+} ({old_mp} → {new_mp})`",
                    inline=True
                )

            # Add current status
            embed.add_field(
                name="Current Status",
                value=(
                    f"HP: `{new_hp}/{char.resources.max_hp}`\n"
                    f"MP: `{new_mp}/{char.resources.max_mp}`"
                ),
                inline=False
            )

            if reason:
                embed.set_footer(text=f"Reason: {reason}")

            # Print debug info
            print(f"Command: /senzu {character}{' --reason \"'+reason+'\"' if reason else ''}")

            # Log restoration if in combat
            if combat_logger:
                if hp_restored > 0:
                    combat_logger.add_event(
                        CombatEventType.HEALING_DONE,
                        message=f"Senzu bean restores {hp_restored} HP",
                        character=char.name,
                        details={
                            "amount": hp_restored,
                            "source": "Senzu Bean",
                            "old_hp": new_hp - hp_restored,
                            "new_hp": new_hp,
                            "reason": reason
                        }
                    )

                if mp_restored > 0:
                    combat_logger.add_event(
                        CombatEventType.RESOURCE_CHANGE,
                        message=f"Senzu bean restores {mp_restored} MP",
                        character=char.name,
                        details={
                            "amount": mp_restored,
                            "source": "Senzu Bean",
                            "old_mp": new_mp - mp_restored,
                            "new_mp": new_mp,
                            "reason": reason
                        }
                    )

                combat_logger.snapshot_character_state(char)

            # Save character
            await self.bot.db.save_character(char)
            
            # Send response
            try:
                # Try to send with senzu bean gif
                await interaction.followup.send(
                    embed=embed,
                    file=discord.File("assets/senzu_bean.gif")
                )
            except FileNotFoundError:
                # Fall back to just the embed if gif not found
                await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in senzu command: {str(e)}", exc_info=True)
            await handle_error(interaction, e)

async def setup(bot):
    await bot.add_cog(HealingCommands(bot))