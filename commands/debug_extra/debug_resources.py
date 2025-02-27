"""Resource debugging extensions for the main debug command group."""

import asyncio
import random
import logging
from typing import Optional, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from core.character import Character
from core.effects.combat import DamageCalculator, DamageType, TempHPEffect
from utils.dice import DiceRoller

logger = logging.getLogger(__name__)

# Store damage verbs as a global dictionary for the damage message generation
DAMAGE_VERBS = {
    "slashing": ["slashes", "cuts", "carves into", "slices"],
    "piercing": ["pierces", "impales", "stabs", "punctures"],
    "bludgeoning": ["bashes", "smashes", "strikes", "pummels"],
    "fire": ["burns", "scorches", "ignites", "sears"],
    "cold": ["freezes", "chills", "frosts", "ices"],
    "lightning": ["shocks", "electrocutes", "zaps", "jolts"],
    "acid": ["melts", "corrodes", "dissolves", "eats away at"],
    "poison": ["poisons", "toxifies", "envenoms", "sickens"],
    "necrotic": ["withers", "decays", "drains", "corrupts"],
    "radiant": ["sears", "purifies", "smites", "blasts"],
    "psychic": ["distresses", "traumatizes", "torments", "assaults"],
    "force": ["blasts", "slams", "impacts", "hammers"],
    "thunder": ["deafens", "blasts", "concusses", "thunders against"],
    "generic": ["damages", "strikes", "attacks", "harms"]
}

# Helper functions need to be defined before they are used
async def _test_standard_damage(debug_cog, interaction):
    """Test standard damage message"""
    print("\n--- Test: Standard Damage ---")
    
    # Set up a test character
    char = await _get_test_character(debug_cog)
    if not char:
        print("Failed to get test character")
        return
        
    # Initial state
    old_hp = char.resources.current_hp
    
    # Simulate damage command
    damage_amount = 5
    damage_type = "slashing"
    
    # Process damage
    char.resources.current_hp = max(0, char.resources.current_hp - damage_amount)
    
    # Create message
    message = f"💥 `{char.name} takes {damage_amount} {damage_type} damage.` HP: {char.resources.current_hp}/{char.resources.max_hp}"
    print(f"Command: /harm {char.name} {damage_amount} {damage_type}")
    print(f"Result: {message}")
    
    # Restore character
    char.resources.current_hp = old_hp
    await debug_cog.bot.db.save_character(char)

async def _test_temp_hp(debug_cog, interaction):
    """Test damage with temp HP"""
    print("\n--- Test: Damage with Temp HP ---")
    
    # Set up a test character
    char = await _get_test_character(debug_cog)
    if not char:
        print("Failed to get test character")
        return
        
    # Initial state
    old_hp = char.resources.current_hp
    
    # Add temp HP
    temp_hp_amount = 10
    char.resources.current_temp_hp = temp_hp_amount
    char.resources.max_temp_hp = temp_hp_amount
    
    # Simulate damage command
    damage_amount = 15
    damage_type = "piercing"
    
    # Process damage
    absorbed = min(char.resources.current_temp_hp, damage_amount)
    remaining = damage_amount - absorbed
    
    char.resources.current_temp_hp = max(0, char.resources.current_temp_hp - absorbed)
    if char.resources.current_temp_hp <= 0:
        char.resources.max_temp_hp = 0
        
    char.resources.current_hp = max(0, char.resources.current_hp - remaining)
    
    # Create message
    message = f"💥 `{char.name} takes {damage_amount} {damage_type} damage, {absorbed} absorbed by shield.` HP: {char.resources.current_hp}/{char.resources.max_hp}"
    print(f"Command: /harm {char.name} {damage_amount} {damage_type}")
    print(f"Result: {message}")
    
    # Restore character
    char.resources.current_hp = old_hp
    char.resources.current_temp_hp = 0
    char.resources.max_temp_hp = 0
    await debug_cog.bot.db.save_character(char)

