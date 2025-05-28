"""
Move command system for using, creating, and managing moves.

Features:
- Move usage with resource tracking
- Move creation and modification
- Attack roll processing
- Turn phase handling
- Roll modifier effect handling
- Parent resource support for linked characters

ADDED: use_parent_resources parameter for child characters to use parent's resources
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
    
    # This helper function is used to adjust the duration of a move effect phase based on the turn timing
    # It checks if the move is being used during the character's turn and adjusts the phase duration accordingly
    def _adjust_timing_parameters(self, character_name, cast_time, duration, cooldown):
        """
        Adjust all timing parameters based on whether the move is used during the character's turn or not.
        
        If a move is used during a character's turn, we need to add 1 to all timing parameters
        so they don't immediately decrement to 0 and move to the next phase too early.
        
        Args:
            character_name: Name of character receiving the effect
            cast_time: Original cast time value (can be None)
            duration: Original duration value (can be None)
            cooldown: Original cooldown value (can be None)
            
        Returns:
            Tuple of (adjusted_cast_time, adjusted_duration, adjusted_cooldown)
        """
        # If initiative tracker not available, no adjustment needed
        if not hasattr(self.bot, 'initiative_tracker'):
            return cast_time, duration, cooldown
            
        # Check if we're in combat
        tracker = self.bot.initiative_tracker
        if not tracker or tracker.state.value not in ['active', 'waiting']:
            return cast_time, duration, cooldown
            
        # Check if there's a current turn and it matches our character
        is_characters_turn = False
        if tracker.current_turn and tracker.current_turn.character_name == character_name:
            is_characters_turn = True
            
        # If it's the character's turn, add 1 to all timing parameters
        if is_characters_turn:
            # Adjust cast time if present and > 0
            if cast_time is not None and cast_time > 0:
                cast_time += 1
                
            # Adjust duration if present and > 0
            if duration is not None and duration > 0:
                duration += 1
                
            # Adjust cooldown if present and > 0
            if cooldown is not None and cooldown > 0:
                cooldown += 1
                
        return cast_time, duration, cooldown
    
    def _handle_parent_resources(self, character: Character, star_cost: int, mp_cost: int, hp_cost: int, use_parent_resources: bool) -> Tuple[bool, str, List[str]]:
        """
        Handle resource costs using parent resources if requested and character is linked.
        
        Args:
            character: The character using the move
            star_cost: Star cost of the move
            mp_cost: MP cost of the move  
            hp_cost: HP cost of the move
            use_parent_resources: Whether to use parent's resources
            
        Returns:
            Tuple of (success, error_message, resource_messages)
        """
        resource_messages = []
        
        # Check if character is linked and parent resources are requested  
        if use_parent_resources and hasattr(character, 'parent_name') and character.parent_name:
            # Get parent character
            parent_char = self.bot.game_state.get_character(character.parent_name)
            if not parent_char:
                return False, f"Parent character '{character.parent_name}' not found", []
            
            # Check and apply parent's resources
            # Check MP cost
            if mp_cost > 0:
                if hasattr(parent_char, 'resources') and hasattr(parent_char.resources, 'current_mp'):
                    if parent_char.resources.current_mp < mp_cost:
                        return False, f"Parent {parent_char.name} doesn't have enough MP ({parent_char.resources.current_mp}/{mp_cost})", []
                    # Deduct MP from parent
                    parent_char.resources.current_mp -= mp_cost
                    resource_messages.append(f"🔗 {parent_char.name} MP: -{mp_cost} ({parent_char.resources.current_mp}/{parent_char.resources.max_mp})")
            
            # Check HP cost
            if hp_cost > 0:
                if hasattr(parent_char, 'resources') and hasattr(parent_char.resources, 'current_hp'):
                    if parent_char.resources.current_hp <= hp_cost:
                        return False, f"Parent {parent_char.name} doesn't have enough HP ({parent_char.resources.current_hp}/{hp_cost})", []
                    # Deduct HP from parent
                    parent_char.resources.current_hp = max(0, parent_char.resources.current_hp - hp_cost)
                    resource_messages.append(f"🔗 {parent_char.name} HP: -{hp_cost} ({parent_char.resources.current_hp}/{parent_char.resources.max_hp})")
            
            # Check star cost
            if star_cost > 0:
                if hasattr(parent_char, 'action_stars'):
                    can_use, reason = parent_char.can_use_move(star_cost, f"{character.name}'s move")
                    if not can_use:
                        return False, f"Parent {parent_char.name}: {reason}", []
                    # Deduct stars from parent
                    parent_char.use_move_stars(star_cost, f"{character.name}'s move")
                    current_stars = parent_char.action_stars.current_stars
                    max_stars = parent_char.action_stars.max_stars
                    resource_messages.append(f"🔗 {parent_char.name} Stars: -{star_cost} ({current_stars}/{max_stars})")
            
            return True, "", resource_messages
            
        elif use_parent_resources:
            # Character requested parent resources but isn't linked
            if not hasattr(character, 'parent_name') or not character.parent_name:
                return False, f"{character.name} is not a linked child character. Cannot use parent resources.", []
        
        # Use character's own resources (normal behavior)
        # Check MP cost
        if mp_cost > 0 and hasattr(character, 'resources') and hasattr(character.resources, 'current_mp'):
            if character.resources.current_mp < mp_cost:
                return False, f"Not enough MP ({character.resources.current_mp}/{mp_cost})", []
                
        # Check HP cost (only if it would reduce to 0 or below)
        if hp_cost > 0 and hasattr(character, 'resources') and hasattr(character.resources, 'current_hp'):
            if character.resources.current_hp <= hp_cost:
                return False, f"Not enough HP ({character.resources.current_hp}/{hp_cost})", []
        
        # Check star cost
        if star_cost > 0 and hasattr(character, 'action_stars'):
            can_use, reason = character.can_use_move(star_cost, "move")
            if not can_use:
                return False, reason, []
        
        return True, "", []

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
                try:
                    char_data = await self.bot.db.load_character(char_name)
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
                except Exception as e:
                    logger.error(f"Error loading character for move autocomplete: {e}", exc_info=True)
                    return []
            
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
    
    async def character_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for character names"""
        try:
            # Use proper async method instead of direct dict access
            char_names = await self.bot.db.list_characters()
            
            return [
                app_commands.Choice(name=name, value=name)
                for name in char_names
                if current.lower() in name.lower()
            ][:25]  # Discord limits to 25 choices
        except Exception as e:
            logger.warning(f"Character autocomplete error: {e}")
            return []  # Return empty list as fallback

    @app_commands.command(name="use", description="Use a stored move")
    @app_commands.describe(
        character="Character using the move",
        name="Name of the move to use",
        target="Target character(s) (comma-separated)",
        roll_timing="When to process attack roll: instant, active, or per_turn",
        aoe_mode="How to handle multiple targets: single (one roll) or multi (roll per target)",
        use_parent_resources="Use parent character's resources instead of child's (for linked characters)"
    )
    @app_commands.autocomplete(character=character_autocomplete, name=move_name_autocomplete)
    async def use_move(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        target: Optional[str] = None,
        roll_timing: Optional[str] = None,
        aoe_mode: Optional[str] = "single",
        use_parent_resources: bool = False
    ):
        """
        Use a stored move from a character's moveset.
        
        This command:
        - Retrieves a move from the character's saved moveset in Firebase
        - Creates a MoveEffect with all the stored parameters
        - Applies the effect to the character
        - Handles resource costs, cooldowns, and usage tracking
        - Tracks database state changes
        - NEW: Can use parent character's resources if character is linked
        
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
            
            # Handle resource costs (potentially using parent resources)
            success, error_msg, resource_messages = self._handle_parent_resources(
                char, move.star_cost, move.mp_cost, move.hp_cost, use_parent_resources
            )
            
            if not success:
                await interaction.followup.send(f"Cannot use {name}: {error_msg}", ephemeral=True)
                return

            # Adjust all timing parameters
            adjusted_cast_time, adjusted_duration, adjusted_cooldown = self._adjust_timing_parameters(
                character, move.cast_time, move.duration, move.cooldown
            )
                
            # Create move effect with all parameters
            move_effect = MoveEffect(
                name=move.name,
                description=move.description,
                star_cost=move.star_cost,
                mp_cost=move.mp_cost,
                hp_cost=move.hp_cost,
                cast_time=adjusted_cast_time,  # Use adjusted cast time
                duration=adjusted_duration,    # Use adjusted duration
                cooldown=adjusted_cooldown,    # Use adjusted cooldown
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
            result = await apply_effect(char, move_effect, current_round)
            
            # IMPORTANT: Now process any pending async operations
            if hasattr(move_effect, 'execute_pending_operations'):
                additional_messages = await move_effect.execute_pending_operations()
                if additional_messages:
                    # Add any additional messages to the result
                    if isinstance(additional_messages, list):
                        for msg in additional_messages:
                            if msg not in result:
                                result += f"\n{msg}"
                    else:
                        result += f"\n{additional_messages}"
            
            # Mark move as used
            move.use(current_round)
            
            # Resource costs were already handled above, so we don't need to apply them again
            # But we need to save the parent character if parent resources were used
            if use_parent_resources and hasattr(char, 'parent_name') and char.parent_name:
                parent_char = self.bot.game_state.get_character(char.parent_name)
                if parent_char:
                    await self.bot.db.save_character(parent_char)
            
            # Save character state
            await self.bot.db.save_character(char)
            
            # Save any targets that were modified
            for target_char in targets:
                await self.bot.db.save_character(target_char)
                
            # Add resource usage info to result if parent resources were used
            if resource_messages:
                resource_info = "\n".join(resource_messages)
                result += f"\n\n**Resource Usage:**\n{resource_info}"
                
            # Display result
            await interaction.followup.send(result)
            
        except Exception as e:
            error_msg = await handle_error(interaction, e)
            logger.error(f"Error using move: {str(e)}", exc_info=True)
    
    @app_commands.command(name="temp", description="Create a temporary move for testing")
    @app_commands.describe(
        character="The character using the move",
        name="The name of the move",
        description="Description of the move",
        cast_time="Cast time in turns",
        duration="Duration in turns",
        cooldown="Cooldown in turns",
        mp_cost="Mana cost",
        star_cost="Star cost",
        target="Target of the move (optional)",
        attack_roll="Attack roll formula (e.g. 'd20+str')",
        damage="Damage formula (e.g. '2d6+str fire')",
        crit_range="Critical hit range (default: 20)",
        roll_timing="When to roll attacks (instant, active, per_turn)",
        aoe_mode="AOE mode (single, multi)",
        hp_bonus="Health points to gain per hit",
        mp_bonus="Mana points to gain per hit",
        star_bonus="Action stars to gain per hit",
        bonus_note="Custom note to display with hit bonuses",
        use_parent_resources="Use parent character's resources instead of child's (for linked characters)"
    )
    async def temp_move(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        description: str,
        cast_time: Optional[int] = None,
        duration: Optional[int] = None,
        cooldown: Optional[int] = None,
        mp_cost: Optional[int] = 0,
        star_cost: Optional[int] = 0,
        target: Optional[str] = None,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        crit_range: Optional[int] = 20,
        roll_timing: Optional[str] = "active",
        aoe_mode: Optional[str] = "single",
        hp_bonus: Optional[int] = 0,
        mp_bonus: Optional[int] = 0,
        star_bonus: Optional[int] = 0,
        bonus_note: Optional[str] = None,
        use_parent_resources: bool = False
    ):
        """Create a temporary move for testing"""
        try:
            # Log command parameters
            cmd_params = f"/move temp character: {character} name: {name} description: {description}"
            if cast_time is not None: cmd_params += f" cast_time: {cast_time}"
            if duration is not None: cmd_params += f" duration: {duration}"
            if cooldown is not None: cmd_params += f" cooldown: {cooldown}"
            if mp_cost != 0: cmd_params += f" mp_cost: {mp_cost}"
            if star_cost != 0: cmd_params += f" star_cost: {star_cost}"
            if target: cmd_params += f" target: {target}"
            if attack_roll: cmd_params += f" attack_roll: {attack_roll}"
            if damage: cmd_params += f" damage: {damage}"
            if crit_range != 20: cmd_params += f" crit_range: {crit_range}"
            if roll_timing != "active": cmd_params += f" roll_timing: {roll_timing}"
            if aoe_mode != "single": cmd_params += f" aoe_mode: {aoe_mode}"
            if hp_bonus: cmd_params += f" hp_bonus: {hp_bonus}"
            if mp_bonus: cmd_params += f" mp_bonus: {mp_bonus}"
            if star_bonus: cmd_params += f" star_bonus: {star_bonus}"
            if bonus_note: cmd_params += f" bonus_note: {bonus_note}"
            if use_parent_resources: cmd_params += f" use_parent_resources: {use_parent_resources}"
            
            print(f"COMMAND EXECUTED: {cmd_params}")
            logger.info(f"COMMAND EXECUTED: {cmd_params}")
            
            await interaction.response.defer()
            
            # Get source character
            source = interaction.client.game_state.get_character(character)
            if not source:
                await interaction.followup.send(f"Character '{character}' not found.")
                return
            
            # Handle resource costs (potentially using parent resources)
            success, error_msg, resource_messages = self._handle_parent_resources(
                source, star_cost, mp_cost, 0, use_parent_resources  # HP cost validation happens in MoveEffect
            )
            
            if not success:
                await interaction.followup.send(f"Cannot use {name}: {error_msg}", ephemeral=True)
                return
                
            # Get target character if specified
            target_char = None
            targets = []
            if target:
                # Support multiple targets separated by commas
                target_names = [t.strip() for t in target.split(',')]
                for target_name in target_names:
                    t_char = interaction.client.game_state.get_character(target_name)
                    if t_char:
                        targets.append(t_char)
                    else:
                        await interaction.followup.send(f"Target '{target_name}' not found.", ephemeral=True)
                
                # Check target compatibility with aoe_mode
                if 'multihit' in (attack_roll or '') and aoe_mode == 'multi' and len(targets) > 1:
                    await interaction.followup.send(
                        "⚠️ Multihit attacks are not compatible with multiple targets in 'multi' mode. "
                        "Using 'single' mode instead.",
                        ephemeral=True
                    )
                    aoe_mode = 'single'
                
            # Create bonus_on_hit parameter if any bonuses specified
            bonus_on_hit = None
            if hp_bonus or mp_bonus or star_bonus or bonus_note:
                from core.effects.move.combat import BonusOnHit
                bonus_on_hit = BonusOnHit(
                    stars=star_bonus,
                    mp=mp_bonus,
                    hp=hp_bonus,
                    custom_note=bonus_note
                )
                
            # Create the move effect
            from core.effects.move import MoveEffect
            
            # Debug print for the roll_timing parameter
            print(f"Creating move with roll_timing: {roll_timing} (type: {type(roll_timing)})")
            
            move = MoveEffect(
                name=name,
                description=description,
                star_cost=star_cost,
                mp_cost=mp_cost,
                cast_time=cast_time,
                duration=duration,
                cooldown=cooldown,
                attack_roll=attack_roll,
                damage=damage,
                crit_range=crit_range,
                targets=targets,
                roll_timing=roll_timing,
                aoe_mode=aoe_mode,
                bonus_on_hit=bonus_on_hit
            )
            
            # Apply the effect
            from core.effects.manager import apply_effect
            
            current_round = 1
            if hasattr(interaction.client, 'initiative_tracker'):
                tracker = interaction.client.initiative_tracker
                if hasattr(tracker, 'round_number'):
                    current_round = tracker.round_number
                    
            # Make sure we're properly awaiting apply_effect
            result = await apply_effect(source, move, current_round)
            
            # Execute pending operations like attack rolls
            if hasattr(move, 'execute_pending_operations'):
                try:
                    messages = await move.execute_pending_operations()
                    if messages:
                        if isinstance(messages, list):
                            # Send as a single message for cleaner output
                            await interaction.followup.send('\n'.join(messages))
                        else:
                            await interaction.followup.send(messages)
                except Exception as e:
                    logger.error(f"Error executing pending operations: {e}")
            
            # Resource costs were already handled above, so we don't need to apply them again
            # But we need to save the parent character if parent resources were used
            if use_parent_resources and hasattr(source, 'parent_name') and source.parent_name:
                parent_char = interaction.client.game_state.get_character(source.parent_name)
                if parent_char:
                    await interaction.client.db.save_character(parent_char)
                    
            # Save the character
            await interaction.client.db.save_character(source)
            
            # Also save target characters if modified
            for target_char in targets:
                await interaction.client.db.save_character(target_char)
            
            # Add resource usage info to result if parent resources were used
            if resource_messages:
                resource_info = "\n".join(resource_messages)
                result += f"\n\n**Resource Usage:**\n{resource_info}"
                
            await interaction.followup.send(result)
            
        except Exception as e:
            from utils.error_handler import handle_error
            await handle_error(interaction, e)
            
            # Also log the exception for debugging
            print(f"ERROR executing move command: {str(e)}")
            logger.error(f"Error executing move command: {str(e)}", exc_info=True)

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