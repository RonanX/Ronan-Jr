"""
Debug commands for testing specific bot systems.

These commands help test and validate specific system behaviors.
Group structure:
/debug effects - Test effect system
/debug initiative - Test initiative system
/debug combat - Test combat system
"""

# General imports
import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio
from typing import Optional, List, Tuple

# Core imports
from core.effects.status import SkipEffect, FrostbiteEffect, ACEffect
from core.effects.manager import process_effects
from modules.combat.initiative import CombatState
from core.effects.move import MoveEffect, MoveState

# Move imports
from modules.moves.data import Moveset, MoveData
from modules.moves.loader import MoveLoader

# Util imports
from utils.error_handler import handle_error
from utils.test_helper import process_turns
from utils.test_helper import recreate_test_characters, run_move_effect_tests

logger = logging.getLogger(__name__)

class DebugCommands(commands.GroupCog, name="debug"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="reset")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_test_chars(self, interaction: discord.Interaction):
        """Recreate test characters with clean state"""
        try:
            await interaction.response.defer()
            
            # Disable database verbosity during test
            was_debug_enabled = getattr(self.bot.db, 'debug_mode', False)
            self.bot.db.debug_mode = False
            
            chars = await recreate_test_characters(self.bot)
            
            # Restore debug mode
            self.bot.db.debug_mode = was_debug_enabled
            
            if chars:
                await interaction.followup.send(
                    f"✨ Recreated test characters: {', '.join(chars)}"
                )
            else:
                await interaction.followup.send(
                    "❌ Error recreating test characters"
                )
                
        except Exception as e:
            logger.error(f"Error in reset command: {e}")
            await interaction.followup.send(f"Error in debug command: {str(e)}")

    @app_commands.command(name="move")
    @app_commands.checks.has_permissions(administrator=True)
    async def debug_move(self, interaction: discord.Interaction):
        """Test move effect behavior with phases and transitions"""
        try:
            await interaction.response.defer()
            
            print("\n=== Starting Move Effect Debug ===\n")
            
            # Disable database verbosity temporarily
            was_debug_enabled = getattr(self.bot.db, 'debug_mode', False)
            self.bot.db.debug_mode = False
            
            try:
                # Reset test characters first
                await recreate_test_characters(self.bot)
                
                # Enable quiet mode for initiative tracker to reduce noise
                if hasattr(self.bot, 'initiative_tracker'):
                    self.bot.initiative_tracker.set_quiet_mode(True)
                
                # Run all tests
                await run_move_effect_tests(self.bot, interaction)
                
                # Disable quiet mode
                if hasattr(self.bot, 'initiative_tracker'):
                    self.bot.initiative_tracker.set_quiet_mode(False)
                
                print("\n=== Move Effect Debug Complete ===")
                await interaction.followup.send("Move effect debug complete - check console for results")
            finally:
                # Restore original debug mode setting
                self.bot.db.debug_mode = was_debug_enabled
                
        except Exception as e:
            print(f"Error in move debug: {e}")
            # Make sure to disable quiet mode even on error
            if hasattr(self.bot, 'initiative_tracker'):
                self.bot.initiative_tracker.set_quiet_mode(False)
            await interaction.followup.send(f"Error in debug command: {str(e)}")

    @app_commands.command(name="ac")
    @app_commands.checks.has_permissions(administrator=True)
    async def debug_ac_command(self, interaction: discord.Interaction):
        """Test AC effect behavior"""
        try:
            await interaction.response.defer()
            await self._debug_ac_logic(interaction)
        except Exception as e:
            print(f"Error in AC debug: {e}")
            await interaction.followup.send(f"Error in debug command: {str(e)}")
            
    # Separate logic function that can be called internally
    async def _debug_ac_logic(self, interaction: discord.Interaction):
        """AC effect testing logic"""
        # Disable database verbosity
        was_debug_enabled = getattr(self.bot.db, 'debug_mode', False)
        self.bot.db.debug_mode = False
        
        try:
            # Reset test characters first
            await recreate_test_characters(self.bot)
            
            print("\n=== Starting AC Effect Debug ===\n")
            
            # Get test character
            char = self.bot.game_state.get_character("test")
            if not char:
                await interaction.followup.send("Error: Test character not found")
                return
                
            original_ac = char.defense.current_ac
            print(f"Initial AC: {original_ac}")
            
            # Test 1: Message Formatting
            print("\nTest 1: Message Formatting")
            effect = ACEffect(amount=-2, duration=2)
            
            print("\nChecking apply message format:")
            msg = effect.format_effect_message(
                f"{char.name}'s AC reduced by 2",
                ["Duration: 2 turns", f"Current AC: {char.defense.current_ac}"]
            )
            print(f"Formatted message: {msg}")
            print("Expected format: '[emoji] `message` [emoji]\\n• `detail1`\\n• `detail2`")
            
            print("\nChecking for backtick issues:")
            # Test with pre-backticked message
            msg2 = effect.format_effect_message(
                f"`{char.name}'s AC reduced by 2`",
                ["`Duration: 2 turns`"]
            )
            print(f"With existing backticks: {msg2}")
            print("Should not have double backticks")
            
            # Test 2: Effect Processing
            print("\nTest 2: Effect Processing Phases")
            msg = char.add_effect(effect, 1)
            print(f"Effect applied: {msg}")
            print(f"New AC: {char.defense.current_ac}")
            
            # Process turns
            for i in range(3):  # Test full duration + 1
                print(f"\nProcessing turn {i+1}:")
                
                # Process effects
                was_skipped, start_msgs, end_msgs = process_effects(
                    char,
                    i+1,  # round number
                    char.name,
                    None  # no combat logger
                )
                
                print("Start Messages:")
                for msg in start_msgs:
                    print(f"  {msg}")
                
                print("\nEnd Messages:")
                for msg in end_msgs:
                    print(f"  {msg}")
                
                print(f"\nAfter turn {i+1}:")
                print(f"  AC: {char.defense.current_ac}")
                print(f"  Active effects: {[e.name for e in char.effects]}")
                
                await asyncio.sleep(1)
            
            # Test 3: Cleanup Verification
            print("\nTest 3: Effect Cleanup")
            print(f"Final AC: {char.defense.current_ac}")
            print(f"Expected AC: {original_ac}")
            print(f"Remaining effects: {[e.name for e in char.effects]}")
            
            # Clean up
            print("\nResetting character state...")
            char.effects = []
            char.defense.current_ac = original_ac
            await self.bot.db.save_character(char)
            
            print("\n=== AC Effect Debug Complete ===")
            await interaction.followup.send("AC effect debug complete - check console for results")
        finally:
            # Restore original debug mode setting
            self.bot.db.debug_mode = was_debug_enabled

    @app_commands.command(name="skip")
    @app_commands.checks.has_permissions(administrator=True)
    async def debug_skip_command(self, interaction: discord.Interaction):
        """Test skip effect and turn handling"""
        try:
            await interaction.response.defer()
            await self._debug_skip_logic(interaction)
        except Exception as e:
            print(f"Error in skip debug: {e}")
            await interaction.followup.send(f"Error in debug command: {str(e)}")
    
    # Separate logic function that can be called internally        
    async def _debug_skip_logic(self, interaction: discord.Interaction):
        """Skip effect testing logic"""
        # Disable database verbosity
        was_debug_enabled = getattr(self.bot.db, 'debug_mode', False)
        self.bot.db.debug_mode = False
        
        try:
            # Reset test characters first
            await recreate_test_characters(self.bot)
            
            print("\n=== Starting Skip Effect Debug ===\n")
            
            # Get test character
            char = self.bot.game_state.get_character("test")
            if not char:
                await interaction.followup.send("Error: Test character not found")
                return
                
            print("Test 1: Basic Skip Effect")
            effect = SkipEffect(duration=1, reason="Debug Test")
            
            print("\nApplying skip effect...")
            msg = char.add_effect(effect, 1)
            print(f"Apply message: {msg}")
            print(f"Effect added: {effect in char.effects}")
            
            print("\nProcessing effects...")
            was_skipped, start_msgs, end_msgs = process_effects(
                char,
                1,  # round number
                char.name,
                None  # no combat logger
            )
            
            print(f"\nResults:")
            print(f"Was skipped: {was_skipped}")
            print("Start messages:")
            for msg in start_msgs:
                print(f"  {msg}")
            print("End messages:")
            for msg in end_msgs:
                print(f"  {msg}")
                
            print("\nTest 2: Skip Effect Cleanup")
            print(f"Remaining effects: {[e.name for e in char.effects]}")
            print(f"Duration remaining: {effect.duration if hasattr(effect, 'duration') else None}")
            
            # Clean up
            char.effects = []
            await self.bot.db.save_character(char)
            
            print("\n=== Skip Effect Debug Complete ===")
            await interaction.followup.send("Skip effect debug complete - check console for results")
        finally:
            # Restore original debug mode setting
            self.bot.db.debug_mode = was_debug_enabled

    @app_commands.command(name="frostbite")
    @app_commands.checks.has_permissions(administrator=True)
    async def debug_frostbite_command(self, interaction: discord.Interaction):
        """Test frostbite effect and stacking"""
        try:
            await interaction.response.defer()
            await self._debug_frostbite_logic(interaction)
        except Exception as e:
            print(f"Error in frostbite debug: {e}")
            await interaction.followup.send(f"Error in debug command: {str(e)}")
            
    # Separate logic function that can be called internally
    async def _debug_frostbite_logic(self, interaction: discord.Interaction):
        """Frostbite effect testing logic"""
        # Disable database verbosity
        was_debug_enabled = getattr(self.bot.db, 'debug_mode', False)
        self.bot.db.debug_mode = False
        
        try:
            # Reset test characters first
            await recreate_test_characters(self.bot)
            
            print("\n=== Starting Frostbite Debug ===\n")
            
            # Get test character
            char = self.bot.game_state.get_character("test")
            if not char:
                await interaction.followup.send("Error: Test character not found")
                return
                
            print("Initial state:")
            print(f"AC: {char.defense.current_ac}")
            print(f"Active effects: {[e.name for e in char.effects]}")
            
            print("\nTest 1: Frostbite Stacking")
            
            # Add stacks one at a time
            for i in range(1, 4):  # Max 3 stacks
                print(f"\nAdding stack {i}...")
                effect = FrostbiteEffect(stacks=1, duration=3)  # Set 3 turns to test decrementing
                msg = char.add_effect(effect, 1)
                print(f"Apply message: {msg}")
                print(f"Current AC: {char.defense.current_ac}")
                print(f"Active effects: {[e.name for e in char.effects]}")
                
                # Process effects
                was_skipped, start_msgs, end_msgs = process_effects(
                    char,
                    1,  # round number
                    char.name,
                    None  # no combat logger
                )
                
                print(f"Was skipped: {was_skipped}")
                print("Effect messages:")
                for msg in start_msgs + end_msgs:
                    print(f"  {msg}")
                    
            print("\nTest 2: Frostbite Decrementing")
            
            # Process multiple turns to see stack decrementation
            for turn in range(1, 6):  # 5 additional turns
                print(f"\nProcessing turn {turn}...")
                # Process effects at different "rounds"
                was_skipped, start_msgs, end_msgs = process_effects(
                    char,
                    turn + 1,  # round number (advancing)
                    char.name,
                    None  # no combat logger
                )
                
                # Show state after processing
                print(f"After turn {turn}:")
                print(f"  Frostbite stacks: {getattr(effect, 'stacks', 0)}")
                print(f"  AC: {char.defense.current_ac}")
                print(f"  Skip triggered: {was_skipped}")
                print(f"  Active effects: {[e.name for e in char.effects]}")
                print(f"  Effect messages: {len(start_msgs + end_msgs)}")
                
                for msg in start_msgs + end_msgs:
                    print(f"    {msg}")
                
                await asyncio.sleep(0.5)  # brief pause for readability
            
            # Clean up
            char.effects = []
            char.defense.current_ac = char.defense.base_ac
            await self.bot.db.save_character(char)
            
            print("\n=== Frostbite Debug Complete ===")
            await interaction.followup.send("Frostbite debug complete - check console for results")
        finally:
            # Restore original debug mode setting
            self.bot.db.debug_mode = was_debug_enabled

    @app_commands.command(name="damage")
    @app_commands.checks.has_permissions(administrator=True)
    async def debug_damage_command(self, interaction: discord.Interaction):
        """Test damage calculation system"""
        try:
            await interaction.response.defer()
            await self._debug_damage_logic(interaction)
        except Exception as e:
            print(f"Error in damage debug: {e}")
            await interaction.followup.send(f"Error in debug command: {str(e)}")
            
    # Separate logic function that can be called internally
    async def _debug_damage_logic(self, interaction: discord.Interaction):
        """Damage calculation testing logic"""
        # Disable database verbosity
        was_debug_enabled = getattr(self.bot.db, 'debug_mode', False)
        self.bot.db.debug_mode = False
        
        try:
            # Reset test characters first
            await recreate_test_characters(self.bot)
            
            print("\n=== Starting Damage System Debug ===\n")
            
            # Get test characters
            source = self.bot.game_state.get_character("test")
            target = self.bot.game_state.get_character("test2")
            
            if not source or not target:
                await interaction.followup.send("Error: Test characters not found")
                return
            
            # Import attack calculator
            from utils.advanced_dice.attack_calculator import AttackCalculator, AttackParameters
            
            # Define test scenarios
            tests = [
                {
                    "name": "Basic Attack",
                    "roll": "1d20+int",
                    "damage": "2d6 slashing",
                    "crit_range": 20
                },
                {
                    "name": "Critical Hit",
                    "roll": "1d20+5",  # Force high roll
                    "damage": "3d8 fire",
                    "crit_range": 15  # Lower crit threshold
                },
                {
                    "name": "Multiple Damage Types",
                    "roll": "1d20+2",
                    "damage": "1d6 fire, 1d4 cold",
                    "crit_range": 20
                },
                {
                    "name": "Multihit Attack",
                    "roll": "3d20 multihit",
                    "damage": "1d6 piercing",
                    "crit_range": 20
                }
            ]
            
            # Run tests
            for i, test in enumerate(tests):
                print(f"\n--- Test {i+1}: {test['name']} ---")
                
                params = AttackParameters(
                    roll_expression=test["roll"],
                    character=source,
                    targets=[target],
                    damage_str=test["damage"],
                    crit_range=test["crit_range"],
                    reason=test["name"]
                )
                
                message, embed = AttackCalculator.process_attack(params)
                print("\nResult:")
                print(message)
                
                if embed:
                    print("\nEmbed Fields:")
                    for field in embed.fields:
                        print(f"  {field.name}: {field.value}")
                
                # Brief pause
                await asyncio.sleep(0.5)
            
            print("\n=== Damage System Debug Complete ===")
            await interaction.followup.send("Damage system debug complete - check console for results")
        finally:
            # Restore original debug mode setting
            self.bot.db.debug_mode = was_debug_enabled

    @app_commands.command(name="test_fixes")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_fixes(self, interaction: discord.Interaction):
        """Test all system fixes together - frostbite, cooldown, etc."""
        try:
            await interaction.response.defer()
            
            # Disable database verbosity
            was_debug_enabled = getattr(self.bot.db, 'debug_mode', False)
            self.bot.db.debug_mode = False
            
            try:
                # Reset test characters first
                await recreate_test_characters(self.bot)
                
                print("\n=== COMPREHENSIVE FIX TESTING ===\n")
                
                # Test frostbite effect first
                print("\n=== 1. TESTING FROSTBITE EFFECT ===\n")
                await self._debug_frostbite_logic(interaction)
                
                # Allow small pause between tests
                await asyncio.sleep(1)
                
                print("\n=== 2. TESTING MOVE COOLDOWNS ===\n")
                
                # Test cooldown message fix
                char = self.bot.game_state.get_character("test")
                
                # Reset character state
                char.effects = []
                char.resources.current_mp = char.resources.max_mp
                char.resources.current_hp = char.resources.max_hp
                char.action_stars.refresh()
                
                print("Initial state:")
                print(f"Character: {char.name}")
                print(f"MP: {char.resources.current_mp}")
                print(f"HP: {char.resources.current_hp}")
                
                # Create a move with cooldown
                move = MoveEffect(
                    name="Test Cooldown Move",
                    description="Testing cooldown message fix",
                    mp_cost=5, 
                    cooldown=2  # 2 turn cooldown
                )
                
                # Apply the move
                print("\nApplying cooldown move...")
                msg = char.add_effect(move, 1)
                print(f"Apply message: {msg}")
                
                # Check current state
                print("\nChecking move state...")
                move_effect = next((e for e in char.effects if e.name == move.name), None)
                if move_effect:
                    print(f"  State: {move_effect.state}")
                    if move_effect.state == MoveState.COOLDOWN:
                        cooldown_phase = move_effect.phases.get(MoveState.COOLDOWN)
                        if cooldown_phase:
                            print(f"  Cooldown: {cooldown_phase.duration} turns, {cooldown_phase.turns_completed} completed")
                else:
                    print("  Move effect not found!")
                    
                # Save character - NOW WITH DB MONITORING
                await self.bot.db.save_character(char, debug_paths=['effects', 'action_stars'])
                
                # Process turns to see cooldown messages
                print("\nProcessing turns to test cooldown messaging...")
                # Let's see 3 turns - should see messages for 2 turns and none for the 3rd
                from utils.test_helper import process_turns
                await process_turns(self.bot, interaction, ["test", "test2"], 3)
                
                # Verify cooldown ended
                char = self.bot.game_state.get_character("test")
                has_effect = any(e.name == move.name for e in char.effects)
                print(f"\nFinal state - Still has effect: {has_effect} (should be False)")
                
                # Test using it again after cooldown
                if not has_effect:
                    print("\nTesting using move again after cooldown...")
                    move2 = MoveEffect(
                        name="Test Cooldown Move",
                        description="Testing cooldown message fix",
                        mp_cost=5,
                        cooldown=2
                    )
                    msg = char.add_effect(move2, 4)  # Round 4 now
                    print(f"Apply message: {msg}")
                    
                    # Should be no leftover messages from previous cooldown
                    
                print("\n=== 3. TESTING MOVESET DATABASE ===\n")
                
                # Create a moveset for testing
                print("Creating test moveset...")
                
                # Create a few moves for the character
                moves = [
                    MoveData(
                        name="Fireball",
                        description="A powerful fire attack",
                        mp_cost=10,
                        star_cost=2,
                        cooldown=2,
                        attack_roll="1d20+int",
                        damage="3d6 fire"
                    ),
                    MoveData(
                        name="Healing Light",
                        description="Restores health to the caster",
                        mp_cost=5,
                        hp_cost=-10,  # Heals 10 HP
                        star_cost=1,
                        duration=0    # Instant effect
                    ),
                    MoveData(
                        name="Defensive Stance",
                        description="Increases defense temporarily",
                        mp_cost=3,
                        star_cost=1,
                        duration=3    # 3 turn duration
                    )
                ]
                
                # Add moves to character
                for move in moves:
                    char.add_move(move)
                    
                # Save character WITH DATABASE MONITORING
                await self.bot.db.save_character(char, debug_paths=['moveset'])
                
                # List moves before saving
                print(f"\nMoves for {char.name}:")
                for move_name in char.list_moves():
                    print(f"  • {move_name}")
                    
                # Save moveset to global collection
                moveset_name = "test_moveset"
                print(f"\nSaving moveset as '{moveset_name}'...")
                
                success = await MoveLoader.save_global_moveset(
                    self.bot.db,
                    moveset_name,
                    char.moveset,
                    "Test moveset for debugging"
                )
                
                print(f"Save result: {'Success' if success else 'Failed'}")
                
                # List global movesets
                print("\nListing global movesets:")
                movesets = await self.bot.db.list_movesets()
                
                if movesets:
                    for moveset in movesets:
                        print(f"  • {moveset.get('name')}: {moveset.get('move_count')} moves")
                else:
                    print("  No movesets found!")
                    
                # Load moveset to another character
                target_char = self.bot.game_state.get_character("test2")
                
                if target_char:
                    print(f"\nLoading moveset to {target_char.name}...")
                    
                    # Clear any existing moves
                    target_char.moveset.clear()
                    
                    # Load moveset from global collection
                    loaded_moves = await MoveLoader.load_global_moveset(self.bot.db, moveset_name)
                    
                    if loaded_moves:
                        # Create moveset with loaded data
                        target_char.moveset = Moveset.from_dict(loaded_moves.to_dict())
                        
                        # Save character with updated moveset
                        await self.bot.db.save_character(target_char, debug_paths=['moveset'])
                        
                        # List loaded moves
                        print(f"Loaded moves for {target_char.name}:")
                        for move_name in target_char.list_moves():
                            print(f"  • {move_name}")
                    else:
                        print("Failed to load moveset!")
                
                print("\n=== COMPREHENSIVE TEST COMPLETE ===")
                await interaction.followup.send("All fixes tested - check console for results")
            finally:
                # Restore original debug mode setting
                self.bot.db.debug_mode = was_debug_enabled
            
        except Exception as e:
            print(f"Error in fix testing: {e}")
            await interaction.followup.send(f"Error in test command: {str(e)}")

    @app_commands.command(name="movesets")
    @app_commands.checks.has_permissions(administrator=True)
    async def debug_movesets(self, interaction: discord.Interaction):
        """Test all moveset functionality with database monitoring"""
        try:
            await interaction.response.defer()
            
            # Disable database verbosity
            was_debug_enabled = getattr(self.bot.db, 'debug_mode', False)
            self.bot.db.debug_mode = False
            
            try:
                # Reset test characters
                await recreate_test_characters(self.bot)
                
                print("\n=== MOVESET SYSTEM DEBUG ===\n")
                
                # Get test characters
                test_char = self.bot.game_state.get_character("test")
                target_char = self.bot.game_state.get_character("test2")
                
                if not test_char or not target_char:
                    await interaction.followup.send("Error: Test characters not found")
                    return
                    
                # Reset character state
                test_char.effects = []
                test_char.moveset.clear()
                test_char.resources.current_mp = test_char.resources.max_mp
                test_char.resources.current_hp = test_char.resources.max_hp
                test_char.action_stars.refresh()
                
                target_char.effects = []
                target_char.moveset.clear()
                target_char.resources.current_mp = target_char.resources.max_mp
                target_char.resources.current_hp = target_char.resources.max_hp
                target_char.action_stars.refresh()
                
                # Save initial state with monitoring
                print("\n--- Initial Character State ---")
                await self.bot.db.save_character(test_char, debug_paths=['moveset', 'effects', 'resources'])
                
                # Step 1: Create Local Moves
                print("\n=== 1. CREATING LOCAL MOVES ===")
                
                # Create a variety of moves for testing
                test_moves = [
                    {
                        "name": "Basic Attack",
                        "description": "A simple attack",
                        "mp_cost": 0,
                        "star_cost": 1,
                        "attack_roll": "1d20+int",
                        "damage": "1d6+str slashing",
                        "crit_range": 20,
                    },
                    {
                        "name": "Fireball",
                        "description": "A powerful fire attack",
                        "mp_cost": 10,
                        "star_cost": 2, 
                        "attack_roll": "1d20+int",
                        "damage": "3d6 fire",
                        "save_type": "dex",
                        "save_dc": "8+prof+int",
                        "half_on_save": True,
                        "cooldown": 2
                    },
                    {
                        "name": "Healing Light",
                        "description": "Restores health to self",
                        "mp_cost": 5,
                        "hp_cost": -10,  # Negative for healing
                        "star_cost": 1,
                        "duration": 0    # Instant effect
                    },
                    {
                        "name": "Ultimate Power",
                        "description": "A powerful attack with cast time",
                        "mp_cost": 20,
                        "star_cost": 3,
                        "cast_time": 1,
                        "duration": 2,
                        "cooldown": 3,
                        "attack_roll": "1d20+int advantage",
                        "damage": "5d8 force",
                        "track_heat": True,
                        "uses": 3
                    }
                ]
                
                # Create each move
                for move_data in test_moves:
                    print(f"\nCreating move: {move_data['name']}")
                    move = MoveData(
                        name=move_data["name"],
                        description=move_data["description"],
                        mp_cost=move_data.get("mp_cost", 0),
                        hp_cost=move_data.get("hp_cost", 0),
                        star_cost=move_data.get("star_cost", 1),
                        attack_roll=move_data.get("attack_roll"),
                        damage=move_data.get("damage"),
                        crit_range=move_data.get("crit_range", 20),
                        save_type=move_data.get("save_type"),
                        save_dc=move_data.get("save_dc"),
                        half_on_save=move_data.get("half_on_save", False),
                        cast_time=move_data.get("cast_time"),
                        duration=move_data.get("duration"),
                        cooldown=move_data.get("cooldown"),
                        uses=move_data.get("uses"),
                        enable_heat_tracking=move_data.get("track_heat", False)
                    )
                    
                    # Add to character's moveset
                    test_char.add_move(move)
                    
                # Save character with monitoring
                print("\n--- Character After Move Creation ---")
                await self.bot.db.save_character(test_char, debug_paths=['moveset'])
                
                # Step 2: List Moves
                print("\n=== 2. LISTING MOVES ===")
                move_names = test_char.list_moves()
                print(f"Found {len(move_names)} moves:")
                for name in move_names:
                    move = test_char.get_move(name)
                    print(f"  • {name}: {move.description}")
                    if move.mp_cost or move.star_cost:
                        print(f"    - Costs: MP {move.mp_cost}, Stars {move.star_cost}")
                    if move.cooldown:
                        print(f"    - Cooldown: {move.cooldown} turns")
                    if move.uses:
                        print(f"    - Uses: {move.uses}/{move.uses_remaining} remaining")
                
                # Step 3: Test Move Info
                print("\n=== 3. TESTING MOVE INFO ===")
                test_move = "Fireball"
                print(f"Getting info for: {test_move}")
                move_data = test_char.get_move(test_move)
                if move_data:
                    print(f"Move: {move_data.name}")
                    print(f"Description: {move_data.description}")
                    print(f"MP Cost: {move_data.mp_cost}")
                    print(f"Star Cost: {move_data.star_cost}")
                    if move_data.attack_roll:
                        print(f"Attack: {move_data.attack_roll}")
                    if move_data.damage:
                        print(f"Damage: {move_data.damage}")
                    if move_data.save_type:
                        print(f"Save: {move_data.save_type} (DC: {move_data.save_dc})")
                        print(f"Half on Save: {move_data.half_on_save}")
                    if move_data.cooldown:
                        print(f"Cooldown: {move_data.cooldown} turns")
                else:
                    print(f"Move '{test_move}' not found!")
                
                # Step 4: Test Move Use in Initiative
                print("\n=== 4. TESTING MOVE USE IN INITIATIVE ===")
                
                # Start initiative
                print("\nStarting test combat...")
                
                # Initialize initiative tracker
                tracker = self.bot.initiative_tracker
                
                # Clear any existing combat
                # Check if combat is active using the state attribute instead of combat_active
                if hasattr(tracker, 'state') and tracker.state != CombatState.INACTIVE:
                    tracker.end_combat()
                    
                # Set up a simple 2-character battle
                char_names = [test_char.name, target_char.name]
                
                # Log the battle setup, don't use the interaction directly
                success, message = await tracker.set_battle(
                    char_names,
                    interaction,
                    round_number=1,
                    current_turn=0
                )
                
                if not success:
                    print(f"Failed to set up combat: {message}")
                    return
                
                # Set the combat state to ACTIVE since we can't respond to interaction again
                tracker.state = CombatState.ACTIVE
                print("\n--- Combat Started ---")
                
                # Disable logger channel sending if it exists
                if hasattr(tracker, 'logger') and hasattr(tracker.logger, 'channel_id'):
                    tracker.logger.channel_id = None
                
                # Test using a move (Fireball)
                print("\nTesting move use...")
                
                # Find the move we want to use
                move_name = "Fireball"
                move_data = test_char.get_move(move_name)
                
                if not move_data:
                    print(f"Move '{move_name}' not found!")
                    return
                    
                # Create a move effect from the move data
                move_effect = MoveEffect(
                    name=move_data.name,
                    description=move_data.description,
                    mp_cost=move_data.mp_cost,
                    star_cost=move_data.star_cost,
                    attack_roll=move_data.attack_roll,
                    damage=move_data.damage,
                    save_type=move_data.save_type,
                    save_dc=move_data.save_dc,
                    half_on_save=move_data.half_on_save,
                    cooldown=move_data.cooldown,
                    targets=[target_char]
                )
                
                # Apply the effect
                print(f"\nUsing {move_name} on {target_char.name}...")
                result = test_char.add_effect(move_effect, tracker.round_number)
                print(f"Use result: {result}")
                
                # Mark the move as used
                move_data.use(tracker.round_number)
                
                # Use action stars
                test_char.use_move_stars(move_data.star_cost, move_data.name)
                
                # Save character with monitoring
                print("\n--- Character After Move Use ---")
                await self.bot.db.save_character(test_char, debug_paths=['effects', 'moveset', 'action_stars', 'resources'])
                
                # Process a few combat turns to see effects
                print("\nProcessing combat turns to see effects and cooldowns...")
                await process_turns(self.bot, interaction, [test_char.name, target_char.name], 3)
                
                # Refresh character references
                test_char = self.bot.game_state.get_character("test")
                target_char = self.bot.game_state.get_character("test2")
                
                # Check cooldown status
                print("\nChecking cooldown status after combat...")
                move_data = test_char.get_move(move_name)
                if move_data:
                    if move_data.last_used_round:
                        elapsed = tracker.round_number - move_data.last_used_round
                        remaining = max(0, move_data.cooldown - elapsed) if move_data.cooldown else 0
                        print(f"{move_name} last used in round {move_data.last_used_round}")
                        print(f"Current round: {tracker.round_number}")
                        print(f"Cooldown remaining: {remaining} turns")
                    else:
                        print(f"{move_name} has not been used yet")
                else:
                    print(f"Move '{move_name}' not found after combat!")
                    
                # End combat
                tracker.end_combat()
                print("\n--- Combat Ended ---")
                
                # Step 5: Test Global Movesets
                print("\n=== 5. TESTING GLOBAL MOVESETS ===")
                
                # Save moveset to global collection
                from modules.moves.loader import MoveLoader
                
                global_name = "test_global_moveset"
                print(f"\nSaving global moveset as '{global_name}'...")
                
                success = await MoveLoader.save_global_moveset(
                    self.bot.db,
                    global_name,
                    test_char.moveset,
                    "Test global moveset for debugging"
                )
                
                print(f"Global save result: {'Success' if success else 'Failed'}")
                
                # List global movesets
                print("\nListing global movesets:")
                movesets = await self.bot.db.list_movesets()
                
                if movesets:
                    for moveset in movesets:
                        print(f"  • {moveset.get('name')}: {moveset.get('move_count')} moves")
                else:
                    print("  No global movesets found!")
                    
                # Load global moveset to second character
                print(f"\nLoading global moveset to {target_char.name}...")
                
                # Clear any existing moves
                target_char.moveset.clear()
                
                # Load the global moveset
                loaded_moveset = await MoveLoader.load_global_moveset(self.bot.db, global_name)
                
                if loaded_moveset:
                    # Apply to target character
                    target_char.moveset = loaded_moveset
                    
                    # Save character with monitoring
                    print("\n--- Second Character After Global Moveset Load ---")
                    await self.bot.db.save_character(target_char, debug_paths=['moveset'])
                    
                    # List moves to verify
                    print(f"\nMoves loaded to {target_char.name}:")
                    for move_name in target_char.list_moves():
                        print(f"  • {move_name}")
                else:
                    print(f"Failed to load global moveset '{global_name}'")
                    
                # Step 6: Test Temp Move
                print("\n=== 6. TESTING TEMP MOVE ===")
                
                # Reset character state
                test_char.effects = []
                test_char.resources.current_mp = test_char.resources.max_mp
                test_char.resources.current_hp = test_char.resources.max_hp
                test_char.action_stars.refresh()
                
                # Create a temp move effect
                temp_move = MoveEffect(
                    name="Lightning Strike",
                    description="A one-time lightning attack",
                    mp_cost=8,
                    star_cost=2,
                    attack_roll="1d20+int",
                    damage="4d6 lightning",
                    targets=[target_char]
                )
                
                # Apply the effect
                print(f"\nUsing temp move on {target_char.name}...")
                result = test_char.add_effect(temp_move, 1)
                print(f"Temp move result: {result}")
                
                # Save character with monitoring
                print("\n--- Character After Temp Move ---")
                await self.bot.db.save_character(test_char, debug_paths=['effects', 'resources', 'action_stars'])
                
                # Verify it's not in moveset
                print("\nVerifying temp move is not in moveset:")
                in_moveset = any(m == temp_move.name for m in test_char.list_moves())
                print(f"Temp move in moveset: {in_moveset} (should be False)")
                
                # Check if it's in effects
                print("\nVerifying temp move is in effects:")
                in_effects = any(e.name == temp_move.name for e in test_char.effects)
                print(f"Temp move in effects: {in_effects} (should be True)")
                
                # Step 7: Delete Move
                print("\n=== 7. TESTING MOVE DELETION ===")
                
                # Delete a move
                move_to_delete = "Healing Light"
                print(f"\nDeleting move: {move_to_delete}")
                
                # Check if it exists first
                exists_before = move_to_delete in test_char.list_moves()
                print(f"Move exists before deletion: {exists_before}")
                
                # Delete it
                if exists_before:
                    test_char.remove_move(move_to_delete)
                    
                    # Save character with monitoring
                    print("\n--- Character After Move Deletion ---")
                    await self.bot.db.save_character(test_char, debug_paths=['moveset'])
                    
                    # Verify it's gone
                    exists_after = move_to_delete in test_char.list_moves()
                    print(f"Move exists after deletion: {exists_after} (should be False)")
                else:
                    print(f"Move '{move_to_delete}' not found, can't delete")
                
                # Final summary
                print("\n=== MOVESETS SYSTEM TEST COMPLETE ===")
                print(f"Tested {len(test_moves)} local moves")
                print(f"Tested global moveset '{global_name}'")
                print(f"Tested move use in combat")
                print(f"Tested temp move")
                print(f"Tested move deletion")

                # Print detailed summary of test results
                def print_moveset_test_summary(test_char, global_move_results):
                    """Print a comprehensive summary of moveset test results"""
                    # Add a clear test summary header
                    print("\n" + "="*60)
                    print(f"MOVESET SYSTEM TEST SUMMARY FOR {test_char.name.upper()}")
                    print("="*60)
                    
                    # Analyze move mechanics
                    local_moves = test_char.list_moves()
                    effect_moves = [e for e in test_char.effects if hasattr(e, 'is_move_effect') and e.is_move_effect()]
                    
                    # 1. Local moves analysis
                    print("\n[1] STORED MOVES ANALYSIS:")
                    print(f"  • Total moves in moveset: {len(local_moves)}")
                    mp_cost_total = sum(test_char.get_move(m).mp_cost for m in local_moves)
                    print(f"  • Total MP cost: {mp_cost_total}")
                    
                    # Categorize by type
                    attack_moves = [m for m in local_moves if test_char.get_move(m).attack_roll]
                    utility_moves = [m for m in local_moves if not test_char.get_move(m).attack_roll]
                    cooldown_moves = [m for m in local_moves if test_char.get_move(m).cooldown]
                    
                    print(f"  • Combat moves: {len(attack_moves)}")
                    print(f"  • Utility moves: {len(utility_moves)}")
                    print(f"  • Moves with cooldown: {len(cooldown_moves)}")
                    
                    # 2. Effect analysis
                    print("\n[2] ACTIVE MOVE EFFECTS:")
                    if effect_moves:
                        for effect in effect_moves:
                            state = effect.state.value if hasattr(effect, 'state') else "unknown"
                            targets = effect.targets if hasattr(effect, 'targets') else []
                            target_names = [t.name for t in targets] if targets else ["None"]
                            
                            print(f"  • {effect.name}:")
                            print(f"    - State: {state}")
                            print(f"    - Targets: {', '.join(target_names)}")
                            
                            # Show phase details if applicable
                            if hasattr(effect, 'phases'):
                                for phase_name, phase in effect.phases.items():
                                    if phase:
                                        completed = phase.turns_completed if hasattr(phase, 'turns_completed') else 0
                                        duration = phase.duration if hasattr(phase, 'duration') else 0
                                        print(f"    - {phase_name} phase: {completed}/{duration} turns")
                    else:
                        print("  • No active move effects")
                    
                    # 3. Resources analysis
                    print("\n[3] RESOURCE STATUS:")
                    print(f"  • MP: {test_char.resources.current_mp}/{test_char.resources.max_mp}")
                    print(f"  • Stars: {test_char.action_stars.current_stars}/{test_char.action_stars.max_stars}")
                    
                    # 4. Global system status
                    print("\n[4] GLOBAL MOVESET STATUS:")
                    if hasattr(global_move_results, 'get'):
                        save_result = global_move_results.get('global_save_success', False)
                        name = global_move_results.get('global_name', 'unknown')
                        load_result = global_move_results.get('global_load_success', False)
                        
                        print(f"  • Save: {'✓ Success' if save_result else '✗ Failed'}")
                        print(f"  • Name: {name}")
                        print(f"  • Load: {'✓ Success' if load_result else '✗ Failed'}")
                    else:
                        print("  • No global moveset operations performed")
                    
                    # 5. Database changes
                    print("\n[5] DATABASE UPDATE SUMMARY:")
                    print("  • Updated paths: ['moveset', 'effects', 'action_stars', 'resources']")
                    
                    print("\n" + "="*60)
                    print("END OF MOVESET TEST SUMMARY")
                    print("="*60)

                # Add results tracking
                moveset_test_results = {
                    'global_save_success': success,  # From save_global_moveset result
                    'global_name': global_name,
                    'global_load_success': loaded_moveset is not None
                }

                # Call the summary function
                print_moveset_test_summary(test_char, moveset_test_results)
                
                await interaction.followup.send("Moveset debug complete - check console for results")
            finally:
                # Restore original debug mode setting
                self.bot.db.debug_mode = was_debug_enabled
            
        except Exception as e:
            print(f"Error in moveset debug: {e}")
            await interaction.followup.send(f"Error in debug command: {str(e)}")

async def setup(bot):
    # Initialize the cog
    debug_cog = DebugCommands(bot)
    
    # Add the cog to the bot
    await bot.add_cog(debug_cog)
    
    # Import and add resource debug commands after cog initialization
    try:
        # This function will be imported and called after the cog is fully set up
        # to avoid the type annotation issues
        from commands.debug_extra.debug_resources import add_resource_debug_commands
        add_resource_debug_commands(debug_cog)
        print("Successfully added resource debug commands")
    except Exception as e:
        print(f"Failed to add resource debug commands: {e}")