async def _test_resistances(debug_cog, interaction):
    """Test damage with resistances"""
    print("\n--- Test: Damage with Resistances ---")
    
    # Set up a test character
    char = await _get_test_character(debug_cog)
    if not char:
        print("Failed to get test character")
        return
        
    # Initial state
    old_hp = char.resources.current_hp
    
    # Add resistance
    resist_type = "fire"
    resist_amount = 50  # 50% resistance
    char.defense.damage_resistances[resist_type] = resist_amount
    
    # Simulate damage command
    damage_amount = 20
    damage_type = resist_type
    
    # Process damage
    reduced_amount = int(damage_amount * (1 - resist_amount / 100))
    char.resources.current_hp = max(0, char.resources.current_hp - reduced_amount)
    
    # Create message
    message = f"💥 `{char.name} takes {reduced_amount} {damage_type} damage (resisted 50%).` HP: {char.resources.current_hp}/{char.resources.max_hp}"
    print(f"Command: /harm {char.name} {damage_amount} {damage_type}")
    print(f"Result: {message}")
    
    # Restore character
    char.resources.current_hp = old_hp
    char.defense.damage_resistances = {}
    await debug_cog.bot.db.save_character(char)

async def _test_vulnerabilities(debug_cog, interaction):
    """Test damage with vulnerabilities"""
    print("\n--- Test: Damage with Vulnerabilities ---")
    
    # Set up a test character
    char = await _get_test_character(debug_cog)
    if not char:
        print("Failed to get test character")
        return
        
    # Initial state
    old_hp = char.resources.current_hp
    
    # Add vulnerability
    vuln_type = "cold"
    vuln_amount = 50  # 50% vulnerability
    char.defense.damage_vulnerabilities[vuln_type] = vuln_amount
    
    # Simulate damage command
    damage_amount = 10
    damage_type = vuln_type
    
    # Process damage
    increased_amount = int(damage_amount * (1 + vuln_amount / 100))
    char.resources.current_hp = max(0, char.resources.current_hp - increased_amount)
    
    # Create message
    message = f"💥 `{char.name} takes {increased_amount} {damage_type} damage (vulnerable +50%).` HP: {char.resources.current_hp}/{char.resources.max_hp}"
    print(f"Command: /harm {char.name} {damage_amount} {damage_type}")
    print(f"Result: {message}")
    
    # Restore character
    char.resources.current_hp = old_hp
    char.defense.damage_vulnerabilities = {}
    await debug_cog.bot.db.save_character(char)

async def _test_multi_damage(debug_cog, interaction):
    """Test multiple damage types"""
    print("\n--- Test: Multiple Damage Types ---")
    
    # Set up a test character
    char = await _get_test_character(debug_cog)
    if not char:
        print("Failed to get test character")
        return
        
    # Initial state
    old_hp = char.resources.current_hp
    
    # Simulate damage command with multiple types
    damage_amounts = {"slashing": 3, "fire": 5}
    total_damage = sum(damage_amounts.values())
    
    # Process damage
    char.resources.current_hp = max(0, char.resources.current_hp - total_damage)
    
    # Create message
    damage_details = ", ".join(f"{amt} {type}" for type, amt in damage_amounts.items())
    message = f"💥 `{char.name} takes {total_damage} damage ({damage_details}).` HP: {char.resources.current_hp}/{char.resources.max_hp}"
    print(f"Command: /harm {char.name} 3 slashing, 5 fire")
    print(f"Result: {message}")
    
    # Restore character
    char.resources.current_hp = old_hp
    await debug_cog.bot.db.save_character(char)

async def _test_critical_damage(debug_cog, interaction):
    """Test critical hit damage"""
    print("\n--- Test: Critical Hit Damage ---")
    
    # Set up a test character
    char = await _get_test_character(debug_cog)
    if not char:
        print("Failed to get test character")
        return
        
    # Initial state
    old_hp = char.resources.current_hp
    
    # Simulate critical damage command
    damage_amount = 12
    damage_type = "piercing"
    
    # Process damage
    char.resources.current_hp = max(0, char.resources.current_hp - damage_amount)
    
    # Create message
    message = f"💥 `CRITICAL HIT! {char.name} takes {damage_amount} {damage_type} damage.` HP: {char.resources.current_hp}/{char.resources.max_hp}"
    print(f"Command: /harm {char.name} {damage_amount//2} {damage_type} --crit")
    print(f"Result: {message}")
    
    # Restore character
    char.resources.current_hp = old_hp
    await debug_cog.bot.db.save_character(char)

