"""
## src/modules/menu/action_handler.py

UI handler for displaying character action information.
Provides a simpler, more compatible interface for viewing and using moves.
"""

import discord
from discord import ui, app_commands, Embed, Color, ButtonStyle
import logging
from typing import List, Optional, Any, Dict, Callable, Union, Tuple

import asyncio
import json
import re

from core.character import Character
from modules.moves.data import MoveData
from utils.action_costs import STANDARD_ACTIONS, get_action_info
from utils.stat_helper import StatHelper, StatType

logger = logging.getLogger(__name__)

# Constants for pagination and UI
MOVES_PER_PAGE = 4
CATEGORIES = ["All", "Offense", "Utility", "Defense"]
DEFAULT_CATEGORY = "All"

class ActionSelectMenu(ui.Select):
    """Select menu for choosing an action"""
    
    def __init__(self, placeholder: str = "Select an action..."):
        # Create options for standard actions
        options = [
            discord.SelectOption(
                label="Basic Attack",
                description="Make a basic attack (⭐1)",
                value="basic_attack",
                emoji="⚔️"
            ),
            discord.SelectOption(
                label="Dodge",
                description="Attacks against you have disadvantage (⭐2)",
                value="dodge",
                emoji="🛡️"
            ),
            discord.SelectOption(
                label="Dash",
                description="Double your movement speed (⭐1)",
                value="dash",
                emoji="🏃"
            ),
            discord.SelectOption(
                label="Disengage",
                description="Avoid opportunity attacks (⭐1)",
                value="disengage",
                emoji="↪️"
            ),
            discord.SelectOption(
                label="Help",
                description="Give advantage to an ally (⭐1)",
                value="help",
                emoji="🤝"
            ),
            discord.SelectOption(
                label="Hide",
                description="Attempt to hide (⭐1)",
                value="hide",
                emoji="👁️"
            )
        ]
        
        super().__init__(
            placeholder=placeholder,
            options=options,
            min_values=1,
            max_values=1
        )

class ActionMenuView(ui.View):
    """View for selecting a standard action to perform"""
    
    def __init__(self, character: Character, bot):
        super().__init__(timeout=60)
        self.character = character
        self.bot = bot
        
        # Add action select menu
        self.action_select = ActionSelectMenu(placeholder="Select an action...")
        
        # Define a callback for the action selection
        async def action_selected(interaction: discord.Interaction):
            action_key = self.action_select.values[0]
            
            if action_key == "basic_attack":
                # Show basic attack form
                await interaction.response.send_modal(
                    BasicAttackForm(self.character, self.bot)
                )
            else:
                # Handle standard action
                await self.execute_standard_action(interaction, action_key)
        
        # Set the callback and add the selection menu to the view
        self.action_select.callback = action_selected
        self.add_item(self.action_select)
    
    async def execute_standard_action(self, interaction: discord.Interaction, action_key: str):
        """Execute a standard action directly"""
        try:
            # Get action info
            action_info = get_action_info(action_key)
            if not action_info:
                await interaction.response.send_message(
                    f"Error: Action '{action_key}' not found.",
                    ephemeral=True
                )
                return
                
            # Check if character has enough stars
            can_use, reason = self.character.can_use_move(action_info.star_cost, action_info.name)
            if not can_use:
                await interaction.response.send_message(
                    f"Cannot use {action_info.name}: {reason}",
                    ephemeral=True
                )
                return
            
            # Defer the response to avoid timeout
            await interaction.response.defer(ephemeral=True)
            
            # Direct approach using manager with improved error handling
            from core.effects.move import MoveEffect
            from core.effects.manager import apply_effect
            
            # Get character from game state
            character = self.bot.game_state.get_character(self.character.name)
            if not character:
                await interaction.followup.send("Character not found", ephemeral=True)
                return
            
            # Get current round
            current_round = 1
            if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                current_round = self.bot.initiative_tracker.round_number
            
            # Create temporary move effect
            move_effect = MoveEffect(
                name=action_info.name,
                description=action_info.description,
                star_cost=action_info.star_cost,
                mp_cost=0,
                hp_cost=0,
                duration=0,
                cooldown=0
            )
            
            # Apply the effect
            character.use_move_stars(action_info.star_cost, action_info.name)
            result = await apply_effect(character, move_effect, current_round)
            
            # Save character
            await self.bot.db.save_character(character)
            
            # Send result
            await interaction.followup.send(result)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error executing standard action: {e}", exc_info=True)
            
            # Handle error
            await interaction.followup.send(
                f"An error occurred: {str(e)}",
                ephemeral=True
            )

