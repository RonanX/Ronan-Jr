"""
## src/modules/menu/action_handler.py

UI handler for displaying character action information.
Provides a simpler, more compatible interface for viewing and using moves.
"""

import discord
from discord import Embed, Color, ui, ButtonStyle, SelectOption
from typing import List, Optional, Dict, Any, Tuple, Callable
import asyncio
import logging

from core.character import Character
from modules.moves.data import MoveData

logger = logging.getLogger(__name__)

# Constants for pagination and UI
MOVES_PER_PAGE = 4
CATEGORIES = ["All", "Offense", "Utility", "Defense"]
DEFAULT_CATEGORY = "All"

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
                
            cost_text = " | ".join(costs) if costs else ""
            
            # Create select option
            options.append(
                SelectOption(
                    label=move.name[:25],  # Max 25 chars for label
                    description=f"{move.category} {cost_text}"[:50],  # Max 50 chars for description
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

class UseMoveView(ui.View):
    """View for selecting a move to use"""
    
    def __init__(self, character: Character, moves: List[MoveData], bot):
        super().__init__(timeout=60)
        self.character = character
        self.moves = moves
        self.bot = bot
        
        # Add move select menu
        self.move_select = MoveSelectMenu(
            moves, 
            placeholder="Select a move to use..."
        )
        
        # Define a callback for the move selection
        async def move_selected(interaction: discord.Interaction):
            # Get selected move
            try:
                move_idx = int(self.move_select.values[0])
                move = self.moves[move_idx]
                
                # Check resource costs first
                if self.character.resources.current_mp < move.mp_cost:
                    await interaction.response.send_message(
                        f"{self.character.name} doesn't have enough MP! (Needs {move.mp_cost}, has {self.character.resources.current_mp})",
                        ephemeral=True
                    )
                    return
                
                # Check action stars
                can_use_stars, stars_reason = self.character.can_use_move(move.star_cost)
                if not can_use_stars:
                    await interaction.response.send_message(
                        f"{self.character.name} can't use this move: {stars_reason}",
                        ephemeral=True
                    )
                    return
                
                # Get current round if in combat
                current_round = 1
                if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                    current_round = self.bot.initiative_tracker.round_number
                
                # Check if move is on cooldown first
                existing_cooldown = False
                for effect in self.character.effects:
                    if hasattr(effect, 'name') and effect.name == move.name and hasattr(effect, 'state'):
                        if effect.state == MoveState.COOLDOWN:
                            # There's already a cooldown effect for this move
                            phase = effect.phases.get(MoveState.COOLDOWN)
                            if phase:
                                remaining = phase.duration - phase.turns_completed
                                await interaction.response.send_message(
                                    f"{self.character.name} can't use {move.name}: On cooldown ({remaining} turns remaining)",
                                    ephemeral=True
                                )
                                return
                            existing_cooldown = True
                            break
                
                # Only check moveset cooldown if no active cooldown effect
                if not existing_cooldown:
                    # Check cooldowns in the move data
                    can_use, reason = move.can_use(current_round)
                    if not can_use:
                        await interaction.response.send_message(
                            f"{self.character.name} can't use {move.name}: {reason}",
                            ephemeral=True
                        )
                        return
                
                # Check if move needs a target
                if move.attack_roll or (move.damage and not move.save_type):
                    # Show target selector - get all possible targets
                    targets = []
                    
                    # Try to get characters from initiative tracker
                    if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                        turn_order = getattr(self.bot.initiative_tracker, 'turn_order', [])
                        for turn in turn_order:
                            if hasattr(turn, 'character_name'):
                                target_char = self.bot.game_state.get_character(turn.character_name)
                                if target_char and target_char.name != character.name:
                                    targets.append(target_char)
                    
                    # If no targets from initiative, try all characters
                    if not targets and hasattr(self.bot.game_state, 'get_all_characters'):
                        targets = [c for c in self.bot.game_state.get_all_characters() 
                                if c.name != character.name]
                    elif not targets and hasattr(self.bot.game_state, 'characters'):
                        # Alternative access through characters dictionary
                        targets = [c for name, c in self.bot.game_state.characters.items() 
                                if name != character.name]
                    
                    if targets:
                        # Create target options for dropdown
                        target_options = [
                            SelectOption(
                                label=target.name,
                                description=f"AC: {target.defense.current_ac}" if hasattr(target, 'defense') else ""
                            )
                            for target in targets[:25]  # Discord limits to 25 options
                        ]
                        
                        # Create target select menu
                        target_select = ui.Select(
                            placeholder="Select a target...",
                            options=target_options,
                            min_values=1,
                            max_values=1
                        )
                        
                        # Create view
                        target_view = ui.View(timeout=60)
                        
                        async def target_callback(target_interaction):
                            target_name = target_select.values[0]
                            
                            # Now execute the move with the target
                            await execute_move(target_interaction, move, target_name)
                            
                        target_select.callback = target_callback
                        target_view.add_item(target_select)
                        
                        # Show target selector
                        await interaction.response.send_message(
                            f"Select a target for {move.name}:",
                            view=target_view,
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            "No targets available. Add characters or start combat first.",
                            ephemeral=True
                        )
                else:
                    # Use move directly without a target
                    await execute_move(interaction, move)
            except (ValueError, IndexError) as e:
                logger.error(f"Error selecting move: {e}", exc_info=True)
                await interaction.response.send_message(
                    "Invalid move selection.",
                    ephemeral=True
                )
        
        # Set the callback and add the selection menu to the view
        self.move_select.callback = move_selected
        self.add_item(self.move_select)
        
        async def execute_move(interaction, move, target=None):
            """Execute a move with or without a target"""
            try:
                # Always defer first to avoid timeout
                try:
                    await interaction.response.defer()
                except:
                    # If already deferred, this will fail but we can continue
                    pass
                
                # Find the MoveCommands cog
                move_cog = None
                for cog_name, cog in self.bot.cogs.items():
                    if cog_name == "MoveCommands":
                        move_cog = cog
                        break
                
                if move_cog and hasattr(move_cog, 'use_move'):
                    # Direct call to the use_move method in the cog (preferred method)
                    try:
                        await move_cog.use_move(
                            interaction,
                            self.character.name,
                            move.name,
                            target
                        )
                        return
                    except Exception as e:
                        logger.error(f"Error directly calling use_move: {e}", exc_info=True)
                        # Continue to fallback
                
                # Fallback: Get the character and manually apply the move effect
                character = self.bot.game_state.get_character(self.character.name)
                if character:
                    # Get current round if in combat
                    current_round = 1
                    if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                        current_round = self.bot.initiative_tracker.round_number
                    
                    # Mark the move as used in moveset for cooldown tracking
                    move_data = character.get_move(move.name)
                    if move_data:
                        move_data.use(current_round)
                    
                    # Get target character if specified
                    target_char = None
                    if target:
                        target_char = self.bot.game_state.get_character(target)
                    
                    # Create a MoveEffect (don't force active state)
                    from core.effects.move import MoveEffect, MoveState, RollTiming
                    move_effect = MoveEffect(
                        name=move.name,
                        description=move.description,
                        mp_cost=move.mp_cost,
                        hp_cost=move.hp_cost,
                        star_cost=move.star_cost,
                        cast_time=move.cast_time,
                        duration=move.duration,
                        cooldown=move.cooldown,
                        attack_roll=move.attack_roll,
                        damage=move.damage,
                        crit_range=move.crit_range,
                        save_type=move.save_type,
                        save_dc=move.save_dc,
                        half_on_save=move.half_on_save,
                        roll_timing=move.roll_timing,
                        targets=[target_char] if target_char else [],
                        enable_heat_tracking=getattr(move, 'enable_heat_tracking', False)
                    )
                    
                    # Add the effect to the character & let the effect handle state transitions
                    result_message = character.add_effect(move_effect, current_round)
                    
                    # Use action stars
                    character.use_move_stars(move.star_cost, move.name)
                    
                    # If move has cooldown, explicitly register it with action_stars
                    if move.cooldown:
                        character.action_stars.start_cooldown(move.name, move.cooldown)
                    
                    # Save character
                    await self.bot.db.save_character(character, debug_paths=['effects', 'action_stars'])
                    
                    # Send success message directly to the channel (use the formatted message from MoveEffect)
                    if interaction.channel:
                        await interaction.channel.send(result_message)
                    else:
                        # Fallback to followup if no channel
                        await interaction.followup.send(result_message)
                else:
                    # Character not found
                    await interaction.followup.send(
                        f"❌ Character '{self.character.name}' not found.",
                        ephemeral=True
                    )
                    
            except Exception as e:
                logger.error(f"Error executing move: {e}", exc_info=True)
                # Handle error directly instead of using handle_error function
                error_embed = discord.Embed(
                    title="Error Using Move",
                    description=f"An error occurred: {str(e)}",
                    color=discord.Color.red()
                )
                
                try:
                    await interaction.followup.send(embed=error_embed, ephemeral=True)
                except:
                    # Last resort if all else fails
                    print(f"Critical error executing move: {e}")
                    
class TargetSelectView(ui.View):
    """View for selecting a target for a move"""
    
    def __init__(self, character: Character, move: MoveData, bot):
        super().__init__(timeout=60)
        self.character = character
        self.move = move
        self.bot = bot
        
        # Get potential targets
        targets = []
        
        try:
            if hasattr(bot, 'initiative_tracker') and bot.initiative_tracker.state != 'inactive':
                # Get characters in current initiative
                for turn in bot.initiative_tracker.turn_order:
                    target_char = bot.game_state.get_character(turn.character_name)
                    if target_char and target_char.name != character.name:
                        targets.append(target_char)
            else:
                # Get all characters as potential targets
                targets = [c for c in bot.game_state.get_all_characters() 
                           if c.name != character.name]
        except Exception as e:
            logger.error(f"Error getting targets: {e}", exc_info=True)
            targets = []
            
        # Add target select menu if we have targets
        if targets:
            self.target_select = ui.Select(
                placeholder="Select a target...",
                options=[
                    SelectOption(
                        label=target.name,
                        description=f"AC: {target.defense.current_ac}"
                    )
                    for target in targets[:25]  # Discord limits to 25 options
                ],
                min_values=1,
                max_values=1
            )
            
            async def target_selected(interaction: discord.Interaction):
                # Get selected target
                target_name = self.target_select.values[0]
                
                # Use move with target
                try:
                    move_cog = self.bot.get_cog('MoveCommands')
                    if move_cog:
                        await interaction.response.defer()
                        await move_cog.use_move(
                            interaction,
                            self.character.name,
                            self.move.name,
                            target_name
                        )
                    else:
                        await interaction.response.send_message(
                            "Move system is not available. Please try again later.",
                            ephemeral=True
                        )
                except Exception as e:
                    logger.error(f"Error using move with target: {e}", exc_info=True)
                    await interaction.response.send_message(
                        f"Error using move: {str(e)}",
                        ephemeral=True
                    )
                    
            self.target_select.callback = target_selected
            self.add_item(self.target_select)
            
        else:
            # No targets available
            self.add_item(ui.Button(
                label="No targets available",
                disabled=True
            ))

class MoveInfoView(ui.View):
    """View for displaying move info"""
    
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
        
        async def move_selected(interaction: discord.Interaction):
            # Get selected move
            try:
                move_idx = int(self.move_select.values[0])
                move = self.moves[move_idx]
                
                # Show move info
                info_embed = self.handler.create_move_info_embed(self.character, move)
                await interaction.response.send_message(
                    embed=info_embed,
                    ephemeral=True
                )
            except (ValueError, IndexError) as e:
                await interaction.response.send_message(
                    "Invalid move selection.",
                    ephemeral=True
                )
                
        self.move_select.callback = move_selected
        self.add_item(self.move_select)

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
        
        # Show standard action costs
        embed.add_field(
            name="Standard Actions",
            value=(
                "🔹 **Basic Attack** (⭐)\n"
                "🔹 **Dodge** (⭐⭐)\n"
                "🔹 **Dash** (⭐)\n"
                "🔹 **Help** (⭐)\n"
                "🔹 **Disengage** (⭐)"
            ),
            inline=False
        )
        
        # Show placeholder for full move system
        embed.set_footer(text="Use the Moveset tab to view and use character moves")
        
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
                costs.append(f"💙 +{abs(move.mp_cost)} MP")
            if move.hp_cost > 0:
                costs.append(f"❤️ HP: {move.hp_cost}")
            elif move.hp_cost < 0:
                costs.append(f"❤️ +{abs(move.hp_cost)} HP")
                
            cost_text = " | ".join(costs)
            
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
            value=move.category,
            inline=True
        )
        
        # Add costs
        costs = []
        if move.star_cost > 0:
            costs.append(f"⭐ {move.star_cost} stars")
        if move.mp_cost > 0:
            costs.append(f"💙 {move.mp_cost} MP")
        elif move.mp_cost < 0:
            costs.append(f"💙 Restores {abs(move.mp_cost)} MP")
        if move.hp_cost > 0:
            costs.append(f"❤️ {move.hp_cost} HP")
        elif move.hp_cost < 0:
            costs.append(f"❤️ Heals {abs(move.hp_cost)} HP")
            
        if costs:
            embed.add_field(
                name="Costs",
                value="\n".join(costs),
                inline=True
            )
            
        # Add timing info
        timing = []
        if move.cast_time:
            timing.append(f"Cast Time: {move.cast_time} turn(s)")
        if move.duration:
            timing.append(f"Duration: {move.duration} turn(s)")
        if move.cooldown:
            timing.append(f"Cooldown: {move.cooldown} turn(s)")
            
        if timing:
            embed.add_field(
                name="Timing",
                value="\n".join(timing),
                inline=True
            )
            
        # Add combat info
        combat = []
        if move.attack_roll:
            combat.append(f"Attack Roll: {move.attack_roll}")
        if move.damage:
            combat.append(f"Damage: {move.damage}")
        if move.save_type:
            save_text = f"Save: {move.save_type.upper()}"
            if move.save_dc:
                save_text += f" (DC {move.save_dc})"
            if move.half_on_save:
                save_text += " (Half damage on save)"
            combat.append(save_text)
        if move.crit_range != 20:
            combat.append(f"Crit Range: {move.crit_range}-20")
            
        if combat:
            embed.add_field(
                name="Combat",
                value="\n".join(combat),
                inline=False
            )
            
        # Add usage info
        usage = []
        if move.uses is not None:
            uses_text = f"Uses: {move.uses}"
            if move.uses_remaining is not None:
                uses_text = f"Uses: {move.uses_remaining}/{move.uses}"
            usage.append(uses_text)
            
        # Check cooldown status
        if move.cooldown and move.last_used_round:
            current_round = 1  # Default
            if hasattr(self.bot, 'initiative_tracker') and self.bot.initiative_tracker.state != 'inactive':
                current_round = self.bot.initiative_tracker.round_number
                
            if move.last_used_round >= current_round - move.cooldown:
                rounds_left = move.cooldown - (current_round - move.last_used_round)
                usage.append(f"On Cooldown: {rounds_left} round(s) remaining")
                
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