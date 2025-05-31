"""
Initiative tracking system for combat with character linking support. Handles turn order, 
effect processing, and combat state management with improved message formatting.

FIXED: Removed duplicate move effect processing that was causing effects to appear twice.
Move effects inherit from BaseEffect and are already processed by the regular effect system.

Key Features:
- Turn-based combat management
- Effect processing and timing with character linking (NO DUPLICATE PROCESSING)
- Progress bar visualization
- Formatted message output
- Effect feedback message handling
- Linked character effect processing during parent turns
- Safeguards to prevent child characters in initiative

IMPLEMENTATION MANDATES:
- Use CombatLogger for ALL combat events
- Process effects in correct order (start -> end -> expire)
- Always save character state after effect processing
- Use MessageFormatter for ALL output
- Track both temporary and permanent effect states
- Handle effect cleanup properly on combat end
- Process linked children effects during parent character turns
- ONLY USE ONE EFFECT PROCESSING SYSTEM (no duplicates)
"""

from typing import List, Dict, Optional, Tuple
import discord
from discord.ext import commands
import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum

from core.character import Character, StatType
from core.state import CombatLogger, CombatEventType
from core.effects.manager import process_effects_with_linking  # Base effects
from core.effects.move.manager import process_move_effects_with_linking  # Move effects
from core.effects.status import FrostbiteEffect, SkipEffect
from utils.dice import DiceRoller
from utils.error_handler import handle_error
from utils.formatting import MessageFormatter
from .save_handler import SaveHandler, InitiativeSaveData

logger = logging.getLogger(__name__)

class CombatState(Enum):
    """Possible states for the combat system"""
    INACTIVE = "inactive"
    WAITING = "waiting"     # State for delayed start 
    ACTIVE = "active"
    PAUSED = "paused"