class BasicAttackForm(ui.Modal, title="Basic Attack"):
    """Form for configuring a basic attack"""
    
    target = ui.TextInput(
        label="Target(s)",
        placeholder="Enter target name(s), separated by commas",
        required=True
    )
    
    attack_type = ui.TextInput(
        label="Attack Type",
        placeholder="melee or magic",
        default="melee",
        required=True
    )
    
    attack_power = ui.TextInput(
        label="Attack Power Level (1-5)",
        placeholder="1=d4, 2=d6, 3=d8, 4=2d4, 5=2d6",
        default="1",
        required=True,
        max_length=1
    )
    
    damage_type = ui.TextInput(
        label="Damage Type",
        placeholder="slashing, piercing, fire, force, etc.",
        required=False
    )
    
    reason = ui.TextInput(
        label="Description (optional)",
        placeholder="What does your attack look like?",
        required=False,
        max_length=100
    )
    
    def __init__(self, character: Character, bot):
        super().__init__()
        self.character = character
        self.bot = bot
        
        # Set damage type defaults based on attack type
        self.damage_type.default = "slashing"
        
        # Calculate available attack powers based on modifiers
        if hasattr(self.character, 'stats'):
            # Get the strength mod for melee
            str_mod = StatHelper.get_stat_modifier(self.character, StatType.STRENGTH)
            
            # Get the higher of INT or WIS for magic
            int_mod = StatHelper.get_stat_modifier(self.character, StatType.INTELLIGENCE)
            wis_mod = StatHelper.get_stat_modifier(self.character, StatType.WISDOM)
            magic_mod = max(int_mod, wis_mod)
            
            # Calculate max levels
            max_melee_level = min(5, max(1, str_mod + 2))
            max_magic_level = min(5, max(1, magic_mod + 2))
            
            # Update the label to show available levels
            self.attack_power.label = f"Attack Power (Melee:1-{max_melee_level}, Magic:1-{max_magic_level})"
            
            # Update the placeholder to show available levels
            self.attack_power.placeholder = f"Melee(1-{max_melee_level}), Magic(1-{max_magic_level})"
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Get form values
            targets = self.target.value.strip()
            attack_type = self.attack_type.value.lower().strip()
            
            # Validate attack type
            if attack_type not in ["melee", "magic"]:
                await interaction.followup.send(
                    "Invalid attack type. Please use 'melee' or 'magic'.",
                    ephemeral=True
                )
                return
            
            # Validate and convert power level to integer
            try:
                power_level = int(self.attack_power.value.strip())
                if power_level < 1 or power_level > 5:
                    await interaction.followup.send(
                        "Attack power must be between 1 and 5.",
                        ephemeral=True
                    )
                    return
            except ValueError:
                await interaction.followup.send(
                    "Invalid attack power. Please enter a number between 1 and 5.",
                    ephemeral=True
                )
                return
                
            # Get damage type or use default
            damage_type = self.damage_type.value.strip() if self.damage_type.value else ""
            reason = self.reason.value.strip()
            
            # Default damage types if none provided
            if not damage_type:
                damage_type = "slashing" if attack_type == "melee" else "force"
            
            # Determine modifier and calculation
            from utils.stat_helper import StatHelper, StatType
            
            if attack_type == "melee":
                mod_name = "str"
                mod_value = StatHelper.get_stat_modifier(self.character, StatType.STRENGTH)
                
                # Check if power level exceeds character's capability
                max_melee_level = min(5, max(1, mod_value + 2))
                if power_level > max_melee_level:
                    await interaction.followup.send(
                        f"Your strength only allows up to level {max_melee_level} melee attacks.",
                        ephemeral=True
                    )
                    return
            else:  # magic
                # Use the higher of INT or WIS
                int_mod = StatHelper.get_stat_modifier(self.character, StatType.INTELLIGENCE)
                wis_mod = StatHelper.get_stat_modifier(self.character, StatType.WISDOM)
                if int_mod >= wis_mod:
                    mod_name = "int"
                    mod_value = int_mod
                else:
                    mod_name = "wis"
                    mod_value = wis_mod
                    
                # Check if power level exceeds character's capability
                max_magic_level = min(5, max(1, mod_value + 2))
                if power_level > max_magic_level:
                    await interaction.followup.send(
                        f"Your spellcasting ability only allows up to level {max_magic_level} magic attacks.",
                        ephemeral=True
                    )
                    return
            
            # Set damage based on selected power level
            if power_level == 1:
                damage = f"1d4+{mod_name}"
            elif power_level == 2:
                damage = f"1d6+{mod_name}"
            elif power_level == 3:
                damage = f"1d8+{mod_name}"
            elif power_level == 4:
                damage = f"2d4+{mod_name}"
            else:  # power_level == 5
                damage = f"2d6+{mod_name}"
            
            # Add damage type
            damage = f"{damage} {damage_type}"
            
            # Set attack name
            attack_name = reason if reason else "Basic Attack"
            
            # Get character and target from game state
            character = self.bot.game_state.get_character(self.character.name)
            if not character:
                await interaction.followup.send("Character not found", ephemeral=True)
                return
            
            # Get targets
            target_chars = []
            if targets:
                for target_name in targets.split(','):
                    target_name = target_name.strip()
                    target_char = self.bot.game_state.get_character(target_name)
                    if target_char:
                        target_chars.append(target_char)
                    else:
                        await interaction.followup.send(f"Target not found: {target_name}", ephemeral=True)
                        return
            
            # Get current round
            current_round = 1
            if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                current_round = self.bot.initiative_tracker.round_number
            
            # Import needed modules
            from core.effects.move import MoveEffect
            from core.effects.manager import apply_effect  # Import apply_effect directly
            
            # Create the move effect
            move_effect = MoveEffect(
                name=attack_name,
                description=f"A {attack_type} attack" + (f": {reason}" if reason else ""),
                star_cost=1,  # Basic attacks cost 1 star
                mp_cost=0,
                hp_cost=0,
                attack_roll=f"1d20+{mod_name}",
                damage=damage,
                targets=target_chars,
                roll_timing="instant",
                # Don't include additional text about stars
            )
            
            # Use action stars
            character.use_move_stars(1, attack_name)
            
            # Apply the effect directly
            result = await apply_effect(character, move_effect, current_round)
            
            # Save character
            await self.bot.db.save_character(character)
            
            # Save targets if needed
            for target_char in target_chars:
                await self.bot.db.save_character(target_char)
                
            # Send result
            await interaction.followup.send(result)
        
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error processing basic attack: {e}", exc_info=True)
            
            # Handle error
            await interaction.followup.send(
                f"Error processing basic attack: {str(e)}",
                ephemeral=True
            )

