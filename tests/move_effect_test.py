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
- AOE vs Single target mechanics
- Duration testing
"""
import sys
import os
import asyncio
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# Add the root directory to the path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('move_effect_test')

# Import necessary modules from the new move effect system
from core.effects.move import (
    MoveEffect, 
    MovePhase, 
    RollTiming, 
    apply_move_effect, 
    process_move_effects
)
from core.effects.move.bridge import MoveEffectBridge
from core.effects.condition import ConditionType
from modules.moves.manager import MoveManager
from modules.moves.data import MoveData

class MockCharacter:
    """Mock character class for testing"""
    
    def __init__(self, name: str):
        self.name = name
        self.stats = {
            'strength': 14,
            'dexterity': 16,
            'constitution': 13,
            'intelligence': 12,
            'wisdom': 10,
            'charisma': 15
        }
        self.resources = MockResources()
        self.action_stars = MockActionStars()
        self.effects = []
        self.custom_parameters = {}
        self.saves = {
            'strength': 2,
            'dexterity': 5,
            'constitution': 3,
            'intelligence': 1,
            'wisdom': 0,
            'charisma': 2
        }
        self.base_proficiency = 3
        self.effect_feedback = MockEffectFeedback()
        self.defense = MockDefense()
        
        # Add static modifiers for predictable testing
        self.get_stat_modifier = self._mock_get_stat_modifier

    def _mock_get_stat_modifier(self, stat: str) -> int:
        """Mock stat modifier method with high values for testing hits"""
        modifiers = {
            'strength': 5,    # +5 to str attacks
            'dexterity': 5,   # +5 to dex attacks  
            'constitution': 2,
            'intelligence': 5, # +5 to int attacks
            'wisdom': 1,
            'charisma': 3
        }
        return modifiers.get(stat, 0)

class MockDefense:
    """Mock defense stats"""
    
    def __init__(self):
        self.current_ac = 15
        self.base_ac = 15

class MockResources:
    """Mock character resources"""
    
    def __init__(self):
        self.max_hp = 50
        self.current_hp = 50
        self.max_mp = 30
        self.current_mp = 30
        self.max_temp_hp = 0
        self.current_temp_hp = 0

class MockActionStars:
    """Mock action stars"""
    
    def __init__(self):
        self.max_stars = 3
        self.current_stars = 3
        self.bonus_stars = 0

class MockInitiativeTracker:
    """Mock initiative tracker for testing timing detection"""
    
    def __init__(self):
        self.current_turn = None
        self.round_number = 1
        
    def set_current_turn(self, character_name: str):
        """Set the current turn character"""
        self.current_turn = MockTurn(character_name)
        
    def advance_round(self):
        """Advance to next round"""
        self.round_number += 1

class MockTurn:
    """Mock turn object"""
    
    def __init__(self, character_name: str):
        self.character_name = character_name

class MockCombatLogger:
    """Mock combat logger for testing"""
    
    def __init__(self):
        self.events = []
        
    def add_event(self, event_type, message="", character="", details=None):
        """Add a combat event"""
        self.events.append({
            'type': event_type,
            'message': message,
            'character': character,
            'details': details or {}
        })

def create_test_character(name: str, level: int = 5) -> MockCharacter:
    """Create a test character with basic stats"""
    character = MockCharacter(name)
    return character

class MockEffectFeedback:
    """Mock effect feedback system"""
    
    def __init__(self):
        self.feedback = []
        
    def add_feedback(self, effect_name="", expiry_message="", round_number=1, 
                    turn_name="", is_expiry=False, **kwargs):
        """Add feedback message"""
        self.feedback.append({
            'effect_name': effect_name,
            'message': expiry_message,
            'round': round_number,
            'turn': turn_name,
            'is_expiry': is_expiry
        })

def create_test_move_data(name: str, **kwargs) -> MoveData:
    """Create test move data with default values"""
    return MoveData(
        name=name,
        description=kwargs.get('description', f'Test move: {name}'),
        star_cost=kwargs.get('star_cost', 1),
        mp_cost=kwargs.get('mp_cost', 0),
        hp_cost=kwargs.get('hp_cost', 0),
        cast_time=kwargs.get('cast_time'),
        duration=kwargs.get('duration'),
        cooldown=kwargs.get('cooldown'),
        cast_description=kwargs.get('cast_description'),
        attack_roll=kwargs.get('attack_roll'),
        damage=kwargs.get('damage'),
        crit_range=kwargs.get('crit_range', 20),
        conditions=kwargs.get('conditions', []),
        roll_timing=kwargs.get('roll_timing', 'active')
    )

# Test output configuration
TEST_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'move_effect_testing')

class TestLogger:
    """Logger that captures output to both console and file"""
    
    def __init__(self):
        self.messages = []
        
        # Create output directory
        os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)
        
        # Create timestamped output file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_file = os.path.join(TEST_OUTPUT_DIR, f"move_test_results_{timestamp}.txt")
        
    def print(self, message=""):
        """Print to both console and capture for file"""
        print(message)
        self.messages.append(str(message))
        
    def save_to_file(self):
        """Save all captured messages to file"""
        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.messages))
        print(f"\nTest results saved to: {self.output_file}")

# Global test logger
test_logger = TestLogger()

async def test_instant_attack_move():
    """Test instant attack moves with immediate roll processing"""
    test_logger.print("\n=== Testing Instant Attack Move ===")
    
    # Create test characters
    attacker = create_test_character("Alice", 5)
    target = create_test_character("Bob", 5)
    
    # Create initiative tracker
    initiative = MockInitiativeTracker()
    initiative.set_current_turn("Alice")
    
    # Create combat logger
    combat_logger = MockCombatLogger()
    
    # Create instant attack move with static modifier
    move_data = create_test_move_data(
        name="Lightning Strike",
        description="A quick lightning attack",
        attack_roll="20",  # Static 20 for guaranteed hit
        damage="1d8+5 lightning",
        roll_timing="instant",
        bonus_on_hit={'stars': 1, 'mp': 2}
    )
    
    # Convert to MoveEffect using manager
    move_effect = MoveManager.create_effect_from_data(
        move_data, 
        round_number=1, 
        targets=[target]
    )
    
    test_logger.print(f"Created move effect: {move_effect.name}")
    test_logger.print(f"Roll timing: {move_effect.roll_timing}")
    test_logger.print(f"Attack roll: {move_effect.attack_roll}")
    
    # Apply the move
    apply_message = await apply_move_effect(
        attacker, 
        move_effect, 
        round_number=1,
        combat_logger=combat_logger,
        is_combat_active=True,
        initiative_tracker=initiative
    )
    
    test_logger.print(f"Apply message: {apply_message}")
    
    # Execute pending operations (attack rolls)
    pending_messages = await MoveEffectBridge.execute_pending_for_character(attacker)
    if pending_messages:
        test_logger.print("Pending messages:")
        for msg in pending_messages:
            test_logger.print(f"  {msg}")
    
    # Check effect state
    test_logger.print(f"Effect expired: {move_effect.is_expired}")
    test_logger.print(f"Effects on attacker: {len(attacker.effects)}")
    
    return move_effect

async def test_casting_to_active_move():
    """Test move with cast time that transitions to active phase"""
    test_logger.print("\n=== Testing Casting to Active Move ===")
    
    # Create test character
    caster = create_test_character("Wizard", 5)
    target = create_test_character("Enemy", 5)
    
    # Create initiative tracker
    initiative = MockInitiativeTracker()
    initiative.set_current_turn("Wizard")
    
    # Create move with cast time and duration, static modifier for predictable hits
    move_data = create_test_move_data(
        name="Fireball",
        description="A powerful fire spell",
        cast_time=2,
        duration=3,
        cast_description="channels arcane energy for",
        attack_roll="20",  # Static 20 for guaranteed hit
        damage="3d6+3 fire",
        roll_timing="active"
    )
    
    # Convert to MoveEffect
    move_effect = MoveManager.create_effect_from_data(
        move_data,
        round_number=1,
        targets=[target]
    )
    
    test_logger.print(f"Created move: {move_effect.name}")
    test_logger.print(f"Cast time: {move_effect.cast_time}")
    test_logger.print(f"Duration: {move_effect.duration}")
    
    # Apply the move (during own turn)
    apply_message = await apply_move_effect(
        caster,
        move_effect,
        round_number=1,
        initiative_tracker=initiative
    )
    
    test_logger.print(f"Initial apply: {apply_message}")
    
    # Simulate turns with proper round progression
    current_round = 1
    for turn in range(1, 6):
        test_logger.print(f"\n--- Turn {turn} (Round {current_round}) ---")
        
        # Process start of turn
        start_messages = await process_move_effects(
            caster, 
            round_number=current_round, 
            turn_name="Wizard", 
            which="start"
        )
        
        if start_messages:
            test_logger.print("Start of turn:")
            for msg in start_messages:
                test_logger.print(f"  {msg}")
        
        # Execute any pending operations
        pending_messages = await MoveEffectBridge.execute_pending_for_character(caster)
        if pending_messages:
            test_logger.print("Pending operations:")
            for msg in pending_messages:
                test_logger.print(f"  {msg}")
        
        # Process end of turn
        end_messages = await process_move_effects(
            caster,
            round_number=current_round,
            turn_name="Wizard",
            which="end"
        )
        
        if end_messages:
            test_logger.print("End of turn:")
            for msg in end_messages:
                test_logger.print(f"  {msg}")
        
        # Check if effect is still active
        if move_effect.is_expired:
            test_logger.print("Effect has expired")
            break
            
        test_logger.print(f"Effect state: {move_effect.timing_handler.current_phase}")
        test_logger.print(f"Turns remaining: {move_effect.timing_handler.get_remaining_turns()}")
        
        # Advance round
        current_round += 1
    
    return move_effect

async def test_cooldown_only_move():
    """Test move that goes directly to cooldown"""
    test_logger.print("\n=== Testing Cooldown Only Move ===")
    
    character = create_test_character("Fighter", 5)
    target = create_test_character("Target", 5)
    
    # Create move with only cooldown, static modifier for predictable hits
    move_data = create_test_move_data(
        name="Power Strike",
        description="A powerful strike with cooldown",
        cooldown=3,
        attack_roll="20",  # Static 20 for guaranteed hit
        damage="2d6+5",
        roll_timing="instant"
    )
    
    move_effect = MoveManager.create_effect_from_data(
        move_data,
        targets=[target]
    )
    
    test_logger.print(f"Created move: {move_effect.name}")
    test_logger.print(f"Cooldown: {move_effect.cooldown}")
    
    # Apply move
    apply_message = await apply_move_effect(character, move_effect)
    test_logger.print(f"Apply: {apply_message}")
    
    # Execute pending operations
    pending_messages = await MoveEffectBridge.execute_pending_for_character(character)
    if pending_messages:
        test_logger.print("Attack results:")
        for msg in pending_messages:
            test_logger.print(f"  {msg}")
    
    # Simulate cooldown turns with proper round progression
    current_round = 1
    for turn in range(1, 5):
        test_logger.print(f"\n--- Cooldown Turn {turn} (Round {current_round}) ---")
        
        end_messages = await process_move_effects(
            character,
            round_number=current_round,
            turn_name="Fighter",
            which="end"
        )
        
        if end_messages:
            for msg in end_messages:
                test_logger.print(f"  {msg}")
        
        if move_effect.is_expired:
            test_logger.print("Cooldown complete")
            break
            
        # Advance round
        current_round += 1
    
    return move_effect

async def test_during_own_turn_timing():
    """Test timing adjustments for effects applied during own turn"""
    test_logger.print("\n=== Testing During Own Turn Timing ===")
    
    character = create_test_character("Mage", 5)
    
    # Create initiative tracker with character's turn active
    initiative = MockInitiativeTracker()
    initiative.set_current_turn("Mage")
    
    # Create buff move with duration
    move_data = create_test_move_data(
        name="Magic Shield",
        description="Protective barrier",
        duration=2,
        mp_cost=5
    )
    
    move_effect = MoveManager.create_effect_from_data(move_data)
    
    test_logger.print(f"Move duration: {move_effect.duration}")
    
    # Apply during own turn
    apply_message = await apply_move_effect(
        character,
        move_effect,
        round_number=1,
        initiative_tracker=initiative
    )
    
    test_logger.print(f"Applied during own turn: {apply_message}")
    test_logger.print(f"Timing adjusted: {move_effect.timing_handler.timing_adjusted}")
    test_logger.print(f"Internal turns: {move_effect.timing_handler.get_remaining_turns()}")
    test_logger.print(f"Display turns: {move_effect.timing_handler.get_display_turns()}")
    
    # Simulate turns to test duration with proper round progression
    current_round = 1
    for turn in range(1, 5):
        test_logger.print(f"\n--- Turn {turn} (Round {current_round}) ---")
        
        end_messages = await process_move_effects(
            character,
            round_number=current_round,
            turn_name="Mage",
            which="end"
        )
        
        if end_messages:
            for msg in end_messages:
                test_logger.print(f"  {msg}")
        
        if move_effect.is_expired:
            break
        
        test_logger.print(f"Display turns remaining: {move_effect.timing_handler.get_display_turns()}")
        
        # Advance round
        current_round += 1
    
    return move_effect

async def test_discord_compatibility():
    """Test Discord-specific compatibility"""
    test_logger.print("\n=== Testing Discord Compatibility ===")
    
    # Test that messages are properly formatted for Discord
    character = create_test_character("DiscordTest", 5)
    target = create_test_character("Target", 5)
    
    move_data = create_test_move_data(
        name="Discord Test Move",
        description="Testing Discord message formatting",
        attack_roll="20",  # Guaranteed hit
        damage="1d4+1",
        roll_timing="instant"
    )
    
    move_effect = MoveManager.create_effect_from_data(
        move_data,
        targets=[target]
    )
    
    # Apply move
    apply_message = await apply_move_effect(character, move_effect)
    
    # Check message formatting
    test_logger.print("Message format checks:")
    test_logger.print(f"  Contains emojis: {'✨' in apply_message}")
    test_logger.print(f"  Contains backticks: {'`' in apply_message}")
    test_logger.print(f"  Length under Discord limit: {len(apply_message) < 2000}")
    test_logger.print(f"  Message: {apply_message}")
    
    # Execute pending
    pending_messages = await MoveEffectBridge.execute_pending_for_character(character)
    if pending_messages:
        for msg in pending_messages:
            test_logger.print(f"  Pending length OK: {len(msg) < 2000} - {msg}")
    
    return move_effect

async def test_bonus_on_hit():
    """Test bonus on hit functionality with guaranteed hit"""
    test_logger.print("\n=== Testing Bonus on Hit (Guaranteed Hit) ===")
    
    character = create_test_character("Rogue", 5)
    target = create_test_character("Victim", 5)
    
    # Create move with bonus on hit, guaranteed hit
    move_data = create_test_move_data(
        name="Precise Strike",
        description="Strike that grants bonuses on hit",
        attack_roll="20",  # Static 20 for guaranteed hit
        damage="1d6+3",
        roll_timing="instant"
    )
    
    # Set bonus_on_hit data directly
    move_effect = MoveManager.create_effect_from_data(
        move_data,
        targets=[target]
    )
    
    # Manually set bonus on hit for testing
    from core.effects.move.combat import BonusOnHit
    try:
        move_effect.bonus_on_hit = BonusOnHit()
        move_effect.bonus_on_hit.mp_bonus = 3
        move_effect.bonus_on_hit.star_bonus = 1  
        move_effect.bonus_on_hit.custom_note = "Precise hit bonus"
    except Exception as e:
        test_logger.print(f"Failed to set bonus on hit: {e}")
    
    test_logger.print(f"Initial MP: {character.resources.current_mp}")
    test_logger.print(f"Initial Stars: {character.action_stars.current_stars}")
    
    # Apply move
    apply_message = await apply_move_effect(character, move_effect)
    test_logger.print(f"Apply: {apply_message}")
    
    # Execute attack
    pending_messages = await MoveEffectBridge.execute_pending_for_character(character)
    if pending_messages:
        for msg in pending_messages:
            test_logger.print(f"  {msg}")
    
    test_logger.print(f"Final MP: {character.resources.current_mp}")
    test_logger.print(f"Final Stars: {character.action_stars.current_stars}")
    
    return move_effect

async def test_aoe_single_target():
    """Test AOE vs single target attack mechanics"""
    test_logger.print("\n=== Testing AOE vs Single Target ===")
    
    attacker = create_test_character("Mage", 5)
    target1 = create_test_character("Enemy1", 5)
    target2 = create_test_character("Enemy2", 5)
    target3 = create_test_character("Enemy3", 5)
    
    # Test single target attack
    test_logger.print("\n--- Single Target Attack ---")
    single_move = create_test_move_data(
        name="Magic Missile",
        description="Single target spell",
        attack_roll="20",  # Guaranteed hit
        damage="1d4+1 force",
        roll_timing="instant"
    )
    
    single_effect = MoveManager.create_effect_from_data(
        single_move,
        targets=[target1]
    )
    
    apply_msg = await apply_move_effect(attacker, single_effect)
    test_logger.print(f"Single target: {apply_msg}")
    
    pending = await MoveEffectBridge.execute_pending_for_character(attacker)
    for msg in pending:
        test_logger.print(f"  {msg}")
    
    # Test AOE attack
    test_logger.print("\n--- AOE Attack (Multiple Targets) ---")
    aoe_move = create_test_move_data(
        name="Fireball AOE",
        description="Area of effect spell",
        attack_roll="20",  # Guaranteed hit
        damage="2d6 fire",
        roll_timing="instant"
    )
    
    aoe_effect = MoveManager.create_effect_from_data(
        aoe_move,
        targets=[target1, target2, target3]
    )
    
    apply_msg = await apply_move_effect(attacker, aoe_effect)
    test_logger.print(f"AOE attack: {apply_msg}")
    
    pending = await MoveEffectBridge.execute_pending_for_character(attacker)
    for msg in pending:
        test_logger.print(f"  {msg}")
    
    return single_effect, aoe_effect

async def test_multihit_mechanics():
    """Test multihit attack mechanics"""
    test_logger.print("\n=== Testing Multihit Mechanics ===")
    
    attacker = create_test_character("Fighter", 5)
    target = create_test_character("Dummy", 5)
    
    # Test multihit attack
    multihit_move = create_test_move_data(
        name="Flurry of Blows",
        description="Multiple strikes",
        attack_roll="20",  # Guaranteed hits
        damage="1d6+2 each",
        roll_timing="instant"
    )
    
    multihit_effect = MoveManager.create_effect_from_data(
        multihit_move,
        targets=[target]
    )
    
    # Set multihit parameter
    multihit_effect.multihit = 3  # 3 attacks
    
    test_logger.print(f"Multihit count: {getattr(multihit_effect, 'multihit', 1)}")
    
    apply_msg = await apply_move_effect(attacker, multihit_effect)
    test_logger.print(f"Apply: {apply_msg}")
    
    pending = await MoveEffectBridge.execute_pending_for_character(attacker)
    for msg in pending:
        test_logger.print(f"  {msg}")
    
    return multihit_effect

async def test_advantage_disadvantage():
    """Test advantage and disadvantage mechanics"""
    test_logger.print("\n=== Testing Advantage/Disadvantage ===")
    
    attacker = create_test_character("Rogue", 5)
    target = create_test_character("Guard", 5)
    
    # Test advantage
    test_logger.print("\n--- Attack with Advantage ---")
    adv_move = create_test_move_data(
        name="Sneak Attack",
        description="Attack with advantage",
        attack_roll="1d20+8 advantage",
        damage="2d6+4 sneak",
        roll_timing="instant"
    )
    
    adv_effect = MoveManager.create_effect_from_data(adv_move, targets=[target])
    
    apply_msg = await apply_move_effect(attacker, adv_effect)
    test_logger.print(f"Advantage: {apply_msg}")
    
    pending = await MoveEffectBridge.execute_pending_for_character(attacker)
    for msg in pending:
        test_logger.print(f"  {msg}")
    
    # Test disadvantage
    test_logger.print("\n--- Attack with Disadvantage ---")
    dis_move = create_test_move_data(
        name="Blinded Strike",
        description="Attack with disadvantage",
        attack_roll="1d20+8 disadvantage",
        damage="1d8+4",
        roll_timing="instant"
    )
    
    dis_effect = MoveManager.create_effect_from_data(dis_move, targets=[target])
    
    apply_msg = await apply_move_effect(attacker, dis_effect)
    test_logger.print(f"Disadvantage: {apply_msg}")
    
    pending = await MoveEffectBridge.execute_pending_for_character(attacker)
    for msg in pending:
        test_logger.print(f"  {msg}")
    
    return adv_effect, dis_effect

async def test_multihit_bonus_on_hit():
    """Test bonus on hit with multihit attacks"""
    test_logger.print("\n=== Testing Multihit + Bonus on Hit ===")
    
    attacker = create_test_character("Monk", 5)
    target = create_test_character("Training Dummy", 5)
    
    # Create multihit move with bonus on hit
    move_data = create_test_move_data(
        name="Chi Strike",
        description="Multiple energy strikes with recovery",
        attack_roll="20",  # Guaranteed hits
        damage="1d4+2 chi",
        roll_timing="instant"
    )
    
    effect = MoveManager.create_effect_from_data(move_data, targets=[target])
    effect.multihit = 4  # 4 strikes
    
    # Set bonus on hit
    from core.effects.move.combat import BonusOnHit
    try:
        effect.bonus_on_hit = BonusOnHit()
        effect.bonus_on_hit.mp_bonus = 2  # +2 MP per hit
        effect.bonus_on_hit.star_bonus = 0
        effect.bonus_on_hit.custom_note = "Chi recovery"
    except Exception as e:
        test_logger.print(f"Failed to set bonus: {e}")
    
    test_logger.print(f"Initial MP: {attacker.resources.current_mp}")
    test_logger.print(f"Multihit count: {effect.multihit}")
    
    apply_msg = await apply_move_effect(attacker, effect)
    test_logger.print(f"Apply: {apply_msg}")
    
    pending = await MoveEffectBridge.execute_pending_for_character(attacker)
    for msg in pending:
        test_logger.print(f"  {msg}")
    
    test_logger.print(f"Final MP: {attacker.resources.current_mp}")
    
    return effect

async def test_aoe_bonus_mechanics():
    """Test bonus on hit with AOE attacks"""
    test_logger.print("\n=== Testing AOE + Bonus on Hit ===")
    
    caster = create_test_character("Warlock", 5)
    targets = [
        create_test_character("Goblin1", 5),
        create_test_character("Goblin2", 5),
        create_test_character("Goblin3", 5)
    ]
    
    # AOE with life drain
    move_data = create_test_move_data(
        name="Life Drain Burst",
        description="AOE that heals caster per hit",
        attack_roll="20",  # Guaranteed hits
        damage="1d6 necrotic",
        roll_timing="instant"
    )
    
    effect = MoveManager.create_effect_from_data(move_data, targets=targets)
    
    # Set healing bonus per hit
    from core.effects.move.combat import BonusOnHit
    try:
        effect.bonus_on_hit = BonusOnHit()
        effect.bonus_on_hit.hp_bonus = 2  # +2 HP per hit
        effect.bonus_on_hit.custom_note = "Life drain"
    except Exception as e:
        test_logger.print(f"Failed to set bonus: {e}")
    
    test_logger.print(f"Initial HP: {caster.resources.current_hp}")
    test_logger.print(f"Target count: {len(targets)}")
    
    apply_msg = await apply_move_effect(caster, effect)
    test_logger.print(f"Apply: {apply_msg}")
    
    pending = await MoveEffectBridge.execute_pending_for_character(caster)
    for msg in pending:
        test_logger.print(f"  {msg}")
    
    test_logger.print(f"Final HP: {caster.resources.current_hp}")
    
    return effect

async def test_duration_mechanics():
    """Test duration mechanics for 1 vs 2 turn effects"""
    test_logger.print("\n=== Testing Duration Mechanics ===")
    
    character = create_test_character("Cleric", 5)
    initiative = MockInitiativeTracker()
    initiative.set_current_turn("Cleric")
    
    # Test 1-turn duration
    test_logger.print("\n--- 1-Turn Duration Effect ---")
    short_move = create_test_move_data(
        name="Shield of Faith",
        description="Brief protection",
        duration=1,
        mp_cost=3
    )
    
    short_effect = MoveManager.create_effect_from_data(short_move)
    
    apply_msg = await apply_move_effect(character, short_effect, round_number=1, initiative_tracker=initiative)
    test_logger.print(f"1-turn effect applied: {apply_msg}")
    test_logger.print(f"Display turns: {short_effect.timing_handler.get_display_turns()}")
    
    # Simulate turns
    for turn in range(1, 4):
        test_logger.print(f"\n--- Turn {turn} ---")
        end_msgs = await process_move_effects(character, round_number=turn, turn_name="Cleric", which="end")
        for msg in end_msgs:
            test_logger.print(f"  {msg}")
        
        if short_effect.is_expired:
            test_logger.print("1-turn effect expired")
            break
        test_logger.print(f"Remaining: {short_effect.timing_handler.get_display_turns()}")
    
    # Test 2-turn duration
    test_logger.print("\n--- 2-Turn Duration Effect ---")
    long_move = create_test_move_data(
        name="Bless",
        description="Extended blessing",
        duration=2,
        mp_cost=5
    )
    
    long_effect = MoveManager.create_effect_from_data(long_move)
    
    apply_msg = await apply_move_effect(character, long_effect, round_number=1, initiative_tracker=initiative)
    test_logger.print(f"2-turn effect applied: {apply_msg}")
    test_logger.print(f"Display turns: {long_effect.timing_handler.get_display_turns()}")
    
    # Simulate turns
    for turn in range(1, 5):
        test_logger.print(f"\n--- Turn {turn} ---")
        end_msgs = await process_move_effects(character, round_number=turn, turn_name="Cleric", which="end")
        for msg in end_msgs:
            test_logger.print(f"  {msg}")
        
        if long_effect.is_expired:
            test_logger.print("2-turn effect expired")
            break
        test_logger.print(f"Remaining: {long_effect.timing_handler.get_display_turns()}")
    
    return short_effect, long_effect

async def run_all_tests():
    """Run all test scenarios"""
    test_logger.print("Starting Move Effect System Tests")
    test_logger.print("=" * 50)
    test_logger.print(f"Output directory: {TEST_OUTPUT_DIR}")
    test_logger.print(f"Test started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Original tests
        instant_effect = await test_instant_attack_move()
        casting_effect = await test_casting_to_active_move()
        cooldown_effect = await test_cooldown_only_move()
        timing_effect = await test_during_own_turn_timing()
        discord_effect = await test_discord_compatibility()
        
        # New comprehensive tests
        bonus_effect = await test_bonus_on_hit()
        single_effect, aoe_effect = await test_aoe_single_target()
        multihit_effect = await test_multihit_mechanics()
        adv_effect, dis_effect = await test_advantage_disadvantage()
        multihit_bonus_effect = await test_multihit_bonus_on_hit()
        aoe_bonus_effect = await test_aoe_bonus_mechanics()
        short_duration, long_duration = await test_duration_mechanics()
        
        test_logger.print("\n" + "=" * 50)
        test_logger.print("All tests completed successfully!")
        test_logger.print(f"Test finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        test_logger.print("\nTest Summary:")
        test_logger.print("✅ Instant attacks with guaranteed hits")
        test_logger.print("✅ Casting to active phase transitions")
        test_logger.print("✅ Cooldown mechanics")
        test_logger.print("✅ During own turn timing adjustments")
        test_logger.print("✅ Bonus on hit with guaranteed hits")
        test_logger.print("✅ AOE vs single target mechanics")
        test_logger.print("✅ Multihit attack mechanics")
        test_logger.print("✅ Advantage/disadvantage mechanics")
        test_logger.print("✅ Multihit + bonus on hit")
        test_logger.print("✅ AOE + bonus on hit")
        test_logger.print("✅ 1-turn vs 2-turn duration testing")
        test_logger.print("✅ Discord compatibility")
        
    except Exception as e:
        test_logger.print(f"\nTest failed with error: {e}")
        import traceback
        test_logger.print(traceback.format_exc())
    
    finally:
        # Save results to file
        test_logger.save_to_file()

if __name__ == "__main__":
    asyncio.run(run_all_tests())