async def _test_character_damage(debug_cog, interaction):
    """Test damage from one character to another"""
    print("\n--- Test: Character to Character Damage ---")
    
    # Set up test characters
    source = await _get_test_character(debug_cog, "test")
    target = await _get_test_character(debug_cog, "test2")
    
    if not source or not target:
        print("Failed to get test characters")
        return
        
    # Initial state
    old_hp = target.resources.current_hp
    
    # Simulate damage command
    damage_amount = 8
    damage_type = "slashing"
    
    # Process damage
    target.resources.current_hp = max(0, target.resources.current_hp - damage_amount)
    
    # Select a random verb based on damage type
    verbs = debug_cog.damage_verbs.get(damage_type, debug_cog.damage_verbs["generic"])
    verb = random.choice(verbs)
    
    # Create message
    message = f"⚔️ `{source.name} {verb} {target.name} for {damage_amount} {damage_type} damage.` HP: {target.resources.current_hp}/{target.resources.max_hp}"
    print(f"Command: /harm {target.name} {damage_amount} {damage_type} --attacker {source.name}")
    print(f"Result: {message}")
    
    # Restore character
    target.resources.current_hp = old_hp
    await debug_cog.bot.db.save_character(target)

async def _test_overkill(debug_cog, interaction):
    """Test damage that reduces HP to 0"""
    print("\n--- Test: Overkill Damage ---")
    
    # Set up a test character
    char = await _get_test_character(debug_cog)
    if not char:
        print("Failed to get test character")
        return
        
    # Initial state
    old_hp = char.resources.current_hp
    
    # Simulate massive damage command
    damage_amount = 100  # Guaranteed to be more than HP
    damage_type = "necrotic"
    
    # Process damage
    overkill = max(0, damage_amount - char.resources.current_hp)
    char.resources.current_hp = 0
    
    # Create message
    message = f"💀 `{char.name} takes {damage_amount} {damage_type} damage and falls! ({overkill} overkill)` HP: 0/{char.resources.max_hp}"
    print(f"Command: /harm {char.name} {damage_amount} {damage_type}")
    print(f"Result: {message}")
    
    # Restore character
    char.resources.current_hp = old_hp
    await debug_cog.bot.db.save_character(char)

async def _test_mana_changes(debug_cog, interaction):
    """Test various mana changes"""
    print("\n--- Test: Mana Changes ---")
    
    # Set up a test character
    char = await _get_test_character(debug_cog)
    if not char:
        print("Failed to get test character")
        return
        
    # Initial state
    old_mp = char.resources.current_mp
    max_mp = char.resources.max_mp
    half_mp = max_mp // 2
    
    # Test 1: Add mana
    char.resources.current_mp = half_mp  # Set to half
    add_amount = 10
    new_mp = min(max_mp, half_mp + add_amount)
    
    # Create message for add
    add_message = f"💙 `{char.name} gains {add_amount} MP.` MP: {new_mp}/{max_mp}"
    print(f"Command: /mana add {char.name} {add_amount}")
    print(f"Result: {add_message}")
    
    # Test 2: Subtract mana
    char.resources.current_mp = half_mp  # Reset to half
    sub_amount = 10
    new_mp = max(0, half_mp - sub_amount)
    
    # Create message for subtract
    sub_message = f"💙 `{char.name} spends {sub_amount} MP on an ability.` MP: {new_mp}/{max_mp}"
    print(f"Command: /mana sub {char.name} {sub_amount}")
    print(f"Result: {sub_message}")
    
    # Test 3: Set mana
    set_amount = 15
    char.resources.current_mp = half_mp  # Reset to half
    change = set_amount - half_mp
    
    # Create message for set
    change_text = f" (+{change})" if change > 0 else f" ({change})" if change < 0 else ""
    set_message = f"💙 `{char.name}'s MP set to {set_amount}/{max_mp}{change_text}`"
    print(f"Command: /mana set {char.name} {set_amount}")
    print(f"Result: {set_message}")
    
    # Restore character
    char.resources.current_mp = old_mp
    await debug_cog.bot.db.save_character(char)

