"""
Skill Check Command (src/commands/skillcheck.py)

Handles all types of character checks (ability checks, saving throws, and skill checks).
Supports both DC-based and contested checks with optional advantage/disadvantage.
"""

import discord
from discord import app_commands
from discord.ext import commands
from enum import Enum
from typing import Optional, Dict, Any, List
import logging

from core.character import Character, StatType
from utils.advanced_dice.parser import DiceParser
from utils.advanced_dice.calculator import DiceCalculator
from utils.error_handler import ErrorTranslator

logger = logging.getLogger(__name__)

class CheckType(Enum):
    """Types of character checks"""
    SAVE = "save"           # Saving throws
    ABILITY = "ability"     # Raw ability checks
    SKILL = "skill"         # Skill checks

# Add choice definitions
ABILITY_CHOICES = [
    app_commands.Choice(name="Strength (STR)", value="strength"),
    app_commands.Choice(name="Dexterity (DEX)", value="dexterity"),
    app_commands.Choice(name="Constitution (CON)", value="constitution"),
    app_commands.Choice(name="Intelligence (INT)", value="intelligence"),
    app_commands.Choice(name="Wisdom (WIS)", value="wisdom"),
    app_commands.Choice(name="Charisma (CHA)", value="charisma")
]

SKILL_CHOICES = [
    # Strength
    app_commands.Choice(name="Athletics (STR)", value="athletics"),
    # Dexterity
    app_commands.Choice(name="Acrobatics (DEX)", value="acrobatics"),
    app_commands.Choice(name="Sleight of Hand (DEX)", value="sleight_of_hand"),
    app_commands.Choice(name="Stealth (DEX)", value="stealth"),
    # Intelligence
    app_commands.Choice(name="Arcana (INT)", value="arcana"),
    app_commands.Choice(name="History (INT)", value="history"),
    app_commands.Choice(name="Investigation (INT)", value="investigation"),
    app_commands.Choice(name="Nature (INT)", value="nature"),
    app_commands.Choice(name="Religion (INT)", value="religion"),
    # Wisdom
    app_commands.Choice(name="Animal Handling (WIS)", value="animal_handling"),
    app_commands.Choice(name="Insight (WIS)", value="insight"),
    app_commands.Choice(name="Medicine (WIS)", value="medicine"),
    app_commands.Choice(name="Mysticism (WIS)", value="mysticism"),
    app_commands.Choice(name="Perception (WIS)", value="perception"),
    app_commands.Choice(name="Survival (WIS)", value="survival"),
    # Charisma
    app_commands.Choice(name="Deception (CHA)", value="deception"),
    app_commands.Choice(name="Intimidation (CHA)", value="intimidation"),
    app_commands.Choice(name="Performance (CHA)", value="performance"),
    app_commands.Choice(name="Persuasion (CHA)", value="persuasion")
]

# Mapping of skills to their ability scores
SKILL_ABILITIES = {
    # Strength
    "athletics": StatType.STRENGTH,
    
    # Dexterity
    "acrobatics": StatType.DEXTERITY,
    "sleight_of_hand": StatType.DEXTERITY,
    "stealth": StatType.DEXTERITY,
    
    # Intelligence
    "arcana": StatType.INTELLIGENCE,
    "history": StatType.INTELLIGENCE,
    "investigation": StatType.INTELLIGENCE,
    "nature": StatType.INTELLIGENCE,
    "religion": StatType.INTELLIGENCE,
    
    # Wisdom
    "animal_handling": StatType.WISDOM,
    "insight": StatType.WISDOM,
    "medicine": StatType.WISDOM,
    "mysticism": StatType.WISDOM,
    "perception": StatType.WISDOM,
    "survival": StatType.WISDOM,
    
    # Charisma
    "deception": StatType.CHARISMA,
    "intimidation": StatType.CHARISMA,
    "performance": StatType.CHARISMA,
    "persuasion": StatType.CHARISMA
}

class Advantage(Enum):
    """Possible advantage states"""
    NORMAL = "normal"
    ADVANTAGE = "advantage"
    DISADVANTAGE = "disadvantage"

