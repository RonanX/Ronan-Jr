"""
Test character management helper.
Creates consistent test characters with clean state.
Also contains debug test methods for various systems.
"""

from core.character import Character, Stats, Resources, DefenseStats, StatType
from core.effects.move import MoveEffect, MoveState, RollTiming
from core.effects.status import SkipEffect, FrostbiteEffect, ACEffect
from core.effects.manager import process_effects
from modules.combat.initiative import CombatState
from typing import List, Dict, Optional, Tuple, Any
import logging
import asyncio

# Function for quickly deleting and recreating test-test4
async def recreate_test_characters(bot) -> List[str]:
    """
    Delete and recreate standard test characters.
    Returns list of created character names.
    """
    test_chars = ["test", "test2", "test3", "test4"]
    
    try:
        print("\n=== Recreating Test Characters ===")
        
        # Delete existing if any
        for name in test_chars:
            await bot.db.delete_character(name)
            if name in bot.game_state.characters:
                del bot.game_state.characters[name]
        
        # Base stats template
        base_stats = {
            StatType.STRENGTH: 10,
            StatType.DEXTERITY: 12,  # +1 modifier for initiative
            StatType.CONSTITUTION: 10,
            StatType.INTELLIGENCE: 14, # +2 for attack rolls
            StatType.WISDOM: 10,
            StatType.CHARISMA: 10
        }
        
        # Create each character
        for name in test_chars:
            stats = Stats(
                base=base_stats.copy(),
                modified=base_stats.copy()
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
            
            # Add to game state
            bot.game_state.add_character(char)
            
            # Save to database
            await bot.db.save_character(char)
            print(f"  Created character: {name}")
            
        print(f"=== Recreated {len(test_chars)} test characters ===")
        return test_chars
        
    except Exception as e:
        print(f"Error recreating test characters: {e}")
        return []

# New function to run all move effect tests
async def run_move_effect_tests(bot, interaction):
    """Run all move effect tests"""
    # Temporarily disable database verbose logging
    was_debug_enabled = getattr(bot.db, 'debug_mode', False)
    bot.db.debug_mode = False
    
    try:
        print("\n=== Starting Move Effect Tests ===")
        await test_instant_move(bot, interaction)
        await asyncio.sleep(1)  # Brief pause between tests
        
        await test_cast_time_move(bot, interaction)
        await asyncio.sleep(1)
        
        await test_duration_move(bot, interaction)
        await asyncio.sleep(1)
        
        await test_cooldown_move(bot, interaction)
        await asyncio.sleep(1)
        
        await test_full_phase_move(bot, interaction)
        await asyncio.sleep(1)
        
        await test_resource_costs(bot, interaction)
        await asyncio.sleep(1)
        
        await test_attack_move(bot, interaction)
        await asyncio.sleep(1)
        
        await test_multi_target_move(bot, interaction)
        await asyncio.sleep(1)
        
        await test_cleanup(bot, interaction)
        print("\n=== Move Effect Tests Complete ===")
    finally:
        # Restore original debug mode setting
        bot.db.debug_mode = was_debug_enabled

# Helper for processing turns in test scenarios
async def process_turns(bot, interaction, char_names: list, turns: int):
    """Process a specific number of turns for testing"""
    print(f"\nProcessing {turns} turns with characters: {', '.join(char_names)}")
    
    # Get the initiative tracker
    tracker = bot.initiative_tracker
    
    # Set up testing combat if not already in one
    if tracker.state == CombatState.INACTIVE:
        print("Setting up test combat...")
        # Just log the battle setup, don't use the interaction
        success, message = await tracker.set_battle(
            char_names,
            interaction,
            round_number=1,
            current_turn=0
        )
        if not success:
            print(f"Failed to set up combat: {message}")
            return
        
        # Force the combat state to be ACTIVE since we can't respond to interaction again
        tracker.state = CombatState.ACTIVE
        print("\n=== Combat Started ===")
        tracker.logger.channel_id = None  # Disable logger channel sending
    
    # Create a channel reference for logging but no messages
    class DummyChannel:
        async def send(self, *args, **kwargs):
            return None
    
    class DummyInteraction:
        def __init__(self):
            self.channel = DummyChannel()
            
        async def response(self):
            return None
            
        async def followup(self):
            return None
            
        async def followup(self, *args, **kwargs):
            return None
            
    dummy_interaction = DummyInteraction()
    
    # Process the requested number of turns without sending Discord messages
    for i in range(turns):
        print(f"\n--- Turn {i+1} ---")
        
        # Skip the next_turn method and manually advance
        # This avoids sending Discord messages
        if tracker.turn_order:
            current_char_name = tracker.turn_order[tracker.current_index].character_name
            current_char = bot.game_state.get_character(current_char_name)
            
            if current_char:
                print(f"Current Character: {current_char_name}")
                print(f"Round: {tracker.round_number}")
                
                # Process effects manually
                was_skipped, start_msgs, end_msgs = process_effects(
                    current_char,
                    tracker.round_number,
                    current_char_name,
                    None  # No combat logger
                )
                
                # Show effect details
                if current_char.effects:
                    print("Active effects:")
                    for effect in current_char.effects:
                        print(f"  • {effect.name} ({effect.__class__.__name__})")
                        
                        # Show move-specific details
                        if hasattr(effect, 'state'):
                            print(f"    - State: {effect.state}")
                            # Show phase information if available
                            if hasattr(effect, 'phases'):
                                for state, phase in effect.phases.items():
                                    if phase:
                                        print(f"    - {state} phase: {phase.duration} turns, {phase.turns_completed} completed")
                        
                        # Show timing details if available
                        if hasattr(effect, 'timing') and effect.timing:
                            print(f"    - Started: Round {effect.timing.start_round}, {effect.timing.start_turn}'s turn")
                            print(f"    - Duration: {effect.timing.duration if effect.timing.duration is not None else 'Permanent'}")
                else:
                    print("No active effects")
                    
                # Show effect messages
                if start_msgs:
                    print("Start of turn messages:")
                    for msg in start_msgs:
                        print(f"  • {msg}")
                
                if end_msgs:
                    print("End of turn messages:")
                    for msg in end_msgs:
                        print(f"  • {msg}")
                
                # Save character
                await bot.db.save_character(current_char)
                
                # Advance to next turn
                tracker.current_index += 1
                if tracker.current_index >= len(tracker.turn_order):
                    tracker.round_number += 1
                    tracker.current_index = 0
                    print(f"\n=== Round {tracker.round_number} Begins ===")
                    
                    # Refresh stars on round transition
                    for turn in tracker.turn_order:
                        char = bot.game_state.get_character(turn.character_name)
                        if char:
                            char.refresh_stars()
            else:
                print(f"Character {current_char_name} not found")
        
        # Brief pause for readability
        await asyncio.sleep(0.2)
    
    # End combat when done
    tracker.end_combat()
    print("\n=== Combat Ended ===")
    print("Test combat complete")

### Helpers for move debugging ###
async def test_instant_move(bot, interaction):
    """Test instant move with no phases"""
    print("\n=== Test 1: Instant Move ===")
    
    # Get test character
    char = bot.game_state.get_character("test")
    if not char:
        print("Test character not found!")
        return
    
    # Reset character state
    char.effects = []
    char.resources.current_mp = char.resources.max_mp
    char.resources.current_hp = char.resources.max_hp
    char.action_stars.refresh()
    
    print("Initial state:")
    print(f"MP: {char.resources.current_mp}/{char.resources.max_mp}")
    print(f"HP: {char.resources.current_hp}/{char.resources.max_hp}")
    print(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars}")
    
    # Create and apply instant move
    move = MoveEffect(
        name="Quick Strike",
        description="A basic attack with no phases",
        mp_cost=5,
        star_cost=2
    )
    
    print("\nApplying instant move...")
    # Use current round 1 for non-combat testing
    result = char.add_effect(move, 1)
    print(f"Apply result: {result}")
    
    # Apply star cost manually (this should now be handled in the MoveEffect)
    char.action_stars.use_stars(move.star_cost, move.name)
    
    # Check post-application state
    print("\nPost-application state:")
    print(f"MP: {char.resources.current_mp}/{char.resources.max_mp} (expected: -{move.mp_cost})")
    print(f"HP: {char.resources.current_hp}/{char.resources.max_hp}")
    print(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars} (expected: -{move.star_cost})")
    
    # Check if it's still in effects list (should be removed immediately)
    has_effect = any(e.name == move.name for e in char.effects)
    print(f"Still has effect: {has_effect} (expected: False for instant moves)")
    
    # If it's still there, manually transition state to simulate completion
    for effect in char.effects[:]:
        if effect.name == move.name:
            print("Manually cleaning up instant move effect (should happen automatically)")
            effect.on_expire(char)
            char.effects.remove(effect)
    
    # Save character
    await bot.db.save_character(char)
    
    print("Instant move test complete")

async def test_cast_time_move(bot, interaction):
    """Test move with cast time only"""
    print("\n=== Test 2: Cast Time Move ===")
    
    # Get test character
    char = bot.game_state.get_character("test")
    if not char:
        print("Test character not found!")
        return
    
    # Reset character state
    char.effects = []
    char.resources.current_mp = char.resources.max_mp
    char.resources.current_hp = char.resources.max_hp
    char.action_stars.refresh()
    
    print("Initial state:")
    print(f"MP: {char.resources.current_mp}/{char.resources.max_mp}")
    print(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars}")
    
    # Create move with cast time
    move = MoveEffect(
        name="Fireball",
        description="A powerful fire attack with cast time",
        mp_cost=10,
        star_cost=2,
        cast_time=2  # 2 turns to cast
    )
    
    print("\nApplying cast time move...")
    result = char.add_effect(move, 1)
    print(f"Apply result: {result}")
    
    # Apply star cost manually (should be handled by the effect now)
    char.action_stars.use_stars(move.star_cost, move.name)
    
    # Check post-application state
    print("\nPost-application state:")
    print(f"MP: {char.resources.current_mp}/{char.resources.max_mp} (expected: -{move.mp_cost})")
    print(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars} (expected: -{move.star_cost})")
    
    # Verify initial state
    has_effect = any(e.name == move.name for e in char.effects)
    print(f"Has effect: {has_effect} (expected: True during cast time)")
    
    move_effect = next((e for e in char.effects if e.name == move.name), None)
    if move_effect:
        print(f"Move state: {move_effect.state} (expected: CASTING)")
    
    # Save character
    await bot.db.save_character(char)
    
    # Process turns to see phase transition
    print("\nProcessing turns to see cast completion...")
    await process_turns(bot, interaction, ["test", "test2"], 3)  # 2 turns for cast + 1 extra
    
    # Refresh character reference
    char = bot.game_state.get_character("test")
    
    # Check if effect was completed/removed properly
    has_effect = any(e.name == move.name for e in char.effects)
    print(f"\nFinal state - Has effect: {has_effect} (expected: False after cast completion)")
    
    # Manually clean up if needed - effects may not be auto-removed in test environment
    if has_effect:
        print("Manually cleaning up cast time move effect")
        for effect in char.effects[:]:
            if effect.name == move.name:
                effect.on_expire(char)
                char.effects.remove(effect)
        await bot.db.save_character(char)
    
    print("Cast time move test complete")

async def test_duration_move(bot, interaction):
    """Test move with duration only"""
    print("\n=== Test 3: Duration Move ===")
    
    # Get test character
    char = bot.game_state.get_character("test")
    if not char:
        print("Test character not found!")
        return
    
    # Reset character state
    char.effects = []
    char.resources.current_mp = char.resources.max_mp
    char.resources.current_hp = char.resources.max_hp
    char.action_stars.refresh()
    
    print("Initial state:")
    print(f"MP: {char.resources.current_mp}/{char.resources.max_mp}")
    print(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars}")
    
    # Create move with duration
    move = MoveEffect(
        name="Defensive Stance",
        description="A defensive buff that lasts 3 turns",
        mp_cost=8,
        star_cost=1,
        duration=3  # 3 turn duration
    )
    
    print("\nApplying duration move...")
    result = char.add_effect(move, 1)
    print(f"Apply result: {result}")
    
    # Apply star cost manually
    char.action_stars.use_stars(move.star_cost, move.name)
    
    # Check post-application state
    print("\nPost-application state:")
    print(f"MP: {char.resources.current_mp}/{char.resources.max_mp} (expected: -{move.mp_cost})")
    print(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars} (expected: -{move.star_cost})")
    
    # Verify initial state
    has_effect = any(e.name == move.name for e in char.effects)
    print(f"Has effect: {has_effect} (expected: True)")
    
    move_effect = next((e for e in char.effects if e.name == move.name), None)
    if move_effect:
        print(f"Move state: {move_effect.state} (expected: ACTIVE)")
    
    # Save character
    await bot.db.save_character(char)
    
    # Process turns to see duration tracking
    print("\nProcessing turns to see duration tracking...")
    await process_turns(bot, interaction, ["test", "test2"], 4)  # 3 turns duration + 1 extra
    
    # Refresh character reference
    char = bot.game_state.get_character("test")
    
    # Check if effect was completed/removed properly
    has_effect = any(e.name == move.name for e in char.effects)
    print(f"\nFinal state - Has effect: {has_effect} (expected: False after duration)")
    
    # Manually clean up if needed
    if has_effect:
        print("Manually cleaning up duration move effect")
        for effect in char.effects[:]:
            if effect.name == move.name:
                effect.on_expire(char)
                char.effects.remove(effect)
        await bot.db.save_character(char)
    
    print("Duration move test complete")
    
async def test_cooldown_move(bot, interaction):
    """Test move with cooldown only"""
    print("\n=== Test 4: Cooldown Move ===")
    
    # Get test character
    char = bot.game_state.get_character("test")
    if not char:
        print("Test character not found!")
        return
    
    # Reset character state
    char.effects = []
    char.resources.current_mp = char.resources.max_mp
    char.resources.current_hp = char.resources.max_hp
    char.action_stars.refresh()
    
    print("Initial state:")
    print(f"MP: {char.resources.current_mp}/{char.resources.max_mp}")
    print(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars}")
    
    # Create move with cooldown
    move = MoveEffect(
        name="Power Strike",
        description="A powerful attack with cooldown",
        mp_cost=5,
        star_cost=1,
        cooldown=2  # 2 turn cooldown
    )
    
    print("\nApplying cooldown move...")
    result = char.add_effect(move, 1)
    print(f"Apply result: {result}")
    
    # Apply star cost manually
    char.action_stars.use_stars(move.star_cost, move.name)
    
    # Check post-application state
    print("\nPost-application state:")
    print(f"MP: {char.resources.current_mp}/{char.resources.max_mp} (expected: -{move.mp_cost})")
    print(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars} (expected: -{move.star_cost})")
    
    # Check initial state (should be in cooldown)
    move_effect = next((e for e in char.effects if e.name == move.name), None)
    if move_effect:
        print(f"Move state: {move_effect.state} (expected: COOLDOWN)")
        # Check if cooldown phase exists
        cooldown_phase = move_effect.phases.get(MoveState.COOLDOWN)
        if cooldown_phase:
            print(f"Cooldown phase: {cooldown_phase.duration} turns, {cooldown_phase.turns_completed} completed")
        else:
            print("No cooldown phase found in effect")
    else:
        print("Move effect not found (expected to be in cooldown state)")
    
    # Register move in action stars system (normally done by the move command)
    # Use the correct parameter - get duration from the phase
    cooldown_duration = 2  # Default in case phase doesn't exist
    if move_effect and move_effect.phases.get(MoveState.COOLDOWN):
        cooldown_duration = move_effect.phases[MoveState.COOLDOWN].duration
        
    char.action_stars.start_cooldown(move.name, cooldown_duration)
    
    # Save character
    await bot.db.save_character(char)
    
    # Process turns to see cooldown tracking
    print("\nProcessing turns to see cooldown tracking...")
    await process_turns(bot, interaction, ["test", "test2"], 3)  # 2 turns cooldown + 1 extra
    
    # Refresh character reference
    char = bot.game_state.get_character("test")
    
    # Check cooldown status in action stars
    in_cooldown = move.name in char.action_stars.used_moves
    print(f"\nFinal state - Move in cooldown: {in_cooldown} (expected: False after cooldown)")
    
    # Try to use the move again after cooldown
    move2 = MoveEffect(
        name="Power Strike",
        description="A powerful attack with cooldown",
        mp_cost=5,
        star_cost=1,
        cooldown=2
    )
    
    print("\nAttempting to use move again after cooldown...")
    result = char.add_effect(move2, 4)  # Using round 4 now
    print(f"Apply result: {result}")
    
    # Apply star cost manually
    char.action_stars.use_stars(move2.star_cost, move2.name)
    
    # Save character
    await bot.db.save_character(char)
    
    print("Cooldown move test complete")

async def test_full_phase_move(bot, interaction):
    """Test move with all phases (cast + active + cooldown)"""
    print("\n=== Test 5: Full Phase Move ===")
    
    # Get test character
    char = bot.game_state.get_character("test")
    if not char:
        print("Test character not found!")
        return
    
    # Reset character state
    char.effects = []
    char.resources.current_mp = char.resources.max_mp
    char.resources.current_hp = char.resources.max_hp
    char.action_stars.refresh()
    
    print("Initial state:")
    print(f"MP: {char.resources.current_mp}/{char.resources.max_mp}")
    print(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars}")
    
    # Create full phase move
    move = MoveEffect(
        name="Ultimate Ability",
        description="A powerful ability with all phases",
        mp_cost=15,
        star_cost=3,
        cast_time=2,    # 2 turn cast
        duration=3,     # 3 turn active duration
        cooldown=2      # 2 turn cooldown
    )
    
    print("\nApplying full phase move...")
    result = char.add_effect(move, 1)
    print(f"Apply result: {result}")
    
    # Check post-application state
    print("\nPost-application state:")
    print(f"MP: {char.resources.current_mp}/{char.resources.max_mp} (expected: -{move.mp_cost})")
    print(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars} (expected: -{move.star_cost})")
    
    # Check initial state
    move_effect = next((e for e in char.effects if e.name == move.name), None)
    if move_effect:
        print(f"Move state: {move_effect.state} (expected: CASTING)")
        
        # Show phase info
        for state, phase in move_effect.phases.items():
            if phase:
                print(f"  {state} phase: {phase.duration} turns, {phase.turns_completed} completed")
    
    # Save character
    await bot.db.save_character(char)
    
    # Process turns to see all phase transitions
    print("\nProcessing turns to see all phase transitions...")
    # We need: 2 turns cast + 3 turns active + 2 turns cooldown + 1 extra = 8 turns
    await process_turns(bot, interaction, ["test", "test2"], 8)
    
    # Refresh character reference
    char = bot.game_state.get_character("test")
    
    # Check if effect was completed/removed properly
    has_effect = any(e.name == move.name for e in char.effects)
    print(f"\nFinal state - Has effect: {has_effect} (expected: False after all phases)")
    
    # Check cooldown status in action stars
    in_cooldown = move.name in char.action_stars.used_moves
    print(f"Move in cooldown: {in_cooldown} (expected: False after all phases)")
    
    print("Full phase move test complete")

async def test_resource_costs(bot, interaction):
    """Test resource cost application"""
    print("\n=== Test 6: Resource Costs ===")
    
    # Get test character
    char = bot.game_state.get_character("test")
    if not char:
        print("Test character not found!")
        return
    
    # Reset character state
    char.effects = []
    char.resources.current_mp = char.resources.max_mp
    char.resources.current_hp = char.resources.max_hp
    char.action_stars.refresh()
    
    print("Initial state:")
    print(f"HP: {char.resources.current_hp}/{char.resources.max_hp}")
    print(f"MP: {char.resources.current_mp}/{char.resources.max_mp}")
    print(f"Stars: {char.action_stars.current_stars}/{char.action_stars.max_stars}")
    
    # Test 1: MP cost
    print("\n--- Test 6.1: MP Cost ---")
    move_mp = MoveEffect(
        name="MP Cost Test",
        description="Tests MP cost application",
        mp_cost=5
    )
    
    print("\nApplying MP cost move...")
    initial_mp = char.resources.current_mp
    result = char.add_effect(move_mp, 1)
    print(f"Apply result: {result}")
    print(f"MP change: {initial_mp} → {char.resources.current_mp} (expected: -{move_mp.mp_cost})")
    
    # Test 2: HP cost
    print("\n--- Test 6.2: HP Cost ---")
    move_hp = MoveEffect(
        name="HP Cost Test",
        description="Tests HP cost application",
        hp_cost=5
    )
    
    print("\nApplying HP cost move...")
    initial_hp = char.resources.current_hp
    result = char.add_effect(move_hp, 1)
    print(f"Apply result: {result}")
    print(f"HP change: {initial_hp} → {char.resources.current_hp} (expected: -{move_hp.hp_cost})")
    
    # Test 3: Star cost
    print("\n--- Test 6.3: Star Cost ---")
    move_star = MoveEffect(
        name="Star Cost Test",
        description="Tests star cost application",
        star_cost=2
    )
    
    print("\nApplying star cost move...")
    initial_stars = char.action_stars.current_stars
    result = char.add_effect(move_star, 1)
    print(f"Apply result: {result}")
    print(f"Stars change: {initial_stars} → {char.action_stars.current_stars} (expected: -{move_star.star_cost})")
    
    # Test 4: Multiple costs
    print("\n--- Test 6.4: Multiple Costs ---")
    move_all = MoveEffect(
        name="All Costs Test",
        description="Tests all costs together",
        mp_cost=3,
        hp_cost=3,
        star_cost=1
    )
    
    print("\nApplying move with all costs...")
    initial_hp = char.resources.current_hp
    initial_mp = char.resources.current_mp
    initial_stars = char.action_stars.current_stars
    
    result = char.add_effect(move_all, 1)
    print(f"Apply result: {result}")
    
    print(f"Resource changes:")
    print(f"HP: {initial_hp} → {char.resources.current_hp} (expected: -{move_all.hp_cost})")
    print(f"MP: {initial_mp} → {char.resources.current_mp} (expected: -{move_all.mp_cost})")
    print(f"Stars: {initial_stars} → {char.action_stars.current_stars} (expected: -{move_all.star_cost})")
    
    # Test 5: Insufficient resources
    print("\n--- Test 6.5: Insufficient Resources ---")
    
    # Set resources low
    char.resources.current_mp = 3
    char.action_stars.current_stars = 1
    
    move_expensive = MoveEffect(
        name="Expensive Move",
        description="A move requiring more resources than available",
        mp_cost=10,
        star_cost=3
    )
    
    print("\nAttempting to use move with insufficient resources...")
    print(f"Current MP: {char.resources.current_mp} (need {move_expensive.mp_cost})")
    print(f"Current Stars: {char.action_stars.current_stars} (need {move_expensive.star_cost})")
    
    # Should still work since MoveEffect doesn't validate resources directly
    # In the real command, validation would happen first
    result = char.add_effect(move_expensive, 1)
    print(f"Apply result: {result}")
    
    # Save character
    await bot.db.save_character(char)
    
    print("Resource costs test complete")

async def test_attack_move(bot, interaction):
    """Test move with attack roll"""
    print("\n=== Test 7: Attack Move ===")
    
    # Get test character
    source = bot.game_state.get_character("test")
    target = bot.game_state.get_character("test2")
    
    if not source or not target:
        print("Test characters not found!")
        return
    
    # Reset character state
    source.effects = []
    source.resources.current_mp = source.resources.max_mp
    source.resources.current_hp = source.resources.max_hp
    source.action_stars.refresh()
    
    print("Initial state:")
    print(f"Source: {source.name}")
    print(f"Target: {target.name}")
    print(f"Target AC: {target.defense.current_ac}")
    
    # Test Instant Attack
    print("\n--- Test 7.1: Instant Attack Roll ---")
    instant_attack = MoveEffect(
        name="Instant Attack",
        description="Attack that rolls immediately",
        mp_cost=5,
        attack_roll="1d20+int",
        damage="2d6 fire",
        targets=[target],
        roll_timing=RollTiming.INSTANT
    )
    
    print("\nApplying instant attack move...")
    result = source.add_effect(instant_attack, 1)
    print(f"Apply result: {result}")
    
    # Test Active Phase Attack
    print("\n--- Test 7.2: Active Phase Attack Roll ---")
    active_attack = MoveEffect(
        name="Delayed Attack",
        description="Attack that rolls when active phase begins",
        mp_cost=8,
        cast_time=2,
        duration=1,
        attack_roll="1d20+int",
        damage="3d8 lightning",
        targets=[target],
        roll_timing=RollTiming.ACTIVE
    )
    
    print("\nApplying active attack move (with cast time)...")
    result = source.add_effect(active_attack, 1)
    print(f"Apply result: {result}")
    
    # Save characters
    await bot.db.save_character(source)
    await bot.db.save_character(target)
    
    # Process turns to see cast time → active phase transition and attack roll
    print("\nProcessing turns to see attack roll on active phase...")
    await process_turns(bot, interaction, [source.name, target.name], 3)  # 2 turns cast + 1 active
    
    # Test Per-Turn Attack
    print("\n--- Test 7.3: Per-Turn Attack Roll ---")
    # Reset characters
    source = bot.game_state.get_character("test")
    target = bot.game_state.get_character("test2")
    
    source.effects = []
    source.resources.current_mp = source.resources.max_mp
    source.resources.current_hp = source.resources.max_hp
    source.action_stars.refresh()
    
    per_turn_attack = MoveEffect(
        name="Damage Aura",
        description="Attack that rolls each turn during duration",
        mp_cost=10,
        duration=3,
        attack_roll="1d20+int",
        damage="1d6 necrotic",
        targets=[target],
        roll_timing=RollTiming.PER_TURN
    )
    
    print("\nApplying per-turn attack move...")
    result = source.add_effect(per_turn_attack, 1)
    print(f"Apply result: {result}")
    
    # Save characters
    await bot.db.save_character(source)
    await bot.db.save_character(target)
    
    # Process turns to see attack rolls each turn
    print("\nProcessing turns to see per-turn attack rolls...")
    await process_turns(bot, interaction, [source.name, target.name], 4)  # 3 turns duration + 1 extra
    
    print("Attack move tests complete")

async def test_multi_target_move(bot, interaction):
    """Test move effect targeting multiple characters"""
    print("\n=== Test 8: Multi-Target Move ===")
    
    # Get test characters
    source = bot.game_state.get_character("test")
    targets = [
        bot.game_state.get_character("test2"),
        bot.game_state.get_character("test3")
    ]
    
    if not source or None in targets:
        print("Test characters not found!")
        return
    
    # Reset all character states
    all_chars = [source] + targets
    for char in all_chars:
        char.effects = []
        char.resources.current_mp = char.resources.max_mp
        char.resources.current_hp = char.resources.max_hp
        char.action_stars.refresh()
    
    print("Initial state:")
    print(f"Source: {source.name}")
    print(f"Targets: {[t.name for t in targets]}")
    
    # Create multi-target move
    move = MoveEffect(
        name="Area Effect",
        description="An effect that targets multiple characters",
        mp_cost=10,
        star_cost=2,
        duration=2,     # 2 turn duration
        targets=targets,  # Pass target characters
        attack_roll="1d20+int",  # Add attack roll
        damage="3d6 fire"        # Add damage
    )
    
    print("\nApplying multi-target move...")
    result = source.add_effect(move, 1)
    print(f"Apply result: {result}")
    
    # Check if targets were affected (they should be when passed to the constructor)
    # But in reality, this would require additional coding in the MoveEffect class
    print("\nChecking target effects:")
    for target in targets:
        target_effects = [e for e in target.effects if isinstance(e, MoveEffect)]
        print(f"{target.name}: {len(target_effects)} move effects")
        if target_effects:
            for effect in target_effects:
                print(f"  Effect: {effect.name}")
    
    # Process a few turns to see effects
    print("\nProcessing turns to see multi-target effects...")
    await process_turns(bot, interaction, [c.name for c in all_chars], 3)
    
    # Save characters
    for char in all_chars:
        await bot.db.save_character(char)
    
    print("Multi-target move test complete")

async def test_cleanup(bot, interaction):
    """Test effect cleanup functionality"""
    print("\n=== Test 9: Cleanup Test ===")
    
    # Get all test characters
    test_chars = ["test", "test2", "test3", "test4"]
    characters = []
    
    for name in test_chars:
        char = bot.game_state.get_character(name)
        if char:
            characters.append(char)
    
    if not characters:
        print("No test characters found!")
        return
    
    print(f"Found {len(characters)} test characters to clean up")
    
    # Apply a mix of move effects to all characters
    print("\nApplying test effects before cleanup...")
    
    for i, char in enumerate(characters):
        # Apply different effects based on character
        if i == 0:
            # First character gets a move with all phases
            move = MoveEffect(
                name="Full Test Move",
                description="A move with all phases for cleanup testing",
                mp_cost=5,
                star_cost=1,
                cast_time=1,
                duration=2,
                cooldown=1
            )
            char.add_effect(move, 1)
            print(f"Applied full-phase move to {char.name}")
            
        elif i == 1:
            # Second character gets a duration-only move
            move = MoveEffect(
                name="Duration Test Move",
                description="A move with duration for cleanup testing",
                mp_cost=5,
                duration=3
            )
            char.add_effect(move, 1)
            print(f"Applied duration-only move to {char.name}")
            
        elif i == 2:
            # Third character gets a resource-draining move
            move = MoveEffect(
                name="Resource Test Move",
                description="A move with resource costs for cleanup testing",
                mp_cost=10,
                hp_cost=5,
                star_cost=2
            )
            char.add_effect(move, 1)
            print(f"Applied resource-cost move to {char.name}")
            
        else:
            # Remaining characters get instant moves
            move = MoveEffect(
                name="Instant Test Move",
                description="An instant move for cleanup testing"
            )
            char.add_effect(move, 1)
            print(f"Applied instant move to {char.name}")
    
    # Save characters with effects
    for char in characters:
        await bot.db.save_character(char)
    
    # Check effect state
    print("\nEffect state before cleanup:")
    for char in characters:
        print(f"{char.name}: {len(char.effects)} effects")
        for effect in char.effects:
            print(f"  • {effect.name} ({effect.__class__.__name__})")
            if hasattr(effect, 'state'):
                print(f"    - State: {effect.state}")
    
    # Clean up all effects
    print("\nCleaning up effects...")
    for char in characters:
        # Store original state
        original_hp = char.resources.current_hp
        original_mp = char.resources.current_mp
        original_stars = char.action_stars.current_stars
        original_ac = char.defense.current_ac
        
        # Process cleanup
        cleanup_msgs = []
        for effect in char.effects[:]:  # Copy list since we're modifying it
            if msg := effect.on_expire(char):
                cleanup_msgs.append(msg)
            char.effects.remove(effect)
        
        # Reset state
        char.resources.current_temp_hp = 0
        char.resources.max_temp_hp = 0
        char.defense.current_ac = char.defense.base_ac
        
        # Clear action stars cooldowns
        char.action_stars.clear_cooldowns()
        
        # Log changes
        print(f"\nCleanup for {char.name}:")
        if cleanup_msgs:
            print("Cleanup messages:")
            for msg in cleanup_msgs:
                print(f"  • {msg}")
        
        print(f"State changes:")
        print(f"  HP: {original_hp} → {char.resources.current_hp}")
        print(f"  MP: {original_mp} → {char.resources.current_mp}")
        print(f"  Stars: {original_stars} → {char.action_stars.current_stars}")
        print(f"  AC: {original_ac} → {char.defense.current_ac}")
        
        # Save cleaned character
        await bot.db.save_character(char)
    
    # Verify all effects are cleared
    print("\nFinal state after cleanup:")
    for char in characters:
        print(f"{char.name}: {len(char.effects)} effects")
        if char.effects:
            print("  WARNING: Character still has effects!")
            for effect in char.effects:
                print(f"    • {effect.name}")
    
    print("Cleanup test complete")

### End of helpers for move debugging ###