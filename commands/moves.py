"""
## src/commands/moves.py

Commands for creating and using character moves.
Handles creating MoveData for character movesets and applying MoveEffects.

Commands:
- /move use: Use a one-off move (added as effect)
- /move temp: Create a temporary effect-based move (stored in character.effects)
- /move create: Create a permanent move (stored in character.moveset)
- /move list: List a character's available moves
- /move info: Show detailed information about a move
"""

import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Optional, List

from core.effects.move import MoveEffect, MoveState, RollTiming
from core.effects.condition import ConditionType
from modules.moves.data import MoveData, Moveset
from modules.moves.loader import MoveLoader
from utils.error_handler import handle_error
from utils.formatting import MessageFormatter

logger = logging.getLogger(__name__)

class MoveCommands(commands.GroupCog, name="move"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
        
    @app_commands.command(name="use")
    @app_commands.describe(
        character="Character using the move",
        name="Name of the move to use",
        target="Target character (optional)"
    )
    async def use_move(
        self, 
        interaction: discord.Interaction,
        character: str,
        name: str,
        target: Optional[str] = None
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
            
            # Get target if specified
            target_char = None
            if target:
                target_char = self.bot.game_state.get_character(target)
                if not target_char:
                    await interaction.followup.send(f"Target '{target}' not found")
                    return
            
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
            
            # First check if there's an existing move effect in cooldown
            existing_cooldown = False
            for effect in char.effects:
                if hasattr(effect, 'name') and effect.name == name and hasattr(effect, 'state'):
                    if effect.state == MoveState.COOLDOWN:
                        # There's already a cooldown effect for this move
                        phase = effect.phases.get(MoveState.COOLDOWN)
                        if phase:
                            remaining = phase.duration - phase.turns_completed
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
                roll_timing=move_data.roll_timing,
                targets=[target_char] if target_char else []
            )
            
            # Apply the effect
            result = char.add_effect(move_effect, current_round)
            
            # Use action stars
            char.use_move_stars(move_data.star_cost, move_data.name)
            
            # Save character state
            await self.bot.db.save_character(char, debug_paths=['effects', 'action_stars', 'moveset'])
            
            # Format response using single-line approach with bullets for details
            primary_message = f"⚔️ `{char.name} uses {name}` ⚔️"
            
            # Collect details
            details = []
            
            # Add cost info
            costs = []
            if move_data.mp_cost > 0:
                costs.append(f"💙 MP: {move_data.mp_cost}")
            if move_data.hp_cost > 0:
                costs.append(f"❤️ HP: {move_data.hp_cost}")
            elif move_data.hp_cost < 0:
                costs.append(f"❤️ Healing: {abs(move_data.hp_cost)}")
            if move_data.star_cost > 0:
                costs.append(f"⭐ Stars: {move_data.star_cost}")
                
            if costs:
                details.append("• `" + " | ".join(costs) + "`")
                
            # Add target info if applicable
            if target_char:
                details.append(f"• `Target: {target_char.name}`")
                
            # Add timing info
            timing = []
            if move_data.cast_time:
                timing.append(f"Cast: {move_data.cast_time} turns")
            if move_data.duration:
                timing.append(f"Duration: {move_data.duration} turns")
            if move_data.cooldown:
                timing.append(f"Cooldown: {move_data.cooldown} turns")
                
            if timing:
                details.append("• `" + " | ".join(timing) + "`")
                
            # Add description if available
            if move_data.description:
                # Split by semicolons if present
                if ';' in move_data.description:
                    for part in move_data.description.split(';'):
                        if part := part.strip():
                            details.append(f"• `{part}`")
                else:
                    details.append(f"• `{move_data.description}`")
                    
            # Combine message with details
            response = primary_message
            if details:
                response += "\n" + "\n".join(details)
                
            await interaction.followup.send(response)
            
        except Exception as e:
            error_msg = handle_error(e, "Error using move")
            await interaction.followup.send(error_msg, ephemeral=True)
            
    @app_commands.command(name="temp")
    @app_commands.describe(
        character="Character using the move",
        name="Name of the move to use",
        description="Move description",
        target="Target character (optional)",
        mp_cost="MP cost (default: 0)",
        hp_cost="HP cost or healing if negative (default: 0)",
        star_cost="Star cost (default: 1)",
        attack_roll="Attack roll expression (e.g., '1d20+int')",
        damage="Damage expression (e.g., '2d6 fire')",
        crit_range="Natural roll needed for critical hit (default: 20)",
        cast_time="Turns needed to cast (default: 0)",
        duration="Turns the effect lasts (default: 0)",
        cooldown="Turns before usable again (default: 0)",
        save_type="Required saving throw (str, dex, con, etc.)",
        save_dc="Difficulty class for saves (8+prof+stat)",
        roll_timing="When to apply rolls (instant, active, per_turn)",
        track_heat="Whether to track heat stacks (default: False)"
    )
    async def temp_move(
        self, 
        interaction: discord.Interaction,
        character: str,
        name: str,
        description: str,
        target: Optional[str] = None,
        mp_cost: Optional[int] = 0,
        hp_cost: Optional[int] = 0, 
        star_cost: Optional[int] = 1,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        crit_range: Optional[int] = 20,
        cast_time: Optional[int] = None,
        duration: Optional[int] = None,
        cooldown: Optional[int] = None,
        save_type: Optional[str] = None,
        save_dc: Optional[str] = None,
        roll_timing: Optional[str] = "active",
        track_heat: Optional[bool] = False
    ):
        """
        Create and use a temporary one-time move.
        This creates an effect but does NOT save to the moveset.
        """
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
                return
                
            # Get target if specified
            target_char = None
            if target:
                target_char = self.bot.game_state.get_character(target)
                if not target_char:
                    await interaction.followup.send(f"Target '{target}' not found")
                    return
            
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
                crit_range=crit_range,
                save_type=save_type,
                save_dc=save_dc,
                roll_timing=roll_timing,
                targets=[target_char] if target_char else [],
                enable_heat_tracking=track_heat
            )
            
            # Apply the effect
            result = char.add_effect(move_effect, current_round)
            
            # Use action stars
            char.use_move_stars(star_cost, name)
            
            # Save character state
            await self.bot.db.save_character(char, debug_paths=['effects', 'action_stars'])
            
            # Format response using single-line approach with bullets for details
            primary_message = f"✨ `{char.name} uses {name} (Temporary)` ✨"
            
            # Collect details
            details = []
            
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
                
            # Add target info if applicable
            if target_char:
                details.append(f"• `Target: {target_char.name}`")
                
            # Add timing info
            timing = []
            if cast_time:
                timing.append(f"Cast: {cast_time} turns")
            if duration:
                timing.append(f"Duration: {duration} turns")
            if cooldown:
                timing.append(f"Cooldown: {cooldown} turns")
                
            if timing:
                details.append("• `" + " | ".join(timing) + "`")
                
            # Add attack info if applicable
            attack_details = []
            if attack_roll:
                attack_details.append(f"Attack: {attack_roll}")
            if damage:
                attack_details.append(f"Damage: {damage}")
            if crit_range != 20:
                attack_details.append(f"Crit: {crit_range}-20")
                
            if attack_details:
                details.append("• `" + " | ".join(attack_details) + "`")
                    
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
            error_msg = handle_error(e, "Error using temporary move")
            await interaction.followup.send(error_msg, ephemeral=True)
    
    @app_commands.command(name="create")
    @app_commands.describe(
        character="Character to add the move to",
        name="Name of the move",
        description="Description of the move",
        mp_cost="MP cost (default: 0)",
        hp_cost="HP cost or healing if negative (default: 0)",
        star_cost="Star cost (default: 1)",
        attack_roll="Attack roll expression (e.g., '1d20+int')",
        damage="Damage expression (e.g., '2d6 fire')",
        crit_range="Natural roll needed for critical hit (default: 20)",
        cast_time="Turns needed to cast (default: 0)",
        duration="Turns the effect lasts (default: 0)",
        cooldown="Turns before usable again (default: 0)",
        uses="Number of uses (-1 for unlimited)",
        save_type="Required saving throw (str, dex, con, etc.)",
        save_dc="Difficulty class for saves (8+prof+stat)",
        half_on_save="Whether save halves damage (default: False)",
        roll_timing="When to apply rolls (instant, active, per_turn)",
        track_heat="Whether to track heat stacks (default: False)"
    )
    async def create_move(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        description: str,
        mp_cost: Optional[int] = 0,
        hp_cost: Optional[int] = 0,
        star_cost: Optional[int] = 1,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        crit_range: Optional[int] = 20,
        cast_time: Optional[int] = None,
        duration: Optional[int] = None,
        cooldown: Optional[int] = None,
        uses: Optional[int] = -1,
        save_type: Optional[str] = None,
        save_dc: Optional[str] = None,
        half_on_save: Optional[bool] = False,
        roll_timing: Optional[str] = "active",
        track_heat: Optional[bool] = False
    ):
        """
        Create and add a permanent move to a character's moveset.
        This adds to character.moveset, not character.effects.
        """
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
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
                crit_range=crit_range,
                save_type=save_type,
                save_dc=save_dc,
                half_on_save=half_on_save,
                roll_timing=roll_timing,
                enable_heat_tracking=track_heat
            )
            
            # Add to character's moveset
            char.add_move(move_data)
            
            # Save character state with debugging enabled for movesets
            await self.bot.db.save_character(char, debug_paths=['moveset'])
            
            # Format response using single-line approach with bullets for details
            primary_message = f"📓 `Move Created: {name} added to {char.name}'s moveset` 📓"
            
            # Collect details
            details = []
            
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
            if crit_range != 20:
                attack_details.append(f"Crit: {crit_range}-20")
            if save_type:
                save_text = f"{save_type.upper()} Save"
                if save_dc:
                    save_text += f" (DC: {save_dc})"
                if half_on_save:
                    save_text += " (Half on save)"
                attack_details.append(save_text)
                    
            if attack_details:
                details.append("• `" + " | ".join(attack_details) + "`")
                
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
        """List all moves in a character's moveset"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found")
                return
                
            # Get move list
            move_names = char.list_moves()
            
            if not move_names:
                await interaction.followup.send(f"{char.name} has no moves in their moveset")
                return
                
            # Create result embed
            embed = discord.Embed(
                title=f"{char.name}'s Moves",
                description=f"Found {len(move_names)} moves",
                color=discord.Color.blue()
            )
            
            # Add moves with details
            for move_name in move_names:
                move = char.get_move(move_name)
                if move:
                    details = [move.description] if move.description else []
                    
                    # Add costs
                    costs = []
                    if move.mp_cost:
                        costs.append(f"💙 MP: {move.mp_cost}")
                    if move.hp_cost > 0:
                        costs.append(f"❤️ HP: {move.hp_cost}")
                    elif move.hp_cost < 0:
                        costs.append(f"❤️ Healing: {abs(move.hp_cost)}")
                    if move.star_cost:
                        costs.append(f"⭐ Stars: {move.star_cost}")
                        
                    if costs:
                        details.append(" | ".join(costs))
                        
                    # Add usage
                    usage = []
                    if move.uses is not None:
                        usage.append(f"Uses: {move.uses_remaining}/{move.uses}")
                    if move.cooldown:
                        if move.last_used_round:
                            # Calculate cooldown remaining if in combat
                            if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                                current_round = self.bot.initiative_tracker.round_number
                                elapsed = current_round - move.last_used_round
                                remaining = max(0, move.cooldown - elapsed)
                                usage.append(f"Cooldown: {remaining}/{move.cooldown}")
                            else:
                                usage.append(f"Cooldown: {move.cooldown}")
                        else:
                            usage.append(f"Cooldown: {move.cooldown}")
                            
                    if usage:
                        details.append(" | ".join(usage))
                        
                    # Add attack info
                    if move.attack_roll or move.damage:
                        attack = []
                        if move.attack_roll:
                            attack.append(f"Attack: {move.attack_roll}")
                        if move.damage:
                            attack.append(f"Damage: {move.damage}")
                        details.append(" | ".join(attack))
                        
                    embed.add_field(
                        name=move.name,
                        value="\n".join(details) if details else "No details",
                        inline=False
                    )
                
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            error_msg = handle_error(e, "Error listing moves")
            await interaction.followup.send(error_msg, ephemeral=True)
            
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
                
            # Create result embed
            embed = discord.Embed(
                title=move_data.name,
                description=move_data.description,
                color=discord.Color.blue()
            )
            
            # Basic info
            basic_info = []
            if move_data.mp_cost:
                basic_info.append(f"💙 MP Cost: {move_data.mp_cost}")
            if move_data.hp_cost > 0:
                basic_info.append(f"❤️ HP Cost: {move_data.hp_cost}")
            elif move_data.hp_cost < 0:
                basic_info.append(f"❤️ HP Healing: {abs(move_data.hp_cost)}")
            if move_data.star_cost:
                basic_info.append(f"⭐ Star Cost: {move_data.star_cost}")
            if move_data.enable_heat_tracking:
                basic_info.append("🔥 Tracks Heat")
                
            if basic_info:
                embed.add_field(name="Basic Info", value="\n".join(basic_info), inline=False)
                
            # Timing info
            timing_info = []
            if move_data.cast_time:
                timing_info.append(f"Cast Time: {move_data.cast_time} turns")
            if move_data.duration:
                timing_info.append(f"Duration: {move_data.duration} turns")
            if move_data.cooldown:
                timing_info.append(f"Cooldown: {move_data.cooldown} turns")
                
            if timing_info:
                embed.add_field(name="Timing", value="\n".join(timing_info), inline=True)
                
            # Usage info
            usage_info = []
            if move_data.uses is not None:
                usage_info.append(f"Uses: {move_data.uses_remaining}/{move_data.uses}")
                
            # Check if on cooldown
            if move_data.last_used_round is not None and move_data.cooldown:
                if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                    current_round = self.bot.initiative_tracker.round_number
                    elapsed = current_round - move_data.last_used_round
                    if elapsed < move_data.cooldown:
                        remaining = move_data.cooldown - elapsed
                        usage_info.append(f"On Cooldown: {remaining} turns remaining")
                else:
                    # Also check the cooldown in effects list
                    cooldown_effect = None
                    for effect in char.effects:
                        if (hasattr(effect, 'name') and effect.name == move_data.name and 
                            hasattr(effect, 'state') and effect.state == MoveState.COOLDOWN):
                            cooldown_effect = effect
                            break
                            
                    if cooldown_effect and hasattr(cooldown_effect, 'phases'):
                        phase = cooldown_effect.phases.get(MoveState.COOLDOWN)
                        if phase:
                            remaining = phase.duration - phase.turns_completed
                            if remaining > 0:
                                usage_info.append(f"On Cooldown: {remaining} turns remaining")
                    else:
                        usage_info.append(f"Last Used: Round {move_data.last_used_round}")
                
            if usage_info:
                embed.add_field(name="Usage", value="\n".join(usage_info), inline=True)
                
            # Combat info
            combat_info = []
            if move_data.attack_roll:
                combat_info.append(f"Attack Roll: {move_data.attack_roll}")
            if move_data.damage:
                combat_info.append(f"Damage: {move_data.damage}")
            if move_data.crit_range != 20:
                combat_info.append(f"Crit Range: {move_data.crit_range}-20")
            if move_data.save_type:
                save_text = f"Save: {move_data.save_type.upper()}"
                if move_data.save_dc:
                    save_text += f" (DC: {move_data.save_dc})"
                if move_data.half_on_save:
                    save_text += " (Half damage on save)"
                combat_info.append(save_text)
            if move_data.roll_timing and move_data.roll_timing != "active":
                roll_text = {
                    "instant": "Rolls are made immediately on use",
                    "active": "Rolls are made when active phase begins",
                    "per_turn": "Rolls are made each turn during duration"
                }.get(move_data.roll_timing, f"Roll Timing: {move_data.roll_timing}")
                combat_info.append(roll_text)
                
            if combat_info:
                embed.add_field(name="Combat", value="\n".join(combat_info), inline=False)
                
            # Custom parameters if any
            if move_data.custom_parameters:
                custom = []
                for key, value in move_data.custom_parameters.items():
                    custom.append(f"{key}: {value}")
                if custom:
                    embed.add_field(name="Custom Parameters", value="\n".join(custom), inline=False)
                    
            await interaction.followup.send(embed=embed)
            
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
        # Try to find character in previous options
        options = interaction.data.get('options', [])
        character = None
        for option in options:
            if option.get('name') == 'character':
                character = option.get('value')
                break
                
        if not character:
            return []
            
        # Get character's moves
        char = self.bot.game_state.get_character(character)
        if not char:
            return []
            
        move_names = char.list_moves()
        matches = [m for m in move_names if current.lower() in m.lower()]
        return [app_commands.Choice(name=move, value=move) for move in matches[:25]]
            
    # Add autocompletes to commands
    list_moves.autocomplete('character')(character_autocomplete)
    use_move.autocomplete('character')(character_autocomplete)
    use_move.autocomplete('target')(character_autocomplete)
    temp_move.autocomplete('character')(character_autocomplete)
    temp_move.autocomplete('target')(character_autocomplete)
    create_move.autocomplete('character')(character_autocomplete)
    move_info.autocomplete('character')(character_autocomplete)
    move_info.autocomplete('move_name')(move_name_autocomplete)
    delete_move.autocomplete('character')(character_autocomplete)
    delete_move.autocomplete('move_name')(move_name_autocomplete)

async def setup(bot):
    await bot.add_cog(MoveCommands(bot))