class MovesetView(ui.View):
    """View for the moveset display with category filters and pagination"""
    
    def __init__(self, character: Character, category: str = DEFAULT_CATEGORY, page: int = 0, handler = None):
        super().__init__(timeout=180)  # 3 minute timeout
        self.character = character
        self.category = category.lower()
        self.page = page
        self.handler = handler
        self.viewer = None  # Will be set if we're in character viewer context
        
        # Get all moves
        self.all_moves = []
        if hasattr(character, 'moveset') and hasattr(character.moveset, 'moves'):
            self.all_moves = list(character.moveset.moves.values())
        elif hasattr(character, 'list_moves') and callable(getattr(character, 'list_moves')):
            move_names = character.list_moves()
            for name in move_names:
                move = character.get_move(name)
                if move:
                    self.all_moves.append(move)
                    
        # Filter by category
        self.filtered_moves = self._filter_moves()
        self.max_pages = max(1, (len(self.filtered_moves) + MOVES_PER_PAGE - 1) // MOVES_PER_PAGE)
        
        # Build the UI
        self._build_view()
        
    def _filter_moves(self) -> List[MoveData]:
        """Filter moves based on selected category"""
        if self.category == "all":
            # Return all moves
            return self.all_moves
            
        # Filter by category with fallback for moves without categories
        return [
            move for move in self.all_moves 
            if getattr(move, 'category', '').lower() == self.category
        ]
    
    def _build_view(self):
        """Build the complete view with all UI elements"""
        # Clear any existing items
        self.clear_items()
        
        # Add category buttons (row 0)
        for i, cat in enumerate(CATEGORIES):
            selected = cat.lower() == self.category
            button = ui.Button(
                style=ButtonStyle.primary if selected else ButtonStyle.secondary,
                label=cat,
                custom_id=f"category:{cat.lower()}",
                row=0
            )
            
            # Set category button callback
            async def make_category_callback(interaction, cat=cat):
                self.category = cat.lower()
                self.filtered_moves = self._filter_moves()
                self.max_pages = max(1, (len(self.filtered_moves) + MOVES_PER_PAGE - 1) // MOVES_PER_PAGE)
                self.page = 0  # Reset to first page
                self._build_view()
                
                # Update embed too
                embed = self.handler.create_moves_embed(
                    self.character, 
                    self.page, 
                    self.category
                )
                await interaction.response.edit_message(embed=embed, view=self)
                
            button.callback = make_category_callback
            self.add_item(button)
            
        # Add action buttons (row 1)
        if self.filtered_moves:
            # Get only moves on the current page
            start_idx = self.page * MOVES_PER_PAGE
            current_page_moves = self.filtered_moves[start_idx:start_idx + MOVES_PER_PAGE]
            
            if current_page_moves:
                # Add Use Move button
                use_button = ui.Button(
                    style=ButtonStyle.primary,
                    label="Use Move",
                    row=1
                )
                
                async def use_move_callback(interaction):
                    # Only show moves from the current page
                    bot = self.handler.bot if self.handler else None
                    use_move_view = UseMoveView(self.character, current_page_moves, bot)
                    await interaction.response.send_message(
                        "Select a move to use:",
                        view=use_move_view,
                        ephemeral=True
                    )
                    
                use_button.callback = use_move_callback
                self.add_item(use_button)
                
                # Add Info button
                info_button = ui.Button(
                    style=ButtonStyle.secondary,
                    label="Move Info",
                    row=1
                )
                
                async def info_callback(interaction):
                    await interaction.response.send_message(
                        "Select a move for details:",
                        view=MoveInfoView(self.character, current_page_moves, self.handler),
                        ephemeral=True
                    )
                    
                info_button.callback = info_callback
                self.add_item(info_button)
                
                # Add Back button if in character viewer context
                back_button = ui.Button(
                    style=ButtonStyle.secondary,
                    label="Back to Overview",
                    row=1
                )
                
                async def back_callback(interaction):
                    # Go back to character overview
                    from modules.menu.character_viewer import CharacterViewer
                    
                    # Try to use existing viewer if we have one
                    if self.viewer:
                        viewer = self.viewer
                    else:
                        # Create new viewer
                        viewer = CharacterViewer(self.character)
                        if self.handler and hasattr(self.handler, 'bot'):
                            viewer.bot = self.handler.bot
                            viewer.action_handler = self.handler
                    
                    # Set page to overview
                    viewer.current_page = "overview"
                    
                    # Create view
                    from modules.menu.character_viewer import CharacterViewerUI
                    view = CharacterViewerUI(viewer)
                    
                    # Get embed
                    embed = await viewer.create_current_embed()
                    
                    # Update message
                    await interaction.response.edit_message(embed=embed, view=view)
                
                back_button.callback = back_callback
                self.add_item(back_button)
        
        # Add pagination controls if needed (row 2)
        if self.max_pages > 1:
            # Previous page button
            prev_button = ui.Button(
                style=ButtonStyle.secondary,
                label="◀",
                disabled=(self.page <= 0),
                row=2
            )
            
            async def prev_callback(interaction):
                if self.page > 0:
                    self.page -= 1
                    self._build_view()
                    
                    # Update embed too
                    embed = self.handler.create_moves_embed(
                        self.character, 
                        self.page, 
                        self.category
                    )
                    await interaction.response.edit_message(embed=embed, view=self)
                    
            prev_button.callback = prev_callback
            self.add_item(prev_button)
            
            # Page indicator (non-interactive)
            page_indicator = ui.Button(
                style=ButtonStyle.secondary,
                label=f"{self.page + 1}/{self.max_pages}",
                disabled=True,
                row=2
            )
            self.add_item(page_indicator)
            
            # Next page button
            next_button = ui.Button(
                style=ButtonStyle.secondary,
                label="▶",
                disabled=(self.page >= self.max_pages - 1),
                row=2
            )
            
            async def next_callback(interaction):
                if self.page < self.max_pages - 1:
                    self.page += 1
                    self._build_view()
                    
                    # Update embed too
                    embed = self.handler.create_moves_embed(
                        self.character, 
                        self.page, 
                        self.category
                    )
                    await interaction.response.edit_message(embed=embed, view=self)
                    
            next_button.callback = next_callback
            self.add_item(next_button)

class ActionHandler:
    """Handles display of action-related information and moves"""
    
    def __init__(self, bot = None):
        self.bot = bot
    
    @staticmethod
    def create_action_embed(character: Character) -> Embed:
        """Create embed showing action information"""
        embed = Embed(
            title=f"{character.name}'s Actions",
            description="Select an action to perform:",
            color=Color.blue()
        )

        # Star display
        current_stars = getattr(character.action_stars, 'current_stars', 5)
        max_stars = getattr(character.action_stars, 'max_stars', 5)
        
        # Create visual star meter
        filled_stars = "⭐" * current_stars
        empty_stars = "⚫" * (max_stars - current_stars)
        star_meter = f"{filled_stars}{empty_stars}"
        
        embed.add_field(
            name="Action Stars",
            value=f"`{current_stars}/{max_stars}`\n{star_meter}",
            inline=False
        )

        # Show any used moves
        used_moves = getattr(character.action_stars, 'used_moves', {})
        if used_moves:
            moves_list = []
            for move, cooldown in used_moves.items():
                moves_list.append(f"• {move} - Cooldown: {cooldown} round(s)")
                
            embed.add_field(
                name="Used Moves",
                value="\n".join(moves_list),
                inline=False
            )
            
        # Add available attack levels based on modifiers
        from utils.stat_helper import StatHelper, StatType
        
        str_mod = StatHelper.get_stat_modifier(character, StatType.STRENGTH)
        int_mod = StatHelper.get_stat_modifier(character, StatType.INTELLIGENCE)
        wis_mod = StatHelper.get_stat_modifier(character, StatType.WISDOM)
        
        melee_level = min(5, max(1, str_mod + 2))
        magic_level = min(5, max(1, max(int_mod, wis_mod) + 2))
        
        embed.add_field(
            name="Combat Abilities",
            value=(
                f"**Melee Attack:** Level `{melee_level}` (up to "
                f"`{ActionHandler._level_to_dice(melee_level)}`)\n"
                f"**Magic Attack:** Level `{magic_level}` (up to "
                f"`{ActionHandler._level_to_dice(magic_level)}`)"
            ),
            inline=False
        )
        
        # Show damage type examples
        embed.add_field(
            name="Common Damage Types",
            value=(
                "**Physical:** `slashing`, `piercing`, `bludgeoning`\n"
                "**Elemental:** `fire`, `ice`, `electric`, `water`, `wind`, `sonic`\n"
                "**Energy:** `radiant`, `necrotic`, `force`, `psychic`, `thunder`\n"
                "**Chemical:** `acid`, `poison`"
            ),
            inline=False
        )
        
        # Show standard action costs
        embed.add_field(
            name="Standard Actions",
            value=(
                "🔹 **Basic Attack** (`⭐1`)\n"
                "🔹 **Dodge** (`⭐2`)\n"
                "🔹 **Dash** (`⭐1`)\n"
                "🔹 **Help** (`⭐1`)\n"
                "🔹 **Disengage** (`⭐1`)\n"
                "🔹 **Hide** (`⭐1`)"
            ),
            inline=False
        )
        
        return embed
    
    def create_moves_embed(self, character: Character, page: int = 0, 
                            category: str = DEFAULT_CATEGORY) -> Embed:
        """Create embed showing character moves with pagination and categories"""
        # Get all moves
        all_moves = []
        if hasattr(character, 'moveset') and hasattr(character.moveset, 'moves'):
            all_moves = list(character.moveset.moves.values())
        elif hasattr(character, 'list_moves') and callable(getattr(character, 'list_moves')):
            move_names = character.list_moves()
            for name in move_names:
                move = character.get_move(name)
                if move:
                    all_moves.append(move)
                    
        # Filter by category
        filtered_moves = all_moves
        if category.lower() != "all":
            filtered_moves = [
                move for move in all_moves 
                if getattr(move, 'category', '').lower() == category.lower()
            ]
                
        # Calculate pagination
        total_moves = len(filtered_moves)
        max_pages = max(1, (total_moves + MOVES_PER_PAGE - 1) // MOVES_PER_PAGE)
        page = min(page, max_pages - 1) if max_pages > 0 else 0
        
        # Create the embed
        embed = Embed(
            title=f"{character.name}'s Moveset",
            description=f"Category: **{category}** • Page {page + 1}/{max_pages}",
            color=Color.blue()
        )
        
        # Star display (compact)
        current_stars = getattr(character.action_stars, 'current_stars', 5)
        max_stars = getattr(character.action_stars, 'max_stars', 5)
        embed.add_field(
            name="Action Stars",
            value=f"{current_stars}/{max_stars} {'⭐' * current_stars}{'⚫' * (max_stars - current_stars)}",
            inline=False
        )
        
        # Display moves for current page
        start_idx = page * MOVES_PER_PAGE
        page_moves = filtered_moves[start_idx:start_idx + MOVES_PER_PAGE]
        
        for move in page_moves:
            # Format move info
            name = move.name
            
            # Create cost text
            costs = []
            if move.star_cost > 0:
                costs.append(f"⭐{move.star_cost}")
            if move.mp_cost > 0:
                costs.append(f"💙 MP: {move.mp_cost}")
            elif move.mp_cost < 0:
                # Show MP gain with a + sign
                costs.append(f"💙 +{abs(move.mp_cost)} MP")
            if move.hp_cost > 0:
                costs.append(f"❤️ HP: {move.hp_cost}")
            elif move.hp_cost < 0:
                # Show healing with a + sign
                costs.append(f"❤️ +{abs(move.hp_cost)} HP")
                
            cost_text = " | ".join(costs) if costs else ""
            
            # Create timing info text
            timing_info = []
            if move.cast_time and move.cast_time > 0:
                timing_info.append(f"🔄 {move.cast_time}T Cast")
            if move.duration and move.duration > 0:
                timing_info.append(f"⏳ {move.duration}T Duration")
            if move.cooldown and move.cooldown > 0:
                timing_info.append(f"⌛ {move.cooldown}T Cooldown")
                
            timing_text = " | ".join(timing_info)
            
            # Create status text
            status = []
            if move.cooldown and move.last_used_round:
                # Check if on cooldown
                current_round = 1  # Default
                if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                    current_round = self.bot.initiative_tracker.round_number
                    
                if move.last_used_round >= current_round - move.cooldown:
                    rounds_left = move.cooldown - (current_round - move.last_used_round)
                    status.append(f"Cooldown: {rounds_left} round(s)")
                    
            if move.uses is not None:
                uses_left = move.uses_remaining if move.uses_remaining is not None else move.uses
                status.append(f"Uses: {uses_left}/{move.uses}")
                
            status_text = " | ".join(status) if status else "Ready"
            
            # Category label
            category_text = f"[{move.category}]" if move.category else ""
            
            # Create the field with bold name and category
            field_name = f"**{name} {category_text}**"
            field_value = []
            
            # Add costs with single backticks
            if cost_text:
                field_value.append(f"`{cost_text}`")
            else:
                field_value.append("`No cost`")
                
            # Add timing info with single backticks
            if timing_text:
                field_value.append(f"`{timing_text}`")
            
            # Create the description block with triple backticks
            description_block = []
            
            # Add description
            if move.description:
                if ';' in move.description:
                    # Split by semicolons and join with newlines
                    parts = []
                    for part in move.description.split(';'):
                        part = part.strip()
                        if part:
                            parts.append(part)
                    if parts:
                        description_block.extend(parts)
                else:
                    description_block.append(move.description)
            
            # Add empty line as separator if we have both description and combat info
            if description_block and (move.attack_roll or move.damage):
                description_block.append("")
            
            # Add combat info if applicable
            combat_info = []
            if move.attack_roll:
                combat_info.append(f"Attack: {move.attack_roll}")
            if move.damage:
                combat_info.append(f"Damage: {move.damage}")
                
            if combat_info:
                combat_text = " | ".join(combat_info)
                description_block.append(f"• {combat_text}")
            
            # Add empty line before status
            if description_block:
                description_block.append("")
                
            # Add status at the end
            description_block.append(f"Status: {status_text}")
            
            # Format with triple backticks
            if description_block:
                field_value.append(f"```\n{chr(10).join(description_block)}\n```")
            
            embed.add_field(
                name=field_name,
                value="\n".join(field_value),
                inline=False
            )
            
        # Add info if no moves found
        if not page_moves:
            if total_moves == 0:
                if category.lower() == "all":
                    embed.add_field(
                        name="No Moves Found",
                        value="This character has no moves. Use `/move create` to add moves.",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="No Moves Found",
                        value=f"No {category} moves found. Choose another category or use `/move create` to add moves.",
                        inline=False
                    )
            else:
                embed.add_field(
                    name="Page Empty",
                    value="This page has no moves. Navigate to another page.",
                    inline=False
                )
                
        return embed
    
    def create_move_info_embed(self, character: Character, move: MoveData) -> Embed:
        """Create detailed embed for a specific move"""
        embed = Embed(
            title=f"{move.name}",
            description=move.description.replace(';', '\n• ') if move.description else "No description",
            color=Color.blue()
        )
        
        # Add move metadata
        embed.add_field(
            name="Category",
            value=getattr(move, 'category', 'Uncategorized'),
            inline=True
        )
        
        # Add costs
        costs = []
        if getattr(move, 'star_cost', 0) > 0:
            costs.append(f"⭐ {move.star_cost} stars")
        if getattr(move, 'mp_cost', 0) > 0:
            costs.append(f"💙 {move.mp_cost} MP")
        elif getattr(move, 'mp_cost', 0) < 0:
            costs.append(f"💙 Restores {abs(move.mp_cost)} MP")
        if getattr(move, 'hp_cost', 0) > 0:
            costs.append(f"❤️ {move.hp_cost} HP")
        elif getattr(move, 'hp_cost', 0) < 0:
            costs.append(f"❤️ Heals {abs(move.hp_cost)} HP")
            
        if costs:
            embed.add_field(
                name="Costs",
                value="\n".join(costs),
                inline=True
            )
            
        # Add timing info
        timing = []
        if getattr(move, 'cast_time', None) and move.cast_time > 0:
            timing.append(f"🔄 Cast Time: {move.cast_time} turn(s)")
        if getattr(move, 'duration', None) and move.duration > 0:
            timing.append(f"⏳ Duration: {move.duration} turn(s)")
        if getattr(move, 'cooldown', None) and move.cooldown > 0:
            timing.append(f"⌛ Cooldown: {move.cooldown} turn(s)")
            
        if timing:
            embed.add_field(
                name="Timing",
                value="\n".join(timing),
                inline=True
            )
            
        # Add combat info
        combat = []
        if getattr(move, 'attack_roll', None):
            combat.append(f"Attack Roll: {move.attack_roll}")
        if getattr(move, 'damage', None):
            combat.append(f"Damage: {move.damage}")
        
        # Safely check for save_type attribute
        if hasattr(move, 'save_type') and move.save_type:
            save_text = f"Save: {move.save_type.upper()}"
            if hasattr(move, 'save_dc') and move.save_dc:
                save_text += f" (DC {move.save_dc})"
            if hasattr(move, 'half_on_save') and move.half_on_save:
                save_text += " (Half damage on save)"
            combat.append(save_text)
        
        if hasattr(move, 'crit_range') and move.crit_range != 20:
            combat.append(f"Crit Range: {move.crit_range}-20")
            
        if combat:
            embed.add_field(
                name="Combat",
                value="\n".join(combat),
                inline=False
            )
            
        # Add usage info
        usage = []
        if hasattr(move, 'uses') and move.uses is not None:
            uses_text = f"Uses: {move.uses}"
            if hasattr(move, 'uses_remaining') and move.uses_remaining is not None:
                uses_text = f"Uses: {move.uses_remaining}/{move.uses}"
            usage.append(uses_text)
            
        # Check cooldown status
        if hasattr(move, 'cooldown') and move.cooldown and hasattr(move, 'last_used_round') and move.last_used_round:
            current_round = 1  # Default
            if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                current_round = self.bot.initiative_tracker.round_number
                
            if move.last_used_round >= current_round - move.cooldown:
                rounds_left = move.cooldown - (current_round - move.last_used_round)
                usage.append(f"On Cooldown: {rounds_left} turn(s) remaining")
                
        if usage:
            embed.add_field(
                name="Usage",
                value="\n".join(usage),
                inline=False
            )
            
        return embed
    
    async def show_moves(self, interaction: discord.Interaction, character: Character):
        """Show a paginated view of a character's moves"""
        try:
            # Check if character has moves
            has_moves = False
            
            if hasattr(character, 'moveset') and hasattr(character.moveset, 'moves'):
                has_moves = bool(character.moveset.moves)
            elif hasattr(character, 'list_moves') and callable(getattr(character, 'list_moves')):
                has_moves = bool(character.list_moves())
                
            if not has_moves:
                # No moves found
                embed = Embed(
                    title=f"{character.name}'s Moveset",
                    description=f"{character.name} has no moves. Use `/move create` to add moves.",
                    color=Color.blue()
                )
                await interaction.followup.send(embed=embed)
                return
                
            # Create the embed
            embed = self.create_moves_embed(character)
            
            # Create the view
            view = MovesetView(character, handler=self)
            
            # Send the message
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"Error showing moves: {e}", exc_info=True)
            await interaction.followup.send(
                f"Error showing moves: {str(e)}",
                ephemeral=True
            )

    async def show_action_menu(self, interaction: discord.Interaction, character: Character):
        """Show the action menu for a character"""
        try:
            # Create the action menu view
            view = ActionMenuView(character, self.bot)
            
            # Create the embed
            embed = self.create_action_embed(character)
            
            # Show the action menu (edit message if followup, otherwise send new response)
            if interaction.response.is_done():
                await interaction.edit_original_message(embed=embed, view=view)
            else:
                await interaction.response.edit_message(embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"Error showing action menu: {e}", exc_info=True)
            # Handle response based on whether response is already done
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Error showing action menu: {str(e)}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"Error showing action menu: {str(e)}",
                    ephemeral=True
                )
    
    @staticmethod
    def _level_to_dice(level: int) -> str:
        """Convert a level to dice notation"""
        if level == 1:
            return "d4"
        elif level == 2:
            return "d6"
        elif level == 3:
            return "d8"
        elif level == 4:
            return "2d4"
        else:  # level 5
            return "2d6"

class MoveSelectMenu(ui.Select):
    """Select menu for choosing a move"""
    
    def __init__(
        self, 
        moves: List[MoveData], 
        placeholder: str = "Select a move...",
        max_options: int = 25
    ):
        # Create options from moves
        options = []
        for i, move in enumerate(moves[:max_options]):
            # Create cost indicator
            costs = []
            if move.star_cost > 0:
                costs.append(f"⭐{move.star_cost}")
            if move.mp_cost > 0:
                costs.append(f"MP:{move.mp_cost}")
            elif move.mp_cost < 0:
                # Show MP gain with a + sign
                costs.append(f"MP:+{abs(move.mp_cost)}")
            if move.hp_cost > 0:
                costs.append(f"HP:{move.hp_cost}")
            elif move.hp_cost < 0:
                # Show healing with a + sign
                costs.append(f"HP:+{abs(move.hp_cost)}")
                
            cost_text = " | ".join(costs) if costs else ""
            
            # Add uses info if available
            uses_text = ""
            if move.uses is not None:
                uses_remaining = move.uses_remaining if hasattr(move, 'uses_remaining') and move.uses_remaining is not None else move.uses
                uses_text = f" | Uses:{uses_remaining}/{move.uses}"
            
            # Create category text
            category_text = move.category if hasattr(move, 'category') and move.category else ""
            
            # Create description with costs, uses, and category
            description = category_text
            if cost_text:
                description += f" | {cost_text}"
            if uses_text:
                description += uses_text
                
            # Truncate description if too long
            if len(description) > 50:
                description = description[:47] + "..."
            
            # Create select option
            options.append(
                discord.SelectOption(
                    label=move.name[:25],  # Max 25 chars for label
                    description=description,  # Include all info
                    value=str(i)  # Use index as value
                )
            )
        
        # Create the select menu
        super().__init__(
            placeholder=placeholder,
            options=options[:25],  # Discord limits to 25 options
            min_values=1,
            max_values=1
        )

class TargetSelectMenu(discord.ui.Select):
    """Select menu for choosing multiple targets"""
    def __init__(self, bot, available_targets, min_values=1, max_values=10):
        self.bot = bot
        
        # Create options from available targets
        options = [
            discord.SelectOption(label=target.name, value=target.name)
            for target in available_targets[:25]  # Discord limit
        ]
        
        # If no targets available, add a placeholder option
        if not options:
            options = [discord.SelectOption(label="No targets available", value="none")]
        
        super().__init__(
            placeholder="Select target(s)...",
            min_values=min_values if options and options[0].value != "none" else 0,
            max_values=min(max_values, len(options)) if options and options[0].value != "none" else 0,
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle selection of targets"""
        # Store the selected targets in the VIEW (not in self)
        view = self.view
        view.selected_targets = self.values
        
        # Update the message to show selected targets
        targets_text = ", ".join(self.values) if self.values else "None"
        
        embed = interaction.message.embeds[0]
        
        # Update the embed with selected targets
        for i, field in enumerate(embed.fields):
            if field.name == "Selected Targets":
                embed.set_field_at(i, name="Selected Targets", value=targets_text, inline=False)
                break
        else:
            # Field not found, add it
            embed.clear_fields()
            embed.add_field(name="Selected Targets", value=targets_text, inline=False)
        
        # Use the parent view, not self
        await interaction.response.edit_message(embed=embed, view=view)

class UseMoveView(discord.ui.View):
    """View for selecting a move to use"""
    def __init__(self, character, moves_list, bot, timeout=60):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.character = character
        self.moves_list = moves_list
        self.selected_move = None
        self.selected_targets = []
        self.force_during = False
        
        # Add initial move selection components
        self.move_select = MoveSelectMenu(
            self.moves_list,
            placeholder="Select a move..."
        )
        self.add_item(self.move_select)
        
        # Explicitly set the callback for move selection
        self.move_select.callback = self.move_selected_callback

    async def move_selected_callback(self, interaction: discord.Interaction):
        """Callback for when a move is selected"""
        try:
            # Get the selected move index
            move_idx = int(self.move_select.values[0])
            self.selected_move = self.moves_list[move_idx]
            
            # Format description with bullet points if it contains semicolons
            description = getattr(self.selected_move, 'description', 'No description available')
            if description and ';' in description:
                formatted_description = "• " + description.replace(';', '\n• ')
            else:
                formatted_description = description
            
            # Create embed with move info
            embed = Embed(
                title=f"Using {self.selected_move.name}",
                description=formatted_description,
                color=Color.blue()
            )
            
            # Add options field
            embed.add_field(
                name="Options",
                value=f"During Own Turn: {'Yes' if self.force_during else 'No'}",
                inline=False
            )
            
            # Add instructions field
            embed.add_field(
                name="Instructions",
                value="1. Use 'Select Targets' if this move affects other characters\n"
                      "2. Toggle 'During Turn' if needed\n"
                      "3. Click 'Execute' when ready to use the move",
                inline=False
            )
            
            await interaction.response.edit_message(embed=embed, view=self)
            
        except (ValueError, IndexError) as e:
            logger.error(f"Error selecting move: {e}", exc_info=True)
            await interaction.response.send_message(
                f"Error selecting move: {str(e)}",
                ephemeral=True
            )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure that the interaction comes from any valid user"""
        # Allow all interactions since we can't check owner_id
        return True

    async def on_timeout(self):
        """Disable the view on timeout"""
        for item in self.children:
            item.disabled = True
            
        # Only attempt to edit message if we've stored it
        if hasattr(self, 'message') and self.message:
            try:
                await self.message.edit(view=self)
            except discord.errors.NotFound:
                pass  # Message might have been deleted
        
    @discord.ui.button(label="Select Targets", style=discord.ButtonStyle.primary, row=1)
    async def select_targets_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open target selection dialog"""
        if not self.selected_move:
            await interaction.response.send_message(
                "Please select a move first!",
                ephemeral=True
            )
            return
            
        # Get all characters as potential targets
        available_targets = list(self.bot.game_state.characters.values())
        
        # Create a temporary view for target selection
        target_view = discord.ui.View(timeout=60)
        target_select = TargetSelectMenu(self.bot, available_targets, min_values=1, max_values=10)
        target_view.add_item(target_select)
        
        # Add done button with callback
        done_button = discord.ui.Button(
            label="Done", 
            style=discord.ButtonStyle.success
        )
        
        # Create a reference to self (the original view)
        original_view = self
        
        async def done_callback(done_interaction: discord.Interaction):
            # Store the selected targets from the target selection menu
            if hasattr(target_select, 'values') and target_select.values:
                # Update the original view's selected targets
                original_view.selected_targets = target_select.values
                
                targets_text = ", ".join(original_view.selected_targets)
                
                # Visual feedback
                await done_interaction.response.send_message(
                    f"✅ **Targets selected:** {targets_text}\n\n"
                    f"Return to the move selection and click **Execute** when ready.",
                    ephemeral=True
                )
                
                # Also update the original message if possible
                try:
                    # Get original embed
                    if interaction.message and interaction.message.embeds:
                        embed = interaction.message.embeds[0]
                        
                        # Update or add targets field
                        targets_field_index = -1
                        for i, field in enumerate(embed.fields):
                            if field.name == "Selected Targets":
                                targets_field_index = i
                                break
                                
                        if targets_field_index >= 0:
                            embed.set_field_at(
                                targets_field_index,
                                name="Selected Targets",
                                value=targets_text,
                                inline=False
                            )
                        else:
                            embed.add_field(
                                name="Selected Targets",
                                value=targets_text,
                                inline=False
                            )
                            
                        # Try to update original message (may fail due to Discord limitations)
                        try:
                            await interaction.edit_original_response(embed=embed, view=original_view)
                        except:
                            # If we can't update original, at least we showed confirmation
                            pass
                except Exception as e:
                    # Don't fail if we can't update the original message
                    logger.error(f"Error updating original message with targets: {e}")
            else:
                await done_interaction.response.send_message(
                    "No targets selected. Please select at least one target.",
                    ephemeral=True
                )
        
        # Attach the callback to the done button
        done_button.callback = done_callback
        target_view.add_item(done_button)
        
        # Create embed for target selection
        embed = discord.Embed(
            title="Target Selection",
            description=f"Select targets for {self.selected_move.name}",
            color=discord.Color.blue()
        )
        
        # Add a field for currently selected targets if any
        if self.selected_targets:
            embed.add_field(
                name="Currently Selected",
                value=", ".join(self.selected_targets),
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, view=target_view, ephemeral=True)

    @discord.ui.button(label="Toggle During Turn", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_during_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle the force_during option"""
        self.force_during = not self.force_during
        button.label = f"During Turn: {'Yes' if self.force_during else 'No'}"
        
        # Create a new embed or update existing one
        try:
            embeds = interaction.message.embeds
            embed = embeds[0] if embeds and len(embeds) > 0 else None
        except (IndexError, AttributeError):
            embed = None
            
        if not embed:
            # Format description with bullet points if it contains semicolons
            description = getattr(self.selected_move, 'description', 'No description available') if self.selected_move else "Select a move to use"
            if self.selected_move and description and ';' in description:
                formatted_description = "• " + description.replace(';', '\n• ')
            else:
                formatted_description = description
            
            # Create a new basic embed
            embed = Embed(
                title="Move Selection" if not self.selected_move else f"Using {self.selected_move.name}",
                description=formatted_description,
                color=Color.blue()
            )
        
        # Find or update options field
        options_field_index = -1
        for i, field in enumerate(embed.fields):
            if field.name == "Options":
                options_field_index = i
                break
                
        options_text = f"During Own Turn: {'Yes' if self.force_during else 'No'}"
        
        if options_field_index >= 0:
            embed.set_field_at(options_field_index, name="Options", value=options_text, inline=False)
        else:
            embed.add_field(name="Options", value=options_text, inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Execute", style=discord.ButtonStyle.success, row=2)
    async def execute_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Execute the selected move with the specified targets and options"""
        if not self.selected_move:
            await interaction.response.send_message(
                "Please select a move first!",
                ephemeral=True
            )
            return
            
        # Defer response to allow for longer processing time
        await interaction.response.defer(ephemeral=True)
        
        # Execute the move
        await self.execute_move(interaction, self.selected_move, self.selected_targets, self.force_during)

    async def execute_move(self, interaction, move, targets=None, force_during=False):
        """Execute a move with or without a target"""
        try:
            # The interaction has already been responded to by the execute_button method
            # No need to defer again - just use followup messages
            
            # Get character from game state
            character = self.bot.game_state.get_character(self.character.name)
            if not character:
                await interaction.followup.send("Character not found", ephemeral=True)
                return
                
            # Get target characters
            target_chars = []
            if targets:
                for target_name in targets:
                    target_char = self.bot.game_state.get_character(target_name)
                    if target_char:
                        target_chars.append(target_char)
            
            # Format target string for the command
            target_str = ", ".join(t.name for t in target_chars) if target_chars else None
            
            # Get current round
            current_round = 1
            if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                current_round = self.bot.initiative_tracker.round_number
                
            # Import needed modules
            from core.effects.move import MoveEffect
            from core.effects.manager import apply_effect
            
            # Create the effect
            move_effect = MoveEffect(
                name=move.name,
                description=move.description,
                mp_cost=move.mp_cost,
                hp_cost=move.hp_cost,
                star_cost=move.star_cost,
                cast_time=getattr(move, 'cast_time', None),
                duration=getattr(move, 'duration', None),
                cooldown=getattr(move, 'cooldown', None),
                attack_roll=getattr(move, 'attack_roll', None),
                damage=getattr(move, 'damage', None),
                crit_range=getattr(move, 'crit_range', 20),
                roll_timing=getattr(move, 'roll_timing', 'active'),
                targets=target_chars,
                bonus_on_hit=getattr(move, 'bonus_on_hit', None),
                aoe_mode=getattr(move, 'aoe_mode', 'single'),
                force_during=force_during
            )
            
            # IMPORTANT: Do NOT deduct stars here - let apply_effect handle ALL resource costs
            # Remove this line to avoid double-charging stars:
            # character.use_move_stars(move.star_cost, move.name)
            
            # Apply the effect - this will handle all resource costs internally
            result = await apply_effect(character, move_effect, current_round)
            
            # Mark as used
            if hasattr(move, 'use'):
                move.use(current_round)
            
            # Save character
            await self.bot.db.save_character(character)
            
            # Save targets if needed
            for target_char in target_chars:
                await self.bot.db.save_character(target_char)
                
            # Process any pending async operations
            if hasattr(move_effect, 'execute_pending_operations'):
                additional_messages = await move_effect.execute_pending_operations()
                if additional_messages:
                    if isinstance(additional_messages, list):
                        result += "\n" + "\n".join(additional_messages)
                    else:
                        result += "\n" + additional_messages
            
            # Send a confirmation to the user (ephemeral)
            await interaction.followup.send(f"Executing {move.name}...", ephemeral=True)
            
            # Send the actual result to the channel directly (public)
            await interaction.channel.send(result)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error executing move: {e}", exc_info=True)
            
            # Handle error (keep ephemeral)
            await interaction.followup.send(
                f"Error executing move: {str(e)}",
                ephemeral=True
            )

class MoveInfoView(ui.View):
    """View for showing move info"""
    def __init__(self, character: Character, moves: List[MoveData], handler):
        super().__init__(timeout=60)
        self.character = character
        self.moves = moves
        self.handler = handler
        
        # Add move select menu
        self.move_select = MoveSelectMenu(
            moves, 
            placeholder="Select a move for details..."
        )
        
        # Define a callback for the selection
        async def move_selected(interaction: discord.Interaction):
            try:
                # Get selected move
                move_idx = int(self.move_select.values[0])
                move = self.moves[move_idx]
                
                # Create an embed with move details
                embed = self.handler.create_move_info_embed(self.character, move)
                
                # Show the details
                await interaction.response.send_message(
                    embed=embed,
                    ephemeral=True
                )
            except (ValueError, IndexError) as e:
                logger.error(f"Error showing move info: {e}", exc_info=True)
                await interaction.response.send_message(
                    f"Error showing move info: {str(e)}",
                    ephemeral=True
                )
                
        # Set the callback and add the selection menu to the view
        self.move_select.callback = move_selected
        self.add_item(self.move_select)

    async def character_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for character names"""
        try:
            # Use proper async method instead of direct dict access
            char_names = await self.bot.db.list_characters()
            
            return [
                app_commands.Choice(name=name, value=name)
                for name in char_names
                if current.lower() in name.lower()
            ][:25]  # Discord limits to 25 choices
        except Exception as e:
            logger.warning(f"Character autocomplete error: {e}")
            return []  # Return empty list as fallback