"""
Commands for managing combat initiative.
"""

import discord
import asyncio
from discord import app_commands, Interaction, Embed, Color
from discord.ext import commands
from typing import List, Optional
import logging

from utils.error_handler import handle_error
from modules.combat.initiative import InitiativeTracker
from modules.combat.save_handler import SaveConfirmView
from datetime import datetime, date

logger = logging.getLogger(__name__)

class InitiativeCommands(commands.GroupCog, name="initiative"):
    """Commands for managing combat initiative and turns"""
    
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
        self.tracker = InitiativeTracker(bot)
        self.quiet_mode = False  # For suppressing debug prints

    def debug_print(self, *args, **kwargs):
        """Print debug info only if not in quiet mode"""
        if not self.quiet_mode:
            print(*args, **kwargs)        
            
    @app_commands.command(name="start")
    @app_commands.describe(
        characters="Space-separated list of character names"
    )
    async def start_combat(
        self,
        interaction: discord.Interaction,
        characters: str
    ):
        """Start combat with initiative contest"""
        try:
            await interaction.response.defer()
            
            # Log command usage
            self.debug_print(f"\n=== Starting Combat with: {characters} ===")
            
            # Split character names and validate they exist
            char_list = [name.strip() for name in characters.split()]
            combat_chars = []
            
            for name in char_list:
                char = self.bot.game_state.get_character(name)
                if not char:
                    await interaction.followup.send(
                        f"❌ `Character '{name}' not found` ❌",
                        ephemeral=True
                    )
                    return
                combat_chars.append(char)
                self.debug_print(f"Added character: {name}")
            
            # Start combat with DEX contest
            success, message = await self.tracker.start_combat(combat_chars, interaction)
            
            if not success:
                await interaction.followup.send(
                    f"❌ `{message}` ❌",
                    ephemeral=True
                )
                return
                
            # Ask about autosave
            await self.tracker.save_handler.enable_autosave(interaction)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="setbattle")
    @app_commands.describe(
        order="Space-separated list of character names in desired order",
        round_number="Starting round number (default: 1)",
        current_turn="Index of current turn (0-based, default: 0)"
    )
    async def set_battle(
        self,
        interaction: discord.Interaction,
        order: str,
        round_number: Optional[int] = 1,
        current_turn: Optional[int] = 0
    ):
        """Start combat with manual turn order"""
        try:
            await interaction.response.defer()
            
            self.debug_print(f"\n=== Setting Battle: Round {round_number}, Turn {current_turn} ===")
            self.debug_print(f"Order: {order}")
            
            # Split character names and validate they exist
            char_list = [name.strip() for name in order.split()]
            
            # Validate all characters exist
            for name in char_list:
                if not self.bot.game_state.get_character(name):
                    await interaction.followup.send(
                        f"❌ `Character '{name}' not found` ❌",
                        ephemeral=True
                    )
                    return
            
            # Validate turn index
            if current_turn < 0 or current_turn >= len(char_list):
                await interaction.followup.send(
                    "❌ `Invalid turn index. Must be between 0 and the number of characters - 1` ❌",
                    ephemeral=True
                )
                return
                
            # Validate round number
            if round_number < 1:
                await interaction.followup.send(
                    "❌ `Round number must be 1 or greater` ❌",
                    ephemeral=True
                )
                return
            
            # Set manual battle order
            success, message = await self.tracker.set_battle(
                char_list,
                interaction,
                round_number=round_number,
                current_turn=current_turn
            )
            
            if not success:
                await interaction.followup.send(
                    f"❌ `{message}` ❌",
                    ephemeral=True
                )
                return
                
            # Ask about autosave
            await self.tracker.save_handler.enable_autosave(interaction)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="next")
    async def next_turn(self, interaction: discord.Interaction):
        """Advance to the next turn"""
        try:
            # Process turn
            success, message, effect_messages = await self.tracker.next_turn(interaction)
            
            if not success:
                await interaction.followup.send(f"❌ `{message}` ❌")
                return
                
            # Handle autosave
            if self.tracker.save_handler.autosave_enabled:
                order = [turn.character_name for turn in self.tracker.turn_order]
                await self.tracker.save_handler.autosave(
                    order,
                    self.tracker.current_index,
                    self.tracker.round_number
                )
                
        except Exception as e:
            self.debug_print(f"Error in next command: {e}")
            await interaction.followup.send(f"❌ `An error occurred processing the turn` ❌")

    @app_commands.command(name="quicksave")
    async def quicksave(self, interaction: discord.Interaction):
        """Create a quicksave of the current initiative state"""
        try:
            await interaction.response.defer()
            
            self.debug_print("\n=== Creating Quicksave ===")
            
            if not self.tracker.turn_order:
                await interaction.followup.send(
                    "❌ `No active combat to save` ❌",
                    ephemeral=True
                )
                return
                
            # Create quicksave
            order = [turn.character_name for turn in self.tracker.turn_order]
            await self.tracker.save_handler.quicksave(
                interaction,
                order,
                self.tracker.current_index,
                self.tracker.round_number
            )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="save")
    @app_commands.describe(name="Optional name for the save. If not provided, a numbered file name will be used.")
    async def save(
        self,
        interaction: discord.Interaction,
        name: Optional[str] = None
    ):
        """Save the current initiative state"""
        try:
            await interaction.response.defer()
            
            # Log command without redundant logging
            self.debug_print(f"\n=== Saving Initiative State: {name or 'auto-named'} ===")
            
            if not self.tracker.turn_order:
                await interaction.followup.send(
                    "❌ `No active combat to save` ❌",
                    ephemeral=True
                )
                return
                
            # Create save
            order = [turn.character_name for turn in self.tracker.turn_order]
            await self.tracker.save_handler.save(
                interaction,
                order,
                self.tracker.current_index,
                self.tracker.round_number,
                name
            )

        except Exception as e:
            await handle_error(interaction, e)
    
    @app_commands.command(name="listsaves") 
    async def list_saves_command(self, interaction: Interaction):
        """List all available initiative saves"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            self.debug_print("\n=== Listing Initiative Saves ===")
            
            # Get and sort saves
            saves = self.tracker.save_handler.list_saves()  # Synchronous
            
            if not saves:
                await interaction.followup.send(
                    "📁 No saved encounters found.",
                    ephemeral=True
                )
                return
            
            # Create embed
            embed = Embed(
                title="📁 Saved Encounters",
                color=Color.blue()
            )
            
            # Track today's date once
            today = date.today()
            
            # Add save entries
            for save in saves:
                name = save['name']
                # Skip system saves unless they exist
                if name in ['autosave', 'quicksave'] and not save.get('timestamp'):
                    continue
                    
                # Build value list
                value = []
                
                # Add round and character count
                value.append(f"Round {save['round']}")
                value.append(f"{save['characters']} characters")
                
                # Add timestamp if exists
                if save.get('timestamp'):
                    try:
                        # Parse timestamp
                        timestamp = datetime.fromisoformat(save['timestamp'])
                        
                        # Format based on if it's from today
                        if timestamp.date() == today:
                            time_str = f"Saved today at {timestamp.strftime('%I:%M %p')}"
                        else:
                            time_str = f"Saved {timestamp.strftime('%m/%d')} at {timestamp.strftime('%I:%M %p')}"
                        value.append(time_str)
                    except (ValueError, TypeError):
                        pass  # Skip timestamp if invalid
                    
                # Add description if exists
                if save.get('description'):
                    value.append(f"*{save['description']}*")
                    
                # Add field to embed
                embed.add_field(
                    name=f"{'🔄' if name in ['autosave', 'quicksave'] else '📄'} {name}",
                    value="\n".join(value),
                    inline=False
                )
            
            # Send the embed
            await interaction.followup.send(
                embed=embed,
                ephemeral=True
            )

        except Exception as e:
            self.debug_print(f"Error in listsaves command: {e}")
            await interaction.followup.send(
                "❌ An error occurred while listing saves.",
                ephemeral=True
            )

    @app_commands.command(name="load")
    @app_commands.describe(save_name="Name of save to load (defaults to quicksave)")
    async def load_save(
        self,
        interaction: discord.Interaction,
        save_name: Optional[str] = "quicksave"
    ):
        """Load a saved initiative state"""
        try:
            await interaction.response.defer()
            
            self.debug_print(f"\n=== Loading Save: {save_name} ===")
            
            # Check if combat is active
            if self.tracker.turn_order:
                view = SaveConfirmView()
                await interaction.followup.send(
                    "⚠️ A combat is already in progress. Load anyway?",
                    view=view,
                    ephemeral=True
                )
                await view.wait()
                
                if not view.value:
                    await interaction.followup.send(
                        "Load cancelled.",
                        ephemeral=True
                    )
                    return
            
            # Load save data
            save_data = await self.tracker.save_handler.load_save(interaction, save_name)
            if not save_data:
                return
                
            # Set up battle with saved state
            success, message = await self.tracker.set_battle(
                save_data.order,
                interaction,
                round_number=save_data.round_number,
                current_turn=save_data.current_turn
            )
            
            if not success:
                await interaction.followup.send(
                    f"❌ `{message}` ❌",
                    ephemeral=True
                )
                return
                
            # Show load embed
            embed = await self.tracker.save_handler.create_load_embed(save_data)
            await interaction.followup.send(embed=embed)
            
            # Ask about autosave
            await self.tracker.save_handler.enable_autosave(interaction)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="addcombat")
    @app_commands.describe(
        character="Character to add to combat"
    )
    async def add_combatant(
        self,
        interaction: discord.Interaction,
        character: str
    ):
        """Add a character to ongoing combat"""
        try:
            await interaction.response.defer()
            
            self.debug_print(f"\n=== Adding Combatant: {character} ===")
            
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(
                    f"❌ `Character '{character}' not found` ❌",
                    ephemeral=True
                )
                return
            
            success, message = await self.tracker.add_combatant(char, interaction)
            
            if not success:
                await interaction.followup.send(
                    f"❌ `{message}` ❌",
                    ephemeral=True
                )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="removecombat")
    @app_commands.describe(
        character="Character to remove from combat"
    )
    async def remove_combatant(
        self,
        interaction: discord.Interaction,
        character: str
    ):
        """Remove a character from combat"""
        try:
            await interaction.response.defer()
            
            self.debug_print(f"\n=== Removing Combatant: {character} ===")
            
            success, message = await self.tracker.remove_combatant(character, interaction)
            
            if not success:
                await interaction.followup.send(
                    f"❌ `{message}` ❌",
                    ephemeral=True
                )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="endcombat", description="End the current combat")
    async def end_combat(self, interaction: discord.Interaction):
        """End the current combat session"""
        try:
            await interaction.response.defer()
            
            # Fixed: Pass the interaction to the end_combat method
            success, message = await self.tracker.end_combat(interaction)
            
            if not success:
                await interaction.followup.send(f"❌ {message}", ephemeral=True)
                
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="order")
    async def view_order(
        self,
        interaction: discord.Interaction
    ):
        """Show current initiative order"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            self.debug_print("\n=== Viewing Initiative Order ===")
            
            if not self.tracker.turn_order:
                await interaction.followup.send(
                    "❌ `No active combat` ❌",
                    ephemeral=True
                )
                return

            order_text = []
            for i, turn in enumerate(self.tracker.turn_order):
                if i == self.tracker.current_index:
                    order_text.append(f"▶️ {turn.character_name} (Current)")
                else:
                    order_text.append(f"⬜ {turn.character_name}")
            
            await interaction.followup.send(
                "📋 Current turn order:\n" + "\n".join(order_text),
                ephemeral=True
            )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="log")
    async def view_log(
        self,
        interaction: discord.Interaction
    ):
        """Show recent combat actions"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            self.debug_print("\n=== Viewing Combat Log ===")
            
            entries = self.tracker.combat_log.entries[-5:]  # Last 5 entries
            
            if not entries:
                await interaction.followup.send(
                    "📜 No combat actions yet.",
                    ephemeral=True
                )
                return
                
            log_text = []
            for entry in reversed(entries):
                icon = {
                    "action": "⚔️",
                    "effect": "✨",
                    "system": "📢",
                    "damage": "💥",
                    "heal": "💚"
                }.get(entry["type"], "ℹ️")
                
                log_text.append(f"{icon} {entry['message']}")
                
            await interaction.followup.send(
                "📜 Recent actions:\n" + "\n".join(log_text),
                ephemeral=True
            )

        except Exception as e:
            await handle_error(interaction, e)

async def setup(bot):
    await bot.add_cog(InitiativeCommands(bot))