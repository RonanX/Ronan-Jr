"""
Ronan Jr Discord Bot - Complete Rewrite (v2.0)

This is a complete rewrite of the Ronan Jr Discord bot, focusing on better code organization,
enhanced features, and a more robust foundation for future additions.

Note: When editing the move effect system, please ensure to update the bridge and effect files accordingly. 
Do not modify the core effect manager directly, as it may lead to inconsistencies and bugs.
Instead, use the provided bridge system to handle move effects and their interactions as well as the
move-exclusive base and manager files in the moves directory.
"""

import os
import sys
import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
from typing import Optional
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db


# Core imports
from core.database import Database
from core.state import GameState
from core.character import Character, Stats, Resources, DefenseStats, StatType
from core.effects.manager import register_effects, process_effects


# Module imports
from modules.menu.character_creation import StatGenerationView, display_creation_result
from modules.menu.character_viewer import CharacterViewer
from modules.menu.defense_handler import DefenseHandler

# Load error handler
from utils.error_handler import setup as error_handler_setup


# Enhanced environment variable loading with better error handling
def load_environment_variables():
    """Load environment variables with robust error checking and helpful messages"""
    # First, check if the secrets.env file exists
    env_path = 'secrets.env'
    if not os.path.exists(env_path):
        print(f"ERROR: {env_path} file not found in {os.getcwd()}")
        print("Please ensure your secrets.env file is in the correct directory.")
        return False
    
    # Try to load the environment variables
    load_dotenv(env_path)
    
    # Check required variables
    required_vars = [
        'TOKEN',         # Bot token (primary)
        'DMTOKEN',       # Alternative token name
        'DATABASEURL',   # Firebase URL
        'APIKEY',        # Firebase API key
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    # Look for either TOKEN or DMTOKEN (allowing for different naming conventions)
    has_token = os.getenv('TOKEN') or os.getenv('DMTOKEN')
    if not has_token:
        print("ERROR: No bot token found in secrets.env")
        print("Please make sure either TOKEN or DMTOKEN is set in your secrets.env file")
        return False
    
    # Report any other missing variables
    if missing_vars and 'TOKEN' in missing_vars and 'DMTOKEN' not in missing_vars:
        # If TOKEN is missing but DMTOKEN exists, we can continue
        missing_vars.remove('TOKEN')
    
    if missing_vars:
        print(f"WARNING: The following variables are missing from secrets.env: {', '.join(missing_vars)}")
        print("Some features may not work correctly without these variables.")
        
    # Print successful variables for debugging
    print("Environment Variables Loaded Successfully:")
    token_var = 'DMTOKEN' if os.getenv('DMTOKEN') else 'TOKEN'
    print(f"✓ Bot token ({token_var})")
    print(f"✓ Database URL: {os.getenv('DATABASEURL')[:20]}..." if os.getenv('DATABASEURL') else "✗ Database URL missing")
    
    return True

# Load environment variables
if not load_environment_variables():
    print("Failed to load required environment variables. Please fix secrets.env file.")
    sys.exit(1)  # Exit if critical environment variables are missing

# Get the token, prioritizing DMTOKEN if available (for backward compatibility)
TOKEN = os.getenv('DMTOKEN') if os.getenv('DMTOKEN') else os.getenv('TOKEN')

# Get Firebase config from environment variables
DATABASEURL = os.getenv('DATABASEURL')
APIKEY = os.getenv('APIKEY')
AUTHDOMAIN = os.getenv('AUTHDOMAIN')
PROJECTID = os.getenv('PROJECTID')
STORAGEBUCKET = os.getenv('STORAGEBUCKET')
MESSAGINGSENDERID = os.getenv('MESSAGINGSENDERID')
APPID = os.getenv('APPID')
MEASUREMENTID = os.getenv('MEASUREMENTID')

# Configure logging  
logging.basicConfig(  
    level=logging.INFO,  
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  
    handlers=[  
        logging.FileHandler('bot.log'),  
        logging.StreamHandler()  
    ]  
)  
logger = logging.getLogger(__name__)

# List of guild IDs where commands will be available  
GUILD_IDS = [421424814952284160, 968588058133942312]

class GameBot(commands.Bot):  
    """Main bot class that handles all game logic and state"""  
    def __init__(self):  
        intents = discord.Intents.default()  
        intents.message_content = True  
        intents.messages = True  
         
        super().__init__(  
            command_prefix='/',  
            intents=intents,  
            allowed_mentions=discord.AllowedMentions(  
                roles=False,  
                users=False,  
                everyone=False  
            )  
        )  
        
        # Initialize core systems  
        self.db = Database()  
        self.game_state = GameState()  
         
        # Sync status  
        self.synced = False
        
        # Store important commands for verification
        self.verified_commands = {}
        self.required_commands = {
            'move': ['use', 'temp', 'create', 'update', 'list', 'import']
        }
        
    async def verify_commands(self):
        """Verify that all required commands are registered"""
        for group, commands_list in self.required_commands.items():
            group_cog = self.get_cog(f"{group.capitalize()}Commands")
            if not group_cog:
                print(f"WARNING: {group.capitalize()}Commands cog not found!")
                continue
                
            print(f"Checking {group} commands...")
            
            # Get all registered commands in this group
            try:
                registered = [cmd.name for cmd in group_cog.walk_app_commands()]
                print(f"Found commands: {', '.join(registered)}")
                
                # Check for missing commands
                missing = [cmd for cmd in commands_list if cmd not in registered]
                if missing:
                    print(f"WARNING: Missing required {group} commands: {', '.join(missing)}")
                    print("Try running the /sync command to update Discord's command registry.")
                else:
                    print(f"✓ All required {group} commands are registered")
                    
                # Store for reference
                self.verified_commands[group] = registered
            except Exception as e:
                print(f"Error checking {group} commands: {e}")
        
    async def setup_hook(self):
        """Called when the bot is starting up"""
        # Register all effect types  
        register_effects()  
         
        # Load data from database with better error handling
        try:
            await self.db.initialize()  
            await self.game_state.load(self.db)
            print("Database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}", exc_info=True)
            print(f"WARNING: Database initialization failed. Error: {e}")
            print("Bot will continue without database functionality.")
        
        # Register the move effect bridge
        try:
            from core.effects.move.bridge import register_with_bot
            register_with_bot(self)
            print("Move effect bridge registered successfully")
            
            # Add diagnostics for additional error checking
            try:
                from core.effects.move.effect import MoveEffect, MovePhase
                from core.effects.move.combat import CombatProcessor
                print(f"Move effect subsystem verified: MoveEffect OK, MovePhase OK")
                
                # Test for required methods
                test_effect = MoveEffect(name="test", description="test")
                if hasattr(test_effect, 'get_phase_name') and callable(test_effect.get_phase_name):
                    print("Required method check: get_phase_name() OK")
                else:
                    print("WARNING: Required method missing: get_phase_name()")
                
                # Test for combat processor
                test_processor = CombatProcessor()
                if hasattr(test_processor, 'perform_sync_attack') and callable(test_processor.perform_sync_attack):
                    print("Required method check: perform_sync_attack() OK")
                else:
                    print("WARNING: Required method missing: perform_sync_attack()")
                    
            except Exception as verification_error:
                print(f"Move effect verification failed: {verification_error}")
        except Exception as e:
            logger.error(f"Failed to register move effect bridge: {e}", exc_info=True)
            print(f"WARNING: Move effects may not function correctly. Error: {e}")
         
        # Load command extensions
        print("Loading command extensions...")
        extensions = [
            "commands.effects",
            "commands.debug",
            "commands.movesets",
            "commands.mana",
            "commands.combat",
            "commands.healing",
            "commands.advanced_roll",
            "commands.skillcheck",
            "commands.move_cancel",
            "modules.menu.skill_check_handler",
            "commands.initiative",
            "commands.qol",
            "commands.moves",
            "commands.actions"
        ]
        
        # Track loaded extensions
        loaded_extensions = []
        
        for extension in extensions:
            try:
                await self.load_extension(extension)
                loaded_extensions.append(extension)
                print(f"✓ Loaded {extension}")
            except Exception as e:
                logger.error(f"Failed to load extension {extension}: {e}", exc_info=True)
                print(f"✗ Error loading {extension}: {e}")
        
        print(f"Loaded {len(loaded_extensions)}/{len(extensions)} extensions")

        # Get initiative tracker from the cog after loading  
        initiative_cog = self.get_cog('InitiativeCommands')  
        if initiative_cog:  
            self.initiative_tracker = initiative_cog.tracker
        
        # Verify all required commands
        await self.verify_commands()
        
    async def on_ready(self):
        """Called when the bot is ready"""
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print(f'{self.user}: ok i pull up')
        
        # Auto-sync commands if needed and possible
        if not self.synced:
            print("Commands not yet synced. Attempting auto-sync...")
            try:
                # Try syncing to primary guild first for faster testing
                guild = discord.Object(id=GUILD_IDS[0])
                synced = await self.tree.sync(guild=guild)
                print(f"Auto-synced {len(synced)} commands to guild {GUILD_IDS[0]}")
                self.synced = True
                
                # Verify commands again after sync
                await self.verify_commands()
            except Exception as e:
                print(f"Auto-sync failed: {e}")
                print("Manual sync required using /sync command")

bot = GameBot()


# Setup error handler
error_handler_setup(bot)

@bot.hybrid_command(name='sync', description='Synchronize the bot with the predefined guilds.')
@commands.is_owner()
async def sync(ctx: commands.Context):
    try:
        # Sync global commands
        global_commands = await bot.tree.sync()
        await ctx.send(f"{len(global_commands)} global commands synced.")


        # Sync guild-specific commands  
        for guild_id in GUILD_IDS:
            guild = discord.Object(id=guild_id)
            guild_commands = await bot.tree.sync(guild=guild)
            await ctx.send(f"{len(guild_commands)} commands synced to guild ID {guild_id}.")
       
        print(f"Commands synced successfully.")
       
    except Exception as e:
        error_message = f"Error syncing commands: {e}"
        logging.error(error_message)
        await ctx.send(error_message, ephemeral=True)


### Character Management Commands ###


@bot.tree.command(name="create", description="Create a new character")
@app_commands.describe(
    name="The name of the character",
    hp="Starting hit points",
    mp="Starting mana points",
    ac="Base armor class"
)
async def create_character(
    interaction: discord.Interaction,
    name: str,
    hp: int,
    mp: int,
    ac: int
):
    """Creates a new character with customizable stats"""
    try:
        # Check if character already exists
        if bot.game_state.get_character(name):
            embed = discord.Embed(
                title="❌ Error",
                description=f"A character named '{name}' already exists.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return


        # Create initial embed
        embed = discord.Embed(
            title="Character Creation",
            description=(
                f"Creating character: **{name}**\n\n"
                "Choose how you want to generate stats:\n"
                "🎲 **Roll Method**: Different dice rolling methods\n"
                "💪 **Power Level**: Preset stat ranges\n"
                "✍️ **Manual Entry**: Input your own stats"
            ),
            color=discord.Color.blue()
        )
       
        # Show base info
        embed.add_field(
            name="Base Values",
            value=f"❤️ HP: {hp}\n💙 MP: {mp}\n🛡️ AC: {ac}",
            inline=False
        )


        # Create and show stat generation options
        view = StatGenerationView(name, hp, mp, ac)
        await interaction.response.send_message(embed=embed, view=view)
       
    except Exception as e:
        logger.error(f"Error in create command: {str(e)}", exc_info=True)
        await interaction.response.send_message(
            "An error occurred while creating the character. Please try again.",
            ephemeral=True
        )


@bot.tree.command(name="delete", description="Delete a character")
@app_commands.describe(name="The name of the character to delete")
async def delete_character(interaction: discord.Interaction, name: str):
    """Deletes a character from the game"""
    await interaction.response.defer()
   
    try:
        # Remove from database
        await bot.db.delete_character(name)
       
        # Remove from game state
        bot.game_state.remove_character(name)
       
        await interaction.followup.send(f"Character {name} has been deleted.")
       
    except Exception as e:
        logger.error(f"Error deleting character: {e}", exc_info=True)
        await interaction.followup.send(
            "An error occurred while deleting the character.",
            ephemeral=True
        )

@bot.tree.command(name="check", description="Display a character's stats and status")
@app_commands.describe(
    name="Name of the character to check",
    ephemeral="Whether to show the result only to you (default: True)"
)
async def check(interaction: discord.Interaction, name: str, ephemeral: bool = True):
    """Displays detailed character information using the CharacterViewer"""
    try:
        # Convert name to proper case and check both versions
        proper_name = name.capitalize()
        character = bot.game_state.get_character(name) or bot.game_state.get_character(proper_name)
        
        if not character:
            await interaction.response.send_message(
                f"Character '{name}' not found.",
                ephemeral=True  # Always make error messages ephemeral
            )
            return

        # Initialize and show the character viewer
        viewer = CharacterViewer(character)
        await viewer.show(interaction, ephemeral=ephemeral)

    except Exception as e:
        logger.error(f"Error in check command: {str(e)}", exc_info=True)
        await interaction.response.send_message(
            "An error occurred while displaying character information.",
            ephemeral=True  # Always make error messages ephemeral
        )


@bot.tree.command(name="list", description="List all characters")
async def list_characters(interaction: discord.Interaction):
    """Lists all characters in the game"""
    await interaction.response.defer()
   
    try:
        # Try loading from database first
        char_names = await bot.db.list_characters()
       
        if not char_names:
            await interaction.followup.send("No characters found.")
            return
           
        # Load each character
        characters = []
        for name in char_names:
            # Try game state first
            char = bot.game_state.get_character(name)
            if not char:
                # If not in game state, load from database
                char_data = await bot.db.load_character(name)
                if char_data:
                    char = Character.from_dict(char_data)
                    bot.game_state.add_character(char)
            if char:
                characters.append(char)
           
        if not characters:
            await interaction.followup.send("No characters found.")
            return
           
        embed = discord.Embed(title="Character List", color=discord.Color.blue())
       
        for character in sorted(characters, key=lambda c: c.name):
            status = (
                f"HP: {character.resources.current_hp}/{character.resources.max_hp} | "
                f"MP: {character.resources.current_mp}/{character.resources.max_mp} | "
                f"AC: {character.defense.current_ac}"
            )
            embed.add_field(name=character.name, value=status, inline=False)
           
        await interaction.followup.send(embed=embed)
       
    except Exception as e:
        logger.error(f"Error listing characters: {e}", exc_info=True)
        await interaction.followup.send(
            "An error occurred while retrieving the character list.",
            ephemeral=True
        )


@bot.command(name='stop')
@commands.is_owner()
async def stop(ctx):
    """Stops the bot and closes the process."""
    await ctx.send("Shutting down...")
    await bot.close()


if __name__ == "__main__":
    bot.run(TOKEN)


"""
Available Conditions:
Movement Conditions:
- prone: -2 to attacks, melee attackers have advantage
- grappled: Cannot move or be moved
- restrained: No movement, disadvantage on attacks, vulnerable
- airborne: Out of melee range, immune to ground effects
- slowed: Half movement speed, no reactions


Combat Conditions:
- blinded: Can't see, disadvantage on attacks, vulnerable
- deafened: Can't hear, fails hearing-based checks
- marked: Next attack has advantage, moving triggers reactions
- guarded: Attacks against have disadvantage, better defenses
- flanked: Vulnerable to attacks, can't take reactions


Control Conditions:
- incapacitated: No actions/reactions, fails STR/DEX saves
- paralyzed: Can't move/act, melee hits are critical
- charmed: Can't attack source, vulnerable to their effects
- frightened: Must move away, disadvantage near source
- confused: Random actions each turn


Situational Conditions:
- hidden: Hard to hit, advantage on attacks
- invisible: Can't be seen, advantage on attacks
- underwater: Most attacks disadvantage, fire resistance
- concentrating: Must make CON saves when damaged
- surprised: No actions first turn, vulnerable


State Conditions:
- bleeding: DoT damage, leaves trail
- poisoned: Disadvantage on rolls, DoT damage
- silenced: No verbal spells/speech
- exhausted: All penalties halved


Usage:
/effect condition <target> <comma-separated conditions> [duration]
Example: /effect condition Gandalf prone,blinded 3


Note: Duration is optional. Without duration, conditions are toggles.
Effects show in turn order and character sheets with mechanical effects.
"""
