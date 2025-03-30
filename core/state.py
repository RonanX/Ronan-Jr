"""  
Game State Manager (src/core/state.py)

This file manages the active game state in memory, acting as a cache between the bot  
and the database. It tracks all current game information including characters,  
combat status, and initiative order. It also provides combat logging functionality.
"""

from typing import Dict, List, Optional, Tuple, Any
import logging
from datetime import datetime
import re
from enum import Enum

from .character import Character

logger = logging.getLogger(__name__)

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
    Combat logger for tracking and displaying combat events.
    
    Features:
    - Console output of all combat events
    - Character state tracking
    - Command parameter logging
    - Embed content display
    - Turn progression visualization
    """
    
    def __init__(self, channel_id: Optional[int] = None):
        self.channel_id = channel_id
        self.current_combat_id = None
        self.current_round = 0
        self.debug_mode = False  # Controls verbosity
        self._last_message = None  # For deduplication
        self.show_commands = True  # Whether to show command parameters

    def _clean_message(self, msg: str) -> str:
        """Remove emojis and clean up formatting for console output"""
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
        """Log command usage with parameters"""
        if not self.show_commands:
            return
        
        # Build a neat formatted parameter list for display
        param_list = []
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, str) and len(value) > 50:
                # Truncate long values
                value = value[:47] + "..."
            param_list.append(f"{key}:{value}")
        
        cmd_str = f"Command used: /{command_name}"
        if param_list:
            cmd_str += f" {' '.join(param_list)}"
            
        print(f"\n{cmd_str}")

    def start_combat(self, characters: List['Character'] = None) -> None:
        """Log combat start with participating characters"""
        print("\n=== Combat Started ===")
        
        if characters and self.debug_mode:
            char_names = [c.name for c in characters]
            print(f"Participants: {', '.join(char_names)}")
        
        print("")  # Empty line for spacing
        self.current_round = 1

    def end_combat(self) -> None:
        """Log combat end with summary information"""
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
        """Log a combat event with optional detail information"""
        message = self._clean_message(message)
        if not message:
            return
            
        # Format message with character name if provided
        formatted_msg = f"{character}: {message}" if character else message
        
        if self._should_log(formatted_msg):
            # Include round number if provided
            round_prefix = f"[Round {round_number}] " if round_number else ""
            print(f"{round_prefix}{formatted_msg}")
            
            # Print details if in debug mode
            if self.debug_mode and details:
                for key, value in details.items():
                    if key == "round" or key == "character":
                        continue  # Skip redundant info
                    print(f"  {key}: {value}")

    def log_embed(self, title: str, fields: Dict[str, str]) -> None:
        """Display embed content in console-friendly format"""
        title = self._clean_message(title)
        if title and self._should_log(title):
            print(f"\n{title}")
           
        logged_lines = set()
         
        # Handle effects field specially for better visibility
        if "Effects" in fields:
            effects_content = fields.get("Effects", "")
            if effects_content:
                print("\nEffect Messages:")
                effect_lines = effects_content.split('\n')
                for line in effect_lines:
                    line = self._clean_message(line.strip())
                    if line:
                        print(f"  {line}")
                        logged_lines.add(line)
        
        # Handle duration updates specifically
        if "Duration Updates" in fields:
            updates_content = fields.get("Duration Updates", "")
            if updates_content:
                print("\nEffect Updates:")
                update_lines = updates_content.split('\n')
                for line in update_lines:
                    line = self._clean_message(line.strip())
                    if line:
                        print(f"  {line}")
                        logged_lines.add(line)
                        
        # Handle will expire next specifically
        if "Will Expire Next Turn" in fields:
            expire_content = fields.get("Will Expire Next Turn", "")
            if expire_content:
                print("\nEffect Expiry Warnings:")
                expire_lines = expire_content.split('\n')
                for line in expire_lines:
                    line = self._clean_message(line.strip())
                    if line:
                        print(f"  {line}")
                        logged_lines.add(line)
                        
        # Handle expired effects specifically
        if "Effects Expired" in fields:
            expired_content = fields.get("Effects Expired", "")
            if expired_content:
                print("\nEffects Expired:")
                expired_lines = expired_content.split('\n')
                for line in expired_lines:
                    line = self._clean_message(line.strip())
                    if line:
                        print(f"  {line}")
                        logged_lines.add(line)
         
        # Process other fields
        for name, value in fields.items():
            if not value or name in ["Turn", "Effects", "Duration Updates", "Will Expire Next Turn", "Effects Expired"]:
                continue
                 
            field_title = self._clean_message(name)
            print(f"\n{field_title}:")
             
            value = self._clean_message(value)
            lines = value.split('\n')
               
            for line in lines:
                line = line.strip()
                if line and line not in logged_lines:
                    if line.startswith('•'):
                        print(f"  {line}")
                    else:
                        print(f"  {line}")
                    logged_lines.add(line)
                     
        # Add a blank line after field output
        print("")

    def snapshot_character_state(self, character: 'Character') -> None:
        """Log character state for tracking changes over time"""
        if not self.debug_mode:
            return
            
        # Basic character info
        print(f"Character state: {character.name}")
        print(f"  HP: {character.resources.current_hp}/{character.resources.max_hp}")
        print(f"  MP: {character.resources.current_mp}/{character.resources.max_mp}")
        print(f"  AC: {character.defense.current_ac}")
        
        # Effect logging
        if character.effects:
            print(f"  Effects: {len(character.effects)}")
            for effect in character.effects:
                duration_info = ""
                if hasattr(effect, 'get_remaining_turns'):
                    duration_info = f" ({effect.get_remaining_turns()} turns remaining)"
                print(f"    • {effect.name}{duration_info}")
                
                # For move effects, show phase information
                if hasattr(effect, 'state'):
                    print(f"      State: {effect.state.value}")

    def log_combat_start(self, title: str, fields: Dict[str, str]) -> None:
        """Display combat start information including initiative order"""
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
        """Show round transition with separator for clarity"""
        self.current_round = round_number
        print(f"\n=== Round {round_number} Begins! ===")
        print("Action stars refreshed for all characters!")
        print("")
        
    def log_move_parameters(self, character: str, move_name: str, **params):
        """Log move command usage with detailed parameters"""
        if not self.show_commands:
            return
            
        print(f"\n{character} uses move '{move_name}'")
        
        # Group parameters by category
        basic_params = ['mp_cost', 'hp_cost', 'star_cost', 'target']
        timing_params = ['cast_time', 'duration', 'cooldown', 'roll_timing']
        combat_params = ['attack_roll', 'damage', 'crit_range', 'save_type', 'save_dc']
        
        # Print basic parameters
        basic_values = []
        for param in basic_params:
            if param in params and params[param] is not None:
                if param == 'target' and params[param]:
                    basic_values.append(f"Target: {params[param]}")
                elif params[param] != 0:  # Skip zero costs
                    basic_values.append(f"{param}: {params[param]}")
                    
        if basic_values:
            print("  " + " | ".join(basic_values))
            
        # Print timing parameters
        timing_values = []
        for param in timing_params:
            if param in params and params[param] is not None:
                timing_values.append(f"{param}: {params[param]}")
                
        if timing_values:
            print("  " + " | ".join(timing_values))
            
        # Print combat parameters
        combat_values = []
        for param in combat_params:
            if param in params and params[param] is not None:
                combat_values.append(f"{param}: {params[param]}")
                
        if combat_values:
            print("  " + " | ".join(combat_values))
        
        # Print description if available
        if 'description' in params and params['description']:
            print(f"  Description: {params['description']}")
            
        print("")  # Empty line for spacing

    def log_phase_transition(self, move_name: str, old_state: str, new_state: str, turns_completed: int, duration: int):
        """Log move phase transitions for debugging"""
        if not self.debug_mode:
            return
            
        print(f"PHASE CHANGE: {move_name} - {old_state} → {new_state}")
        print(f"  Completed {turns_completed}/{duration} turns in previous phase")
        print("")

class GameState:
    """  
    Manages the active game state, including characters and combat status.  
    Acts as an in-memory cache to reduce database calls.  
    """  
    def __init__(self):  
        self.characters: Dict[str, Character] = {}  
        self.combat_active: bool = False  
        self.round_number: int = 0  
        self.initiative_order: List[str] = []  
        self.current_turn: int = 0  
        self.db = None  # Will be set during load
        self.logger = CombatLogger()  # Initialize the logger

    async def load(self, database) -> None:  
        """Load all characters from database into memory"""  
        self.db = database  
        try:  
            # Load character list from database  
            char_data = self.db._refs['characters'].get()  
             
            if char_data and isinstance(char_data, dict):  
                # Create Character objects from data  
                for name, data in char_data.items():  
                    if name != 'movesets':  # Skip movesets collection  
                        try:  
                            self.characters[name] = Character.from_dict(data)  
                        except Exception as e:  
                            print(f"Error loading character {name}: {e}")  
                            continue  
                             
            print(f"Loaded {len(self.characters)} characters into game state")  
             
        except Exception as e:  
            print(f"Error loading game state: {e}")  
            # Don't raise the error - allow the bot to start without data  
            pass

    def add_character(self, character: Character) -> None:  
        """Add a character to the game state"""  
        self.characters[character.name] = character  
        print(f"Added character {character.name} to game state")

    def remove_character(self, name: str) -> bool:  
        """Remove a character from the game state"""  
        if name in self.characters:  
            del self.characters[name]  
            print(f"Removed character {name} from game state")  
            return True  
        return False

    def get_character(self, name: str) -> Optional[Character]:  
        """Get a character by name (case-insensitive)"""  
        name_lower = name.lower()  
        for char_name, character in self.characters.items():  
            if char_name.lower() == name_lower:  
                return character  
        return None

    def get_all_characters(self) -> List[Character]:  
        """Get a list of all characters"""  
        return list(self.characters.values())

    def start_combat(self, initiative_order: List[str]) -> None:  
        """Start combat with the given initiative order"""  
        self.combat_active = True  
        self.round_number = 1  
        self.initiative_order = initiative_order  
        self.current_turn = 0  
        
        # Log combat start
        self.logger.start_combat()
        self.logger.log_combat_start("Combat Started", {
            "Initiative Order": "\n".join(initiative_order)
        })

    def end_combat(self) -> None:  
        """End combat and clean up combat-related states"""  
        self.combat_active = False  
        self.round_number = 0  
        self.initiative_order = []  
        self.current_turn = 0  
        
        # Log combat end
        self.logger.end_combat()

    def next_turn(self) -> Optional[str]:  
        """Advance to next turn in combat, returns name of character whose turn it is"""  
        if not self.combat_active or not self.initiative_order:  
            return None

        self.current_turn = (self.current_turn + 1) % len(self.initiative_order)  
        if self.current_turn == 0:  
            self.round_number += 1  
            # Log round transition
            self.logger.log_round_transition(self.round_number)

        current_character = self.initiative_order[self.current_turn]  
        self.logger.add_event(
            CombatEventType.TURN_START,
            message=f"Turn advanced to {current_character}",
            character=current_character,
            round_number=self.round_number
        )
        return current_character

    async def save_state(self) -> None:  
        """Save current game state to database"""  
        if not self.db:  
            print("Cannot save state: database not initialized")  
            return

        try:  
            # Save all characters  
            for character in self.characters.values():  
                await self.db.save_character(character)

            if self.combat_active:  
                combat_state = {  
                    'active': True,  
                    'round': self.round_number,  
                    'initiative': self.initiative_order,  
                    'current_turn': self.current_turn  
                }  
                self.db._refs['characters'].child('combat_state').set(combat_state)

            print("Game state saved successfully")  
             
        except Exception as e:  
            print(f"Error saving game state: {e}")  
            raise