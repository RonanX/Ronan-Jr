"""
## src/commands/debug_extra/debug_movesets.py

Comprehensive debugging tools for movesets and moves.
Tests various move types, durations, and functionality.

Features:
- Load debug moveset from database
- Test moves with various phases (cast/active/cooldown)
- Test attack rolls and targeting
- Test resource costs and tracking
- Test duration and expiry
"""

import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio
from typing import List, Dict, Optional, Tuple, Any

from core.effects.move import MoveEffect, MoveState, RollTiming
from modules.moves.data import MoveData, Moveset
from modules.moves.loader import MoveLoader
from utils.test_helper import process_turns, recreate_test_characters
from modules.combat.initiative import CombatState

logger = logging.getLogger(__name__)

# Name of the debug moveset in Firebase
DEBUG_MOVESET_NAME = "debug"

# This is the style used in debug files - add functions to the cog
def add_moveset_debug_commands(cog):
    """Register debug commands on the provided cog"""
    print("Registering moveset debug commands...")
    
    # Add functions directly to the cog
    cog.debug_movesets = debug_movesets  # Main test command
    cog.create_debug_moveset = create_debug_moveset
    cog.test_move_basics = test_move_basics
    cog.test_move_initiative = test_move_initiative
    cog.test_move_cooldowns = test_move_cooldowns
    cog.test_move_targeting = test_move_targeting
    cog.test_move_ui = test_move_ui
    cog.test_phase_durations = test_phase_durations  # Test for phases
    
    # Also add helper functions
    cog.load_debug_moveset = load_debug_moveset
    cog.apply_moveset_to_characters = apply_moveset_to_characters
    cog.setup_initiative = setup_initiative
    cog.reset_character_state = reset_character_state
    
    print("Moveset debug commands registered!")

async def load_debug_moveset(bot) -> Optional[Moveset]:
    """Load the debug moveset from Firebase"""
    try:
        # Attempt to load the moveset
        moveset = await MoveLoader.load_global_moveset(bot.db, DEBUG_MOVESET_NAME)
        if not moveset:
            print(f"Debug moveset '{DEBUG_MOVESET_NAME}' not found in database")
            return None
        
        print(f"Loaded debug moveset with {len(moveset.list_moves())} moves")
        return moveset
    except Exception as e:
        print(f"Error loading debug moveset: {e}")
        return None

async def apply_moveset_to_characters(bot, moveset: Moveset, character_names: List[str]) -> List[str]:
    """Apply the moveset to the specified characters"""
    successfully_loaded = []
    
    for name in character_names:
        char = bot.game_state.get_character(name)
        if not char:
            print(f"Character '{name}' not found")
            continue
        
        # Clear any existing moves
        char.moveset.clear()
        
        # Copy moves from debug moveset
        for move_name in moveset.list_moves():
            move = moveset.get_move(move_name)
            if move:
                char.add_move(move)
        
        # Save character
        await bot.db.save_character(char)
        successfully_loaded.append(name)
        print(f"Applied debug moveset to {name}")
    
    return successfully_loaded

async def setup_initiative(bot, interaction, character_names: List[str]) -> bool:
    """Set up initiative for testing"""
    try:
        print("\nSetting up test combat...")
        
        # Get initiative tracker
        tracker = bot.initiative_tracker
        
        # End any existing combat
        if tracker.state != CombatState.INACTIVE:
            tracker.end_combat()
            
        # Set up combat with the character names
        success, message = await tracker.set_battle(
            character_names,
            interaction,
            round_number=1,
            current_turn=0
        )
        
        if not success:
            print(f"Failed to set up combat: {message}")
            return False
            
        # Force the combat state to be ACTIVE
        tracker.state = CombatState.ACTIVE
        print("Combat started successfully")
        
        # Disable logger channel sending if it exists
        if hasattr(tracker, 'logger') and hasattr(tracker.logger, 'channel_id'):
            tracker.logger.channel_id = None
            
        return True
    except Exception as e:
        print(f"Error setting up initiative: {e}")
        return False

