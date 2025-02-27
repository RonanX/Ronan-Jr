"""
Combat logging system with simplified output for better readability.
Uses plain print statements instead of complex logging structure.
"""

from enum import Enum
from typing import Optional, Dict, Any, List
import re
from datetime import datetime

class CombatEventType(Enum):
    """Types of combat events to track"""
    COMBAT_START = "combat_start"
    COMBAT_END = "combat_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    EFFECT_APPLIED = "effect_applied"
    EFFECT_EXPIRED = "effect_expired"
    DAMAGE_DEALT = "damage_dealt"
    HEALING_DONE = "healing_done"
    STATUS_UPDATE = "status_update"
    RESOURCE_CHANGE = "resource_change"
    COMMAND_USED = "command_used"
    SYSTEM_MESSAGE = "system_message"

class CombatLogger:
    """
    Simplified combat logger for cleaner test output.
    Uses print statements instead of logging for better readability.
    """
    
    def __init__(self, channel_id: Optional[int]):
        self.channel_id = channel_id
        self.current_combat_id = None
        self.current_round = 0
        self.debug_mode = False  # Controls verbosity
        self._last_message = None  # For deduplication

    def _clean_message(self, msg: str) -> str:
        """Remove emojis and clean up formatting"""
        if not msg:
            return ""
            
        # Remove Discord emoji codes
        msg = re.sub(r':[a-zA-Z_]+:', '', msg)
        
        # Remove Unicode emojis
        msg = re.sub(r'[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]', '', msg)
        
        # Clean up any double spaces or edge whitespace
        msg = ' '.join(msg.split())
        
        # Remove backticks for cleaner output
        msg = msg.replace('`', '')
        
        return msg

    def _should_log(self, message: str) -> bool:
        """Check if message should be logged (prevent duplicates)"""
        if message == self._last_message:
            return False
        self._last_message = message
        return True

    def log_command(self, command_name: str, **params):
        """Log command usage (simplified)"""
        if not self.debug_mode:
            return
            
        param_list = []
        for key, value in params.items():
            if value is None:
                continue
            param_list.append(f"{key}:{value}")
            
        cmd_str = f"Command used: /{command_name} {' '.join(param_list)}"
        print(f"\n{cmd_str}")

    def start_combat(self, characters: List['Character'] = None) -> None:
        """Log combat start (simplified)"""
        print("\n=== Combat Started ===\n")
        
    def end_combat(self) -> None:
        """Log combat end (simplified)"""
        print("\n=== Combat Ended ===\n")
        self.current_combat_id = None
        self.current_round = 0

    def add_event(
        self,
        event_type: CombatEventType,
        message: str,
        character: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        round_number: Optional[int] = None
    ) -> None:
        """Log a combat event (simplified)"""
        if self.debug_mode:
            message = self._clean_message(message)
            if not message:
                return
                
            # Format message with character name if provided
            formatted_msg = f"{character}: {message}" if character else message
            
            if self._should_log(formatted_msg):
                print(formatted_msg)

    def log_embed(self, title: str, fields: Dict[str, str]) -> None:
        """Log embed content in simple text format"""
        title = self._clean_message(title)
        if title and self._should_log(title):
            print(f"\n{title}")
        
        logged_lines = set()
        
        for name, value in fields.items():
            if not value or name == "Turn":  # Skip turn fields to avoid duplication
                continue
                
            value = self._clean_message(value)
            lines = value.split('\n')
            
            for line in lines:
                line = line.strip()
                if line and line not in logged_lines:
                    if line.startswith('•'):
                        msg = f"  {line}"
                    else:
                        msg = line
                        
                    if self._should_log(msg):
                        print(msg)
                    logged_lines.add(line)
        
        # Add a blank line after field output
        print("")

    def snapshot_character_state(self, character: 'Character') -> None:
        """Track character state changes (simplified)"""
        if not self.debug_mode:
            return
            
        # Only log basic info in debug mode
        print(f"Character state: {character.name}")
        print(f"  HP: {character.resources.current_hp}/{character.resources.max_hp}")
        print(f"  MP: {character.resources.current_mp}/{character.resources.max_mp}")
        print(f"  AC: {character.defense.current_ac}")
        
        # Only log effects if there are any
        if character.effects:
            print(f"  Effects: {len(character.effects)}")
            if self.debug_mode:
                for effect in character.effects:
                    print(f"    • {effect.name}")

    def log_combat_start(self, title: str, fields: Dict[str, str]) -> None:
        """Special handling for combat start message (simplified)"""
        clean_title = self._clean_message(title)
        if clean_title:
            print(f"\n{clean_title}")
        
        # Log initiative order
        if "Initiative Order" in fields:
            order = fields["Initiative Order"].replace("```", "").strip()
            print(order)
            print("")
        
        # Log roll details if present
        if "Roll Details" in fields:
            details = fields["Roll Details"].replace("```", "").strip()
            print(details)
            print("")

    def log_round_transition(self, round_number: int) -> None:
        """Log round transition with consistent formatting (simplified)"""
        msg = f"Round {round_number} Begins!"
        print(f"\n{msg}")
        print("Action stars refreshed for all characters!")
        print("")