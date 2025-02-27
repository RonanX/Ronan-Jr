"""Combat commands for managing damage and combat effects."""

import logging
import asyncio
import re
import random
from typing import Optional, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from core.character import Character
from core.effects.combat import DamageCalculator, DamageType, TempHPEffect
from utils.error_handler import handle_error
from utils.dice import DiceRoller
from utils.formatting import MessageFormatter
from modules.combat.logger import CombatEventType

logger = logging.getLogger(__name__)

def apply_damage(target: Character, damage: int) -> Tuple[int, int, int]:
    """
    Apply damage to a character, handling temp HP
    Returns (damage_dealt, absorbed_by_temp, final_hp)
    """
    # Handle temp HP first
    absorbed, remaining = target.resources.remove_temp_hp(damage)
    
    # Apply remaining damage to regular HP
    old_hp = target.resources.current_hp
    target.resources.current_hp = max(0, old_hp - remaining)
    
    return remaining, absorbed, target.resources.current_hp

class CombatCommands(commands.Cog):
    """Commands for handling combat and damage"""
    def __init__(self, bot):
        self.bot = bot
        
        # Dictionary of damage type verbs for more natural messages
        self.damage_verbs = {
            "slashing": ["slashes", "cuts", "carves into", "slices"],
            "piercing": ["pierces", "impales", "stabs", "punctures"],
            "bludgeoning": ["bashes", "smashes", "strikes", "pummels"],
            "fire": ["burns", "scorches", "ignites", "sears"],
            "cold": ["freezes", "chills", "frosts", "ices"],
            "lightning": ["shocks", "electrocutes", "zaps", "jolts"],
            "acid": ["melts", "corrodes", "dissolves", "eats away at"],
            "poison": ["poisons", "toxifies", "envenoms", "sickens"],
            "necrotic": ["withers", "decays", "drains", "corrupts"],
            "radiant": ["sears", "purifies", "smites", "blasts"],
            "psychic": ["distresses", "traumatizes", "torments", "assaults"],
            "force": ["blasts", "slams", "impacts", "hammers"],
            "thunder": ["deafens", "blasts", "concusses", "thunders against"],
            "generic": ["damages", "strikes", "attacks", "harms"]
        }

    @app_commands.command(name="harm")
    @app_commands.describe(
        name="Character being attacked",
        damage="Damage amount/dice and types (e.g., '2d6+3 slashing, 1d8 fire')",
        attacker="Character dealing the damage (for modifiers)",
        crit="Whether this is a critical hit (doubles dice)",
        reason="Reason for the damage (optional)"
    )
    async def harm(
        self,
        interaction: discord.Interaction,
        name: str,
        damage: str,
        attacker: Optional[str] = None,
        crit: bool = False,
        reason: Optional[str] = None
    ):
        """Process and apply damage to a character"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Find target character
            target = self.bot.game_state.get_character(name)
            if not target:
                await interaction.followup.send(
                    f"❌ Character '{name}' not found.",
                    ephemeral=True
                )
                return

            # Get attacker if specified
            attacker_char = None
            if attacker:
                attacker_char = self.bot.game_state.get_character(attacker)
                if not attacker_char and any(
                    mod in damage.lower() 
                    for mod in ['str', 'dex', 'con', 'int', 'wis', 'cha']
                ):
                    await interaction.followup.send(
                        f"❌ Attacker '{attacker}' not found (required for stat modifiers).",
                        ephemeral=True
                    )
                    return

            # Get combat logger if in combat
            combat_logger = None
            if hasattr(self.bot, 'initiative_tracker'):
                combat_logger = self.bot.initiative_tracker.logger

            if combat_logger:
                combat_logger.snapshot_character_state(target)

            # Process each damage component
            damage_results = []  # [(original, type, final, absorbed, increase)]
            total_damage = 0
            rolls_explanation = []
            
            # Split multiple damage types
            for part in damage.split(','):
                part = part.strip()
                if not part:
                    continue
                    
                try:
                    # Split amount and type
                    if ' ' in part:
                        amount_str, damage_type = part.rsplit(' ', 1)
                    else:
                        amount_str, damage_type = part, 'generic'
                    
                    # Handle crit dice doubling
                    if crit and 'd' in amount_str.lower():
                        amount_str = re.sub(
                            r'(\d+)d',
                            lambda m: f"{int(m.group(1))*2}d",
                            amount_str
                        )
                    
                    # Roll damage
                    amount, roll_exp = DiceRoller.roll_dice(amount_str, attacker_char)
                    damage_type = DamageType.from_string(damage_type)
                    
                    # Calculate final damage
                    result = DamageCalculator.calculate_damage(
                        amount, damage_type, target, attacker_char
                    )
                    
                    # Track results
                    damage_results.append((
                        amount,  # original
                        str(damage_type),  # type
                        result.final_damage,  # final
                        result.absorbed_by_temp_hp,  # absorbed
                        result.vulnerability_increase  # increase
                    ))
                    
                    total_damage += result.final_damage
                    rolls_explanation.append(f"{roll_exp} {damage_type}")
                    
                except ValueError as e:
                    logger.warning(f"Error processing damage part '{part}': {e}")
                    continue

            if not damage_results:
                await interaction.followup.send(
                    "❌ Invalid damage format. Use: '2d6+3 slashing, 1d8 fire'",
                    ephemeral=True
                )
                return

            # Show roll details privately
            roll_msg = "🎲 **Damage Rolls**\n" + "\n".join(f"• {roll}" for roll in rolls_explanation)
            await interaction.followup.send(roll_msg, ephemeral=True)
            
            # Print debug info about the command
            print(f"Command: /harm {name} {damage}{' --attacker '+attacker if attacker else ''}{' --crit' if crit else ''}{' --reason \"'+reason+'\"' if reason else ''}")
            
            # Apply final damage
            if total_damage > 0:
                old_hp = target.resources.current_hp
                final_damage, absorbed, final_hp = apply_damage(target, total_damage)
                
                # Generate a human-readable message
                message = self._generate_damage_message(
                    target=target,
                    attacker=attacker,
                    attacker_char=attacker_char,
                    damage_results=damage_results,
                    total_damage=total_damage,
                    absorbed=absorbed,
                    old_hp=old_hp,
                    final_hp=final_hp,
                    crit=crit,
                    reason=reason
                )
                
                # Log damage if in combat
                if combat_logger:
                    combat_logger.add_event(
                        CombatEventType.DAMAGE_DEALT,
                        message=f"Takes {total_damage} damage",
                        character=target.name,
                        details={
                            "damage": total_damage,
                            "breakdown": damage_results,
                            "attacker": attacker,
                            "old_hp": old_hp,
                            "new_hp": final_hp,
                            "absorbed": absorbed,
                            "reason": reason,
                            "crit": crit
                        }
                    )
                    combat_logger.snapshot_character_state(target)
                
                # Send direct message to channel
                await interaction.channel.send(message)
                
                # If character is incapacitated, send a dramatic message
                if final_hp == 0:
                    if attacker:
                        await interaction.channel.send(f"⚠️ {attacker} has struck down {target.name}! ⚠️")
                    else:
                        await interaction.channel.send(f"⚠️ {target.name} has fallen! ⚠️")

            # Save character changes
            await self.bot.db.save_character(target)

        except Exception as e:
            logger.error(f"Error in harm command: {str(e)}", exc_info=True)
            await handle_error(interaction, e)

    def _generate_damage_message(
        self,
        target,
        attacker,
        attacker_char,
        damage_results,
        total_damage,
        absorbed,
        old_hp,
        final_hp,
        crit=False,
        reason=None
    ) -> str:
        """Generate a human-readable damage message"""
        
        # Get primary damage type for verb selection
        damage_types = [t for _, t, _, _, _ in damage_results]
        primary_type = damage_types[0] if damage_types else "generic"
        
        # Start with appropriate prefix based on whether there's an attacker
        if attacker and attacker_char:
            # Attack from character to character
            verb_options = self.damage_verbs.get(primary_type, self.damage_verbs["generic"])
            verb = random.choice(verb_options)
            
            # Construct main message with backticks
            if crit:
                main_part = f"{attacker} critically {verb} {target.name} for {total_damage} damage"
                prefix = "⚔️ `"
            else:
                main_part = f"{attacker} {verb} {target.name} for {total_damage} damage"
                prefix = "⚔️ `"
        else:
            # No attacker specified
            if crit:
                main_part = f"CRITICAL HIT! {target.name} takes {total_damage} damage"
                prefix = "💥 `"
            else:
                main_part = f"{target.name} takes {total_damage} damage"
                prefix = "💥 `"
        
        # Add damage type breakdown if there are multiple types
        if len(damage_results) > 1:
            # Multiple damage types, list them
            types_list = [f"{final} {type}" for _, type, final, _, _ in damage_results]
            main_part += f" ({', '.join(types_list)})"
        elif len(damage_results) == 1:
            # Single damage type, just add the type
            main_part += f" ({damage_results[0][1]})"
        
        # Add resistance/vulnerability info if applicable
        for orig, type, final, _, vuln in damage_results:
            if orig != final and final < orig:
                # Add resistance info
                resist_pct = round((1 - final/orig) * 100)
                if resist_pct > 0:
                    main_part += f", resisted {resist_pct}%"
                    break  # Only show first resistance
            elif vuln > 0:
                # Add vulnerability info
                main_part += f", vulnerable +{vuln}%"
                break  # Only show first vulnerability
        
        # Add temp HP absorption if any
        if absorbed > 0:
            main_part += f", {absorbed} absorbed by shield"
            
        # Close backticks
        main_part += "`"
        
        # Construct full message with HP status
        message = f"{prefix}{main_part}. HP: {final_hp}/{target.resources.max_hp}"
        
        # Add reason if provided
        if reason:
            message += f" ({reason})"
        
        return message

    @app_commands.command(name="temp_hp")
    @app_commands.describe(
        name="Character to receive temp HP",
        amount="Amount of temp HP (can use dice)",
        duration="Duration in turns (optional)",
        reason="Reason for the temp HP (optional)"
    )
    async def temp_hp(
        self,
        interaction: discord.Interaction,
        name: str,
        amount: str,
        duration: Optional[int] = None,
        reason: Optional[str] = None
    ):
        """Grant temporary HP to a character"""
        try:
            await interaction.response.defer(ephemeral=True)

            # Get character
            char = self.bot.game_state.get_character(name)
            if not char:
                await interaction.followup.send(
                    f"❌ Character '{name}' not found.",
                    ephemeral=True
                )
                return

            # Roll temp HP amount
            try:
                hp_amount, roll_exp = DiceRoller.roll_dice(amount)
            except ValueError as e:
                await interaction.followup.send(
                    f"❌ Invalid amount format: {e}",
                    ephemeral=True
                )
                return

            # Get combat logger if in combat
            combat_logger = None
            if hasattr(self.bot, 'initiative_tracker'):
                combat_logger = self.bot.initiative_tracker.logger

            if combat_logger:
                combat_logger.snapshot_character_state(char)

            # Create and apply temp HP effect
            effect = TempHPEffect(hp_amount, duration)
            old_temp = char.resources.current_temp_hp
            char.add_effect(effect)
            new_temp = char.resources.current_temp_hp

            # Show roll details privately
            await interaction.followup.send(
                f"🎲 Temp HP roll: {DiceRoller.format_roll_result(hp_amount, roll_exp)}",
                ephemeral=True
            )
            
            # Print debug info
            print(f"Command: /temp_hp {name} {amount}{' --duration '+str(duration) if duration else ''}{' --reason \"'+reason+'\"' if reason else ''}")
            
            # Create main message part
            main_part = f"{char.name} gains {hp_amount} temporary HP"
            
            # Add duration if specified
            if duration:
                main_part += f" for {duration} turns"
                
            # Construct full message with backticks
            message = f"🛡️ `{main_part}`"
                
            # Add reason if provided
            if reason:
                message += f" ({reason})"
                
            # Add current shields info
            message += f". Shield: {new_temp}, HP: {char.resources.current_hp}/{char.resources.max_hp}"
            
            # Log if in combat
            if combat_logger:
                combat_logger.add_event(
                    CombatEventType.RESOURCE_CHANGE,
                    message=f"Gains {hp_amount} temporary HP",
                    character=char.name,
                    details={
                        "resource": "temp_hp",
                        "amount": hp_amount,
                        "old_value": old_temp,
                        "new_value": new_temp,
                        "duration": duration,
                        "reason": reason
                    }
                )
                combat_logger.snapshot_character_state(char)

            await interaction.channel.send(message)
            await self.bot.db.save_character(char)

        except Exception as e:
            await handle_error(interaction, e)

async def setup(bot):
    await bot.add_cog(CombatCommands(bot))