async def reset_character_state(bot, character_names: List[str]):
    """Reset character state for testing"""
    for name in character_names:
        char = bot.game_state.get_character(name)
        if not char:
            continue
            
        # Clear effects
        char.effects = []
        
        # Reset resources
        char.resources.current_mp = char.resources.max_mp
        char.resources.current_hp = char.resources.max_hp
        
        # Refresh stars
        char.action_stars.refresh()
        
        # Clear cooldowns in moveset
        if hasattr(char, 'moveset'):
            for move_name in char.list_moves():
                move = char.get_move(move_name)
                if move:
                    move.last_used_round = None
                    if hasattr(move, 'uses_remaining') and move.uses is not None:
                        move.uses_remaining = move.uses
        
        # Save character
        await bot.db.save_character(char)
        print(f"Reset state for {name}")

async def debug_movesets(interaction: discord.Interaction, enable_firebase_logging: bool = False):
    """Run comprehensive moveset debugging"""
    try:
        await interaction.response.defer()
        
        # Get bot reference directly from interaction
        bot = interaction.client
        
        # Set Firebase logging on database if requested
        if hasattr(bot, 'db'):
            bot.db.debug_mode = enable_firebase_logging
            if enable_firebase_logging:
                print("\n:bar_chart: Firebase debug logging ENABLED")
            else:
                print("\n:bar_chart: Firebase debug logging DISABLED")
        
        # First step: Recreate test characters
        print("\nRecreating test characters...")
        await recreate_test_characters(bot)
        
        # Load debug moveset - fixed to pass the bot directly
        print("\nLoading debug moveset...")
        moveset = await load_debug_moveset(bot)
        if not moveset:
            await interaction.followup.send(
                ":x: Debug moveset not found. Please create a moveset called 'debug' in Firebase."
            )
            return
        
        # Apply to test characters
        test_chars = ["test", "test2", "test3", "test4"]
        loaded_chars = await apply_moveset_to_characters(bot, moveset, test_chars)
        
        if not loaded_chars:
            await interaction.followup.send(":x: Failed to load moveset to any test characters")
            return
        
        # Run comprehensive tests
        print("\n=== STARTING COMPREHENSIVE MOVE TESTS ===\n")
        
        # Test 1: Basic move usage - checks move creation and application
        await test_move_basics(interaction, bot)
        
        # Test 2: Initiative with moves - checks how moves behave in combat flow
        await test_move_initiative(interaction, bot)
        
        # Test 3: Move cooldowns - specifically test cooldown tracking and messages
        await test_move_cooldowns(interaction, bot)
        
        # Test 4: Move targeting - tests target selection and attack rolls
        await test_move_targeting(interaction, bot)
        
        # Test 5: Move UI - test UI components like action_handler
        await test_move_ui(interaction, bot)
        
        # Test 6: Phase durations - test timing and transitions
        await test_phase_durations(interaction, bot)
        
        print("\n=== COMPREHENSIVE MOVE TESTS COMPLETE ===\n")
        
        # Restore database debug mode
        if hasattr(bot, 'db'):
            bot.db.debug_mode = False
        
        # Summarize results
        await interaction.followup.send(
            f":white_check_mark: Moveset debugging complete - check console for results\n" +
            f"Firebase logging was {'enabled' if enable_firebase_logging else 'disabled'}"
        )
        
    except Exception as e:
        print(f"Error in movesets debug: {e}")
        await interaction.followup.send(f"Error in debug command: {str(e)}")

