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
                if is_during_own_turn and not debug_effect.permanent:
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
                    # For effects NOT applied during own turn: ensure positive internal duration
                    debug_effect._internal_duration = max(1, duration)
                    debug_effect._display_duration = duration
                    print(f"DEBUG: Applied NOT during own turn. Set internal={max(1, duration)}, display={duration}")
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

async def setup(bot):
    # Ensure effects are registered before adding the cog
    register_effects()
    await bot.add_cog(EffectsCommands(bot))
    logger.info("EffectsCommands Cog loaded.")