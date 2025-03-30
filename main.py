"""
Ronan Jr Discord Bot - Complete Rewrite (v2.0)


This is a complete rewrite of the Ronan Jr Discord bot, focusing on better code organization,
enhanced features, and a more robust foundation for future additions.


Features to Implement:
1. Character System
   - Enhanced stat generation with multiple methods
   - Status effect system with various effect types
   - Temporary stat modifications
   - Character progression and leveling
   - Inventory system with item management


2. Combat System
   - Initiative tracking with multiple options
   - Action economy with Initiative Points (IP)
   - Turn management and combat states
   - AoE and multi-target support
   - Combat log and history


3. Spell/Move System
   - Spell slots and cooldowns
   - Multiple damage types and resistances
   - Effect application and duration tracking
   - Spell categories and organization
   - Moveset saving and loading


4. UI Improvements
   - Form-based input for complex commands
   - Rich embeds for information display
   - Interactive menus and buttons
   - Better feedback and error messages
   - Help system with examples


5. Quality of Life Features
   - Dice rolling with various methods
   - State saving and loading
   - Combat automation options
   - Batch commands for efficiency
   - Custom command aliases


6. Additional Systems
   - Random name generation
   - Grid-based movement
   - Effect combinations
   - Custom effect creation
   - Sound effects and multimedia


Code Organization:
- core/: Core systems and data structures
- modules/: Feature-specific implementations
- utils/: Helper functions and constants
- menu/: UI components and views


This rewrite aims to provide a more maintainable, extensible, and user-friendly bot
while preserving and enhancing the functionality of the original version.
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


# Load environment variables
load_dotenv('secrets.env')


# Get the token and Firebase config from environment variables
TOKEN = "MTE1MjQ0Mzc1Mjg3OTc1MTI5Mg.GLZp2d.uDIu0Hhy2ivGJ2dgiirjqIE9HF5mBFajuacc9g"
DATABASEURL = "https://ronan-jr-s-brain-default-rtdb.firebaseio.com"
APIKEY = "AIzaSyBAl5wjW1D6KY_7ZEZVz_HJPGLUDeK9mXs"
AUTHDOMAIN = "ronan-jr-s-brain.firebaseapp.com"
PROJECTID = "ronan-jr-s-brain"
STORAGEBUCKET = "ronan-jr-s-brain.appspot.com"
MESSAGINGSENDERID = "367079247693"
APPID = "1:367079247693:web:cb031f1b79229ef1007104"
MEASUREMENTID = "G-6PQ2DEH8BV"


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

    async def setup_hook(self):  
        """Called when the bot is starting up"""  
        # Register all effect types  
        register_effects()  
         
        # Load data from database  
        await self.db.initialize()  
        await self.game_state.load(self.db)  
         
        # Search for and load files with commands  
        await self.load_extension("commands.effects")  # Load effect commands  
        await self.load_extension("commands.debug") # Load debug commands
        await self.load_extension("commands.movesets")  # Load moveset commands  
        await self.load_extension("commands.mana") #Load mana commands
        await self.load_extension("commands.combat")   # Load combat commands  
        await self.load_extension("commands.healing")  # Load healing commands  
        await self.load_extension("commands.advanced_roll") # Load dice roll commands  
        await self.load_extension("commands.skillcheck")  # Load skill check commands
        await self.load_extension("modules.menu.skill_check_handler")  # Load skill check context menus  
        await self.load_extension("commands.initiative")  # Load initiative commands  
        await self.load_extension("commands.qol")  # Load QOL commands
        await self.load_extension("commands.moves") # Load move commands
        await self.load_extension("commands.actions") # Load action commands

        # Get initiative tracker from the cog after loading  
        initiative_cog = self.get_cog('InitiativeCommands')  
        if initiative_cog:  
            self.initiative_tracker = initiative_cog.tracker

    async def on_ready(self):  
        """Called when the bot is ready"""  
        print(f'Logged in as {self.user} (ID: {self.user.id})')  
        print(f'{self.user}: ok i pull up')

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


    except Exception as e:
        logger.error(f"Error in check command: {str(e)}", exc_info=True)
        await interaction.response.send_message(
            "An error occurred while displaying character information.",
            ephemeral=True
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


@bot.command(name='stop')
@commands.is_owner()
async def stop(ctx):
    """Stops the bot and closes the process."""
    await ctx.send("Shutting down...")
    await bot.close()


if __name__ == "__main__":
    bot.run(TOKEN)