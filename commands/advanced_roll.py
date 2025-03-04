"""
Advanced roll commands using the new dice system.
Supports complex rolls with modifiers, multi-hits, targeting, and more.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
import logging

from utils.advanced_dice.calculator import DiceCalculator
from utils.advanced_dice.attack_calculator import AttackCalculator, AttackParameters
from utils.error_handler import handle_error
from utils.stat_helper import StatType, StatHelper
from utils.dice import DiceRoller

logger = logging.getLogger(__name__)

class RollCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="roll")
    @app_commands.describe(
        expression="Dice expression (e.g., 2d6+3, d20+str, 3d20 multihit, d20 advantage)",
        character="Character name for stat modifiers (for +str, +dex, etc.)",
        targets="Target(s) to check against (comma-separated names)",
        aoe="AoE mode: 'single' (one roll against all) or 'multi' (roll per target)",
        crit_range="Natural roll required for critical hit (default: 20)",
        damage="Damage formula with type (e.g., '2d6 fire', '1d8+str slashing, 2d4 cold')",
        reason="Optional note to display with the roll result",
        detailed="Show detailed roll breakdown (for non-target rolls)",
    )
    async def roll(
        self,
        interaction: discord.Interaction,
        expression: str,
        character: Optional[str] = None,
        targets: Optional[str] = None,
        aoe: Optional[str] = None,
        crit_range: Optional[int] = 20,
        damage: Optional[str] = None,
        reason: Optional[str] = None,
        detailed: bool = False,
    ):
        """
        Roll dice with advanced options
        
        BASIC FORMAT:
        • Simple roll: 2d6, d20
        • With modifiers: d20+str, 2d6+3
        • Advantage/disadvantage: d20 advantage, d20 disadvantage
        • Multihit: 3d20 multihit 2
        
        ATTACK EXAMPLES:
        • Single target: /roll d20+str targets:Goblin damage:2d6 slashing
        • Multiple targets: /roll d20+dex targets:Goblin,Orc damage:2d6 fire
        • Multiple hits: /roll 3d20 multihit 2 targets:Boss damage:1d6
        """
        try:
            # Simple command logging
            cmd_log = f"/roll expression: {expression}"
            if character:
                cmd_log += f" character: {character}"
            if targets:
                cmd_log += f" targets: {targets}"
            if aoe:
                cmd_log += f" aoe: {aoe}"
            if damage:
                cmd_log += f" damage: {damage}"
            if reason:
                cmd_log += f" reason: {reason}"
            print(f"\nCommand: {cmd_log}")
            
            await interaction.response.defer()
            
            # Get character if specified
            char_obj = None
            if character:
                char_obj = self.bot.game_state.get_character(character)
                if not char_obj:
                    await interaction.followup.send(
                        f"Character '{character}' not found.",
                        ephemeral=True
                    )
                    return

            # If no targets, use regular dice calculator
            if not targets and not damage:
                total, formatted, detailed_log = DiceCalculator.calculate_complex(
                    expression,
                    character=char_obj,
                    concise=not detailed
                )
                await interaction.followup.send(formatted)
                if detailed_log:
                    print(f"Roll details:\n{detailed_log}")
                return

            # Get targets if specified
            target_list = []
            if targets:
                target_names = [t.strip() for t in targets.split(',')]
                for name in target_names:
                    target = self.bot.game_state.get_character(name)
                    if target:
                        target_list.append(target)
                    else:
                        await interaction.followup.send(
                            f"Target '{name}' not found.",
                            ephemeral=True
                        )
                        return

            # Set up attack parameters
            params = AttackParameters(
                roll_expression=expression,
                character=char_obj,
                targets=target_list if target_list else None,
                damage_str=damage,
                crit_range=crit_range,
                aoe_mode=aoe or 'single',
                reason=reason
            )

            # Process the attack roll
            message, detailed_embed = await AttackCalculator.process_attack(params)
            print(f"Roll output: {message}")
            
            # Send initial response
            if detailed_embed:
                # Add reaction for details if there's an embed
                sent_message = await interaction.followup.send(message)
                await sent_message.add_reaction('📊')
                
                # Store embed for reaction handler
                setattr(sent_message, '_roll_details', detailed_embed)
                
                # Add reaction handler
                def check(reaction, user):
                    return (
                        user == interaction.user and 
                        str(reaction.emoji) == '📊' and
                        reaction.message.id == sent_message.id
                    )
                
                try:
                    # Wait for reaction (60 seconds)
                    reaction, user = await self.bot.wait_for(
                        'reaction_add',
                        timeout=60.0,
                        check=check
                    )
                    
                    # Show detailed embed
                    await interaction.followup.send(
                        embed=detailed_embed,
                        ephemeral=True
                    )
                    
                    # Remove reaction option
                    await sent_message.clear_reactions()
                    
                except TimeoutError:
                    # Remove reaction after timeout
                    await sent_message.clear_reactions()
            else:
                # Simple roll, just send the message
                await interaction.followup.send(message)

        except Exception as e:
            await handle_error(interaction, e)
            print(f"Error in roll command: {str(e)}")

    @app_commands.command(name="multiroll")
    @app_commands.describe(
        expression="Dice expression to roll multiple times",
        count="Number of times to roll",
        character="Character name for stat modifiers",
    )
    async def multiroll(
        self,
        interaction: discord.Interaction,
        expression: str,
        count: int,
        character: Optional[str] = None,
    ):
        """Roll the same dice expression multiple times"""
        try:
            if count < 1 or count > 20:
                await interaction.response.send_message(
                    "Please enter a number between 1 and 20.",
                    ephemeral=True
                )
                return

            # Get character if specified
            char = None
            if character:
                char = self.bot.game_state.get_character(character)
                if not char:
                    await interaction.response.send_message(
                        f"Character '{character}' not found.",
                        ephemeral=True
                    )
                    return

            # Do rolls
            results = []
            total = 0
            detailed_logs = []

            for i in range(count):
                roll_total, formatted, detailed = DiceCalculator.calculate_complex(
                    expression,
                    character=char,
                    concise=True
                )
                results.append(formatted)
                total += roll_total
                if detailed:
                    detailed_logs.append(detailed)

            # Format output
            output = "\n".join(f"Roll {i+1}: {result}" for i, result in enumerate(results))
            if count > 1:
                output += f"\n\nTotal: {total}"
                output += f"\nAverage: {total/count:.2f}"

            # Send response
            await interaction.response.send_message(output)

            # Log detailed breakdowns
            if detailed_logs:
                log_output = "\n\n".join(detailed_logs)
                print(f"Detailed multiroll breakdown for {interaction.user}:\n{log_output}")

        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="debugroll")
    @app_commands.checks.has_permissions(administrator=True)  # Admin only
    async def debug_roll(self, interaction: discord.Interaction):
        """Run test scenarios for roll command debugging"""
        await interaction.response.defer(ephemeral=True)
        
        print("\n=== Starting Roll Debug Test Suite ===\n")
        
        # Get required test characters
        test_char = self.bot.game_state.get_character("test")
        test_target = self.bot.game_state.get_character("test2")
        test_target2 = self.bot.game_state.get_character("test3")
        
        if not all([test_char, test_target, test_target2]):
            await interaction.followup.send("Error: Required test characters (test, test2, test3) not found in database")
            return
        
        # Print character stats from database
        print("=== Test Character Stats ===")
        for char in [test_char, test_target, test_target2]:
            print(f"\n{char.name}:")
            print("Base Stats:")
            for stat, value in char.stats.base.items():
                print(f"  {stat}: {value} (mod: {(value-10)//2})")
            print("Modified Stats:")
            for stat, value in char.stats.modified.items():
                print(f"  {stat}: {value} (mod: {(value-10)//2})")
            print(f"AC: {char.defense.current_ac}")
            
        print("\n=== Starting Test Scenarios ===\n")

        # Test scenarios with detailed comments
        scenarios = [
            # Static number handling
            {"expr": "15", "char": "test", "target": "test2", "dmg": "1d8"},  # Basic static attack
            {"expr": "3+str", "char": "test", "target": "test2", "dmg": "2d6"},  # Static + stat mod
            {"expr": "str+dex+5", "char": "test", "target": "test2", "dmg": "1d8"},  # Multiple stat mods + static
            {"expr": "str+dex+wis", "char": "test", "target": "test2", "dmg": "1d8"},  # Pure stat combo
            
            # Complex dice combinations
            {"expr": "2d20+str+5", "char": "test", "target": "test2", "dmg": "1d8+str"},  # Dice + stat + static
            {"expr": "3d20 advantage", "char": "test", "target": "test2", "dmg": "2d6"},  # Advantage roll
            {"expr": "d20+str disadvantage", "char": "test", "target": "test2", "dmg": "2d6"},  # Disadvantage with stat
            
            # Multiple damage types
            {"expr": "d20+5", "char": "test", "target": "test2", "dmg": "1d8 slash, 2d6 fire, 1d4 cold"},  # Triple damage type
            {"expr": "15", "char": "test", "target": "test2", "dmg": "str fire, dex cold"},  # Static damage with stats
            
            # AoE behavior
            {"expr": "d20+str", "char": "test", "target": "test2,test3", "dmg": "2d6 fire", "aoe": "single"},  # AoE single with type
            {"expr": "str+15", "char": "test", "target": "test2,test3", "dmg": "str+5 fire", "aoe": "multi"},  # AoE multi with stat dmg
            
            # Crit testing
            {"expr": "d20+wis", "char": "test", "target": "test2", "dmg": "2d6+str", "crit": 15},  # Lower crit threshold
            {"expr": "15", "char": "test", "target": "test2", "dmg": "2d6", "crit": 15},  # Static hit crit
            
            # Multihit combinations
            {"expr": "3d20 multihit 2", "char": "test", "target": "test2", "dmg": "1d6+str"},  # Basic multihit
            {"expr": "3d20 multihit str", "char": "test", "target": "test2", "dmg": "1d6 fire"},  # Multihit with stat bonus
        ]
        
        print(f"Running {len(scenarios)} test scenarios...")

        # Debug function for stat parsing
        def debug_stat_parse(expr: str, char: Optional['Character']):
            print(f"\nDebug Stat Parse for: {expr}")
            if char:
                print(f"Character stats:")
                for stat in StatType:
                    value = StatHelper.get_stat_value(char, stat)
                    mod = StatHelper.get_stat_modifier(char, stat)
                    print(f"  {stat.name}: {value} (mod: {mod})")
                    
                # Debug DiceRoller parsing
                try:
                    total, explanation = DiceRoller.roll_dice(expr, char)
                    print(f"DiceRoller parsed result:")
                    print(f"  Total: {total}")
                    print(f"  Explanation: {explanation}")
                except Exception as e:
                    print(f"DiceRoller error: {e}")
                    
                # Debug Calculator parsing
                try:
                    result, formatted, _ = DiceCalculator.calculate_complex(expr, char)
                    print(f"Calculator parsed result:")
                    print(f"  Result: {result}")
                    print(f"  Formatted: {formatted}")
                except Exception as e:
                    print(f"Calculator error: {e}")

        for i, scenario in enumerate(scenarios, 1):
            print(f"\n=== Scenario {i} ===")
            
            # Build command string
            cmd = f"/roll expression: {scenario['expr']}"
            if 'char' in scenario:
                cmd += f" character: {scenario['char']}"
            if 'target' in scenario:
                cmd += f" targets: {scenario['target']}"
            if 'dmg' in scenario:
                cmd += f" damage: {scenario['dmg']}"
            if 'aoe' in scenario:
                cmd += f" aoe: {scenario['aoe']}"
            if 'reason' in scenario:
                cmd += f" reason: {scenario['reason']}"
                
            print(f"Command: {cmd}")
            
            # Run the roll
            try:
                if 'target' in scenario or 'dmg' in scenario:
                    # Attack roll
                    params = AttackParameters(
                        roll_expression=scenario['expr'],
                        character=self.bot.game_state.get_character(scenario.get('char')),
                        targets=[self.bot.game_state.get_character(t.strip()) 
                                for t in scenario.get('target', '').split(',') if t.strip()],
                        damage_str=scenario.get('dmg'),
                        aoe_mode=scenario.get('aoe', 'single'),
                        reason=scenario.get('reason')
                    )
                    message, _ = await AttackCalculator.process_attack(params)
                else:
                    # Basic roll
                    char = self.bot.game_state.get_character(scenario.get('char')) if 'char' in scenario else None
                    _, message, _ = DiceCalculator.calculate_complex(scenario['expr'], char)
                    
                print(f"Result: {message}")
                
            except Exception as e:
                print(f"Error: {str(e)}")
                
        print("\n=== Roll Debug Complete ===")
        await interaction.followup.send("Roll debug complete - check console for results")

    @app_commands.command(name="rollhelp")
    async def roll_help(self, interaction: discord.Interaction):
        """Show detailed help for dice rolling commands"""
        embed = discord.Embed(
            title="📊 Dice Rolling Guide",
            description="Guide to using the advanced dice rolling system",
            color=discord.Color.blue()
        )
        
        # Basic Rolls
        embed.add_field(
            name="Basic Rolls",
            value=(
                "• `2d6` - Roll two six-sided dice\n"
                "• `d20+5` - Roll d20 and add 5\n"
                "• `4d6+2` - Roll four d6 and add 2\n"
                "• `3d8-1` - Roll three d8 and subtract 1"
            ),
            inline=False
        )
        
        # Stat Modifiers
        embed.add_field(
            name="Character Stats",
            value=(
                "• `d20+str` - Roll d20 and add strength modifier\n"
                "• `2d6+dex` - Roll 2d6 and add dexterity modifier\n"
                "• `d20+str+2` - Roll d20 and add strength modifier plus 2\n"
                "• `d20+proficiency` - Roll d20 and add proficiency bonus"
            ),
            inline=False
        )
        
        # Advanced Options
        embed.add_field(
            name="Advanced Options",
            value=(
                "• `d20 advantage` - Roll with advantage (2d20, take highest)\n"
                "• `d20 disadvantage` - Roll with disadvantage (2d20, take lowest)\n"
                "• `3d20 multihit 2` - Roll 3d20 as separate attacks with +2 to each\n"
                "• `3d20 multihit dex` - Roll 3d20 with dexterity bonus to each hit"
            ),
            inline=False
        )
        
        # Attack Examples
        embed.add_field(
            name="Attack Examples",
            value=(
                "• `/roll d20+str targets:Goblin damage:1d8+str slashing`\n"
                "• `/roll d20+dex targets:Orc,Goblin damage:1d6+dex piercing`\n"
                "• `/roll d20+int targets:Dragon damage:8d6 fire aoe:single`\n"
                "• `/roll 3d20 multihit targets:Boss damage:2d6+str slashing`"
            ),
            inline=False
        )
        
        # AoE Modes
        embed.add_field(
            name="AoE Modes",
            value=(
                "• `single` - One roll applied to all targets\n"
                "• `multi` - Separate roll for each target"
            ),
            inline=False
        )
        
        # Tips and Tricks
        embed.add_field(
            name="Tips and Tricks",
            value=(
                "• Use `reason` to add context to your roll\n"
                "• Set `crit_range` for critical hits below 20\n"
                "• For damage types, just add the type after the formula\n"
                "• Comma-separate damage types: `2d6 fire, 1d8 cold`"
            ),
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
async def setup(bot):
    await bot.add_cog(RollCommands(bot))