async def format_check_result(
    roll_result: int,
    character: Character,
    check_type: CheckType,
    stat_or_skill: str,
    dc: Optional[int] = None,
    advantage: bool = False,
    disadvantage: bool = False,
    reason: Optional[str] = None,
    breakdown: Optional[str] = None
) -> discord.Embed:
    """Format check result into a nice embed"""
    
    # Determine if this was a skill, save, or ability check
    if check_type == CheckType.SKILL:
        check_name = f"{stat_or_skill.capitalize()} Check"
        # Add proficiency indicator if applicable
        if character.proficiencies.skills[stat_or_skill].value > 0:
            check_name += " (Proficient)"
            if character.proficiencies.skills[stat_or_skill].value > 1:
                check_name += " (Expert)"
    elif check_type == CheckType.SAVE:
        check_name = f"{stat_or_skill.capitalize()} Save"
        if character.proficiencies.saves[StatType(stat_or_skill)].value > 0:
            check_name += " (Proficient)"
    else:
        check_name = f"{stat_or_skill.capitalize()} Check"

    # Create embed
    embed = discord.Embed(
        title=f"🎲 {character.name}'s {check_name}",
        color=discord.Color.blue()
    )

    # Add advantage/disadvantage indicator if applicable
    if advantage and not disadvantage:
        embed.add_field(
            name="Roll Type",
            value="Advantage",
            inline=True
        )
    elif disadvantage and not advantage:
        embed.add_field(
            name="Roll Type",
            value="Disadvantage",
            inline=True
        )
    elif advantage and disadvantage:
        embed.add_field(
            name="Roll Type",
            value="Normal (Advantage/Disadvantage Cancel)",
            inline=True
        )

    # Add roll breakdown if provided
    if breakdown:
        embed.add_field(
            name="Roll Details",
            value=f"`{breakdown}`",
            inline=False
        )
    else:
        embed.add_field(
            name="Result",
            value=str(roll_result),
            inline=True
        )

    # Add DC comparison if provided
    if dc is not None:
        success = roll_result >= dc
        embed.add_field(
            name="Target DC",
            value=str(dc),
            inline=True
        )
        embed.add_field(
            name="Outcome",
            value=f"{'✅ Success' if success else '❌ Failure'}",
            inline=True
        )

    # Add reason if provided
    if reason:
        embed.set_footer(text=f"Reason: {reason}")

    return embed

async def format_contested_result(
    roller: Character,
    opponent: Character,
    roller_total: int,
    opp_total: int,
    check_type: CheckType,
    stat_or_skill: str,
    reason: Optional[str] = None,
    roller_breakdown: Optional[str] = None,
    opp_breakdown: Optional[str] = None,
    advantage_str: str = ""  # Optional string for advantage states
) -> discord.Embed:
    """Format contested check result into an embed"""
    
    # Create base embed
    if check_type == CheckType.SKILL:
        check_name = f"Contested {stat_or_skill.capitalize()} Check"
    elif check_type == CheckType.SAVE:
        check_name = f"Contested {stat_or_skill.capitalize()} Save"
    else:
        check_name = f"Contested {stat_or_skill.capitalize()} Check"
        
    embed = discord.Embed(
        title=f"🎲 {check_name}",
        color=discord.Color.blue()
    )

    # Add rolls for both characters
    if roller_breakdown:
        embed.add_field(
            name=f"{roller.name}'s Roll",
            value=f"{roller_breakdown} = **{roller_total}**",  # Removed backticks
            inline=False
        )
    else:
        embed.add_field(
            name=f"{roller.name}'s Roll",
            value=str(roller_total),
            inline=True
        )

    if opp_breakdown:
        embed.add_field(
            name=f"{opponent.name}'s Roll",
            value=f"{opp_breakdown} = **{opp_total}**",  # Removed backticks
            inline=False
        )
    else:
        embed.add_field(
            name=f"{opponent.name}'s Roll",
            value=str(opp_total),
            inline=True
        )

    # Determine winner
    difference = abs(roller_total - opp_total)
    if roller_total > opp_total:
        winner = roller.name
        result = f"✅ {winner} wins by {difference}!"
    elif opp_total > roller_total:
        winner = opponent.name
        result = f"❌ {winner} wins by {difference}!"
    else:
        result = "🤝 It's a tie!"

    embed.add_field(
        name="Result",
        value=result,
        inline=False
    )

    # Add reason if provided
    if reason:
        embed.set_footer(text=f"Reason: {reason}")

    return embed