async def test_phase_durations(interaction: discord.Interaction, bot):
    """Test phase durations and transitions in detail"""
    try:
        print("\n=== TEST: PHASE DURATIONS AND TRANSITIONS ===\n")
        
        # Reset character state
        await reset_character_state(bot, ["test", "test2"])
        
        # Get test character
        source = bot.game_state.get_character("test")
        if not source:
            print("Test character not found")
            return
        
        # Set up initiative for testing
        success = await setup_initiative(bot, interaction, ["test", "test2"])
        if not success:
            print("Failed to set up initiative")
            return
            
        print("\n=== Testing Move with ALL Phases ===")
        
        # Create a move with all phases for focused testing
        full_move = MoveEffect(
            name="Test All Phases",
            description="Testing all phases with precise durations",
            mp_cost=5,
            star_cost=1,
            cast_time=2,      # 2 turn cast time
            duration=3,       # 3 turn active duration
            cooldown=2        # 2 turn cooldown
        )
        
        # Apply effect
        print("\n[Round 1] Applying effect...")
        result = await full_move.on_apply(source, 1)  # Round 1
        print(f"Apply result: {result}")
        
        # Manually use action stars
        source.action_stars.use_stars(1, full_move.name)
        
        # Print initial state
        print("\nInitial state:")
        print(f"State: {full_move.state}")
        print(f"Phase durations:")
        for state, phase in full_move.phases.items():
            if phase:
                print(f"  {state.name}: {phase.duration} turns, {phase.turns_completed} completed")
        
        # Save character
        await bot.db.save_character(source)
        
        # Process turns to observe all phases
        total_turns = 7  # Need 7 turns for all phases (2 cast + 3 active + 2 cooldown)
        
        for turn in range(1, total_turns + 1):
            print(f"\n[Round {turn+1}] Processing turn {turn}...")
            
            # Advance a turn
            await process_turns(bot, interaction, ["test", "test2"], 1)
            
            # Get updated character and effect
            source = bot.game_state.get_character("test")
            effect = next((e for e in source.effects if e.name == full_move.name), None)
            
            # Check effect state
            if effect:
                print(f"State: {effect.state}")
                print(f"Phase durations:")
                for state, phase in effect.phases.items():
                    if phase:
                        print(f"  {state.name}: {phase.duration} turns, {phase.turns_completed} completed")
            else:
                print(f"Effect no longer exists after turn {turn}")
                if turn < total_turns:
                    print("WARNING: Effect ended earlier than expected!")
                else:
                    print("Effect completed all phases as expected.")
                break
        
        # End combat
        bot.initiative_tracker.end_combat()
        
        print("\n=== Phase Duration Test Complete ===")
        
    except Exception as e:
        print(f"Error in phase duration test: {e}")
        # Clean up
        try:
            bot.initiative_tracker.end_combat()
        except:
            pass

async def test_move_basics(interaction: discord.Interaction, bot):
    """Test basic move usage and functionality"""
    try:
        print("\n=== TEST: BASIC MOVE USAGE ===\n")
        
        # Reset character state
        await reset_character_state(bot, ["test", "test2"])
        
        # Get test character
        source = bot.game_state.get_character("test")
        if not source:
            print("Test character not found")
            return
            
        # List moves
        print("\nAvailable moves:")
        move_names = source.list_moves()
        for name in move_names:
            move = source.get_move(name)
            if move:
                print(f"  • {name}")
                
                # Show costs
                costs = []
                if move.star_cost > 0:
                    costs.append(f"Stars: {move.star_cost}")
                if move.mp_cost != 0:
                    costs.append(f"MP: {move.mp_cost}")
                if move.hp_cost != 0:
                    costs.append(f"HP: {move.hp_cost}")
                if costs:
                    print(f"    - Costs: {', '.join(costs)}")
                
                # Show phases
                phases = []
                if move.cast_time:
                    phases.append(f"Cast: {move.cast_time} turns")
                if move.duration:
                    phases.append(f"Duration: {move.duration} turns")
                if move.cooldown:
                    phases.append(f"Cooldown: {move.cooldown} turns")
                if phases:
                    print(f"    - Phases: {', '.join(phases)}")
        
        # Test creating a MoveEffect
        test_move = None
        if move_names:
            # Find a move with cast time for testing
            for name in move_names:
                move = source.get_move(name)
                if move and move.cast_time:
                    test_move = move
                    break
            
            # If no cast time move found, use any move
            if not test_move and move_names:
                test_move = source.get_move(move_names[0])
        
        if test_move:
            print(f"\nTesting move: {test_move.name}")
            
            # Create MoveEffect from the MoveData
            move_effect = MoveEffect(
                name=test_move.name,
                description=test_move.description,
                mp_cost=test_move.mp_cost,
                hp_cost=test_move.hp_cost,
                star_cost=test_move.star_cost,
                cast_time=test_move.cast_time,
                duration=test_move.duration,
                cooldown=test_move.cooldown,
                attack_roll=test_move.attack_roll,
                damage=test_move.damage
            )
            
            # Check resources before
            print("\nBefore applying effect:")
            print(f"MP: {source.resources.current_mp}/{source.resources.max_mp}")
            print(f"HP: {source.resources.current_hp}/{source.resources.max_hp}")
            print(f"Stars: {source.action_stars.current_stars}/{source.action_stars.max_stars}")
            
            # Apply effect
            result = await move_effect.on_apply(source, 1)
            print(f"\nApply result: {result}")
            
            # Manually use action stars (would normally be done by move command)
            source.action_stars.use_stars(test_move.star_cost, test_move.name)
            
            # Check resources after
            print("\nAfter applying effect:")
            print(f"MP: {source.resources.current_mp}/{source.resources.max_mp}")
            print(f"HP: {source.resources.current_hp}/{source.resources.max_hp}")
            print(f"Stars: {source.action_stars.current_stars}/{source.action_stars.max_stars}")
            
            # Check effect state
            effect = None
            for e in source.effects:
                if e.name == test_move.name:
                    effect = e
                    break
            
            if effect:
                print("\nEffect state:")
                print(f"State: {effect.state}")
                
                # Show phases
                if hasattr(effect, 'phases'):
                    for state, phase in effect.phases.items():
                        if phase:
                            print(f"{state.value} phase: {phase.duration} turns, {phase.turns_completed} completed")
            else:
                print("\nNo effect found! (This is unexpected)")
            
            # Save character
            await bot.db.save_character(source)
            
            print("\nBasic move test complete")
        else:
            print("No suitable test move found")
        
    except Exception as e:
        print(f"Error in basic move test: {e}")

