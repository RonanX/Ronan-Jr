"""
Test turn-based duration handling for MoveEffect.

This test specifically validates:
1. Moves used during character's turn get duration+1 internally
2. Moves used outside character's turn get normal duration
3. Display formatting is consistent regardless of internal duration
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

# Import required classes
from core.character import Character, Stats, Resources, DefenseStats, StatType
from core.effects.move import MoveEffect, MoveState, RollTiming
from modules.combat.initiative import InitiativeTracker, CombatState

class MockBot:
    """Mock bot class for testing"""
    def __init__(self):
        self.game_state = MagicMock()
        self.db = MagicMock()
        self.initiative_tracker = None
        
async def test_turn_based_moves(bot):
    """
    Test turn-based move duration handling.
    
    This test demonstrates the behavior of moves when applied:
    1. During the character's own turn
    2. Not during the character's own turn
    
    Expected behavior:
    - When applied during character's turn:
      - Duration is internally increased by 1
      - Displayed duration matches original value
      - Duration correctly counts down
    - When applied outside character's turn:
      - Duration works normally
      - No special handling needed
    """
    print("\n=== Testing Turn-Based Move Duration ===")
    
    # Create test characters
    test_chars = ["test1", "test2"]
    characters = {}
    
    for name in test_chars:
        stats = Stats(
            base={
                StatType.STRENGTH: 10,
                StatType.DEXTERITY: 12,
                StatType.CONSTITUTION: 10,
                StatType.INTELLIGENCE: 14,
                StatType.WISDOM: 10,
                StatType.CHARISMA: 10
            },
            modified={
                StatType.STRENGTH: 10,
                StatType.DEXTERITY: 12,
                StatType.CONSTITUTION: 10,
                StatType.INTELLIGENCE: 14,
                StatType.WISDOM: 10,
                StatType.CHARISMA: 10
            }
        )
        
        resources = Resources(
            current_hp=50,
            max_hp=50,
            current_mp=100,
            max_mp=100
        )
        
        defense = DefenseStats(
            base_ac=12,
            current_ac=12
        )
        
        char = Character(
            name=name,
            stats=stats,
            resources=resources,
            defense=defense
        )
        
        # Add to dict
        characters[name] = char
        # Add to game state
        bot.game_state.get_character = lambda n: characters.get(n)
    
    # Setup initiative tracker with these characters
    tracker = InitiativeTracker(bot)
    tracker.set_quiet_mode(True)  # Reduce console noise
    tracker.state = CombatState.ACTIVE
    tracker.turn_order = [
        MagicMock(character_name="test1"),
        MagicMock(character_name="test2")
    ]
    tracker.current_index = 0  # test1's turn
    tracker.round_number = 1
    
    # Set up bot with tracker
    bot.initiative_tracker = tracker
    
    # Get the characters
    test1 = characters["test1"]
    test2 = characters["test2"]
    
    print("\n=== Test 1: Move used DURING character's turn ===")
    # Set to test1's turn
    tracker.current_index = 0
    
    # Create a move with 1 turn duration
    during_move = MoveEffect(
        name="During Turn Buff",
        description="Buff applied during character's turn",
        duration=1,
        mp_cost=5
    )
    
    # Apply the move to test1 (whose turn it is)
    print("Applying move during test1's turn...")
    await during_move.on_apply(test1, tracker.round_number)
    
    # Check the internal vs. displayed duration
    print(f"Original duration: {during_move.state_machine.duration}")
    print(f"Internal turns_remaining: {during_move.state_machine.turns_remaining}")
    print(f"Displayed duration: {during_move.displayed_duration}")
    print(f"Applied during own turn flag: {during_move.applied_during_own_turn}")
    print(f"State machine duration_adjusted flag: {during_move.state_machine.duration_adjusted}")
    
    # Process turn end for test1
    print("\nProcessing test1's turn end...")
    messages = await during_move.on_turn_end(test1, tracker.round_number, test1.name)
    for msg in messages:
        print(f"- {msg}")
        
    # Change to test2's turn
    tracker.current_index = 1
    
    # Process turn end for test2
    print("\nProcessing test2's turn...")
    # No messages since it's not the effect owner's turn
    messages = await during_move.on_turn_end(test1, tracker.round_number, test2.name)
    
    # Move to round 2, test1's turn
    tracker.round_number = 2
    tracker.current_index = 0
    
    # Process turn start for test1 on round 2
    print("\nProcessing test1's turn start on round 2...")
    messages = await during_move.on_turn_start(test1, tracker.round_number, test1.name)
    for msg in messages:
        print(f"- {msg}")
    
    # Process turn end for test1 on round 2
    print("\nProcessing test1's turn end on round 2...")
    messages = await during_move.on_turn_end(test1, tracker.round_number, test1.name)
    for msg in messages:
        print(f"- {msg}")
    
    # Check if effect is marked for removal
    print(f"\nEffect state at end of cycle:")
    print(f"Marked for removal: {during_move.marked_for_removal}")
    print(f"Is expired: {during_move.is_expired}")
    print(f"State machine should_be_removed: {during_move.state_machine.should_be_removed}")
    
    # Clear effect from character
    test1.effects = []
    
    print("\n=== Test 2: Move used NOT DURING character's turn ===")
    # Set to test2's turn
    tracker.current_index = 1
    
    # Create another move with 1 turn duration
    outside_move = MoveEffect(
        name="Outside Turn Buff",
        description="Buff applied outside character's turn",
        duration=1,
        mp_cost=5
    )
    
    # Apply the move to test1 (but it's test2's turn)
    print("Applying move to test1 during test2's turn...")
    await outside_move.on_apply(test1, tracker.round_number)
    
    # Check the internal vs. displayed duration
    print(f"Original duration: {outside_move.state_machine.duration}")
    print(f"Internal turns_remaining: {outside_move.state_machine.turns_remaining}")
    print(f"Displayed duration: {outside_move.displayed_duration}")
    print(f"Applied during own turn flag: {outside_move.applied_during_own_turn}")
    print(f"State machine duration_adjusted flag: {outside_move.state_machine.duration_adjusted}")
    
    # Move to round 3, test1's turn
    tracker.round_number = 3
    tracker.current_index = 0
    
    # Process turn start for test1 on round 3
    print("\nProcessing test1's turn start on round 3...")
    messages = await outside_move.on_turn_start(test1, tracker.round_number, test1.name)
    for msg in messages:
        print(f"- {msg}")
    
    # Process turn end for test1 on round 3
    print("\nProcessing test1's turn end on round 3...")
    messages = await outside_move.on_turn_end(test1, tracker.round_number, test1.name)
    for msg in messages:
        print(f"- {msg}")
    
    # Check if effect is marked for removal
    print(f"\nEffect state at end of cycle:")
    print(f"Marked for removal: {outside_move.marked_for_removal}")
    print(f"Is expired: {outside_move.is_expired}")
    print(f"State machine should_be_removed: {outside_move.state_machine.should_be_removed}")
    
    print("\n=== Turn-Based Move Tests Complete ===")
    return "Turn-based move tests completed"
    
async def run_tests():
    """Run all tests"""
    # Create mock bot
    bot = MockBot()
    
    # Run turn-based duration test
    await test_turn_based_moves(bot)
    
if __name__ == "__main__":
    # Run tests
    asyncio.run(run_tests())