async def _get_test_character(debug_cog, name: str = "test") -> Optional[Character]:
    """Get or create a test character"""
    char = debug_cog.bot.game_state.get_character(name)
    
    if not char:
        # Try to recreate test characters
        print(f"Test character '{name}' not found, attempting to recreate...")
        from utils.test_helper import recreate_test_characters
        chars = await recreate_test_characters(debug_cog.bot)
        
        if name in chars:
            char = debug_cog.bot.game_state.get_character(name)
        else:
            print(f"Failed to recreate test character '{name}'")
            return None
            
    return char

def add_resource_debug_commands(debug_cog):
    """Add resource debug commands to the main DebugCommands cog"""
    
    # Store the damage verbs for access in methods
    debug_cog.damage_verbs = DAMAGE_VERBS
    
    # Add direct commands using the debug_cog's group command
    
    @debug_cog.app_command.command(name="test_resources")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_resources(interaction: discord.Interaction):
        """Run all resource message tests with various damage and mana scenarios"""
        try:
            await interaction.response.defer()
            
            print("\n=== RESOURCE DEBUG TESTING ===\n")
            
            # Run all test functions
            await _test_standard_damage(debug_cog, interaction)
            await asyncio.sleep(1)  # Brief pause between tests
            
            await _test_temp_hp(debug_cog, interaction)
            await asyncio.sleep(1)
            
            await _test_resistances(debug_cog, interaction)
            await asyncio.sleep(1)
            
            await _test_vulnerabilities(debug_cog, interaction)
            await asyncio.sleep(1)
            
            await _test_multi_damage(debug_cog, interaction)
            await asyncio.sleep(1)
            
            await _test_critical_damage(debug_cog, interaction)
            await asyncio.sleep(1)
            
            await _test_character_damage(debug_cog, interaction)
            await asyncio.sleep(1)
            
            await _test_overkill(debug_cog, interaction)
            await asyncio.sleep(1)
            
            await _test_mana_changes(debug_cog, interaction)
            
            print("\n=== RESOURCE DEBUG COMPLETE ===\n")
            await interaction.followup.send("Resource debug testing complete - check console for results")
            
        except Exception as e:
            logger.error(f"Error in resource debug test: {e}", exc_info=True)
            await interaction.followup.send(f"Error: {str(e)}")

    @debug_cog.app_command.command(name="damage_variations")
    @app_commands.checks.has_permissions(administrator=True)
    async def damage_variations(interaction: discord.Interaction):
        """Test different damage message variations in the channel"""
        try:
            await interaction.response.defer()
            
            # Get test characters
            char1 = await _get_test_character(debug_cog, "test")
            char2 = await _get_test_character(debug_cog, "test2")
            
            if not char1 or not char2:
                await interaction.followup.send("Test characters not found")
                return
            
            # Store original HP
            old_hp1 = char1.resources.current_hp
            old_hp2 = char2.resources.current_hp
                
            await interaction.followup.send("Showing damage message variations:")
            
            # Basic damage
            await interaction.channel.send(f"💥 `{char1.name} takes 7 slashing damage.` HP: {char1.resources.current_hp-7}/{char1.resources.max_hp}")
            await asyncio.sleep(1)
            
            # Character to character
            await interaction.channel.send(f"⚔️ `{char1.name} slashes {char2.name} for 12 slashing damage.` HP: {char2.resources.current_hp-12}/{char2.resources.max_hp}")
            await asyncio.sleep(1)
            
            # Critical hit
            await interaction.channel.send(f"💥 `CRITICAL HIT! {char2.name} takes 18 piercing damage.` HP: {char2.resources.current_hp-18}/{char2.resources.max_hp}")
            await asyncio.sleep(1)
            
            # With resistance
            await interaction.channel.send(f"💥 `{char1.name} takes 5 fire damage (resisted 50%).` HP: {char1.resources.current_hp-5}/{char1.resources.max_hp}")
            await asyncio.sleep(1)
            
            # With vulnerability
            await interaction.channel.send(f"⚡ `{char1.name} takes 15 lightning damage (vulnerable +50%).` HP: {char1.resources.current_hp-15}/{char1.resources.max_hp}")
            await asyncio.sleep(1)
            
            # Multiple damage types
            await interaction.channel.send(f"💥 `{char2.name} takes 20 damage (12 fire, 8 radiant).` HP: {char2.resources.current_hp-20}/{char2.resources.max_hp}")
            await asyncio.sleep(1)
            
            # Temp HP absorption
            await interaction.channel.send(f"🛡️ `{char1.name} takes 15 bludgeoning damage, 10 absorbed by shield.` HP: {char1.resources.current_hp-5}/{char1.resources.max_hp}")
            await asyncio.sleep(1)
            
            # Down to 0 HP
            await interaction.channel.send(f"💀 `{char2.name} takes 50 necrotic damage and falls!` HP: 0/{char2.resources.max_hp}")
            await asyncio.sleep(1)
            
            # Character-to-character critical
            await interaction.channel.send(f"⚔️ `{char2.name} critically smites {char1.name} for 25 radiant damage.` HP: {char1.resources.current_hp-25}/{char1.resources.max_hp}")
            
            # Restore characters
            char1.resources.current_hp = old_hp1
            char2.resources.current_hp = old_hp2
            await debug_cog.bot.db.save_character(char1)
            await debug_cog.bot.db.save_character(char2)
            
            await interaction.channel.send("All message variations displayed")
            
        except Exception as e:
            logger.error(f"Error in damage variations: {e}", exc_info=True)
            await interaction.followup.send(f"Error: {str(e)}")

    @debug_cog.app_command.command(name="mana_variations")
    @app_commands.checks.has_permissions(administrator=True)
    async def mana_variations(interaction: discord.Interaction):
        """Test different mana message variations in the channel"""
        try:
            await interaction.response.defer()
            
            # Get test character
            char = await _get_test_character(debug_cog, "test")
            
            if not char:
                await interaction.followup.send("Test character not found")
                return
            
            # Store original MP
            old_mp = char.resources.current_mp
            max_mp = char.resources.max_mp
                
            await interaction.followup.send("Showing mana message variations:")
            
            # Add mana
            await interaction.channel.send(f"💙 `{char.name} gains 15 MP.` MP: {min(max_mp, old_mp+15)}/{max_mp}")
            await asyncio.sleep(1)
            
            # Subtract mana
            await interaction.channel.send(f"💙 `{char.name} spends 10 MP on Fireball.` MP: {max(0, old_mp-10)}/{max_mp}")
            await asyncio.sleep(1)
            
            # Add with reason
            await interaction.channel.send(f"💙 `{char.name} gains 8 MP from meditation.` MP: {min(max_mp, old_mp+8)}/{max_mp}")
            await asyncio.sleep(1)
            
            # Set to value (increase)
            await interaction.channel.send(f"💙 `{char.name}'s MP set to {max_mp}/{max_mp} (+{max_mp-old_mp}) (full restore)`")
            await asyncio.sleep(1)
            
            # Set to value (decrease)
            await interaction.channel.send(f"💙 `{char.name}'s MP set to 5/{max_mp} ({5-old_mp}) (drained)`")
            
            # Restore character
            char.resources.current_mp = old_mp
            await debug_cog.bot.db.save_character(char)
            
            await interaction.channel.send("All mana message variations displayed")
            
        except Exception as e:
            logger.error(f"Error in mana variations: {e}", exc_info=True)
            await interaction.followup.send(f"Error: {str(e)}")
    
    # Tell the user we're successful
    print("Resource debug commands added successfully")