async def test_move_initiative(interaction: discord.Interaction, bot):
    """Test move behavior in initiative"""
    try:
        print("\n=== TEST: INITIATIVE MOVES ===\n")
        
        # Reset character state
        await reset_character_state(bot, ["test", "test2"])
        
        # Set up initiative
        success = await setup_initiative(bot, interaction, ["test", "test2"])
        if not success:
            print("Failed to set up initiative")
            return
        
        # Get test characters
        source = bot.game_state.get_character("test")
        target = bot.game_state.get_character("test2")
        
        if not source or not target:
            print("Test characters not found")
            return
        
        # Test applying a move with phases
        available_moves = source.list_moves()
        
        # Find a move with all phases for testing
        test_move = None
        for name in available_moves:
            move = source.get_move(name)
            if move and move.cast_time and move.duration and move.cooldown:
                test_move = move
                break
        
        # If no full phase move found, try to find one with at least cast time
        if not test_move:
            for name in available_moves:
                move = source.get_move(name)
                if move and move.cast_time:
                    test_move = move
                    break
        
        # If still no move found, use first available
        if not test_move and available_moves:
            test_move = source.get_move(available_moves[0])
        
        if test_move:
            print(f"\nTesting move in initiative: {test_move.name}")
            
            # Create MoveEffect
            move_effect = MoveEffect(
                name=test_move.name,
                description=test_move.description,
                mp_cost=test_move.mp_cost,
                hp_cost=test_move.hp_cost,
                star_cost=test_move.star_cost,
                cast_time=test_move.cast_time,
                duration=test_move.duration,
                cooldown=test_move.cooldown,
                attack_roll=test_move.attack_roll,
                damage=test_move.damage,
                targets=[target] if test_move.attack_roll else []
            )
            
            # Apply effect
            print("\nApplying move effect...")
            result = await move_effect.on_apply(source, bot.initiative_tracker.round_number)
            print(f"Apply result: {result}")
            
            # Manually use action stars
            source.action_stars.use_stars(test_move.star_cost, test_move.name)
            
            # Save character
            await bot.db.save_character(source)
            
            # Process turns to see the effect through all phases
            turns_needed = 0
            if test_move.cast_time:
                turns_needed += test_move.cast_time
            if test_move.duration:
                turns_needed += test_move.duration
            if test_move.cooldown:
                turns_needed += test_move.cooldown
            
            # Add an extra turn to see completion
            turns_needed += 1
            
            print(f"\nProcessing {turns_needed} turns to observe all phases...")
            await process_turns(bot, interaction, ["test", "test2"], turns_needed)
            
            # Get updated character
            source = bot.game_state.get_character("test")
            
            # Check if effect is still present (should be gone)
            has_effect = any(e.name == test_move.name for e in source.effects)
            print(f"\nEffect still present: {has_effect} (expected: False)")
            
            # Check if move is on cooldown in action stars
            in_cooldown = test_move.name in source.action_stars.used_moves
            print(f"Move in cooldown: {in_cooldown} (expected: False after full cycle)")
        else:
            print("No suitable test move found")
        
        # End combat
        bot.initiative_tracker.end_combat()
        
    except Exception as e:
        print(f"Error in initiative move test: {e}")
        # Make sure combat ends
        try:
            bot.initiative_tracker.end_combat()
        except:
            pass