def build_roll_expression(
    character: Character,
    check_type: CheckType,
    stat_or_skill: str,
    advantage: bool = False,
    disadvantage: bool = False,
    modifier: int = 0
) -> str:
    """Build dice roll expression with appropriate modifiers"""
    
    # Start with base d20
    if advantage and not disadvantage:
        base = "2d20k1"  # Roll 2d20, keep highest (changed from kh1)
    elif disadvantage and not advantage:
        base = "2d20kl1"  # Roll 2d20, keep lowest
    else:
        base = "1d20"
    
    # Add stat modifier
    if check_type == CheckType.SKILL:
        # Get the ability score for this skill
        ability = SKILL_ABILITIES[stat_or_skill]
        base += f"+({ability.value})"  # Add ability modifier
        
        # Add proficiency if skilled
        prof_level = character.proficiencies.skills[stat_or_skill]
        if prof_level.value > 0:
            prof_bonus = character.get_proficiency_bonus(prof_level)
            if prof_bonus:
                base += f"+{prof_bonus}"
                
    elif check_type == CheckType.SAVE:
        # Add ability modifier
        ability = StatType(stat_or_skill)
        base += f"+({ability.value})"
        
        # Add proficiency if proficient in this save
        prof_level = character.proficiencies.saves[ability]
        if prof_level.value > 0:
            prof_bonus = character.get_proficiency_bonus(prof_level)
            if prof_bonus:
                base += f"+{prof_bonus}"
                
    else:  # Ability check
        # Just add ability modifier
        ability = StatType(stat_or_skill)
        base += f"+({ability.value})"
    
    # Add optional modifier
    if modifier:
        base += f"{'+' if modifier > 0 else ''}{modifier}"
    
    return base

