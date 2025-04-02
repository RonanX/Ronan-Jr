"""
Enhanced Burn Effect Test with Clear Timing Visualization

This test focuses on proper timing of burn effects with various application scenarios.
It visualizes the effect lifecycle, duration calculation, and feedback system.

Usage:
- Run specific scenarios with command-line arguments
- Outputs detailed logs with clear round/turn tracking
- Shows effect lifecycle stages and feedback messages
"""

import asyncio
import sys
import os
import logging
from typing import List, Dict, Any
import argparse
import time

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add the src directory to the python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import game components
from core.character import Character, Stats, Resources, DefenseStats, StatType, EffectFeedback
from core.state import GameState, CombatLogger, CombatEventType 
from core.effects.burn_effect import BurnEffect
from core.effects.manager import apply_effect, process_effects, register_effects

# ANSI color codes for better output styling
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    MAGENTA = '\033[35m'  # Add the missing MAGENTA color
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(message):
    """Print a formatted header message"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{message.center(80)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 80}{Colors.ENDC}\n")

def print_section(message):
    """Print a formatted section message"""
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'-' * 50}{Colors.ENDC}")
    print(f"{Colors.BLUE}{Colors.BOLD}{message}{Colors.ENDC}")
    print(f"{Colors.BLUE}{Colors.BOLD}{'-' * 50}{Colors.ENDC}\n")

def print_round(round_num, character_name):
    """Print a round marker"""
    print(f"\n{Colors.GREEN}{Colors.BOLD}===== ROUND {round_num}: {character_name}'s Turn ====={Colors.ENDC}\n")

def print_phase(phase_name, character_name):
    """Print a turn phase marker"""
    print(f"{Colors.CYAN}--- {phase_name} for {character_name} ---{Colors.ENDC}")

def print_effect_message(message_type, content):
    """Print a formatted effect message"""
    if "damage" in content.lower():
        prefix = f"{Colors.RED}[{message_type}]:{Colors.ENDC} "
    elif "worn off" in content.lower() or "expired" in content.lower():
        prefix = f"{Colors.YELLOW}[{message_type}]:{Colors.ENDC} "
    else:
        prefix = f"{Colors.GREEN}[{message_type}]:{Colors.ENDC} "
    print(f"{prefix}{content}")

def print_character_status(character: Character, round_num: int):
    """Print character status in a clear format with improved effect details"""
    print(f"\n{Colors.BLUE}{Colors.BOLD}==== Character Status: {character.name} (Round {round_num}) ===={Colors.ENDC}")
    print(f"{Colors.GREEN}HP: {character.resources.current_hp}/{character.resources.max_hp}{Colors.ENDC}")
    
    # Show active effects
    print(f"{Colors.YELLOW}Active Effects: {len(character.effects)}{Colors.ENDC}")
    for i, effect in enumerate(character.effects):
        effect_type = effect.__class__.__name__
        print(f"  {Colors.YELLOW}Effect {i+1}: {effect_type} '{effect.name}'{Colors.ENDC}")
        
        # Add timing info if available
        if hasattr(effect, 'timing') and effect.timing:
            print(f"    Start Round: {effect.timing.start_round}")
            print(f"    Duration: {effect.duration}")
            print(f"    Application Round: {getattr(effect, '_application_round', 'N/A')}")
            print(f"    Application Turn: {getattr(effect, '_application_turn', 'N/A')}")
            print(f"    Will Expire Next: {getattr(effect, '_will_expire_next', False)}")
            print(f"    Marked for Expiry: {getattr(effect, '_marked_for_expiry', False)}")
            print(f"    Expiry Message Sent: {getattr(effect, '_expiry_message_sent', False)}")

def print_effect_feedback(character):
    """Print effect feedback information for testing the feedback system"""
    print(f"\n{Colors.MAGENTA}Effect Feedback: {len(character.effect_feedback)}{Colors.ENDC}")
    
    if not character.effect_feedback:
        print(f"  {Colors.MAGENTA}No feedback entries{Colors.ENDC}")
        return
    
    for i, feedback in enumerate(character.effect_feedback):
        print(f"  {Colors.MAGENTA}Feedback {i+1}: {feedback.effect_name}{Colors.ENDC}")
        print(f"    Message: {feedback.expiry_message}")
        print(f"    Expired on round: {feedback.round_expired}, turn: {feedback.turn_expired}")
        print(f"    Displayed: {feedback.displayed}")
        print("")

async def run_scenario_1():
    """
    SCENARIO 1: Effect applied DURING character's turn
    
    This tests what happens when an effect is applied during a character's 
    own turn with duration=1. It should last until the end of their NEXT turn.
    """
    print_header("SCENARIO 1: Effect applied DURING character's turn")
    print("Expected: Effect should apply, deal damage at the start of next turn, and wear off at the end of next turn")
    
    # Create test character
    character = Character(
        name="Test1",
        stats=Stats(
            base={stat: 10 for stat in StatType},
            modified={stat: 10 for stat in StatType}
        ),
        resources=Resources(
            current_hp=50,
            max_hp=50,
            current_mp=50,
            max_mp=50
        ),
        defense=DefenseStats(
            base_ac=10,
            current_ac=10
        )
    )
    
    # Create combat logger for effect processing
    combat_logger = CombatLogger()
    
    # Track rounds
    round_num = 1
    
    # === ROUND 1 START ===
    print_round(round_num, character.name)
    
    # Process turn start - should be no effects yet
    print_phase("TURN START", character.name)
    was_skipped, start_msgs, _ = await process_effects(character, round_num, character.name, combat_logger)
    for msg in start_msgs:
        print_effect_message("TURN START", msg)
        
    # Apply the burn effect DURING their turn
    print_phase("APPLY EFFECT", character.name)
    print(f"Applying burn effect with damage=1, duration=1 to {character.name}")
    burn_effect = BurnEffect("1", duration=1)
    apply_msg = await apply_effect(character, burn_effect, round_num, combat_logger)
    print_effect_message("APPLY", apply_msg)
    
    # Process turn end
    print_phase("TURN END", character.name)
    was_skipped, _, end_msgs = await process_effects(character, round_num, character.name, combat_logger)
    for msg in end_msgs:
        print_effect_message("TURN END", msg)
    
    # Show character status
    print_character_status(character, round_num)
    print_effect_feedback(character)
    
    # === ROUND 2 START ===
    round_num = 2
    print_round(round_num, character.name)
    
    # Process turn start - should see damage applied
    print_phase("TURN START", character.name)
    was_skipped, start_msgs, _ = await process_effects(character, round_num, character.name, combat_logger)
    for msg in start_msgs:
        print_effect_message("TURN START", msg)
    
    # Process turn end - effect should expire here
    print_phase("TURN END", character.name)
    was_skipped, _, end_msgs = await process_effects(character, round_num, character.name, combat_logger)
    for msg in end_msgs:
        print_effect_message("TURN END", msg)
    
    # Show character status
    print_character_status(character, round_num)
    print_effect_feedback(character)
    
    # === ROUND 3 START (verification) ===
    round_num = 3
    print_round(round_num, character.name)
    
    # Process turn start - should be no effects
    print_phase("TURN START", character.name)
    was_skipped, start_msgs, _ = await process_effects(character, round_num, character.name, combat_logger)
    for msg in start_msgs:
        print_effect_message("TURN START", msg)
    
    # Show character status - should be no effects
    print_character_status(character, round_num)
    print_effect_feedback(character)

async def run_scenario_2():
    """
    SCENARIO 2: Effect applied BEFORE character's turn
    
    This tests what happens when an effect is applied to a character
    before their turn in the same round. With duration=1, it should
    expire at the end of their current turn.
    """
    print_header("SCENARIO 2: Effect applied BEFORE character's turn")
    print("Expected: Effect should apply, deal damage at the start of current turn, and wear off at the end of current turn")
    
    # Create two test characters
    char1 = Character(
        name="Attacker",
        stats=Stats(
            base={stat: 10 for stat in StatType},
            modified={stat: 10 for stat in StatType}
        ),
        resources=Resources(
            current_hp=50,
            max_hp=50,
            current_mp=50,
            max_mp=50
        ),
        defense=DefenseStats(
            base_ac=10,
            current_ac=10
        )
    )
    
    char2 = Character(
        name="Target",
        stats=Stats(
            base={stat: 10 for stat in StatType},
            modified={stat: 10 for stat in StatType}
        ),
        resources=Resources(
            current_hp=50,
            max_hp=50,
            current_mp=50,
            max_mp=50
        ),
        defense=DefenseStats(
            base_ac=10,
            current_ac=10
        )
    )
    
    # Create combat logger for effect processing
    combat_logger = CombatLogger()
    
    # Track rounds
    round_num = 1
    
    # === ROUND 1: ATTACKER'S TURN ===
    print_round(round_num, char1.name)
    
    # Process attacker's turn (not important for this test)
    print_phase("TURN START", char1.name)
    was_skipped, start_msgs, _ = await process_effects(char1, round_num, char1.name, combat_logger)
    
    # Apply the burn effect to Target BEFORE their turn
    print_phase("APPLY EFFECT", f"{char1.name} → {char2.name}")
    print(f"Applying burn effect with damage=1, duration=1 to {char2.name}")
    burn_effect = BurnEffect("1", duration=1)
    apply_msg = await apply_effect(char2, burn_effect, round_num, combat_logger)
    print_effect_message("APPLY", apply_msg)
    
    # Show target's status after effect application
    print_character_status(char2, round_num)
    
    # === ROUND 1: TARGET'S TURN ===
    print_round(round_num, char2.name)
    
    # Process target's turn start - should see damage applied
    print_phase("TURN START", char2.name)
    was_skipped, start_msgs, _ = await process_effects(char2, round_num, char2.name, combat_logger)
    for msg in start_msgs:
        print_effect_message("TURN START", msg)
    
    # Process target's turn end - effect should expire here
    print_phase("TURN END", char2.name)
    was_skipped, _, end_msgs = await process_effects(char2, round_num, char2.name, combat_logger)
    for msg in end_msgs:
        print_effect_message("TURN END", msg)
    
    # Show target's status after their turn
    print_character_status(char2, round_num)
    print_effect_feedback(char2)
    
    # === ROUND 2: TARGET'S TURN (verification) ===
    round_num = 2
    print_round(round_num, char2.name)
    
    # Process target's turn start - should be no effects
    print_phase("TURN START", char2.name)
    was_skipped, start_msgs, _ = await process_effects(char2, round_num, char2.name, combat_logger)
    for msg in start_msgs:
        print_effect_message("TURN START", msg)
    
    # Show target's status - should be no effects
    print_character_status(char2, round_num)
    print_effect_feedback(char2)

async def run_scenario_3():
    """
    SCENARIO 3: Testing feedback system with effect removal
    
    This tests the effect feedback system when an effect is manually
    removed before it has a chance to expire normally.
    """
    print_header("SCENARIO 3: Effect feedback system with effect removal")
    print("Expected: Effect should be properly removed but expiry message should still show next round")
    
    # Create test character
    character = Character(
        name="FeedbackTest",
        stats=Stats(
            base={stat: 10 for stat in StatType},
            modified={stat: 10 for stat in StatType}
        ),
        resources=Resources(
            current_hp=50,
            max_hp=50,
            current_mp=50,
            max_mp=50
        ),
        defense=DefenseStats(
            base_ac=10,
            current_ac=10
        )
    )
    
    # Create combat logger for effect processing
    combat_logger = CombatLogger()
    
    # Track rounds
    round_num = 1
    
    # === ROUND 1 START ===
    print_round(round_num, character.name)
    
    # Apply the burn effect
    print_phase("APPLY EFFECT", character.name)
    print(f"Applying burn effect with damage=1, duration=2 to {character.name}")
    burn_effect = BurnEffect("1", duration=2)
    apply_msg = await apply_effect(character, burn_effect, round_num, combat_logger)
    print_effect_message("APPLY", apply_msg)
    
    # Process turn start - should see damage
    print_phase("TURN START", character.name)
    was_skipped, start_msgs, _ = await process_effects(character, round_num, character.name, combat_logger)
    for msg in start_msgs:
        print_effect_message("TURN START", msg)
    
    # Process turn end
    print_phase("TURN END", character.name)
    was_skipped, _, end_msgs = await process_effects(character, round_num, character.name, combat_logger)
    for msg in end_msgs:
        print_effect_message("TURN END", msg)
    
    # Show character status with effect
    print_character_status(character, round_num)
    
    # Manually remove the effect (simulating a /effect remove command)
    print_section("MANUAL EFFECT REMOVAL")
    print("Simulating player using /effect remove command")
    
    removed = False
    for effect in character.effects[:]:  # Copy list since we're modifying it
        if isinstance(effect, BurnEffect):
            expire_msg = effect.on_expire(character)
            character.effects.remove(effect)
            print_effect_message("MANUAL REMOVE", expire_msg)
            removed = True
    
    if not removed:
        print("No burn effect found to remove")
    
    # Show character status after removal
    print_character_status(character, round_num)
    print_effect_feedback(character)
    
    # === ROUND 2 START ===
    round_num = 2
    print_round(round_num, character.name)
    
    # Process turn start - should see feedback message but no damage
    print_phase("TURN START", character.name)
    was_skipped, start_msgs, _ = await process_effects(character, round_num, character.name, combat_logger)
    if start_msgs:
        for msg in start_msgs:
            print_effect_message("TURN START", msg)
    else:
        print("No start messages (expected if feedback not working)")
    
    # Show character status - effect should be completely gone
    print_character_status(character, round_num)
    print_effect_feedback(character)

async def run_scenario_4():
    """
    SCENARIO 4: Removing effects in different ways
    
    This tests removing effects through various methods to see how the
    feedback system handles each case.
    """
    print_header("SCENARIO 4: Removing effects in different ways")
    print("Expected: All removal methods should generate proper feedback messages")
    
    # Create test character
    character = Character(
        name="RemovalTest",
        stats=Stats(
            base={stat: 10 for stat in StatType},
            modified={stat: 10 for stat in StatType}
        ),
        resources=Resources(
            current_hp=50,
            max_hp=50,
            current_mp=50,
            max_mp=50
        ),
        defense=DefenseStats(
            base_ac=10,
            current_ac=10
        )
    )
    
    # Create combat logger for effect processing
    combat_logger = CombatLogger()
    
    # Track rounds
    round_num = 1
    
    # === ROUND 1 START ===
    print_round(round_num, character.name)
    
    # Apply 3 burn effects with different durations
    print_phase("APPLY EFFECTS", character.name)
    
    # Effect 1: Duration = 1
    burn1 = BurnEffect("1", duration=1)
    msg1 = await apply_effect(character, burn1, round_num, combat_logger)
    print_effect_message("APPLY 1", msg1)
    
    # Effect 2: Duration = 2
    burn2 = BurnEffect("2", duration=2)
    burn2.name = "Burn2"  # Rename for clarity
    msg2 = await apply_effect(character, burn2, round_num, combat_logger)
    print_effect_message("APPLY 2", msg2)
    
    # Effect 3: Duration = 3
    burn3 = BurnEffect("3", duration=3)
    burn3.name = "Burn3"  # Rename for clarity
    msg3 = await apply_effect(character, burn3, round_num, combat_logger)
    print_effect_message("APPLY 3", msg3)
    
    # Show character status with all effects
    print_character_status(character, round_num)
    
    # Test different removal methods
    print_section("TESTING REMOVAL METHODS")
    
    # Method 1: Let effect expire naturally
    print("Method 1: Natural expiry (for Burn) - will happen at turn end")
    
    # Method 2: Manual removal
    print("Method 2: Manual removal (for Burn2)")
    for effect in character.effects[:]:
        if getattr(effect, 'name', '') == 'Burn2':
            expire_msg = effect.on_expire(character)
            character.effects.remove(effect)
            print_effect_message("MANUAL REMOVE", expire_msg)
    
    # Method 3: Using remove_effect function
    print("Method 3: Using remove_effect (for Burn3)")
    for effect in character.effects[:]:
        if getattr(effect, 'name', '') == 'Burn3':
            from core.effects.manager import remove_effect
            result = await remove_effect(character, effect.name, combat_logger)
            print_effect_message("FUNCTION REMOVE", result)
    
    # Process turn end for natural expiry
    print_phase("TURN END", character.name)
    was_skipped, _, end_msgs = await process_effects(character, round_num, character.name, combat_logger)
    for msg in end_msgs:
        print_effect_message("TURN END", msg)
    
    # Show character status after removals
    print_character_status(character, round_num)
    print_effect_feedback(character)
    
    # === ROUND 2 START ===
    round_num = 2
    print_round(round_num, character.name)
    
    # Process turn start - should see feedback messages from all removal methods
    print_phase("TURN START", character.name)
    was_skipped, start_msgs, _ = await process_effects(character, round_num, character.name, combat_logger)
    if start_msgs:
        for msg in start_msgs:
            print_effect_message("TURN START", msg)
    else:
        print("No start messages (indicates feedback system failure)")
    
    # Show character status - all effects should be gone
    print_character_status(character, round_num)
    print_effect_feedback(character)

async def run_all_tests():
    """Run all test scenarios"""
    register_effects()
    
    await run_scenario_1()
    time.sleep(1)  # Brief pause between scenarios
    
    await run_scenario_2()
    time.sleep(1)
    
    await run_scenario_3()
    time.sleep(1)
    
    await run_scenario_4()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test the burn effect system")
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3, 4], 
                        help="Run a specific test scenario (1-4)")
    args = parser.parse_args()
    
    print_header("BURN EFFECT SYSTEM TEST")
    register_effects()  # Register effects before testing
    
    if args.scenario:
        if args.scenario == 1:
            asyncio.run(run_scenario_1())
        elif args.scenario == 2:
            asyncio.run(run_scenario_2())
        elif args.scenario == 3:
            asyncio.run(run_scenario_3())
        elif args.scenario == 4:
            asyncio.run(run_scenario_4())
    else:
        # Run all scenarios by default
        asyncio.run(run_all_tests())