@dataclass
class TurnData:
    """Data for a single turn in combat"""
    character_name: str
    round_number: int
    initiative_roll: int = 0
    current_ip: int = 100
    used_actions: List[str] = field(default_factory=list)
    skipped: bool = False  # Track if this turn was skipped
    skip_reason: Optional[str] = None

    def format_progress(self) -> str:
        progress = self.current_ip
        bar_length = 20
        filled = int((progress / 100) * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        return f"{bar} {progress}%"

@dataclass
class CombatLog:
    """Tracks recent combat actions and effects"""
    entries: List[Dict] = field(default_factory=list)
    max_entries: int = 5

    def add_entry(self, entry_type: str, message: str, character: str = None):
        entry = {
            "type": entry_type,
            "message": message,
            "character": character,
            "timestamp": discord.utils.utcnow()
        }
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries.pop(0)

class InitiativeTracker:
    """
    Handles combat initiative tracking and turn management with character linking support.
    
    FIXED: No longer processes move effects separately - they're handled by the regular effect system.
    
    Responsible for:
    - Managing combat state
    - Processing turns and effects (including linked character effects)
    - Handling combat messages and formatting
    - Managing skipped turns
    - Save/load functionality
    - Processing effect feedback
    - Coordinating parent/child character effect processing
    - Preventing child characters from entering initiative
    """
    def __init__(self, bot):
        self.bot = bot
        self.state = CombatState.INACTIVE
        self.turn_order: List[TurnData] = []
        self.current_index: int = 0
        self.round_number: int = 0
        self.combat_log = CombatLog()
        self.last_state = None
        self.current_turn_message: Optional[discord.Message] = None
        self.logger = bot.game_state.logger
        self.save_handler = SaveHandler(bot.db, self.logger)
        self.quiet_mode = False  # For suppressing debug prints
        self.previous_turn_end_msgs = []  # Track previous turn's end messages
        self.expiry_pending_msgs = []     # Track messages for effects about to expire

    def set_quiet_mode(self, quiet: bool = True):
        """Enable/disable debug prints"""
        self.quiet_mode = quiet

    def debug_print(self, *args, **kwargs):
        """Print only if not in quiet mode"""
        if not self.quiet_mode:
            print(*args, **kwargs)

    def _check_for_child_characters(self, characters: List[Character]) -> List[str]:
        """
        Check if any characters are child characters (have parent_name set).
        
        Args:
            characters: List of characters to check
            
        Returns:
            List of child character names that should not be in initiative
        """
        child_characters = []
        for char in characters:
            if hasattr(char, 'parent_name') and char.parent_name:
                child_characters.append(char.name)
        return child_characters

    def _check_character_is_child(self, character: Character) -> Tuple[bool, str]:
        """
        Check if a single character is a child character.
        
        Args:
            character: Character to check
            
        Returns:
            Tuple of (is_child, parent_name)
        """
        if hasattr(character, 'parent_name') and character.parent_name:
            return True, character.parent_name
        return False, ""

    @property
    def current_turn(self) -> Optional[TurnData]:
        """Get the current turn's data"""
        if not self.turn_order:
            return None
        return self.turn_order[self.current_index]

    async def announce_turn(self, interaction: discord.Interaction, effect_messages: List[str] = None):
        """
        Announce turn with FIXED effect message formatting.
        
        Properly handles move effect messages which come in formatted blocks:
        - **Move Name** 
        - • `Description`
        - • `Attack results`
        """
        current_char = self.bot.game_state.get_character(self.current_turn.character_name)
        
        # Create announcement embed
        embed = discord.Embed(color=discord.Color.blue())
        
        # Create fields dict for logging
        fields = {}

        # Format turn info
        if self.current_turn.skipped:
            skip_msg = self.current_turn.skip_reason or "Turn skipped"
            embed.description = f"⏭️ **{self.current_turn.character_name}'s Turn**\n╰─ {skip_msg}"
            embed.color = discord.Color.red()
            fields["Turn"] = f"{self.current_turn.character_name}'s Turn\n{skip_msg}"
        else:
            embed.description = f"🎯 **{self.current_turn.character_name}'s Turn**"
            fields["Turn"] = f"{self.current_turn.character_name}'s Turn"

        # Process effect messages with improved formatting
        if effect_messages:
            # Filter out empty messages
            valid_messages = [msg for msg in effect_messages if msg and isinstance(msg, str)]
            
            if valid_messages:
                # Join messages with proper spacing for move effect blocks
                formatted_content = ""
                
                for i, msg in enumerate(valid_messages):
                    # Add the message
                    formatted_content += msg
                    
                    # Add spacing between different move effect blocks
                    # (detected by messages starting with **)
                    if (i < len(valid_messages) - 1 and 
                        msg.startswith('**') and 
                        valid_messages[i + 1].startswith('**')):
                        formatted_content += "\n\n"
                    elif i < len(valid_messages) - 1:
                        formatted_content += "\n"
                
                embed.add_field(
                    name="Effects",
                    value=formatted_content,
                    inline=False
                )
                fields["Effects"] = formatted_content

        # Send turn announcement
        await interaction.followup.send(embed=embed)
        
        # Log turn announcement
        if self.logger:
            self.logger.log_embed(
                f"{self.current_turn.character_name}'s Turn",
                fields
            )
    async def send_effect_update(self, interaction: discord.Interaction, effect_msgs: List[str], expiry_msgs: List[str] = None):
        """
        Send effect update embed with IMPROVED message categorization.
        
        Now properly handles the cleaned up message format from the fixed move effects.
        """
        # Initialize message categories
        status_msgs = []      # "(phase) X turns remaining" messages
        transition_msgs = []  # "activates", "enters cooldown" messages  
        attack_msgs = []      # Attack results and combat messages
        expiry_msgs = expiry_msgs or []
        
        # Process each message and categorize more precisely
        for msg in effect_msgs:
            if not msg:
                continue
                
            msg_lower = msg.lower()
            
            # Expiry messages (shouldn't be in effect_msgs but check anyway)
            if any(pattern in msg_lower for pattern in 
                ["worn off", "expired", "has ended", "wears off", "has worn off"]):
                if msg not in expiry_msgs:
                    expiry_msgs.append(msg)
                continue
            
            # Transition messages
            if any(pattern in msg_lower for pattern in 
                ["activates", "enters cooldown", "transitions to"]):
                transition_msgs.append(msg)
                continue
            
            # Status messages (duration remaining)
            if "remaining" in msg_lower and ("turn" in msg_lower or "round" in msg_lower):
                status_msgs.append(msg)
                continue
            
            # Attack/combat messages (contain dice rolls, damage, hits, etc.)
            if any(pattern in msg_lower for pattern in 
                ["🎲", "hits:", "damage:", "→", "ac ", "miss", "crit"]):
                attack_msgs.append(msg)
                continue
            
            # Default to status
            status_msgs.append(msg)
        
        # Create embed only if we have content
        if not (transition_msgs or status_msgs or attack_msgs or expiry_msgs):
            return
        
        embed = discord.Embed(title="Effects Update", color=discord.Color.gold())
        
        # Add fields in order of importance
        if transition_msgs:
            embed.add_field(
                name="Phase Transitions",
                value="\n".join(transition_msgs),
                inline=False
            )
        
        if attack_msgs:
            embed.add_field(
                name="Combat Results",
                value="\n".join(attack_msgs),
                inline=False
            )
        
        if status_msgs:
            embed.add_field(
                name="Active Effects",
                value="\n".join(status_msgs),
                inline=False
            )
        
        if expiry_msgs:
            embed.add_field(
                name="Effects Expired",
                value="\n".join(expiry_msgs),
                inline=False
            )
        
        # Send the update
        await interaction.followup.send(embed=embed)
        
        # Log to CombatLogger
        if self.logger:
            fields = {}
            for field in embed.fields:
                fields[field.name] = field.value
            self.logger.log_embed("Effects Update", fields)
        
        # Clear displayed feedback from all characters
        for turn in self.turn_order:
            char = self.bot.game_state.get_character(turn.character_name)
            if char and hasattr(char, 'effect_feedback'):
                char.mark_feedback_displayed()
                if hasattr(char, 'clear_old_feedback'):
                    char.clear_old_feedback()

    async def process_skipped_turn(self, interaction: discord.Interaction) -> Tuple[bool, str, List[str]]:
        """Process a skipped turn without recursive next_turn call - DUAL PROCESSING VERSION"""
        # Get the character for end effects
        current_char_name = self.current_turn.character_name
        current_char = self.bot.game_state.get_character(current_char_name)
        
        # Initialize message lists
        end_effect_messages = []
        expiry_messages = []
        
        # Process end-of-turn effects for skipped character (including linked children)
        if current_char:
            # Check for pending effect feedback first
            pending_feedback = current_char.get_pending_feedback()
            if pending_feedback:
                for feedback in pending_feedback:
                    if feedback.expiry_message and not feedback.displayed:
                        expiry_messages.append(feedback.expiry_message)
                
                # Mark feedback as displayed
                current_char.mark_feedback_displayed()
            
            # Process both base and move effects for turn end
            base_was_skipped, base_start_msgs, base_end_msgs = await process_effects_with_linking(
                current_char,
                self.round_number,
                current_char.name,
                self.logger,
                self.bot.game_state
            )
    
            move_was_skipped, move_start_msgs, move_end_msgs = await process_move_effects_with_linking(
                current_char,
                self.round_number,
                current_char.name,
                self.logger,
                self.bot.game_state
            )
    
            # Combine end messages
            end_msgs = base_end_msgs + move_end_msgs
            
            # Improved expiry message detection
            for msg in end_msgs:
                if not msg:
                    continue
                    
                # Enhanced pattern matching for expiry messages
                is_expiry = False
                if any(pattern in msg.lower() for pattern in 
                    ["worn off", "expired", "has ended", "wears off", "has worn off"]):
                    is_expiry = True
                    
                if is_expiry:
                    if msg not in expiry_messages:  # Avoid duplicates
                        expiry_messages.append(msg)
                else:
                    end_effect_messages.append(msg)
            
            # Show end effects if any
            if end_effect_messages or expiry_messages:
                # Send the update with separated expiry messages
                await self.send_effect_update(interaction, end_effect_messages, expiry_messages)
            
            # Save character state
            await self.bot.db.save_character(current_char)
        
        # Advance to next turn
        self.current_index += 1
        if self.current_index >= len(self.turn_order):
            self.round_number += 1
            self.current_index = 0
            await interaction.followup.send(embed=discord.Embed(
                title=f"Round {self.round_number} Begins!",
                color=discord.Color.blue(),
                description="Action stars refreshed for all characters!"
            ))
            for turn in self.turn_order:
                char = self.bot.game_state.get_character(turn.character_name)
                if char:
                    char.refresh_stars()
        
        new_char = self.bot.game_state.get_character(self.current_turn.character_name)
        if new_char:
            # Check for pending effect feedback first
            start_effect_messages = []
            pending_feedback = new_char.get_pending_feedback()
            if pending_feedback:
                for feedback in pending_feedback:
                    if feedback.expiry_message and not feedback.displayed:
                        start_effect_messages.append(feedback.expiry_message)
                
                # Mark feedback as displayed
                new_char.mark_feedback_displayed()
            
            # Process both base and move effects for turn start
            base_was_skipped, base_start_msgs, _ = await process_effects_with_linking(
                new_char,
                self.round_number,
                new_char.name,
                self.logger,
                self.bot.game_state
            )
    
            move_was_skipped, move_start_msgs, _ = await process_move_effects_with_linking(
                new_char,
                self.round_number,
                new_char.name,
                self.logger,
                self.bot.game_state
            )
    
            # Combine results
            was_skipped = base_was_skipped or move_was_skipped
            start_msgs = base_start_msgs + move_start_msgs
            
            # Update skip status
            self.current_turn.skipped = was_skipped
            
            # Handle effect messages
            if start_msgs:
                start_effect_messages.extend(start_msgs)
                
            # Save character state
            await self.bot.db.save_character(new_char)
            
            # Announce turn
            await self.announce_turn(interaction, start_effect_messages)
            
            # Handle another skipped turn if needed
            if was_skipped:
                return await self.process_skipped_turn(interaction)
                
            return True, "", start_effect_messages
        
        return True, "", []

    async def process_turn_effects(self, character: Character) -> Tuple[bool, List[str]]:
        """Process effects and format messages with linking support - DUAL PROCESSING VERSION."""
        was_skipped = False
        skip_reason = None
        messages = []
        
        self.debug_print(f"\nProcessing effects for {character.name}")
        self.debug_print(f"Initial state: {[e.name for e in character.effects]}")
        
        # Take snapshot if logging enabled
        if self.logger:
            self.logger.snapshot_character_state(character)
        
        # Process both base effects and move effects separately
        base_was_skipped, base_start_msgs, base_end_msgs = await process_effects_with_linking(
            character,
            self.round_number,
            character.name,
            self.logger,
            self.bot.game_state
        )
    
        move_was_skipped, move_start_msgs, move_end_msgs = await process_move_effects_with_linking(
            character,
            self.round_number, 
            character.name,
            self.logger,
            self.bot.game_state
        )
    
        # Combine results
        was_skipped = base_was_skipped or move_was_skipped
        start_messages = base_start_msgs + move_start_msgs
        end_messages = base_end_msgs + move_end_msgs
        
        # Update skip reason if we were skipped
        if was_skipped:
            # Look for skip effects to get reason
            for effect in character.effects:
                if isinstance(effect, SkipEffect):
                    skip_reason = effect.reason
                    break
                elif isinstance(effect, FrostbiteEffect) and effect.stacks >= 5:
                    skip_reason = "❄️ `Frozen solid - Cannot act`"
                    break
            
            # Set default reason if none found
            if not skip_reason:
                skip_reason = "Turn skipped"
                
            # Update turn data
            self.current_turn.skip_reason = skip_reason
            self.debug_print(f"Turn skipped: {skip_reason}")
        
        # Take another snapshot after processing
        if self.logger:
            self.logger.snapshot_character_state(character)
        
        # Return start messages for turn announcement
        return was_skipped, start_messages

    async def start_combat(self, characters: List[Character], interaction: discord.Interaction) -> Tuple[bool, str]:
        """Start combat with initiative contest and child character safeguards"""
        try:
            if self.state != CombatState.INACTIVE:
                return False, "Combat is already in progress"

            # SAFEGUARD: Check for child characters
            child_chars = self._check_for_child_characters(characters)
            if child_chars:
                child_list = ', '.join(child_chars)
                parent_suggestions = []
                
                for char_name in child_chars:
                    char = self.bot.game_state.get_character(char_name)
                    if char and hasattr(char, 'parent_name') and char.parent_name:
                        parent_suggestions.append(f"{char_name} → {char.parent_name}")
                
                suggestion_text = '\n'.join(parent_suggestions) if parent_suggestions else ""
                
                return False, (
                    f"❌ **Child characters cannot enter initiative directly:** {child_list}\n\n"
                    f"**Use their parent characters instead:**\n{suggestion_text}\n\n"
                    f"*Child character effects will automatically be processed during their parent's turn.*"
                )

            # Initialize logger
            self.logger.channel_id = interaction.channel_id
            self.logger.start_combat(characters)

            # Clear temporary effects and handle stars
            cleanup_messages = []
            for char in characters:
                # Clear temp effects
                msgs = await self.clear_combat_effects(char)
                if msgs:
                    if isinstance(msgs, list):
                        cleanup_messages.extend(msgs)
                    elif isinstance(msgs, str):
                        cleanup_messages.append(msgs)
                        
                # Reset action stars
                char.refresh_stars()
                
                # Reset move uses for all moves
                if hasattr(char, 'moveset') and hasattr(char.moveset, 'moves'):
                    for move_name, move in char.moveset.moves.items():
                        if hasattr(move, 'uses') and move.uses is not None:
                            move.uses_remaining = move.uses
                
                # Clear move cooldowns
                if hasattr(char, 'moveset'):
                    for move_name in char.list_moves():
                        move = char.get_move(move_name)
                        if move:
                            move.last_used_round = None
                
                await self.bot.db.save_character(char)
                
                # Log state changes
                if self.logger:
                    self.logger.snapshot_character_state(char)

            # Show cleanup messages if any
            if cleanup_messages:
                formatted_messages = []
                for msg in cleanup_messages:
                    if msg and isinstance(msg, str):
                        if not (msg.startswith('`') and msg.endswith('`')):
                            msg = f"`{msg}`"
                        formatted_messages.append(msg)
                        
                if formatted_messages:
                    await interaction.followup.send(
                        "\n".join(formatted_messages),
                        ephemeral=True
                    )

            # Process initiative rolls
            initiatives: List[Tuple[int, Character]] = []
            for char in characters:
                roll_result, explanation = DiceRoller.roll_dice("1d20+dex", char)
                initiatives.append((roll_result, char))
                # Log initiative roll
                self.logger.add_event(
                    CombatEventType.SYSTEM_MESSAGE,
                    message=f"{char.name} rolls {roll_result} for initiative ({explanation})",
                    character=char.name
                )

            # Sort by initiative (high to low)
            initiatives.sort(reverse=True, key=lambda x: x[0])

            # Create turn order
            self.turn_order = [
                TurnData(
                    character_name=char.name,
                    round_number=1,
                    initiative_roll=roll
                ) for roll, char in initiatives
            ]

            # Set to waiting state - combat will start on first /next
            self.state = CombatState.WAITING
            self.round_number = 0  # Will increment to 1 on first /next
            self.current_index = 0

            # Create initiative announcement embed
            embed = discord.Embed(title="Battle Begins!", color=discord.Color.blue())
            
            # Add initiative order
            order_text = []
            for roll, char in initiatives:
                order_text.append(f"{char.name} ({roll})")
                
            embed.add_field(
                name="Initiative Order",
                value=f"```\n{'\n'.join(order_text)}\n```",
                inline=False
            )
            
            # Add roll details
            details = []
            for roll, char in initiatives:
                details.append(f"{char.name} - {roll} (DEX: {char.stats.get_modifier(StatType.DEXTERITY):+})")
            
            embed.add_field(
                name="Roll Details",
                value=f"```\n" + "\n".join(details) + "\n```",
                inline=False
            )
            
            embed.set_footer(text="Type /next to begin the battle!")
            
            await interaction.followup.send(embed=embed)
            
            return True, "Combat initialized"

        except Exception as e:
            logger.error(f"Error starting combat: {e}", exc_info=True)
            return False, f"Error starting combat: {str(e)}"
        
    async def clear_combat_effects(self, character: Character) -> List[str]:
        """
        Clear temporary effects and reset cooldowns at combat start.
        
        This is an improved version that:
        1. Properly handles permanent effects
        2. Cleans up move cooldowns in both moveset and effects
        3. Preserves natural resistances/vulnerabilities
        4. Returns all cleanup messages
        5. Clears effect feedback
        """
        cleanup_messages = []
        
        # Handle effects
        for effect in character.effects[:]:  # Copy list since we're modifying it
            # Skip permanent effects if they're marked as such
            if hasattr(effect, 'permanent') and effect.permanent:
                self.debug_print(f"Keeping permanent effect: {effect.name}")
                continue
                
            # Handle different effect categories
            effect_type = effect.__class__.__name__
            
            # A move effect in cooldown phase should be removed entirely
            if hasattr(effect, 'state') and effect_type == 'MoveEffect':
                # Check if on_expire is async
                if hasattr(effect.on_expire, '__await__'):
                    msg = await effect.on_expire(character)
                else:
                    msg = effect.on_expire(character)
                    
                if msg:
                    cleanup_messages.append(msg)
                    
                character.effects.remove(effect)
                continue
                
            # For non-permanent effects, clean them up
            # Check if on_expire is async
            if hasattr(effect.on_expire, '__await__'):
                msg = await effect.on_expire(character)
            else:
                msg = effect.on_expire(character)
                
            if msg:
                cleanup_messages.append(msg)
                
            character.effects.remove(effect)
        
        # Reset character state affected by effects
        character.resources.current_temp_hp = 0
        character.resources.max_temp_hp = 0
        
        # Clear effect-based resistances/vulnerabilities, but keep natural ones
        character.defense.damage_resistances = {}
        character.defense.damage_vulnerabilities = {}
        
        # Reset AC to base value
        character.defense.current_ac = character.defense.base_ac
        
        # Clear any specialized state fields
        if hasattr(character, 'heat_stacks'):
            delattr(character, 'heat_stacks')
            
        # Clear all move cooldowns - FIXING THE VARIABLE NAME HERE
        if hasattr(character, 'moveset'):
            for move_name in character.list_moves():
                move = character.get_move(move_name)  # FIXED: changed 'char' to 'character'
                if move:
                    move.last_used_round = None
                    if hasattr(move, 'uses') and move.uses is not None:
                        move.uses_remaining = move.uses
        
        # Clear action star cooldowns
        if hasattr(character, 'action_stars'):
            character.action_stars.clear_cooldowns()
            
        # Clear effect feedback
        character.effect_feedback = []
            
        return cleanup_messages
        
    async def set_battle(
                self,
                character_names: List[str],
                interaction: discord.Interaction,
                round_number: int = 1,
                current_turn: int = 0
            ) -> Tuple[bool, str]:
                """Start combat with manual turn order with child character safeguards"""
                try:
                    if self.state != CombatState.INACTIVE:
                        return False, "Combat is already in progress"

                    # SAFEGUARD: Check for child characters
                    child_chars = []
                    parent_suggestions = []
                    
                    for name in character_names:
                        char = self.bot.game_state.get_character(name)
                        if char:
                            is_child, parent_name = self._check_character_is_child(char)
                            if is_child:
                                child_chars.append(name)
                                parent_suggestions.append(f"{name} → {parent_name}")
                    
                    if child_chars:
                        child_list = ', '.join(child_chars)
                        suggestion_text = '\n'.join(parent_suggestions)
                        
                        return False, (
                            f"❌ **Child characters cannot enter initiative directly:** {child_list}\n\n"
                            f"**Use their parent characters instead:**\n{suggestion_text}\n\n"
                            f"*Child character effects will automatically be processed during their parent's turn.*"
                        )

                    # Important: Set round number before state change
                    self.round_number = round_number
                    
                    # Initialize combat info
                    self.turn_order = [
                        TurnData(
                            character_name=name,
                            round_number=round_number,  # Use the actual round number
                            current_ip=100
                        ) for name in character_names
                    ]
                    
                    # Set state and current turn - don't touch round_number again
                    self.state = CombatState.WAITING
                    self.current_index = min(current_turn, len(character_names) - 1)  # Ensure valid turn

                    # Initialize logger
                    self.logger.channel_id = interaction.channel_id
                    self.logger.start_combat()

                    # Verify all characters exist but don't modify them
                    missing_chars = []
                    for name in character_names:
                        char = self.bot.game_state.get_character(name)
                        if not char:
                            missing_chars.append(name)
                    
                    if missing_chars:
                        return False, f"The following characters were not found: {', '.join(missing_chars)}"

                    # Create initiative embed
                    embed = discord.Embed(title="Initiative Order Set", color=discord.Color.blue())
                    
                    # Add order text
                    order_text = []
                    for i, name in enumerate(character_names):
                        if i == current_turn:
                            order_text.append(f"▶️ {name} (Current)")
                        else:
                            order_text.append(f"⬜ {name}")
                    
                    embed.add_field(
                        name="Initiative Order",
                        value=f"```\n{chr(10).join(order_text)}\n```",
                        inline=False
                    )
                    
                    current_char = character_names[current_turn]
                    
                    # Make footer clearer about the current state
                    embed.set_footer(
                        text=f"Resuming on Round {self.round_number}, {current_char}'s turn\n"
                            f"Type /next to continue the battle!"
                    )
                    
                    await interaction.followup.send(embed=embed)
                    
                    return True, "Combat resumed"
                    
                except Exception as e:
                    logger.error(f"Error setting battle: {e}", exc_info=True)
                    return False, f"Error setting battle: {str(e)}"

    async def next_turn(self, interaction: discord.Interaction) -> Tuple[bool, str, List[str]]:
        """
        Advance to next turn with FIXED effect processing and message formatting.
        
        Key fixes:
        - Proper turn end effect processing with message separation
        - Clean turn start effect processing
        - DUAL processing for base and move effects
        - Better message formatting for turn announcements
        """
        try:
            await interaction.response.defer()
            
            # First turn handling
            if self.state == CombatState.WAITING:
                self.debug_print("\n=== Combat Start ===")
                self.state = CombatState.ACTIVE
                if self.round_number < 1:
                    self.round_number = 1
                    
                # Process first turn with DUAL processing
                current_char = self.bot.game_state.get_character(self.current_turn.character_name)
                if current_char:
                    # Process both base and move effects for turn start
                    base_was_skipped, base_start_msgs, _ = await process_effects_with_linking(
                        current_char,
                        self.round_number,
                        current_char.name,
                        self.logger,
                        self.bot.game_state
                    )
    
                    move_was_skipped, move_start_msgs, _ = await process_move_effects_with_linking(
                        current_char,
                        self.round_number,
                        current_char.name,
                        self.logger,
                        self.bot.game_state
                    )
    
                    # Combine results
                    was_skipped = base_was_skipped or move_was_skipped
                    start_msgs = base_start_msgs + move_start_msgs
                    
                    self.current_turn.skipped = was_skipped
                    await self.bot.db.save_character(current_char)
    
                    # First round announcement
                    await interaction.followup.send(embed=discord.Embed(
                        title=f"Round {self.round_number} Begins!",
                        color=discord.Color.blue(),
                        description="Action stars refreshed for all characters!"
                    ))
                    
                    # Announce first turn
                    await self.announce_turn(interaction, start_msgs)
                    return True, "", start_msgs
    
            if self.state != CombatState.ACTIVE:
                return False, "Combat is not active", []
    
            # Store current character before advancing
            current_char_name = self.current_turn.character_name
            current_char = self.bot.game_state.get_character(current_char_name)
            
            # Process turn END effects for current character with DUAL processing
            turn_end_messages = []
            expiry_messages = []
            
            if current_char:
                self.debug_print(f"\n=== Processing turn end for {current_char.name} ===")
                
                # Process both base and move effects for turn end
                base_was_skipped, _, base_end_msgs = await process_effects_with_linking(
                    current_char,
                    self.round_number,
                    current_char.name,
                    self.logger,
                    self.bot.game_state
                )
    
                move_was_skipped, _, move_end_msgs = await process_move_effects_with_linking(
                    current_char,
                    self.round_number,
                    current_char.name,
                    self.logger,
                    self.bot.game_state
                )
    
                # Combine end messages
                end_msgs = base_end_msgs + move_end_msgs
                
                # Check for pending effect feedback (expiry messages)
                pending_feedback = current_char.get_pending_feedback()
                if pending_feedback:
                    self.debug_print(f"Found {len(pending_feedback)} pending feedback entries")
                    for feedback in pending_feedback:
                        if feedback.expiry_message and not feedback.displayed:
                            self.debug_print(f"Adding feedback expiry message: {feedback.expiry_message}")
                            expiry_messages.append(feedback.expiry_message)
                
                # Categorize end messages
                for msg in end_msgs:
                    if not msg:
                        continue
                    
                    # Check if it's an expiry message
                    msg_lower = msg.lower()
                    if any(pattern in msg_lower for pattern in 
                        ["worn off", "expired", "has ended", "wears off", "has worn off"]):
                        if msg not in expiry_messages:
                            expiry_messages.append(msg)
                    else:
                        turn_end_messages.append(msg)
                
                # Save character after processing
                await self.bot.db.save_character(current_char)
                
                # Show turn end effect updates if any
                if turn_end_messages or expiry_messages:
                    self.debug_print(f"Sending turn end effect update:")
                    self.debug_print(f"- Status messages: {len(turn_end_messages)}")
                    self.debug_print(f"- Expiry messages: {len(expiry_messages)}")
                    await self.send_effect_update(interaction, turn_end_messages, expiry_messages)
    
            # Advance turn
            is_new_round = self.current_index == len(self.turn_order) - 1
            
            if is_new_round:
                self.debug_print(f"\n=== Round {self.round_number} Complete ===")
                self.round_number += 1
                self.current_index = 0
                
                self.debug_print(f"\n=== Round {self.round_number} Begins ===")
                
                # Announce new round
                await interaction.followup.send(embed=discord.Embed(
                    title=f"Round {self.round_number} Begins!",
                    color=discord.Color.blue(),
                    description="Action stars refreshed for all characters!"
                ))
                
                # Refresh stars for all characters
                for turn in self.turn_order:
                    char = self.bot.game_state.get_character(turn.character_name)
                    if char:
                        char.refresh_stars()
            else:
                self.current_index += 1
    
            # Process turn START for next character with DUAL processing
            next_char = self.bot.game_state.get_character(self.current_turn.character_name)
            turn_start_messages = []
            
            if next_char:
                self.debug_print(f"\n=== Processing turn start for {next_char.name} ===")
                
                # Check for any pending feedback first
                pending_feedback = next_char.get_pending_feedback()
                if pending_feedback:
                    for feedback in pending_feedback:
                        if feedback.expiry_message and not feedback.displayed:
                            turn_start_messages.append(feedback.expiry_message)
                
                # Process both base and move effects for turn start
                base_was_skipped, base_start_msgs, _ = await process_effects_with_linking(
                    next_char,
                    self.round_number,
                    next_char.name,
                    self.logger,
                    self.bot.game_state
                )
    
                move_was_skipped, move_start_msgs, _ = await process_move_effects_with_linking(
                    next_char,
                    self.round_number,
                    next_char.name,
                    self.logger,
                    self.bot.game_state
                )
    
                # Combine results
                was_skipped = base_was_skipped or move_was_skipped
                start_msgs = base_start_msgs + move_start_msgs
                
                # Update skip status
                self.current_turn.skipped = was_skipped
                
                # Add start messages (these include formatted move descriptions and attacks)
                if start_msgs:
                    turn_start_messages.extend(start_msgs)
                
                # Save character state
                await self.bot.db.save_character(next_char)
                
                # Handle skipped turns
                if was_skipped:
                    if self.logger:
                        self.logger.add_event(
                            CombatEventType.STATUS_UPDATE,
                            message=f"{next_char.name}'s turn skipped",
                            character=next_char.name,
                            details={"reason": self.current_turn.skip_reason},
                            round_number=self.round_number
                        )
                    
                    await self.announce_turn(interaction, turn_start_messages)
                    await asyncio.sleep(1)
                    return await self.process_skipped_turn(interaction)
                
                # Announce next turn with properly formatted messages
                await self.announce_turn(interaction, turn_start_messages)
                return True, "", turn_start_messages
    
            return True, "", []
    
        except Exception as e:
            self.debug_print(f"Error in next_turn: {str(e)}")
            logger.error(f"Error in next_turn: {str(e)}", exc_info=True)
            return False, f"Error processing turn: {str(e)}", []
        
    async def end_combat(self, interaction: discord.Interaction = None) -> Tuple[bool, str]:
        """
        End the current combat session without modifying character states.
        """
        try:
            # Check if combat is active
            if self.state == CombatState.INACTIVE:
                return False, "No combat is currently active"
            
            # Log combat end
            if self.logger:
                self.logger.end_combat()
                
            # Reset tracker state
            self.state = CombatState.INACTIVE
            self.turn_order = []
            self.current_index = 0
            self.round_number = 0
            
            # Only send message if interaction is provided (not in tests)
            if interaction:
                # Create combat end embed and send it
                embed = discord.Embed(
                    title="⚔️ Combat Ended ⚔️",
                    description="`The battle has concluded!`",
                    color=discord.Color.dark_red()
                )
                
                embed.set_footer(text="Character states have been preserved")
                await interaction.followup.send(embed=embed)
            
            return True, "Combat ended successfully"
            
        except Exception as e:
            logger.error(f"Error ending combat: {e}", exc_info=True)
            return False, f"Error ending combat: {str(e)}"
        
    def end_combat_test(self):
        """End combat without interaction - for testing only"""
        # Log combat end if logger exists
        if self.logger:
            self.logger.end_combat()
            
        # Reset tracker state
        self.state = CombatState.INACTIVE
        self.turn_order = []
        self.current_index = 0
        self.round_number = 0
        
        print("\n=== Combat Ended ===")
        print("Test combat complete")

    async def add_combatant(
        self, 
        character: Character, 
        interaction: discord.Interaction,
        position: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Add a character to an ongoing combat session with child character safeguards.
        
        Args:
            character: The character to add
            interaction: Discord interaction
            position: Optional position in the initiative order (0-based index)
                      If None, adds at the end of the initiative order
        
        Returns:
            Tuple of (success, message)
        """
        try:
            # Check if combat is active
            if self.state == CombatState.INACTIVE:
                return False, "No active combat session"
                
            # SAFEGUARD: Check if character is a child character
            is_child, parent_name = self._check_character_is_child(character)
            if is_child:
                return False, (
                    f"❌ **Child character '{character.name}' cannot enter initiative directly.**\n\n"
                    f"**Use their parent character '{parent_name}' instead.**\n\n"
                    f"*Child character effects will automatically be processed during their parent's turn.*"
                )
                
            # Check if character already in combat
            if any(turn.character_name == character.name for turn in self.turn_order):
                return False, f"{character.name} is already in combat"
            
            # Initialize effects and action stars
            # Clear temp effects
            cleanup_messages = await self.clear_combat_effects(character)
            if cleanup_messages:
                if isinstance(cleanup_messages, list):
                    cleanup_text = "\n".join(cleanup_messages)
                else:
                    cleanup_text = cleanup_messages
                    
                await interaction.followup.send(
                    f"Cleanup for {character.name}:\n{cleanup_text}",
                    ephemeral=True
                )
                
            # Reset action stars
            character.refresh_stars()
            
            # Create turn data
            turn_data = TurnData(
                character_name=character.name,
                round_number=self.round_number,
                initiative_roll=0,  # No initiative roll for mid-combat additions
                current_ip=100
            )
            
            # Insert at specified position or append to end
            if position is not None:
                # Validate position
                if position < 0 or position > len(self.turn_order):
                    return False, f"Invalid position: {position}. Must be between 0 and {len(self.turn_order)}"
                    
                # Insert at specified position
                self.turn_order.insert(position, turn_data)
                
                # Adjust current_index if inserting before current turn
                if position <= self.current_index:
                    self.current_index += 1
            else:
                # Add to end of initiative order
                self.turn_order.append(turn_data)
            
            # Create embed to announce addition
            embed = discord.Embed(
                title="Combat Update",
                description=f"✅ **{character.name}** has joined the battle!",
                color=discord.Color.green()
            )
            
            # Add initiative order field
            order_text = []
            for i, turn in enumerate(self.turn_order):
                if i == self.current_index:
                    order_text.append(f"▶️ {turn.character_name} (Current)")
                else:
                    order_text.append(f"⬜ {turn.character_name}")
                    
            embed.add_field(
                name="Updated Initiative Order",
                value="\n".join(order_text),
                inline=False
            )
            
            # Add position info if specified
            if position is not None:
                pos_text = f"Inserted at position {position+1}" if position < len(self.turn_order)-1 else "Added to the end"
                embed.set_footer(text=pos_text)
            
            await interaction.followup.send(embed=embed)
            
            # Log to combat logger
            if self.logger:
                self.logger.add_event(
                    CombatEventType.SYSTEM_MESSAGE,
                    message=f"{character.name} has joined the battle",
                    character=character.name,
                    details={"position": position if position is not None else "end"}
                )
                
            return True, f"{character.name} added to combat"
            
        except Exception as e:
            logger.error(f"Error adding combatant: {e}", exc_info=True)
            return False, f"Error adding combatant: {str(e)}"
            
    async def remove_combatant(
        self, 
        character_name: str, 
        interaction: discord.Interaction
    ) -> Tuple[bool, str]:
        """
        Remove a character from combat.
        
        Args:
            character_name: Name of character to remove
            interaction: Discord interaction
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Check if combat is active
            if self.state == CombatState.INACTIVE:
                return False, "No active combat session"
                
            # Find character in turn order
            char_index = None
            for i, turn in enumerate(self.turn_order):
                if turn.character_name == character_name:
                    char_index = i
                    break
                    
            if char_index is None:
                return False, f"{character_name} is not in combat"
                
            # Get original position for reporting
            original_position = char_index
                
            # Handle current index adjustment
            if char_index == self.current_index:
                # If removing current character, just advance to next turn
                # Don't actually increment current_index, as removing the character shifts everything
                pass
            elif char_index < self.current_index:
                # If removing character before current turn, adjust index down
                self.current_index -= 1
                
            # Remove from turn order
            removed_turn = self.turn_order.pop(char_index)
            
            # Create embed to announce removal
            embed = discord.Embed(
                title="Combat Update",
                description=f"❌ **{character_name}** has left the battle!",
                color=discord.Color.red()
            )
            
            # Add new initiative order if any characters remain
            if self.turn_order:
                order_text = []
                for i, turn in enumerate(self.turn_order):
                    if i == self.current_index:
                        order_text.append(f"▶️ {turn.character_name} (Current)")
                    else:
                        order_text.append(f"⬜ {turn.character_name}")
                        
                embed.add_field(
                    name="Updated Initiative Order",
                    value="\n".join(order_text),
                    inline=False
                )
            else:
                # If no characters remain, end combat
                await self.end_combat(interaction)
                embed.add_field(
                    name="Combat Ended",
                    value="All combatants have left the battle!",
                    inline=False
                )
                
            await interaction.followup.send(embed=embed)
            
            # Log to combat logger
            if self.logger:
                self.logger.add_event(
                    CombatEventType.SYSTEM_MESSAGE,
                    message=f"{character_name} has left the battle",
                    character=character_name,
                    details={"original_position": original_position}
                )
                
            return True, f"{character_name} removed from combat"
            
        except Exception as e:
            logger.error(f"Error removing combatant: {e}", exc_info=True)
            return False, f"Error removing combatant: {str(e)}"
            
    def _get_current_state(self) -> Dict:
        """Get the current combat state for undo functionality"""
        return {
            "turn_order": self.turn_order.copy(),
            "current_index": self.current_index,
            "round_number": self.round_number,
            "state": self.state
        }