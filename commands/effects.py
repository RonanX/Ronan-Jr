"""
Discord commands for managing character effects.

Message Format Standard:
All feedback messages should follow the format: `[emoji] [backticked message] [emoji]`
Example: ✨ `Effect applied to Character` ✨

Adhere to base.py's guidelines so that there are no errors for backticks
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Tuple, List, Any, Dict

import discord
from discord import Interaction, SelectOption, app_commands
from discord.ui import Select, View
from discord.ext import commands

from utils.error_handler import handle_error
from utils.formatting import MessageFormatter

from core.effects.base import EffectRegistry, BaseEffect, EffectCategory, CustomEffect
from core.effects.manager import apply_effect, remove_effect, get_effect_summary
from core.effects.combat import (
    BurnEffect, SourceHeatWaveEffect, TargetHeatWaveEffect, 
    TempHPEffect, ResistanceEffect, VulnerabilityEffect, WeaknessEffect, ShockEffect
)
from core.effects.resource import DrainEffect, RegenEffect
from core.effects.status import ACEffect, FrostbiteEffect, SkipEffect
from core.effects.condition import ConditionEffect, ConditionType, CONDITION_PROPERTIES
from core.effects.move import MoveEffect

from modules.combat.logger import CombatEventType, CombatLogger
from modules.combat.initiative import CombatState
from modules.moves.data import MoveData



logger = logging.getLogger(__name__)

class EffectSelect(Select):
    def __init__(self, effects: List[Tuple[str, str]]):
        options = [
            SelectOption(
                label=name,
                description=f"Remove {name} effect",
                value=name.lower()
            ) for name, _ in effects
        ]
        super().__init__(
            placeholder="Choose an effect to remove...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.selected_effect = None

    async def callback(self, interaction: Interaction):
        self.selected_effect = self.values[0]
        self.view.stop()

class EffectSelectView(View):
    def __init__(self):
        super().__init__(timeout=60.0)
        self.selected_effect = None

def find_matching_effects(search_term: str, effects: List[Any]) -> List[Tuple[str, str]]:
    """
    Find effects that match the search term using fuzzy matching.
    Returns list of (effect_name, match_score) tuples.
    """
    from difflib import SequenceMatcher

    search_term = search_term.lower()
    matches = []
    
    # Common aliases/shortcuts
    aliases = {
        'temp': ['temporary hp', 'temp hp'],
        'ac': ['ac boost', 'ac reduction'],
        'heat': ['heatwave', 'heat wave', 'phoenix pursuit'],
        'burn': ['burning', 'burn damage'],
        'frost': ['frostbite', 'freeze'],
        'vuln': ['vulnerability'],
        'res': ['resistance'],
    }
    
    # Check aliases first
    for key, alias_list in aliases.items():
        if search_term.startswith(key):
            for alias in alias_list:
                for effect in effects:
                    effect_name = getattr(effect, 'name', '').lower()
                    if alias in effect_name:
                        # Give perfect score to alias matches
                        matches.append((effect.name, 1.0))
    
    # Then do fuzzy matching on effect names
    for effect in effects:
        effect_name = getattr(effect, 'name', '').lower()
        if effect_name:
            # Get match ratio
            ratio = SequenceMatcher(None, search_term, effect_name).ratio()
            
            # Only include if it's a decent match and not already matched by alias
            if ratio > 0.4 and not any(m[0] == effect.name for m in matches):
                matches.append((effect.name, ratio))
    
    # Sort by match score (highest first)
    return sorted(matches, key=lambda x: x[1], reverse=True)

def fuzzy_match_effects(search_term: str, effects: List[Any]) -> List[Tuple[str, float]]:
    """Find effects with names similar to search_term"""
    from difflib import SequenceMatcher
    
    search_term = search_term.lower()
    matches = []
    
    for effect in effects:
        if hasattr(effect, 'name'):
            name = effect.name.lower()
            ratio = SequenceMatcher(None, search_term, name).ratio()
            if ratio > 0.5:  # Only decent matches
                matches.append((effect.name, ratio))
    
    return sorted(matches, key=lambda x: x[1], reverse=True)

class EffectCommands(commands.GroupCog, name="effect"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

        # Initialize own initiative tracker for testing
        from modules.combat.initiative import InitiativeTracker, CombatState, CombatLog
        from modules.combat.logger import CombatLogger
        from modules.combat.save_handler import SaveHandler
        
        print("Creating test initiative tracker...")
        self.tracker = InitiativeTracker(bot)
        self.tracker.state = CombatState.INACTIVE
        self.tracker.turn_order = []
        self.tracker.current_index = 0
        self.tracker.round_number = 0
        self.tracker.combat_log = CombatLog()
        
        # Store on bot for other commands to access
        self.bot.initiative_tracker = self.tracker
        
    ## General effect managing commands ##

    @app_commands.command(name="drain")
    @app_commands.describe(
        character="Character to drain resources from",
        resource_type="Type of resource to drain (HP/MP)",
        amount="Amount to drain (can use dice notation)",
        siphon_target="Character to receive the drained resources (optional)",
        duration="Duration in turns (optional)",
        reason="Reason for the drain (optional)"
    )
    @app_commands.choices(
        resource_type=[
            app_commands.Choice(name="Hit Points (HP)", value="hp"),
            app_commands.Choice(name="Mana Points (MP)", value="mp")
        ]
    )
    async def drain_effect(
        self,
        interaction: discord.Interaction,
        character: str,
        resource_type: app_commands.Choice[str],
        amount: str,
        siphon_target: Optional[str] = None,
        duration: Optional[int] = None,
        reason: Optional[str] = None
    ):
        """Apply a resource drain effect that can optionally siphon to another character"""
        try:
            await interaction.response.defer()

            # Get target character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(
                    f"Character '{character}' not found.",
                    ephemeral=True
                )
                return

            # Validate siphon target if provided
            target = None
            if siphon_target:
                target = self.bot.game_state.get_character(siphon_target)
                if not target:
                    await interaction.followup.send(
                        f"Siphon target '{siphon_target}' not found.",
                        ephemeral=True
                    )
                    return

            # Get combat logger if in combat
            combat_logger = None
            if hasattr(self.bot, 'initiative_tracker'):
                combat_logger = self.bot.initiative_tracker.logger

            if combat_logger:
                combat_logger.snapshot_character_state(char)
                if target:
                    combat_logger.snapshot_character_state(target)

            # Create drain effect
            effect = DrainEffect(
                amount=amount,
                resource_type=resource_type.value,
                siphon_target=siphon_target,
                duration=duration,
                game_state=self.bot.game_state  # Pass game_state to effect
            )

            # Get current round if in combat
            round_number = 1
            if combat_logger:
                round_number = getattr(self.bot.initiative_tracker, 'round_number', 1)

            # Apply effect - with proper await
            message = await apply_effect(
                char,
                effect,
                round_number,
                combat_logger
            )

            # Create response embed
            embed = discord.Embed(
                description=message,
                color=discord.Color.purple() if siphon_target else discord.Color.red()
            )
            
            if reason:
                embed.set_footer(text=f"Reason: {reason}")

            await interaction.followup.send(embed=embed)

            # Save affected characters
            await self.bot.db.save_character(char)
            if target:
                await self.bot.db.save_character(target)

            # Log command usage
            if combat_logger:
                combat_logger.log_command(
                    "drain",
                    interaction.user,
                    {
                        "character": character,
                        "resource_type": resource_type.value,
                        "amount": amount,
                        "siphon_target": siphon_target,
                        "duration": duration,
                        "reason": reason
                    }
                )

        except Exception as e:
            logger.error(f"Error in drain effect: {str(e)}", exc_info=True)
            await handle_error(interaction, e)

    @app_commands.command(name="condition")
    @app_commands.describe(
        target="The character to affect",
        conditions="Comma-separated list of conditions (prone, blinded, etc)",
        duration="How many rounds the conditions last (optional)"
    )
    async def condition_command(
        self,
        interaction: discord.Interaction,
        target: str,
        conditions: str,
        duration: Optional[int] = None
    ):
        """Apply conditions to a character"""
        await interaction.response.defer()
        
        try:
            # Get target character
            character = self.bot.game_state.get_character(target)
            if not character:
                await interaction.followup.send(
                    f"Character '{target}' not found.",
                    ephemeral=True
                )
                return

            # Parse condition list
            condition_names = [c.strip().lower() for c in conditions.split(",")]
            valid_conditions = []
            invalid_conditions = []
            
            for name in condition_names:
                try:
                    condition = ConditionType(name)
                    valid_conditions.append(condition)
                except ValueError:
                    invalid_conditions.append(name)
            
            if invalid_conditions:
                # Create embed showing valid options
                embed = discord.Embed(
                    title="Invalid Conditions",
                    description=f"The following conditions were invalid: {', '.join(invalid_conditions)}",
                    color=discord.Color.red()
                )
                
                # Group conditions by category for cleaner display
                categories = {
                    "Movement": ["prone", "grappled", "restrained", "airborne", "slowed"],
                    "Combat": ["blinded", "deafened", "marked", "guarded", "flanked"],
                    "Control": ["incapacitated", "paralyzed", "charmed", "frightened", "confused"],
                    "Situational": ["hidden", "invisible", "underwater", "concentrating", "surprised"],
                    "State": ["bleeding", "poisoned", "silenced", "exhausted"]
                }
                
                for category, conds in categories.items():
                    embed.add_field(
                        name=category,
                        value=", ".join(conds),
                        inline=False
                    )
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
                
            if not valid_conditions:
                await interaction.followup.send(
                    "Please specify at least one valid condition.",
                    ephemeral=True
                )
                return
            
            # Create and apply the condition effect
            effect = ConditionEffect(
                conditions=valid_conditions,
                duration=duration,
                source=interaction.user.display_name
            )
            
            # Get current round number from combat state if in combat
            round_number = 1
            if hasattr(self.bot, 'initiative_tracker') and \
               self.bot.initiative_tracker.state == CombatState.ACTIVE:
                round_number = self.bot.initiative_tracker.round_number
            
            # Apply effect - with proper await
            result = await apply_effect(character, effect, round_number)
            
            # Create response embed
            embed = discord.Embed(
                title="Condition Applied",
                description=result,
                color=discord.Color.blue()
            )
            
            # Add effect details
            details = []
            for condition in valid_conditions:
                if props := CONDITION_PROPERTIES.get(condition):
                    effects = props.get("turn_effects", [])
                    if effects:
                        details.extend(effects)
            
            if details:
                embed.add_field(
                    name="Effects",
                    value="\n".join(details),
                    inline=False
                )
            
            if duration:
                embed.add_field(
                    name="Duration",
                    value=f"Lasts for {duration} {'turn' if duration == 1 else 'turns'}",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
            # Save character changes
            await self.bot.db.save_character(character)
            
        except Exception as e:
            await interaction.followup.send(
                f"Error applying conditions: {str(e)}",
                ephemeral=True
            )

    @condition_command.autocomplete('conditions')
    async def condition_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> List[app_commands.Choice[str]]:
        """Provide autocomplete for condition names"""
        conditions = [c.value for c in ConditionType]
        
        # If user has started typing, filter conditions
        if current:
            conditions = [c for c in conditions if current.lower() in c.lower()]
            
        # Return up to 25 choices
        return [
            app_commands.Choice(name=cond, value=cond)
            for cond in sorted(conditions)[:25]
        ]

    @app_commands.command(name="remove")
    @app_commands.describe(
        character="The character to remove the effect from",
        effect_name="Name of the effect to remove (burn, ac, heat, pursuit, etc) or 'all'"
    )
    async def remove(
        self,
        interaction: discord.Interaction,
        character: str,
        effect_name: str
    ):
        """Remove an effect from a character"""
        await interaction.response.defer()
        
        char = self.bot.game_state.get_character(character)
        if not char:
            await interaction.followup.send(f"❌ `Character {character} not found` ❌")
            return

        # Handle "remove all" case
        if effect_name.lower() == "all":
            # Process cleanup for each effect
            for effect in char.effects[:]:  # Copy list since we're modifying it
                # Handle async/sync for on_expire
                if hasattr(effect.on_expire, '__await__'):
                    await effect.on_expire(char)
                else:
                    effect.on_expire(char)
            
            # Clear all effects
            char.effects = []
            
            # Reset temporary HP
            char.resources.current_temp_hp = 0
            char.resources.max_temp_hp = 0
            
            # Reset AC to base value
            char.defense.current_ac = char.defense.base_ac
            
            # Clear effect-based resistances/vulnerabilities
            char.defense.damage_resistances = {}
            char.defense.damage_vulnerabilities = {}
            
            await self.bot.db.save_character(char)
            await interaction.followup.send(f"✨ `Removed all effects from {character}` ✨")
            return

        # Handle heat/pursuit removal (removes both source and target effects)
        if effect_name.lower() in ['heat', 'heatwave', 'pursuit', 'phoenix pursuit']:
            messages = []
            
            # Find all heat-related effects
            for effect in char.effects[:]:  # Copy list since we're modifying it
                if isinstance(effect, (SourceHeatWaveEffect, TargetHeatWaveEffect)):
                    # Handle async/sync for on_expire
                    if hasattr(effect.on_expire, '__await__'):
                        expire_msg = await effect.on_expire(char)
                    else:
                        expire_msg = effect.on_expire(char)
                    
                    if expire_msg:
                        messages.append(expire_msg)
                    char.effects.remove(effect)

            if not messages:
                await interaction.followup.send(f"❌ `No heat-related effects found on {character}` ❌")
                return

            await self.bot.db.save_character(char)
            await interaction.followup.send("\n".join(messages))
            return

        # Handle AC effect removal with selection for multiple effects
        if effect_name.lower() in ['ac', 'armor class']:
            standalone_ac_effects = [
                e for e in char.effects 
                if isinstance(e, ACEffect) and not any(
                    isinstance(parent, (TargetHeatWaveEffect, FrostbiteEffect)) 
                    for parent in char.effects if hasattr(parent, 'ac_effect') 
                    and parent.ac_effect == e
                )
            ]
            
            if not standalone_ac_effects:
                await interaction.followup.send(f"❌ `No removable AC effects found on {character}` ❌")
                return
                
            if len(standalone_ac_effects) == 1:
                effect = standalone_ac_effects[0]
                # Handle async/sync for on_expire
                if hasattr(effect.on_expire, '__await__'):
                    message = await effect.on_expire(char)
                else:
                    message = effect.on_expire(char)
                char.effects.remove(effect)
                await self.bot.db.save_character(char)
                await interaction.followup.send(message)
                return
            
            # Create selection menu for multiple effects
            options = []
            for i, effect in enumerate(standalone_ac_effects):
                sign = '+' if effect.amount > 0 else ''
                options.append(
                    SelectOption(
                        label=f"AC Change: {sign}{effect.amount}",
                        description=f"{'Permanent' if effect.permanent else f'Duration: {effect.duration}'}" if hasattr(effect, 'duration') else 'No duration',
                        value=str(i)
                    )
                )
                
            select = Select(
                placeholder="Choose an AC effect to remove...",
                options=options,
                min_values=1,
                max_values=1
            )
            
            async def select_callback(interaction: discord.Interaction):
                effect = standalone_ac_effects[int(select.values[0])]
                # Handle async/sync for on_expire
                if hasattr(effect.on_expire, '__await__'):
                    message = await effect.on_expire(char)
                else:
                    message = effect.on_expire(char)
                char.effects.remove(effect)
                await self.bot.db.save_character(char)
                await interaction.response.send_message(message)
                view.stop()
                
            select.callback = select_callback
            view = View()
            view.add_item(select)
            
            await interaction.followup.send(
                f"Multiple AC effects found on {character}. Please select one to remove:",
                view=view,
                ephemeral=True
            )
            return

        # Use fuzzy matching to find effects
        matches = fuzzy_match_effects(effect_name, char.effects)
        
        if not matches:
            await interaction.followup.send(f"❌ `No matching effects found on {character}` ❌")
            return
        
        # If there's exactly one good match, remove it
        if len(matches) == 1 or matches[0][1] > 0.8:  # Perfect or very good match
            effect_name = matches[0][0]
            effect = next(e for e in char.effects if e.name == effect_name)
            # Handle async/sync for on_expire
            if hasattr(effect.on_expire, '__await__'):
                message = await effect.on_expire(char)
            else:
                message = effect.on_expire(char)
            char.effects.remove(effect)
            await self.bot.db.save_character(char)
            await interaction.followup.send(message)
            return
        
        # If there are multiple potential matches, show selection menu
        options = []
        for name, score in matches[:25]:  # Limit to 25 choices (Discord max)
            effect = next(e for e in char.effects if e.name == name)
            desc = []
            if hasattr(effect, 'duration'):
                desc.append("Duration: " + (str(effect.duration) + " turns" if effect.duration else "Permanent"))
            if hasattr(effect, 'amount'):
                desc.append(f"Amount: {effect.amount}")
            
            options.append(
                SelectOption(
                    label=name,
                    description=" | ".join(desc) if desc else None,
                    value=name
                )
            )
        
        select = Select(
            placeholder="Choose an effect to remove...",
            options=options,
            min_values=1,
            max_values=1
        )
        
        async def select_callback(interaction: discord.Interaction):
            effect = next(e for e in char.effects if e.name == select.values[0])
            # Handle async/sync for on_expire
            if hasattr(effect.on_expire, '__await__'):
                message = await effect.on_expire(char)
            else:
                message = effect.on_expire(char)
            char.effects.remove(effect)
            await self.bot.db.save_character(char)
            await interaction.response.send_message(message)
            view.stop()
            
        select.callback = select_callback
        view = View()
        view.add_item(select)
        
        await interaction.followup.send(
            f"Multiple matching effects found on {character}. Please select one to remove:",
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="list")
    @app_commands.describe(
        character="The character to list effects for"
    )
    async def list_effects(
        self,
        interaction: discord.Interaction,
        character: str
    ):
        """List all active effects on a character"""
        await interaction.response.send_message("Fetching effects...", ephemeral=True)
        print(f"Command used: /effect list {character}")

        char = self.bot.game_state.get_character(character)
        if not char:
            await interaction.channel.send(f"❌ `Character {character} not found` ❌")
            return

        summary = get_effect_summary(char)
        
        embed = discord.Embed(
            title=f"{char.name}'s Active Effects",
            description="\n".join(summary),
            color=discord.Color.blue()
        )

        await interaction.channel.send(embed=embed)
        await interaction.delete_original_response()

    ## Combat & Status Effects ##

    @app_commands.command(name="ac")
    @app_commands.describe(
        character="Character to modify",
        amount="Amount to modify AC by (positive or negative)",
        duration="Duration in turns (optional)",
        permanent="Whether this effect is permanent"
    )
    async def ac_effect(
        self,
        interaction: discord.Interaction,
        character: str,
        amount: int,
        duration: Optional[int] = None,
        permanent: bool = False
    ):
        """Apply an AC modification effect"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            effect = ACEffect(amount, duration, permanent)
            # Apply effect - with proper await
            message = await apply_effect(char, effect)

            await self.bot.db.save_character(char)
            
            duration_str = " permanently" if permanent else f" for {duration} turns" if duration else ""
            current_ac = char.defense.current_ac
            
            if amount > 0:
                await interaction.followup.send(
                    f"🛡️ `Reinforced {character}'s defenses by +{amount}{duration_str}! (AC now {current_ac})` 🛡️"
                )
            else:
                await interaction.followup.send(
                    f"🛡️ `Weakened {character}'s defenses by {amount}{duration_str}! (AC now {current_ac})` 🛡️"
                )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="resistance")
    @app_commands.describe(
        character="Character to receive resistance",
        damage_type="Type of damage to resist",
        percentage="Resistance percentage (default: 50)",
        duration="Duration in turns (optional)"
    )
    async def resistance(
        self,
        interaction: discord.Interaction,
        character: str,
        damage_type: str,
        percentage: Optional[int] = 50,
        duration: Optional[int] = None
    ):
        """Add damage resistance to a character"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            effect = ResistanceEffect(damage_type, percentage, duration)
            # Apply effect - with proper await
            message = await apply_effect(char, effect)

            await self.bot.db.save_character(char)
            
            await interaction.followup.send(
                f"🛡️ `Added {percentage}% {damage_type} resistance to {character}"
                f"{f' for {duration} turns' if duration else ''}` 🛡️"
            )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="vulnerability")
    @app_commands.describe(
        character="Character to receive vulnerability",
        damage_type="Type of damage to be vulnerable to",
        percentage="Vulnerability percentage (default: 50)",
        duration="Duration in turns (optional)"
    )
    async def vulnerability(
        self,
        interaction: discord.Interaction,
        character: str,
        damage_type: str,
        percentage: Optional[int] = 50,
        duration: Optional[int] = None
    ):
        """Add damage vulnerability to a character"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            effect = VulnerabilityEffect(damage_type, percentage, duration)
            # Apply effect - with proper await
            message = await apply_effect(char, effect)

            await self.bot.db.save_character(char)
            
            await interaction.followup.send(
                f"⚔️ `Added {percentage}% {damage_type} vulnerability to {character}"
                f"{f' for {duration} turns' if duration else ''}` ⚔️"
            )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="weakness")
    @app_commands.describe(
        character="Character to receive weakness",
        damage_type="Type of damage to be weak with",
        percentage="Weakness percentage (default: 50)",
        duration="Duration in turns (optional)"
    )
    async def weakness(
        self,
        interaction: discord.Interaction,
        character: str,
        damage_type: str,
        percentage: Optional[int] = 50,
        duration: Optional[int] = None
    ):
        """Add damage weakness to a character"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            effect = WeaknessEffect(damage_type, percentage, duration)
            # Apply effect - with proper await
            message = await apply_effect(char, effect)

            await self.bot.db.save_character(char)
            
            await interaction.followup.send(
                f"💔 `Added {percentage}% weakness with {damage_type} damage to {character}"
                f"{f' for {duration} turns' if duration else ''}` 💔"
            )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="burn")
    @app_commands.describe(
        character="Character to apply burn to",
        damage="Amount of damage per turn (can use dice notation)",
        duration="Duration in turns (optional)"
    )
    async def burn(
        self,
        interaction: discord.Interaction,
        character: str,
        damage: str,
        duration: Optional[int] = None
    ):
        """Apply a burning effect that deals damage each turn"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            # Get current round from initiative tracker
            initiative_cog = self.bot.get_cog('InitiativeCommands')
            current_round = initiative_cog.tracker.round_number if initiative_cog else 1

            effect = BurnEffect(damage, duration)
            # Apply effect - with proper await
            message = await apply_effect(char, effect, current_round)

            await self.bot.db.save_character(char)
            await interaction.followup.send(message)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="frostbite")
    @app_commands.describe(
        character="The character to apply frostbite to",
        stacks="Number of frostbite stacks to add"
    )
    async def frostbite(
        self,
        interaction: discord.Interaction,
        character: str,
        stacks: int = 1
    ):
        """Apply frostbite stacks to a character"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            effect = FrostbiteEffect(stacks)
            # Apply effect - with proper await
            message = await apply_effect(char, effect)

            await self.bot.db.save_character(char)
            await interaction.followup.send(message)
            
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="custom")
    @app_commands.describe(
        character="Character to apply effect to",
        name="Name of the custom effect",
        description="Effect description (use * for bullet points)",
        duration="Duration in turns (optional)",
        permanent="Whether this effect is permanent"
    )
    async def custom(
        self,
        interaction: discord.Interaction,
        character: str,
        name: str,
        description: str,
        duration: Optional[int] = None,
        permanent: bool = False
    ):
        """Apply a custom effect with optional bullet points"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            effect = CustomEffect(name, duration, description, permanent=permanent)
            # Apply effect - with proper await
            message = await apply_effect(char, effect)

            await self.bot.db.save_character(char)
            
            duration_str = "permanently" if permanent else f"for {duration} turns"
            await interaction.followup.send(f"✨ `{name} applied to {character} {duration_str}` ✨")

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="heatwave")
    @app_commands.describe(
        source="Character using Heat Wave",
        target="Character being affected",
        stacks="Number of Heat stacks to add"
    )
    async def heatwave(
        self,
        interaction: discord.Interaction,
        source: str,
        target: str,
        stacks: int = 1
    ):
        """Apply Heat Wave effect between characters"""
        try:
            await interaction.response.defer()

            source_char = self.bot.game_state.get_character(source)
            target_char = self.bot.game_state.get_character(target)

            if not source_char or not target_char:
                await interaction.followup.send("❌ `One or both characters not found` ❌")
                return

            # Get or create source effect to track attunement
            source_effect = next(
                (e for e in source_char.effects if isinstance(e, SourceHeatWaveEffect)),
                SourceHeatWaveEffect()
            )
            
            # Create and apply target effect
            target_effect = TargetHeatWaveEffect(source, stacks)
            
            # Update source's attunement
            source_msg = source_effect.add_stacks(stacks, source_char)
            if not any(isinstance(e, SourceHeatWaveEffect) for e in source_char.effects):
                source_char.effects.append(source_effect)
                
            # Apply target effect - with proper await
            target_msg = await apply_effect(target_char, target_effect)

            await self.bot.db.save_character(source_char)
            await self.bot.db.save_character(target_char)
            
            # Send appropriate feedback based on state
            if source_effect.activated:
                if stacks >= 3:
                    await interaction.followup.send(
                        f"🔥 `{source}'s Phoenix Pursuit active → {target} afflicted by Heat {stacks}/3 (Vulnerable)` 🔥"
                    )
                else:
                    await interaction.followup.send(
                        f"🔥 `{source}'s Phoenix Pursuit active → {target} afflicted by Heat {stacks}/3` 🔥"
                    )
            else:
                total_stacks = getattr(source_effect, 'stacks', 0)
                if stacks >= 3:
                    await interaction.followup.send(
                        f"🔥 `{source}'s attunement at {total_stacks}/3 → {target} afflicted by Heat {stacks}/3 (Vulnerable)` 🔥"
                    )
                else:
                    await interaction.followup.send(
                        f"🔥 `{source}'s attunement at {total_stacks}/3 → {target} afflicted by Heat {stacks}/3` 🔥"
                    )
            
        except Exception as e:
            logger.error(f"Error in heatwave command: {str(e)}", exc_info=True)
            await handle_error(interaction, e)

    @app_commands.command(name="natural_resistance")
    @app_commands.describe(
        character="Character to modify",
        damage_type="Type of damage to add resistance to",
        percentage="Resistance percentage",
        remove="Remove this natural resistance instead of adding it"
    )
    async def natural_resistance(
        self,
        interaction: discord.Interaction,
        character: str,
        damage_type: str,
        percentage: int = 50,
        remove: bool = False
    ):
        """Add or remove natural damage resistance"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            if remove:
                if damage_type in char.defense.natural_resistances:
                    del char.defense.natural_resistances[damage_type]
                    await self.bot.db.save_character(char)
                    await interaction.followup.send(
                        f"🛡️ `Removed natural {damage_type} resistance from {character}` 🛡️"
                    )
                else:
                    await interaction.followup.send(
                        f"❌ `{character} doesn't have natural {damage_type} resistance` ❌"
                    )
            else:
                char.defense.natural_resistances[damage_type] = percentage
                await self.bot.db.save_character(char)
                await interaction.followup.send(
                    f"🛡️ `Added {percentage}% natural {damage_type} resistance to {character}` 🛡️"
                )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="natural_vulnerability")
    @app_commands.describe(
        character="Character to modify",
        damage_type="Type of damage to add vulnerability to",
        percentage="Vulnerability percentage",
        remove="Remove this natural vulnerability instead of adding it"
    )
    async def natural_vulnerability(
        self,
        interaction: discord.Interaction,
        character: str,
        damage_type: str,
        percentage: int = 50,
        remove: bool = False
    ):
        """Add or remove natural damage vulnerability"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            if remove:
                if damage_type in char.defense.natural_vulnerabilities:
                    del char.defense.natural_vulnerabilities[damage_type]
                    await self.bot.db.save_character(char)
                    await interaction.followup.send(
                        f"⚔️ `Removed natural {damage_type} vulnerability from {character}` ⚔️"
                    )
                else:
                    await interaction.followup.send(
                        f"❌ `{character} doesn't have natural {damage_type} vulnerability` ❌"
                    )
            else:
                char.defense.natural_vulnerabilities[damage_type] = percentage
                await self.bot.db.save_character(char)
                await interaction.followup.send(
                    f"⚔️ `Added {percentage}% natural {damage_type} vulnerability to {character}` ⚔️"
                )

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="skip")
    @app_commands.describe(
        character="Character to affect",
        duration="How many turns to skip (default: 1)",
        reason="Optional reason for skipping"
    )
    async def skip(
        self,
        interaction: discord.Interaction,
        character: str,
        duration: Optional[int] = 1,
        reason: Optional[str] = None
    ) -> None:
        """Apply skip effect to a character"""
        await interaction.response.defer()
        
        try:
            # Get character
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(
                    f"Character '{character}' not found.",
                    ephemeral=True
                )
                return
                
            # Create and apply skip effect
            effect = SkipEffect(duration=duration, reason=reason)
            # Apply effect - with proper await
            message = await apply_effect(char, effect)
            
            # Save character
            await self.bot.db.save_character(char)
            
            await interaction.followup.send(message)
            
        except Exception as e:
            logger.error(f"Error in skip effect command: {e}", exc_info=True)
            await handle_error(interaction, e)

    @app_commands.command(name="debugeffects")
    @app_commands.checks.has_permissions(administrator=True)
    async def debug_effects(self, interaction: discord.Interaction):
        """Run test scenarios for effect system debugging"""
        try:
            await interaction.response.defer()
            
            print("\n=== Starting Effect System Debug ===\n")
            
            # Verify test characters exist
            test_chars = ["test", "test2", "test3", "test4"]
            chars = []
            for name in test_chars:
                char = self.bot.game_state.get_character(name)
                if not char:
                    await interaction.followup.send(
                        f"Error: Required test character '{name}' not found"
                    )
                    return
                chars.append(char)

            print("Initializing debug session...")
            self.tracker.logger = CombatLogger(interaction.channel_id)
            
            # Enable quiet mode for cleaner output
            print("Setting quiet mode...")
            self.tracker.set_quiet_mode(True)
            
            print("Setting up test combat...")
            success, message = await self.tracker.set_battle(
                [char.name for char in chars],
                interaction
            )
            if not success:
                await interaction.followup.send(f"Error: {message}")
                return

            # Run test phases
            await self._test_basic_effects(chars, interaction)
            await asyncio.sleep(1)  # Brief pause between phases
            await self._test_move_phases(chars, interaction)
            await asyncio.sleep(1)
            await self._test_stacking_effects(chars, interaction)
            await asyncio.sleep(1)
            await self._test_cleanup(chars, interaction)

            print("\n=== Effect System Debug Complete ===")
            
            # Disable quiet mode before ending
            self.tracker.set_quiet_mode(False)
            
            # End combat
            self.tracker.end_combat()
            await interaction.followup.send("Effect debug complete - check console for results")
            
        except Exception as e:
            print(f"Error in debug command: {e}")
            # Make sure to disable quiet mode even on error
            if hasattr(self, 'tracker'):
                self.tracker.set_quiet_mode(False)
            await interaction.followup.send(f"Error in debug command: {str(e)}")
            return

    async def _test_basic_effects(self, chars: List['Character'], interaction: discord.Interaction):
        """Test basic effect application and duration"""
        print("\n=== Phase 1: Basic Effects ===")
        
        # Test 1: AC Effect
        print("\nTest 1a: Basic AC Effect")
        char = chars[0]
        print(f"Applying -2 AC effect to {char.name} for 2 turns")
        print(f"Initial AC: {char.defense.current_ac}")
        
        effect = ACEffect(amount=-2, duration=2)
        msg = await apply_effect(char, effect, self.tracker.round_number)
        print(f"Apply message: {msg}")
        print(f"New AC: {char.defense.current_ac}")
        print("Expected: AC should decrease by 2 and last 2 turns")
        
        # Test 1b: Burn Effect
        print("\nTest 1b: Burn Effect with Dice")
        char = chars[1]
        print(f"Applying 1d6 burn to {char.name} for 3 turns")
        print(f"Initial HP: {char.resources.current_hp}")
        
        effect = BurnEffect("1d6", duration=3)
        msg = await apply_effect(char, effect, self.tracker.round_number)
        print(f"Apply message: {msg}")
        print("Expected: Should roll 1d6 damage at start of each turn for 3 turns")

        # Test 1c: Drain Effect
        print("\nTest 1c: MP Drain with Siphon")
        source = chars[2]
        target = chars[3]
        print(f"Draining 5 MP from {target.name} to {source.name}")
        print(f"Source MP: {source.resources.current_mp}")
        print(f"Target MP: {target.resources.current_mp}")
        
        effect = DrainEffect(5, "mp", source.name, duration=2)
        msg = await apply_effect(target, effect, self.tracker.round_number)
        print(f"Apply message: {msg}")
        print("Expected: 5 MP should transfer each turn for 2 turns")

        await self.bot.db.save_character(chars[0])
        await self.bot.db.save_character(chars[1])
        await self.bot.db.save_character(chars[2])
        await self.bot.db.save_character(chars[3])

    async def _test_move_phases(self, chars: List['Character'], interaction: discord.Interaction):
        """Test move effect phases and transitions"""
        print("\n=== Phase 2: Move Effects ===")
        
        # Test 2a: Cast Time Move
        print("\nTest 2a: Move with Cast Time")
        char = chars[0]
        move_effect = MoveEffect(
            name="Flame Ritual",
            description="A powerful flame attack",
            cast_time=1,
            duration=2,
            cooldown=1,
            mp_cost=10,
            star_cost=2
        )
        
        print(f"Applying cast time move to {char.name}")
        print("Parameters:")
        print(f"  Cast Time: 1 turn")
        print(f"  Duration: 2 turns")
        print(f"  Cooldown: 1 turn")
        print(f"Initial state: {move_effect.state}")
        
        msg = await apply_effect(char, move_effect, self.tracker.round_number)
        print(f"Apply message: {msg}")
        print("Expected phases:")
        print("1. Cast Time (1 turn)")
        print("2. Active Effect (2 turns)")
        print("3. Cooldown (1 turn)")
        print("4. Complete")
        await self.bot.db.save_character(char)

    async def _test_stacking_effects(self, chars: List['Character'], interaction: discord.Interaction):
        """Test effects that stack or interact"""
        print("\n=== Phase 3: Stacking Effects ===")
        
        # Test 3a: Heat Wave
        print("\nTest 3a: Heat Wave Stacks")
        source = chars[0]
        target = chars[1]
        
        print(f"Applying Heat Wave from {source.name} to {target.name}")
        print("Initial states:")
        print(f"Source heat stacks: {getattr(source, 'heat_stacks', 0)}")
        print(f"Target heat stacks: {getattr(target, 'heat_stacks', 0)}")
        print(f"Target AC: {target.defense.current_ac}")
        
        # Apply first stack
        source_effect = SourceHeatWaveEffect()
        target_effect = TargetHeatWaveEffect(source.name, 1)
        
        source_msg = source_effect.add_stacks(1, source)
        target_msg = await apply_effect(target, target_effect)
        
        print("\nAfter 1 stack:")
        print(f"Source message: {source_msg}")
        print(f"Target message: {target_msg}")
        print(f"Target AC: {target.defense.current_ac}")
        
        await self.bot.db.save_character(source)
        await self.bot.db.save_character(target)

    async def _test_cleanup(self, chars: List['Character'], interaction: discord.Interaction):
        """Test effect cleanup and expiry"""
        print("\n=== Phase 4: Effect Cleanup ===")
        
        # Process turns to see cleanup
        for i in range(6):  # Run 6 turns to see full effect lifecycles
            print(f"\nProcessing turn {i+1}")
            success, message, effect_msgs = await self.tracker.next_turn(interaction)
            
            current_char = self.bot.game_state.get_character(
                self.tracker.current_turn.character_name
            )
            
            print(f"\nCharacter: {current_char.name}")
            print("Active effects:")
            for effect in current_char.effects:
                print(f"  {effect.name}")
                if hasattr(effect, 'timing'):
                    print(f"    Start round: {effect.timing.start_round}")
                    print(f"    Duration: {effect.timing.duration}")
                if hasattr(effect, 'state'):
                    print(f"    State: {effect.state}")
            
            if effect_msgs:
                print("\nEffect Messages:")
                for msg in effect_msgs:
                    print(f"  {msg}")
            
            await asyncio.sleep(1)  # Brief delay between turns
            
        print("\n=== Cleaning Up Test Effects ===")
        
        # Clean up all effects from test characters
        for char in chars:
            print(f"\nCleaning up {char.name}'s effects:")
            
            # Get effect counts before cleanup
            effect_count = len(char.effects)
            print(f"Found {effect_count} effects to remove")
            
            # Process cleanup for each effect
            for effect in char.effects[:]:  # Copy list since we're modifying it
                print(f"  Removing {effect.name}")
                # Handle async/sync for on_expire
                if hasattr(effect.on_expire, '__await__'):
                    await effect.on_expire(char)
                else:
                    effect.on_expire(char)
                    
            # Clear all effects
            char.effects = []
            
            # Reset any modified stats/resources
            char.resources.current_temp_hp = 0
            char.resources.max_temp_hp = 0
            char.defense.current_ac = char.defense.base_ac
            char.defense.damage_resistances = {}
            char.defense.damage_vulnerabilities = {}
            
            # Clear any resource modifications
            if hasattr(char, 'heat_stacks'):
                delattr(char, 'heat_stacks')
            
            # Save cleaned character
            await self.bot.db.save_character(char)
            print(f"  Cleanup complete - saved to database")
            
        print("\nDebug cleanup complete - all test effects removed")
            
    @app_commands.command(name="shock")
    @app_commands.describe(
        character="Character to apply shock to",
        damage="Amount of damage per shock (can use dice notation)",
        chance="Chance to trigger shock effect (default: 50%)",
        duration="Duration in turns (optional, defaults to 1)",
        permanent="Whether this effect is permanent"
    )
    async def shock(
        self,
        interaction: discord.Interaction,
        character: str,
        damage: str,
        chance: Optional[int] = 50,
        duration: Optional[int] = 1,
        permanent: bool = False
    ):
        """Apply a shock effect that has a chance to damage and stun"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            # Get current round from initiative tracker
            current_round = 1
            if hasattr(self.bot, 'initiative_tracker'):
                current_round = getattr(self.bot.initiative_tracker, 'round_number', 1)

            effect = ShockEffect(damage, chance, duration, permanent)
            # Apply effect - with proper await
            message = await apply_effect(char, effect, current_round)

            await self.bot.db.save_character(char)
            await interaction.followup.send(message)

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="regen")
    @app_commands.describe(
        character="Character to apply regeneration to",
        resource_type="Type of resource to regenerate (HP/MP)",
        amount="Amount to regenerate per turn (can use dice notation)",
        duration="Duration in turns (optional, defaults to 1)",
        permanent="Whether this effect is permanent"
    )
    @app_commands.choices(
        resource_type=[
            app_commands.Choice(name="Hit Points (HP)", value="hp"),
            app_commands.Choice(name="Mana Points (MP)", value="mp")
        ]
    )
    async def regeneration(
        self,
        interaction: discord.Interaction,
        character: str,
        resource_type: app_commands.Choice[str],
        amount: str,
        duration: Optional[int] = 1,
        permanent: bool = False
    ):
        """Apply a regeneration effect that restores resources over time"""
        try:
            await interaction.response.defer()

            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.followup.send(f"❌ `Character {character} not found` ❌")
                return

            effect = RegenEffect(
                amount=amount,
                resource_type=resource_type.value,
                duration=duration,
                permanent=permanent
            )

            # Get current round from initiative tracker
            current_round = 1
            if hasattr(self.bot, 'initiative_tracker'):
                current_round = getattr(self.bot.initiative_tracker, 'round_number', 1)

            # Apply effect - with proper await
            message = await apply_effect(char, effect, current_round)

            await self.bot.db.save_character(char)
            await interaction.followup.send(message)

        except Exception as e:
            await handle_error(interaction, e)

async def setup(bot):
    await bot.add_cog(EffectCommands(bot))