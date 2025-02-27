import discord
from discord.ui import View, Select, Button
from typing import Dict, List, Optional
from enum import Enum
from core.character import ProficiencyLevel, StatType

import logging
logger = logging.getLogger(__name__)

class ProficiencySelectionView(View):
    """UI for selecting character proficiencies with both points and proficiency-based limits"""
    def __init__(
        self,
        character_type: Enum,
        quick_create: bool = False,
        base_proficiency: int = 2,
        allowed_saves: int = 1,
        allowed_skills: int = 2,
        can_expertise: bool = False,
        timeout: Optional[float] = 180
    ):
        super().__init__(timeout=timeout)
        self.character_type = character_type
        self.quick_create = quick_create
        self.base_proficiency = base_proficiency
        self.max_saves = allowed_saves
        self.max_skills = allowed_skills
        self.can_expertise = can_expertise
        
        self.selected_saves: List[StatType] = []
        self.selected_skills: List[str] = []
        self.expertise: List[str] = []
        self.value = None
        
        if not quick_create:
            from utils.proficiency_config import SKILLS
            self.available_skills = SKILLS
            # Start with total points based on max possible selections
            self.total_points = self.max_saves + self.max_skills
            self.points_remaining = self.total_points
            logger.info(
                f"Initialized hybrid proficiency selection - Points: {self.points_remaining}, "
                f"Max Saves: {self.max_saves}, Max Skills: {self.max_skills}, "
                f"Can Expertise: {self.can_expertise} for {character_type}"
            )
            self._setup_components()

    def _setup_components(self):
        """Add all the selection components to the view"""
        # Save selection - respect both points and max saves
        max_saves = min(self.max_saves, max(1, self.points_remaining))
        logger.info(f"Setting up save selection with max {max_saves} saves")
        save_select = Select(
            placeholder="Select Saving Throw Proficiencies",
            options=[
                discord.SelectOption(
                    label=f"{stat.value.capitalize()} Save",
                    value=stat.value,
                    description=f"Add proficiency to {stat.value} saving throws"
                )
                for stat in StatType
            ],
            min_values=0,
            max_values=max_saves,
            custom_id="save_select"
        )
        save_select.callback = self.on_save_select
        self.add_item(save_select)

        # Skill selection - respect both points and max skills
        max_skills = min(self.max_skills, self.points_remaining)
        logger.info(f"Setting up skill selection with max {max_skills} skills")
        skill_select = Select(
            placeholder="Select Skill Proficiencies",
            options=[
                discord.SelectOption(
                    label=skill.capitalize(),
                    value=skill,
                    description=f"{stat.value.capitalize()}-based skill"
                )
                for skill, stat in self.available_skills.items()
            ],
            min_values=0,
            max_values=max_skills,
            custom_id="skill_select"
        )
        skill_select.callback = self.on_skill_select
        self.add_item(skill_select)

        # Add confirmation button
        confirm_button = Button(
            label="Confirm Selections",
            style=discord.ButtonStyle.success,
            custom_id="confirm"
        )
        confirm_button.callback = self.on_confirm
        self.add_item(confirm_button)

    async def start(self, interaction: discord.Interaction):
        """Start the proficiency selection process"""
        embed = discord.Embed(
            title="Proficiency Selection",
            description=(
                f"Select your proficiencies using the dropdowns below.\n"
                f"Proficiency Bonus: +{self.base_proficiency}\n"
                f"Points Available: {self.points_remaining}/{self.total_points}\n"
                f"Maximum Saves: {self.max_saves}\n"
                f"Maximum Skills: {self.max_skills}\n"
                f"Expertise Available: {'Yes' if self.can_expertise else 'No'}\n\n"
                "**Steps:**\n"
                "1. Select saving throw proficiencies\n"
                "2. Select skill proficiencies\n"
                f"3. {'Choose expertise (if available)' if self.can_expertise else 'Review selections'}\n"
                "4. Click confirm when done"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_save_select(self, interaction: discord.Interaction):
        """Handle saving throw selection"""
        values = interaction.data["values"]
        self.selected_saves = [StatType(value) for value in values]
        self.points_remaining = self._calculate_remaining_points()
        await self.update_display(interaction)

    async def on_skill_select(self, interaction: discord.Interaction):
        """Handle skill selection"""
        values = interaction.data["values"]
        self.selected_skills = values
        self.points_remaining = self._calculate_remaining_points()
        
        if len(self.selected_skills) > 0 and self.can_expertise:
            # Only show expertise if allowed and skills are selected
            await self.show_expertise_selection(interaction)
        else:
            await self.update_display(interaction)

    async def show_expertise_selection(self, interaction: discord.Interaction):
        """Show expertise selection for chosen skills"""
        # Remove old expertise select if it exists
        self.remove_item_type(Select, "expertise_select")
        
        expertise_select = Select(
            placeholder="Select Skills for Expertise (Optional)",
            options=[
                discord.SelectOption(
                    label=f"{skill.capitalize()} (Expert)",
                    value=skill,
                    description="Double proficiency bonus"
                )
                for skill in self.selected_skills
            ],
            min_values=0,
            max_values=1,  # Limit to one expertise
            custom_id="expertise_select"
        )
        expertise_select.callback = self.on_expertise_select
        self.add_item(expertise_select)
        await self.update_display(interaction)

    async def on_expertise_select(self, interaction: discord.Interaction):
        """Handle expertise selection"""
        values = interaction.data["values"]
        self.expertise = values
        await self.update_display(interaction)

    async def on_confirm(self, interaction: discord.Interaction):
        """Handle confirmation of selections"""
        if len(self.selected_saves) > self.max_saves or len(self.selected_skills) > self.max_skills:
            await interaction.response.send_message(
                "You've selected more proficiencies than allowed. Please adjust your selections.",
                ephemeral=True
            )
            return

        logger.info(
            f"Confirming selections - Saves: {self.selected_saves}, "
            f"Skills: {self.selected_skills}, Expertise: {self.expertise}"
        )
        
        # Create proficiency dictionary
        proficiencies = {
            "saves": {
                stat.value: ProficiencyLevel.PROFICIENT.value 
                for stat in self.selected_saves
            },
            "skills": {
                skill: (
                    ProficiencyLevel.EXPERT.value if skill in self.expertise 
                    else ProficiencyLevel.PROFICIENT.value
                )
                for skill in self.selected_skills
            }
        }
        
        logger.info(f"Created proficiency dictionary: {proficiencies}")
        
        # Show confirmation message
        embed = discord.Embed(
            title="Proficiencies Confirmed!",
            description="Creating your character...",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)
        
        # Set the value and stop the view
        self.value = proficiencies
        self.stop()

    def _calculate_remaining_points(self) -> int:
        """Calculate remaining proficiency points while respecting limits"""
        used = len(self.selected_saves) + len(self.selected_skills)
        remaining = self.total_points - used
        
        # Ensure we don't exceed proficiency-based limits
        if len(self.selected_saves) > self.max_saves:
            remaining = 0
        if len(self.selected_skills) > self.max_skills:
            remaining = 0
            
        return max(0, remaining)

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed with current selections"""
        logger.info(
            f"Updating display - Points: {self.points_remaining}/{self.total_points}, "
            f"Saves: {self.selected_saves}, Skills: {self.selected_skills}, "
            f"Expertise: {self.expertise}"
        )
        
        embed = discord.Embed(
            title="Proficiency Selection",
            description=(
                f"Points Remaining: {self.points_remaining}/{self.total_points}\n\n"
                "**Current Limits:**\n"
                f"• Saving Throws: {len(self.selected_saves)}/{self.max_saves}\n"
                f"• Skills: {len(self.selected_skills)}/{self.max_skills}\n"
                f"• Expertise: {'Available' if self.can_expertise else 'Not Available'}\n\n"
                "Click confirm when you're done"
            ),
            color=discord.Color.blue()
        )

        if self.selected_saves:
            saves_text = "\n".join(f"• {save.value.capitalize()}" for save in self.selected_saves)
            embed.add_field(
                name="Selected Saving Throws",
                value=saves_text,
                inline=True
            )

        if self.selected_skills:
            skills_text = "\n".join(
                f"• {skill.capitalize()}" + 
                (" (Expert)" if skill in self.expertise else "")
                for skill in self.selected_skills
            )
            embed.add_field(
                name="Selected Skills",
                value=skills_text,
                inline=True
            )
        else:
            embed.add_field(
                name="Selected Skills",
                value="None selected yet",
                inline=True
            )

        try:
            await interaction.response.edit_message(embed=embed, view=self)
            logger.info("Successfully updated display")
        except Exception as e:
            logger.error(f"Error updating display: {e}")

    def remove_item_type(self, item_type, custom_id=None):
        """Remove items of a specific type and optionally with a specific custom_id"""
        to_remove = []
        for item in self.children:
            if isinstance(item, item_type):
                if custom_id is None or getattr(item, "custom_id", None) == custom_id:
                    to_remove.append(item)
        
        for item in to_remove:
            self.remove_item(item)

