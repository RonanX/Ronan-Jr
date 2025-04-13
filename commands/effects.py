"""
Discord commands for managing and debugging character effects.
"""

import logging
import discord
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Optional, Literal, List

# Import necessary components from the core effects system
from modules.combat.initiative import InitiativeTracker
from core.effects.manager import apply_effect, remove_effect, EffectRegistry, register_effects, get_effect_summary
from core.effects.debug_effect import DebugEffect # Import the specific debug effect
from core.character import Character
from utils.error_handler import handle_error

logger = logging.getLogger(__name__)

# Ensure effects are registered when this module is loaded
register_effects()

class EffectsCommands(commands.GroupCog, name="effect"):
    """Commands related to character effects"""

    def __init__(self, bot):
        self.bot = bot
        super().__init__()

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
            if debug_effect.timing:
                applied_during = "DURING" if debug_effect.timing.applied_during_own_turn else "NOT DURING"
                int_duration = debug_effect._internal_duration if not permanent else "N/A"
                disp_duration = debug_effect._display_duration if not permanent else "N/A"
                embed.add_field(
                    name="Internal State",
                    value=f"```\nApplied: {applied_during} own turn\nInternal Duration: {int_duration}\nDisplayed Duration: {disp_duration}\nPermanent: {debug_effect.permanent}\nTurns Elapsed: {debug_effect.turns_elapsed}\n```",
                    inline=False
                )
            
            # DEBUG LOG: Print the embed content to the console
            print("\n=== DEBUG EFFECT EMBED CONTENT ===")
            print(f"Title: {embed.title}")
            print(f"Description: {embed.description}")
            for field in embed.fields:
                print(f"\nField: {field.name}")
                print(f"Value: {field.value}")
            print("=== END EMBED CONTENT ===\n")
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="remove")
    @app_commands.describe(
        character="The character to remove the effect from.",
        effect_name="The exact name of the effect to remove."
    )
    async def remove_effect_command(
        self,
        interaction: Interaction,
        character: str,
        effect_name: str
    ):
        """Removes a specific effect from a character."""
        try:
            await interaction.response.defer()

            target_char = self.bot.game_state.get_character(character)
            if not target_char:
                await interaction.followup.send(f"❌ Character '{character}' not found.", ephemeral=True)
                return

            # Remove the effect using the manager function
            remove_message = await remove_effect(
                character=target_char,
                effect_name=effect_name,
                combat_logger=self.bot.game_state.logger # Pass the logger
            )

            await interaction.followup.send(remove_message)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="list")
    @app_commands.describe(
        character="The character to list effects for."
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

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="debug_bulk")
    @app_commands.describe(
        char1="First character to apply effects to (for DURING effects)",
        char2="Second character to apply effects to (for NOT DURING effects)",
        effect_prefix="Prefix to add to effect names for identification (default: '')"
    )
    async def debug_bulk_effects(
        self,
        interaction: Interaction,
        char1: str,
        char2: str,
        effect_prefix: Optional[str] = ""
    ):
        """Applies a set of 4 test effects (1 and 2 turn durations, DURING and NOT DURING) to two characters."""
        try:
            await interaction.response.defer()

            # Get the characters
            char1_obj = self.bot.game_state.get_character(char1)
            char2_obj = self.bot.game_state.get_character(char2)
            
            if not char1_obj:
                await interaction.followup.send(f"❌ Character '{char1}' not found.", ephemeral=True)
                return
                
            if not char2_obj:
                await interaction.followup.send(f"❌ Character '{char2}' not found.", ephemeral=True)
                return

            # Add prefix if provided
            prefix = f"{effect_prefix} " if effect_prefix else ""
            
            # Create effect descriptions
            effects = [
                # DURING effects for char1
                {
                    "character": char1_obj,
                    "name": f"{prefix}2 turns during",
                    "duration": 2,
                    "message": "Debugging...",
                    "force_during": True
                },
                {
                    "character": char1_obj,
                    "name": f"{prefix}1 turn during",
                    "duration": 1,
                    "message": "Debugging...",
                    "force_during": True
                },
                # NOT DURING effects for char2
                {
                    "character": char2_obj,
                    "name": f"{prefix}2 turns not during",
                    "duration": 2,
                    "message": "Debugging...",
                    "force_during": False
                },
                {
                    "character": char2_obj,
                    "name": f"{prefix}1 turn not during",
                    "duration": 1,
                    "message": "Debugging...",
                    "force_during": False
                }
            ]
            
            # Print log header for this command
            print("\n=== BULK DEBUG EFFECT PROCESSING ===")
            
            # Apply all effects
            applied_effects = []
            for effect_info in effects:
                # Create a DebugEffect with the parameters
                debug_effect = DebugEffect(
                    name=effect_info["name"],
                    duration=effect_info["duration"],
                    message=effect_info["message"]
                )
                
                # Get current round info
                initiative_tracker = None
                current_round = 1
                is_combat = False
                
                # Get initiative info if available
                if hasattr(self.bot, 'initiative_tracker'):
                    initiative_tracker = self.bot.initiative_tracker
                    if initiative_tracker.state.value != 'inactive':
                        is_combat = True
                        current_round = initiative_tracker.round_number
                
                # Set the force_during flag
                debug_effect.is_during_own_turn = effect_info["force_during"]
                
                # Log the type of effect being created
                print(f"\nCreating effect: {effect_info['name']} for {effect_info['character'].name}")
                print(f"During Own Turn: {effect_info['force_during']}")
                
                # Directly handle duration adjustments like in debug_effect command
                if not debug_effect.permanent:
                    if effect_info["force_during"]:
                        # For DURING own turn effects
                        if effect_info["duration"] == 1:
                            # Duration=1 special case
                            debug_effect._internal_duration = 2
                            debug_effect._display_duration = 1
                            print(f"DEBUG: Duration=1 applied during own turn. Set internal=2, display=1")
                        else:
                            # Normal case for DURING
                            debug_effect._internal_duration = effect_info["duration"] + 1
                            debug_effect._display_duration = effect_info["duration"]
                            print(f"DEBUG: Applied during own turn. Set internal={effect_info['duration']+1}, display={effect_info['duration']}")
                    else:
                        # For NOT DURING effects - same internal & display
                        safe_duration = max(1, effect_info["duration"])
                        debug_effect._internal_duration = safe_duration
                        debug_effect._display_duration = safe_duration
                        print(f"DEBUG: Applied NOT during own turn. Set internal={safe_duration}, display={safe_duration}")
                
                # Apply the effect using manager function
                apply_msg = await apply_effect(
                    character=effect_info["character"],
                    effect=debug_effect,
                    round_number=current_round,
                    combat_logger=self.bot.game_state.logger,
                    is_combat_active=is_combat,
                    initiative_tracker=initiative_tracker
                )
                
                # Print effect application message
                print(f"Applied: {apply_msg}")
                
                # Store effect info for the response embed
                applied_effects.append({
                    "character": effect_info["character"].name,
                    "effect": debug_effect.name,
                    "message": apply_msg,
                    "internal_duration": debug_effect._internal_duration,
                    "display_duration": debug_effect._display_duration,
                    "during_own_turn": effect_info["force_during"]
                })
                
                # Save after each application
                await self.bot.db.save_character(effect_info["character"])
            
            # Create response embed
            embed = discord.Embed(
                title="Bulk Debug Effects Applied",
                description=f"Applied 4 test effects to {char1} and {char2}",
                color=discord.Color.blue()
            )
            
            # Add fields for each effect
            for effect_data in applied_effects:
                # Create detailed info about the effect
                details = [
                    f"Applied to: {effect_data['character']}",
                    f"Type: {'DURING' if effect_data['during_own_turn'] else 'NOT DURING'} own turn",
                    f"Internal Duration: {effect_data['internal_duration']}",
                    f"Display Duration: {effect_data['display_duration']}"
                ]
                
                # Fix the message if needed to match the effect type
                effect_msg = effect_data["message"]
                if not effect_data["during_own_turn"] and "DURING turn" in effect_msg and "NOT DURING turn" not in effect_msg:
                    effect_msg = effect_msg.replace("DURING turn", "NOT DURING turn")
                
                # Add field for this effect
                embed.add_field(
                    name=effect_data['effect'],
                    value=f"{effect_msg}\n\n```\n{chr(10).join(details)}\n```",
                    inline=False
                )
            
            # DEBUG LOG: Print the embed content to the console
            print("\n=== BULK DEBUG EFFECT EMBED CONTENT ===")
            print(f"Title: {embed.title}")
            print(f"Description: {embed.description}")
            for field in embed.fields:
                print(f"\nField: {field.name}")
                print(f"Value: {field.value}")
            print("=== END EMBED CONTENT ===\n")
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await handle_error(interaction, e)

async def setup(bot):
    # Ensure effects are registered before adding the cog
    register_effects()
    await bot.add_cog(EffectsCommands(bot))
    logger.info("EffectsCommands Cog loaded.")