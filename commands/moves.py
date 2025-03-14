"""
Move command system for using, creating, and managing moves.

Features:
- Move usage with resource tracking
- Move creation and modification
- Attack roll processing
- Turn phase handling
"""

import discord
from discord import app_commands
from discord.ext import commands
import logging
import json
import re
import asyncio
from typing import Optional, List, Dict, Any, Tuple

from core.character import Character, StatType
from core.effects.move import MoveEffect, MoveState, RollTiming
from modules.moves.data import MoveData, Moveset
from utils.formatting import MessageFormatter
from utils.dice import DiceRoller
from utils.error_handler import handle_error

logger = logging.getLogger(__name__)

class MoveCommands(commands.GroupCog, name="move"):
    """Commands for move usage and management"""
    
    def __init__(self, bot):
        self.bot = bot
        self.pending_attacks = {}
        super().__init__()
    
    @app_commands.command(name="use", description="Use a stored move")
    @app_commands.describe(
        character="Character using the move",
        name="Name of the move to use",
        target="Target character(s) (comma-separated)",
        roll_timing="When to process attack roll: instant, active, or per_turn",
        aoe_mode="How to handle multiple targets: single (one roll) or multi (roll per target)"
    )
    async def use_move(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        target: Optional[str] = None,
        roll_timing: Optional[str] = None,
        aoe_mode: Optional[str] = "single"
    ):
        """Use a stored move from a character's moveset"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found.")
                return
                
            # Get the move
            move = char.get_move(name)
            if not move:
                await interaction.followup.send(f"Move '{name}' not found for {character}.")
                return
                
            # Find target characters
            targets = []
            if target:
                target_names = [t.strip() for t in target.split(',')]
                for target_name in target_names:
                    target_char = self.bot.game_state.get_character(target_name)
                    if target_char:
                        targets.append(target_char)
                    else:
                        await interaction.followup.send(
                            f"Target '{target_name}' not found. Continuing with available targets."
                        )
                
                # Validate AoE mode + multihit compatibility
                if 'multihit' in (move.attack_roll or '') and aoe_mode == 'multi' and len(targets) > 1:
                    await interaction.followup.send(
                        "⚠️ Multihit attacks are not compatible with multiple targets in 'multi' mode. "
                        "Using 'single' mode instead."
                    )
                    aoe_mode = 'single'
            
            # Check if we're in combat
            in_combat = (hasattr(self.bot, 'initiative_tracker') and 
                            self.bot.initiative_tracker.state.value == 'active')
            current_round = self.bot.initiative_tracker.round_number if in_combat else 0
            
            # Check if move can be used (cooldown, uses)
            try:
                can_use, reason = move.can_use(current_round)
                if not can_use:
                    await interaction.followup.send(f"Cannot use {name}: {reason}")
                    return
            except AttributeError:
                # Fallback if can_use method doesn't exist or is incompatible
                pass
                
            # Check action star cost
            if hasattr(char, 'can_use_move') and move.star_cost > 0:
                can_use, reason = char.can_use_move(move.star_cost, move.name)
                if not can_use:
                    await interaction.followup.send(f"Cannot use {name}: {reason}")
                    return
                
            # Create move effect with all parameters
            move_effect = MoveEffect(
                name=move.name,
                description=move.description,
                star_cost=move.star_cost,
                mp_cost=move.mp_cost,
                hp_cost=move.hp_cost,
                cast_time=move.cast_time,
                duration=move.duration,
                cooldown=move.cooldown,
                cast_description=move.cast_description,
                attack_roll=move.attack_roll,
                damage=move.damage,
                crit_range=move.crit_range,
                conditions=move.conditions if hasattr(move, 'conditions') else [],
                roll_timing=roll_timing or move.roll_timing,
                uses=move.uses,
                targets=targets,
                bonus_on_hit=move.bonus_on_hit if hasattr(move, 'bonus_on_hit') else None,
                aoe_mode=aoe_mode or getattr(move, 'aoe_mode', 'single')
            )
            
            # Apply effect and get feedback message
            result = await char.add_effect(move_effect, current_round)
            
            # Mark move as used
            move.use(current_round)
            
            # Use action stars if required
            if hasattr(char, 'use_move_stars') and move.star_cost > 0:
                char.use_move_stars(move.star_cost, move.name)
            
            # Save character state
            await self.bot.db.save_character(char)
            
            # Save any targets that were modified
            for target_char in targets:
                await self.bot.db.save_character(target_char)
                
            # Display result
            await interaction.followup.send(result)
            
        except Exception as e:
            error_msg, traceback = handle_error(e, "Error using move")
            logger.error(traceback)
            await interaction.followup.send(error_msg, ephemeral=True)
    
    @app_commands.command(name="temp", description="Use a temporary move (not saved)")
    @app_commands.describe(
        character="Character using the move",
        name="Name of the move",
        description="Move description",
        mp_cost="MP cost (negative for regen)",
        hp_cost="HP cost (negative for healing)",
        star_cost="Action star cost",
        cast_time="Cast time (in turns)",
        duration="Active duration (in turns)",
        cooldown="Cooldown after use (in turns)",
        target="Target character(s) (comma-separated)",
        attack_roll="Attack roll formula (e.g., 1d20+str)",
        damage="Damage formula (e.g., 2d6+str fire)",
        crit_range="Natural roll for critical hit",
        roll_timing="When to process attack roll: instant, active, or per_turn",
        advanced_json="Advanced parameters in JSON format"
    )
    async def temp_move(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        description: str,
        mp_cost: int = 0,
        hp_cost: int = 0,
        star_cost: int = 0,
        cast_time: Optional[int] = None,
        duration: Optional[int] = None,
        cooldown: Optional[int] = None,
        target: Optional[str] = None,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        crit_range: int = 20,
        roll_timing: str = "active",
        advanced_json: Optional[str] = None
    ):
        """Use a temporary move without saving it to character's moveset"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found.")
                return
                
            # Find target characters
            targets = []
            if target:
                target_names = [t.strip() for t in target.split(',')]
                for target_name in target_names:
                    target_char = self.bot.game_state.get_character(target_name)
                    if target_char:
                        targets.append(target_char)
                    else:
                        await interaction.followup.send(
                            f"Target '{target_name}' not found. Continuing with available targets."
                        )
            
            # Check if we're in combat
            in_combat = (hasattr(self.bot, 'initiative_tracker') and 
                         self.bot.initiative_tracker.state.value == 'active')
            current_round = self.bot.initiative_tracker.round_number if in_combat else 0
                
            # Check action star cost
            if hasattr(char, 'can_use_move') and star_cost > 0:
                can_use, reason = char.can_use_move(star_cost, name)
                if not can_use:
                    await interaction.followup.send(f"Cannot use {name}: {reason}")
                    return
                
            # Parse advanced JSON parameter
            extra_params = {}
            if advanced_json:
                try:
                    extra_params = json.loads(advanced_json)
                except json.JSONDecodeError:
                    await interaction.followup.send(
                        f"Invalid JSON in advanced_json parameter: {advanced_json}",
                        ephemeral=True
                    )
                    return
            
            # Extract parameters from advanced_json
            bonus_on_hit = extra_params.get('bonus_on_hit')
            aoe_mode = extra_params.get('aoe_mode', 'single')
            conditions = extra_params.get('conditions', [])
                
            # Create move effect
            move_effect = MoveEffect(
                name=name,
                description=description,
                star_cost=star_cost,
                mp_cost=mp_cost,  # Can be negative for mana regen
                hp_cost=hp_cost,  # Can be negative for healing
                cast_time=cast_time,
                duration=duration,
                cooldown=cooldown,
                cast_description=extra_params.get('cast_description'),
                attack_roll=attack_roll,
                damage=damage,
                crit_range=crit_range,
                conditions=conditions,
                roll_timing=roll_timing,
                targets=targets,
                bonus_on_hit=bonus_on_hit,
                aoe_mode=aoe_mode
            )
            
            # Apply effect and get feedback message
            result = await self.bot.game_state.apply_effect(
                char,
                move_effect,
                current_round
            )
            
            # Use action stars if required
            if hasattr(char, 'use_move_stars') and star_cost > 0:
                char.use_move_stars(star_cost, name)
            
            # Save character state
            await self.bot.db.save_character(char)
            
            # Save any targets that were modified
            for target_char in targets:
                await self.bot.db.save_character(target_char)
                
            # Display result
            await interaction.followup.send(result)
            
        except Exception as e:
            error_msg, traceback = handle_error(e, "Error in temp_move")
            logger.error(traceback)
            await interaction.followup.send(error_msg, ephemeral=True)

    @app_commands.command(name="create", description="Create a new move for a character")
    @app_commands.describe(
        character="Character to add the move to",
        name="Name of the move",
        description="Move description",
        category="Move category (Offense, Defense, Utility)",
        mp_cost="MP cost (negative for regen)",
        hp_cost="HP cost (negative for healing)",
        star_cost="Action star cost",
        cast_time="Cast time (in turns)",
        duration="Active duration (in turns)",
        cooldown="Cooldown after use (in turns)",
        attack_roll="Attack roll formula (e.g., 1d20+str)",
        damage="Damage formula (e.g., 2d6+str fire)",
        crit_range="Natural roll for critical hit",
        roll_timing="When to process attack roll: instant, active, or per_turn",
        uses="Number of uses per combat (-1 for unlimited)",
        advanced_json="Advanced parameters in JSON format"
    )
    async def create_move(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        description: str,
        category: str = "Offense",
        mp_cost: int = 0,
        hp_cost: int = 0,
        star_cost: int = 0,
        cast_time: Optional[int] = None,
        duration: Optional[int] = None,
        cooldown: Optional[int] = None,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        crit_range: int = 20,
        roll_timing: str = "active",
        uses: int = -1,
        advanced_json: Optional[str] = None
    ):
        """Create a new move and add it to a character's moveset"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found.")
                return
                
            # Check if move name already exists
            if char.get_move(name):
                await interaction.followup.send(
                    f"Move '{name}' already exists for {character}. Use /update_move to modify it.",
                    ephemeral=True
                )
                return
                
            # Parse advanced JSON parameter
            extra_params = {}
            if advanced_json:
                try:
                    extra_params = json.loads(advanced_json)
                except json.JSONDecodeError:
                    await interaction.followup.send(
                        f"Invalid JSON in advanced_json parameter: {advanced_json}",
                        ephemeral=True
                    )
                    return
            
            # Create move data
            move_data = MoveData(
                name=name,
                description=description,
                mp_cost=mp_cost,
                hp_cost=hp_cost,
                star_cost=star_cost,
                cast_time=cast_time,
                duration=duration,
                cooldown=cooldown,
                cast_description=extra_params.get('cast_description'),
                attack_roll=attack_roll,
                damage=damage,
                crit_range=crit_range,
                roll_timing=roll_timing,
                category=category,
                uses=None if uses < 0 else uses,
                uses_remaining=None if uses < 0 else uses,
                bonus_on_hit=extra_params.get('bonus_on_hit'),
                aoe_mode=extra_params.get('aoe_mode', 'single'),
                conditions=extra_params.get('conditions', [])
            )
            
            # Add move to character
            char.add_move(move_data)
            
            # Save character state
            await self.bot.db.save_character(char)
            
            # Format response
            embed = discord.Embed(
                title=f"Move Created: {name}",
                description=description,
                color=discord.Color.green()
            )
            
            # Basic parameters
            basics = []
            if mp_cost != 0:
                sign = '-' if mp_cost > 0 else '+'
                basics.append(f"MP: {sign}{abs(mp_cost)}")
            if hp_cost != 0:
                sign = '-' if hp_cost > 0 else '+'
                basics.append(f"HP: {sign}{abs(hp_cost)}")
            if star_cost > 0:
                basics.append(f"Stars: {star_cost}")
            if uses >= 0:
                basics.append(f"Uses: {uses}")
                
            if basics:
                embed.add_field(
                    name="Resource Costs",
                    value="\n".join(basics),
                    inline=True
                )
                
            # Timing parameters
            timing = []
            if cast_time:
                timing.append(f"Cast Time: {cast_time} turn(s)")
            if duration:
                timing.append(f"Duration: {duration} turn(s)")
            if cooldown:
                timing.append(f"Cooldown: {cooldown} turn(s)")
                
            if timing:
                embed.add_field(
                    name="Timing",
                    value="\n".join(timing),
                    inline=True
                )
                
            # Combat parameters
            combat = []
            if attack_roll:
                combat.append(f"Attack: {attack_roll}")
            if damage:
                combat.append(f"Damage: {damage}")
            if crit_range != 20:
                combat.append(f"Crit Range: {crit_range}+")
            if roll_timing:
                combat.append(f"Roll Timing: {roll_timing}")
                
            if combat:
                embed.add_field(
                    name="Combat",
                    value="\n".join(combat),
                    inline=True
                )
                
            # Advanced parameters
            if extra_params:
                advanced = []
                if 'bonus_on_hit' in extra_params:
                    advanced.append(f"Bonus on Hit: {extra_params['bonus_on_hit']}")
                if 'aoe_mode' in extra_params:
                    advanced.append(f"AoE Mode: {extra_params['aoe_mode']}")
                if 'conditions' in extra_params:
                    advanced.append(f"Conditions: {', '.join(extra_params['conditions'])}")
                    
                if advanced:
                    embed.add_field(
                        name="Advanced Parameters",
                        value="\n".join(advanced),
                        inline=False
                    )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            error_msg, traceback = handle_error(e, "Error creating move")
            logger.error(traceback)
            await interaction.followup.send(error_msg, ephemeral=True)
    
    @app_commands.command(name="update", description="Update an existing move")
    @app_commands.describe(
        character="Character with the move",
        name="Name of the move to update",
        description="New move description",
        category="New move category",
        mp_cost="New MP cost (negative for regen)",
        hp_cost="New HP cost (negative for healing)",
        star_cost="New action star cost",
        cast_time="New cast time (in turns)",
        duration="New active duration (in turns)",
        cooldown="New cooldown after use (in turns)",
        attack_roll="New attack roll formula",
        damage="New damage formula",
        crit_range="New natural roll for critical hit",
        roll_timing="New roll timing",
        uses="New number of uses per combat (-1 for unlimited)",
        advanced_json="New advanced parameters in JSON format"
    )
    async def update_move(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
        mp_cost: Optional[int] = None,
        hp_cost: Optional[int] = None,
        star_cost: Optional[int] = None,
        cast_time: Optional[int] = None,
        duration: Optional[int] = None,
        cooldown: Optional[int] = None,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        crit_range: Optional[int] = None,
        roll_timing: Optional[str] = None,
        uses: Optional[int] = None,
        advanced_json: Optional[str] = None
    ):
        """Update an existing move in a character's moveset"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found.")
                return
                
            # Get existing move
            move = char.get_move(name)
            if not move:
                await interaction.followup.send(f"Move '{name}' not found for {character}.")
                return
                
            # Parse advanced JSON parameter
            extra_params = {}
            if advanced_json:
                try:
                    extra_params = json.loads(advanced_json)
                except json.JSONDecodeError:
                    await interaction.followup.send(
                        f"Invalid JSON in advanced_json parameter: {advanced_json}",
                        ephemeral=True
                    )
                    return
            
            # Update move data (only non-None values)
            if description is not None:
                move.description = description
            if category is not None:
                move.category = category
            if mp_cost is not None:
                move.mp_cost = mp_cost
            if hp_cost is not None:
                move.hp_cost = hp_cost
            if star_cost is not None:
                move.star_cost = star_cost
            if cast_time is not None:
                move.cast_time = cast_time
            if duration is not None:
                move.duration = duration
            if cooldown is not None:
                move.cooldown = cooldown
            if attack_roll is not None:
                move.attack_roll = attack_roll
            if damage is not None:
                move.damage = damage
            if crit_range is not None:
                move.crit_range = crit_range
            if roll_timing is not None:
                move.roll_timing = roll_timing
            if uses is not None:
                move.uses = None if uses < 0 else uses
                move.uses_remaining = None if uses < 0 else uses
                
            # Handle advanced parameters
            if 'cast_description' in extra_params:
                move.cast_description = extra_params['cast_description']
            if 'bonus_on_hit' in extra_params:
                move.bonus_on_hit = extra_params['bonus_on_hit']
            if 'aoe_mode' in extra_params:
                move.aoe_mode = extra_params['aoe_mode']
            if 'conditions' in extra_params:
                move.conditions = extra_params['conditions']
            
            # Save character state
            await self.bot.db.save_character(char)
            
            # Format response
            embed = discord.Embed(
                title=f"Move Updated: {name}",
                description=move.description,
                color=discord.Color.green()
            )
            
            # Basic parameters
            basics = []
            if move.mp_cost != 0:
                sign = '-' if move.mp_cost > 0 else '+'
                basics.append(f"MP: {sign}{abs(move.mp_cost)}")
            if move.hp_cost != 0:
                sign = '-' if move.hp_cost > 0 else '+'
                basics.append(f"HP: {sign}{abs(move.hp_cost)}")
            if move.star_cost > 0:
                basics.append(f"Stars: {move.star_cost}")
            if move.uses is not None:
                basics.append(f"Uses: {move.uses_remaining}/{move.uses}")
                
            if basics:
                embed.add_field(
                    name="Resource Costs",
                    value="\n".join(basics),
                    inline=True
                )
                
            # Timing parameters
            timing = []
            if move.cast_time:
                timing.append(f"Cast Time: {move.cast_time} turn(s)")
            if move.duration:
                timing.append(f"Duration: {move.duration} turn(s)")
            if move.cooldown:
                timing.append(f"Cooldown: {move.cooldown} turn(s)")
                
            if timing:
                embed.add_field(
                    name="Timing",
                    value="\n".join(timing),
                    inline=True
                )
                
            # Combat parameters
            combat = []
            if move.attack_roll:
                combat.append(f"Attack: {move.attack_roll}")
            if move.damage:
                combat.append(f"Damage: {move.damage}")
            if move.crit_range != 20:
                combat.append(f"Crit Range: {move.crit_range}+")
            if move.roll_timing:
                combat.append(f"Roll Timing: {move.roll_timing}")
                
            if combat:
                embed.add_field(
                    name="Combat",
                    value="\n".join(combat),
                    inline=True
                )
                
            # Advanced parameters
            advanced = []
            if move.bonus_on_hit:
                advanced.append(f"Bonus on Hit: {move.bonus_on_hit}")
            if move.aoe_mode and move.aoe_mode != 'single':
                advanced.append(f"AoE Mode: {move.aoe_mode}")
            if move.conditions:
                advanced.append(f"Conditions: {', '.join(move.conditions)}")
                
            if advanced:
                embed.add_field(
                    name="Advanced Parameters",
                    value="\n".join(advanced),
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            error_msg, traceback = handle_error(e, "Error updating move")
            logger.error(traceback)
            await interaction.followup.send(error_msg, ephemeral=True)
    
    @app_commands.command(name="delete", description="Delete a move from a character")
    @app_commands.describe(
        character="Character to remove the move from",
        name="Name of the move to delete"
    )
    async def delete_move(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str
    ):
        """Delete a move from a character's moveset"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found.")
                return
                
            # Check if move exists
            if not char.get_move(name):
                await interaction.followup.send(
                    f"Move '{name}' not found for {character}.",
                    ephemeral=True
                )
                return
                
            # Remove move
            char.remove_move(name)
            
            # Save character state
            await self.bot.db.save_character(char)
            
            await interaction.followup.send(f"Move '{name}' deleted from {character}'s moveset.")
            
        except Exception as e:
            error_msg, traceback = handle_error(e, "Error deleting move")
            logger.error(traceback)
            await interaction.followup.send(error_msg, ephemeral=True)
    
    @app_commands.command(name="list", description="List all moves for a character")
    @app_commands.describe(
        character="Character to list moves for",
        category="Filter by category (leave empty for all)"
    )
    async def list_moves(
        self,
        interaction: discord.Interaction,
        character: str,
        category: Optional[str] = None
    ):
        """List all moves in a character's moveset"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found.")
                return
                
            # Get moves
            if hasattr(char, 'moveset') and hasattr(char.moveset, 'get_moves_by_category'):
                moves = char.moveset.get_moves_by_category(category)
            else:
                moves = []
                
            if not moves:
                if category:
                    await interaction.followup.send(
                        f"{character} has no moves in the {category} category."
                    )
                else:
                    await interaction.followup.send(f"{character} has no moves.")
                return
                
            # Create embed
            embed = discord.Embed(
                title=f"{character}'s Moves",
                description=f"Total: {len(moves)}",
                color=discord.Color.blue()
            )
            
            # Group by category
            by_category = {}
            for move in moves:
                cat = move.category
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(move)
                
            # Add fields for each category
            for cat, cat_moves in by_category.items():
                move_lines = []
                for move in cat_moves:
                    # Basic info
                    line = f"**{move.name}**"
                    
                    # Costs
                    costs = []
                    if move.mp_cost != 0:
                        costs.append(f"MP:{move.mp_cost}")
                    if move.hp_cost != 0:
                        costs.append(f"HP:{move.hp_cost}")
                    if move.star_cost > 0:
                        costs.append(f"⭐:{move.star_cost}")
                        
                    if costs:
                        line += f" ({', '.join(costs)})"
                        
                    # Uses if limited
                    if move.uses is not None:
                        line += f" - {move.uses_remaining}/{move.uses} uses"
                        
                    # Cooldown status if in combat
                    if (move.cooldown and move.last_used_round and 
                        hasattr(self.bot, 'initiative_tracker') and 
                        self.bot.initiative_tracker.state.value == 'active'):
                        
                        current_round = self.bot.initiative_tracker.round_number
                        rounds_since = current_round - move.last_used_round
                        if rounds_since < move.cooldown:
                            remaining = move.cooldown - rounds_since
                            line += f" (CD: {remaining})"
                    
                    move_lines.append(line)
                
                embed.add_field(
                    name=cat,
                    value="\n".join(move_lines),
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            error_msg, traceback = handle_error(e, "Error listing moves")
            logger.error(traceback)
            await interaction.followup.send(error_msg, ephemeral=True)
    
    @app_commands.command(name="info", description="Show detailed information about a move")
    @app_commands.describe(
        character="Character that has the move",
        name="Name of the move"
    )
    async def move_info(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str
    ):
        """Show detailed information about a specific move"""
        try:
            await interaction.response.defer()
            
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"Character '{character}' not found.")
                return
                
            # Get move
            move = char.get_move(name)
            if not move:
                await interaction.followup.send(
                    f"Move '{name}' not found for {character}.",
                    ephemeral=True
                )
                return
                
            # Create embed
            embed = discord.Embed(
                title=f"{move.name}",
                description=move.description,
                color=discord.Color.blue()
            )
            
            # Basic parameters
            basics = []
            if move.mp_cost != 0:
                sign = '-' if move.mp_cost > 0 else '+'
                basics.append(f"MP: {sign}{abs(move.mp_cost)}")
            if move.hp_cost != 0:
                sign = '-' if move.hp_cost > 0 else '+'
                basics.append(f"HP: {sign}{abs(move.hp_cost)}")
            if move.star_cost > 0:
                basics.append(f"Stars: {move.star_cost}")
            if move.uses is not None:
                basics.append(f"Uses: {move.uses_remaining}/{move.uses}")
                
            if basics:
                embed.add_field(
                    name="Resource Costs",
                    value="\n".join(basics),
                    inline=True
                )
                
            # Timing parameters
            timing = []
            if move.cast_time:
                timing.append(f"Cast Time: {move.cast_time} turn(s)")
            if move.duration:
                timing.append(f"Duration: {move.duration} turn(s)")
            if move.cooldown:
                timing.append(f"Cooldown: {move.cooldown} turn(s)")
                
                # Show cooldown status if applicable
                if (move.last_used_round and 
                    hasattr(self.bot, 'initiative_tracker') and 
                    self.bot.initiative_tracker.state.value == 'active'):
                    
                    current_round = self.bot.initiative_tracker.round_number
                    rounds_since = current_round - move.last_used_round
                    if rounds_since < move.cooldown:
                        remaining = move.cooldown - rounds_since
                        timing.append(f"⏳ On cooldown: {remaining} turn(s) remaining")
                
            if timing:
                embed.add_field(
                    name="Timing",
                    value="\n".join(timing),
                    inline=True
                )
                
            # Combat parameters
            combat = []
            if move.attack_roll:
                combat.append(f"Attack: {move.attack_roll}")
            if move.damage:
                combat.append(f"Damage: {move.damage}")
            if move.crit_range != 20:
                combat.append(f"Crit Range: {move.crit_range}+")
            if move.roll_timing:
                combat.append(f"Roll Timing: {move.roll_timing}")
                
            if combat:
                embed.add_field(
                    name="Combat",
                    value="\n".join(combat),
                    inline=True
                )
                
            # Advanced parameters
            advanced = []
            if move.bonus_on_hit:
                advanced.append(f"Bonus on Hit: {move.bonus_on_hit}")
            if move.aoe_mode and move.aoe_mode != 'single':
                advanced.append(f"AoE Mode: {move.aoe_mode}")
            if move.conditions:
                advanced.append(f"Conditions: {', '.join(move.conditions)}")
                
            if advanced:
                embed.add_field(
                    name="Advanced Parameters",
                    value="\n".join(advanced),
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            error_msg, traceback = handle_error(e, "Error showing move info")
            logger.error(traceback)
            await interaction.followup.send(error_msg, ephemeral=True)

async def setup(bot):
    await bot.add_cog(MoveCommands(bot))