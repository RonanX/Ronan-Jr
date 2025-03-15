"""
src/modules/menu/character_viewer.py

Main class to handle character information display and interaction.
"""

import discord
from discord import Interaction, Embed, ButtonStyle, Color, SelectOption
from discord.ui import View, Button, Select
from typing import Optional, Dict, Any, List, Tuple

from core.character import Character
from modules.menu.defense_handler import DefenseHandler

class CharacterViewer:
    """Main class to handle character information display and interaction."""
    def __init__(self, character: Any):
        self.character = character
        self.current_view: Optional[View] = None
        self.current_page = "overview"
        self.action_handler = None
        self.bot = None

    def _get_attr(self, attr: str, default: Any = None) -> Any:
        """Safely get attribute from either Character object or dict"""
        if isinstance(self.character, dict):
            if '.' in attr:  # Handle nested attributes
                value = self.character
                for key in attr.split('.'):
                    value = value.get(key, {})
                return value or default
            return self.character.get(attr, default)
        
        # Handle nested attributes for Character object
        if '.' in attr:
            value = self.character
            for key in attr.split('.'):
                value = getattr(value, key, None)
                if value is None:
                    return default
            return value
        return getattr(self.character, attr, default)

    def get_effect_modifiers(self, effect_type: str) -> List[Tuple[int, str]]:
        """Get list of modifiers from effects along with their sources"""
        modifiers = []
        effects = self._get_attr('effects', [])
        
        for effect in effects:
            if isinstance(effect, dict):
                if effect.get('type') == effect_type:
                    amount = effect.get('amount', 0)
                    source = effect.get('source', 'Unknown')
                    if amount != 0:
                        modifiers.append((amount, source))
            else:
                # Handle Effect objects
                if getattr(effect, 'type', None) == effect_type:
                    amount = getattr(effect, 'amount', 0)
                    source = getattr(effect, 'source', 'Unknown')
                    if amount != 0:
                        modifiers.append((amount, source))
                    
        return modifiers

    def get_ac_display(self) -> str:
        """Get AC display string with modifiers if present"""
        base_ac = self._get_attr('defense.base_ac', 10)
        current_ac = self._get_attr('defense.current_ac', base_ac)
        
        # Calculate total modifier (current_ac - base_ac)
        total_mod = current_ac - base_ac
        
        # Only show modifier if non-zero
        if total_mod == 0:
            return f"`{base_ac}`"
        
        # Format with modifier
        sign = '+' if total_mod > 0 else ''
        return f"`{base_ac}` ({sign}{total_mod})"

    def get_hp_display(self) -> str:
        """Get HP display string with temp HP, formatted consistently with AC display"""
        current = self._get_attr('resources.current_hp', 0)
        maximum = self._get_attr('resources.max_hp', 0)
        current_temp = self._get_attr('resources.current_temp_hp', 0)
        max_temp = self._get_attr('resources.max_temp_hp', 0)
        
        # Base HP display
        display = f"`{current}/{maximum}`"
        
        # Add temp HP if present (matching AC modifier style)
        if current_temp > 0:
            display = f"{display} (+{current_temp})"
        
        return display

    async def show(self, interaction: discord.Interaction, ephemeral: bool = True) -> None:
        """Initialize and display the character viewer"""
        # Set bot from interaction if available
        if hasattr(interaction, 'client'):
            self.bot = interaction.client
            
            # Initialize action handler if needed
            if not self.action_handler:
                from modules.menu.action_handler import ActionHandler
                self.action_handler = ActionHandler(self.bot)
        
        # Create the main UI
        self.current_view = CharacterViewerUI(self)
        
        # Generate the embed
        embed = await self.create_current_embed()
        
        # Send the message with the view
        await interaction.response.send_message(embed=embed, view=self.current_view, ephemeral=ephemeral)

    async def create_current_embed(self) -> Embed:
        """Create embed based on current page"""
        if self.current_page == "overview":
            return await self._create_overview_embed()
        elif self.current_page == "stats":
            return await self._create_stats_embed()
        elif self.current_page == "defenses":
            return await self._create_defense_embed()
        elif self.current_page == "status":
            return await self._create_status_embed()
        elif self.current_page == "actions":
            return await self._create_actions_embed()
        elif self.current_page == "moveset":
            return await self._create_moveset_embed()
        elif self.current_page == "inventory":
            return await self._create_inventory_embed()
        return await self._create_overview_embed()

    async def _create_overview_embed(self) -> Embed:
        """Create the overview page embed"""
        embed = Embed(
            title=f"{self._get_attr('name', 'Unknown')}'s Overview",
            color=Color.gold()
        )

        # Core stats in compact format
        embed.add_field(
            name="HP", 
            value=self.get_hp_display(), 
            inline=True
        )
        embed.add_field(
            name="MP",
            value=f"`{self._get_attr('resources.current_mp', 0)}/{self._get_attr('resources.max_mp', 0)}`",
            inline=True
        )
        embed.add_field(
            name="AC",
            value=self.get_ac_display(),
            inline=True
        )

        # Other stats
        embed.add_field(
            name="Proficiency",
            value=f"`+{self._get_attr('base_proficiency', 0)}`",
            inline=True
        )
        embed.add_field(
            name="Spell Save DC",
            value=f"`{self._get_attr('spell_save_dc', 0)}`",
            inline=True
        )
        
        # Action stars (compact)
        current_stars = self._get_attr('action_stars.current_stars', 5)
        max_stars = self._get_attr('action_stars.max_stars', 5)
        
        embed.add_field(
            name="Action Stars",
            value=f"`{current_stars}/{max_stars}` {'⭐' * current_stars}{'⚫' * (max_stars - current_stars)}",
            inline=True
        )
        
        # Add active effects summary if any (instead of moveset info)
        effects = self._get_attr('effects', [])
        if effects:
            effect_count = len(effects)
            if effect_count > 0:
                embed.add_field(
                    name=f"Active Effects ({effect_count})",
                    value="See Status Effects tab for details",
                    inline=False
                )
        
        return embed

    async def _create_stats_embed(self) -> Embed:
            """Create the stats page embed"""
            embed = Embed(
                title=f"{self._get_attr('name', 'Unknown')}'s Stats",
                color=Color.blue()
            )
            
            # Get stats directly from character data
            if isinstance(self.character, dict):
                base_stats = {}
                modified_stats = {}
                for stat_data in self.character.get('stats', {}).get('base', {}):
                    # Convert from stored enum string back to value
                    stat_name = stat_data.split('.')[-1].lower()  # Get 'STRENGTH' from 'StatType.STRENGTH'
                    base_stats[stat_name] = self.character['stats']['base'][stat_data]
                    modified_stats[stat_name] = self.character['stats'].get('modified', {}).get(stat_data, base_stats[stat_name])
            else:
                # If character is an object
                base_stats = {
                    stat.name.lower(): value 
                    for stat, value in self.character.stats.base.items()
                }
                modified_stats = {
                    stat.name.lower(): value 
                    for stat, value in self.character.stats.modified.items()
                }
            
            # Format each stat category
            for stat_type in ['strength', 'dexterity', 'constitution', 'intelligence', 'wisdom', 'charisma']:
                base = base_stats.get(stat_type.lower(), 10)
                mod = modified_stats.get(stat_type.lower(), base)
                
                # Calculate modifiers
                base_mod = (base - 10) // 2
                current_mod = (mod - 10) // 2
                
                # Format display
                value = f"**Base:** {base} ({base_mod:+})"
                if base != mod:
                    value += f"\n**Current:** {mod} ({current_mod:+})"
                    
                embed.add_field(
                    name=stat_type.title(),
                    value=value,
                    inline=True
                )
                
            return embed

    async def _create_defense_embed(self) -> Embed:
        """Create the defenses page embed using DefenseHandler"""
        return DefenseHandler.create_defense_embed(self.character)

    async def _create_status_embed(self) -> Embed:
        """Create the status effects page embed using the StatusEffectHandler"""
        from .status_effects_handler import StatusEffectHandler
        
        embed = Embed(
            title=f"{self._get_attr('name', 'Unknown')}'s Status Effects",
            color=Color.gold()
        )
        
        effects = self._get_attr('effects', [])
        
        # Format all active effects
        if effects:
            effect_texts = StatusEffectHandler.format_effects(effects, self.character)
            if effect_texts:
                embed.description = "\n".join(effect_texts)
            else:
                embed.description = "No active status effects."
        else:
            embed.description = "No active effects."
        
        # Add special resources if any
        if self.character:  # Only add if we have a character object
            StatusEffectHandler.add_special_resources(embed, self.character)
        
        return embed

    async def _create_actions_embed(self) -> Embed:
        """Create the actions page using ActionHandler"""
        if self.action_handler:
            return self.action_handler.create_action_embed(self.character)
        
        # Fallback if ActionHandler not available
        from .action_handler import ActionHandler
        self.action_handler = ActionHandler(self.bot)
        return self.action_handler.create_action_embed(self.character)

    async def _create_moveset_embed(self) -> Embed:
        """Create moveset page with ActionHandler"""
        # If we have the action_handler, use it
        if self.action_handler and hasattr(self.character, 'list_moves'):
            # Check if there are any moves
            if self.character.list_moves():
                return self.action_handler.create_moves_embed(self.character)
        
        # Fallback for no moves or no action handler
        embed = Embed(
            title=f"{self._get_attr('name', 'Unknown')}'s Moveset",
            color=Color.greyple()
        )
        
        if hasattr(self.character, 'list_moves') and callable(getattr(self.character, 'list_moves')):
            moves = self.character.list_moves()
            if not moves:
                embed.description = "No moves found. Use `/move create` to add moves to this character."
            else:
                # Basic move list without fancy pagination
                moves_by_category = {}
                for name in moves:
                    move = self.character.get_move(name)
                    if move:
                        category = getattr(move, 'category', 'Other')
                        if category not in moves_by_category:
                            moves_by_category[category] = []
                        moves_by_category[category].append(move)
                
                for category, category_moves in moves_by_category.items():
                    move_lines = []
                    for move in category_moves:
                        cost_parts = []
                        if getattr(move, 'star_cost', 0) > 0:
                            cost_parts.append(f"⭐ {move.star_cost}")
                        if getattr(move, 'mp_cost', 0) > 0:
                            cost_parts.append(f"MP: {move.mp_cost}")
                            
                        cost_text = f" ({', '.join(cost_parts)})" if cost_parts else ""
                        move_lines.append(f"• {move.name}{cost_text}")
                        
                    if move_lines:
                        embed.add_field(
                            name=f"{category} Moves ({len(move_lines)})",
                            value="\n".join(move_lines),
                            inline=False
                        )
                
                embed.set_footer(text="Use '/move list' for interactive move management")
        else:
            embed.description = "Moveset system not available for this character."
        
        return embed

    async def _create_inventory_embed(self) -> Embed:
        """Placeholder for inventory page"""
        embed = Embed(
            title=f"{self._get_attr('name', 'Unknown')}'s Inventory",
            description="Inventory system coming soon!",
            color=Color.greyple()
        )
        return embed