async def test_move_cooldowns(interaction: discord.Interaction, bot):
    """Test move cooldown behavior"""
    try:
        print("\n=== TEST: MOVE COOLDOWNS ===\n")
        
        # Reset character state
        await reset_character_state(bot, ["test", "test2"])
        
        # Set up initiative
        success = await setup_initiative(bot, interaction, ["test", "test2"])
        if not success:
            print("Failed to set up initiative")
            return
        
        # Get test character
        source = bot.game_state.get_character("test")
        if not source:
            print("Test character not found")
            return
        
        # Find a move with cooldown
        cooldown_move = None
        for name in source.list_moves():
            move = source.get_move(name)
            if move and move.cooldown:
                cooldown_move = move
                break
        
        if not cooldown_move:
            print("No move with cooldown found for testing")
            return
        
        print(f"\nTesting cooldown for move: {cooldown_move.name}")
        print(f"Cooldown duration: {cooldown_move.cooldown} turns")
        
        # Create MoveEffect
        move_effect = MoveEffect(
            name=cooldown_move.name,
            description=cooldown_move.description,
            mp_cost=cooldown_move.mp_cost,
            hp_cost=cooldown_move.hp_cost,
            star_cost=cooldown_move.star_cost,
            cast_time=cooldown_move.cast_time,
            duration=cooldown_move.duration,
            cooldown=cooldown_move.cooldown,
            attack_roll=cooldown_move.attack_roll,
            damage=cooldown_move.damage
        )
        
        # Apply effect
        print("\nApplying move effect first time...")
        result = await move_effect.on_apply(source, bot.initiative_tracker.round_number)
        print(f"Apply result: {result}")
        
        # Mark move as used in moveset data
        cooldown_move.use(bot.initiative_tracker.round_number)
        
        # Use action stars
        source.action_stars.use_stars(cooldown_move.star_cost, cooldown_move.name)
        
        # Save character
        await bot.db.save_character(source)
        
        # Process turns until cooldown phase is reached
        active_phase_turns = 0
        if cooldown_move.cast_time:
            active_phase_turns += cooldown_move.cast_time
        if cooldown_move.duration:
            active_phase_turns += cooldown_move.duration
        
        if active_phase_turns > 0:
            print(f"\nProcessing {active_phase_turns} turns to get to cooldown phase...")
            await process_turns(bot, interaction, ["test", "test2"], active_phase_turns)
        
        # Get updated character
        source = bot.game_state.get_character("test")
        
        # Check if move is in cooldown phase
        effect = next((e for e in source.effects if e.name == cooldown_move.name), None)
        if effect:
            print("\nMove effect status after active phases:")
            print(f"State: {effect.state} (expected: COOLDOWN)")
            
            # Verify cooldown phase details
            if hasattr(effect, 'phases'):
                cooldown_phase = effect.phases.get(MoveState.COOLDOWN)
                if cooldown_phase:
                    print(f"Cooldown phase: {cooldown_phase.duration} turns, {cooldown_phase.turns_completed} completed")
                    remaining = cooldown_phase.duration - cooldown_phase.turns_completed
                    print(f"Remaining: {remaining} turns")
                else:
                    print("Cooldown phase not found (unexpected)")
        else:
            print("Move effect not found (unexpected)")
        
        # Process remaining cooldown turns
        print(f"\nProcessing {cooldown_move.cooldown} more turns to complete cooldown...")
        await process_turns(bot, interaction, ["test", "test2"], cooldown_move.cooldown)
        
        # Get updated character
        source = bot.game_state.get_character("test")
        
        # Check final state - should be able to use move again
        has_effect = any(e.name == cooldown_move.name for e in source.effects)
        print(f"\nEffect still present: {has_effect} (expected: False after cooldown)")
        
        # End combat
        bot.initiative_tracker.end_combat()
        print("\nCooldown test complete")
        
    except Exception as e:
        print(f"Error in cooldown test: {e}")
        # Make sure combat ends
        try:
            bot.initiative_tracker.end_combat()
        except:
            pass