class SkillCheck(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    skillcheck = app_commands.Group(name="skillcheck", description="Make various character checks")

    @skillcheck.command(name="save")
    @app_commands.describe(
        character="The character making the save",
        stat="Which ability score to save with",
        dc="Target DC (optional)",
        advantage="Roll with advantage",
        disadvantage="Roll with disadvantage",
        modifier="Additional modifier to add/subtract (e.g., +2 or -1)",
        reason="Reason for the save (e.g., 'Dodging fireball')"
    )
    @app_commands.choices(stat=ABILITY_CHOICES)
    async def save(
        self,
        interaction: discord.Interaction,
        character: str,
        stat: app_commands.Choice[str],
        dc: Optional[int] = None,
        advantage: bool = False,
        disadvantage: bool = False,
        modifier: Optional[int] = 0,
        reason: Optional[str] = None
    ):
        """Make a saving throw"""
        try:
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.response.send_message(
                    f"Character '{character}' not found.",
                    ephemeral=True
                )
                return

            expression = build_roll_expression(
                char, 
                CheckType.SAVE, 
                stat.value,
                advantage,
                disadvantage,
                modifier
            )
            
            total, formatted, breakdown = DiceCalculator.calculate_complex(
                expression,
                character=char,
                concise=False
            )

            embed = await format_check_result(
                total,
                char,
                CheckType.SAVE,
                stat.value,
                dc,
                advantage,
                disadvantage,
                reason,
                breakdown
            )
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error in save command: {e}", exc_info=True)
            await interaction.response.send_message(
                f"Error processing save: {ErrorTranslator.translate_error(e)}",
                ephemeral=True
            )

    @skillcheck.command(name="ability")
    @app_commands.describe(
        character="The character making the check",
        stat="Which ability score to use",
        dc="Target DC (optional)",
        advantage="Roll with advantage",
        disadvantage="Roll with disadvantage",
        modifier="Additional modifier to add/subtract (e.g., +2 or -1)",
        reason="Reason for the check (e.g., 'Breaking down door')"
    )
    @app_commands.choices(stat=ABILITY_CHOICES)
    async def ability(
        self,
        interaction: discord.Interaction,
        character: str,
        stat: app_commands.Choice[str],
        dc: Optional[int] = None,
        advantage: bool = False,
        disadvantage: bool = False,
        modifier: Optional[int] = 0,
        reason: Optional[str] = None
    ):
        """Make an ability check"""
        try:
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.response.send_message(
                    f"Character '{character}' not found.",
                    ephemeral=True
                )
                return

            expression = build_roll_expression(
                char, 
                CheckType.ABILITY, 
                stat.value,
                advantage,
                disadvantage,
                modifier
            )
            
            total, formatted, breakdown = DiceCalculator.calculate_complex(
                expression,
                character=char,
                concise=False
            )

            embed = await format_check_result(
                total,
                char,
                CheckType.ABILITY,
                stat.value,
                dc,
                advantage,
                disadvantage,
                reason,
                breakdown
            )
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error in ability command: {e}", exc_info=True)
            await interaction.response.send_message(
                f"Error processing ability check: {ErrorTranslator.translate_error(e)}",
                ephemeral=True
            )

    @skillcheck.command(name="skill")
    @app_commands.describe(
        character="The character making the check",
        skill="Which skill to use",
        dc="Target DC (optional)",
        advantage="Roll with advantage",
        disadvantage="Roll with disadvantage",
        modifier="Additional modifier to add/subtract (e.g., +2 or -1)",
        reason="Reason for the check (e.g., 'Sneaking past guard')"
    )
    @app_commands.choices(skill=SKILL_CHOICES)
    async def skill(
        self,
        interaction: discord.Interaction,
        character: str,
        skill: app_commands.Choice[str],
        dc: Optional[int] = None,
        advantage: bool = False,
        disadvantage: bool = False,
        modifier: Optional[int] = 0,
        reason: Optional[str] = None
    ):
        """Make a skill check"""
        try:
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.response.send_message(
                    f"Character '{character}' not found.",
                    ephemeral=True
                )
                return

            expression = build_roll_expression(
                char, 
                CheckType.SKILL, 
                skill.value,
                advantage,
                disadvantage,
                modifier
            )
            
            total, formatted, breakdown = DiceCalculator.calculate_complex(
                expression,
                character=char,
                concise=False
            )

            embed = await format_check_result(
                total,
                char,
                CheckType.SKILL,
                skill.value,
                dc,
                advantage,
                disadvantage,
                reason,
                breakdown
            )
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error in skill command: {e}", exc_info=True)
            await interaction.response.send_message(
                f"Error processing skill check: {ErrorTranslator.translate_error(e)}",
                ephemeral=True
            )

    @skillcheck.command(name="special")
    @app_commands.describe(
        character="Character making the check",
        check_type="Type of special check",
        advantage="Roll with advantage",
        disadvantage="Roll with disadvantage",
        modifier="Additional modifier to add/subtract (e.g., +2 or -1)",
        reason="Reason for the check (optional)"
    )
    @app_commands.choices(check_type=[
        app_commands.Choice(name="Death Save", value="death"),
        app_commands.Choice(name="Concentration", value="concentration")
    ])
    async def special(
        self,
        interaction: discord.Interaction,
        character: str,
        check_type: app_commands.Choice[str],
        advantage: bool = False,
        disadvantage: bool = False,
        modifier: Optional[int] = 0,
        reason: Optional[str] = None
    ):
        """Make a special check (death saves, concentration, etc.)"""
        try:
            char = self.bot.game_state.get_character(character)
            if not char:
                await interaction.response.send_message(
                    f"Character '{character}' not found.",
                    ephemeral=True
                )
                return

            if check_type.value == "death":
                # Death saves are straight d20 rolls
                expression = "1d20"
                if advantage and not disadvantage:
                    expression = "2d20k1"
                elif disadvantage and not advantage:
                    expression = "2d20kl1"
                
                if modifier:  # Add any modifiers
                    expression += f"{'+' if modifier > 0 else ''}{modifier}"
                    
                total, formatted, breakdown = DiceCalculator.calculate_complex(
                    expression,
                    character=char,
                    concise=False
                )
                
                embed = discord.Embed(
                    title=f"💀 {char.name}'s Death Save",
                    color=discord.Color.dark_red()
                )
                
                if total == 20:
                    result = "🎯 **NATURAL 20** - Gain 1 HP!"
                elif total >= 10:
                    result = "✅ Success"
                elif total == 1:
                    result = "💔 **NATURAL 1** - Counts as two failures!"
                else:
                    result = "❌ Failure"
                    
                embed.add_field(
                    name="Roll",
                    value=f"`{breakdown}`" if breakdown else str(total),
                    inline=True
                )
                embed.add_field(name="Result", value=result, inline=True)
                
            else:  # Concentration
                # Concentration is a Constitution save
                expression = build_roll_expression(
                    char, 
                    CheckType.SAVE, 
                    "constitution",
                    advantage,
                    disadvantage,
                    modifier
                )
                
                total, formatted, breakdown = DiceCalculator.calculate_complex(
                    expression,
                    character=char,
                    concise=False
                )
                
                dc = 10  # Base DC for concentration
                embed = await format_check_result(
                    total,
                    char,
                    CheckType.SAVE,
                    "constitution",
                    dc,
                    advantage,
                    disadvantage,
                    "Concentration Check",
                    breakdown
                )
                embed.title = f"🧠 {char.name}'s Concentration Check"

            if reason:
                embed.set_footer(text=f"Reason: {reason}")
                
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error in special check command: {e}", exc_info=True)
            await interaction.response.send_message(
                f"Error processing special check: {ErrorTranslator.translate_error(e)}",
                ephemeral=True
            )

    @skillcheck.command(name="contest")
    @app_commands.describe(
        character="Character making the check",
        opponent="Opposing character",
        type="Type of check (ability/skill)",
        stat_or_skill="Ability score or skill to use",  # This will be autocompleted
        advantage="Roll with advantage",
        disadvantage="Roll with disadvantage",
        opponent_advantage="Opponent rolls with advantage",
        opponent_disadvantage="Opponent rolls with disadvantage",
        modifier="Additional modifier for main character",
        opponent_modifier="Additional modifier for opponent",
        reason="Reason for the contest"
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="Ability Check", value="ability"),
            app_commands.Choice(name="Skill Check", value="skill")
        ]
    )
    async def contest(
        self,
        interaction: discord.Interaction,
        character: str,
        opponent: str,
        type: app_commands.Choice[str],
        stat_or_skill: str,  # This is now just a string
        advantage: bool = False,
        disadvantage: bool = False,
        opponent_advantage: bool = False,
        opponent_disadvantage: bool = False,
        modifier: Optional[int] = 0,
        opponent_modifier: Optional[int] = 0,
        reason: Optional[str] = None
    ):
        """Make a contested check against another character"""
        try:
            # Validate and get both characters
            char = self.bot.game_state.get_character(character)
            opp = self.bot.game_state.get_character(opponent)
            if not char or not opp:
                await interaction.response.send_message(
                    f"Character not found: {character if not char else opponent}",
                    ephemeral=True
                )
                return

            # Validate stat/skill based on type
            check_type = CheckType(type.value)
            if check_type == CheckType.SKILL:
                if stat_or_skill.lower() not in SKILL_ABILITIES:  # Use .lower() directly on string
                    await interaction.response.send_message(
                        f"Invalid skill: {stat_or_skill}",
                        ephemeral=True
                    )
                    return
            else:
                try:
                    StatType(stat_or_skill.lower())  # Use .lower() directly on string
                except ValueError:
                    await interaction.response.send_message(
                        f"Invalid ability score: {stat_or_skill}",
                        ephemeral=True
                    )
                    return

            # Build expressions for both characters
            char_expression = build_roll_expression(
                char, 
                check_type,
                stat_or_skill.lower(),
                advantage,
                disadvantage,
                modifier
            )
            
            opp_expression = build_roll_expression(
                opp, 
                check_type,
                stat_or_skill.lower(),
                opponent_advantage,
                opponent_disadvantage,
                opponent_modifier
            )
            
            # Roll for both
            char_total, _, char_breakdown = DiceCalculator.calculate_complex(
                char_expression,
                character=char,
                concise=False
            )
            opp_total, _, opp_breakdown = DiceCalculator.calculate_complex(
                opp_expression,
                character=opp,
                concise=False
            )

            # Format and send result
            embed = await format_contested_result(
                char,
                opp,
                char_total,
                opp_total,
                check_type,
                stat_or_skill.lower(),  # Use .lower() directly on string
                reason,
                char_breakdown,
                opp_breakdown
            )
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error in contest command: {e}", exc_info=True)
            await interaction.response.send_message(
                f"Error processing contested check: {ErrorTranslator.translate_error(e)}",
                ephemeral=True
            )

    @contest.autocomplete('stat_or_skill')
    async def contest_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        check_type = interaction.namespace.type
        
        if check_type == "ability":
            return [
                app_commands.Choice(name=choice.name, value=choice.value)
                for choice in ABILITY_CHOICES
                if current.lower() in choice.name.lower()
            ]
        else:
            return [
                app_commands.Choice(name=choice.name, value=choice.value)
                for choice in SKILL_CHOICES
                if current.lower() in choice.name.lower()
            ]

async def setup(bot):
    await bot.add_cog(SkillCheck(bot))