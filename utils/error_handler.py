"""Error handling utilities for the bot."""

import discord
from discord import app_commands
import logging
import re

logger = logging.getLogger(__name__)

class ErrorTranslator:
    @staticmethod
    def translate_error(error):
        """Converts Python errors into human-readable messages."""
        error_type = type(error).__name__
        error_msg = str(error)
        
        error_translations = {
            # Async/Coroutine Related Errors
            "RuntimeError": {
                "pattern": "coroutine '(.+)' was never awaited",
                "translation": "Hey! We forgot to 'await' an async function. This usually happens when we forget to put 'await' before things like 'ctx.send()' or 'interaction.response.send_message()'"
            },
            "NotFound": {
                "pattern": "404 Not Found",
                "translation": "Discord couldn't find what we're looking for. This usually means we tried to edit or respond to a message that's too old or has been deleted."
            },
            "Forbidden": {
                "pattern": "403 Forbidden",
                "translation": "The bot doesn't have permission to do this action. Check the bot's role permissions in your server settings."
            },
            "HTTPException": {
                "pattern": "(.+)",
                "translation": "There was an issue communicating with Discord. This could be because the message is too long, or Discord is having issues."
            },
            "InteractionResponded": {
                "pattern": "(.+)",
                "translation": "We tried to respond to a slash command more than once. Remember, you can only use interaction.response.send_message() once - after that, use interaction.followup.send()"
            },
            "ClientException": {
                "pattern": "(.+)",
                "translation": "Something went wrong with the Discord connection. This might be because we tried to do something in the wrong order."
            },
            "CommandInvokeError": {
                "pattern": "(.+)",
                "translation": "The command started but ran into a problem. Check the error details below for more info."
            },
            "MissingPermissions": {
                "pattern": "(.+)",
                "translation": "The bot is missing some Discord permissions it needs. Check the bot's role permissions in your server."
            },
            "BotMissingPermissions": {
                "pattern": "(.+)",
                "translation": "The bot needs more permissions to do this. Make sure the bot's role has the right permissions in your server settings."
            },
            "MissingRequiredArgument": {
                "pattern": "(.+) is a required argument that is missing",
                "translation": "A required piece of information is missing. Make sure you've included all the necessary parts of the command."
            },
            "CommandOnCooldown": {
                "pattern": "(.+)",
                "translation": "This command is on cooldown. Please wait a bit before trying again."
            },
            "DisabledCommand": {
                "pattern": "(.+)",
                "translation": "This command is currently disabled."
            },
            "MaxConcurrencyReached": {
                "pattern": "(.+)",
                "translation": "Too many people are using this command right now. Please wait a moment and try again."
            },
            "ExtensionError": {
                "pattern": "(.+)",
                "translation": "There was a problem with one of the bot's extensions or cogs. This is usually a code issue that needs fixing."
            },
            "BadArgument": {
                "pattern": "(.+)",
                "translation": "One of the command arguments wasn't in the right format. Double-check what you're typing!"
            },
            "BadUnionArgument": {
                "pattern": "(.+)",
                "translation": "One of the command arguments wasn't in any of the accepted formats. Check the command help for what types of input are allowed."
            },
            "PrivateMessageOnly": {
                "pattern": "(.+)",
                "translation": "This command can only be used in private messages with the bot."
            },
            "NoPrivateMessage": {
                "pattern": "(.+)",
                "translation": "This command cannot be used in private messages, only in servers."
            },
            "NSFWChannelRequired": {
                "pattern": "(.+)",
                "translation": "This command can only be used in age-restricted channels."
            },
            "CheckFailure": {
                "pattern": "(.+)",
                "translation": "You don't have permission to use this command, or a check failed."
            },
            "ConversionError": {
                "pattern": "(.+)",
                "translation": "Couldn't convert one of your inputs to the right format. Check what type of input the command needs!"
            },
            "UnexpectedQuoteError": {
                "pattern": "(.+)",
                "translation": "There's an issue with quotation marks in your command. Make sure all quotes are properly closed!"
            },
            "InvalidEndOfQuotedStringError": {
                "pattern": "(.+)",
                "translation": "There's something wrong after a quoted section in your command. Make sure to use spaces between quoted sections!"
            },
            "ExpectedClosingQuoteError": {
                "pattern": "(.+)",
                "translation": "A quote in your command wasn't closed. Make sure all quotes have both opening and closing marks!"
            },
            "ReferenceError": {
                "pattern": "(.+)",
                "translation": "We're trying to use something that doesn't exist anymore. This usually happens when trying to reference deleted messages or old data."
            },
            "TimeoutError": {
                "pattern": "(.+)",
                "translation": "The operation took too long and timed out. This might be because Discord is slow or the bot is overloaded."
            },
            "asyncio.TimeoutError": {
                "pattern": "(.+)",
                "translation": "Waited too long for something to happen (like a button click or message response). The operation has been cancelled."
            },
            "NameError": {
                "pattern": "name '(.+)' is not defined",
                "translation": "Oops! Looks like we're trying to use something that doesn't exist yet. The thing we're looking for is '{}'."
            },
            "TypeError": {
                "pattern": "sequence item \\d+: expected str instance, (\\w+) found",
                "translation": "Oops! We're trying to combine strings with other types of data. Found a {} where we expected text. This usually happens when joining messages together."
            },
            "TypeError_Generic": {
                "pattern": "(.+)",
                "translation": "Whoops! We tried to do something with the wrong type of data. For example, trying to add a number to text."
            },
            "ValueError": {
                "pattern": "(.+)",
                "translation": "The value we're trying to use isn't valid. For example, trying to convert 'hello' into a number."
            },
            "AttributeError": {
                "pattern": "'(.+)' object has no attribute '(.+)'",
                "translation": "We're trying to use a feature that doesn't exist. It's like trying to find a 'sunroof' on a bicycle."
            },
            "KeyError": {
                "pattern": "(.+)",
                "translation": "We're trying to find something that doesn't exist in our data, like looking for a 'Z' in 'ABC'."
            },
            "IndexError": {
                "pattern": "(.+)",
                "translation": "We're trying to access a position in a list that doesn't exist, like trying to get the 5th item from a list of 3 items."
            },
            "SyntaxError": {
                "pattern": "(.+)",
                "translation": "There's a typo or incorrect format in the code. It's like having a grammatical error in a sentence."
            },
            "ZeroDivisionError": {
                "pattern": "(.+)",
                "translation": "We tried to divide by zero, which is a mathematical no-no!"
            }
        }

        # Get the translation template for this error type
        translation = error_translations.get(error_type, {
            "pattern": "(.+)",
            "translation": "An unexpected error occurred: {}"
        })

        match = re.search(translation["pattern"], error_msg)
        if match:
            # Format the translation with the captured groups
            return translation["translation"].format(*match.groups())
        
        # Fallback to a generic message with the original error
        return f"Something went wrong: {error_msg}"

    @staticmethod
    def format_async_error(error):
        """Special formatter for async/coroutine errors with examples."""
        if "coroutine" in str(error):
            return (
                "\n🔄 Async Error Helper:\n"
                "=" * 50 + "\n"
                "📌 Common fixes:\n"
                "1. Add 'await' before Discord operations like:\n"
                "   - await ctx.send('message')\n"
                "   - await interaction.response.send_message('message')\n"
                "   - await message.delete()\n\n"
                "2. If using buttons/modals, make sure to:\n"
                "   - await interaction.response.send_modal(MyModal())\n"
                "   - await interaction.response.defer()\n"
                "   before sending followup messages\n\n"
                "3. For multiple messages, use:\n"
                "   - First message: await interaction.response.send_message()\n"
                "   - Later messages: await interaction.followup.send()\n"
                "=" * 50
            )
        return None

    @staticmethod
    def format_for_console(error, context=""):
        """Formats the error message for console output with optional context."""
        friendly_message = ErrorTranslator.translate_error(error)
        
        console_message = [
            "\n🔍 Error Breakdown:",
            "=" * 50,
            f"📌 What Happened: {friendly_message}",
            f"🔧 Technical Details: {type(error).__name__}: {str(error)}"
        ]
        
        if context:
            console_message.append(f"📋 Context: {context}")
            
        console_message.append("=" * 50)
        
        return "\n".join(console_message)

