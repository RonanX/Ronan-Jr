"""
Test harness for combat move functionality with initiative tracking.
"""

import asyncio
import sys
import os
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
import logging

# Add src to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from core.character import Character, Stats, Resources, DefenseStats, StatType
from modules.moves.data import MoveData, Moveset
from core.effects.condition import ConditionType, ConditionEffect

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class CombatState:
    """Track combat state for testing"""
    round_number: int = 1
    current_turn: int = 0
    initiative_order: List[str] = field(default_factory=list)
    characters: Dict[str, Character] = field(default_factory=dict)

class CombatTester:
    """Test harness for combat move functionality"""
    
    def __init__(self):
        self.combat_state = CombatState()
        
    async def setup_test_combat(self):
        """Create test combat with initiative order"""
        # Create characters with different stats for testing
        characters = {
            "Flames": await self.create_character(
                name="Flames",
                str=16, dex=14, con=12, 
                int=10, wis=8, cha=14
            ),
            "Sera": await self.create_character(
                name="Sera",
                str=10, dex=16, con=14,
                int=12, wis=14, cha=12
            )
        }
        
        # Set initiative order
        initiative_order = ["Flames", "Sera"]
        
        # Initialize combat state
        self.combat_state.characters = characters
        self.combat_state.initiative_order = initiative_order
        
        return self.combat_state
        
    async def create_character(self, name: str, **stats) -> Character:
        """Create a test character with given stats"""
        base_stats = {
            StatType.STRENGTH: stats.get('str', 10),
            StatType.DEXTERITY: stats.get('dex', 10),
            StatType.CONSTITUTION: stats.get('con', 10),
            StatType.INTELLIGENCE: stats.get('int', 10),
            StatType.WISDOM: stats.get('wis', 10),
            StatType.CHARISMA: stats.get('cha', 10)
        }
        char_stats = Stats(base=base_stats)
        char_stats.modified = base_stats.copy()
        
        resources = Resources(
            current_hp=50,
            max_hp=50,
            current_mp=30,
            max_mp=30
        )
        
        defense = DefenseStats(
            base_ac=15,
            current_ac=15
        )
        
        return Character(name, stats=char_stats, resources=resources, defense=defense)

    async def run_combat_test(self):
        """Test moves in combat with initiative"""
        logger.info("\n=== Starting Combat Test ===")
        
        # Setup combat
        await self.setup_test_combat()
        
        # Test moves
        test_moves = [
            # Instant roll move
            MoveData(
                name="Quick Strike",
                description="Fast attack that rolls immediately",
                attack_roll="1d20+dex",
                damage="1d6+dex slashing",
                star_cost=1,
                roll_timing="instant"
            ),
            # Active phase roll move
            MoveData(
                name="Power Attack",
                description="Strong attack that rolls in active phase",
                attack_roll="1d20+str",
                damage="2d6+str slashing",
                star_cost=2,
                cast_time=1,
                roll_timing="active"
            ),
            # Roll per turn move
            MoveData(
                name="Burning Weapon",
                description="Weapon catches fire;Deals extra damage each turn",
                attack_roll="1d20+str",
                damage="1d8+str slashing, 1d4 fire",
                star_cost=2,
                duration=3,
                roll_timing="per_turn"
            ),
            # Save move
            MoveData(
                name="Mind Blast",
                description="Psychic blast with confused condition",
                damage="2d6 psychic",
                star_cost=2,
                save_type="wis",
                save_dc="8+prof+int",
                half_on_save=True,
                conditions=[ConditionType.CONFUSED],
                roll_timing="instant"
            )
        ]
        
        # Add moves to characters
        flames = self.combat_state.characters["Flames"]
        sera = self.combat_state.characters["Sera"]
        
        for move in test_moves:
            flames.add_move(move)
        
        # Run 4 rounds
        for round_num in range(1, 5):
            self.combat_state.round_number = round_num
            logger.info(f"\n=== Round {round_num} ===")
            
            # Process each turn
            for i, char_name in enumerate(self.combat_state.initiative_order):
                self.combat_state.current_turn = i
                char = self.combat_state.characters[char_name]
                
                logger.info(f"\n{char_name}'s Turn:")
                
                # Process turn start effects
                turn_messages = []
                for effect in char.effects:
                    if msgs := effect.on_turn_start(char, round_num, char_name):
                        if isinstance(msgs, list):
                            turn_messages.extend(msgs)
                        else:
                            turn_messages.append(msgs)
                
                if turn_messages:
                    logger.info("Turn Start Effects:")
                    for msg in turn_messages:
                        logger.info(f"  {msg}")
                
                # Use a move if it's Flames' turn
                if char_name == "Flames":
                    if round_num == 1:
                        # Test instant roll
                        logger.info("\nUsing Quick Strike (instant roll):")
                        move = flames.get_move("Quick Strike")
                        flames.add_move(move)
                    elif round_num == 2:
                        # Test active phase roll
                        logger.info("\nUsing Power Attack (active phase roll):")
                        move = flames.get_move("Power Attack")
                        flames.add_move(move)
                    elif round_num == 3:
                        # Test per turn roll
                        logger.info("\nUsing Burning Weapon (per turn roll):")
                        move = flames.get_move("Burning Weapon")
                        flames.add_move(move)
                        
                # Process turn end effects
                effect_messages = []
                for effect in char.effects[:]:
                    if msgs := effect.on_turn_end(char, round_num, char_name):
                        if isinstance(msgs, list):
                            effect_messages.extend(msgs)
                        else:
                            effect_messages.append(msgs)
                            
                    # Check for expired effects
                    if effect.is_expired:
                        if expire_msg := effect.on_expire(char):
                            effect_messages.append(expire_msg)
                        char.effects.remove(effect)
                
                if effect_messages:
                    logger.info("\nTurn End Effects:")
                    for msg in effect_messages:
                        logger.info(f"  {msg}")
            
            # End of round - refresh stars
            for char in self.combat_state.characters.values():
                char.refresh_stars()
                
            logger.info("\nEnd of Round")

async def main():
    """Run all tests"""
    tester = CombatTester()
    await tester.run_combat_test()
    
if __name__ == "__main__":
    asyncio.run(main())