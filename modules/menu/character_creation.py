"""
Character Creation UI Components (src/modules/menu/character_creation.py)

This file contains the enhanced UI components for character creation, including
multiple stat generation methods, power level presets, and comprehensive previews.

Features:
- Multiple stat generation methods
- Power level presets (Weak, Medium, Strong, etc.)
- Stat rerolling
- Skill preview
- Random name generation (coming soon)
- Comprehensive stat displays
"""

import discord
from discord import ui
from discord.ui import Modal, TextInput, View, Select, Button
from typing import Optional, Dict, Any, List, Union
from enum import Enum
from core.character import (
    Character, Stats, Resources, DefenseStats, 
    StatType, ProficiencyLevel
)
import random
import logging
from enum import Enum

from utils.proficiency_config import (
    ChuaStyle, FairyType, get_preset_proficiencies, 
    calculate_spell_save_dc, get_proficiency_limits
)
from .proficiency_selection import ProficiencySelectionView

logger = logging.getLogger(__name__)

class CharacterTypeView(View):
    """View for selecting character type and style"""
    def __init__(self, name: str, hp: int, mp: int, ac: int, stats: Dict[StatType, int],
                 base_proficiency: int, allowed_saves: int, allowed_skills: int, can_expertise: bool):
        super().__init__()
        self.name = name
        self.hp = hp
        self.mp = mp
        self.ac = ac
        self.stats = stats
        self.base_proficiency = base_proficiency
        self.allowed_saves = allowed_saves
        self.allowed_skills = allowed_skills
        self.can_expertise = can_expertise
        
        # Add creature type selection
        self.creature_select = Select(
            placeholder="Select Creature Type",
            options=[
                discord.SelectOption(
                    label="Chua",
                    value="chua",
                    description="Essence-wielding warriors"
                ),
                discord.SelectOption(
                    label="Fairy",
                    value="fairy",
                    description="Magical beings with diverse abilities"
                )
            ],
            custom_id="creature_type"
        )
        self.creature_select.callback = self.on_creature_select
        self.add_item(self.creature_select)

    async def start(self, interaction: discord.Interaction):
        """Start the character type selection process"""
        embed = discord.Embed(
            title="Character Type Selection",
            description=(
                "Choose your character type to proceed with proficiency selection\n\n"
                f"Proficiency Bonus: +{self.base_proficiency}\n"
                f"Available Saves: {self.allowed_saves}\n"
                f"Available Skills: {self.allowed_skills}\n"
                f"Can Select Expertise: {'Yes' if self.can_expertise else 'No'}"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_creature_select(self, interaction: discord.Interaction):
        """Handle creature type selection"""
        try:
            if self.creature_select.values[0] == "chua":
                # Show Chua style options
                style_select = Select(
                    placeholder="Select Combat Style",
                    options=[
                        discord.SelectOption(
                            label="Tank",
                            value="tank",
                            description="Durable physical fighters"
                        ),
                        discord.SelectOption(
                            label="Rusher",
                            value="rusher",
                            description="Swift, agile combatants"
                        ),
                        discord.SelectOption(
                            label="Elemental",
                            value="elemental",
                            description="Essence manipulation specialists"
                        ),
                        discord.SelectOption(
                            label="Tank-Rusher Hybrid",
                            value="hybrid_tank_rusher",
                            description="Combines Tank and Rusher styles"
                        ),
                        discord.SelectOption(
                            label="Tank-Elemental Hybrid",
                            value="hybrid_tank_elemental",
                            description="Combines Tank and Elemental styles"
                        ),
                        discord.SelectOption(
                            label="Rusher-Elemental Hybrid",
                            value="hybrid_rusher_elemental",
                            description="Combines Rusher and Elemental styles"
                        ),
                        discord.SelectOption(
                            label="Balancer",
                            value="balancer",
                            description="Adaptable fighter, learns multiple styles"
                        )
                    ]
                )
                style_enum = ChuaStyle
            else:
                # Show Fairy type options
                style_select = Select(
                    placeholder="Select Fairy Type",
                    options=[
                        discord.SelectOption(
                            label="Energy",
                            value="energy",
                            description="Energy manipulation and teleportation"
                        ),
                        discord.SelectOption(
                            label="Mind",
                            value="mind",
                            description="Telekinesis and mental abilities"
                        ),
                        discord.SelectOption(
                            label="Spell",
                            value="spell",
                            description="Versatile spellcasting"
                        ),
                        discord.SelectOption(
                            label="Fighting",
                            value="fighting",
                            description="Physical combat specialists"
                        ),
                        discord.SelectOption(
                            label="Spirit",
                            value="spirit",
                            description="Spiritual and supernatural abilities"
                        ),
                        discord.SelectOption(
                            label="Omni",
                            value="omni",
                            description="Access to multiple fairy abilities"
                        )
                    ]
                )
                style_enum = FairyType

            style_view = View()
            
            async def on_style_select(style_interaction: discord.Interaction):
                try:
                    style = style_enum(style_select.values[0])
                    await self.show_proficiency_options(style_interaction, style)
                except Exception as e:
                    logger.error(f"Error in style selection: {e}", exc_info=True)
                    await style_interaction.response.send_message(
                        "An error occurred while processing your selection. Please try again.",
                        ephemeral=True
                    )

            style_select.callback = on_style_select
            style_view.add_item(style_select)
            
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title=f"Select {'Combat Style' if self.creature_select.values[0] == 'chua' else 'Fairy Type'}",
                    description=(
                        "Choose your specialization:\n\n"
                        f"Proficiency Bonus: +{self.base_proficiency}\n"
                        f"Available Saves: {self.allowed_saves}\n"
                        f"Available Skills: {self.allowed_skills}\n"
                        f"Can Select Expertise: {'Yes' if self.can_expertise else 'No'}"
                    ),
                    color=discord.Color.blue()
                ),
                view=style_view
            )
        except Exception as e:
            logger.error(f"Error in creature type selection: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while processing your selection. Please try again.",
                ephemeral=True
            )

    async def show_proficiency_options(self, interaction: discord.Interaction, style: Enum):
        """Show proficiency selection options"""
        try:
            quick_view = View()
            
            quick_button = Button(
                label="Quick Create",
                style=discord.ButtonStyle.primary,
                custom_id="quick"
            )
            manual_button = Button(
                label="Manual Proficiencies",
                style=discord.ButtonStyle.secondary,
                custom_id="manual"
            )
            
            async def on_quick_create(button_interaction: discord.Interaction):
                await self.handle_character_creation(button_interaction, style, quick_create=True)
                
            async def on_manual_create(button_interaction: discord.Interaction):
                await self.handle_character_creation(button_interaction, style, quick_create=False)
            
            quick_button.callback = on_quick_create
            manual_button.callback = on_manual_create
            
            quick_view.add_item(quick_button)
            quick_view.add_item(manual_button)
            
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="Proficiency Selection",
                    description=(
                        "Choose how to set proficiencies:\n\n"
                        "🎲 Quick Create: Use preset proficiencies\n"
                        "✍️ Manual: Choose your own proficiencies\n\n"
                        f"Proficiency Bonus: +{self.base_proficiency}\n"
                        f"Available Saves: {self.allowed_saves}\n"
                        f"Available Skills: {self.allowed_skills}\n"
                        f"Can Select Expertise: {'Yes' if self.can_expertise else 'No'}"
                    ),
                    color=discord.Color.blue()
                ),
                view=quick_view
            )
        except Exception as e:
            logger.error(f"Error showing proficiency options: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while showing proficiency options. Please try again.",
                ephemeral=True
            )

    async def handle_character_creation(self, interaction: discord.Interaction, style: Enum, quick_create: bool):
        """Handle character creation process"""
        try:
            if quick_create:
                # Show loading message for quick create
                await interaction.response.edit_message(
                    embed=discord.Embed(
                        title="Creating Character",
                        description="Processing your selections...",
                        color=discord.Color.blue()
                    ),
                    view=None
                )

                logger.info(f"Quick creating character with style {style}")
                proficiencies = get_preset_proficiencies(style)
            else:
                # For manual creation, defer the interaction first
                await interaction.response.defer()
                
                logger.info(f"Starting manual proficiency selection for style {style}")
                prof_view = ProficiencySelectionView(
                    style, 
                    quick_create=False,
                    base_proficiency=self.base_proficiency,
                    allowed_saves=self.allowed_saves,
                    allowed_skills=self.allowed_skills,
                    can_expertise=self.can_expertise
                )
                
                # Send new message with proficiency selection
                selection_embed = discord.Embed(
                    title="Select Proficiencies",
                    description="Choose your character's proficiencies",
                    color=discord.Color.blue()
                )
                selection_message = await interaction.followup.send(
                    embed=selection_embed,
                    view=prof_view,
                    wait=True
                )
                
                # Wait for proficiency selection
                await prof_view.wait()
                proficiencies = prof_view.value
                    
                if not proficiencies:
                    logger.info("Proficiency selection cancelled or timed out")
                    await selection_message.edit(
                        embed=discord.Embed(
                            title="Character Creation Cancelled",
                            description="Proficiency selection was cancelled or timed out.",
                            color=discord.Color.red()
                        ),
                        view=None
                    )
                    return
            
            logger.info(f"Creating character with proficiencies: {proficiencies}")
            
            character = create_character_with_stats(
                name=self.name,
                hp=self.hp,
                mp=self.mp,
                ac=self.ac,
                base_stats=self.stats,
                style=style,
                proficiencies=proficiencies,
                base_proficiency=self.base_proficiency
            )
            
            logger.info("Saving character to database")
            await interaction.client.db.save_character(character)
            
            logger.info("Character created successfully, showing results")
            # Show completion message
            success_embed = discord.Embed(
                title="✨ Character Created!",
                description=f"Character {self.name} has been created successfully.",
                color=discord.Color.green()
            )
            
            # For quick create, we can edit the original message
            # For manual create, we send a new message
            if quick_create:
                await interaction.channel.send(embed=success_embed)
            else:
                await selection_message.edit(embed=success_embed, view=None)
                
            await display_creation_result(interaction, character)
            
        except Exception as e:
            logger.error(f"Error in character creation: {e}", exc_info=True)
            error_embed = discord.Embed(
                title="Error",
                description="An error occurred during character creation. Please try again.",
                color=discord.Color.red()
            )
            try:
                if quick_create:
                    await interaction.followup.send(embed=error_embed)
                else:
                    await interaction.channel.send(embed=error_embed)
            except:
                await interaction.channel.send(embed=error_embed)

