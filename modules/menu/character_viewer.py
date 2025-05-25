"""
src/modules/menu/character_viewer.py

Main class to handle character information display and interaction.
Enhanced with improved stats display for active effects.
"""

import discord
from discord import Interaction, Embed, ButtonStyle, Color, SelectOption
from discord.ui import View, Button, Select
from typing import Optional, Dict, Any, List, Tuple

from core.character import Character, StatType
from modules.menu.defense_handler import DefenseHandler

class CharacterViewer:
    """Main class to handle character information display and interaction."""
    def __init__(self, character: Any):
        self.character = character
        self.current_view: Optional[View] = None
        self.current_page = "overview"
        self.action_handler = None
        self.bot = None
        self.debug_mode = False  # Set to True to enable debug output

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
        """Create the overview page embed with enhanced stat display"""
        embed = Embed(
            title=f"{self._get_attr('name', 'Unknown')}'s Overview",
            color=Color.gold()
        )

        # Core stats in compact format with visual enhancement for modified stats
        # HP with visual bar and temp HP visualization
        hp_current = self._get_attr('resources.current_hp', 0)
        hp_max = self._get_attr('resources.max_hp', 100)
        hp_temp = self._get_attr('resources.current_temp_hp', 0)
        
        # Calculate percentages for visualization - ensure accurate scaling
        hp_percent = min(10, max(0, int((hp_current / hp_max) * 10))) if hp_max > 0 else 0
        
        # Temp HP should be proportional to max HP for display
        temp_percent_of_max = min(1.0, hp_temp / hp_max) if hp_max > 0 else 0
        temp_blocks = max(1, min(10, int(temp_percent_of_max * 10))) if hp_temp > 0 else 0
        
        # Determine if temp HP fits in the main bar or needs overflow
        remaining_blocks = 10 - hp_percent
        temp_in_main = min(remaining_blocks, temp_blocks)
        temp_overflow = max(0, temp_blocks - temp_in_main)
        
        # Create base HP bar
        hp_bar = "🟩" * hp_percent
        
        # Add temp HP as white blocks in the remaining space
        if temp_in_main > 0:
            hp_bar += "⬜" * temp_in_main
            
        # Fill the rest with empty blocks
        hp_bar += "⬛" * (10 - hp_percent - temp_in_main)
        
        # If temp HP exceeds the remaining space, show overflow bar
        if temp_overflow > 0:
            temp_bar = "⬜" * temp_overflow + "⬛" * (10 - temp_overflow)
            hp_display = f"{self.get_hp_display()}\n{hp_bar}\n{temp_bar} ← Temp HP"
        else:
            hp_display = f"{self.get_hp_display()}\n{hp_bar}"
        
        embed.add_field(
            name="HP", 
            value=hp_display, 
            inline=True
        )
        
        # MP with visual bar
        mp_current = self._get_attr('resources.current_mp', 0)
        mp_max = self._get_attr('resources.max_mp', 100)
        mp_percent = int((mp_current / mp_max) * 10) if mp_max > 0 else 0
        mp_bar = "🟦" * mp_percent + "⬛" * (10 - mp_percent)
        
        embed.add_field(
            name="MP",
            value=f"`{mp_current}/{mp_max}`\n{mp_bar}",
            inline=True
        )
        
        # Enhanced AC display
        embed.add_field(
            name="AC",
            value=self.get_ac_display(),
            inline=True
        )

        # Other stats with enhanced visual formatting
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
        
        # Action stars with visual display
        current_stars = self._get_attr('action_stars.current_stars', 5)
        max_stars = self._get_attr('action_stars.max_stars', 5)
        star_display = "⭐" * current_stars + "⚫" * (max_stars - current_stars)
        
        embed.add_field(
            name="Action Stars",
            value=f"`{current_stars}/{max_stars}`\n{star_display}",
            inline=True
        )
        
        # ENHANCED: Ability Scores Summary (Compact)
        # Show any modified ability scores with indicators
        has_modified = False
        modified_stats = []
        
        for stat_type in ['strength', 'dexterity', 'constitution', 'intelligence', 'wisdom', 'charisma']:
            base = self._get_base_stat(stat_type)
            mod = self._get_modified_stat(stat_type)
            
            if base != mod:
                has_modified = True
                base_mod = (base - 10) // 2
                current_mod = (mod - 10) // 2
                mod_change = current_mod - base_mod
                
                # Visual indicator for increase/decrease
                indicator = "🔼" if mod_change > 0 else "🔽"
                stat_abbr = stat_type[:3].upper()
                
                modified_stats.append(f"{stat_abbr} {mod} ({current_mod:+}) {indicator}")
        
        if has_modified:
            embed.add_field(
                name="Modified Abilities",
                value=" • ".join(modified_stats),
                inline=False
            )
        
        # Add active effects summary if any
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
        """
        Create the stats page embed with enhanced display for modified stats.
        Improved to show clean, visually appealing stat modifications with color-coded segments.
        """
        embed = Embed(
            title=f"{self._get_attr('name', 'Unknown')}'s Abilities",
            color=Color.blue(),
            description="**Ability Scores** with modifiers and active effects."
        )
        
        # Format each stat with a cleaner, more visual approach
        for stat_type in ['strength', 'dexterity', 'constitution', 'intelligence', 'wisdom', 'charisma']:
            # Get base and modified values
            base = self._get_base_stat(stat_type)
            mod = self._get_modified_stat(stat_type)
            
            # Get all effects that modify this stat
            stat_effects = self._get_stat_effects_for_type(stat_type)
            total_effect = sum(effect[2] for effect in stat_effects)
            
            # Calculate modifiers (base and modified)
            base_mod = (base - 10) // 2
            current_mod = (mod - 10) // 2
            
            # Format display with visual indicators
            if base != mod:
                # There's a modification
                mod_diff = mod - base
                
                # Determine appropriate sign
                sign = "+" if mod_diff > 0 else ""
                
                # Create a color-coded visual bar to represent the stat
                stat_bar = self._create_color_coded_stat_bar(base, mod, 30)
                
                # Format for display effects
                effect_text = ""
                if stat_effects:
                    effect_parts = []
                    for name, _, amount, _ in stat_effects:
                        effect_sign = "+" if amount > 0 else ""
                        effect_parts.append(f"{name} ({effect_sign}{amount})")
                    if effect_parts:
                        effect_text = "\n" + " • ".join(effect_parts)
                
                # Format the display with correct values
                value = (
                    f"**Score:** `{base}` → `{mod}` ({sign}{mod_diff})\n"
                    f"**Modifier:** `{base_mod:+}` → `{current_mod:+}`\n"
                    f"{stat_bar}{effect_text}"
                )
            else:
                # No modification - simpler display
                stat_bar = self._create_color_coded_stat_bar(base, base, 30)
                value = (
                    f"**Score:** `{base}`\n"
                    f"**Modifier:** `{base_mod:+}`\n"
                    f"{stat_bar}"
                )
                
            embed.add_field(
                name=stat_type.title(),
                value=value,
                inline=True
            )
        
        # Add a section for passive scores
        passive_perception = 10 + self._get_stat_modifier('wisdom')
        passive_insight = 10 + self._get_stat_modifier('wisdom')
        passive_investigation = 10 + self._get_stat_modifier('intelligence')
        
        embed.add_field(
            name="Passive Scores",
            value=(
                f"**Perception:** `{passive_perception}`\n"
                f"**Insight:** `{passive_insight}`\n"
                f"**Investigation:** `{passive_investigation}`"
            ),
            inline=False
        )
        
        # Add active stat effects if any
        stat_effects = self._get_stat_effects()
        if stat_effects:
            effects_text = []
            for effect_name, stat_type, amount, duration in stat_effects:
                sign = "+" if amount > 0 else ""
                duration_text = "" if duration is None else f" ({duration})"
                effects_text.append(f"• {effect_name}: {stat_type.title()} {sign}{amount}{duration_text}")
            
            embed.add_field(
                name="Active Stat Effects",
                value="\n".join(effects_text) if effects_text else "None",
                inline=False
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
        
    def _get_base_stat(self, stat_type: str) -> int:
        """Get base value for a stat"""
        # Try using StatManager if available (most reliable)
        if hasattr(self.character, 'stat_manager'):
            try:
                # Try to convert string to enum
                from core.effects.stat import StatType
                enum_stat = StatType(stat_type)
                
                # Get base value from stat manager
                return self.character.stat_manager._get_base_value(enum_stat)
            except (ImportError, ValueError, AttributeError):
                # Continue with fallback methods
                pass
        
        # First try to get from StatType enum if dealing with a Character object
        if not isinstance(self.character, dict):
            # If character has a proper Stats object with StatType enum keys
            if hasattr(self.character, 'stats') and hasattr(self.character.stats, 'base'):
                # Try finding via direct enum lookup
                try:
                    # Import StatType if available
                    from core.character import StatType
                    # Find matching enum and use as key
                    try:
                        enum_stat = StatType(stat_type)
                        if enum_stat in self.character.stats.base:
                            return self.character.stats.base[enum_stat]
                    except (ValueError, KeyError):
                        # Try a string search if direct lookup fails
                        for key, value in self.character.stats.base.items():
                            if isinstance(key, StatType) and key.value == stat_type:
                                return value
                except ImportError:
                    # StatType not available, continue with fallback
                    pass
                    
                # Fallback to string comparison for both key types
                for key, value in self.character.stats.base.items():
                    # Get string representation of key
                    key_str = getattr(key, 'value', str(key)).lower()
                    if key_str == stat_type.lower():
                        return value
        
        # Dictionary-based approach for both object and dict character representations 
        if isinstance(self.character, dict):
            # Try to get from base stats dict structure
            stats = self.character.get('stats', {}).get('base', {})
            for key, value in stats.items():
                if key.lower() == stat_type.lower():
                    return value
                    
        # Default fallback
        return 10
    
    def _get_modified_stat(self, stat_type: str) -> int:
        """Get modified value for a stat"""
        # First try to use StatManager to look up the most current state
        if hasattr(self.character, 'stat_manager'):
            try:
                # Try to convert string to enum
                from core.effects.stat import StatType
                enum_stat = StatType(stat_type)
                
                # Get base value
                base_value = self.character.stat_manager._get_base_value(enum_stat)
                
                # Get total modifier
                modifier = self.character.stat_manager.get_total_modifier(enum_stat)
                
                # Return base + modifier
                return base_value + modifier
            except (ImportError, ValueError, AttributeError):
                # Continue with fallback methods
                pass
        
        # First try to get from StatType enum if dealing with a Character object
        if not isinstance(self.character, dict):
            # If character has a proper Stats object with StatType enum keys
            if hasattr(self.character, 'stats') and hasattr(self.character.stats, 'modified'):
                # Try finding via direct enum lookup
                try:
                    # Import StatType if available
                    from core.character import StatType
                    # Find matching enum and use as key
                    try:
                        enum_stat = StatType(stat_type)
                        if enum_stat in self.character.stats.modified:
                            return self.character.stats.modified[enum_stat]
                    except (ValueError, KeyError):
                        # Try a string search if direct lookup fails
                        for key, value in self.character.stats.modified.items():
                            if isinstance(key, StatType) and key.value == stat_type:
                                return value
                except ImportError:
                    # StatType not available, continue with fallback
                    pass
                    
                # Fallback to string comparison for both key types
                for key, value in self.character.stats.modified.items():
                    # Get string representation of key
                    key_str = getattr(key, 'value', str(key)).lower()
                    if key_str == stat_type.lower():
                        return value
        
        # Dictionary-based approach
        if isinstance(self.character, dict):
            # Try to get from modified stats
            stats = self.character.get('stats', {}).get('modified', {})
            for key, value in stats.items():
                if key.lower() == stat_type.lower():
                    return value
        
        # If no modified stat found, fall back to base stat
        return self._get_base_stat(stat_type)
    
    def _get_stat_modifier(self, stat_type: str) -> int:
        """Calculate modifier for a stat"""
        value = self._get_modified_stat(stat_type)
        return (value - 10) // 2
    
    def _create_color_coded_stat_bar(self, base_value: int, modified_value: int, max_width: int = 20) -> str:
        """
        Create a visual bar representing stat strength with color coding.
        Green for base value, yellow for buffs, red for debuffs.
        
        Args:
            base_value: The base stat value
            modified_value: The modified stat value
            max_width: Maximum width of the bar
        
        Returns:
            Formatted color-coded bar string
        """
        # Scale values for representation
        max_stat = 30  # Cap at 30 for display purposes
        
        # Calculate the net difference - this is the key value!
        net_diff = modified_value - base_value
        
        # Log the values for debugging
        if self.debug_mode:
            print(f"STAT BAR: Base={base_value}, Modified={modified_value}, Net Diff={net_diff}")
            # Also print stat effects if available
            for effect in self._get_stat_effects_for_type(self._get_current_stat_type()):
                print(f"  - Effect: {effect[0]}, Amount: {effect[2]}")
        
        # Create clear visualization based on the net effect
        if net_diff == 0:  # No change - all green
            base_blocks = int((min(base_value, max_stat) / max_stat) * max_width)
            bar = "🟩" * base_blocks + "⬛" * (max_width - base_blocks)
        
        elif net_diff > 0:  # Net positive - use green base + yellow buff
            # Calculate scaled portions
            base_blocks = int((min(base_value, max_stat) / max_stat) * max_width)
            buff_blocks = int((min(net_diff, max_stat - base_value) / max_stat) * max_width)
            buff_blocks = max(1, buff_blocks)  # Always show at least 1 block for visibility
            
            # Create bar
            bar = "🟩" * base_blocks + "🟨" * buff_blocks
            bar += "⬛" * (max_width - len(bar))
            
        else:  # Net negative - use green for remaining + red for debuff
            # For debuffs, we show the modified value in green and the lost value in red
            remaining_blocks = int((min(modified_value, max_stat) / max_stat) * max_width)
            debuff_blocks = int((min(abs(net_diff), base_value) / max_stat) * max_width)
            debuff_blocks = max(1, debuff_blocks)  # Always show at least 1 block
            
            # Create bar
            bar = "🟩" * remaining_blocks + "🟥" * debuff_blocks
            bar += "⬛" * (max_width - len(bar))
        
        return bar
        
    def _get_current_stat_type(self) -> str:
        """Helper to determine which stat type is currently being processed"""
        # Check call stack to determine context
        import inspect
        frame = inspect.currentframe()
        try:
            while frame:
                if 'stat_type' in frame.f_locals:
                    return frame.f_locals['stat_type']
                frame = frame.f_back
            return "unknown"
        finally:
            del frame  # Always delete frame reference
            
    def _get_stat_effects_for_type(self, stat_type: str) -> List[Tuple[str, str, int, Optional[str]]]:
        """Get all effects that modify a specific stat type"""
        all_effects = self._get_stat_effects()
        return [effect for effect in all_effects if effect[1].lower() == stat_type.lower()]
    
    def _get_stat_effects(self) -> List[Tuple[str, str, int, Optional[str]]]:
        """Get all active stat effects on the character"""
        effects = self._get_attr('effects', [])
        stat_effects = []
        
        for effect in effects:
            if isinstance(effect, dict):
                # Dictionary form
                if 'type' in effect and effect['type'] == 'StatEffect':
                    name = effect.get('name', 'Unknown Effect')
                    stat_type = effect.get('stat_type', 'unknown')
                    amount = effect.get('amount', 0)
                    
                    # Determine duration text
                    duration_text = None
                    if effect.get('permanent', False):
                        duration_text = "Permanent"
                    elif 'duration' in effect:
                        duration = effect['duration']
                        if duration == 1:
                            duration_text = "1 turn"
                        else:
                            duration_text = f"{duration} turns"
                    
                    stat_effects.append((name, stat_type, amount, duration_text))
            else:
                # Object form
                if hasattr(effect, 'type') and effect.type == 'StatEffect':
                    name = getattr(effect, 'name', 'Unknown Effect')
                    
                    # Handle different ways stat_type might be stored
                    stat_type = getattr(effect, 'stat_type', None)
                    if hasattr(stat_type, 'value'):
                        stat_type = stat_type.value
                    elif stat_type is None:
                        stat_type = 'unknown'
                    
                    amount = getattr(effect, 'amount', 0)
                    
                    # Determine duration text
                    duration_text = None
                    if getattr(effect, 'permanent', False):
                        duration_text = "Permanent"
                    elif hasattr(effect, 'duration'):
                        duration = effect.duration
                        if duration == 1:
                            duration_text = "1 turn"
                        else:
                            duration_text = f"{duration} turns"
                    
                    stat_effects.append((name, stat_type, amount, duration_text))
        
        return stat_effects

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