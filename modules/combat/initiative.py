"""
Initiative tracking system for combat. Handles turn order, effect processing,
and combat state management with improved message formatting.

Key Features:
- Turn-based combat management
- Effect processing and timing
- Progress bar visualization
- Formatted message output

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
from core.effects.manager import process_effects
from core.effects.status import FrostbiteEffect, SkipEffect
from utils.dice import DiceRoller
from utils.error_handler import handle_error
from utils.formatting import MessageFormatter
from .logger import CombatLogger, CombatEventType
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
        self.logger = CombatLogger(None)  # Channel ID set when combat starts
        self.save_handler = SaveHandler(bot.db, self.logger)
        self.quiet_mode = False  # For suppressing debug prints

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

    async def send_effect_update(self, interaction: discord.Interaction, duration_msgs: List[str], expiry_msgs: List[str]):
        """Send effect update embed via followup"""
        embed = discord.Embed(title="Effects Update", color=discord.Color.red())
        
        if duration_msgs:
            formatted_msgs = [
                msg if '`' in msg else f"`{msg}`" 
                for msg in duration_msgs if msg
            ]
            if formatted_msgs:
                embed.add_field(
                    name="Duration Updates",
                    value="\n".join(formatted_msgs),
                    inline=False
                )
                
        if expiry_msgs:
            formatted_msgs = [
                msg if '`' in msg else f"`{msg}`" 
                for msg in expiry_msgs if msg
            ]
            if formatted_msgs:
                embed.add_field(
                    name="Effects Expired",
                    value="\n".join(formatted_msgs),
                    inline=False
                )
                
        await interaction.followup.send(embed=embed)

    async def process_skipped_turn(self, interaction: discord.Interaction) -> Tuple[bool, str, List[str]]:
        """Process a skipped turn without recursive next_turn call"""
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
            was_skipped, start_msgs, end_msgs = process_effects(
                new_char,
                self.round_number,
                new_char.name,
                self.logger
            )
            self.current_turn.skipped = was_skipped
            await self.bot.db.save_character(new_char)
            await self.announce_turn(interaction, start_msgs)
            if end_msgs:
                await self.send_effect_update(interaction, end_msgs, [])
            return True, "", start_msgs
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
        
        # Process each effect
        for effect in character.effects[:]:  # Copy list since we're modifying it
            # Process start of turn effects
            if start_msgs := effect.on_turn_start(
                character,
                round_number=self.round_number,
                turn_name=character.name
            ):
                if isinstance(start_msgs, list):
                    messages.extend(start_msgs)
                elif isinstance(start_msgs, str):
                    messages.append(start_msgs)
                    
            # Check for frozen/skipped turn
            if isinstance(effect, FrostbiteEffect) and effect.stacks >= 5:
                was_skipped = True
                skip_reason = "❄️ `Frozen solid - Cannot act`"
                self.debug_print(f"Turn skipped: {skip_reason}")
                
            # Check for expired effects at start of turn
            if (not hasattr(effect, '_handles_own_expiry') or not effect._handles_own_expiry) and \
            effect.timing and effect.timing.should_expire(self.round_number, character.name):
                if expired_msg := effect.on_expire(character):
                    messages.append(expired_msg)
                    self.debug_print(f"Effect expired: {effect.name}")
                character.effects.remove(effect)

        # Update turn data with skip reason if needed
        if was_skipped and skip_reason:
            self.current_turn.skip_reason = skip_reason

        # Take another snapshot after processing
        if self.logger:
            self.logger.snapshot_character_state(character)

        # Format messages
        formatted_messages = []
        for msg in messages:
            if not msg or not isinstance(msg, str):
                continue
            if not (msg.startswith('`') and msg.endswith('`')):
                msg = f"`{msg}`"
            formatted_messages.append(msg)

        self.debug_print(f"Final state: {[e.name for e in character.effects]}")
        self.debug_print(f"Effect messages: {formatted_messages}")
        
        return was_skipped, formatted_messages

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
        """
        cleanup_messages = []
        
        # Handle effects
        for effect in character.effects[:]:  # Copy list since we're modifying it
            # Skip permanent effects if they're marked as such
            if effect.permanent:
                self.debug_print(f"Keeping permanent effect: {effect.name}")
                continue
                
            # Handle different effect categories
            effect_type = effect.__class__.__name__
            
            # A move effect in cooldown phase should be removed entirely
            if hasattr(effect, 'state') and effect_type == 'MoveEffect':
                msg = effect.on_expire(character)
                if msg:
                    cleanup_messages.append(msg)
                    
                character.effects.remove(effect)
                continue
                
            # For non-permanent effects, clean them up
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
            
        # Clear all move cooldowns
        if hasattr(character, 'moveset'):
            for move_name in character.list_moves():
                move = character.get_move(move_name)
                if move:
                    move.last_used_round = None
                    if hasattr(move, 'uses') and move.uses is not None:
                        move.uses_remaining = move.uses
        
        # Clear action star cooldowns
        if hasattr(character, 'action_stars'):
            character.action_stars.clear_cooldowns()
            
        return cleanup_messages
        
    async def set_battle(
            self,
            character_names: List[str],
            interaction: discord.Interaction,
            round_number: int = 1,
            current_turn: int = 0
        ) -> Tuple[bool, str]:
            """Start combat with manual turn order"""
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

                # Clear character effects and reset cooldowns
                cleanup_messages = []
                for name in character_names:
                    char = self.bot.game_state.get_character(name)
                    if char:
                        msgs = await self.clear_combat_effects(char)
                        if msgs:
                            cleanup_messages.extend(msgs)
                            
                        # Reset stars
                        char.refresh_stars()
                        
                        # Save changes
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
                    text=f"Starting on Round {self.round_number}, {current_char}'s turn\n"
                        f"Type /next to continue the battle!"
                )
                
                await interaction.followup.send(embed=embed)
                
                return True, "Combat initialized"
                
            except Exception as e:
                logger.error(f"Error setting battle: {e}", exc_info=True)
                return False, f"Error setting battle: {str(e)}"

    async def next_turn(self, interaction: discord.Interaction) -> Tuple[bool, str, List[str]]:
        """Advance to next turn and process effects"""
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
                    was_skipped, start_msgs, end_msgs = process_effects(
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
                    if end_msgs:
                        await self.send_effect_update(interaction, end_msgs, [])
                    return True, "", start_msgs

            if self.state != CombatState.ACTIVE:
                return False, "Combat is not active", []

            # Process current character's turn end
            end_effect_messages = []
            current_char = self.bot.game_state.get_character(self.current_turn.character_name)
            if current_char:
                # Get end of turn effects
                was_skipped, start_msgs, end_msgs = process_effects(
                    current_char,
                    self.round_number,
                    current_char.name,
                    self.logger
                )
                if end_msgs:
                    end_effect_messages.extend(end_msgs)
                    # Show end of turn effects BEFORE any round transition
                    await self.send_effect_update(interaction, end_msgs, [])

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
                # Process new turn
                was_skipped, start_msgs, end_msgs = process_effects(
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
                if end_msgs:
                    end_effect_messages.extend(end_msgs)
                    
                # Save character state
                await self.bot.db.save_character(new_char)
                
                # Handle skipped turns
                if was_skipped:
                    if self.logger:
                        self.logger.add_event(
                            CombatEventType.STATUS_UPDATE,
                            message=f"{new_char.name}'s turn skipped",
                            character=new_char.name,
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
        
    async def add_combatant(self, character: Character, interaction: discord.Interaction) -> Tuple[bool, str]:
            """Add a character to the current combat"""
            try:
                if self.state not in [CombatState.ACTIVE, CombatState.WAITING]:
                    return False, "Combat is not active"

                # Clean up effects first
                cleanup_messages = await self.clear_combat_effects(character)
                
                # Reset stars
                character.refresh_stars()
                
                # Save changes
                await self.bot.db.save_character(character)

                # Add at current initiative count
                self.turn_order.append(
                    TurnData(
                        character_name=character.name,
                        round_number=self.round_number,
                        current_ip=100
                    )
                )
                
                # Log with combat logger
                if self.logger:
                    self.logger.add_event(
                        CombatEventType.SYSTEM_MESSAGE,
                        message=f"{character.name} joined the battle",
                        character=character.name,
                        details={"action": "join_combat"}
                    )
                    self.logger.snapshot_character_state(character)
                
                # Send feedback message
                embed = discord.Embed(
                    description=f"⚔️ `{character.name} has joined the battle!` ⚔️",
                    color=discord.Color.blue()
                )
                
                await interaction.followup.send(embed=embed)
                
                return True, f"Added {character.name} to combat"

            except Exception as e:
                logger.error(f"Error adding combatant: {e}", exc_info=True)
                return False, f"Error adding combatant: {str(e)}"

    async def remove_combatant(self, character_name: str, interaction: discord.Interaction) -> Tuple[bool, str]:
            """Remove a character from combat"""
            try:
                if self.state not in [CombatState.ACTIVE, CombatState.WAITING]:
                    return False, "Combat is not active"

                # Find character first for logging
                char = self.bot.game_state.get_character(character_name)
                if char and self.logger:
                    self.logger.snapshot_character_state(char)

                # Find and remove character
                for i, turn in enumerate(self.turn_order):
                    if turn.character_name == character_name:
                        self.turn_order.pop(i)
                        
                        # Adjust current_index if needed
                        if i < self.current_index:
                            self.current_index -= 1
                        elif i == self.current_index:
                            self.current_index %= len(self.turn_order)
                        
                        # Log with combat logger
                        if self.logger:
                            self.logger.add_event(
                                CombatEventType.SYSTEM_MESSAGE,
                                message=f"{character_name} left the battle",
                                character=character_name,
                                details={"action": "leave_combat"}
                            )
                        
                        # Send feedback message
                        embed = discord.Embed(
                            description=f"⚔️ `{character_name} has left the battle!` ⚔️",
                            color=discord.Color.blue()
                        )
                        
                        await interaction.followup.send(embed=embed)
                        
                        return True, f"Removed {character_name} from combat"
                
                return False, f"Character {character_name} not found in combat"

            except Exception as e:
                logger.error(f"Error removing combatant: {e}", exc_info=True)
                return False, f"Error removing combatant: {str(e)}"

    def end_combat(self) -> Tuple[bool, str]:
        """End the current combat"""
        if self.state == CombatState.INACTIVE:
            return False, "No combat in progress"
            
        self.state = CombatState.INACTIVE
        self.turn_order.clear()
        self.current_index = 0
        self.round_number = 0
        self.combat_log = CombatLog()
        
        # End combat logging
        self.logger.end_combat()
        
        return True, "Combat ended"

    def _get_current_state(self) -> Dict:
        """Get the current combat state for undo functionality"""
        return {
            "turn_order": self.turn_order.copy(),
            "current_index": self.current_index,
            "round_number": self.round_number,
            "state": self.state
        }