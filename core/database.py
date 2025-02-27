"""
Database Management System (src/core/database.py)

This file handles all database operations using Firebase. It's the only file that should
directly interact with Firebase, making it the single source of truth for data persistence.

Key Features:
- Single characters collection for all character data
- Efficient batch operations
- Automated error handling and logging
- Migration support for old data structure

When to Modify:
- Adding new types of data to save/load
- Changing how data is structured in Firebase
- Adding new database operations
- Modifying error handling for database operations

Dependencies:
- Firebase Admin SDK
- serviceAccountKey.json for Firebase authentication
- secrets.env for Firebase configuration
"""

from datetime import datetime
import os
import logging
import firebase_admin
from firebase_admin import credentials, db
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class Database:
    """Handles all database operations using Firebase Realtime Database."""
    
    def __init__(self):
        self.initialized = False
        self._db = None
        self._refs = {}

    async def initialize(self) -> None:
        """Initialize Firebase connection and run any needed migrations"""
        if self.initialized:
            return

        try:
            database_url = "https://ronan-jr-s-brain-default-rtdb.firebaseio.com"
            cred = credentials.Certificate("D:/Games/Campaigns/Ronan Jr/serviceAccountKey.json")
            firebase_admin.initialize_app(cred, {
                'databaseURL': database_url
            })

            # Initialize database references
            self._db = db.reference('/')
            self._refs = {
                'characters': db.reference('characters'),
                'shared_movesets': db.reference('shared_movesets'),
                'shared_moves': db.reference('shared_moves'),
                'initiative_saves': db.reference('initiative_saves')  # Add this line
            }

            await self._check_and_migrate()
            self.initialized = True
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {str(e)}", exc_info=True)
            raise

    # Move Management Methods
    async def save_moveset(self, name: str, moveset_data: Dict[str, Any]) -> None:
        """Save a moveset to the database"""
        if not self.initialized:
            await self.initialize()
            
        try:
            self._refs['movesets'].child(name).set(moveset_data)
            logger.info(f"Moveset {name} saved successfully")
            
        except Exception as e:
            logger.error(f"Failed to save moveset: {str(e)}", exc_info=True)
            raise

    async def load_moveset(self, name: str) -> Optional[Dict[str, Any]]:
        """Load a moveset from the database"""
        if not self.initialized:
            await self.initialize()
            
        try:
            moveset = self._refs['movesets'].child(name).get()
            
            if not moveset:
                logger.warning(f"Moveset {name} not found in database")
                return None
                
            logger.info(f"Moveset {name} loaded successfully")
            return moveset
            
        except Exception as e:
            logger.error(f"Failed to load moveset: {str(e)}", exc_info=True)
            raise
            
    async def share_move(self, move_data: Dict[str, Any]) -> str:
        """
        Share a move to make it available to other characters.
        Returns the share ID.
        """
        if not self.initialized:
            await self.initialize()
            
        try:
            # Generate a unique ID for the shared move
            share_ref = self._refs['shared_moves'].push()
            share_id = share_ref.key
            
            # Save move data
            share_ref.set({
                'data': move_data,
                'created_at': {'.sv': 'timestamp'}
            })
            
            logger.info(f"Move shared successfully with ID: {share_id}")
            return share_id
            
        except Exception as e:
            logger.error(f"Failed to share move: {str(e)}", exc_info=True)
            raise
            
    async def get_shared_move(self, share_id: str) -> Optional[Dict[str, Any]]:
        """Get a shared move by its share ID"""
        if not self.initialized:
            await self.initialize()
            
        try:
            move_data = self._refs['shared_moves'].child(share_id).get()
            
            if not move_data:
                logger.warning(f"Shared move {share_id} not found")
                return None
                
            logger.info(f"Shared move {share_id} loaded successfully")
            return move_data.get('data')
            
        except Exception as e:
            logger.error(f"Failed to load shared move: {str(e)}", exc_info=True)
            raise

    async def delete_shared_move(self, share_id: str) -> bool:
        """Delete a shared move. Returns True if found and deleted."""
        if not self.initialized:
            await self.initialize()
            
        try:
            if not self._refs['shared_moves'].child(share_id).get():
                logger.warning(f"Shared move {share_id} not found")
                return False
                
            self._refs['shared_moves'].child(share_id).delete()
            logger.info(f"Shared move {share_id} deleted successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete shared move: {str(e)}", exc_info=True)
            raise

    async def _check_and_migrate(self) -> None:
        """Check if old data structure exists and migrate if needed"""
        try:
            old_base_stats = db.reference('base_stats').get()
            old_char_data = db.reference('character_data').get()

            if old_base_stats or old_char_data:
                logger.info("Found old data structure, starting migration...")
                
                # Migrate each character
                migrated = 0
                for char_name in set(list(old_base_stats.keys()) + list(old_char_data.keys())):
                    base = old_base_stats.get(char_name, {})
                    current = old_char_data.get(char_name, {})
                    
                    # Calculate spell save DC
                    base_stats = base.get("stats", {})
                    proficiency = current.get("proficiency", 2)
                    spellcasting_mods = [
                        (base_stats.get("intelligence", 10) - 10) // 2,
                        (base_stats.get("wisdom", 10) - 10) // 2,
                        (base_stats.get("charisma", 10) - 10) // 2
                    ]
                    spell_save_dc = 8 + proficiency + max(spellcasting_mods)
                    
                    # Construct new character data format
                    new_data = {
                        "name": char_name,
                        "stats": {
                            "base": base.get("stats", {}),
                            "modified": current.get("stats", base.get("stats", {}))
                        },
                        "resources": {
                            "current_hp": current.get("current_hp", base.get("max_hp", 0)),
                            "max_hp": base.get("max_hp", 0),
                            "current_mp": current.get("current_mp", base.get("max_mp", 0)),
                            "max_mp": base.get("max_mp", 0),
                            "temp_hp": current.get("temp_hp", 0)
                        },
                        "defense": {
                            "base_ac": base.get("base_ac", 10),
                            "current_ac": current.get("ac", base.get("base_ac", 10)),
                            "damage_resistances": current.get("damage_resistances", {}),
                            "damage_vulnerabilities": current.get("damage_vulnerabilities", {})
                        },
                        "effects": current.get("status_effects", []),
                        "spell_slots": current.get("spell_slots", {}),
                        "proficiency": proficiency,
                        "spell_save_dc": spell_save_dc
                    }
                    
                    # Save in new format
                    self._refs['characters'].child(char_name).set(new_data)
                    migrated += 1

                # Delete old data structure if migration successful
                db.reference('base_stats').delete()
                db.reference('character_data').delete()
                
                logger.info(f"Migration complete: {migrated} characters migrated")
            else:
                logger.info("No migration needed")

        except Exception as e:
            logger.error(f"Error during migration: {str(e)}", exc_info=True)
            raise

    async def save_character(self, character, debug_paths=None) -> None:
        """
        Save character data to the database with optional change tracking
        
        Args:
            character: Character object to save
            debug_paths: List of paths to monitor for changes (e.g. ['moveset', 'effects'])
        """
        if not self.initialized:
            await self.initialize()

        try:
            # Get previous state for diff if debugging
            old_data = None
            if debug_paths:
                old_data = self._refs['characters'].child(character.name).get()
                
            # Convert character to dictionary
            char_dict = character.to_dict()
            
            # Save directly to characters collection
            self._refs['characters'].child(character.name).set(char_dict)
            
            # Show changes if debug paths specified
            if debug_paths and old_data:
                print(f"\n===== DB Changes for '{character.name}' =====")
                for path in debug_paths:
                    self._print_path_changes(old_data, char_dict, path)
            
            # Normal logging
            if not getattr(self, 'debug_mode', False):
                logger.info(f"Character {character.name} saved successfully")
            
        except Exception as e:
            logger.error(f"Failed to save character: {str(e)}", exc_info=True)
            raise

    async def load_character(self, name: str) -> Optional[Dict[str, Any]]:
        """Load character data from the database"""
        if not self.initialized:
            await self.initialize()

        try:
            # Get character data
            char_data = self._refs['characters'].child(name).get()
            
            if not char_data:
                logger.warning(f"Character {name} not found in database")
                return None

            # Ensure proficiency and spell_save_dc exist
            if 'proficiency' not in char_data:
                char_data['proficiency'] = 2
                
            if 'spell_save_dc' not in char_data:
                # Calculate if missing
                base_stats = char_data.get('stats', {}).get('base', {})
                proficiency = char_data['proficiency']
                spellcasting_mods = [
                    (base_stats.get("intelligence", 10) - 10) // 2,
                    (base_stats.get("wisdom", 10) - 10) // 2,
                    (base_stats.get("charisma", 10) - 10) // 2
                ]
                char_data['spell_save_dc'] = 8 + proficiency + max(spellcasting_mods)

            logger.info(f"Character {name} loaded successfully")
            return char_data
            
        except Exception as e:
            logger.error(f"Failed to load character: {str(e)}", exc_info=True)
            raise

    async def delete_character(self, name: str) -> bool:
        """Delete a character from the database"""
        if not self.initialized:
            await self.initialize()

        try:
            # Check if character exists
            if not self._refs['characters'].child(name).get():
                logger.warning(f"Character {name} not found in database")
                return False

            # Delete from characters collection
            self._refs['characters'].child(name).delete()
            
            logger.info(f"Character {name} deleted successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete character: {str(e)}", exc_info=True)
            raise

    async def list_characters(self) -> List[str]:
        """Get a list of all character names in the database"""
        if not self.initialized:
            await self.initialize()

        try:
            char_data = self._refs['characters'].get()
            return list(char_data.keys()) if char_data else []
        except Exception as e:
            logger.error(f"Failed to list characters: {str(e)}", exc_info=True)
            raise

    ### Firebase real-time logging ###
    def _print_path_changes(self, old_data, new_data, path):
        """
        Print changes for a specific path in the data.
        Shows only what changed in a compact format.
        
        Args:
            old_data: Previous data state
            new_data: New data state
            path: Path to check (e.g. 'moveset', 'effects.0')
        """
        # Navigate to the path in both objects
        old_value = self._get_nested_value(old_data, path) 
        new_value = self._get_nested_value(new_data, path)
        
        # Skip if both are None
        if old_value is None and new_value is None:
            return
            
        # Handle different cases
        if old_value is None:
            print(f"\n----- Added: {path} -----")
            self._print_compact(new_value)
        elif new_value is None:
            print(f"\n----- Removed: {path} -----")
            self._print_compact(old_value)
        elif old_value != new_value:
            print(f"\n----- Changed: {path} -----")
            if isinstance(old_value, dict) and isinstance(new_value, dict):
                self._print_dict_diff(old_value, new_value)
            elif isinstance(old_value, list) and isinstance(new_value, list):
                self._print_list_diff(old_value, new_value)
            else:
                print(f"Old: {old_value}")
                print(f"New: {new_value}")

    def _get_nested_value(self, data, path):
        """Get value at nested path like 'moveset.moves.fireball'"""
        if data is None:
            return None
            
        current = data
        parts = path.split('.')
        
        for part in parts:
            # Handle list indices
            if part.isdigit() and isinstance(current, list):
                index = int(part)
                if index < len(current):
                    current = current[index]
                else:
                    return None
            # Handle dict keys
            elif isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
                
        return current

    def _print_compact(self, value, max_depth=2, indent=0):
        """Print a compact representation of a value"""
        if isinstance(value, dict):
            if indent >= max_depth * 2:
                print(" " * indent + "{...}")
                return
                
            print(" " * indent + "{")
            for k, v in value.items():
                print(" " * (indent + 2) + f"{k}: ", end="")
                if isinstance(v, (dict, list)):
                    print()
                    self._print_compact(v, max_depth, indent + 4)
                else:
                    print(v)
            print(" " * indent + "}")
            
        elif isinstance(value, list):
            if indent >= max_depth * 2:
                print(" " * indent + f"[...] ({len(value)} items)")
                return
                
            print(" " * indent + "[")
            # Only show first 3 items to keep it compact
            for i, item in enumerate(value[:3]):
                print(" " * (indent + 2) + f"[{i}]: ", end="")
                if isinstance(item, (dict, list)):
                    print()
                    self._print_compact(item, max_depth, indent + 4)
                else:
                    print(item)
            if len(value) > 3:
                print(" " * (indent + 2) + f"... ({len(value) - 3} more items)")
            print(" " * indent + "]")
            
        else:
            print(value)

    def _print_dict_diff(self, old, new, indent=0):
        """Print differences between two dictionaries"""
        all_keys = set(old.keys()) | set(new.keys())
        
        for key in sorted(all_keys):
            # Added key
            if key not in old:
                print(" " * indent + f"+ {key}: ", end="")
                self._print_compact(new[key], max_depth=2, indent=indent)
            # Removed key
            elif key not in new:
                print(" " * indent + f"- {key}")
            # Changed value
            elif old[key] != new[key]:
                print(" " * indent + f"~ {key}:")
                if isinstance(old[key], dict) and isinstance(new[key], dict):
                    self._print_dict_diff(old[key], new[key], indent + 2)
                elif isinstance(old[key], list) and isinstance(new[key], list):
                    self._print_list_diff(old[key], new[key], indent + 2)
                else:
                    print(" " * (indent + 2) + f"From: {old[key]}")
                    print(" " * (indent + 2) + f"To:   {new[key]}")

    def _print_list_diff(self, old, new, indent=0):
        """Print differences between two lists"""
        # Simple case - different lengths
        if len(old) != len(new):
            print(" " * indent + f"Length changed: {len(old)} → {len(new)}")
            
        # If lists are small, show item differences
        if len(old) <= 5 and len(new) <= 5:
            # Find common length to compare
            common_len = min(len(old), len(new))
            
            # Check each item
            for i in range(common_len):
                if old[i] != new[i]:
                    print(" " * indent + f"Item [{i}] changed:")
                    if isinstance(old[i], dict) and isinstance(new[i], dict):
                        self._print_dict_diff(old[i], new[i], indent + 2)
                    else:
                        print(" " * (indent + 2) + f"From: {old[i]}")
                        print(" " * (indent + 2) + f"To:   {new[i]}")
            
            # Show added items
            for i in range(len(old), len(new)):
                print(" " * indent + f"+ Item [{i}]: {new[i]}")
                
            # Show removed items
            for i in range(len(new), len(old)):
                print(" " * indent + f"- Item [{i}]: {old[i]}")
        else:
            print(" " * indent + "List too large to show detailed diff")

    ### End of firebase real-time logging ###

    # Moveset Management Methods
    async def save_moveset(self, name: str, moves_data: Dict[str, Any], description: Optional[str] = None) -> bool:
        """Save a moveset to the global movesets collection"""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Create metadata
            metadata = {
                "name": name,
                "move_count": len(moves_data),
                "description": description or "No description provided",
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Save to global movesets collection with metadata
            self._refs['shared_movesets'].child(name).set({
                "metadata": metadata,
                "moves": moves_data
            })
            
            logger.info(f"Moveset {name} saved successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save moveset: {str(e)}", exc_info=True)
            return False

    async def load_moveset(self, name: str) -> Optional[Dict[str, Any]]:
        """Load a moveset from the global collection"""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Get data from shared movesets
            moveset_data = self._refs['shared_movesets'].child(name).get()
            
            if not moveset_data:
                logger.warning(f"Moveset {name} not found in database")
                return None
                
            # Extract just the moves data
            moves_data = moveset_data.get('moves', {})
            
            logger.info(f"Moveset {name} loaded successfully")
            return moves_data
            
        except Exception as e:
            logger.error(f"Failed to load moveset: {str(e)}", exc_info=True)
            return None

    async def list_movesets(self) -> List[Dict[str, Any]]:
        """List all available shared movesets with metadata"""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Get all movesets
            movesets_data = self._refs['shared_movesets'].get()
            
            if not movesets_data:
                return []
                
            # Extract metadata for each moveset
            result = []
            for name, data in movesets_data.items():
                metadata = data.get('metadata', {})
                if not metadata:
                    # If no metadata, create basic info
                    metadata = {
                        "name": name,
                        "move_count": len(data.get('moves', {})),
                        "description": "No description"
                    }
                
                # Ensure name is included
                metadata["name"] = name
                
                result.append(metadata)
                
            return result
            
        except Exception as e:
            logger.error(f"Failed to list movesets: {str(e)}", exc_info=True)
            return []

    async def delete_moveset(self, name: str) -> bool:
        """Delete a moveset from the global collection"""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Check if moveset exists
            if not self._refs['shared_movesets'].child(name).get():
                logger.warning(f"Moveset {name} not found")
                return False
                
            # Delete the moveset
            self._refs['shared_movesets'].child(name).delete()
            
            logger.info(f"Moveset {name} deleted successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete moveset: {str(e)}", exc_info=True)
            return False

    async def get_moveset_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific moveset"""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Get data from shared movesets
            moveset_data = self._refs['shared_movesets'].child(name).get()
            
            if not moveset_data:
                return None
                
            # Get metadata or generate basic info
            metadata = moveset_data.get('metadata', {})
            if not metadata:
                metadata = {
                    "name": name,
                    "move_count": len(moveset_data.get('moves', {})),
                    "description": "No description"
                }
                
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to get moveset metadata: {str(e)}", exc_info=True)
            return None