async def test_move_targeting(interaction: discord.Interaction, bot):
    """Test move targeting and attack rolls"""
    try:
        print("\n=== TEST: MOVE TARGETING ===\n")
        
        # Reset character state
        await reset_character_state(bot, ["test", "test2", "test3"])
        
        # Set up initiative
        success = await setup_initiative(bot, interaction, ["test", "test2", "test3"])
        if not success:
            print("Failed to set up initiative")
            return
        
        # Get characters
        source = bot.game_state.get_character("test")
        target1 = bot.game_state.get_character("test2")
        target2 = bot.game_state.get_character("test3")
        
        if not source or not target1 or not target2:
            print("Test characters not found")
            return
        
        # Find an attack move
        attack_move = None
        for name in source.list_moves():
            move = source.get_move(name)
            if move and move.attack_roll and move.damage:
                attack_move = move
                break
        
        if not attack_move:
            print("No attack move found for testing")
            return
        
        print(f"\nTesting targeting with move: {attack_move.name}")
        print(f"Attack roll: {attack_move.attack_roll}")
        print(f"Damage: {attack_move.damage}")
        
        # Test 1: Single target
        print("\n--- TEST 1: SINGLE TARGET ---")
        print(f"Target: {target1.name} (AC: {target1.defense.current_ac})")
        
        single_effect = MoveEffect(
            name=attack_move.name,
            description=attack_move.description,
            mp_cost=attack_move.mp_cost,
            star_cost=attack_move.star_cost,
            attack_roll=attack_move.attack_roll,
            damage=attack_move.damage,
            targets=[target1],  # Single target
            roll_timing="instant"  # Force instant roll for testing
        )
        
        # Apply effect
        print("\nApplying single target effect...")
        result = await single_effect.on_apply(source, bot.initiative_tracker.round_number)
        print(f"Apply result: {result}")
        
        # Save character
        await bot.db.save_character(source)
        
        # Process 1 turn to see attack resolution
        print("\nProcessing 1 turn to see attack resolution...")
        await process_turns(bot, interaction, ["test", "test2", "test3"], 1)
        
        # Reset character state for next test
        await reset_character_state(bot, ["test", "test2", "test3"])
        
        # Test 2: Multi-target
        print("\n--- TEST 2: MULTI-TARGET (SINGLE ROLL) ---")
        print(f"Targets: {target1.name}, {target2.name}")
        
        multi_effect = MoveEffect(
            name=attack_move.name,
            description=attack_move.description,
            mp_cost=attack_move.mp_cost,
            star_cost=attack_move.star_cost,
            attack_roll=attack_move.attack_roll,
            damage=attack_move.damage,
            targets=[target1, target2],  # Multiple targets
            roll_timing="instant"  # Force instant roll
        )
        
        # Set AoE mode to 'single' (one roll for all targets)
        multi_effect.combat_processor.aoe_mode = 'single'
        
        # Apply effect
        print("\nApplying multi-target effect (Single Roll Mode)...")
        result = await multi_effect.on_apply(source, bot.initiative_tracker.round_number)
        print(f"Apply result: {result}")
        
        # Save character
        await bot.db.save_character(source)
        
        # Process 1 turn to see attack resolution
        print("\nProcessing 1 turn to see attack resolution for multiple targets (Single Roll)...")
        await process_turns(bot, interaction, ["test", "test2", "test3"], 1)
        
        # Reset character state for next test
        await reset_character_state(bot, ["test", "test2", "test3"])
        
        # Test 3: Multi-target with separate rolls
        print("\n--- TEST 3: MULTI-TARGET (MULTI ROLL) ---")
        print(f"Targets: {target1.name}, {target2.name}")
        
        multiroll_effect = MoveEffect(
            name=attack_move.name,
            description=attack_move.description,
            mp_cost=attack_move.mp_cost,
            star_cost=attack_move.star_cost,
            attack_roll=attack_move.attack_roll,
            damage=attack_move.damage,
            targets=[target1, target2],  # Multiple targets
            roll_timing="instant"  # Force instant roll
        )
        
        # Set AoE mode to 'multi' (separate roll for each target)
        multiroll_effect.combat_processor.aoe_mode = 'multi'
        
        # Apply effect
        print("\nApplying multi-target effect (Multi Roll Mode)...")
        result = await multiroll_effect.on_apply(source, bot.initiative_tracker.round_number)
        print(f"Apply result: {result}")
        
        # Save character
        await bot.db.save_character(source)
        
        # Process 1 turn to see attack resolution
        print("\nProcessing 1 turn to see attack resolution for multiple targets (Multi Roll)...")
        await process_turns(bot, interaction, ["test", "test2", "test3"], 1)
        
        # End combat
        bot.initiative_tracker.end_combat()
        print("\nTargeting test complete")
        
    except Exception as e:
        print(f"Error in targeting test: {e}")
        # Make sure combat ends
        try:
            bot.initiative_tracker.end_combat()
        except:
            pass

