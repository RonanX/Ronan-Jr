"""
Discord commands for managing and debugging character effects, including burn effects.
Enhanced with improved console logging for debugging effects.
"""

import logging
import discord
from discord import app_commands, Interaction, ui
from discord.ext import commands
from typing import Optional, Literal, List, Dict, Any, Union

# Import necessary components from the core effects system
from modules.combat.initiative import InitiativeTracker
from core.effects.manager import apply_effect, remove_effect, EffectRegistry, register_effects, get_effect_summary
from core.effects.debug_effect import DebugEffect
from core.effects.burn_effect import BurnEffect  # Import the new BurnEffect
from core.effects.ac import ACEffect  # Import ACEffect for the new command
from core.effects.stat import StatEffect, StatType
from core.character import Character
from utils.error_handler import handle_error, handle_command_error
from utils.constants import EMOJI_MAP  # For emoji consistency
from utils.formatting import MessageFormatter  # For consistent logging

logger = logging.getLogger(__name__)

# Ensure effects are registered when this module is loaded
register_effects()

# Stack removal UI components
class StackRemovalSelect(ui.Select):
    """Dropdown for selecting multiple effect stacks to remove."""
    def __init__(self, effects: List[Dict[str, Any]]):
        # Create options from the effects list
        options = []
        for i, effect_info in enumerate(effects):
            # Create a descriptive label for each stack
            effect = effect_info["effect"]
            
            # Format label based on effect type
            if isinstance(effect, BurnEffect):
                # For burn effects, show damage formula
                if effect.is_dice:
                    dmg_text = f"{effect.damage_formula} (dice)"
                else:
                    dmg_text = f"{effect.damage_formula} damage"
                    
                label = f"{effect.name} - Stack {i+1} - {dmg_text}"
            else:
                # Generic label for other stackable effects
                label = f"{effect.name} - Stack {i+1}"
            
            # Create the option
            options.append(discord.SelectOption(
                label=label,
                value=str(i),
                emoji=effect.emoji if hasattr(effect, "emoji") else "✨"
            ))
        
        # Initialize the select with multi-select enabled
        super().__init__(
            placeholder="Select stacks to remove...",
            min_values=1,
            max_values=min(len(options), 25),  # Discord limits to 25 max selections
            options=options
        )
        
    async def callback(self, interaction: Interaction):
        # This is handled in the view's callback
        pass

class StackRemovalView(ui.View):
    """View for removing multiple effect stacks."""
    def __init__(self, character: Character, effect_name: str, effects: List[Dict[str, Any]], 
                 message_callback=None, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.character = character
        self.effect_name = effect_name
        self.effects = effects
        self.message_callback = message_callback
        
        # Add the select menu
        self.select = StackRemovalSelect(effects)
        self.add_item(self.select)
    
    async def on_timeout(self):
        # Disable the select when it times out
        self.select.disabled = True
        
        # Update the message if callback exists
        if self.message_callback:
            await self.message_callback("Selection timed out", update=True, view=self)
    
    @ui.button(label="Remove Selected", style=discord.ButtonStyle.danger)
    async def remove_button(self, interaction: Interaction, button: ui.Button):
        # Get the selected indices (as strings)
        selected_indices = self.select.values
        
        # Convert to integers and sort in reverse order (to remove from end first)
        selected_indices = sorted([int(idx) for idx in selected_indices], reverse=True)
        
        # Process each selected effect
        results = []
        modified_effects = []
        
        for idx in selected_indices:
            if idx < len(self.effects):
                effect_info = self.effects[idx]
                effect = effect_info["effect"]
                
                # Handle stack removal based on effect type
                if hasattr(effect, "remove_stack"):
                    # For effects with stack removal method
                    should_remove, message = effect.remove_stack(self.character)
                    
                    if should_remove:
                        # If all stacks removed, remove the effect entirely
                        if effect in self.character.effects:
                            self.character.effects.remove(effect)
                        
                        # Record result
                        results.append({
                            "type": "full_removal",
                            "effect": effect.name,
                            "message": message
                        })
                    else:
                        # Record partial removal
                        results.append({
                            "type": "partial_removal",
                            "effect": effect.name,
                            "message": message
                        })
                        
                        # Track modified effects
                        modified_effects.append(effect)
                else:
                    # For effects without stack support, just remove it
                    if effect in self.character.effects:
                        self.character.effects.remove(effect)
                    
                    # Record result
                    results.append({
                        "type": "full_removal",
                        "effect": effect.name,
                        "message": f"✨ `{effect.name} removed from {self.character.name}`"
                    })
        
        # Create response embed
        embed = discord.Embed(
            title="Stack Removal Results",
            description=f"Removed {len(selected_indices)} stacks from {self.character.name}",
            color=discord.Color.green()
        )
        
        # Add fields for each result
        for result in results:
            embed.add_field(
                name=f"{result['effect']} Removal",
                value=result["message"],
                inline=False
            )
        
        # Disable the view
        self.disable_all_items()
        
        # Send the response
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Use the callback to finish processing
        if self.message_callback:
            await self.message_callback(
                f"Successfully processed {len(selected_indices)} stack removals", 
                update=False
            )
    
    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: Interaction, button: ui.Button):
        # Disable the view
        self.disable_all_items()
        
        # Update the message
        embed = discord.Embed(
            title="Stack Removal Cancelled",
            description="No stacks were removed.",
            color=discord.Color.grey()
        )
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Use the callback
        if self.message_callback:
            await self.message_callback("Operation cancelled by user", update=False)
    
    def disable_all_items(self):
        """Disable all interactive elements in the view."""
        for child in self.children:
            child.disabled = True

