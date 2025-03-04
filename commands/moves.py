"""
## src/commands/moves.py

Commands for creating and using character moves.
Handles creating MoveData for character movesets and applying MoveEffects.

Commands:
- /move use: Use a move from character's moveset (applies as effect)
- /move temp: Create and use a temporary move (not saved to moveset)
- /move create: Create a permanent move (saved to character.moveset)
- /move list: List a character's available moves
- /move info: Show detailed information about a move
- /move delete: Delete a move from a character's moveset
"""

import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Optional, List, Literal
import json

from core.effects.move import MoveEffect, MoveState, RollTiming
from core.effects.manager import apply_effect  # Import apply_effect directly
from core.effects.condition import ConditionType
from modules.moves.data import MoveData, Moveset
from modules.moves.loader import MoveLoader
from modules.menu.action_handler import ActionHandler
from utils.error_handler import handle_error
from utils.formatting import MessageFormatter

logger = logging.getLogger(__name__)

class MoveCommands(commands.GroupCog, name="move"):
    def __init__(self, bot):
        self.bot = bot
        self.action_handler = ActionHandler(bot)
        super().__init__()
        
    @app_commands.command(name="use")
    @app_commands.describe(
        character="Character using the move",
        name="Name of the move to use",
        target="Target character(s) (comma-separated for multiple targets)",
        roll_timing="When to process attack roll (instant, active, per_turn)",
        aoe_mode="AoE mode: 'single' (one roll) or 'multi' (roll per target)"
    )
    async def use_move(
        self, 
        interaction: discord.Interaction,
        character: str,
        name: str,
        target: Optional[str] = None,
        roll_timing: Optional[Literal["instant", "active", "per_turn"]] = None,
        aoe_mode: Optional[Literal["single", "multi"]] = "single"
    ):
        """
        Use a move that is stored in a character's moveset.
        Applies the move as an effect.
        """
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
                return
            
            # Get targets if specified (supports multiple targets)
            target_chars = []
            if target:
                target_names = [t.strip() for t in target.split(',')]
                for target_name in target_names:
                    target_char = self.bot.game_state.get_character(target_name)
                    if not target_char:
                        await interaction.followup.send(f"Target '{target_name}' not found")
                        return
                    target_chars.append(target_char)
            
            # Get current round number for accurate cooldown checking
            current_round = 1
            if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                current_round = self.bot.initiative_tracker.round_number
            
            # Check if character has this move in their moveset
            move_data = char.get_move(name)
            if not move_data:
                await interaction.followup.send(
                    f"{char.name} doesn't have a move named '{name}' in their moveset. "
                    f"Use '/move create' to add it first, or '/move temp' for a one-time move.",
                    ephemeral=True
                )
                return
            
            # Check resource costs
            if char.resources.current_mp < move_data.mp_cost:
                await interaction.followup.send(
                    f"{char.name} doesn't have enough MP! (Needs {move_data.mp_cost}, has {char.resources.current_mp})",
                    ephemeral=True
                )
                return
            
            # Check for existing move effects with this name
            existing_cooldown = False
            for effect in char.effects:
                if hasattr(effect, 'name') and effect.name == name and hasattr(effect, 'state'):
                    if effect.state == MoveState.COOLDOWN:
                        # There's already a cooldown effect for this move
                        remaining = effect.get_remaining_turns()
                        await interaction.followup.send(
                            f"{char.name} can't use {name}: On cooldown ({remaining} turns remaining)",
                            ephemeral=True
                        )
                        return
                    existing_cooldown = True
                    break
            
            # Only check moveset cooldown if no active cooldown effect
            if not existing_cooldown:
                # Check star costs and cooldowns
                can_use, reason = move_data.can_use(current_round)
                if not can_use:
                    await interaction.followup.send(
                        f"{char.name} can't use {name}: {reason}",
                        ephemeral=True
                    )
                    return
                
            # Check action stars
            can_use_stars, stars_reason = char.can_use_move(move_data.star_cost)
            if not can_use_stars:
                await interaction.followup.send(
                    f"{char.name} can't use this move: {stars_reason}",
                    ephemeral=True
                )
                return
            
            # Mark the move as used (for cooldown tracking in moveset)
            move_data.use(current_round)
            
            # Override roll_timing if specified in command
            actual_roll_timing = roll_timing if roll_timing else move_data.roll_timing
            
            # Create move effect from the move data
            move_effect = MoveEffect(
                name=move_data.name,
                description=move_data.description,
                mp_cost=move_data.mp_cost,
                hp_cost=move_data.hp_cost,
                star_cost=move_data.star_cost,
                cast_time=move_data.cast_time,
                duration=move_data.duration,
                cooldown=move_data.cooldown,
                cast_description=move_data.cast_description,
                attack_roll=move_data.attack_roll,
                damage=move_data.damage,
                crit_range=move_data.crit_range,
                save_type=move_data.save_type,
                save_dc=move_data.save_dc,
                half_on_save=move_data.half_on_save,
                roll_timing=actual_roll_timing,  # Use potentially overridden value
                targets=target_chars,
                enable_heat_tracking=move_data.enable_heat_tracking
            )
            
            # Set the AoE mode if specified
            move_effect.aoe_mode = aoe_mode
            
            # Use action stars
            char.use_move_stars(move_data.star_cost, move_data.name)
            
            # Explicitly register cooldown if the move has one
            if move_data.cooldown:
                char.action_stars.start_cooldown(move_data.name, move_data.cooldown)
            
            # Apply the effect
            result = await apply_effect(char, move_effect, current_round)
            
            # Save character state
            await self.bot.db.save_character(char, debug_paths=['effects', 'action_stars', 'moveset'])
            
            # Send response
            await interaction.followup.send(result)
            
        except Exception as e:
            error_msg = handle_error(e, "Error using move")
            logger.error(f"Error in use_move: {str(e)}", exc_info=True)
            await interaction.followup.send(error_msg, ephemeral=True)
            
    @app_commands.command(name="temp")
    @app_commands.describe(
        character="Character using the move",
        name="Name of the move to use",
        description="Move description (use semicolons for bullet points)",
        category="Move category (Offense, Defense, Utility, Other)",
        target="Target character(s) (comma-separated for multiple targets)",
        mp_cost="MP cost (default: 0)",
        hp_cost="HP cost or healing if negative (default: 0)",
        star_cost="Star cost (default: 1)",
        attack_roll="Attack roll expression (e.g., '1d20+int')",
        damage="Damage expression (e.g., '2d6 fire')",
        cast_time="Turns needed to cast (default: 0)",
        duration="Turns the effect lasts (default: 0)",
        cooldown="Turns before usable again (default: 0)",
        roll_timing="When to process attack roll (instant, active, per_turn)",
        aoe_mode="AoE mode: 'single' (one roll) or 'multi' (roll per target)",
        advanced_json="Optional JSON with advanced parameters (save_type, half_on_save, etc.)"
    )
    async def temp_move(
        self, 
        interaction: discord.Interaction,
        character: str,
        name: str,
        description: str,
        category: Literal["Offense", "Defense", "Utility", "Other"],
        target: Optional[str] = None,
        mp_cost: Optional[int] = 0,
        hp_cost: Optional[int] = 0, 
        star_cost: Optional[int] = 1,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        cast_time: Optional[int] = None,
        duration: Optional[int] = None,
        cooldown: Optional[int] = None,
        roll_timing: Optional[Literal["instant", "active", "per_turn"]] = "active",
        aoe_mode: Optional[Literal["single", "multi"]] = "single",
        advanced_json: Optional[str] = None
    ):
        """
        Create and use a temporary one-time move.
        This creates an effect but does NOT save to the moveset.
        Use advanced_json for specialized parameters like save_type, half_on_save, etc.
        """
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
                return
                
            # Get targets if specified (supports multiple targets)
            target_chars = []
            if target:
                target_names = [t.strip() for t in target.split(',')]
                for target_name in target_names:
                    target_char = self.bot.game_state.get_character(target_name)
                    if not target_char:
                        await interaction.followup.send(f"Target '{target_name}' not found")
                        return
                    target_chars.append(target_char)
            
            # Check resource costs
            if char.resources.current_mp < mp_cost:
                await interaction.followup.send(
                    f"{char.name} doesn't have enough MP! (Needs {mp_cost}, has {char.resources.current_mp})",
                    ephemeral=True
                )
                return
                
            # Check star costs
            can_use, reason = char.can_use_move(star_cost)
            if not can_use:
                await interaction.followup.send(
                    f"{char.name} can't use this move: {reason}",
                    ephemeral=True
                )
                return
            
            # Get current round number
            current_round = 1
            if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                current_round = self.bot.initiative_tracker.round_number
            
            # Parse advanced JSON parameters if provided
            advanced_params = {}
            if advanced_json:
                try:
                    advanced_params = json.loads(advanced_json)
                except json.JSONDecodeError as e:
                    await interaction.followup.send(
                        f"Error in advanced_json: {str(e)}. Please check your JSON syntax.",
                        ephemeral=True
                    )
                    return
            
            # Create move effect (temporary)
            move_effect = MoveEffect(
                name=name,
                description=description,
                mp_cost=mp_cost,
                hp_cost=hp_cost,
                star_cost=star_cost,
                cast_time=cast_time,
                duration=duration,
                cooldown=cooldown,
                attack_roll=attack_roll,
                damage=damage,
                targets=target_chars,
                roll_timing=roll_timing,
                # Advanced parameters from JSON
                crit_range=advanced_params.get('crit_range', 20),
                save_type=advanced_params.get('save_type'),
                save_dc=advanced_params.get('save_dc'),
                half_on_save=advanced_params.get('half_on_save', False),
                enable_heat_tracking=advanced_params.get('enable_heat_tracking', False)
            )
            
            # Set the AoE mode if specified
            move_effect.aoe_mode = aoe_mode
            
            # Use action stars
            char.use_move_stars(star_cost, name)
            
            # Apply the effect
            result = await apply_effect(char, move_effect, current_round)
            
            # Save character state with debug paths enabled
            await self.bot.db.save_character(char, debug_paths=['effects', 'action_stars'])
            
            # Send response
            await interaction.followup.send(result)
            
        except Exception as e:
            error_msg = handle_error(e, "Error using temporary move")
            logger.error(f"Error in temp_move: {str(e)}", exc_info=True)
            await interaction.followup.send(error_msg, ephemeral=True)
    
    @app_commands.command(name="create")
    @app_commands.describe(
        character="Character to add the move to",
        name="Name of the move",
        description="Description of the move (use semicolons for bullet points)",
        category="Move category (REQUIRED)",
        mp_cost="MP cost (default: 0)",
        hp_cost="HP cost or healing if negative (default: 0)",
        star_cost="Star cost (default: 1)",
        attack_roll="Attack roll expression (e.g., '1d20+int')",
        damage="Damage expression (e.g., '2d6 fire')",
        cast_time="Turns needed to cast (default: 0)",
        duration="Turns the effect lasts (default: 0)",
        cooldown="Turns before usable again (default: 0)",
        roll_timing="When to process attack roll (instant, active, per_turn)",
        uses="Number of uses (-1 for unlimited)",
        advanced_json="Optional JSON with advanced parameters (save_type, half_on_save, etc.)"
    )
    async def create_move(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        description: str,
        category: Literal["Offense", "Utility", "Defense", "Other"],
        mp_cost: Optional[int] = 0,
        hp_cost: Optional[int] = 0,
        star_cost: Optional[int] = 1,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        cast_time: Optional[int] = None,
        duration: Optional[int] = None,
        cooldown: Optional[int] = None,
        roll_timing: Optional[Literal["instant", "active", "per_turn"]] = "active",
        uses: Optional[int] = -1,
        advanced_json: Optional[str] = None
    ):
        """
        Create and add a permanent move to a character's moveset.
        Use advanced_json for specialized parameters like save_type, half_on_save, etc.
        """
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
                return
            
            # Parse advanced JSON parameters if provided
            advanced_params = {}
            if advanced_json:
                try:
                    advanced_params = json.loads(advanced_json)
                except json.JSONDecodeError as e:
                    await interaction.followup.send(
                        f"Error in advanced_json: {str(e)}. Please check your JSON syntax.",
                        ephemeral=True
                    )
                    return
            
            # Create move data (permanent, not an effect)
            move_data = MoveData(
                name=name,
                description=description,
                mp_cost=mp_cost,
                hp_cost=hp_cost,
                star_cost=star_cost,
                cast_time=cast_time,
                duration=duration,
                cooldown=cooldown if cooldown and cooldown > 0 else None,
                uses=uses if uses and uses > 0 else None,
                attack_roll=attack_roll,
                damage=damage,
                category=category,
                roll_timing=roll_timing,  # Added roll_timing parameter
                # Advanced parameters from JSON
                crit_range=advanced_params.get('crit_range', 20),
                save_type=advanced_params.get('save_type'),
                save_dc=advanced_params.get('save_dc'),
                half_on_save=advanced_params.get('half_on_save', False),
                conditions=advanced_params.get('conditions', []),
                enable_heat_tracking=advanced_params.get('enable_heat_tracking', False),
                target_selection=advanced_params.get('target_selection', 'manual')
            )
            
            # Add to character's moveset
            char.add_move(move_data)
            
            # Save character state with debugging enabled for movesets
            await self.bot.db.save_character(char, debug_paths=['moveset'])
            
            # Format response using single-line approach with bullets for details
            primary_message = f"📓 `Move Created: {name} added to {char.name}'s moveset` 📓"
            
            # Collect details
            details = []
            
            # Add category info prominently
            details.append(f"• `Category: {category}`")
            
            # Add cost info
            costs = []
            if mp_cost > 0:
                costs.append(f"💙 MP: {mp_cost}")
            if hp_cost > 0:
                costs.append(f"❤️ HP: {hp_cost}")
            elif hp_cost < 0:
                costs.append(f"❤️ Healing: {abs(hp_cost)}")
            if star_cost > 0:
                costs.append(f"⭐ Stars: {star_cost}")
                
            if costs:
                details.append("• `" + " | ".join(costs) + "`")
                
            # Add usage info
            usage = []
            if uses and uses > 0:
                usage.append(f"Uses: {uses}")
            if cooldown and cooldown > 0:
                usage.append(f"Cooldown: {cooldown} turns")
            if cast_time:
                usage.append(f"Cast Time: {cast_time} turns")
            if duration:
                usage.append(f"Duration: {duration} turns")
                
            if usage:
                details.append("• `" + " | ".join(usage) + "`")
                
            # Add attack info if applicable
            attack_details = []
            if attack_roll:
                attack_details.append(f"Attack: {attack_roll}")
            if damage:
                attack_details.append(f"Damage: {damage}")
            if roll_timing and roll_timing != "active":
                attack_details.append(f"Roll Timing: {roll_timing}")
                
            if attack_details:
                details.append("• `" + " | ".join(attack_details) + "`")
                
            # Add advanced params summary if used
            if advanced_json:
                adv_summary = []
                if advanced_params.get('save_type'):
                    save_info = f"{advanced_params['save_type'].upper()} Save"
                    if advanced_params.get('save_dc'):
                        save_info += f" (DC: {advanced_params['save_dc']})"
                    if advanced_params.get('half_on_save'):
                        save_info += " (Half on save)"
                    adv_summary.append(save_info)
                
                if advanced_params.get('crit_range', 20) != 20:
                    adv_summary.append(f"Crit: {advanced_params['crit_range']}-20")
                
                if advanced_params.get('enable_heat_tracking'):
                    adv_summary.append("Heat tracking enabled")
                
                if adv_summary:
                    details.append("• `Advanced: " + " | ".join(adv_summary) + "`")
                
            # Add description with semicolon splitting
            if description:
                if ';' in description:
                    for part in description.split(';'):
                        if part := part.strip():
                            details.append(f"• `{part}`")
                else:
                    details.append(f"• `{description}`")
                
            # Combine message with details
            response = primary_message
            if details:
                response += "\n" + "\n".join(details)
                
            await interaction.followup.send(response)
            
        except Exception as e:
            error_msg = handle_error(e, "Error creating move")
            await interaction.followup.send(error_msg, ephemeral=True)
            
    @app_commands.command(name="list")
    @app_commands.describe(character="Character whose moves to list")
    async def list_moves(self, interaction: discord.Interaction, character: str):
        """List all moves in a character's moveset with interactive UI"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
                return
            
            # Initialize action handler if needed
            if not hasattr(self, 'action_handler') or not self.action_handler:
                self.action_handler = ActionHandler(self.bot)
            
            # Get number of moves
            move_count = len(char.list_moves())
            
            if move_count == 0:
                # No moves found
                embed = discord.Embed(
                    title=f"{char.name}'s Moves",
                    description=f"{char.name} has no moves. Use `/move create` to add moves.",
                    color=discord.Color.blue()
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Use action handler to show moves with pagination and categories
            await self.action_handler.show_moves(interaction, char)
            
        except Exception as e:
            # Safe error handling that won't crash
            logger.error(f"Error in list_moves: {str(e)}", exc_info=True)
            error_embed = discord.Embed(
                title="Error Listing Moves",
                description=f"An error occurred: {str(e)}",
                color=discord.Color.red()
            )
            try:
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            except:
                # If followup fails, try response
                try:
                    await interaction.response.send_message(embed=error_embed, ephemeral=True)
                except:
                    # Last resort
                    pass
            
    @app_commands.command(name="info")
    @app_commands.describe(
        character="Character who has the move",
        move_name="Name of the move to view"
    )
    async def move_info(
        self,
        interaction: discord.Interaction,
        character: str,
        move_name: str
    ):
        """Show detailed information about a move"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
                return
                
            # Get move
            move_data = char.get_move(move_name)
            if not move_data:
                await interaction.followup.send(f"Move '{move_name}' not found for {char.name}")
                return
                
            # Create result embed using the ActionHandler
            info_embed = self.action_handler.create_move_info_embed(char, move_data)
            await interaction.followup.send(embed=info_embed)
            
        except Exception as e:
            error_msg = handle_error(e, "Error getting move info")
            await interaction.followup.send(error_msg, ephemeral=True)
    
    @app_commands.command(name="delete")
    @app_commands.describe(
        character="Character who has the move",
        move_name="Name of the move to delete"
    )
    async def delete_move(
        self,
        interaction: discord.Interaction,
        character: str,
        move_name: str
    ):
        """Delete a move from a character's moveset"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
                return
                
            # Try to remove the move
            if not char.remove_move(move_name):
                await interaction.followup.send(f"Move '{move_name}' not found for {char.name}")
                return
                
            # Also clean up any active move effects with this name
            for effect in char.effects[:]:  # Use copy since we're modifying the list
                if hasattr(effect, 'name') and effect.name == move_name:
                    if hasattr(effect, 'on_expire'):
                        # Handle async or sync on_expire
                        if hasattr(effect.on_expire, '__await__'):
                            await effect.on_expire(char)
                        else:
                            effect.on_expire(char)
                    char.effects.remove(effect)
                
            # Save character state
            await self.bot.db.save_character(char, debug_paths=['moveset', 'effects'])
            
            # Confirm deletion
            await interaction.followup.send(f"🗑️ `Removed '{move_name}' from {char.name}'s moveset` 🗑️")
            
        except Exception as e:
            error_msg = handle_error(e, "Error deleting move")
            await interaction.followup.send(error_msg, ephemeral=True)

    # Character name autocomplete
    async def character_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete character names"""
        chars = list(self.bot.game_state.characters.keys())
        matches = [c for c in chars if current.lower() in c.lower()]
        return [app_commands.Choice(name=char, value=char) for char in matches[:25]]
            
    # Move name autocomplete
    async def move_name_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete move names for a character"""
        try:
            # Try to find character in previous options
            character_name = None
            
            # Extract the options from the interaction data
            if hasattr(interaction, 'data') and 'options' in interaction.data:
                options = interaction.data['options']
                for option in options:
                    if option.get('name') == 'character':
                        character_name = option.get('value')
                        break
                    
            if not character_name:
                return []
                
            # Get character's moves
            char = self.bot.game_state.get_character(character_name)
            if not char:
                # Try to load from database if not in game state
                char_data = await self.bot.db.load_character(character_name)
                if not char_data or 'moveset' not in char_data:
                    return []
                    
                # Extract move names directly from database data
                moves_data = char_data.get('moveset', {}).get('moves', {})
                move_names = list(moves_data.keys())
            else:
                # Get from character object
                move_names = char.list_moves()
            
            # Filter by current input (case insensitive)
            current_lower = current.lower()
            matches = [m for m in move_names if current_lower in m.lower()]
            
            # Sort matches for consistency
            matches.sort()
            
            # Return as choices (limited to 25 as per Discord API)
            return [
                app_commands.Choice(name=move, value=move) 
                for move in matches[:25]
            ]
        except Exception as e:
            # Log error but don't crash
            logger.error(f"Error in move_name_autocomplete: {str(e)}", exc_info=True)
            return []
            
    # Add autocompletes to commands
    list_moves.autocomplete('character')(character_autocomplete)
    use_move.autocomplete('character')(character_autocomplete)
    use_move.autocomplete('name')(move_name_autocomplete)
    temp_move.autocomplete('character')(character_autocomplete)
    create_move.autocomplete('character')(character_autocomplete)
    move_info.autocomplete('character')(character_autocomplete)
    move_info.autocomplete('move_name')(move_name_autocomplete)
    delete_move.autocomplete('character')(character_autocomplete)
    delete_move.autocomplete('move_name')(move_name_autocomplete)

async def setup(bot):
    await bot.add_cog(MoveCommands(bot))