"""
## src/modules/moves/loader.py

Move data loading and import/export functionality.
Handles loading from database, importing/exporting as JSON,
and creation from command parameters.
"""

import json
from typing import Optional, Dict, Any, List, Tuple
import logging
from .data import MoveData, Moveset

logger = logging.getLogger(__name__)

class MoveLoader:
    """
    Handles loading move data from various sources.
    
    Features:
    - Load from database (global or character-specific)
    - Import/export as JSON
    - Create moves from command parameters
    - Move data validation
    """
    
    @staticmethod
    async def load_character_moveset(database, character_name: str) -> Optional[Moveset]:
        """
        Load a character's moveset, including any global reference.
        
        This will:
        1. Load the character's local moves
        2. If the character has a global moveset reference, load and merge it
        3. Return the complete moveset with both global and local moves
        """
        try:
            # Load character data
            char_data = await database.load_character(character_name)
            if not char_data:
                print(f"Loader: Character '{character_name}' not found")
                return None
            
            # Check for inline moves data
            moveset = None
            if 'moves' in char_data:
                # Create moveset from character's moves
                moveset_data = {
                    "reference": char_data.get("moveset_reference"),
                    "moves": char_data.get("moves", {})
                }
                moveset = Moveset.from_dict(moveset_data)
                
            # If no inline moves, check for reference
            elif 'moveset_reference' in char_data and char_data['moveset_reference']:
                # Load from global moveset
                global_data = await database.load_moveset(char_data['moveset_reference'])
                if global_data:
                    # Create with reference
                    moveset = Moveset(
                        reference=char_data['moveset_reference']
                    )
                    # Add all moves from global moveset
                    for move_name, move_data in global_data.items():
                        move = MoveData.from_dict(move_data)
                        moveset.add_move(move)
                        
            # If no moveset data found, create empty one
            if not moveset:
                moveset = Moveset()
                
            return moveset
            
        except Exception as e:
            logger.error(f"Error loading moves for {character_name}: {e}")
            print(f"Loader ERROR: Failed to load moveset for '{character_name}' - {str(e)}")
            return Moveset()  # Return empty moveset on error
    
    @staticmethod
    async def save_character_moveset(database, character_name: str, moveset: Moveset) -> bool:
        """
        Save a character's moveset directly to their data.
        
        This will:
        1. Save the moveset directly in the character's data
        2. Save the reference to any global moveset
        """
        try:
            # Get character
            char = database.bot.game_state.get_character(character_name)
            if not char:
                print(f"Loader: Character '{character_name}' not found")
                return False
            
            # Update character's moveset
            char.moveset = moveset
            
            # Save to database
            await database.save_character(char)
            return True
            
        except Exception as e:
            logger.error(f"Error saving moveset for {character_name}: {e}")
            print(f"Loader ERROR: Failed to save moveset for '{character_name}' - {str(e)}")
            return False
    
    @staticmethod
    async def save_global_moveset(database, name: str, moveset: Moveset, 
                            description: Optional[str] = None) -> bool:
        """
        Save a moveset to the global movesets collection.
        
        This improved version:
        1. Better handles empty movesets
        2. Adds more detailed metadata
        3. Provides clearer error handling 
        """
        try:
            # Extract moves data
            moves_data = {}
            for move_name, move in moveset.moves.items():
                moves_data[move_name] = move.to_dict()
            
            if not moves_data:
                print(f"Loader WARNING: No moves found in moveset '{name}'")
                return False
                
            # Create metadata with timestamp
            from datetime import datetime
            metadata = {
                "name": name,
                "move_count": len(moves_data),
                "description": description or "No description provided",
                "timestamp": datetime.utcnow().isoformat(),
                "moves": list(moves_data.keys())  # List of move names for quick reference
            }
                
            # Save to global movesets collection with metadata
            try:
                await database.save_moveset(name, moves_data, description)
                print(f"Saved moveset '{name}' with {len(moves_data)} moves")
                return True
            except AttributeError:
                # Fallback for older database implementations
                if hasattr(database, '_refs') and 'shared_movesets' in database._refs:
                    database._refs['shared_movesets'].child(name).set({
                        "metadata": metadata,
                        "moves": moves_data
                    })
                    print(f"Saved moveset '{name}' using fallback method")
                    return True
                else:
                    raise
                    
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error saving global moveset {name}: {e}")
            print(f"Loader ERROR: Failed to save global moveset '{name}' - {str(e)}")
            return False

    @staticmethod
    async def load_global_moveset(database, name: str) -> Optional[Moveset]:
        """
        Load a moveset from the global collection.
        
        This improved version:
        1. Better handles missing movesets
        2. Provides more detailed logging
        3. Handles movesets with differently structured data
        """
        try:
            # Get moveset data
            print(f"Loading global moveset '{name}'...")
            
            moves_data = None
            try:
                # Try standard load method first
                moves_data = await database.load_moveset(name)
            except AttributeError:
                # Fallback for older database implementations
                if hasattr(database, '_refs') and 'shared_movesets' in database._refs:
                    moveset_data = database._refs['shared_movesets'].child(name).get()
                    if moveset_data:
                        # Handle different data structures
                        if "moves" in moveset_data:
                            moves_data = moveset_data["moves"]
                        else:
                            # Assume the whole object is moves data without metadata
                            metadata_keys = {"name", "description", "move_count", "timestamp", "metadata"}
                            if not any(key in metadata_keys for key in moveset_data.keys()):
                                moves_data = moveset_data
                
            if not moves_data:
                print(f"Loader: Global moveset '{name}' not found")
                return None
            
            # Create moveset with reference
            moveset = Moveset(
                reference=name
            )
            
            # Count successful moves
            move_count = 0
            
            # Add all moves
            for move_name, move_data in moves_data.items():
                if isinstance(move_data, dict):
                    try:
                        move = MoveData.from_dict(move_data)
                        moveset.add_move(move)
                        move_count += 1
                    except Exception as e:
                        print(f"Error loading move '{move_name}': {e}")
            
            print(f"Loaded moveset '{name}' with {move_count} moves")
            return moveset
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error loading global moveset {name}: {e}")
            print(f"Loader ERROR: Failed to load global moveset '{name}' - {str(e)}")
            return None
    
    @staticmethod
    async def assign_global_moveset(database, bot, character_name: str, moveset_name: str) -> bool:
        """
        Assign a global moveset to a character.
        
        This will:
        1. Check if the global moveset exists
        2. Update the character's moveset reference
        3. Clear any existing character-specific moves
        
        Args:
            database: The database instance
            bot: The bot instance (needed to access game_state)
            character_name: Name of the character to receive the moveset
            moveset_name: Name of the global moveset to assign
        """
        try:
            # Verify global moveset exists
            global_data = await database.load_moveset(moveset_name)
            if not global_data:
                print(f"Loader: Global moveset '{moveset_name}' not found")
                return False
            
            # Get character from the game state
            char = bot.game_state.get_character(character_name)
            if not char:
                print(f"Loader: Character '{character_name}' not found")
                return False
            
            # Create new moveset with reference
            char.moveset = Moveset(reference=moveset_name)
            
            # Add all moves from global moveset
            for move_name, move_data in global_data.items():
                if isinstance(move_data, dict):
                    move = MoveData.from_dict(move_data)
                    char.moveset.add_move(move)
            
            # Save character
            await database.save_character(char)
            return True
            
        except Exception as e:
            logger.error(f"Error assigning moveset {moveset_name} to {character_name}: {e}")
            print(f"Loader ERROR: Failed to assign moveset '{moveset_name}' to '{character_name}' - {str(e)}")
            return False
    
    @staticmethod
    def export_moveset(moveset: Moveset, pretty: bool = True) -> str:
        """Export moveset as JSON string"""
        try:
            if pretty:
                return json.dumps(moveset.to_dict(), indent=2)
            return json.dumps(moveset.to_dict())
        except Exception as e:
            logger.error(f"Error exporting moveset: {e}")
            print(f"Loader ERROR: Failed to export moveset - {str(e)}")
            return "{}"
    
    @staticmethod
    def import_moveset(json_str: str) -> Optional[Moveset]:
        """Import moveset from JSON string"""
        try:
            data = json.loads(json_str)
            return Moveset.from_dict(data)
        except Exception as e:
            logger.error(f"Error importing moveset: {e}")
            print(f"Loader ERROR: Failed to import moveset - {str(e)}")
            return None
    
    @staticmethod
    def create_move_from_command(
        name: str,
        description: str,
        **kwargs
    ) -> Optional[MoveData]:
        """
        Create move data from command parameters.
        Used when saving moves created with commands.
        """
        try:
            # Build move with all available parameters
            move = MoveData(
                name=name,
                description=description,
                mp_cost=kwargs.get('mp_cost', 0),
                hp_cost=kwargs.get('hp_cost', 0),
                star_cost=kwargs.get('star_cost', 0),
                cast_time=kwargs.get('cast_time'),
                cooldown=kwargs.get('cooldown'),
                duration=kwargs.get('duration'),
                cast_description=kwargs.get('cast_description'),
                uses=kwargs.get('uses'),
                attack_roll=kwargs.get('attack_roll'),
                damage=kwargs.get('damage'),
                crit_range=kwargs.get('crit_range', 20),
                targets=kwargs.get('targets'),
                save_type=kwargs.get('save_type'),
                save_dc=kwargs.get('save_dc'),
                half_on_save=kwargs.get('half_on_save', False),
                roll_timing=kwargs.get('roll_timing', "active"),
                enable_heat_tracking=kwargs.get('track_heat', False)
            )
            
            # Handle conditions list
            if 'conditions' in kwargs and kwargs['conditions']:
                if isinstance(kwargs['conditions'], list):
                    move.conditions = kwargs['conditions']
                elif isinstance(kwargs['conditions'], str):
                    move.conditions = [c.strip() for c in kwargs['conditions'].split(',')]
                
            return move
            
        except Exception as e:
            logger.error(f"Error creating move: {e}")
            print(f"Loader ERROR: Failed to create move '{name}' - {str(e)}")
            return None
    
    @staticmethod
    def validate_move_data(move: MoveData) -> Tuple[bool, Optional[str]]:
        """Validate move data"""
        # Check required fields
        if not move.name:
            return False, "Move must have a name"
            
        # Validate resource costs
        if move.mp_cost < -1000 or move.mp_cost > 1000:
            return False, "MP cost must be between -1000 and 1000"
            
        if move.hp_cost < -1000 or move.hp_cost > 1000:
            return False, "HP cost must be between -1000 and 1000"
            
        if move.star_cost < 0 or move.star_cost > 5:
            return False, "Star cost must be between 0 and 5"
            
        # Validate timing
        if move.cast_time is not None and move.cast_time < 0:
            return False, "Cast time cannot be negative"
            
        if move.duration is not None and move.duration < 0:
            return False, "Duration cannot be negative"
            
        if move.cooldown is not None and move.cooldown < 0:
            return False, "Cooldown cannot be negative"
            
        # Validate uses
        if move.uses is not None and move.uses < 1:
            return False, "Uses must be at least 1"
            
        # Validate combat parameters
        if move.attack_roll and not any(x in move.attack_roll.lower() for x in ['d20', 'd12']):
            return False, "Attack roll must use d20 or d12"
            
        if move.crit_range and (move.crit_range < 1 or move.crit_range > 20):
            return False, "Crit range must be between 1 and 20"
            
        # Validate roll timing
        if move.roll_timing not in ["instant", "active", "per_turn"]:
            return False, "Roll timing must be 'instant', 'active', or 'per_turn'"
            
        return True, None