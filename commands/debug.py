"""
Debug commands for testing specific bot systems.

These commands help test and validate specific system behaviors.
Group structure:
/debug effects - Test effect system
/debug initiative - Test initiative system
/debug combat - Test combat system
/debug movesets - Test moveset system
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
from core.effects.manager import process_effects, apply_effect
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

    @app_commands.command(name="movesets")
    @app_commands.checks.has_permissions(administrator=True)
    async def debug_movesets(self, interaction: discord.Interaction, enable_firebase_logging: bool = False):
        """Test all moveset and move functionality"""
        try:
            await interaction.response.defer()
            
            # Set Firebase logging on database if requested
            if hasattr(self.bot, 'db'):
                self.bot.db.debug_mode = enable_firebase_logging
                if enable_firebase_logging:
                    print("\n📊 Firebase debug logging ENABLED")
                else:
                    print("\n📊 Firebase debug logging DISABLED")
            
            # First step: Recreate test characters
            print("\nRecreating test characters...")
            await recreate_test_characters(self.bot)
            
            # Load debug moveset - pass the bot parameter
            print("\nLoading debug moveset...")
            moveset = await self.load_debug_moveset(self.bot)
            if not moveset:
                await interaction.followup.send(
                    "❌ Debug moveset not found. Please create a moveset called 'debug' in Firebase."
                )
                return
            
            # Apply to test characters - pass the bot parameter
            test_chars = ["test", "test2", "test3", "test4"]
            loaded_chars = await self.apply_moveset_to_characters(self.bot, moveset, test_chars)
            
            if not loaded_chars:
                await interaction.followup.send("❌ Failed to load moveset to any test characters")
                return
            
            # Run comprehensive tests - PASS THE BOT PARAMETER TO ALL TEST FUNCTIONS
            print("\n=== STARTING COMPREHENSIVE MOVE TESTS ===\n")
            
            # Test 1: Basic move usage - checks move creation and application
            await self.test_move_basics(interaction, self.bot)
            
            # Test 2: Initiative with moves - checks how moves behave in combat flow
            await self.test_move_initiative(interaction, self.bot)
            
            # Test 3: Move cooldowns - specifically test cooldown tracking and messages
            await self.test_move_cooldowns(interaction, self.bot)
            
            # Test 4: Move targeting - tests target selection and attack rolls
            await self.test_move_targeting(interaction, self.bot)
            
            # Test 5: Move UI - test UI components like action_handler
            await self.test_move_ui(interaction, self.bot)
            
            # Test 6: Phase durations - test timing and transitions
            await self.test_phase_durations(interaction, self.bot)
            
            print("\n=== COMPREHENSIVE MOVE TESTS COMPLETE ===\n")
            
            # Restore database debug mode
            if hasattr(self.bot, 'db'):
                self.bot.db.debug_mode = False
            
            # Summarize results
            await interaction.followup.send(
                f"✅ Moveset debugging complete - check console for results\n" +
                f"Firebase logging was {'enabled' if enable_firebase_logging else 'disabled'}"
            )
            
        except Exception as e:
            print(f"Error in movesets debug: {e}")
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
            msg = await apply_effect(char, effect, 1)
            print(f"Effect applied: {msg}")
            print(f"New AC: {char.defense.current_ac}")
            
            # Process turns
            for i in range(3):  # Test full duration + 1
                print(f"\nProcessing turn {i+1}:")
                
                # Process effects
                was_skipped, start_msgs, end_msgs = await process_effects(
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
            msg = await apply_effect(char, effect, 1)
            print(f"Apply message: {msg}")
            print(f"Effect added: {effect in char.effects}")
            
            print("\nProcessing effects...")
            was_skipped, start_msgs, end_msgs = await process_effects(
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
                msg = await apply_effect(char, effect, 1)
                print(f"Apply message: {msg}")
                print(f"Current AC: {char.defense.current_ac}")
                print(f"Active effects: {[e.name for e in char.effects]}")
                
                # Process effects
                was_skipped, start_msgs, end_msgs = await process_effects(
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
                was_skipped, start_msgs, end_msgs = await process_effects(
                    char,
                    turn + 1,  # round number (advancing)
                    char.name,
                    None  # no combat logger
                )
                
                # Show state after processing
                print(f"After turn {turn}:")
                fb_effect = next((e for e in char.effects if isinstance(e, FrostbiteEffect)), None)
                if fb_effect:
                    print(f"  Frostbite stacks: {fb_effect.stacks}")
                else:
                    print("  No frostbite effect found!")
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
                
                message, embed = await AttackCalculator.process_attack(params)
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
                msg = await apply_effect(char, move, 1)
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
                    msg = await apply_effect(char, move2, 4)  # Round 4 now
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

    # HELPER METHODS WITH CORRECT PARAMETERS
    
    async def load_debug_moveset(self, bot) -> Optional[Moveset]:
        """Load the debug moveset from Firebase"""
        DEBUG_MOVESET_NAME = "debug"
        
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

    async def apply_moveset_to_characters(self, bot, moveset: Moveset, character_names: List[str]) -> List[str]:
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

    async def setup_initiative(self, interaction, bot, character_names: List[str]) -> bool:
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

    async def reset_character_state(self, bot, character_names: List[str]):
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
            char.refresh_stars()
            
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

    # TEST METHODS WITH CORRECT PARAMETERS

    async def test_move_basics(self, interaction: discord.Interaction, bot):
        """Test basic move usage and functionality"""
        try:
            print("\n=== TEST: BASIC MOVE USAGE ===\n")
            
            # Reset character state
            await self.reset_character_state(bot, ["test", "test2"])
            
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
                result = await apply_effect(source, move_effect, 1)
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

    async def test_move_initiative(self, interaction: discord.Interaction, bot):
        """Test move behavior in initiative"""
        try:
            print("\n=== TEST: INITIATIVE MOVES ===\n")
            
            # Reset character state
            await self.reset_character_state(bot, ["test", "test2"])
            
            # Set up initiative - pass the bot parameter here
            success = await self.setup_initiative(interaction, bot, ["test", "test2"])
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
                result = await apply_effect(source, move_effect, bot.initiative_tracker.round_number)
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

    async def test_move_cooldowns(self, interaction: discord.Interaction, bot):
        """Test move cooldown behavior"""
        try:
            print("\n=== TEST: MOVE COOLDOWNS ===\n")
            
            # Reset character state
            await self.reset_character_state(bot, ["test", "test2"])
            
            # Set up initiative - make sure to pass bot parameter
            success = await self.setup_initiative(interaction, bot, ["test", "test2"])
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
            result = await apply_effect(source, move_effect, bot.initiative_tracker.round_number)
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

    async def test_move_targeting(self, interaction: discord.Interaction, bot):
        """Test move targeting and attack rolls"""
        try:
            print("\n=== TEST: MOVE TARGETING ===\n")
            
            # Reset character state
            await self.reset_character_state(bot, ["test", "test2", "test3"])
            
            # Set up initiative - pass bot parameter
            success = await self.setup_initiative(interaction, bot, ["test", "test2", "test3"])
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
            result = await apply_effect(source, single_effect, bot.initiative_tracker.round_number)
            print(f"Apply result: {result}")
            
            # Save character
            await bot.db.save_character(source)
            
            # Process 1 turn to see attack resolution
            print("\nProcessing 1 turn to see attack resolution...")
            await process_turns(bot, interaction, ["test", "test2", "test3"], 1)
            
            # Reset character state for next test
            await self.reset_character_state(bot, ["test", "test2", "test3"])
            
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
            result = await apply_effect(source, multi_effect, bot.initiative_tracker.round_number)
            print(f"Apply result: {result}")
            
            # Save character
            await bot.db.save_character(source)
            
            # Process 1 turn to see attack resolution
            print("\nProcessing 1 turn to see attack resolution for multiple targets (Single Roll)...")
            await process_turns(bot, interaction, ["test", "test2", "test3"], 1)
            
            # Reset character state for next test
            await self.reset_character_state(bot, ["test", "test2", "test3"])
            
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
            result = await apply_effect(source, multiroll_effect, bot.initiative_tracker.round_number)
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

    async def test_move_ui(self, interaction: discord.Interaction, bot):
        """Test move UI components"""
        try:
            print("\n=== TEST: MOVE UI ===\n")
            
            # Reset character state
            await self.reset_character_state(bot, ["test"])
            
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

    async def test_phase_durations(self, interaction: discord.Interaction, bot):
        """Test phase durations and transitions in detail"""
        try:
            print("\n=== TEST: PHASE DURATIONS AND TRANSITIONS ===\n")
            
            # Reset character state
            await self.reset_character_state(bot, ["test", "test2"])
            
            # Get test character
            source = bot.game_state.get_character("test")
            if not source:
                print("Test character not found")
                return
            
            # Set up initiative for testing - pass bot parameter
            success = await self.setup_initiative(interaction, bot, ["test", "test2"])
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
            result = await apply_effect(source, full_move, 1)  # Round 1
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

    async def create_debug_moveset(self, interaction: discord.Interaction, bot):
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
                "debug",
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
    
    # Import and add moveset debug commands
    try:
        from commands.debug_extra.debug_movesets import add_moveset_debug_commands
        add_moveset_debug_commands(debug_cog)
        print("Successfully added moveset debug commands")
    except Exception as e:
        print(f"Failed to add moveset debug commands: {e}")