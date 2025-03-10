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
- /say: Make the bot say a message directly in the channel
- /embed: Create an embedded message in the channel
"""

import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Optional, List, Literal
import json
from io import BytesIO

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

    @commands.command(name="say")
    @commands.has_permissions(manage_messages=True)
    async def say(self, ctx, *, message: str):
        """
        Have the bot say something in the channel.
        This command posts the message directly without showing the command.
        """
        try:
            # Delete the command message if we have permissions
            try:
                await ctx.message.delete()
            except:
                pass
                
            # Send the message directly to the channel
            await ctx.send(message)
        except Exception as e:
            error_msg = handle_error(e, "Error sending message")
            await ctx.send(error_msg, ephemeral=True)
            
    @app_commands.command(name="say")
    @app_commands.describe(message="The message to say")
    async def slash_say(self, interaction: discord.Interaction, message: str):
        """Have the bot say something in the channel"""
        try:
            # Hide the command execution
            await interaction.response.defer(ephemeral=True)
            
            # Send the message directly to the channel
            await interaction.channel.send(message)
            
            # Send confirmation only to the command user
            await interaction.followup.send("Message sent!", ephemeral=True)
        except Exception as e:
            error_msg = handle_error(e, "Error sending message")
            await interaction.followup.send(error_msg, ephemeral=True)
            
    @app_commands.command(name="embed")
    @app_commands.describe(
        title="Embed title",
        description="Embed description",
        footer="Optional footer text",
        color="Hex color code (e.g. #FF0000)",
        attachment="Optional attachment file"
    )
    async def embed_message(
        self, 
        interaction: discord.Interaction, 
        title: str,
        description: str,
        footer: Optional[str] = None,
        color: Optional[str] = None,
        attachment: Optional[discord.Attachment] = None
    ):
        """Create an embedded message"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Parse color if provided
            embed_color = discord.Color.blue()  # Default
            if color:
                try:
                    if color.startswith('#'):
                        color = color[1:]
                    embed_color = discord.Color.from_rgb(
                        int(color[0:2], 16),
                        int(color[2:4], 16),
                        int(color[4:6], 16)
                    )
                except:
                    pass  # Keep default if parsing fails
            
            embed = discord.Embed(
                title=title,
                description=description,
                color=embed_color
            )
            
            if footer:
                embed.set_footer(text=footer)
            
            # Handle attachment
            file = None
            if attachment:
                file_data = await attachment.read()
                file = discord.File(fp=BytesIO(file_data), filename=attachment.filename)
                embed.set_image(url=f"attachment://{attachment.filename}")
            
            # Send the embed
            if file:
                await interaction.channel.send(embed=embed, file=file)
            else:
                await interaction.channel.send(embed=embed)
            
            await interaction.followup.send("Embed sent!", ephemeral=True)
        except Exception as e:
            error_msg = handle_error(e, "Error sending embed")
            await interaction.followup.send(error_msg, ephemeral=True)
        
    # Character name autocomplete
    async def character_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete character names"""
        try:
            bot = interaction.client
            # Get all characters
            if hasattr(bot.game_state, 'characters'):
                chars = list(bot.game_state.characters.keys())
            elif hasattr(bot.game_state, 'get_all_characters'):
                chars = [char.name for char in bot.game_state.get_all_characters()]
            else:
                # Fallback in case we can't get characters
                return []
                
            # Filter by current input
            current_lower = current.lower()
            matches = [c for c in chars if current_lower in c.lower()]
            
            # Sort matches for consistency
            matches.sort()
            
            # Return as choices (limited to 25 as per Discord API)
            return [
                app_commands.Choice(name=char, value=char) 
                for char in matches[:25]
            ]
        except Exception as e:
            # Log error but don't crash
            print(f"Error in character_autocomplete: {str(e)}")
            return []
            
    # Move name autocomplete
    async def move_name_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete move names for a character"""
        try:
            # Extract character name from previous options
            character_name = None
            options = None
            
            # Get data from interaction
            if hasattr(interaction, 'namespace') and hasattr(interaction.namespace, 'character'):
                character_name = interaction.namespace.character
            elif hasattr(interaction, 'data') and 'options' in interaction.data:
                options = interaction.data['options']
                for option in options:
                    if option.get('name') == 'character':
                        character_name = option.get('value')
                        break
            
            # If we couldn't find the character, return empty list
            if not character_name:
                print(f"Autocomplete: No character name found")
                return []
                
            # Get the character
            char = self.bot.game_state.get_character(character_name)
            if not char:
                print(f"Autocomplete: Character '{character_name}' not found")
                return []
                
            # See how move data is stored on this character
            move_names = []
            
            # Try getting moves from various places (each character might store them differently)
            # 1. Try list_moves method
            if hasattr(char, 'list_moves') and callable(getattr(char, 'list_moves')):
                move_names = char.list_moves()
                print(f"Autocomplete: Found {len(move_names)} moves using list_moves()")
                
            # 2. Try direct access to moveset
            elif hasattr(char, 'moveset'):
                if hasattr(char.moveset, 'moves'):
                    # Move names might be keys in a dict
                    if isinstance(char.moveset.moves, dict):
                        move_names = list(char.moveset.moves.keys())
                        print(f"Autocomplete: Found {len(move_names)} moves in moveset.moves dict")
                    # Moves might be a list of objects
                    elif isinstance(char.moveset.moves, list):
                        move_names = [m.name if hasattr(m, 'name') else str(m) for m in char.moveset.moves]
                        print(f"Autocomplete: Found {len(move_names)} moves in moveset.moves list")
            
            # If we still don't have moves, use a different approach
            if not move_names:
                print(f"Autocomplete: No moves found using standard methods")
                # Try a more generic approach - look for any attribute that might contain moves
                move_attributes = ['moves', 'move_list', 'move_data', 'movedata']
                for attr in move_attributes:
                    if hasattr(char, attr):
                        attr_value = getattr(char, attr)
                        if isinstance(attr_value, dict):
                            move_names = list(attr_value.keys())
                            print(f"Autocomplete: Found {len(move_names)} moves in {attr} dict")
                            break
                        elif isinstance(attr_value, list):
                            move_names = [m.name if hasattr(m, 'name') else str(m) for m in attr_value]
                            print(f"Autocomplete: Found {len(move_names)} moves in {attr} list")
                            break
            
            # If still no moves, try to dump the character object to see what we have
            if not move_names:
                print(f"Autocomplete: Character object dump:")
                for attr_name in dir(char):
                    if not attr_name.startswith('_'):  # Skip private attributes
                        attr_value = getattr(char, attr_name)
                        if not callable(attr_value):  # Skip methods
                            print(f"  {attr_name}: {type(attr_value)}")
                            if isinstance(attr_value, dict) and len(attr_value) < 10:
                                print(f"    Keys: {list(attr_value.keys())}")
                    
            # Filter by current input (case insensitive)
            current_lower = current.lower()
            matches = []
            for move in move_names:
                if current_lower in move.lower():
                    matches.append(move)
            
            print(f"Autocomplete: Found {len(matches)} matches for '{current}'")
            # Sort matches for consistency
            matches.sort()
            
            # Return as choices (limited to 25 as per Discord API)
            return [
                app_commands.Choice(name=move, value=move) 
                for move in matches[:25]
            ]
        except Exception as e:
            # Log error but don't crash
            print(f"Error in move_name_autocomplete: {str(e)}")
            import traceback
            traceback.print_exc()
            return []

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
                
            # Check if character has a moveset
            if not hasattr(char, 'moveset') or not hasattr(char.moveset, 'moves'):
                await interaction.followup.send(f"{char.name} doesn't have a moveset.")
                return
                
            # Check if character has this move in their moveset
            move_data = None
            
            # Try both direct name lookup and lowercase lookup
            move_name_lower = name.lower()
            if name in char.moveset.moves:
                move_data = char.moveset.moves[name]
            elif move_name_lower in char.moveset.moves:
                move_data = char.moveset.moves[move_name_lower]
            # Also try list_moves with get_move if available
            elif hasattr(char, 'list_moves') and hasattr(char, 'get_move'):
                for move_name in char.list_moves():
                    if move_name.lower() == move_name_lower:
                        move_data = char.get_move(move_name)
                        break

            if not move_data:
                await interaction.followup.send(
                    f"{char.name} doesn't have a move named '{name}' in their moveset. "
                    f"Use '/move create' to add it first, or '/move temp' for a one-time move.",
                    ephemeral=True
                )
                return
        
            # Log move parameters
            if hasattr(self.bot.game_state, 'logger') and hasattr(self.bot.game_state.logger, 'log_move_parameters'):
                self.bot.game_state.logger.log_move_parameters(
                    character,
                    name,
                    target=target,
                    mp_cost=move_data.mp_cost,
                    hp_cost=move_data.hp_cost,
                    star_cost=move_data.star_cost,
                    cast_time=move_data.cast_time,
                    duration=move_data.duration,
                    cooldown=move_data.cooldown,
                    roll_timing=roll_timing if roll_timing else move_data.roll_timing,
                    attack_roll=move_data.attack_roll,
                    damage=move_data.damage,
                    aoe_mode=aoe_mode
                )

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
            
            # Check resource costs
            if char.resources.current_mp < move_data.mp_cost:
                await interaction.followup.send(
                    f"{char.name} doesn't have enough MP! (Needs {move_data.mp_cost}, has {char.resources.current_mp})",
                    ephemeral=True
                )
                return
                
            # Explicit check for uses (make sure this happens before cooldown checks)
            if move_data.uses is not None:
                # Initialize uses_remaining if needed
                if move_data.uses_remaining is None:
                    move_data.uses_remaining = move_data.uses
                    
                # Check if we have uses left
                if move_data.uses_remaining <= 0:
                    await interaction.followup.send(
                        f"{char.name} can't use {name}: No uses remaining (0/{move_data.uses})",
                        ephemeral=True
                    )
                    return
            
            # Import MoveState for cooldown checks
            from core.effects.move import MoveEffect, MoveState, RollTiming
            
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
            
            # Sanitize cooldown value
            cooldown = move_data.cooldown
            if cooldown is not None and cooldown <= 0:
                cooldown = None
                
            # Create move effect from the move data
            # MoveEffect, MoveState already imported above
            from core.effects.manager import apply_effect
            
            move_effect = MoveEffect(
                name=move_data.name,
                description=move_data.description,
                mp_cost=move_data.mp_cost,
                hp_cost=move_data.hp_cost,
                star_cost=move_data.star_cost,
                cast_time=move_data.cast_time,
                duration=move_data.duration,
                cooldown=cooldown,
                cast_description=move_data.cast_description,
                attack_roll=move_data.attack_roll,
                damage=move_data.damage,
                crit_range=move_data.crit_range,
                save_type=move_data.save_type,
                save_dc=move_data.save_dc,
                half_on_save=move_data.half_on_save,
                roll_timing=actual_roll_timing,
                targets=target_chars,
                enable_hit_bonus=move_data.enable_heat_tracking
            )
            
            # Set the AoE mode if specified
            move_effect.combat.aoe_mode = aoe_mode
            
            # Use action stars
            char.use_move_stars(move_data.star_cost, move_data.name)
            
            # Explicitly register cooldown if the move has one
            if cooldown:
                char.action_stars.start_cooldown(move_data.name, cooldown)
                
            # Store limited use info to show in result message
            uses_info = None
            if move_data.uses is not None:
                uses_info = f"Uses: {move_data.uses_remaining}/{move_data.uses}"
            
            # Apply the effect - now properly awaited
            result = await apply_effect(char, move_effect, current_round)
            
            # Add resource updates to the message if any
            if mp_cost != 0 or hp_cost != 0 or star_cost > 0 or uses_info:
                # Extract the main message part (before any bullet points)
                main_message_parts = result.split("\n", 1)
                main_message = main_message_parts[0]
                
                # Prepare resource updates
                resource_updates = []
                if mp_cost != 0:
                    resource_updates.append(f"MP: {char.resources.current_mp}/{char.resources.max_mp}")
                if hp_cost != 0:
                    resource_updates.append(f"HP: {char.resources.current_hp}/{char.resources.max_hp}")
                if star_cost > 0 and hasattr(char, 'action_stars'):
                    if hasattr(char.action_stars, 'current_stars') and hasattr(char.action_stars, 'max_stars'):
                        resource_updates.append(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars}")
                if uses_info:
                    resource_updates.append(uses_info)
                    
                # Add resource updates to main message
                if resource_updates:
                    # Find the last emoji in the main message
                    emoji_index = main_message.rfind("✨")
                    if emoji_index > 0:
                        # Insert resource updates before the last emoji
                        updated_message = (
                            main_message[:emoji_index].rstrip() + 
                            f" | {' | '.join(resource_updates)} " + 
                            main_message[emoji_index:]
                        )
                    else:
                        # Just append if we can't find the closing emoji
                        updated_message = main_message + f" | {' | '.join(resource_updates)}"
                    
                    # Reconstruct result with updated main message
                    if len(main_message_parts) > 1:
                        result = updated_message + "\n" + main_message_parts[1]
                    else:
                        result = updated_message
            
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
        description="Move description (use semicolons for bullet points - include save info here)",
        category="Move category (Offense, Defense, Utility, Other)",
        target="Target character(s) (comma-separated for multiple targets)",
        mp_cost="MP cost (default: 0)",
        hp_cost="HP cost or healing if negative (default: 0)",
        star_cost="Star cost (default: 0)",
        attack_roll="Attack roll expression (e.g., '1d20+int')",
        damage="Damage expression (e.g., '2d6 fire')",
        cast_time="Turns needed to cast (default: 0)",
        duration="Turns the effect lasts (default: 0)",
        cooldown="Turns before usable again (default: 0)",
        roll_timing="When to process attack roll (instant, active, per_turn)",
        aoe_mode="AoE mode: 'single' (one roll) or 'multi' (roll per target)",
        advanced_json="Optional JSON with other advanced parameters and save data"
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
        star_cost: Optional[int] = 0,
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
        Use semicolons in description for bullet points and include save info.
        """
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
                return
                
            # Log move parameters
            if hasattr(self.bot.game_state, 'logger') and hasattr(self.bot.game_state.logger, 'log_move_parameters'):
                self.bot.game_state.logger.log_move_parameters(
                    character,
                    name,
                    description=description,
                    target=target,
                    mp_cost=mp_cost,
                    hp_cost=hp_cost,
                    star_cost=star_cost,
                    cast_time=cast_time,
                    duration=duration,
                    cooldown=cooldown,
                    roll_timing=roll_timing,
                    attack_roll=attack_roll,
                    damage=damage,
                    aoe_mode=aoe_mode,
                    advanced_json=advanced_json
                )                

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
                    
            # Sanitize cooldown - set to None if it's 0 or less
            if cooldown is not None and cooldown <= 0:
                cooldown = None
            
            # Create move effect (temporary)
            from core.effects.move import MoveEffect
            from core.effects.manager import apply_effect
            
            # Get save parameters (for backward compatibility)
            save_type = advanced_params.get('save_type')
            save_dc = advanced_params.get('save_dc')
            half_on_save = advanced_params.get('half_on_save', False)
            
            move_effect = MoveEffect(
                name=name,
                description=description,
                mp_cost=mp_cost,
                hp_cost=hp_cost,
                star_cost=star_cost,
                cast_time=cast_time,
                duration=duration,
                cooldown=cooldown,  # Now properly sanitized
                attack_roll=attack_roll,
                damage=damage,
                targets=target_chars,
                roll_timing=roll_timing,
                # Save parameters from advanced_json only
                save_type=save_type,
                save_dc=save_dc,
                half_on_save=half_on_save,
                # Additional advanced parameters
                crit_range=advanced_params.get('crit_range', 20),
                enable_hit_bonus=advanced_params.get('enable_hit_bonus', False),
                hit_bonus_value=advanced_params.get('hit_bonus_value', 1)
            )
            
            # Set the AoE mode if specified
            move_effect.combat.aoe_mode = aoe_mode
            
            # Use action stars
            char.use_move_stars(star_cost, name)
            
            # Apply the effect - now properly awaited
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
        description="Description of the move (use semicolons for bullet points - include save info here)",
        category="Move category (REQUIRED)",
        mp_cost="MP cost (default: 0)",
        hp_cost="HP cost or healing if negative (default: 0)",
        star_cost="Star cost (default: 0)",
        attack_roll="Attack roll expression (e.g., '1d20+int')",
        damage="Damage expression (e.g., '2d6 fire')",
        cast_time="Turns needed to cast (default: 0)",
        duration="Turns the effect lasts (default: 0)",
        cooldown="Turns before usable again (default: 0)",
        roll_timing="When to process attack roll (instant, active, per_turn)",
        uses="Number of uses (-1 for unlimited)",
        advanced_json="Optional JSON with other advanced parameters and save data"
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
        star_cost: Optional[int] = 0,
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
        Use semicolons in description for bullet points and include save info.
        Advanced_json can be used for specialized parameters.
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
                roll_timing=roll_timing,
                # Advanced parameters from JSON (including save params for backward compatibility)
                save_type=advanced_params.get('save_type'),
                save_dc=advanced_params.get('save_dc'),
                half_on_save=advanced_params.get('half_on_save', False),
                crit_range=advanced_params.get('crit_range', 20),
                conditions=advanced_params.get('conditions', []),
                enable_heat_tracking=advanced_params.get('enable_hit_bonus', False) or 
                                    advanced_params.get('enable_heat_tracking', False)
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
                
            # Add save info from advanced_params if present
            save_details = []
            if advanced_params.get('save_type'):
                save_details.append(f"Save: {advanced_params['save_type']}")
            if advanced_params.get('save_dc'):
                save_details.append(f"DC: {advanced_params['save_dc']}")
            if advanced_params.get('half_on_save'):
                save_details.append(f"Half damage on save")
                
            if save_details:
                details.append("• `" + " | ".join(save_details) + "`")
                
            # Add advanced params summary if used
            if advanced_json:
                adv_summary = []
                if advanced_params.get('crit_range', 20) != 20:
                    adv_summary.append(f"Crit: {advanced_params['crit_range']}-20")
                
                if advanced_params.get('enable_hit_bonus', False) or advanced_params.get('enable_heat_tracking', False):
                    adv_summary.append("Star bonus on hit")
                
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
    
    @app_commands.command(name="edit")
    @app_commands.describe(
        character="Character whose move to edit",
        move_name="Name of the move to edit",
        description="New description (use semicolons for bullet points)",
        category="Change the move category",
        mp_cost="Change MP cost",
        hp_cost="Change HP cost/healing",
        star_cost="Change star cost",
        attack_roll="Change attack roll expression (e.g., '1d20+int')",
        damage="Change damage expression (e.g., '2d6 fire')",
        cast_time="Change cast time",
        duration="Change duration",
        cooldown="Change cooldown",
        uses="Change number of uses (-1 for unlimited)",
        reset_uses="Reset the remaining uses to maximum"
    )
    async def edit_move(
        self,
        interaction: discord.Interaction,
        character: str,
        move_name: str,
        description: Optional[str] = None,
        category: Optional[Literal["Offense", "Utility", "Defense", "Other"]] = None,
        mp_cost: Optional[int] = None,
        hp_cost: Optional[int] = None,
        star_cost: Optional[int] = None,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        cast_time: Optional[int] = None,
        duration: Optional[int] = None,
        cooldown: Optional[int] = None,
        uses: Optional[int] = None,
        reset_uses: Optional[bool] = False
    ):
        """Edit an existing move in a character's moveset"""
        try:
            await interaction.response.defer()
            
            # Get the character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
                return
            
            # Get the move
            move = char.get_move(move_name)
            if not move:
                await interaction.followup.send(f"Move '{move_name}' not found for {character}")
                return
            
            # Track what was changed
            changes = []
            
            # Update fields if provided
            if description is not None:
                move.description = description
                changes.append(f"Description changed")
                
            if category is not None:
                move.category = category
                changes.append(f"Category changed to {category}")
                
            if mp_cost is not None:
                move.mp_cost = mp_cost
                changes.append(f"MP cost changed to {mp_cost}")
                
            if hp_cost is not None:
                move.hp_cost = hp_cost
                changes.append(f"HP cost changed to {hp_cost}")
                
            if star_cost is not None:
                move.star_cost = star_cost
                changes.append(f"Star cost changed to {star_cost}")
                
            if attack_roll is not None:
                move.attack_roll = attack_roll if attack_roll.strip() else None
                changes.append(f"Attack roll changed to {attack_roll if attack_roll.strip() else 'None'}")
                
            if damage is not None:
                move.damage = damage if damage.strip() else None
                changes.append(f"Damage changed to {damage if damage.strip() else 'None'}")
                
            if cast_time is not None:
                move.cast_time = cast_time if cast_time > 0 else None
                changes.append(f"Cast time changed to {cast_time if cast_time > 0 else 'None'}")
                
            if duration is not None:
                move.duration = duration if duration > 0 else None
                changes.append(f"Duration changed to {duration if duration > 0 else 'None'}")
                
            if cooldown is not None:
                move.cooldown = cooldown if cooldown > 0 else None
                changes.append(f"Cooldown changed to {cooldown if cooldown > 0 else 'None'}")
                
            if uses is not None:
                old_uses = move.uses
                move.uses = uses if uses > 0 else None
                if move.uses != old_uses:
                    # Reset uses_remaining if uses changed
                    move.uses_remaining = move.uses
                    changes.append(f"Uses changed to {uses if uses > 0 else 'Unlimited'}")
                    
            if reset_uses and move.uses is not None:
                move.uses_remaining = move.uses
                changes.append(f"Uses reset to {move.uses}")
            
            # If nothing was changed
            if not changes:
                await interaction.followup.send(f"No changes made to '{move_name}'")
                return
            
            # Update moveset and save character
            char.moveset.moves[move_name.lower()] = move
            await self.bot.db.save_character(char, debug_paths=['moveset'])
            
            # Create confirmation embed
            embed = discord.Embed(
                title=f"✏️ Move Edited: {move_name}",
                description=f"Move has been updated for {character}",
                color=discord.Color.green()
            )
            
            # Add changes
            embed.add_field(
                name="Changes",
                value="\n".join(f"• {change}" for change in changes),
                inline=False
            )
            
            # Show key properties
            properties = []
            if move.mp_cost != 0:
                properties.append(f"MP Cost: {move.mp_cost}")
            if move.hp_cost != 0:
                properties.append(f"HP Cost: {move.hp_cost}")
            if move.star_cost != 0:
                properties.append(f"Star Cost: {move.star_cost}")
            if move.uses is not None:
                properties.append(f"Uses: {move.uses_remaining}/{move.uses}")
            if move.cooldown is not None:
                properties.append(f"Cooldown: {move.cooldown}T")
                
            if properties:
                embed.add_field(
                    name="Current Properties",
                    value="\n".join(f"• {prop}" for prop in properties),
                    inline=True
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            error_msg = handle_error(e, "Error editing move")
            await interaction.followup.send(error_msg, ephemeral=True)
    
    # Add autocomplete for move_name
    edit_move.autocomplete('character')(character_autocomplete)
    edit_move.autocomplete('move_name')(move_name_autocomplete)

    @app_commands.command(name="uses")
    @app_commands.describe(
        character="Character whose move to modify",
        move_name="Name of the move to modify",
        operation="Operation to perform on move uses",
        value="Value for add/subtract/set operations (not needed for restore)"
    )
    async def manage_move_uses(
        self,
        interaction: discord.Interaction,
        character: str,
        move_name: str,
        operation: Literal["add", "subtract", "set", "restore"],
        value: Optional[int] = None
    ):
        """
        Manage the uses of a character's move.
        You can add, subtract, set, or restore the uses of a move.
        """
        try:
            await interaction.response.defer()
            
            # Get the character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
                return
            
            # Get the move
            move = char.get_move(move_name)
            if not move:
                await interaction.followup.send(f"Move '{move_name}' not found for {character}")
                return
            
            # Check if the move has limited uses
            if move.uses is None:
                await interaction.followup.send(
                    f"Move '{move_name}' doesn't have limited uses.",
                    ephemeral=True
                )
                return
            
            # Ensure uses_remaining is initialized
            if move.uses_remaining is None:
                move.uses_remaining = move.uses
                
            # Track original value for changelog
            original_uses = move.uses_remaining
            
            # Perform the requested operation
            if operation == "add":
                if value is None:
                    await interaction.followup.send(
                        "Please specify a value to add.",
                        ephemeral=True
                    )
                    return
                    
                move.uses_remaining = min(move.uses, move.uses_remaining + value)
                operation_text = f"Added {value} uses"
                
            elif operation == "subtract":
                if value is None:
                    await interaction.followup.send(
                        "Please specify a value to subtract.",
                        ephemeral=True
                    )
                    return
                    
                move.uses_remaining = max(0, move.uses_remaining - value)
                operation_text = f"Subtracted {value} uses"
                
            elif operation == "set":
                if value is None:
                    await interaction.followup.send(
                        "Please specify a value to set.",
                        ephemeral=True
                    )
                    return
                    
                move.uses_remaining = min(move.uses, max(0, value))
                operation_text = f"Set uses to {value}"
                
            elif operation == "restore":
                move.uses_remaining = move.uses
                operation_text = "Restored to maximum uses"
                
            # Save character
            await self.bot.db.save_character(char, debug_paths=['moveset'])
            
            # Create confirmation embed
            embed = discord.Embed(
                title=f"✏️ Move Uses Updated: {move_name}",
                description=f"Updated uses for {character}'s {move_name}",
                color=discord.Color.green()
            )
            
            # Add operation info
            embed.add_field(
                name="Operation",
                value=operation_text,
                inline=False
            )
            
            # Add before/after
            embed.add_field(
                name="Before",
                value=f"{original_uses}/{move.uses}",
                inline=True
            )
            
            embed.add_field(
                name="After",
                value=f"{move.uses_remaining}/{move.uses}",
                inline=True
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            error_msg = handle_error(e, "Error managing move uses")
            await interaction.followup.send(error_msg, ephemeral=True)

    # Add autocompletes for move_name
    manage_move_uses.autocomplete('character')(character_autocomplete)
    manage_move_uses.autocomplete('move_name')(move_name_autocomplete)

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