class CharacterViewerUI(View):
    """UI component for the character viewer"""
    def __init__(self, viewer: CharacterViewer):
        super().__init__(timeout=None)
        self.viewer = viewer
        self._add_navigation()

    def _add_navigation(self) -> None:
        """Add navigation buttons"""
        # Row 1
        self.add_item(NavButton("Overview", "overview", 
                                ButtonStyle.primary if self.viewer.current_page == "overview" else ButtonStyle.secondary))
        self.add_item(NavButton("Stats", "stats", 
                                ButtonStyle.primary if self.viewer.current_page == "stats" else ButtonStyle.secondary))
        self.add_item(NavButton("Defenses", "defenses", 
                                ButtonStyle.primary if self.viewer.current_page == "defenses" else ButtonStyle.secondary))
        self.add_item(NavButton("Status Effects", "status", 
                                ButtonStyle.primary if self.viewer.current_page == "status" else ButtonStyle.secondary))
        
        # Row 2
        self.add_item(NavButton("Actions", "actions", 
                                ButtonStyle.primary if self.viewer.current_page == "actions" else ButtonStyle.secondary, row=1))
        self.add_item(NavButton("Moveset", "moveset", 
                                ButtonStyle.primary if self.viewer.current_page == "moveset" else ButtonStyle.secondary, row=1))
        self.add_item(NavButton("Inventory", "inventory", 
                                ButtonStyle.primary if self.viewer.current_page == "inventory" else ButtonStyle.secondary, row=1))