async def test_move_ui(interaction: discord.Interaction, bot):
    """Test move UI components"""
    try:
        print("\n=== TEST: MOVE UI ===\n")
        
        # Reset character state
        await reset_character_state(bot, ["test"])
        
        # Get test character
        char = bot.game_state.get_character("test")
        if not char:
            print("Test character not found")
            return
        
        # Test action handler
        print("\nTesting action handler...")
        
        # Import action handler
        from modules.menu.action_handler import ActionHandler
        
        # Create action handler
        action_handler = ActionHandler(bot)
        
        # Test creating move embed
        print("\nTesting move embed creation...")
        embed = action_handler.create_moves_embed(char)
        if embed:
            print("✓ Move embed created successfully")
            print(f"  Title: {embed.title}")
            print(f"  Fields: {len(embed.fields)}")
        else:
            print("✗ Failed to create move embed")
        
        # Test move info embed
        print("\nTesting move info embed...")
        move_names = char.list_moves()
        if move_names:
            test_move = char.get_move(move_names[0])
            info_embed = action_handler.create_move_info_embed(char, test_move)
            if info_embed:
                print(f"✓ Move info embed created for {test_move.name}")
                print(f"  Title: {info_embed.title}")
                print(f"  Fields: {len(info_embed.fields)}")
            else:
                print(f"✗ Failed to create move info embed for {test_move.name}")
        else:
            print("No moves found for info embed testing")
        
        print("\nUI test complete")
        
    except Exception as e:
        print(f"Error in UI test: {e}")

