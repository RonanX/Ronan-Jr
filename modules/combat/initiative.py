"""
Initiative tracking system for combat. Handles turn order, effect processing,
and combat state management with improved message formatting.

Key Features:
- Turn-based combat management
- Effect processing and timing
- Progress bar visualization
- Formatted message output
- Effect feedback message handling

IMPLEMENTATION MANDATES:
- Use CombatLogger for ALL combat events
- Process effects in correct order (start -> end -> expire)
- Always save character state after effect processing
- Use MessageFormatter for ALL output
- Track both temporary and permanent effect states
- Handle effect cleanup properly on combat end
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
from core.effects.manager import process_effects  # Import the async function
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
    Handles combat initiative tracking and turn management.
    
    Responsible for:
    - Managing combat state
    - Processing turns and effects
    - Handling combat messages and formatting
    - Managing skipped turns
    - Save/load functionality
    - Processing effect feedback
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

    @property
    def current_turn(self) -> Optional[TurnData]:
        """Get the current turn's data"""
        if not self.turn_order:
            return None
        return self.turn_order[self.current_index]

    async def announce_turn(self, interaction: discord.Interaction, effect_messages: List[str] = None):
        """Announce turn with effect messages"""
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

        # Add effect messages
        if effect_messages:
            # Don't add more backticks if message already has them
            formatted_messages = [
                msg if '`' in msg else f"`{msg}`" 
                for msg in effect_messages if msg
            ]
            
            if formatted_messages:
                embed.add_field(
                    name="Effects",
                    value="\n".join(formatted_messages),
                    inline=False
                )
                fields["Effects"] = "\n".join(formatted_messages)

        # Send turn announcement
        await interaction.followup.send(embed=embed)
        
        # Log turn announcement
        if self.logger:
            self.logger.log_embed(
                f"{self.current_turn.character_name}'s Turn",
                fields
            )

    async def send_effect_update(self, interaction: discord.Interaction, effect_msgs: List[str], expiry_msgs: List[str] = None):
        """Send effect update embed via followup with improved formatting"""
        # Initialize message categories
        duration_msgs = []
        expiry_warning_msgs = []
        final_turn_msgs = []
        expiry_msgs = expiry_msgs or []
        
        # FIXED: Process each message and categorize appropriately
        for msg in effect_msgs:
            if not msg:
                continue
            
            # FIXED: Improved pattern matching for expiry messages
            if any(pattern in msg.lower() for pattern in 
                ["worn off", "expired", "has ended", "wears off", "has worn off"]):
                if msg not in expiry_msgs:
                    expiry_msgs.append(msg)
                continue
                
            # Check for final turn warnings
            if "final turn" in msg.lower() or "will expire" in msg.lower():
                if "final turn" in msg.lower():
                    final_turn_msgs.append(msg)
                else:
                    expiry_warning_msgs.append(msg)
            else:
                duration_msgs.append(msg)
        
        # Create embed for all effect updates
        embed = discord.Embed(title="Effects Update", color=discord.Color.gold())
        
        # Add fields for each message type if they exist
        if duration_msgs:
            embed.add_field(
                name="Effects Continuing",
                value="\n".join(duration_msgs),
                inline=False
            )
        
        if final_turn_msgs:
            embed.add_field(
                name="Final Turn Effects",
                value="\n".join(final_turn_msgs),
                inline=False
            )
        
        if expiry_warning_msgs:
            embed.add_field(
                name="Will Expire Next Turn",
                value="\n".join(expiry_warning_msgs),
                inline=False
            )
        
        if expiry_msgs:
            embed.add_field(
                name="Effects Expired",
                value="\n".join(expiry_msgs),
                inline=False
            )
        
        # Only send if there's content
        if len(embed.fields) > 0:
            await interaction.followup.send(embed=embed)
            
            # Log to CombatLogger
            if self.logger:
                fields = {}
                for field in embed.fields:
                    fields[field.name] = field.value
                self.logger.log_embed("Effects Update", fields)

    async def process_skipped_turn(self, interaction: discord.Interaction) -> Tuple[bool, str, List[str]]:
        """Process a skipped turn without recursive next_turn call"""
        # Get the character for end effects
        current_char_name = self.current_turn.character_name
        current_char = self.bot.game_state.get_character(current_char_name)
        
        # FIXED: Initialize message lists
        end_effect_messages = []
        expiry_messages = []
        
        # Process end-of-turn effects for skipped character
        if current_char:
            # FIXED: Check for pending effect feedback first
            pending_feedback = current_char.get_pending_feedback()
            if pending_feedback:
                for feedback in pending_feedback:
                    if feedback.expiry_message and not feedback.displayed:
                        expiry_messages.append(feedback.expiry_message)
                
                # Mark feedback as displayed
                current_char.mark_feedback_displayed()
            
            # Process effects - properly await the call
            was_skipped, start_msgs, end_msgs = await process_effects(
                current_char,
                self.round_number,
                current_char.name,
                self.logger
            )
            
            # FIXED: Improved expiry message detection
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
            # FIXED: Check for pending effect feedback first
            start_effect_messages = []
            pending_feedback = new_char.get_pending_feedback()
            if pending_feedback:
                for feedback in pending_feedback:
                    if feedback.expiry_message and not feedback.displayed:
                        start_effect_messages.append(feedback.expiry_message)
                
                # Mark feedback as displayed
                new_char.mark_feedback_displayed()
            
            # Process new turn - properly await the call
            was_skipped, start_msgs, _ = await process_effects(
                new_char,
                self.round_number,
                new_char.name,
                self.logger
            )
                
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
        """Process effects and format messages."""
        was_skipped = False
        skip_reason = None
        messages = []
        
        self.debug_print(f"\nProcessing effects for {character.name}")
        self.debug_print(f"Initial state: {[e.name for e in character.effects]}")
        
        # Take snapshot if logging enabled
        if self.logger:
            self.logger.snapshot_character_state(character)
        
        # Process effects - properly await the call
        was_skipped, start_messages, end_messages = await process_effects(
            character, 
            self.round_number, 
            character.name,
            self.logger
        )
        
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
            """Start combat with initiative contest"""
            try:
                if self.state != CombatState.INACTIVE:
                    return False, "Combat is already in progress"

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
                """Start combat with manual turn order without modifying any character data"""
                try:
                    if self.state != CombatState.INACTIVE:
                        return False, "Combat is already in progress"

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
        Advance to next turn and process effects with improved message handling.
        
        Enhanced to properly display effect expiry messages using feedback system.
        """
        try:
            await interaction.response.defer()
            
            # First turn handling
            if self.state == CombatState.WAITING:
                self.debug_print("\n=== Combat Start ===")
                self.state = CombatState.ACTIVE
                if self.round_number < 1:
                    self.round_number = 1
                    
                # Process first turn
                current_char = self.bot.game_state.get_character(self.current_turn.character_name)
                if current_char:
                    # Process effects - properly await the call
                    was_skipped, start_msgs, _ = await process_effects(
                        current_char,
                        self.round_number,
                        current_char.name,
                        self.logger
                    )
                    self.current_turn.skipped = was_skipped
                    await self.bot.db.save_character(current_char)

                    # First round announcement
                    await interaction.followup.send(embed=discord.Embed(
                        title=f"Round {self.round_number} Begins!",
                        color=discord.Color.blue(),
                        description="Action stars refreshed for all characters!"
                    ))
                    
                    # First turn with effects
                    await self.announce_turn(interaction, start_msgs)
                    return True, "", start_msgs

            if self.state != CombatState.ACTIVE:
                return False, "Combat is not active", []

            # Store current character before advancing
            current_char_name = self.current_turn.character_name
            current_char = self.bot.game_state.get_character(current_char_name)
            
            # Process current character's turn end
            end_effect_messages = []
            expiry_messages = []  # Specifically track expiry messages
            if current_char:
                # Get end of turn effects
                # Process effects - properly await the call
                was_skipped, start_msgs, end_msgs = await process_effects(
                    current_char,
                    self.round_number,
                    current_char.name,
                    self.logger
                )
                
                self.debug_print(f"\n=== Processing turn end for {current_char.name} ===")
                self.debug_print(f"Received {len(end_msgs)} end messages")
                
                # Check for pending effect feedback first
                pending_feedback = current_char.get_pending_feedback()
                if pending_feedback:
                    self.debug_print(f"Found {len(pending_feedback)} pending feedback entries")
                    for feedback in pending_feedback:
                        if feedback.expiry_message and not feedback.displayed:
                            self.debug_print(f"Adding feedback expiry message: {feedback.expiry_message}")
                            expiry_messages.append(feedback.expiry_message)
                
                # IMPROVED HANDLING: Better identification of expiry messages in end_msgs
                for msg in end_msgs:
                    if not msg:
                        continue
                        
                    # Enhanced pattern matching for expiry messages
                    is_expiry = False
                    
                    if any(phrase in msg.lower() for phrase in ["worn off", "ended", "expired", "wears off"]):
                        is_expiry = True
                    elif "has worn off" in msg.lower() or "has expired" in msg.lower():
                        is_expiry = True
                        
                    if is_expiry:
                        self.debug_print(f"Found expiry message: {msg}")
                        if msg not in expiry_messages:  # Avoid duplicates
                            expiry_messages.append(msg)
                    else:
                        self.debug_print(f"Regular end message: {msg}")
                        end_effect_messages.append(msg)
                
                # Save the character after processing effects
                await self.bot.db.save_character(current_char)
                
                # IMPROVED: More clear logging for effect update processing
                self.debug_print(f"Sending effect update with:")
                self.debug_print(f"- Regular messages: {len(end_effect_messages)}")
                self.debug_print(f"- Expiry messages: {len(expiry_messages)}")
                
                # Always show the end-of-turn effect updates before moving to next character
                # Ensure expiry messages are included separately for proper categorization
                if end_effect_messages or expiry_messages:
                    await self.send_effect_update(interaction, end_effect_messages, expiry_messages)

            # Handle round transition
            start_effect_messages = []
            if self.current_index == len(self.turn_order) - 1:
                self.debug_print(f"\n=== Round {self.round_number} Complete ===")
                self.round_number += 1
                self.current_index = 0
                
                self.debug_print(f"\n=== Round {self.round_number} Begins ===")
                
                # Announce new round AFTER showing previous turn's end effects
                await interaction.followup.send(embed=discord.Embed(
                    title=f"Round {self.round_number} Begins!",
                    color=discord.Color.blue(),
                    description="Action stars refreshed for all characters!"
                ))
                
                # Refresh stars
                for turn in self.turn_order:
                    char = self.bot.game_state.get_character(turn.character_name)
                    if char:
                        char.refresh_stars()
            else:
                self.current_index += 1

            # Process next character's turn
            new_char = self.bot.game_state.get_character(self.current_turn.character_name)
            if new_char:
                # Check for pending effect feedback first
                pending_feedback = new_char.get_pending_feedback()
                if pending_feedback:
                    for feedback in pending_feedback:
                        if feedback.expiry_message and not feedback.displayed:
                            start_effect_messages.append(feedback.expiry_message)
                
                # Process new turn - properly await the call
                was_skipped, start_msgs, _ = await process_effects(
                    new_char,
                    self.round_number,
                    new_char.name,
                    self.logger
                )
                
                # Update skip status
                self.current_turn.skipped = was_skipped
                
                # Handle effect messages
                if start_msgs:
                    start_effect_messages.extend(start_msgs)
                    
                # Save character state
                await self.bot.db.save_character(new_char)
                
                # Handle skipped turns
                if was_skipped:
                    if self.logger:
                        self.logger.add_event(
                            CombatEventType.STATUS_UPDATE,
                            message=f"{new_char.name}'s turn skipped",
                            character=new_char.name,
                            details={"reason": self.current_turn.skip_reason},
                            round_number=self.round_number
                        )
                    
                    await self.announce_turn(interaction, start_effect_messages)
                    await asyncio.sleep(1)
                    return await self.process_skipped_turn(interaction)
                        
                # Announce next turn
                await self.announce_turn(interaction, start_effect_messages)
                return True, "", start_effect_messages

            return True, "", []

        except Exception as e:
            self.debug_print(f"Error in next_turn: {str(e)}")
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

    def _get_current_state(self) -> Dict:
        """Get the current combat state for undo functionality"""
        return {
            "turn_order": self.turn_order.copy(),
            "current_index": self.current_index,
            "round_number": self.round_number,
            "state": self.state
        }