class NavButton(Button):
    """Navigation button for character viewer"""
    def __init__(self, 
                label: str, 
                page_id: str, 
                style: ButtonStyle = ButtonStyle.secondary,
                row: int = 0):
        super().__init__(
            label=label,
            style=style,
            row=row
        )
        self.page_id = page_id

    async def callback(self, interaction: Interaction) -> None:
        viewer = self.view.viewer  # type: CharacterViewer
        
        # Special handling for actions tab to use ActionHandler
        if self.page_id == "actions" and viewer.action_handler:
            # Get the action menu view
            from modules.menu.action_handler import ActionMenuView
            action_view = ActionMenuView(viewer.character, viewer.bot)
            
            # Create the embed
            embed = viewer.action_handler.create_action_embed(viewer.character)
            
            # Update the UI with highlighted button
            viewer.current_page = self.page_id
            for item in self.view.children:
                if isinstance(item, NavButton):
                    item.style = ButtonStyle.primary if item.page_id == self.page_id else ButtonStyle.secondary
            
            # Add the action selection menu to the current view
            current_view = CharacterViewerUI(viewer)
            
            # Update all button states first
            for item in current_view.children:
                if isinstance(item, NavButton) and item.page_id == self.page_id:
                    item.style = ButtonStyle.primary
            
            # Add action selector to the view
            current_view.add_item(action_view.action_select)
            
            # Update the message
            await interaction.response.edit_message(embed=embed, view=current_view)
            return
        
        # Special handling for moveset tab with ActionHandler
        if self.page_id == "moveset" and viewer.action_handler and hasattr(viewer.character, 'list_moves'):
            # Check if there are moves before showing the specialized view
            has_moves = False
            
            if hasattr(viewer.character, 'moveset') and hasattr(viewer.character.moveset, 'moves'):
                has_moves = bool(viewer.character.moveset.moves)
            elif hasattr(viewer.character, 'list_moves') and callable(getattr(viewer.character, 'list_moves')):
                has_moves = bool(viewer.character.list_moves())
                
            if has_moves:
                # Create the embed
                embed = viewer.action_handler.create_moves_embed(viewer.character)
                
                # Create the view
                from .action_handler import MovesetView
                view = MovesetView(viewer.character, handler=viewer.action_handler)
                view.viewer = viewer  # Set the viewer for back functionality
                
                # Update the message
                await interaction.response.edit_message(embed=embed, view=view)
                return
        
        # Default tab behavior
        viewer.current_page = self.page_id
        
        # Update button states
        for item in self.view.children:
            if isinstance(item, NavButton):
                item.style = ButtonStyle.primary if item.page_id == self.page_id else ButtonStyle.secondary
        
        # Update the view
        embed = await viewer.create_current_embed()
        await interaction.response.edit_message(embed=embed, view=self.view)