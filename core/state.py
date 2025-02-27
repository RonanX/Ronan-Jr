"""
Game State Manager (src/core/state.py)

This file manages the active game state in memory, acting as a cache between the bot
and the database. It tracks all current game information including characters,
combat status, and initiative order.
"""

from typing import Dict, List, Optional
import logging
from .character import Character

logger = logging.getLogger(__name__)

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
                            logger.error(f"Error loading character {name}: {e}")
                            continue
                            
            logger.info(f"Loaded {len(self.characters)} characters into game state")
            
        except Exception as e:
            logger.error(f"Error loading game state: {e}", exc_info=True)
            # Don't raise the error - allow the bot to start without data
            pass

    def add_character(self, character: Character) -> None:
        """Add a character to the game state"""
        self.characters[character.name] = character
        logger.info(f"Added character {character.name} to game state")

    def remove_character(self, name: str) -> bool:
        """Remove a character from the game state"""
        if name in self.characters:
            del self.characters[name]
            logger.info(f"Removed character {name} from game state")
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
        logger.info("Combat started")

    def end_combat(self) -> None:
        """End combat and clean up combat-related states"""
        self.combat_active = False
        self.round_number = 0
        self.initiative_order = []
        self.current_turn = 0
        logger.info("Combat ended")

    def next_turn(self) -> Optional[str]:
        """Advance to next turn in combat, returns name of character whose turn it is"""
        if not self.combat_active or not self.initiative_order:
            return None

        self.current_turn = (self.current_turn + 1) % len(self.initiative_order)
        if self.current_turn == 0:
            self.round_number += 1
            logger.info(f"Starting round {self.round_number}")

        current_character = self.initiative_order[self.current_turn]
        logger.info(f"Turn advanced to {current_character}")
        return current_character

    async def save_state(self) -> None:
        """Save current game state to database"""
        if not self.db:
            logger.error("Cannot save state: database not initialized")
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

            logger.info("Game state saved successfully")
            
        except Exception as e:
            logger.error(f"Error saving game state: {e}", exc_info=True)
            raise
