"""
Test harness for moveset functionality.
"""

import asyncio
import sys
import os
from typing import Optional, List, Dict, Any
import logging

# Add src to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from core.database import Database
from core.character import Character, Stats, Resources, DefenseStats, StatType
from modules.moves.data import MoveData, Moveset

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MovesetTester:
    """Test harness for moveset functionality"""
    
    def __init__(self):
        self.db = Database()
        
    async def setup_test_character(self) -> Character:
        """Create a test character with basic stats"""
        # Basic stats
        stats = Stats(
            base={
                StatType.STRENGTH: 15,
                StatType.DEXTERITY: 14,
                StatType.CONSTITUTION: 13,
                StatType.INTELLIGENCE: 12,
                StatType.WISDOM: 11,
                StatType.CHARISMA: 10
            }
        )
        stats.modified = stats.base.copy()
        
        # Resources
        resources = Resources(
            current_hp=50,
            max_hp=50,
            current_mp=30,
            max_mp=30
        )
        
        # Defense
        defense = DefenseStats(
            base_ac=15,
            current_ac=15
        )
        
        # Create character
        char = Character(
            name="TestChar",
            stats=stats,
            resources=resources,
            defense=defense
        )
        
        # Save to database
        await self.db.save_character(char)
        logger.info("Created test character: TestChar")
        
        return char
        
    async def create_test_moves(self, char: Character) -> List[MoveData]:
        """Create some test moves"""
        moves = [
            MoveData(
                name="Basic Attack",
                description="A simple attack",
                mp_cost=0,
                star_cost=1
            ),
            MoveData(
                name="Fireball",
                description="Launch a ball of fire;Deals fire damage;May cause burn",
                mp_cost=10,
                star_cost=2,
                cooldown=3
            ),
            MoveData(
                name="Ultimate",
                description="Powerful ultimate move",
                mp_cost=20,
                star_cost=3,
                uses=1,
                cast_time=1,
                duration=2,
                cooldown=5
            )
        ]
        
        # Add moves to character
        for move in moves:
            char.add_move(move)
            
        # Save character
        await self.db.save_character(char)
        logger.info(f"Added {len(moves)} test moves to TestChar")
        
        return moves
        
    async def test_character_movesets(self):
        """Test character-specific moveset functionality"""
        try:
            # Setup
            char = await self.setup_test_character()
            moves = await self.create_test_moves(char)
            
            # Test saving character moveset
            logger.info("\nTesting character moveset save...")
            # Save movesets as part of character data
            char_dict = char.to_dict()
            char_dict['movesets'] = char.moveset.to_dict()
            await self.db.save_character(char)
            await self.db.save_character_moveset(char.name, char.moveset.to_dict())
            
            # Test loading character moveset
            logger.info("\nTesting character moveset load...")
            loaded_data = await self.db.load_character_moveset(char.name)
            if loaded_data:
                loaded_moveset = Moveset.from_dict(loaded_data)
                logger.info(f"Loaded {len(loaded_moveset.moves)} moves")
                for name, move in loaded_moveset.moves.items():
                    logger.info(f"  {name}: {move.description}")
            else:
                logger.error("Failed to load character moveset")
                
            return True
            
        except Exception as e:
            logger.error(f"Error in character moveset test: {e}")
            return False
            
    async def test_shared_movesets(self):
        """Test shared moveset functionality"""
        try:
            # Create shared moveset from test character
            char = await self.setup_test_character()
            moves = await self.create_test_moves(char)
            
            # Save as shared moveset
            logger.info("\nTesting shared moveset save...")
            moveset_name = "TestMoveset"
            await self.db.save_shared_moveset(
                moveset_name,
                {
                    "moves": char.moveset.to_dict(),
                    "source_character": char.name,
                    "description": "Test moveset with various moves"
                }
            )
            
            # List shared movesets
            logger.info("\nTesting shared moveset list...")
            movesets = await self.db.list_shared_movesets()
            for ms in movesets:
                logger.info(f"Found moveset: {ms['name']}")
                
            # Load shared moveset
            logger.info("\nTesting shared moveset load...")
            loaded = await self.db.load_shared_moveset(moveset_name)
            if loaded:
                moveset = Moveset.from_dict(loaded["moves"])
                logger.info(f"Loaded {len(moveset.moves)} moves from shared moveset")
                for name, move in moveset.moves.items():
                    logger.info(f"  {name}: {move.description}")
            else:
                logger.error("Failed to load shared moveset")
                
            # Delete shared moveset
            logger.info("\nTesting shared moveset delete...")
            deleted = await self.db.delete_shared_moveset(moveset_name)
            logger.info(f"Moveset deleted: {deleted}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error in shared moveset test: {e}")
            return False

async def main():
    """Run all tests"""
    tester = MovesetTester()
    
    # Run tests
    logger.info("Starting moveset tests...")
    
    char_test = await tester.test_character_movesets()
    logger.info(f"\nCharacter moveset tests: {'PASSED' if char_test else 'FAILED'}")
    
    shared_test = await tester.test_shared_movesets()
    logger.info(f"\nShared moveset tests: {'PASSED' if shared_test else 'FAILED'}")
    
if __name__ == "__main__":
    asyncio.run(main())