async def handle_error(interaction: discord.Interaction, error: Exception) -> None:
    """Handle errors during command execution - specifically for interaction-based commands"""
    friendly_message = ErrorTranslator.translate_error(error)
    logger.error(ErrorTranslator.format_for_console(error, f"Command: {interaction.command.name if interaction.command else 'Unknown'}"))
    
    error_embed = discord.Embed(
        title="🔧 Oops! Something went wrong",
        description=friendly_message,
        color=discord.Color.red()
    )
    
    if interaction.command:
        error_embed.add_field(
            name="Command",
            value=f"`/{interaction.command.name}`",
            inline=False
        )

    if interaction.response.is_done():
        await interaction.followup.send(embed=error_embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=error_embed, ephemeral=True)

# Example error handler for the bot
async def handle_command_error(ctx, error, command_name=None):
    """General error handler for traditional bot commands"""
    context = f"Command: {command_name}" if command_name else "Unknown command"
    
    # Log the user-friendly error message to console
    print(ErrorTranslator.format_for_console(error, context))
    
    # If it's an async error, also show the async helper
    async_help = ErrorTranslator.format_async_error(error)
    if async_help:
        print(async_help)
    
    # Send a friendly message to the user
    friendly_message = ErrorTranslator.translate_error(error)
    error_embed = discord.Embed(
        title="🔧 Oops! Something went wrong",
        description=friendly_message,
        color=discord.Color.red()
    )
    
    if command_name:
        error_embed.add_field(
            name="Command",
            value=f"`/{command_name}`",
            inline=False
        )
    
    await ctx.send(embed=error_embed)

def setup(bot):
    @bot.event 
    async def on_command_error(ctx, error):
        await handle_command_error(ctx, error, ctx.command.name if ctx.command else None)
        
    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_command_error(interaction, error, interaction.command.name if interaction.command else None)