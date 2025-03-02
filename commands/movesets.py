"""
## src/commands/movesets.py

Moveset management commands for saving, loading, and managing movesets.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List
import logging

from modules.moves.data import Moveset
from modules.moves.loader import MoveLoader
from utils.error_handler import handle_error

logger = logging.getLogger(__name__)

class MovesetCommands(commands.GroupCog, name="moveset"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="save")
    @app_commands.describe(
        character="Character whose moveset to save",
        name="Name to save the moveset as",
        description="Optional description for the moveset"
    )
    async def save_moveset(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        description: Optional[str] = None
    ):
        """Save a character's moveset to be loaded by others"""
        await interaction.response.defer()

        try:
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(
                    f"❌ Character '{character}' not found.",
                    ephemeral=True
                )
                return

            # Check if they have moves
            if not char.moveset or not char.list_moves():
                await interaction.followup.send(
                    f"❌ {character} has no moves to save.",
                    ephemeral=True
                )
                return

            # Save to global moveset collection
            success = await MoveLoader.save_global_moveset(
                self.bot.db, 
                name, 
                char.moveset,
                description
            )
            
            if not success:
                await interaction.followup.send(
                    f"❌ Error saving moveset '{name}'.",
                    ephemeral=True
                )
                return

            # Create feedback embed
            embed = discord.Embed(
                title=f"💾 Moveset Saved: {name}",
                description=f"Saved {character}'s moveset",
                color=discord.Color.green()
            )

            move_count = len(char.list_moves())
            embed.add_field(
                name="Contents",
                value=f"• {move_count} move{'s' if move_count != 1 else ''}"
            )

            if description:
                embed.add_field(
                    name="Description",
                    value=description,
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="load")
    @app_commands.describe(
        character="Character to load the moveset into",
        name="Name of the moveset to load",
        merge="Whether to merge with existing moves (default: replace)"
    )
    async def load_moveset(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        merge: Optional[bool] = False
    ):
        """Load a saved moveset into a character"""
        await interaction.response.defer()

        try:
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(
                    f"❌ Character '{character}' not found.",
                    ephemeral=True
                )
                return

            # Get moveset from global collection
            moveset = await MoveLoader.load_global_moveset(self.bot.db, name)
            if not moveset:
                await interaction.followup.send(
                    f"❌ Moveset '{name}' not found.",
                    ephemeral=True
                )
                return

            # Check if character already has moves and not merging
            if char.moveset and char.list_moves() and not merge:
                # Ask for confirmation
                confirm = discord.ui.Button(
                    label="Confirm Replace",
                    style=discord.ButtonStyle.danger
                )
                cancel = discord.ui.Button(
                    label="Cancel",
                    style=discord.ButtonStyle.secondary
                )
                
                view = discord.ui.View()
                view.add_item(confirm)
                view.add_item(cancel)
                
                async def confirm_callback(btn_interaction):
                    if btn_interaction.user != interaction.user:
                        return
                        
                    # Assign moveset (sets reference) - pass both db and bot
                    success = await MoveLoader.assign_global_moveset(
                        self.bot.db,
                        self.bot,
                        character,
                        name
                    )
                    
                    if not success:
                        await interaction.edit_original_response(
                            content="❌ Error assigning moveset.",
                            embed=None,
                            view=None
                        )
                        return
                    
                    # Get updated character
                    char = self.bot.game_state.get_character(character)
                    
                    # Update response
                    embed = discord.Embed(
                        title=f"📥 Moveset Loaded",
                        description=f"Replaced {character}'s moves with '{name}'",
                        color=discord.Color.green()
                    )
                    
                    moves_list = char.list_moves()
                    if moves_list:
                        move_text = "\n".join(f"• {move}" for move in moves_list[:15])
                        if len(moves_list) > 15:
                            move_text += f"\n• ... and {len(moves_list) - 15} more"
                            
                        embed.add_field(
                            name=f"Moves ({len(moves_list)})",
                            value=move_text
                        )
                    
                    await interaction.edit_original_response(
                        content=None,
                        embed=embed,
                        view=None
                    )
                    
                async def cancel_callback(btn_interaction):
                    if btn_interaction.user != interaction.user:
                        return
                        
                    await interaction.edit_original_response(
                        content="Moveset load cancelled.",
                        embed=None,
                        view=None
                    )
                    
                confirm.callback = confirm_callback
                cancel.callback = cancel_callback
                
                # Show confirmation
                embed = discord.Embed(
                    title="⚠️ Confirm Moveset Load",
                    description=f"{character} already has moves that will be replaced.",
                    color=discord.Color.yellow()
                )
                
                # Show current moves
                current_moves = char.list_moves()
                if current_moves:
                    current_text = "\n".join(f"• {move}" for move in current_moves[:10])
                    if len(current_moves) > 10:
                        current_text += f"\n• ... and {len(current_moves) - 10} more"
                    
                    embed.add_field(
                        name=f"Current Moves ({len(current_moves)})",
                        value=current_text
                    )
                
                # Show new moves
                new_moves = moveset.list_moves()
                if new_moves:
                    new_text = "\n".join(f"• {move}" for move in new_moves[:10])
                    if len(new_moves) > 10:
                        new_text += f"\n• ... and {len(new_moves) - 10} more"
                    
                    embed.add_field(
                        name=f"New Moves ({len(new_moves)})",
                        value=new_text
                    )
                
                await interaction.followup.send(
                    embed=embed,
                    view=view
                )
                
            else:
                # No existing moves or merging, load directly
                if merge and char.moveset:
                    # Merge moves
                    for move_name, move in moveset.moves.items():
                        if not char.get_move(move_name):
                            char.moveset.add_move(move)
                            
                    # Save reference
                    char.moveset.reference = name
                else:
                    # Replace with new moveset
                    result = await MoveLoader.assign_global_moveset(
                        self.bot.db,
                        self.bot,
                        character,
                        name
                    )
                    
                    if not result:
                        # If failed to load global moveset, just use the local one
                        char.moveset = moveset
                        await self.bot.db.save_character(char)
                        
                    # If success, the character is already saved by assign_global_moveset
                    # No need to save again
                    return
                
                # Create feedback embed
                embed = discord.Embed(
                    title=f"📥 Moveset Loaded",
                    description=f"{'Merged' if merge else 'Loaded'} moveset '{name}' into {character}",
                    color=discord.Color.green()
                )
                
                moves_list = char.list_moves()
                if moves_list:
                    move_text = "\n".join(f"• {move}" for move in moves_list[:15])
                    if len(moves_list) > 15:
                        move_text += f"\n• ... and {len(moves_list) - 15} more"
                        
                    embed.add_field(
                        name=f"Moves ({len(moves_list)})",
                        value=move_text
                    )
                
                await interaction.followup.send(embed=embed)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="list")
    async def list_movesets(
        self,
        interaction: discord.Interaction
    ):
        """List all available shared movesets"""
        await interaction.response.defer()

        try:
            # Get movesets
            movesets = await self.bot.db.list_movesets()
            if not movesets:
                await interaction.followup.send(
                    "📚 No shared movesets found.",
                    ephemeral=True
                )
                return

            # Create embed
            embed = discord.Embed(
                title="📚 Shared Movesets",
                color=discord.Color.blue(),
                description=f"Found {len(movesets)} shared movesets"
            )

            # Group movesets for better display
            for moveset in movesets:
                # Get basic info
                name = moveset["name"]
                move_count = moveset.get("move_count", 0)
                desc = moveset.get("description", "No description")
                
                # Add compact field (up to 25)
                embed.add_field(
                    name=name,
                    value=f"• Moves: {move_count}\n• {desc}",
                    inline=True
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="info")
    @app_commands.describe(
        name="Name of the moveset to view"
    )
    async def moveset_info(
        self,
        interaction: discord.Interaction,
        name: str
    ):
        """View detailed information about a moveset"""
        await interaction.response.defer()

        try:
            # Get moveset
            moveset = await MoveLoader.load_global_moveset(self.bot.db, name)
            if not moveset:
                await interaction.followup.send(
                    f"❌ Moveset '{name}' not found.",
                    ephemeral=True
                )
                return
                
            # Get metadata
            metadata = await self.bot.db.get_moveset_metadata(name)
            
            # Create embed
            embed = discord.Embed(
                title=f"📚 Moveset: {name}",
                description=metadata.get("description", "No description"),
                color=discord.Color.blue()
            )
            
            # Add moves
            moves = moveset.list_moves()
            if moves:
                # Group moves by type
                combat_moves = []
                utility_moves = []
                
                for move_name in sorted(moves):
                    move = moveset.get_move(move_name)
                    if move.attack_roll or move.damage:
                        # Combat move
                        combat_moves.append(move)
                    else:
                        # Utility move
                        utility_moves.append(move)
                
                # Add combat moves
                if combat_moves:
                    combat_text = []
                    for move in combat_moves[:10]:
                        # Create compact line with costs
                        costs = []
                        if move.mp_cost != 0:
                            costs.append(f"MP:{move.mp_cost}")
                        if move.star_cost > 0:
                            costs.append(f"⭐:{move.star_cost}")
                            
                        cost_text = f" ({', '.join(costs)})" if costs else ""
                        combat_text.append(f"• **{move.name}**{cost_text}")
                        
                    if len(combat_moves) > 10:
                        combat_text.append(f"• ... and {len(combat_moves) - 10} more")
                        
                    embed.add_field(
                        name=f"Combat Moves ({len(combat_moves)})",
                        value="\n".join(combat_text),
                        inline=False
                    )
                
                # Add utility moves
                if utility_moves:
                    utility_text = []
                    for move in utility_moves[:10]:
                        # Create compact line with costs
                        costs = []
                        if move.mp_cost != 0:
                            costs.append(f"MP:{move.mp_cost}")
                        if move.star_cost > 0:
                            costs.append(f"⭐:{move.star_cost}")
                            
                        cost_text = f" ({', '.join(costs)})" if costs else ""
                        utility_text.append(f"• **{move.name}**{cost_text}")
                        
                    if len(utility_moves) > 10:
                        utility_text.append(f"• ... and {len(utility_moves) - 10} more")
                        
                    embed.add_field(
                        name=f"Utility Moves ({len(utility_moves)})",
                        value="\n".join(utility_text),
                        inline=False
                    )
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="delete")
    @app_commands.describe(
        name="Name of the moveset to delete"
    )
    async def delete_moveset(
        self,
        interaction: discord.Interaction,
        name: str
    ):
        """Delete a shared moveset"""
        await interaction.response.defer()

        try:
            # Check if exists
            metadata = await self.bot.db.get_moveset_metadata(name)
            if not metadata:
                await interaction.followup.send(
                    f"❌ Moveset '{name}' not found.",
                    ephemeral=True
                )
                return

            # Confirm deletion
            confirm = discord.ui.Button(
                label="Delete Moveset",
                style=discord.ButtonStyle.danger
            )
            cancel = discord.ui.Button(
                label="Cancel",
                style=discord.ButtonStyle.secondary
            )
            
            view = discord.ui.View()
            view.add_item(confirm)
            view.add_item(cancel)
            
            async def confirm_callback(btn_interaction):
                if btn_interaction.user != interaction.user:
                    return
                    
                # Delete from database
                success = await self.bot.db.delete_moveset(name)
                
                if not success:
                    await interaction.edit_original_response(
                        content=f"❌ Error deleting moveset '{name}'.",
                        embed=None,
                        view=None
                    )
                    return
                
                await interaction.edit_original_response(
                    content=f"✅ Deleted moveset '{name}'.",
                    embed=None,
                    view=None
                )
                
            async def cancel_callback(btn_interaction):
                if btn_interaction.user != interaction.user:
                    return
                    
                await interaction.edit_original_response(
                    content="Deletion cancelled.",
                    embed=None,
                    view=None
                )
                
            confirm.callback = confirm_callback
            cancel.callback = cancel_callback
            
            # Show confirmation
            move_count = metadata.get("move_count", 0)
            embed = discord.Embed(
                title=f"⚠️ Delete Moveset: {name}",
                description=f"Are you sure you want to delete this moveset with {move_count} moves?",
                color=discord.Color.red()
            )
            
            embed.add_field(
                name="Warning",
                value="This action cannot be undone. Characters using this moveset will keep their current moves."
            )
            
            await interaction.followup.send(
                embed=embed,
                view=view
            )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="export")
    @app_commands.describe(
        character="Character whose moveset to export",
        pretty="Whether to format the JSON (default: true)"
    )
    async def export_moveset(
        self,
        interaction: discord.Interaction,
        character: str,
        pretty: Optional[bool] = True
    ):
        """Export a character's moveset as JSON"""
        await interaction.response.defer()

        try:
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(
                    f"❌ Character '{character}' not found.",
                    ephemeral=True
                )
                return

            # Check if they have moves
            if not char.moveset or not char.list_moves():
                await interaction.followup.send(
                    f"❌ {character} has no moves to export.",
                    ephemeral=True
                )
                return

            # Export as JSON
            json_str = MoveLoader.export_moveset(char.moveset, pretty)

            # Create file
            file = discord.File(
                fp=str.encode(json_str),
                filename=f"{character}_moveset.json"
            )

            # Send file
            await interaction.followup.send(
                f"📤 Exported {character}'s moveset",
                file=file,
                ephemeral=True  # Send privately
            )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="clear")
    @app_commands.describe(
        character="Character whose moveset to clear"
    )
    async def clear_moveset(
        self,
        interaction: discord.Interaction,
        character: str
    ):
        """Clear a character's moveset"""
        await interaction.response.defer()

        try:
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(
                    f"❌ Character '{character}' not found.",
                    ephemeral=True
                )
                return

            # Check if they have moves
            if not char.moveset or not char.list_moves():
                await interaction.followup.send(
                    f"⚠️ {character} has no moves to clear.",
                    ephemeral=True
                )
                return

            # Confirm clear
            confirm = discord.ui.Button(
                label="Clear Moves",
                style=discord.ButtonStyle.danger
            )
            cancel = discord.ui.Button(
                label="Cancel",
                style=discord.ButtonStyle.secondary
            )
            
            view = discord.ui.View()
            view.add_item(confirm)
            view.add_item(cancel)
            
            async def confirm_callback(btn_interaction):
                if btn_interaction.user != interaction.user:
                    return
                    
                # Clear moveset
                char.moveset.clear()
                
                # Save character
                await self.bot.db.save_character(char)
                
                await interaction.edit_original_response(
                    content=f"✅ Cleared {character}'s moveset.",
                    embed=None,
                    view=None
                )
                
            async def cancel_callback(btn_interaction):
                if btn_interaction.user != interaction.user:
                    return
                    
                await interaction.edit_original_response(
                    content="Clear cancelled.",
                    embed=None,
                    view=None
                )
                
            confirm.callback = confirm_callback
            cancel.callback = cancel_callback
            
            # Show confirmation
            move_count = len(char.list_moves())
            embed = discord.Embed(
                title=f"⚠️ Clear Moveset: {character}",
                description=f"Are you sure you want to clear {move_count} moves from {character}?",
                color=discord.Color.red()
            )
            
            embed.add_field(
                name="Warning",
                value="This action cannot be undone."
            )
            
            await interaction.followup.send(
                embed=embed,
                view=view
            )

        except Exception as e:
            await handle_error(interaction, e)

    @load_moveset.autocomplete('name')
    @delete_moveset.autocomplete('name')
    @moveset_info.autocomplete('name')
    async def moveset_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete moveset names"""
        try:
            # Get all movesets
            movesets = await self.bot.db.list_movesets()
            if not movesets:
                return []
                
            # Filter by current input
            matching = [
                ms["name"] for ms in movesets
                if current.lower() in ms["name"].lower()
            ]
            
            # Return as choices
            return [
                app_commands.Choice(name=name, value=name)
                for name in matching[:25]  # Discord limits to 25 choices
            ]
            
        except Exception:
            return []

    @app_commands.command(name="import")
    @app_commands.describe(
        name="Name for the imported moveset",
        description="Optional description for the moveset",
        json_file="JSON file containing the moveset (optional)",
        json_data="JSON data as text (optional if file provided)"
    )
    async def import_json(
        self, 
        interaction: discord.Interaction, 
        name: str,
        description: Optional[str] = None,
        json_file: Optional[discord.Attachment] = None,
        json_data: Optional[str] = None
    ):
        """Import a moveset from JSON file or text and save it globally"""
        try:
            await interaction.response.defer()
            
            # Check if we have either a file or text data
            if not json_file and not json_data:
                await interaction.followup.send(
                    "❌ You must provide either a JSON file or paste JSON data.",
                    ephemeral=True
                )
                return
                
            # If file is provided, read its contents
            if json_file:
                # Check if file is a JSON file
                if not json_file.filename.endswith('.json'):
                    await interaction.followup.send(
                        "❌ File must be a JSON file (with .json extension).",
                        ephemeral=True
                    )
                    return
                    
                # Check file size (10MB limit is reasonable)
                if json_file.size > 10 * 1024 * 1024:  # 10MB
                    await interaction.followup.send(
                        "❌ File is too large. Maximum size is 10MB.",
                        ephemeral=True
                    )
                    return
                    
                # Read file content
                file_content = await json_file.read()
                json_data = file_content.decode('utf-8')
            
            # Parse JSON
            try:
                moveset = MoveLoader.import_moveset(json_data)
                if not moveset:
                    await interaction.followup.send(
                        "❌ Failed to parse moveset JSON. Please check your input and try again.",
                        ephemeral=True
                    )
                    return
            except json.JSONDecodeError as e:
                # Provide more helpful error message for JSON syntax errors
                line_col = f"line {e.lineno}, column {e.colno}"
                await interaction.followup.send(
                    f"❌ JSON syntax error at {line_col}: {e.msg}",
                    ephemeral=True
                )
                return
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Error parsing JSON: {str(e)}",
                    ephemeral=True
                )
                return

            # Count moves
            move_count = len(moveset.list_moves())
            if move_count == 0:
                await interaction.followup.send(
                    "❌ The provided JSON doesn't contain any moves.",
                    ephemeral=True
                )
                return
                
            # Save to database
            result = await MoveLoader.save_global_moveset(
                self.bot.db, 
                name, 
                moveset,
                description
            )
            
            if result:
                # Create summary embed
                embed = discord.Embed(
                    title="Moveset Imported Successfully",
                    description=f"Successfully imported **{name}** with {move_count} moves.",
                    color=discord.Color.green()
                )
                
                if json_file:
                    embed.add_field(
                        name="Source",
                        value=f"Imported from file: `{json_file.filename}`",
                        inline=False
                    )
                
                # Add move list by category
                moves_by_category = {}
                for move_name in moveset.list_moves():
                    move = moveset.get_move(move_name)
                    if move:
                        category = getattr(move, 'category', 'Other')
                        if category not in moves_by_category:
                            moves_by_category[category] = []
                        moves_by_category[category].append(move)
                
                # Create a summary for each category
                for category, moves in moves_by_category.items():
                    move_lines = []
                    for move in moves[:10]:  # Limit to 10 moves per category 
                        cost_text = ""
                        if move.star_cost > 0:
                            cost_text += f" ⭐{move.star_cost}"
                        if move.mp_cost != 0:
                            cost_text += f" MP:{abs(move.mp_cost)}"
                        move_lines.append(f"• {move.name}{cost_text}")
                    
                    if len(moves) > 10:
                        move_lines.append(f"• ... and {len(moves) - 10} more")
                        
                    embed.add_field(
                        name=f"{category} Moves ({len(moves)})",
                        value="\n".join(move_lines),
                        inline=False
                    )
                
                embed.set_footer(text=f"Use /moveset load character:<name> name:{name} to add this moveset to a character")
                
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(
                    "❌ Failed to save moveset. Check logs for details.",
                    ephemeral=True
                )
                
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="export")
    @app_commands.describe(
        character="Character whose moveset to export",
        pretty="Whether to format the JSON (default: true)"
    )
    async def export_moveset(
        self,
        interaction: discord.Interaction,
        character: str,
        pretty: Optional[bool] = True
    ):
        """Export a character's moveset as JSON file"""
        await interaction.response.defer()

        try:
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(
                    f"❌ Character '{character}' not found.",
                    ephemeral=True
                )
                return

            # Check if they have moves
            if not char.moveset or not char.list_moves():
                await interaction.followup.send(
                    f"❌ {character} has no moves to export.",
                    ephemeral=True
                )
                return

            # Export as JSON
            json_str = MoveLoader.export_moveset(char.moveset, pretty)
            
            # Create metadata embed
            embed = discord.Embed(
                title=f"{character}'s Moveset Export",
                description=f"Exported {len(char.list_moves())} moves as JSON.",
                color=discord.Color.blue()
            )
            
            # Add instructions
            embed.add_field(
                name="How to Use",
                value=(
                    "Upload this file with the command:\n"
                    "`/moveset import_json name:<name> json_file:<file>`\n\n"
                    "Or import it into another character:\n"
                    "`/moveset load character:<name> name:<moveset_name>`"
                ),
                inline=False
            )
            
            # Add categories breakdown
            moves_by_category = {}
            for move_name in char.list_moves():
                move = char.get_move(move_name)
                if move:
                    category = getattr(move, 'category', 'Other')
                    if category not in moves_by_category:
                        moves_by_category[category] = []
                    moves_by_category[category].append(move)
            
            category_summary = []
            for category, moves in moves_by_category.items():
                category_summary.append(f"{category}: {len(moves)} moves")
                
            if category_summary:
                embed.add_field(
                    name="Categories",
                    value="\n".join(category_summary),
                    inline=False
                )

            # Create file
            file = discord.File(
                fp=str.encode(json_str),
                filename=f"{character}_moveset.json"
            )

            # Send file with embed
            await interaction.followup.send(
                embed=embed,
                file=file
            )

        except Exception as e:
            await handle_error(interaction, e)

async def setup(bot):
    await bot.add_cog(MovesetCommands(bot))