class ProficiencyLevelView(View):
    """Initial view for selecting base proficiency level"""
    def __init__(self, name: str, hp: int, mp: int, ac: int, stats: Dict[StatType, int]):
        super().__init__()
        self.name = name
        self.hp = hp
        self.mp = mp
        self.ac = ac
        self.stats = stats
        
        # Add proficiency selection dropdown
        self.prof_select = Select(
            placeholder="Select Proficiency Level",
            options=[
                discord.SelectOption(
                    label=f"+{i} Proficiency",
                    value=str(i),
                    description=f"{'Novice' if i==1 else 'Trained' if i==2 else 'Expert' if i==3 else 'Master' if i==4 else 'Legendary'}"
                )
                for i in range(1, 6)  # Proficiency from +1 to +5
            ],
            custom_id="proficiency_level"
        )
        self.prof_select.callback = self.on_prof_select
        self.add_item(self.prof_select)

    async def start(self, interaction: discord.Interaction):
        """Start the proficiency level selection process"""
        embed = discord.Embed(
            title="Character Proficiency",
            description=(
                "Select your character's base proficiency bonus.\n\n"
                "This determines their overall skill level:\n"
                "• +1: Novice - Learning the basics\n"
                "• +2: Trained - Competent practitioner\n"
                "• +3: Expert - Highly skilled\n"
                "• +4: Master - Elite level\n"
                "• +5: Legendary - Peak performance"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def on_prof_select(self, interaction: discord.Interaction):
            """Handle proficiency level selection"""
            try:
                prof_level = int(self.prof_select.values[0])
                # Get limits based on proficiency
                limits = get_proficiency_limits(prof_level)
                
                # Create type selection view with proficiency info
                type_view = CharacterTypeView(
                    name=self.name,
                    hp=self.hp,
                    mp=self.mp,
                    ac=self.ac,
                    stats=self.stats,
                    base_proficiency=prof_level,
                    allowed_saves=limits["saves"],
                    allowed_skills=limits["skills"],
                    can_expertise=limits["can_expertise"]
                )
                await type_view.start(interaction)
                
            except Exception as e:
                logger.error(f"Error in proficiency selection: {e}", exc_info=True)
                await interaction.response.send_message(
                    "An error occurred while processing your selection. Please try again.",
                    ephemeral=True
                )

class StatInputModal(Modal):
    """Single modal for manual stat entry"""
    def __init__(self, name: str, hp: int, mp: int, ac: int) -> None:
        super().__init__(title=f"Set Stats for {name}")
        self.name = name
        self.base_hp = hp
        self.base_mp = mp
        self.base_ac = ac
        
        # First five stats (Discord limit)
        self.strength = TextInput(
            label="Strength",
            placeholder="Enter strength (3-18)",
            default="10",
            min_length=1,
            max_length=2,
            required=True
        )
        self.dexterity = TextInput(
            label="Dexterity",
            placeholder="Enter dexterity (3-18)",
            default="10",
            min_length=1,
            max_length=2,
            required=True
        )
        self.constitution = TextInput(
            label="Constitution",
            placeholder="Enter constitution (3-18)",
            default="10",
            min_length=1,
            max_length=2,
            required=True
        )
        self.intelligence = TextInput(
            label="Intelligence",
            placeholder="Enter intelligence (3-18)",
            default="10",
            min_length=1,
            max_length=2,
            required=True
        )
        self.wisdom = TextInput(
            label="Wisdom",
            placeholder="Enter wisdom (3-18)",
            default="10",
            min_length=1,
            max_length=2,
            required=True
        )

        for stat in [self.strength, self.dexterity, self.constitution, 
                    self.intelligence, self.wisdom]:
            self.add_item(stat)

    async def on_submit(self, interaction: discord.Interaction):
        # Create stats dictionary
        stats = {
            StatType.STRENGTH: int(self.strength.value),
            StatType.DEXTERITY: int(self.dexterity.value),
            StatType.CONSTITUTION: int(self.constitution.value),
            StatType.INTELLIGENCE: int(self.intelligence.value),
            StatType.WISDOM: int(self.wisdom.value),
            # Default charisma for now
            StatType.CHARISMA: 10
        }
        
        # Create a view for final stat confirmation
        view = StatConfirmationView(self.name, self.base_hp, self.base_mp, self.base_ac, stats)
        embed = create_stat_preview_embed(self.name, stats)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class StatConfirmationView(View):
    def __init__(self, name: str, hp: int, mp: int, ac: int, stats: Dict[StatType, int]):
        super().__init__()
        self.name = name
        self.hp = hp
        self.mp = mp
        self.ac = ac
        self.stats = stats

    @discord.ui.button(label="Edit Charisma", style=discord.ButtonStyle.primary)
    async def edit_charisma(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CharismaModal(self.name, self.hp, self.mp, self.ac, self.stats)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Accept Stats", style=discord.ButtonStyle.success)
    async def accept_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Start proficiency selection after accepting stats"""
        # Direct to proficiency level selection first
        prof_level_view = ProficiencyLevelView(
            name=self.name,
            hp=self.hp,
            mp=self.mp,
            ac=self.ac,
            stats=self.stats
        )
        await prof_level_view.start(interaction)

class CharismaModal(Modal):
    def __init__(self, name: str, hp: int, mp: int, ac: int, stats: Dict[StatType, int]):
        super().__init__(title=f"Set Charisma for {name}")
        self.name = name
        self.hp = hp
        self.mp = mp
        self.ac = ac
        self.stats = stats.copy()
        
        self.charisma = TextInput(
            label="Charisma",
            placeholder="Enter charisma (3-18)",
            default="10",
            min_length=1,
            max_length=2,
            required=True
        )
        self.add_item(self.charisma)

    async def on_submit(self, interaction: discord.Interaction):
        self.stats[StatType.CHARISMA] = int(self.charisma.value)
        view = StatConfirmationView(self.name, self.hp, self.mp, self.ac, self.stats)
        embed = create_stat_preview_embed(self.name, self.stats)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class StatRollView(View):
    """View for displaying and rerolling stats"""
    def __init__(self, name: str, hp: int, mp: int, ac: int, method: str = "4d6", power_level: Optional[dict] = None):
        super().__init__()
        self.name = name
        self.hp = hp
        self.mp = mp
        self.ac = ac
        self.method = method
        self.power_level = power_level
        self.current_stats = self.generate_stats()
        
    def generate_stats(self) -> Dict[StatType, int]:
        """Generate stats based on selected method"""
        if self.power_level:
            return PowerLevel.get_stats(self.power_level)
            
        stats = {}
        for stat in StatType:
            if self.method == "4d6":
                # 4d6 drop lowest
                rolls = sorted([random.randint(1, 6) for _ in range(4)])
                stats[stat] = sum(rolls[1:])
            elif self.method == "3d6":
                # Straight 3d6
                stats[stat] = sum(random.randint(1, 6) for _ in range(3))
            elif self.method == "2d6+6":
                # 2d6+6 (more average distribution)
                stats[stat] = sum(random.randint(1, 6) for _ in range(2)) + 6
                
        return stats

    async def update_display(self, interaction: discord.Interaction):
        """Update the stat display embed"""
        embed = create_stat_preview_embed(self.name, self.current_stats)
        if isinstance(interaction, discord.Interaction):
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Reroll All", style=discord.ButtonStyle.primary)
    async def reroll_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Reroll all stats"""
        self.current_stats = self.generate_stats()
        await self.update_display(interaction)

    @discord.ui.button(label="Accept Stats", style=discord.ButtonStyle.success)
    async def accept_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Start proficiency selection after accepting stats"""
        prof_level_view = ProficiencyLevelView(
            name=self.name,
            hp=self.hp,
            mp=self.mp,
            ac=self.ac,
            stats=self.current_stats
        )
        await prof_level_view.start(interaction)

class StatGenerationView(View):
    """View for choosing how to generate stats"""
    def __init__(self, name: str, hp: int, mp: int, ac: int):
        super().__init__()
        self.name = name
        self.hp = hp
        self.mp = mp
        self.ac = ac

    @discord.ui.button(label="Manual Entry", style=discord.ButtonStyle.primary)
    async def manual_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal for manual stat entry"""
        modal = StatInputModal(self.name, self.hp, self.mp, self.ac)
        await interaction.response.send_modal(modal)

    @discord.ui.select(
        placeholder="Choose a Power Level...",
        options=[
            discord.SelectOption(label="Novice", description="Below average stats (6-13)", emoji="🌱"),
            discord.SelectOption(label="Intermediate", description="Balanced stats (8-15)", emoji="⚖️"),
            discord.SelectOption(label="Advanced", description="Above average stats (10-16)", emoji="📈"),
            discord.SelectOption(label="Exceptional", description="Superior stats (12-17)", emoji="⭐"),
            discord.SelectOption(label="Supreme", description="Peak stats (14-18)", emoji="💫")
        ]
    )
    async def power_level_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        """Generate stats based on power level"""
        power_levels = {
            "Novice": PowerLevel.NOVICE,
            "Intermediate": PowerLevel.INTERMEDIATE,
            "Advanced": PowerLevel.ADVANCED,
            "Exceptional": PowerLevel.EXCEPTIONAL,
            "Supreme": PowerLevel.SUPREME
        }
        
        view = StatRollView(
            self.name, self.hp, self.mp, self.ac,
            power_level=power_levels[select.values[0]]
        )
        await interaction.response.edit_message(view=view)
        await view.update_display(interaction)

    @discord.ui.select(
        placeholder="Choose a Roll Method...",
        options=[
            discord.SelectOption(label="4d6 Drop Lowest", description="Classic method, tends toward higher stats", emoji="🎲"),
            discord.SelectOption(label="Standard 3d6", description="Pure random, truly random stats", emoji="🎯"),
            discord.SelectOption(label="2d6+6", description="More balanced, reliable stats", emoji="⚖️")
        ]
    )
    async def roll_method_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        """Generate stats using selected roll method"""
        method_map = {
            "4d6 Drop Lowest": "4d6",
            "Standard 3d6": "3d6",
            "2d6+6": "2d6+6"
        }
        
        view = StatRollView(
            self.name, self.hp, self.mp, self.ac,
            method=method_map[select.values[0]]
        )
        await interaction.response.edit_message(view=view)
        await view.update_display(interaction)

class PowerLevel:
    """Defines stat ranges and proficiency for different power levels"""
    NOVICE = {"min": 6, "max": 13, "bonus": -1, "proficiency": 2}
    INTERMEDIATE = {"min": 8, "max": 15, "bonus": 0, "proficiency": 2}
    ADVANCED = {"min": 10, "max": 16, "bonus": 1, "proficiency": 3}
    EXCEPTIONAL = {"min": 12, "max": 17, "bonus": 2, "proficiency": 4}
    SUPREME = {"min": 14, "max": 18, "bonus": 3, "proficiency": 5}

    @staticmethod
    def get_stats(level: dict) -> Dict[StatType, int]:
        """Generate stats within the given power level range"""
        stats = {}
        for stat in StatType:
            base = random.randint(level["min"], level["max"])
            bonus = level["bonus"]
            stats[stat] = min(20, max(3, base + bonus))
        return stats

def create_character_with_stats(*, 
    name: str, 
    hp: int, 
    mp: int, 
    ac: int,
    base_stats: Dict[StatType, int], 
    style: Optional[Union[Enum, str]] = None,  # Updated to allow string
    proficiencies: Optional[Dict] = None,
    base_proficiency: int = 2
) -> Character:
    """Helper function to create a character with given stats"""
    stats = Stats(base=base_stats, modified=base_stats.copy())
    resources = Resources(current_hp=hp, max_hp=hp, current_mp=mp, max_mp=mp)
    defense = DefenseStats(base_ac=ac, current_ac=ac)
    
    logger.info(f"Creating character with style: {style}, proficiency: {base_proficiency}")
    logger.info(f"Proficiencies provided: {proficiencies}")
    
    # Create character with specified base proficiency
    character = Character(
        name=name,
        stats=stats,
        resources=resources,
        defense=defense,
        base_proficiency=base_proficiency
    )
    
    # Convert string style to enum if needed
    if isinstance(style, str):
        if hasattr(ChuaStyle, style.upper()):
            style = ChuaStyle[style.upper()]
        elif hasattr(FairyType, style.upper()):
            style = FairyType[style.upper()]
            
    # Set style
    character.style = style
    
    # Set proficiencies if provided
    if proficiencies:
        if 'saves' in proficiencies:
            for stat_value, level_value in proficiencies['saves'].items():
                if isinstance(stat_value, str):
                    stat = StatType(stat_value)
                else:
                    stat = stat_value
                character.set_save_proficiency(stat, ProficiencyLevel(level_value))
        
        if 'skills' in proficiencies:
            for skill, level_value in proficiencies['skills'].items():
                character.set_skill_proficiency(skill, ProficiencyLevel(level_value))

    # Calculate spell save DC (8 + proficiency + highest of INT, WIS, CHA modifier + style bonus)
    spellcasting_mods = [
        (base_stats[StatType.INTELLIGENCE] - 10) // 2,
        (base_stats[StatType.WISDOM] - 10) // 2,
        (base_stats[StatType.CHARISMA] - 10) // 2
    ]
    highest_mod = max(spellcasting_mods)
    
    if style:
        character.spell_save_dc = calculate_spell_save_dc(style, base_proficiency, highest_mod)
    else:
        character.spell_save_dc = 8 + base_proficiency + highest_mod
    
    logger.info(f"Character created successfully: {character.name}")
    return character

def preview_skills(stats: Dict[StatType, int]) -> str:
    """Generate a preview of key skills with these stats"""
    skills = []
    
    # Calculate some sample skills
    str_mod = (stats[StatType.STRENGTH] - 10) // 2
    dex_mod = (stats[StatType.DEXTERITY] - 10) // 2
    int_mod = (stats[StatType.INTELLIGENCE] - 10) // 2
    
    skills.extend([
        f"Athletics: {str_mod:+}",
        f"Acrobatics: {dex_mod:+}",
        f"Investigation: {int_mod:+}"
    ])
    
    return "\n".join(skills)

def create_stat_preview_embed(name: str, stats: Dict[StatType, int]) -> discord.Embed:
    """Create an embed for previewing character stats"""
    embed = discord.Embed(
        title=f"Stats Preview for {name}",
        color=discord.Color.blue()
    )
    
    # Show current stats with modifiers
    stats_display = []
    for stat in StatType:
        value = stats[stat]
        mod = (value - 10) // 2
        stats_display.append(f"{stat.value.capitalize()}: {value} ({mod:+})")
    
    embed.add_field(
        name="Current Stats",
        value="\n".join(stats_display),
        inline=True
    )

    # Show example skills with these stats
    skills_preview = preview_skills(stats)
    embed.add_field(
        name="Sample Skills",
        value=skills_preview,
        inline=True
    )
    
    return embed

async def display_creation_result(interaction: discord.Interaction, character: Character) -> None:
    """Create and send an embed showing the created character's stats"""
    embed = discord.Embed(
        title=f"✨ Character Created: {character.name}",
        color=discord.Color.green()
    )

    # Add race/type info
    if character.style:
        creature_type = "Chua" if isinstance(character.style, ChuaStyle) else "Fairy"
        type_info = f"{creature_type} - {character.style.value.capitalize()}"
        embed.add_field(name="Type", value=type_info, inline=False)

    # Core resources
    resources = (
        f"❤️ HP: {character.resources.current_hp}/{character.resources.max_hp}\n"
        f"💙 MP: {character.resources.current_mp}/{character.resources.max_mp}\n"
        f"🛡️ AC: {character.defense.current_ac}"
    )
    embed.add_field(name="Resources", value=resources, inline=False)

    # Base stats with modifiers
    stats_display = []
    for stat in StatType:
        value = character.stats.base[stat]
        mod = character.stats.get_modifier(stat)
        stats_display.append(f"{stat.value.capitalize()}: {value} ({mod:+})")
    
    embed.add_field(name="Stats", value="\n".join(stats_display), inline=False)
    
    # Add proficiency and spell save DC
    derived_stats = (
        f"Proficiency Bonus: +{character.base_proficiency}\n"
        f"Spell Save DC: {character.spell_save_dc}"
    )
    embed.add_field(name="Derived Stats", value=derived_stats, inline=False)

    # Show proficiencies
    prof_display = []
    if hasattr(character, 'proficiencies'):
        # Show saving throws
        saves = [
            f"{stat.value.capitalize()} Save (+{character.saves[stat]})"
            for stat, level in character.proficiencies.saves.items()
            if level != ProficiencyLevel.NONE
        ]
        if saves:
            prof_display.append("**Saving Throws:** " + ", ".join(saves))
        
        # Show skills
        skills = [
            f"{skill.capitalize()} (+{character.skills[skill]})" + 
            (" (Expertise)" if character.proficiencies.skills[skill] == ProficiencyLevel.EXPERT else "")
            for skill, level in character.proficiencies.skills.items()
            if level != ProficiencyLevel.NONE
        ]
        if skills:
            prof_display.append("**Skills:** " + ", ".join(skills))

    if prof_display:
        embed.add_field(name="Proficiencies", value="\n".join(prof_display), inline=False)

    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)
    except Exception as e:
        # Fallback if both methods fail
        await interaction.channel.send(embed=embed)