"""
Move command system for using, creating, and managing moves.

Features:
- Move usage with resource tracking
- Move creation and modification
- Attack roll processing
- Turn phase handling
- Roll modifier effect handling
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
from core.effects.rollmod import RollModifierType, RollModifierEffect
from core.effects.manager import apply_effect  # Import apply_effect directly
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
    
    async def character_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for character names"""
        try:
            # Get all characters from the database
            chars = await self.bot.db._refs['characters'].get()
            if not chars:
                return []
            
            # Filter based on current input
            matches = [
                app_commands.Choice(name=name, value=name)
                for name in chars.keys()
                if name != "combat_state" and current.lower() in name.lower()
            ]
            return matches[:25]  # Discord limits to 25 choices
        except Exception as e:
            logger.error(f"Error in character autocomplete: {e}", exc_info=True)
            return []
    
    async def move_name_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for move names based on selected character"""
        try:
            # Get the character name from the interaction
            char_name = interaction.namespace.character
            if not char_name:
                return []
            
            # Try to get character from game state
            char = self.bot.game_state.get_character(char_name)
            if not char:
                # If not in memory, try to load from database
                char_data = await self.bot.db._refs['characters'].child(char_name).get()
                if not char_data or 'moveset' not in char_data or 'moves' not in char_data['moveset']:
                    return []
                
                # Get moves from database
                moves = char_data['moveset']['moves']
                choices = []
                for key, move_data in moves.items():
                    name = move_data.get('name', key)
                    if current.lower() in name.lower():
                        choices.append(app_commands.Choice(name=name, value=name))
                return choices[:25]
            
            # Get moves from character in memory
            if hasattr(char, 'moveset') and hasattr(char.moveset, 'list_moves'):
                moves = char.list_moves()
                return [
                    app_commands.Choice(name=name, value=name)
                    for name in moves
                    if current.lower() in name.lower()
                ][:25]
            
            return []
        except Exception as e:
            logger.error(f"Error in move name autocomplete: {e}", exc_info=True)
            return []
    
    @app_commands.command(name="use", description="Use a stored move")
    @app_commands.describe(
        character="Character using the move",
        name="Name of the move to use",
        target="Target character(s) (comma-separated)",
        roll_timing="When to process attack roll: instant, active, or per_turn",
        aoe_mode="How to handle multiple targets: single (one roll) or multi (roll per target)"
    )
    @app_commands.autocomplete(character=character_autocomplete, name=move_name_autocomplete)
    async def use_move(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        target: Optional[str] = None,
        roll_timing: Optional[str] = None,
        aoe_mode: Optional[str] = "single"
    ):
        """
        Use a stored move from a character's moveset.
        
        This command:
        - Retrieves a move from the character's saved moveset in Firebase
        - Creates a MoveEffect with all the stored parameters
        - Applies the effect to the character
        - Handles resource costs, cooldowns, and usage tracking
        - Tracks database state changes
        
        The stored move remains in the character's moveset for future use.
        """
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
                aoe_mode=aoe_mode or getattr(move, 'aoe_mode', 'single'),
                roll_modifier=move.roll_modifier if hasattr(move, 'roll_modifier') else None
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
            error_msg = await handle_error(interaction, e)
            logger.error(f"Error using move: {str(e)}", exc_info=True)
    
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
    @app_commands.autocomplete(character=character_autocomplete)
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
        """
        Use a temporary move without saving it to character's moveset.
        
        This command:
        - Creates a one-time-use move effect with the specified parameters
        - Does NOT save the move to the character's moveset in Firebase
        - Applies the effect to handle combat interactions
        - Processes any advanced parameters like roll modifiers
        
        Temporary moves are ideal for situational actions or testing new moves.
        For attack rolls with no cast time/duration, the "instant" roll timing
        will automatically generate attack results in the initial response.
        """
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
            roll_modifier = extra_params.get('roll_modifier')
                
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
                aoe_mode=aoe_mode,
                roll_modifier=roll_modifier
            )
            
            # Apply effect and get feedback message - Fix: use apply_effect directly
            result = await apply_effect(
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
            # Fix: Proper error handling
            logger.error(f"Error in temp_move: {str(e)}", exc_info=True)
            await handle_error(interaction, e)

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
    @app_commands.autocomplete(character=character_autocomplete)
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
        """
        Create a new move and add it to a character's moveset.
        
        This command:
        - Creates a persistent move and saves it to the character's moveset in Firebase
        - Supports all move parameters including advanced ones
        - Validates move parameters before saving
        - Prevents duplicates with same name
        
        Created moves appear in autocomplete and can be referenced by name in
        the `/move use` command for convenient access during gameplay.
        """
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
            
            # Extract roll_modifier from advanced JSON if present
            roll_modifier = None
            if 'roll_modifier' in extra_params:
                roll_modifier = extra_params['roll_modifier']
            
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
                conditions=extra_params.get('conditions', []),
                roll_modifier=roll_modifier
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
                if 'roll_modifier' in extra_params:
                    mod = extra_params['roll_modifier']
                    mod_type = mod.get('type', 'bonus')
                    mod_value = mod.get('value', 1)
                    next_only = " (next roll only)" if mod.get('next_roll', False) else ""
                    advanced.append(f"Roll Modifier: {mod_type} {mod_value}{next_only}")
                    
                if advanced:
                    embed.add_field(
                        name="Advanced Parameters",
                        value="\n".join(advanced),
                        inline=False
                    )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error creating move: {str(e)}", exc_info=True)
            await handle_error(interaction, e)
    
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
    @app_commands.autocomplete(character=character_autocomplete, name=move_name_autocomplete)
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
            if 'roll_modifier' in extra_params:
                move.roll_modifier = extra_params['roll_modifier']
            
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
            if hasattr(move, 'roll_modifier') and move.roll_modifier:
                mod = move.roll_modifier
                mod_type = mod.get('type', 'bonus')
                mod_value = mod.get('value', 1)
                next_only = " (next roll only)" if mod.get('next_roll', False) else ""
                advanced.append(f"Roll Modifier: {mod_type} {mod_value}{next_only}")
                
            if advanced:
                embed.add_field(
                    name="Advanced Parameters",
                    value="\n".join(advanced),
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error updating move: {str(e)}", exc_info=True)
            await handle_error(interaction, e)
    
    @app_commands.command(name="delete", description="Delete a move from a character")
    @app_commands.describe(
        character="Character to remove the move from",
        name="Name of the move to delete"
    )
    @app_commands.autocomplete(character=character_autocomplete, name=move_name_autocomplete)
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
            logger.error(f"Error deleting move: {str(e)}", exc_info=True)
            await handle_error(interaction, e)
    
    @app_commands.command(name="list", description="List all moves for a character")
    @app_commands.describe(
        character="Character to list moves for",
        category="Filter by category (leave empty for all)"
    )
    @app_commands.autocomplete(character=character_autocomplete)
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
                    
                    # Add roll modifier info if present
                    if hasattr(move, 'roll_modifier') and move.roll_modifier:
                        mod = move.roll_modifier
                        mod_type = mod.get('type', 'bonus')
                        mod_value = mod.get('value', 1)
                        mod_text = f"{mod_type}:{mod_value}"
                        if mod.get('next_roll', False):
                            mod_text += " (next)"
                        line += f" [{mod_text}]"
                    
                    move_lines.append(line)
                
                embed.add_field(
                    name=cat,
                    value="\n".join(move_lines),
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error listing moves: {str(e)}", exc_info=True)
            await handle_error(interaction, e)
    
    @app_commands.command(name="info", description="Show detailed information about a move")
    @app_commands.describe(
        character="Character that has the move",
        name="Name of the move"
    )
    @app_commands.autocomplete(character=character_autocomplete, name=move_name_autocomplete)
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
                description=move.description.replace(';', '\n• ') if move.description else "No description",
                color=discord.Color.blue()
            )
            
            # Add move metadata
            embed.add_field(
                name="Category",
                value=getattr(move, 'category', 'Uncategorized'),
                inline=True
            )
            
            # Add costs
            costs = []
            if getattr(move, 'star_cost', 0) > 0:
                costs.append(f"⭐ {move.star_cost} stars")
            if getattr(move, 'mp_cost', 0) > 0:
                costs.append(f"💙 {move.mp_cost} MP")
            elif getattr(move, 'mp_cost', 0) < 0:
                costs.append(f"💙 Restores {abs(move.mp_cost)} MP")
            if getattr(move, 'hp_cost', 0) > 0:
                costs.append(f"❤️ {move.hp_cost} HP")
            elif getattr(move, 'hp_cost', 0) < 0:
                costs.append(f"❤️ Heals {abs(move.hp_cost)} HP")
                
            if costs:
                embed.add_field(
                    name="Costs",
                    value="\n".join(costs),
                    inline=True
                )
                
            # Add timing info
            timing = []
            if getattr(move, 'cast_time', None) and move.cast_time > 0:
                timing.append(f"🔄 Cast Time: {move.cast_time} turn(s)")
            if getattr(move, 'duration', None) and move.duration > 0:
                timing.append(f"⏳ Duration: {move.duration} turn(s)")
            if getattr(move, 'cooldown', None) and move.cooldown > 0:
                timing.append(f"⌛ Cooldown: {move.cooldown} turn(s)")
                
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
                
            # Add combat info
            combat = []
            if getattr(move, 'attack_roll', None):
                combat.append(f"Attack Roll: {move.attack_roll}")
            if getattr(move, 'damage', None):
                combat.append(f"Damage: {move.damage}")
            
            # Safely check for save_type attribute
            if hasattr(move, 'save_type') and move.save_type:
                save_text = f"Save: {move.save_type.upper()}"
                if hasattr(move, 'save_dc') and move.save_dc:
                    save_text += f" (DC {move.save_dc})"
                if hasattr(move, 'half_on_save') and move.half_on_save:
                    save_text += " (Half damage on save)"
                combat.append(save_text)
            
            if hasattr(move, 'crit_range') and move.crit_range != 20:
                combat.append(f"Crit Range: {move.crit_range}-20")
                
            # Add roll modifier info if present
            if hasattr(move, 'roll_modifier') and move.roll_modifier:
                mod = move.roll_modifier
                mod_type = mod.get('type', 'bonus')
                mod_value = mod.get('value', 1)
                mod_text = f"Roll Modifier: {mod_type} {mod_value}"
                if mod.get('next_roll', False):
                    mod_text += " (next roll only)"
                combat.append(mod_text)
                
            if combat:
                embed.add_field(
                    name="Combat",
                    value="\n".join(combat),
                    inline=False
                )
                
            # Add usage info
            usage = []
            if hasattr(move, 'uses') and move.uses is not None:
                uses_text = f"Uses: {move.uses}"
                if hasattr(move, 'uses_remaining') and move.uses_remaining is not None:
                    uses_text = f"Uses: {move.uses_remaining}/{move.uses}"
                usage.append(uses_text)
                
            # Check cooldown status
            if hasattr(move, 'cooldown') and move.cooldown and hasattr(move, 'last_used_round') and move.last_used_round:
                current_round = 1  # Default
                if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                    current_round = self.bot.initiative_tracker.round_number
                    
                if move.last_used_round >= current_round - move.cooldown:
                    rounds_left = move.cooldown - (current_round - move.last_used_round)
                    usage.append(f"On Cooldown: {rounds_left} round(s) remaining")
                    
            if usage:
                embed.add_field(
                    name="Usage",
                    value="\n".join(usage),
                    inline=False
                )
                
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error showing move info: {str(e)}", exc_info=True)
            await handle_error(interaction, e)

async def setup(bot):
    await bot.add_cog(MoveCommands(bot))