async def create_debug_moveset(interaction: discord.Interaction, bot):
    """Create a debug moveset with various move types for testing"""
    try:
        await interaction.response.defer()
        
        print("\n=== CREATING DEBUG MOVESET ===\n")
        
        # Create a variety of moves for testing
        moves = [
            # Basic instant attack
            MoveData(
                name="Quick Strike",
                description="A basic attack with no phases",
                mp_cost=5,
                star_cost=1,
                attack_roll="1d20+str",
                damage="1d8+str slashing",
                category="Offense",
                roll_timing="instant"  # Important for instant behavior
            ),
            
            # Cast time move
            MoveData(
                name="Fireball",
                description="A powerful fire attack with cast time",
                mp_cost=10,
                star_cost=2,
                cast_time=2,
                attack_roll="1d20+int",
                damage="3d6 fire",
                save_type="dex",
                save_dc="8+prof+int",
                half_on_save=True,
                category="Offense",
                roll_timing="active"  # Default - will roll when active
            ),
            
            # Duration buff
            MoveData(
                name="Defensive Stance",
                description="A defensive buff that lasts 3 turns",
                mp_cost=8,
                star_cost=1,
                duration=3,
                category="Defense"
            ),
            
            # Cooldown move
            MoveData(
                name="Power Strike",
                description="A powerful attack with cooldown",
                mp_cost=5,
                star_cost=1,
                attack_roll="1d20+str",
                damage="2d8+str slashing",
                cooldown=2,
                category="Offense",
                roll_timing="active"
            ),
            
            # Multi-target attack - AoE Single mode
            MoveData(
                name="Cleave",
                description="An attack that hits multiple targets with one roll",
                mp_cost=8,
                star_cost=2,
                attack_roll="1d20+str",
                damage="1d10+str slashing",
                category="Offense",
                advanced_params={
                    "aoe_mode": "single"
                }
            ),
            
            # Multi-target attack - AoE Multi mode
            MoveData(
                name="Multi-Strike",
                description="Attacks multiple targets with separate rolls for each",
                mp_cost=10,
                star_cost=2,
                attack_roll="1d20+dex",
                damage="1d8+dex piercing",
                category="Offense",
                advanced_params={
                    "aoe_mode": "multi"
                }
            ),
            
            # Healing move
            MoveData(
                name="Healing Light",
                description="Restores health to the caster",
                mp_cost=8,
                hp_cost=-10,  # Negative for healing
                star_cost=1,
                category="Defense"
            ),
            
            # Complete move with all phases
            MoveData(
                name="Ultimate Ability",
                description="A powerful ability with all phases",
                mp_cost=15,
                star_cost=3,
                cast_time=2,
                duration=3,
                cooldown=2,
                attack_roll="1d20+int advantage",
                damage="5d6 force",
                category="Offense",
                roll_timing="active"
            ),
            
            # Utility move
            MoveData(
                name="Teleport",
                description="Teleports the character a short distance",
                mp_cost=12,
                star_cost=2,
                cooldown=3,
                category="Utility"
            ),
            
            # Limited uses move
            MoveData(
                name="Last Resort",
                description="A powerful attack with limited uses",
                mp_cost=20,
                star_cost=3,
                attack_roll="1d20+int",
                damage="8d8 radiant",
                uses=1,
                category="Offense",
                roll_timing="instant"
            ),
            
            # Multi-hit attack
            MoveData(
                name="Flurry of Blows",
                description="Multiple rapid strikes against a single target",
                mp_cost=12,
                star_cost=2,
                attack_roll="3d20 multihit dex",
                damage="1d6+dex bludgeoning",
                cooldown=2,
                category="Offense",
                roll_timing="instant"
            ),
            
            # Per-turn DOT move
            MoveData(
                name="Ongoing Attack",
                description="Attacks the target each turn",
                mp_cost=10,
                star_cost=2,
                attack_roll="1d20+str",
                damage="1d8+str slashing",
                duration=3,
                category="Offense",
                roll_timing="per_turn"  # Will roll each turn
            ),
            
            # Per-turn multi-target, single mode
            MoveData(
                name="Storm Cloud",
                description="A cloud that strikes all targets each turn",
                mp_cost=15,
                star_cost=3,
                attack_roll="1d20+int",
                damage="2d6 lightning",
                duration=2,
                category="Offense",
                roll_timing="per_turn",
                advanced_params={
                    "aoe_mode": "single"
                }
            ),
            
            # Per-turn multi-target, multi mode
            MoveData(
                name="Homing Missiles",
                description="Missiles that seek targets each turn",
                mp_cost=12,
                star_cost=2,
                attack_roll="1d20+int",
                damage="2d4 fire",
                duration=2,
                category="Offense",
                roll_timing="per_turn",
                advanced_params={
                    "aoe_mode": "multi"
                }
            ),
            
            # Heat tracking move
            MoveData(
                name="Phoenix Strike",
                description="A fiery attack that builds heat stacks on targets",
                mp_cost=10,
                star_cost=2,
                attack_roll="1d20+dex",
                damage="2d6 fire",
                category="Offense",
                roll_timing="instant",
                advanced_params={
                    "enable_heat_tracking": True,
                    "crit_range": 18
                }
            )
        ]
        
        # Create moveset
        moveset = Moveset()
        for move in moves:
            moveset.add_move(move)
        
        # Save to database
        success = await MoveLoader.save_global_moveset(
            bot.db,
            DEBUG_MOVESET_NAME,
            moveset,
            "Debug moveset for comprehensive testing"
        )
        
        if success:
            print(f"✓ Debug moveset created with {len(moves)} moves")
            await interaction.followup.send(f"✅ Debug moveset created with {len(moves)} moves")
        else:
            print("✗ Failed to create debug moveset")
            await interaction.followup.send("❌ Failed to create debug moveset")
        
    except Exception as e:
        print(f"Error creating debug moveset: {e}")
        await interaction.followup.send(f"Error creating debug moveset: {str(e)}")