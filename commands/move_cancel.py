"""
Command for canceling active moves with resource refund options.
"""

import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Optional, List
import re

from core.effects.move.effect import MoveEffect

logger = logging.getLogger(__name__)

class MoveCancelCommands(commands.Cog):
    """Commands for canceling active moves"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="move_cancel", description="Cancel an active move")
    @app_commands.describe(
        character="The character whose move to cancel",
        move_name="Partial name of the move to cancel (case-insensitive)",
        refund="Whether to refund resource costs (default: False)"
    )
    async def move_cancel(
        self, 
        interaction: discord.Interaction, 
        character: str,
        move_name: str,
        refund: Optional[bool] = False
    ):
        """
        Cancel an active move effect for a character.
        Optionally refunds the resource costs.
        
        Args:
            character: Name of the character
            move_name: Name of the move to cancel (partial name is allowed)
            refund: Whether to refund resource costs
        """
        await interaction.response.defer()
        
        try:
            # Get the character
            character_obj = self.bot.game_state.get_character(character)
            if not character_obj:
                await interaction.followup.send(f"Character '{character}' not found.", ephemeral=True)
                return
            
            # Find the move effect
            found_effects = []
            move_pattern = re.compile(re.escape(move_name), re.IGNORECASE)
            
            for effect in character_obj.effects:
                if isinstance(effect, MoveEffect) and move_pattern.search(effect.name):
                    found_effects.append(effect)
            
            if not found_effects:
                await interaction.followup.send(
                    f"No active move effects matching '{move_name}' found for {character}.", 
                    ephemeral=True
                )
                return
                
            # If multiple matches, use the closest one
            if len(found_effects) > 1:
                exact_matches = [e for e in found_effects if e.name.lower() == move_name.lower()]
                if exact_matches:
                    # Prefer exact matches
                    target_effect = exact_matches[0]
                else:
                    # Use the first match
                    target_effect = found_effects[0]
                    
                # Inform about multiple matches
                effect_names = [e.name for e in found_effects]
                await interaction.followup.send(
                    f"Multiple moves matched '{move_name}': {', '.join(effect_names)}. Cancelling '{target_effect.name}'."
                )
            else:
                target_effect = found_effects[0]
            
            # Process refund if requested
            refund_msg = ""
            if refund:
                # Check for resource costs
                refunded = []
                
                # MP refund
                if hasattr(target_effect, 'mp_cost') and target_effect.mp_cost > 0:
                    if hasattr(character_obj, 'resources') and hasattr(character_obj.resources, 'current_mp'):
                        # Add MP back, capped at max_mp
                        mp_to_add = min(
                            target_effect.mp_cost,
                            character_obj.resources.max_mp - character_obj.resources.current_mp
                        )
                        if mp_to_add > 0:
                            character_obj.resources.current_mp += mp_to_add
                            refunded.append(f"{mp_to_add} MP")
                
                # HP refund
                if hasattr(target_effect, 'hp_cost') and target_effect.hp_cost > 0:
                    if hasattr(character_obj, 'resources') and hasattr(character_obj.resources, 'current_hp'):
                        # Add HP back, capped at max_hp
                        hp_to_add = min(
                            target_effect.hp_cost,
                            character_obj.resources.max_hp - character_obj.resources.current_hp
                        )
                        if hp_to_add > 0:
                            character_obj.resources.current_hp += hp_to_add
                            refunded.append(f"{hp_to_add} HP")
                
                # Star refund
                if hasattr(target_effect, 'star_cost') and target_effect.star_cost > 0:
                    if hasattr(character_obj, 'action_stars') and hasattr(character_obj.action_stars, 'current_stars'):
                        # Add stars back, capped at max_stars
                        stars_to_add = min(
                            target_effect.star_cost,
                            character_obj.action_stars.max_stars - character_obj.action_stars.current_stars
                        )
                        if stars_to_add > 0:
                            character_obj.action_stars.current_stars += stars_to_add
                            refunded.append(f"{stars_to_add} ⭐")
                
                # Format refund message
                if refunded:
                    refund_msg = f" Refunded: {', '.join(refunded)}."
            
            # Mark the effect as expired
            if hasattr(target_effect, 'marked_for_removal'):
                target_effect.marked_for_removal = True
            
            # Execute expire logic directly
            if hasattr(target_effect, 'on_expire'):
                expiry_message = target_effect.on_expire(character_obj)
            else:
                expiry_message = f"{target_effect.name} has been cancelled"
            
            # Add expire message to effects feedback
            if hasattr(character_obj, 'effect_feedback') and hasattr(character_obj.effect_feedback, 'add_feedback'):
                character_obj.effect_feedback.add_feedback(
                    round_number=getattr(character_obj, 'round_number', 1),
                    effect_name=target_effect.name,
                    expiry_message=expiry_message,
                    is_expiry=True
                )
            
            # Remove the effect
            if target_effect in character_obj.effects:
                character_obj.effects.remove(target_effect)
            
            # Add feedback message
            embed = discord.Embed(
                title="Move Cancelled",
                description=f"Cancelled {target_effect.name} for {character}.{refund_msg}",
                color=discord.Color.orange()
            )
            
            # Show effect info if available
            if hasattr(target_effect, 'description') and target_effect.description:
                embed.add_field(name="Description", value=target_effect.description, inline=False)
            
            # Show current resources
            if hasattr(character_obj, 'resources'):
                res = character_obj.resources
                embed.add_field(
                    name="Current Resources",
                    value=f"HP: {res.current_hp}/{res.max_hp} | MP: {res.current_mp}/{res.max_mp}",
                    inline=False
                )
            
            # Save character state
            if hasattr(self.bot, 'db'):
                await self.bot.db.save_character(character_obj)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in move_cancel command: {e}", exc_info=True)
            await interaction.followup.send(
                f"An error occurred while cancelling the move: {str(e)}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(MoveCancelCommands(bot))