class EffectsCommands(commands.GroupCog, name="effect"):
    """Commands related to character effects"""

    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="ac")
    @app_commands.describe(
        character="Character to apply AC modification to",
        amount="Amount to modify AC by (can be positive or negative)",
        duration="Effect duration in turns (default: 3)",
        permanent="If the AC modification should last indefinitely",
        force_during="Force effect timing"
    )
    async def ac_effect(
        self,
        interaction: Interaction,
        character: str,
        amount: int,
        duration: Optional[int] = 3,
        permanent: Optional[bool] = False,
        force_during: Optional[bool] = None
    ):
        """Apply an armor class modification effect to a character."""
        try:
            # Detailed command parameter logging
            logger.info(f"AC Effect Command: character={character}, amount={amount}, duration={duration}, permanent={permanent}, force_during={force_during}")
            print(f"\n=== AC Effect Command ===")
            print(f"Parameters received:")
            print(f"- Character: {character}")
            print(f"- Amount: {amount}")
            print(f"- Duration: {duration}")
            print(f"- Permanent: {permanent}")
            print(f"- Force During: {force_during}")
            
            await interaction.response.defer()
            target_char = self.bot.game_state.get_character(character)
            if not target_char:
                logger.warning(f"Character '{character}' not found for AC effect")
                await interaction.followup.send(f"❌ Character '{character}' not found.", ephemeral=True)
                return

            # Log character state before applying effect
            print(f"Character found: {character}")
            print(f"Current AC: {target_char.defense.current_ac}")
            print(f"Base AC: {target_char.defense.base_ac}")

            # Create the AC Effect with more robust error handling
            try:
                ac_effect = ACEffect(
                    amount=amount,
                    duration=None if permanent else duration,  # Set duration to None if permanent
                    permanent=permanent
                )
                print(f"AC Effect created successfully: {ac_effect.name}")
            except Exception as effect_error:
                logger.error(f"Failed to create AC effect: {effect_error}", exc_info=True)
                print(f"ERROR creating AC effect: {effect_error}")
                await interaction.followup.send(f"❌ Error creating AC effect: {effect_error}", ephemeral=True)
                return

            # Set timing manually if specified
            if force_during is not None:
                print(f"Setting force_during to {force_during}")
                ac_effect.is_during_own_turn = force_during

            # Get initiative information for proper timing
            initiative_tracker = None
            current_round = 1
            is_combat = False
            current_turn_name = None

            # Get the initiative tracker if available
            if hasattr(self.bot, 'initiative_tracker'):
                initiative_tracker = self.bot.initiative_tracker
                
                # Check if combat is active and get current turn directly
                if initiative_tracker and initiative_tracker.state.value != 'inactive':
                    is_combat = True
                    current_round = initiative_tracker.round_number
                    
                    # Get most accurate turn name
                    if hasattr(initiative_tracker, 'current_turn') and initiative_tracker.current_turn:
                        if hasattr(initiative_tracker.current_turn, 'character_name'):
                            current_turn_name = initiative_tracker.current_turn.character_name
            
            # Log combat state for debugging
            print(f"Combat active: {is_combat}")
            print(f"Current round: {current_round}")
            print(f"Current turn: {current_turn_name}")

            # Apply the effect with the right context
            try:
                message = await apply_effect(
                    character=target_char,
                    effect=ac_effect,
                    round_number=current_round,
                    combat_logger=self.bot.game_state.logger,
                    is_combat_active=is_combat,
                    initiative_tracker=initiative_tracker
                )
                print(f"Effect applied successfully, message: {message}")
            except Exception as apply_error:
                logger.error(f"Failed to apply AC effect: {apply_error}", exc_info=True)
                print(f"ERROR applying AC effect: {apply_error}")
                await interaction.followup.send(f"❌ Error applying AC effect: {apply_error}", ephemeral=True)
                return

            # Save the character
            try:
                await self.bot.db.save_character(target_char)
                print(f"Character saved with new AC: {target_char.defense.current_ac}")
            except Exception as save_error:
                logger.error(f"Failed to save character after AC effect: {save_error}", exc_info=True)
                print(f"WARNING: Could not save character: {save_error}")
                # Continue execution as this is not a critical failure

            # Create response embed with more dynamic messaging
            emoji = "🛡️⬆️" if amount > 0 else "🛡️⬇️" if amount < 0 else "🛡️"
            sign = "+" if amount > 0 else ""
            
            # Choose title based on effect type
            if "error" in message.lower():
                title = f"{emoji} AC Modification Error"
                color = discord.Color.red()
            else:
                if amount > 0:
                    title = f"{emoji} Armor Strengthened"
                    color = discord.Color.green()
                elif amount < 0:
                    title = f"{emoji} Armor Weakened" 
                    color = discord.Color.orange()
                else:
                    title = f"{emoji} AC Modified"
                    color = discord.Color.blue()

            embed = discord.Embed(
                title=title,
                description=message,
                color=color
            )

            # Add effect details with more accurate duration explanation
            duration_display = "Permanent" if permanent else f"{duration} turns exactly"
            embed.add_field(
                name="Effect Details",
                value=f"Amount: {sign}{amount}\nDuration: {duration_display}\nCharacter: {character}",
                inline=False
            )

            # Add AC state
            embed.add_field(
                name="Current AC",
                value=f"{target_char.defense.current_ac}",
                inline=True
            )
            
            # Add debugging help text for duration calculation
            if not permanent:
                embed.add_field(
                    name="Duration Info",
                    value=f"Effect will last for exactly {duration} turns and then expire.",
                    inline=False
                )

            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Uncaught error in ac_effect command: {e}", exc_info=True)
            print(f"CRITICAL ERROR in ac_effect command: {e}")
            await handle_error(interaction, e)

    @app_commands.command(name="burn")
    @app_commands.describe(
        character="Character to apply burn effect to",
        damage="Damage formula (e.g., 'd4' or flat number)",
        duration="Effect duration in turns (default: 3)",
        permanent="If the burn should last indefinitely",
        force_during="Force effect timing"
    )
    async def burn_effect(
        self,
        interaction: Interaction,
        character: str,
        damage: str,
        duration: Optional[int] = 3,
        permanent: Optional[bool] = False,
        force_during: Optional[bool] = None
    ):
        await interaction.response.defer()
        target_char = self.bot.game_state.get_character(character)
        if not target_char:
            await interaction.followup.send(f"❌ Character '{character}' not found.", ephemeral=True)
            return

        damage_str = str(damage)
        if damage_str.startswith('d') and damage_str[1:].isdigit():
            damage_str = '1' + damage_str

        burn_effect = BurnEffect(
            duration=duration,
            damage_formula=damage_str,
            permanent=permanent
        )

        if force_during is not None:
            burn_effect.is_during_own_turn = force_during

        message = await apply_effect(
            character=target_char,
            effect=burn_effect,
            round_number=1,
            combat_logger=self.bot.game_state.logger
        )

        await self.bot.db.save_character(target_char)

        embed = discord.Embed(
            title="🔥 Burn Effect Applied",
            description=message,
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="stat", description="Apply a stat modifier to a character")
    @app_commands.describe(
        character="The character to affect",
        stat="The stat to modify (STR, DEX, CON, INT, WIS, CHA)",
        amount="Amount to modify the stat by (positive or negative)",
        duration="How many turns the effect lasts (default: 3)",
        permanent="Whether the effect is permanent (default: False)",
        force_during="Force effect timing (advanced)"
    )
    async def effect_stat(
        self,
        interaction: discord.Interaction,
        character: str,
        stat: str,
        amount: int,
        duration: Optional[int] = 3,
        permanent: Optional[bool] = False,
        force_during: Optional[bool] = None
    ):
        """Apply a stat effect to modify a character's stats temporarily or permanently"""
        await interaction.response.defer()
        
    @app_commands.command(name="stat", description="Apply a stat modifier to a character")
    @app_commands.describe(
        character="The character to affect",
        stat="The stat to modify (STR, DEX, CON, INT, WIS, CHA)",
        amount="Amount to modify the stat by (positive or negative)",
        duration="How many turns the effect lasts (default: 3)",
        permanent="Whether the effect is permanent (default: False)",
        force_during="Force effect timing (advanced)"
    )
    async def effect_stat(
        self,
        interaction: discord.Interaction,
        character: str,
        stat: str,
        amount: int,
        duration: Optional[int] = 3,
        permanent: Optional[bool] = False,
        force_during: Optional[bool] = None
    ):
        """Apply a stat effect to modify a character's stats temporarily or permanently"""
        try:
            # Detailed command parameter logging
            logger.info(f"Stat Effect Command: character={character}, stat={stat}, amount={amount}, duration={duration}, permanent={permanent}, force_during={force_during}")
            print(f"\n=== Stat Effect Command ===")
            print(f"Parameters received:")
            print(f"- Character: {character}")
            print(f"- Stat: {stat}")
            print(f"- Amount: {amount}")
            print(f"- Duration: {duration}")
            print(f"- Permanent: {permanent}")
            print(f"- Force During: {force_during}")
            
            # Use defer only if not already responded to
            if not interaction.response.is_done():
                await interaction.response.defer()
            
            # Validate stat name
            try:
                stat_type = StatType.from_string(stat)
            except ValueError:
                logger.warning(f"Invalid stat type: {stat}")
                return await interaction.followup.send(
                    f"❌ Invalid stat type: {stat}. Must be one of: strength, dexterity, constitution, intelligence, wisdom, charisma.",
                    ephemeral=True
                )
            
            # Get character from game state
            character_obj = self.bot.game_state.get_character(character)
            if not character_obj:
                logger.warning(f"Character '{character}' not found for Stat effect")
                return await interaction.followup.send(
                    f"❌ Character '{character}' not found.",
                    ephemeral=True
                )
            
            # Log character state before applying effect
            print(f"Character found: {character}")
            base_value = character_obj.stats.base.get(stat_type, 10)
            modified_value = character_obj.stats.modified.get(stat_type, base_value)
            print(f"Current {stat_type.name}: {modified_value}")
            print(f"Base {stat_type.name}: {base_value}")
            
            # Validate inputs
            if permanent and duration:
                await interaction.followup.send(
                    "Note: The duration is ignored for permanent effects.",
                    ephemeral=True
                )
            
            # Create the effect with more robust error handling
            try:
                effect = StatEffect(
                    stat_type=stat_type,
                    amount=amount,
                    duration=None if permanent else duration,
                    permanent=permanent
                )
                print(f"Stat Effect created successfully: {effect.name}")
            except Exception as effect_error:
                logger.error(f"Failed to create Stat effect: {effect_error}", exc_info=True)
                print(f"ERROR creating Stat effect: {effect_error}")
                await interaction.followup.send(f"❌ Error creating Stat effect: {effect_error}", ephemeral=True)
                return
            
            # Set timing manually if specified
            if force_during is not None:
                print(f"Setting force_during to {force_during}")
                effect.is_during_own_turn = force_during
            
            # Get current combat information (for effect timing)
            initiative_tracker = None
            current_round = 1
            is_combat = False
            current_turn_name = None
            
            # Get the initiative tracker if available
            if hasattr(self.bot, 'initiative_tracker'):
                initiative_tracker = self.bot.initiative_tracker
                
                # Check if combat is active and get current turn directly
                if initiative_tracker and hasattr(initiative_tracker, 'state') and initiative_tracker.state.value != 'inactive':
                    is_combat = True
                    current_round = getattr(initiative_tracker, 'round_number', 1)
                    
                    # Get most accurate turn name
                    if hasattr(initiative_tracker, 'current_turn') and initiative_tracker.current_turn:
                        if hasattr(initiative_tracker.current_turn, 'character_name'):
                            current_turn_name = initiative_tracker.current_turn.character_name
            
            # Log combat state for debugging
            print(f"Combat active: {is_combat}")
            print(f"Current round: {current_round}")
            print(f"Current turn: {current_turn_name}")
            
            # Apply the effect
            try:
                from core.effects.manager import apply_effect
                message = await apply_effect(
                    character=character_obj,
                    effect=effect,
                    round_number=current_round,
                    combat_logger=self.bot.game_state.logger if is_combat else None,
                    is_combat_active=is_combat,
                    initiative_tracker=initiative_tracker
                )
                print(f"Effect applied successfully, message: {message}")
            except Exception as apply_error:
                logger.error(f"Failed to apply Stat effect: {apply_error}", exc_info=True)
                print(f"ERROR applying Stat effect: {apply_error}")
                await interaction.followup.send(f"❌ Error applying Stat effect: {apply_error}", ephemeral=True)
                return
            
            # Save character to database
            try:
                await self.bot.db.save_character(character_obj)
                new_value = character_obj.stats.modified.get(stat_type, base_value)
                print(f"Character saved with new {stat_type.name}: {new_value}")
            except Exception as save_error:
                logger.error(f"Failed to save character after Stat effect: {save_error}", exc_info=True)
                print(f"WARNING: Could not save character: {save_error}")
                # Continue execution as this is not a critical failure
            
            # Create response embed with more dynamic messaging
            emoji = "💪⬆️" if amount > 0 else "💪⬇️" if amount < 0 else "💪"
            sign = "+" if amount > 0 else ""
            
            # Choose title based on effect type
            if "error" in message.lower():
                title = f"{emoji} Stat Modification Error"
                color = discord.Color.red()
            else:
                if amount > 0:
                    title = f"{emoji} {stat_type.name.title()} Increased"
                    color = discord.Color.green()
                elif amount < 0:
                    title = f"{emoji} {stat_type.name.title()} Decreased" 
                    color = discord.Color.orange()
                else:
                    title = f"{emoji} {stat_type.name.title()} Modified"
                    color = discord.Color.blue()
            
            embed = discord.Embed(
                title=title,
                description=message,
                color=color
            )
            
            # Add effect details with more accurate duration explanation
            duration_display = "Permanent" if permanent else f"{duration} turns exactly"
            embed.add_field(
                name="Effect Details",
                value=f"Stat: {stat_type.name.title()}\nAmount: {sign}{amount}\nDuration: {duration_display}\nCharacter: {character}",
                inline=False
            )
            
            # Calculate new modifiers
            base_mod = (base_value - 10) // 2
            new_value = character_obj.stats.modified.get(stat_type, base_value)
            new_mod = (new_value - 10) // 2
            mod_change = new_mod - base_mod
            
            # Add stat state field
            embed.add_field(
                name="Stat Change",
                value=f"Base: {base_value} ({base_mod:+})\nCurrent: {new_value} ({new_mod:+})\nModifier Change: {mod_change:+}",
                inline=True
            )
            
            # Add debugging help text for duration calculation
            if not permanent:
                embed.add_field(
                    name="Duration Info",
                    value=f"Effect will last for exactly {duration} turns and then expire.",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            # Log the error and send an error message
            logger.error(f"Error in effect_stat command: {str(e)}", exc_info=True)
            
            # Fix: Use handle_error instead of handle_command_error
            from utils.error_handler import handle_error
            await handle_error(interaction, e)
            
        except Exception as e:
            # Log the error and send an error message
            logger.error(f"Error in effect_stat command: {str(e)}", exc_info=True)
            await handle_command_error(interaction, e, "Failed to apply stat effect")

    @app_commands.command(name="remove")
    @app_commands.describe(
        character="The character to remove the effect from",
        effect_name="The name of the effect to remove (partial names work)"
    )
    async def remove_effect_command(
        self,
        interaction: Interaction,
        character: str,
        effect_name: str
    ):
        """Removes an effect from a character with support for partial names and stack removal."""
        try:
            await interaction.response.defer()

            target_char = self.bot.game_state.get_character(character)
            if not target_char:
                await interaction.followup.send(f"❌ Character '{character}' not found.", ephemeral=True)
                return

            # Check if character has any effects
            if not target_char.effects:
                await interaction.followup.send(f"✅ {character} has no active effects.", ephemeral=True)
                return
            
            # Use fuzzy search to find matching effects
            effect_name_lower = effect_name.lower()
            matching_effects = []
            
            for effect in target_char.effects:
                if effect_name_lower in effect.name.lower():
                    matching_effects.append({
                        "effect": effect,
                        "name": effect.name,
                        "stacks": getattr(effect, "stacks", 1) if hasattr(effect, "stacks") else 1
                    })
            
            # Check if any effects were found
            if not matching_effects:
                await interaction.followup.send(
                    f"❌ No effects matching '{effect_name}' found on {character}.",
                    ephemeral=True
                )
                return
            
            # Log effect details before removal
            print(f"\n=== Effect Removal Request: {effect_name} from {character} ===")
            for i, effect_info in enumerate(matching_effects):
                effect = effect_info["effect"]
                print(f"Effect {i+1}: {effect.name} ({type(effect).__name__})")
                
                if isinstance(effect, BurnEffect):
                    print(f"  Stacks: {effect.stacks}")
                    print(f"  Stack Composition: {effect.stack_composition}")
                    print(f"  State: {effect.state.value}")
                    print(f"  Duration - Display: {effect._display_duration}, Internal: {effect._internal_duration}")
                    print(f"  Turns Elapsed: {effect.turns_elapsed}")
                else:
                    # Generic effect info
                    print(f"  State: {effect.state.value}")
                    if hasattr(effect, '_display_duration'):
                        print(f"  Duration: {effect._display_duration}")
            
            # Check for stackable effects
            stackable_effects = [e for e in matching_effects if e["stacks"] > 1]
            
            if len(matching_effects) == 1 and matching_effects[0]["stacks"] <= 1:
                # Simple case: single non-stacked effect
                effect = matching_effects[0]["effect"]
                
                # Log before removal
                print(f"\nRemoving single effect: {effect.name}")
                
                # Remove the effect
                remove_message = await remove_effect(
                    character=target_char,
                    effect_name=effect.name,
                    combat_logger=self.bot.game_state.logger
                )
                
                # Log after removal
                print(f"Effect removed: {remove_message}")
                
                # Save the character
                await self.bot.db.save_character(target_char)
                
                # Send response
                await interaction.followup.send(remove_message)
                
            elif stackable_effects:
                # Complex case: stackable effects found, show UI for stack selection
                print(f"\nFound {len(stackable_effects)} stackable effects, showing UI")
                
                # Create callback for processing results
                async def process_results(message, update=False, view=None):
                    # This is called after the view processes selections
                    if update and view:
                        # Just update the existing message with the new view
                        pass
                    else:
                        # Log result
                        print(f"Stack removal complete: {message}")
                        
                        # Save the character after processing
                        await self.bot.db.save_character(target_char)
                
                # Create select view
                view = StackRemovalView(
                    target_char, 
                    effect_name, 
                    matching_effects,
                    message_callback=process_results
                )
                
                # Create initial embed
                embed = discord.Embed(
                    title="Effect Stack Removal",
                    description=f"Select which stacks of '{effect_name}' to remove from {character}",
                    color=discord.Color.blue()
                )
                
                # Add a note about stack behavior
                embed.add_field(
                    name="Stack Behavior",
                    value="You can select multiple stacks to remove at once. Each stack is processed separately.",
                    inline=False
                )
                
                # Send the view
                await interaction.followup.send(embed=embed, view=view)
                
            else:
                # Multiple non-stacked effects, just remove all of them
                removed_count = 0
                messages = []
                
                print(f"\nRemoving {len(matching_effects)} non-stacked effects")
                
                for effect_info in matching_effects:
                    effect = effect_info["effect"]
                    
                    # Log before removal
                    print(f"Removing effect: {effect.name}")
                    
                    # Remove the effect
                    remove_message = await remove_effect(
                        character=target_char,
                        effect_name=effect.name,
                        combat_logger=self.bot.game_state.logger
                    )
                    
                    removed_count += 1
                    messages.append(remove_message)
                    
                    # Log after removal
                    print(f"Effect removed: {remove_message}")
                
                # Save the character
                await self.bot.db.save_character(target_char)
                
                # Create response embed
                embed = discord.Embed(
                    title="Effects Removed",
                    description=f"Removed {removed_count} effects from {character}",
                    color=discord.Color.green()
                )
                
                # Add messages
                for i, msg in enumerate(messages):
                    embed.add_field(
                        name=f"Effect {i+1}",
                        value=msg,
                        inline=False
                    )
                
                # Send response
                await interaction.followup.send(embed=embed)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="list")
    @app_commands.describe(
        character="The character to list effects for"
    )
    async def list_effects(
        self,
        interaction: Interaction,
        character: str
    ):
        """Lists all active effects on a character."""
        try:
            await interaction.response.defer()

            target_char = self.bot.game_state.get_character(character)
            if not target_char:
                await interaction.followup.send(f"❌ Character '{character}' not found.", ephemeral=True)
                return

            # Check if character has any effects
            if not hasattr(target_char, 'effects') or not target_char.effects:
                await interaction.followup.send(f"✅ {character} has no active effects.")
                return

            # Log effects to console for debugging
            print(f"\n=== Effects on {character} ===")
            for i, effect in enumerate(target_char.effects):
                print(f"Effect {i+1}: {effect.name} ({type(effect).__name__})")
                print(f"  State: {effect.state.value}")
                
                if hasattr(effect, 'timing') and effect.timing:
                    applied_during = "DURING" if effect.timing.applied_during_own_turn else "NOT DURING"
                    print(f"  Timing: Applied {applied_during} own turn, Start Round: {effect.timing.start_round}")
                
                if hasattr(effect, '_internal_duration'):
                    print(f"  Internal Duration: {effect._internal_duration}")
                
                if hasattr(effect, '_display_duration'):
                    print(f"  Display Duration: {effect._display_duration}")
                
                if hasattr(effect, 'turns_elapsed'):
                    print(f"  Turns Elapsed: {effect.turns_elapsed}")
                
                if hasattr(effect, 'permanent'):
                    print(f"  Permanent: {effect.permanent}")
                
                # Burn-specific info
                if isinstance(effect, BurnEffect):
                    print(f"  Stacks: {effect.stacks}")
                    print(f"  Stack Composition: {effect.stack_composition}")
                    print(f"  Original Damage: {effect.original_damage}")
                    
                    # Print full state dump if available
                    if hasattr(effect, 'dump_state'):
                        print(effect.dump_state("  "))
                
                print("")  # Empty line between effects

            # Import and use get_effect_summary from manager
            effect_summary = get_effect_summary(target_char)

            # Create an embed to display the effects
            embed = discord.Embed(
                title=f"Effects on {character}",
                description=f"Currently active effects: {len(target_char.effects)}",
                color=discord.Color.blue()
            )

            # Add effect information to the embed
            if effect_summary:
                embed.description = "\n".join(effect_summary)
            else:
                embed.description = f"{character} has no active effects."
                
            # Add detailed information field for each effect
            for i, effect in enumerate(target_char.effects):
                details = []
                
                # Basic effect info
                details.append(f"Type: {type(effect).__name__}")
                details.append(f"State: {effect.state.value}")
                
                # Duration info
                if hasattr(effect, 'permanent') and effect.permanent:
                    details.append("Duration: Permanent")
                elif hasattr(effect, '_display_duration') and effect._display_duration is not None:
                    details.append(f"Duration: {effect._display_duration}")
                    
                # Burn-specific info
                if isinstance(effect, BurnEffect):
                    details.append(f"Stacks: {effect.stacks}")
                    details.append(f"Formula: {effect._format_stack_display()}")
                
                # Add the field
                embed.add_field(
                    name=f"{effect.name}",
                    value="\n".join(details),
                    inline=True
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await handle_error(interaction, e)

    # Test command for the new template-using effects system
    @app_commands.command(name="test")
    @app_commands.describe(
        character="Character to apply the test effect to (ignored if bulk=True)",
        duration="Effect duration in turns (default: 3)",
        message="Test message to display with the effect",
        marker="Emoji marker for the effect (default: ⚗️)",
        permanent="Whether the effect should be permanent",
        bulk="Apply test effects to multiple characters with different timing scenarios",
        during="When bulk=True, character to apply 'during own turn' effects to",
        not_during="When bulk=True, character to apply 'not during own turn' effects to"
    )
    async def test_effect_command(
        self,
        interaction: Interaction,
        character: Optional[str] = None,
        duration: Optional[int] = 3,
        message: Optional[str] = "Testing the standard effect helpers",
        marker: Optional[str] = "⚗️",
        permanent: Optional[bool] = False,
        bulk: Optional[bool] = False,
        during: Optional[str] = None,
        not_during: Optional[str] = None
    ):
        """Apply a test effect to verify the enhanced effects system"""
        try:
            await interaction.response.defer()
            
            # Print detailed test information to console
            print(f"\n=== TESTING EFFECT SYSTEM ===")
            print(f"Bulk Mode: {bulk}")
            
            if bulk:
                print(f"During character: {during}")
                print(f"Not during character: {not_during}")
            else:
                print(f"Character: {character}")
            
            print(f"Duration: {duration}")
            print(f"Message: {message}")
            print(f"Marker: {marker}")
            print(f"Permanent: {permanent}")
            
            # Get initiative information
            initiative_tracker = None
            current_round = 1
            is_combat = False
            current_turn_name = None
            
            # Get the initiative tracker if available
            if hasattr(self.bot, 'initiative_tracker'):
                initiative_tracker = self.bot.initiative_tracker
                
                # Check if combat is active
                if initiative_tracker.state.value != 'inactive':
                    is_combat = True
                    current_round = initiative_tracker.round_number
                    
                    # Get current turn name
                    if hasattr(initiative_tracker, 'current_turn') and initiative_tracker.current_turn:
                        if hasattr(initiative_tracker.current_turn, 'character_name'):
                            current_turn_name = initiative_tracker.current_turn.character_name
            
            # Log current combat state
            print(f"Combat Active: {is_combat}")
            print(f"Current Round: {current_round}")
            print(f"Current Turn: {current_turn_name}")
            
            # Import the test effect
            from core.effects.test_effect import TestEffect
            
            # Track results for final embed
            results = []
            
            if bulk:
                # BULK MODE: Apply to both during and not_during characters
                
                # Process "during own turn" character
                if during:
                    during_char = self.bot.game_state.get_character(during)
                    if during_char:
                        print(f"Applying 'during own turn' test effects to {during}")
                        
                        # Apply effects with different durations
                        for test_duration in [1, duration]:
                            # Create test effect
                            test_effect = TestEffect(
                                name=f"Test-D{test_duration}",
                                duration=None if permanent else test_duration,
                                marker=marker,
                                test_message=f"{message} (during={test_duration})",
                                permanent=permanent,
                                debug_mode=True  # Enable debug mode for testing
                            )
                            
                            # Apply the effect
                            try:
                                effect_msg = await apply_effect(
                                    character=during_char,
                                    effect=test_effect,
                                    round_number=current_round,
                                    combat_logger=self.bot.game_state.logger,
                                    is_combat_active=is_combat,
                                    initiative_tracker=initiative_tracker
                                )
                                
                                print(f"  {test_duration}-turn effect: {effect_msg}")
                                print(f"  Internal duration: {test_effect._internal_duration}")
                                print(f"  Display duration: {test_effect._display_duration}")
                                
                                results.append({
                                    "success": True,
                                    "character": during,
                                    "duration": test_duration,
                                    "internal": test_effect._internal_duration,
                                    "display": test_effect._display_duration,
                                    "timing": "during own turn"
                                })
                            except Exception as e:
                                print(f"Error applying 'during' test effect: {e}")
                                results.append({
                                    "success": False,
                                    "character": during,
                                    "duration": test_duration,
                                    "timing": "during own turn",
                                    "error": str(e)
                                })
                                
                        # Save character with effects
                        await self.bot.db.save_character(during_char)
                    else:
                        results.append({
                            "success": False,
                            "character": during,
                            "timing": "during own turn",
                            "error": f"Character '{during}' not found"
                        })
                
                # Process "not during own turn" character
                if not_during:
                    not_during_char = self.bot.game_state.get_character(not_during)
                    if not_during_char:
                        print(f"Applying 'not during own turn' test effects to {not_during}")
                        
                        # Apply effects with different durations
                        for test_duration in [1, duration]:
                            # Create test effect
                            test_effect = TestEffect(
                                name=f"Test-N{test_duration}",
                                duration=None if permanent else test_duration,
                                marker=marker,
                                test_message=f"{message} (not_during={test_duration})",
                                permanent=permanent,
                                debug_mode=True  # Enable debug mode for testing
                            )
                            
                            # Apply the effect
                            try:
                                effect_msg = await apply_effect(
                                    character=not_during_char,
                                    effect=test_effect,
                                    round_number=current_round,
                                    combat_logger=self.bot.game_state.logger,
                                    is_combat_active=is_combat,
                                    initiative_tracker=initiative_tracker
                                )
                                
                                print(f"  {test_duration}-turn effect: {effect_msg}")
                                print(f"  Internal duration: {test_effect._internal_duration}")
                                print(f"  Display duration: {test_effect._display_duration}")
                                
                                results.append({
                                    "success": True,
                                    "character": not_during,
                                    "duration": test_duration,
                                    "internal": test_effect._internal_duration,
                                    "display": test_effect._display_duration,
                                    "timing": "not during own turn"
                                })
                            except Exception as e:
                                print(f"Error applying 'not during' test effect: {e}")
                                results.append({
                                    "success": False,
                                    "character": not_during,
                                    "duration": test_duration,
                                    "timing": "not during own turn",
                                    "error": str(e)
                                })
                                
                        # Save character with effects
                        await self.bot.db.save_character(not_during_char)
                    else:
                        results.append({
                            "success": False,
                            "character": not_during,
                            "timing": "not during own turn",
                            "error": f"Character '{not_during}' not found"
                        })
                
                # Create bulk results embed
                embed = discord.Embed(
                    title="🧪 Bulk Test Effect Results",
                    description=f"Applied test effects with different timing scenarios",
                    color=discord.Color.purple()
                )
                
                # Add results to embed
                for result in results:
                    success_icon = "✅" if result.get("success", False) else "❌"
                    timing = result.get("timing", "unknown")
                    character = result.get("character", "unknown")
                    duration = result.get("duration", "N/A")
                    
                    if result.get("success", False):
                        internal = result.get("internal", "?")
                        display = result.get("display", "?")
                        value = f"Duration: {duration}\nInternal: {internal}\nDisplay: {display}"
                    else:
                        error = result.get("error", "Unknown error")
                        value = f"Error: {error}"
                    
                    embed.add_field(
                        name=f"{success_icon} {character} ({timing})",
                        value=value,
                        inline=False
                    )
                
                # Send combined results
                await interaction.followup.send(embed=embed)
            
            else:
                # SINGLE MODE: Apply to specified character
                if not character:
                    await interaction.followup.send("❌ Character is required when not using bulk mode.", ephemeral=True)
                    return
                    
                target_char = self.bot.game_state.get_character(character)
                if not target_char:
                    await interaction.followup.send(f"❌ Character '{character}' not found.", ephemeral=True)
                    return
                
                # Create test effect
                test_effect = TestEffect(
                    name="Enhanced Test Effect",
                    duration=None if permanent else duration,
                    marker=marker,
                    test_message=message,
                    permanent=permanent,
                    debug_mode=True  # Enable debug mode for testing
                )
                
                # Calculate if applied during own turn
                applied_during = "Yes" if (current_turn_name == character) else "No"
                print(f"Applying During Own Turn: {applied_during}")
                
                # Apply the effect
                effect_message = await apply_effect(
                    character=target_char,
                    effect=test_effect,
                    round_number=current_round,
                    combat_logger=self.bot.game_state.logger,
                    is_combat_active=is_combat,
                    initiative_tracker=initiative_tracker
                )
                
                # Print application result
                print(f"Effect applied, result: {effect_message}")
                print(f"Internal Duration: {test_effect._internal_duration}")
                print(f"Display Duration: {test_effect._display_duration}")
                
                # Save the character
                await self.bot.db.save_character(target_char)
                
                # Create response embed with detailed diagnostic info
                embed = discord.Embed(
                    title="🧪 Test Effect Applied",
                    description=effect_message,
                    color=discord.Color.purple()
                )
                
                # Add timing details
                applied_during = "DURING" if test_effect.timing and test_effect.timing.applied_during_own_turn else "NOT DURING"
                embed.add_field(
                    name="Timing Information",
                    value=f"Applied: {applied_during} own turn\nCombat: {'Active' if is_combat else 'Inactive'}\nRound: {current_round}",
                    inline=False
                )
                
                # Add duration details
                if permanent:
                    duration_text = "Permanent (no expiry)"
                else:
                    duration_text = f"Display Duration: {test_effect._display_duration}\nInternal Duration: {test_effect._internal_duration}"
                
                embed.add_field(
                    name="Duration Tracking",
                    value=duration_text,
                    inline=False
                )
                
                # Add effect parameters
                embed.add_field(
                    name="Effect Parameters",
                    value=f"Message: {message}\nMarker: {marker}",
                    inline=False
                )
                
                # Add disclaimer
                embed.set_footer(text="Check console for detailed debug output")
                
                # Send single result
                await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in test_effect_command: {e}", exc_info=True)
            print(f"ERROR in test_effect_command: {e}")
            await handle_error(interaction, e)

    @app_commands.command(name="debug")
    @app_commands.describe(
        character="The character to apply the debug effect to.",
        name="Optional custom name for the debug effect.",
        duration="Duration of the effect in turns (default: 2, ignored if permanent=true).",
        message="Optional custom message for the effect's updates.",
        timing="When the effect should process ('start', 'end', 'both', default: 'both').",
        force_during="Force effect to be applied during (true) or not during (false) character's turn.",
        permanent="Whether the effect should be permanent (never expires by duration)."
    )
    async def debug_effect(
        self,
        interaction: Interaction,
        character: str,
        name: Optional[str] = "Debug Effect",
        duration: Optional[int] = 2,
        message: Optional[str] = "Debugging...",
        timing: Optional[Literal['start', 'end', 'both']] = 'both',
        force_during: Optional[bool] = None,
        permanent: Optional[bool] = False
    ):
        """Applies a debug effect to test the effects system."""
        try:
            await interaction.response.defer()

            # Get the character object
            target_char = self.bot.game_state.get_character(character)
            if not target_char:
                await interaction.followup.send(f"❌ Character '{character}' not found.", ephemeral=True)
                return

            # Create the DebugEffect instance with permanent parameter
            debug_effect = DebugEffect(
                name=name,
                duration=None if permanent else duration,  # Set duration to None if permanent
                message=message,
                process_timing=timing
            )
            
            # Set the permanent flag explicitly
            debug_effect.permanent = permanent

            # Get initiative information
            initiative_tracker = None
            current_round = 1
            is_combat = False
            current_turn_name = None

            # Get the initiative tracker if available
            if hasattr(self.bot, 'initiative_tracker'):
                initiative_tracker = self.bot.initiative_tracker
                
                # Check if combat is active and get current turn directly
                if initiative_tracker.state.value != 'inactive':
                    is_combat = True
                    current_round = initiative_tracker.round_number
                    
                    # Get most accurate turn name
                    if hasattr(initiative_tracker, 'current_turn') and initiative_tracker.current_turn:
                        if hasattr(initiative_tracker.current_turn, 'character_name'):
                            current_turn_name = initiative_tracker.current_turn.character_name
                    elif (hasattr(initiative_tracker, 'turn_order') and 
                        hasattr(initiative_tracker, 'current_index') and 
                        initiative_tracker.turn_order and 
                        initiative_tracker.current_index < len(initiative_tracker.turn_order)):
                        
                        current_turn = initiative_tracker.turn_order[initiative_tracker.current_index]
                        if hasattr(current_turn, 'character_name'):
                            current_turn_name = current_turn.character_name

            # Print debug information before application
            print("\n=== Debug Effect Application Details ===")
            print(f"Target: {character}")
            print(f"Name: {name}")
            print(f"Duration: {duration}")
            print(f"Message: {message}")
            print(f"Timing: {timing}")
            print(f"Permanent: {permanent}")
            print(f"Force During: {force_during}")
            print(f"Combat Active: {is_combat}")
            print(f"Current Round: {current_round}")
            print(f"Current Turn: {current_turn_name}")

            # DIRECT OVERRIDE: Allow forced setting of "during own turn" status
            is_during_own_turn = None
            if force_during is not None:
                # Use explicit parameter if provided
                is_during_own_turn = force_during
                print(f"DEBUG: Forcing during_own_turn to {is_during_own_turn}")
            elif current_turn_name is not None:
                # Otherwise calculate based on current turn if known
                is_during_own_turn = (current_turn_name == character)
                print(f"DEBUG: Calculated during_own_turn: {is_during_own_turn} (current={current_turn_name}, target={character})")
            else:
                # Default when not in combat
                is_during_own_turn = not is_combat  # True when not in combat, False in combat
                print(f"DEBUG: Defaulting during_own_turn to {is_during_own_turn} (in_combat={is_combat})")

            # Skip duration adjustments for permanent effects
            if not permanent:
                # MANUAL ADJUSTMENT: Set up internal and display duration correctly
                if is_during_own_turn:
                    # For effects applied during own turn
                    if duration == 1:
                        # Special case for duration 1: Internal = 2, Display = 1
                        debug_effect._internal_duration = 2
                        debug_effect._display_duration = 1
                        print(f"DEBUG: Duration=1 applied during own turn. Set internal=2, display=1")
                    else:
                        # Normal case: Internal = Display + 1
                        debug_effect._internal_duration = duration + 1
                        debug_effect._display_duration = duration
                        print(f"DEBUG: Applied during own turn. Set internal={duration+1}, display={duration}")
                else:
                    # For effects NOT applied during own turn: use same value for internal and display
                    # Ensure duration is at least 1
                    safe_duration = max(1, duration)
                    debug_effect._internal_duration = safe_duration
                    debug_effect._display_duration = safe_duration
                    print(f"DEBUG: Applied NOT during own turn. Set internal={safe_duration}, display={safe_duration}")
            else:
                # Print info for permanent effects
                print(f"DEBUG: Effect is permanent, no duration adjustment needed")
            
            # Directly set timing information on the effect
            debug_effect.is_during_own_turn = is_during_own_turn
            debug_effect.current_turn_name = current_turn_name or "unknown"

            # DIRECT OVERRIDE: Pre-initialize timing to avoid relying on apply_effect logic
            debug_effect.timing = None  # Clear any existing timing
            
            # Apply the effect with minimal tracker dependencies
            apply_message = await apply_effect(
                character=target_char,
                effect=debug_effect,
                round_number=current_round,
                combat_logger=self.bot.game_state.logger,
                is_combat_active=is_combat,
                initiative_tracker=initiative_tracker
            )

            # Save character to persist effect
            await self.bot.db.save_character(target_char)

            # Print application message and timing info after
            print("\n=== Debug Effect After Application ===")
            print(f"Application Message: {apply_message}")
            
            # Find the applied effect and print its state
            for effect in target_char.effects:
                if isinstance(effect, DebugEffect) and effect.name == name:
                    print(f"Effect State: {effect.state.value}")
                    print(f"Internal Duration: {effect._internal_duration}")
                    print(f"Display Duration: {effect._display_duration}")
                    print(f"Permanent: {effect.permanent}")
                    print(f"Custom Message: {effect.custom_message}")
                    
                    if effect.timing:
                        applied_during = "DURING" if effect.timing.applied_during_own_turn else "NOT DURING"
                        print(f"Timing - Start Round: {effect.timing.start_round}")
                        print(f"Timing - Start Turn: {effect.timing.start_turn_name}")
                        print(f"Timing - Applied During: {applied_during}")

            # Create detailed embed for diagnosis
            embed = discord.Embed(
                title="Debug Effect Applied",
                description=apply_message,
                color=discord.Color.blue()
            )
            
            # Add combat state information
            combat_status = "Active" if is_combat else "Inactive"
            during_status = "YES" if is_during_own_turn else "NO"
            
            embed.add_field(
                name="Combat Status",
                value=f"```\nState: {combat_status}\nRound: {current_round}\nCurrent Turn: {current_turn_name or 'N/A'}\nTarget Character: {character}\nDuring Own Turn: {during_status}\n```",
                inline=False
            )
            
            # Add effect parameters
            embed.add_field(
                name="Effect Parameters",
                value=f"```\nName: {name}\nDisplay Duration: {duration if not permanent else 'N/A'}\nPermanent: {permanent}\nTiming: {timing}\nMessage: {message}\n```",
                inline=False
            )
            
            # Add internal timing info
            for effect in target_char.effects:
                if isinstance(effect, DebugEffect) and effect.name == name:
                    if effect.timing:
                        applied_during = "DURING" if effect.timing.applied_during_own_turn else "NOT DURING"
                        int_duration = effect._internal_duration if not permanent else "N/A"
                        disp_duration = effect._display_duration if not permanent else "N/A"
                        embed.add_field(
                            name="Internal State",
                            value=f"```\nApplied: {applied_during} own turn\nInternal Duration: {int_duration}\nDisplayed Duration: {disp_duration}\nPermanent: {effect.permanent}\nTurns Elapsed: {effect.turns_elapsed}\n```",
                            inline=False
                        )
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="bulk_burn")
    @app_commands.describe(
        during="Character to apply 'during own turn' burns to",
        not_during="Character to apply 'not during own turn' burns to"
    )
    async def bulk_burn_test(
        self,
        interaction: Interaction,
        during: Optional[str] = None,
        not_during: Optional[str] = None
    ):
        """Applies multiple burn effects for testing different timing scenarios."""
        await interaction.response.defer()
        
        # Track success and failures
        results = []
        
        print(f"\n=== BULK BURN TEST ===")
        print(f"During character: {during}")
        print(f"Not during character: {not_during}")
        
        # Get current round and turn info from initiative tracker
        current_round = 1
        current_turn_name = None
        initiative_active = False
        
        # Try to get initiative information if available
        if hasattr(self.bot, 'initiative_tracker'):
            tracker = self.bot.initiative_tracker
            initiative_active = tracker.state.value != 'inactive'
            current_round = tracker.round_number
            if tracker.current_turn:
                current_turn_name = tracker.current_turn.character_name
        
        # Apply "during own turn" burns if a character was specified
        if during:
            during_char = self.bot.game_state.get_character(during)
            if during_char:
                print(f"Applying 'during own turn' burns to {during}")
                
                # Set timing information explicitly
                is_during_own = True
                # Set during_char as current turn for accurate timing
                if initiative_active and current_turn_name != during:
                    print(f"Warning: {during} is not the current turn character, but setting as during own turn anyway")
                
                # Apply 1-turn burn
                burn1 = BurnEffect(
                    name="Burn-D1",
                    duration=1, 
                    damage_formula="1"
                )
                # IMPORTANT: Set these attributes BEFORE applying the effect
                burn1.is_during_own_turn = is_during_own
                burn1.current_turn_name = during
                
                msg1 = await apply_effect(
                    character=during_char,
                    effect=burn1,
                    round_number=current_round,
                    combat_logger=self.bot.game_state.logger,
                    is_combat_active=initiative_active
                )
                
                print(f"  1-turn burn: {msg1}")
                print(f"  Internal duration: {burn1._internal_duration}")
                print(f"  Display duration: {burn1._display_duration}")
                
                # Apply 2-turn burn
                burn2 = BurnEffect(
                    name="Burn-D2",
                    duration=2, 
                    damage_formula="1"
                )
                # IMPORTANT: Set these attributes BEFORE applying the effect
                burn2.is_during_own_turn = is_during_own
                burn2.current_turn_name = during
                
                msg2 = await apply_effect(
                    character=during_char,
                    effect=burn2,
                    round_number=current_round,
                    combat_logger=self.bot.game_state.logger,
                    is_combat_active=initiative_active
                )
                
                print(f"  2-turn burn: {msg2}")
                print(f"  Internal duration: {burn2._internal_duration}")
                print(f"  Display duration: {burn2._display_duration}")
                
                # Save character with effects
                await self.bot.db.save_character(during_char)
                
                results.append({
                    "character": during,
                    "timing": "during own turn",
                    "effects": [
                        {"duration": 1, "message": msg1, "internal": burn1._internal_duration},
                        {"duration": 2, "message": msg2, "internal": burn2._internal_duration}
                    ]
                })
            else:
                results.append({
                    "character": during,
                    "timing": "during own turn",
                    "error": f"Character '{during}' not found"
                })
        
        # Apply "not during own turn" burns if a character was specified
        if not_during:
            not_during_char = self.bot.game_state.get_character(not_during)
            if not_during_char:
                print(f"Applying 'not during own turn' burns to {not_during}")
                
                # Set timing information explicitly
                is_during_own = False
                
                # Apply 1-turn burn
                burn1 = BurnEffect(
                    name="Burn-N1",
                    duration=1, 
                    damage_formula="1"
                )
                # IMPORTANT: Set these attributes BEFORE applying the effect
                burn1.is_during_own_turn = is_during_own
                burn1.current_turn_name = current_turn_name or "unknown"
                
                msg1 = await apply_effect(
                    character=not_during_char,
                    effect=burn1,
                    round_number=current_round,
                    combat_logger=self.bot.game_state.logger,
                    is_combat_active=initiative_active
                )
                
                print(f"  1-turn burn: {msg1}")
                print(f"  Internal duration: {burn1._internal_duration}")
                print(f"  Display duration: {burn1._display_duration}")
                
                # Apply 2-turn burn
                burn2 = BurnEffect(
                    name="Burn-N2",
                    duration=2, 
                    damage_formula="1"
                )
                # IMPORTANT: Set these attributes BEFORE applying the effect
                burn2.is_during_own_turn = is_during_own
                burn2.current_turn_name = current_turn_name or "unknown"
                
                msg2 = await apply_effect(
                    character=not_during_char,
                    effect=burn2,
                    round_number=current_round,
                    combat_logger=self.bot.game_state.logger,
                    is_combat_active=initiative_active
                )
                
                print(f"  2-turn burn: {msg2}")
                print(f"  Internal duration: {burn2._internal_duration}")
                print(f"  Display duration: {burn2._display_duration}")
                
                # Save character with effects
                await self.bot.db.save_character(not_during_char)
                
                results.append({
                    "character": not_during,
                    "timing": "not during own turn",
                    "effects": [
                        {"duration": 1, "message": msg1, "internal": burn1._internal_duration},
                        {"duration": 2, "message": msg2, "internal": burn2._internal_duration}
                    ]
                })
            else:
                results.append({
                    "character": not_during,
                    "timing": "not during own turn",
                    "error": f"Character '{not_during}' not found"
                })
        
        # Create response embed
        embed = discord.Embed(
            title="🔥 Bulk Burn Test Results",
            description="Applied multiple burn effects with different timing scenarios",
            color=discord.Color.orange()
        )
        
        # Add results to embed
        for result in results:
            if "error" in result:
                embed.add_field(
                    name=f"{result['character']} ({result['timing']})",
                    value=f"❌ Error: {result['error']}",
                    inline=False
                )
            else:
                # Format effect details
                effect_details = []
                for effect in result["effects"]:
                    effect_details.append(
                        f"• {effect['duration']}-turn burn: Internal={effect['internal']}"
                    )
                
                embed.add_field(
                    name=f"{result['character']} ({result['timing']})",
                    value="\n".join(effect_details),
                    inline=False
                )
        
        # Send response
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="bulk_debug")
    @app_commands.describe(
        during="Character to apply 'during own turn' debug effects to",
        not_during="Character to apply 'not during own turn' debug effects to"
    )
    async def bulk_debug_test(
        self,
        interaction: Interaction,
        during: Optional[str] = None,
        not_during: Optional[str] = None
    ):
        """Applies multiple debug effects for testing different timing scenarios."""
        await interaction.response.defer()
        
        # Track success and failures
        results = []
        
        print(f"\n=== BULK DEBUG TEST ===")
        print(f"During character: {during}")
        print(f"Not during character: {not_during}")
        
        # Apply "during own turn" debug effects if a character was specified
        if during:
            during_char = self.bot.game_state.get_character(during)
            if during_char:
                print(f"Applying 'during own turn' debug effects to {during}")
                
                # Apply 1-turn debug effect
                debug1 = DebugEffect(
                    name="Debug-D1",
                    duration=1, 
                    message="Testing during own turn with 1 turn duration"
                )
                debug1.is_during_own_turn = True
                
                msg1 = await apply_effect(
                    character=during_char,
                    effect=debug1,
                    round_number=1,
                    combat_logger=self.bot.game_state.logger
                )
                
                print(f"  1-turn debug: {msg1}")
                print(f"  Internal duration: {debug1._internal_duration}")
                print(f"  Display duration: {debug1._display_duration}")
                
                # Apply 2-turn debug effect
                debug2 = DebugEffect(
                    name="Debug-D2",
                    duration=2, 
                    message="Testing during own turn with 2 turn duration"
                )
                debug2.is_during_own_turn = True
                
                msg2 = await apply_effect(
                    character=during_char,
                    effect=debug2,
                    round_number=1,
                    combat_logger=self.bot.game_state.logger
                )
                
                print(f"  2-turn debug: {msg2}")
                print(f"  Internal duration: {debug2._internal_duration}")
                print(f"  Display duration: {debug2._display_duration}")
                
                # Save character with effects
                await self.bot.db.save_character(during_char)
                
                results.append({
                    "character": during,
                    "timing": "during own turn",
                    "effects": [
                        {"duration": 1, "message": msg1, "internal": debug1._internal_duration},
                        {"duration": 2, "message": msg2, "internal": debug2._internal_duration}
                    ]
                })
            else:
                results.append({
                    "character": during,
                    "timing": "during own turn",
                    "error": f"Character '{during}' not found"
                })
        
        # Apply "not during own turn" debug effects if a character was specified
        if not_during:
            not_during_char = self.bot.game_state.get_character(not_during)
            if not_during_char:
                print(f"Applying 'not during own turn' debug effects to {not_during}")
                
                # Apply 1-turn debug effect
                debug1 = DebugEffect(
                    name="Debug-N1",
                    duration=1, 
                    message="Testing NOT during own turn with 1 turn duration"
                )
                debug1.is_during_own_turn = False
                
                msg1 = await apply_effect(
                    character=not_during_char,
                    effect=debug1,
                    round_number=1,
                    combat_logger=self.bot.game_state.logger
                )
                
                print(f"  1-turn debug: {msg1}")
                print(f"  Internal duration: {debug1._internal_duration}")
                print(f"  Display duration: {debug1._display_duration}")
                
                # Apply 2-turn debug effect
                debug2 = DebugEffect(
                    name="Debug-N2",
                    duration=2, 
                    message="Testing NOT during own turn with 2 turn duration"
                )
                debug2.is_during_own_turn = False
                
                msg2 = await apply_effect(
                    character=not_during_char,
                    effect=debug2,
                    round_number=1,
                    combat_logger=self.bot.game_state.logger
                )
                
                print(f"  2-turn debug: {msg2}")
                print(f"  Internal duration: {debug2._internal_duration}")
                print(f"  Display duration: {debug2._display_duration}")
                
                # Save character with effects
                await self.bot.db.save_character(not_during_char)
                
                results.append({
                    "character": not_during,
                    "timing": "not during own turn",
                    "effects": [
                        {"duration": 1, "message": msg1, "internal": debug1._internal_duration},
                        {"duration": 2, "message": msg2, "internal": debug2._internal_duration}
                    ]
                })
            else:
                results.append({
                    "character": not_during,
                    "timing": "not during own turn",
                    "error": f"Character '{not_during}' not found"
                })
        
        # Create response embed
        embed = discord.Embed(
            title="✨ Bulk Debug Test Results",
            description="Applied multiple debug effects with different timing scenarios",
            color=discord.Color.purple()
        )
        
        # Add results to embed
        for result in results:
            if "error" in result:
                embed.add_field(
                    name=f"{result['character']} ({result['timing']})",
                    value=f"❌ Error: {result['error']}",
                    inline=False
                )
            else:
                # Format effect details
                effect_details = []
                for effect in result["effects"]:
                    effect_details.append(
                        f"• {effect['duration']}-turn debug: Internal={effect['internal']}"
                    )
                
                embed.add_field(
                    name=f"{result['character']} ({result['timing']})",
                    value="\n".join(effect_details),
                    inline=False
                )
        
        # Send response
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="bulk_ac")
    @app_commands.describe(
        during="Character to apply 'during own turn' AC effects to",
        not_during="Character to apply 'not during own turn' AC effects to"
    )
    async def bulk_ac_test(
        self,
        interaction: discord.Interaction,
        during: Optional[str] = None,
        not_during: Optional[str] = None
    ):
        """Applies multiple AC effects for testing different timing scenarios."""
        await interaction.response.defer()
        
        # Track success and failures
        results = []
        
        print(f"\n=== BULK AC TEST ===")
        print(f"During character: {during}")
        print(f"Not during character: {not_during}")
        
        # Get current round and turn info from initiative tracker
        current_round = 1
        current_turn_name = None
        initiative_active = False
        
        # Try to get initiative information if available
        try:
            if hasattr(self.bot, 'initiative_tracker'):
                initiative_active = self.bot.initiative_tracker.state in ["active", "waiting"]
                current_round = self.bot.initiative_tracker.round_number
                if hasattr(self.bot.initiative_tracker, 'current_turn') and self.bot.initiative_tracker.current_turn:
                    current_turn_name = self.bot.initiative_tracker.current_turn.character_name
                print(f"Initiative tracker found: Round {current_round}, Current turn: {current_turn_name or 'None'}")
            else:
                print(f"No initiative tracker found - using default values")
                print(f"Default round: {current_round}, Default turn: {current_turn_name or 'None'}")
        except Exception as e:
            print(f"Error accessing initiative tracker: {e}")
            print(f"Using default values - Round: {current_round}, Turn: {current_turn_name or 'None'}")
        
        # Apply "during own turn" AC effects if a character was specified
        if during:
            target_char = self.bot.game_state.get_character(during)
            if target_char:
                print(f"Applying 'during own turn' AC effects to {during}")
                
                # Apply AC effects with different durations
                for duration in [1, 2, 3]:
                    print(f"Creating AC effect with duration {duration}, amount +{duration}")
                    # Create effect with amount based on duration
                    effect = ACEffect(
                        amount=duration,  # Amount equals duration for easy tracking
                        duration=duration,
                        permanent=False
                    )
                    
                    # Force during own turn
                    effect.is_during_own_turn = True
                    effect.current_turn_name = during  # Use character name as current turn
                    print(f"Set is_during_own_turn = True and current_turn_name = {during}")
                    
                    # Apply the effect
                    try:
                        print(f"Applying effect to {during} (during own turn, duration={duration})")
                        message = await apply_effect(
                            character=target_char,
                            effect=effect,
                            round_number=current_round,
                            combat_logger=self.bot.game_state.logger,
                            is_combat_active=initiative_active,
                            initiative_tracker=None  # Don't pass initiative tracker to avoid errors
                        )
                        
                        print(f"Success! Applied to {during}: AC +{duration} for {duration} turns")
                        print(f"Message: {message}")
                        
                        results.append({
                            "success": True,
                            "character": during,
                            "duration": duration,
                            "timing": "during own turn",
                            "message": f"Applied AC +{duration} for {duration} turns"
                        })
                    except Exception as e:
                        print(f"Error applying 'during' AC effect: {e}")
                        results.append({
                            "success": False,
                            "character": during,
                            "duration": duration,
                            "timing": "during own turn",
                            "message": f"Error: {str(e)}"
                        })
                
                # Save character with new AC effects
                await self.bot.db.save_character(target_char)
                print(f"Character {during} saved successfully")
            else:
                print(f"Character '{during}' not found!")
                results.append({
                    "success": False,
                    "character": during,
                    "timing": "during own turn",
                    "message": f"Character '{during}' not found"
                })
        
        # Apply "not during own turn" AC effects if a character was specified
        if not_during:
            target_char = self.bot.game_state.get_character(not_during)
            if target_char:
                print(f"Applying 'not during own turn' AC effects to {not_during}")
                
                # Apply AC effects with different durations
                for duration in [1, 2, 3]:
                    print(f"Creating AC effect with duration {duration}, amount -{duration}")
                    # Create effect with negative amount based on duration
                    effect = ACEffect(
                        amount=-duration,  # Negative amount equals duration for easy tracking
                        duration=duration,
                        permanent=False
                    )
                    
                    # Force not during own turn
                    effect.is_during_own_turn = False
                    # Set current turn to someone else
                    fake_turn = "other_character" if not_during != "other_character" else "some_other_character"
                    effect.current_turn_name = fake_turn
                    print(f"Set is_during_own_turn = False and current_turn_name = {fake_turn}")
                    
                    # Apply the effect
                    try:
                        print(f"Applying effect to {not_during} (not during own turn, duration={duration})")
                        message = await apply_effect(
                            character=target_char,
                            effect=effect,
                            round_number=current_round,
                            combat_logger=self.bot.game_state.logger,
                            is_combat_active=initiative_active,
                            initiative_tracker=None  # Don't pass initiative tracker to avoid errors
                        )
                        
                        print(f"Success! Applied to {not_during}: AC -{duration} for {duration} turns")
                        print(f"Message: {message}")
                        
                        results.append({
                            "success": True,
                            "character": not_during,
                            "duration": duration,
                            "timing": "not during own turn",
                            "message": f"Applied AC -{duration} for {duration} turns"
                        })
                    except Exception as e:
                        print(f"Error applying 'not during' AC effect: {e}")
                        results.append({
                            "success": False,
                            "character": not_during,
                            "duration": duration,
                            "timing": "not during own turn",
                            "message": f"Error: {str(e)}"
                        })
                
                # Save character with new AC effects
                await self.bot.db.save_character(target_char)
                print(f"Character {not_during} saved successfully")
            else:
                print(f"Character '{not_during}' not found!")
                results.append({
                    "success": False,
                    "character": not_during,
                    "timing": "not during own turn",
                    "message": f"Character '{not_during}' not found"
                })
        
        # Print summary of effect applications
        print("\n=== BULK AC TEST RESULTS ===")
        for result in results:
            success = "✅ Success" if result["success"] else "❌ Failed"
            print(f"{success}: {result['character']} - {result['timing']} - {result['message']}")
        
        # Create response embed
        embed = discord.Embed(
            title="🛡️ Bulk AC Test Results",
            description="Applied multiple AC effects with different timing scenarios",
            color=discord.Color.blue()
        )
        
        # Add results to embed
        for result in results:
            success_icon = "✅" if result["success"] else "❌"
            timing = result.get("timing", "unknown")
            character = result.get("character", "unknown")
            duration = result.get("duration", "N/A")
            
            embed.add_field(
                name=f"{success_icon} {character} - {timing}",
                value=f"Duration: {duration}\n{result['message']}",
                inline=False
            )
        
        # Send response
        await interaction.followup.send(embed=embed)

async def setup(bot):
    # Ensure effects are registered before adding the cog
    register_effects()
    await bot.add_cog(EffectsCommands(bot))
    logger.info("EffectsCommands Cog loaded.")