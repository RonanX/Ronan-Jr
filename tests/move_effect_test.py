"""
Test harness for move effect system improvements.

This script creates test characters and simulates using different types of moves
to test the improvements to the move effect system without requiring Discord.

Usage:
    python -m tests.move_effect_test

Features tested:
- Instant attack roll display
- Multihit modifier handling
- Bonus on hit functionality
- Advantage/disadvantage mechanics
- Parameter migration
"""

import os
import sys
import asyncio
import random
from typing import Dict, List, Any, Optional, Tuple
import logging

# Add the root directory to the path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('move_effect_test')

# Import necessary modules
from core.character import Character, Stats, Resources, DefenseStats, StatType, ProficiencyLevel
from core.effects.move import MoveEffect, BonusOnHit
from modules.moves.data import MoveData
from core.database import Database

class TestHarness:
    """Test harness for move effect system improvements"""
    
    def __init__(self):
        self.db = None
        self.characters = {}
        self.test_results = []
        
        # Mock round number for tests
        self.round_number = 1
        
        # For random number generation in tests
        random.seed(42)  # Use fixed seed for deterministic results
    
    async def initialize(self):
        """Initialize the test harness"""
        # Initialize database
        logger.info("Initializing database...")
        self.db = Database()
        await self.db.initialize()
        
        # Create test characters
        await self.create_test_characters()
    
    async def create_test_characters(self):
        """Create test characters with standard stats"""
        logger.info("Creating test characters...")
        
        # Define base stats for all characters
        base_stats = {
            "test": {  # Main character for running moves
                StatType.STRENGTH: 16,  # +3
                StatType.DEXTERITY: 14,  # +2
                StatType.CONSTITUTION: 14,  # +2
                StatType.INTELLIGENCE: 14,  # +2
                StatType.WISDOM: 12,  # +1
                StatType.CHARISMA: 10,  # +0
            },
            "test2": {  # Target with medium AC
                StatType.STRENGTH: 12,  # +1
                StatType.DEXTERITY: 14,  # +2
                StatType.CONSTITUTION: 14,  # +2
                StatType.INTELLIGENCE: 10,  # +0
                StatType.WISDOM: 12,  # +1
                StatType.CHARISMA: 8,   # -1
            },
            "test3": {  # Target with higher AC
                StatType.STRENGTH: 14,  # +2
                StatType.DEXTERITY: 16,  # +3
                StatType.CONSTITUTION: 16,  # +3
                StatType.INTELLIGENCE: 12,  # +1
                StatType.WISDOM: 10,  # +0
                StatType.CHARISMA: 8,   # -1
            },
            "test4": {  # Target with lower AC
                StatType.STRENGTH: 10,  # +0
                StatType.DEXTERITY: 12,  # +1
                StatType.CONSTITUTION: 12,  # +1
                StatType.INTELLIGENCE: 8,   # -1
                StatType.WISDOM: 10,  # +0
                StatType.CHARISMA: 12,  # +1
            }
        }
        
        # Create characters with different ACs
        ac_values = {
            "test": 14,
            "test2": 14,
            "test3": 16,
            "test4": 12
        }
        
        # Create each character
        for name, stats_dict in base_stats.items():
            # Create stats object
            stats = Stats()
            stats.base = stats_dict
            stats.modified = stats_dict.copy()
            
            # Create resources (80 HP, 80 MP)
            resources = Resources(
                current_hp=80,
                max_hp=80,
                current_mp=80,
                max_mp=80
            )
            
            # Create defense stats with AC
            defense = DefenseStats(
                base_ac=ac_values[name],
                current_ac=ac_values[name]
            )
            
            # Create the character
            character = Character(
                name=name,
                stats=stats,
                resources=resources,
                defense=defense,
                base_proficiency=2  # +2
            )
            
            # Set some basic proficiencies (for stat rolls)
            character.set_save_proficiency(StatType.STRENGTH, ProficiencyLevel.PROFICIENT)
            character.set_save_proficiency(StatType.DEXTERITY, ProficiencyLevel.PROFICIENT)
            
            # Add to our characters dict
            self.characters[name] = character
            
            # Save to database (optional)
            # await self.db.save_character(character)
            
        logger.info(f"Created {len(self.characters)} test characters")
    
    async def create_move(self, 
                        name: str,
                        description: str = "",
                        **kwargs) -> MoveData:
        """Create a move with the given parameters"""
        # Create basic move
        move = MoveData(
            name=name,
            description=description
        )
        
        # Apply additional parameters
        for key, value in kwargs.items():
            if hasattr(move, key):
                setattr(move, key, value)
        
        # Handle advanced_json parameters (simulates what happens in the Discord command)
        advanced_json = kwargs.get('advanced_json', {})
        if advanced_json:
            # Extract known fields from advanced_json and apply them directly
            if 'bonus_on_hit' in advanced_json:
                move.bonus_on_hit = advanced_json['bonus_on_hit']
            
            if 'aoe_mode' in advanced_json:
                move.aoe_mode = advanced_json['aoe_mode']
            
            # Add remaining fields to custom_parameters
            for key, value in advanced_json.items():
                if key not in ['bonus_on_hit', 'aoe_mode']:
                    move.custom_parameters[key] = value
        
        return move
    
    async def apply_move(self, 
                       character_name: str,
                       move: MoveData,
                       target_names: List[str] = None,
                       expected_output: str = None,
                       test_name: str = None) -> str:
        """Apply a move and return the results"""
        try:
            # Get characters
            character = self.characters.get(character_name)
            if not character:
                return f"Error: Character {character_name} not found"
            
            targets = []
            if target_names:
                for name in target_names:
                    target = self.characters.get(name)
                    if target:
                        targets.append(target)
            
            # Create MoveEffect from MoveData
            move_effect = MoveEffect(
                name=move.name,
                description=move.description,
                star_cost=move.star_cost,
                mp_cost=move.mp_cost,
                hp_cost=move.hp_cost,
                cast_time=move.cast_time,
                duration=move.duration,
                cooldown=move.cooldown,
                cast_description=move.cast_description,
                attack_roll=move.attack_roll,
                damage=move.damage,
                crit_range=move.crit_range,
                conditions=move.conditions,
                roll_timing=move.roll_timing,
                uses=move.uses,
                targets=targets,
                bonus_on_hit=move.bonus_on_hit,
                aoe_mode=move.aoe_mode
            )
            
            # Apply the move effect
            result = await move_effect.on_apply(character, self.round_number)
            
            # Record test result
            test_result = {
                'test_name': test_name or f"Move: {move.name}",
                'move': move.name,
                'caster': character_name,
                'targets': target_names,
                'result': result,
                'expected': expected_output,
                'passed': expected_output is None or expected_output in result
            }
            self.test_results.append(test_result)
            
            # Print the result with context
            print(f"\n{'='*80}")
            print(f"TEST: {test_result['test_name']}")
            print(f"Move: {move.name} | Caster: {character_name} | Targets: {target_names}")
            print(f"{'='*80}")
            print(result)
            
            if expected_output:
                if test_result['passed']:
                    print(f"\n✅ PASS: Expected output found")
                else:
                    print(f"\n❌ FAIL: Expected output not found")
                    print(f"Expected to find: {expected_output}")
            
            return result
            
        except Exception as e:
            error_msg = f"Error applying move {move.name}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            # Record failed test
            test_result = {
                'test_name': test_name or f"Move: {move.name}",
                'move': move.name,
                'caster': character_name,
                'targets': target_names,
                'result': error_msg,
                'expected': expected_output,
                'passed': False,
                'error': str(e)
            }
            self.test_results.append(test_result)
            
            print(f"\n{'='*80}")
            print(f"TEST: {test_result['test_name']} (ERROR)")
            print(f"{'='*80}")
            print(error_msg)
            
            return error_msg
    
    def print_summary(self):
        """Print a summary of all test results"""
        passed = sum(1 for t in self.test_results if t['passed'])
        total = len(self.test_results)
        
        print(f"\n{'='*80}")
        print(f"TEST SUMMARY: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
        print(f"{'='*80}")
        
        # List failed tests
        if passed < total:
            print("\nFailed tests:")
            for i, test in enumerate(self.test_results):
                if not test['passed']:
                    print(f"{i+1}. {test['test_name']}")
                    if 'error' in test:
                        print(f"   Error: {test['error']}")

async def run_tests():
    """Run all tests"""
    harness = TestHarness()
    await harness.initialize()
    
    # Test 1: Basic Instant Attack
    move1 = await harness.create_move(
        name="Quick Strike",
        description="A quick strike against a single target",
        attack_roll="1d20+dex",
        damage="1d6+dex slashing",
        mp_cost=5,
        star_cost=1
    )
    await harness.apply_move(
        character_name="test",
        move=move1,
        target_names=["test2"],
        expected_output="d20+dex",
        test_name="1. Basic Instant Attack"
    )
    
    # Test 2: Auto-Detected Instant
    move2 = await harness.create_move(
        name="Swift Slash",
        description="A swift slash; Should be detected as instant",
        attack_roll="1d20+str",
        damage="1d8+str slashing",
        roll_timing="active",
        mp_cost=5,
        star_cost=1
    )
    await harness.apply_move(
        character_name="test",
        move=move2,
        target_names=["test2"],
        expected_output="d20+str",
        test_name="2. Auto-Detected Instant"
    )
    
    # Test 3: With Cast Time
    move3 = await harness.create_move(
        name="Fireball",
        description="A powerful fireball; Takes time to cast",
        attack_roll="1d20+int",
        damage="3d6 fire",
        cast_time=1,
        roll_timing="active",
        mp_cost=10,
        star_cost=2
    )
    await harness.apply_move(
        character_name="test",
        move=move3,
        target_names=["test2"],
        expected_output="begins casting",
        test_name="3. Attack With Cast Time"
    )
    
    # Test 4: Basic Multihit
    move4 = await harness.create_move(
        name="Flurry",
        description="Multiple quick strikes",
        attack_roll="3d20 multihit 2",
        damage="1d4+dex bludgeoning",
        mp_cost=8,
        star_cost=2
    )
    await harness.apply_move(
        character_name="test",
        move=move4,
        target_names=["test2"],
        expected_output="multihit",
        test_name="4. Basic Multihit"
    )
    
    # Test 5: Multihit with Multiple Targets
    move5 = await harness.create_move(
        name="Pin Missiles",
        description="Fire multiple projectiles; Hits all targets",
        attack_roll="4d20 multihit 3",
        damage="1d4 piercing",
        mp_cost=10,
        star_cost=2,
        aoe_mode="single"
    )
    await harness.apply_move(
        character_name="test",
        move=move5,
        target_names=["test2", "test3"],
        expected_output="Hits:",
        test_name="5. Multihit with Multiple Targets"
    )
    
    # Test 6: Multihit Bug Case
    move6 = await harness.create_move(
        name="Rising Dragon",
        description="A powerful rising attack; Multiple hits",
        attack_roll="4d20 multihit 5",
        damage="1d6+2 bludgeoning",
        mp_cost=12,
        star_cost=3
    )
    await harness.apply_move(
        character_name="test",
        move=move6,
        target_names=["test2"],
        expected_output="Hits:",
        test_name="6. Multihit Bug Case"
    )
    
    # Test 7: MP Bonus
    move7 = await harness.create_move(
        name="Mana Drain",
        description="Drains mana from target",
        attack_roll="1d20+int",
        damage="2d4 necrotic",
        mp_cost=5,
        star_cost=1,
        advanced_json={"bonus_on_hit": {"mp": 2}}
    )
    await harness.apply_move(
        character_name="test",
        move=move7,
        target_names=["test2"],
        expected_output="MP: +",
        test_name="7. MP Bonus"
    )
    
    # Test 8: Multiple Bonuses
    move8 = await harness.create_move(
        name="Lifesteal",
        description="Steals life and mana",
        attack_roll="1d20+dex",
        damage="1d8+dex necrotic",
        mp_cost=8,
        star_cost=2,
        advanced_json={"bonus_on_hit": {"hp": 3, "mp": 2, "stars": 1}}
    )
    await harness.apply_move(
        character_name="test",
        move=move8,
        target_names=["test2"],
        expected_output="Hits! Bonuses:",
        test_name="8. Multiple Bonuses"
    )
    
    # Test 9: Custom Note
    move9 = await harness.create_move(
        name="Dragon Strike",
        description="A powerful strike; Builds dragon energy",
        attack_roll="1d20+15",  # Much higher bonus to ensure hit
        damage="2d6+str fire",
        mp_cost=8,
        star_cost=2,
        advanced_json={"bonus_on_hit": {"note": "Dragon Stack"}}
    )
    await harness.apply_move(
        character_name="test",
        move=move9,
        target_names=["test2"],
        expected_output="Dragon Stack",
        test_name="9. Custom Note"
    )
    
    # Test 10: AoE Multiple Hits
    move10 = await harness.create_move(
        name="Chain Lightning",
        description="Lightning jumps between targets",
        attack_roll="1d20+int",
        damage="1d10 lightning",
        mp_cost=12,
        star_cost=2,
        advanced_json={"bonus_on_hit": {"mp": 1, "stars": 1}, "aoe_mode": "multi"}
    )
    await harness.apply_move(
        character_name="test",
        move=move10,
        target_names=["test2", "test3", "test4"],
        expected_output="Bonuses:",
        test_name="10. AoE Multiple Hits"
    )
    
    # Test for multihit advantage
    move11 = await harness.create_move(
        name="Precision Strike",
        description="A precise series of attacks",
        attack_roll="4d20 multihit advantage 2",
        damage="1d8+dex piercing",
        mp_cost=10,
        star_cost=2
    )
    await harness.apply_move(
        character_name="test",
        move=move11,
        target_names=["test2"],
        expected_output="advantage",
        test_name="11. Multihit Advantage"
    )
    
    # Test for multihit disadvantage
    move12 = await harness.create_move(
        name="Wild Shot",
        description="A wild, uncontrolled barrage",
        attack_roll="4d20 multihit disadvantage 2",
        damage="1d8+dex piercing",
        mp_cost=10,
        star_cost=2
    )
    await harness.apply_move(
        character_name="test",
        move=move12,
        target_names=["test2"],
        expected_output="disadvantage",
        test_name="12. Multihit Disadvantage"
    )
    
    # Test for regular advantage
    move13 = await harness.create_move(
        name="Power Attack",
        description="A powerful attack with advantage",
        attack_roll="1d20+str advantage",
        damage="2d6+str slashing",
        mp_cost=5,
        star_cost=1
    )
    await harness.apply_move(
        character_name="test",
        move=move13,
        target_names=["test2"],
        expected_output="advantage",
        test_name="13. Regular Advantage"
    )
    
    # Test for heat tracking migration
    move14 = await harness.create_move(
        name="Phoenix Strike",
        description="A fiery strike that builds heat",
        attack_roll="1d20+dex",
        damage="2d6 fire",
        mp_cost=8,
        star_cost=1,
        advanced_json={"enable_heat_tracking": True}
    )
    await harness.apply_move(
        character_name="test",
        move=move14,
        target_names=["test2"],
        expected_output="Hits! Bonuses:",
        test_name="14. Heat Tracking Migration"
    )
    
    # Test for full featured move
    move15 = await harness.create_move(
        name="Ultimate Blast",
        description="A devastating attack; Multiple targets; Builds power",
        attack_roll="3d20 multihit advantage 1",
        damage="3d6+int force",
        mp_cost=20,
        star_cost=3,
        cooldown=3, advanced_json={
            "bonus_on_hit": {"mp": 2, "hp": 1, "note": "Power Charge"},
            "aoe_mode": "single"  # Changed from "multi" to "single"
        }
    )
    await harness.apply_move(
        character_name="test",
        move=move15,
        target_names=["test2", "test3"],
        expected_output="Power Charge",
        test_name="15. Full Featured Move"
    )
    
    # Print summary of all tests
    harness.print_summary()

if __name__ == "__main__":
    # Run the test harness
    asyncio.run(run_tests())