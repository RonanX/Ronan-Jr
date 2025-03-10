"""
Quality of Life Commands (commands/qol.py)

This file contains commands that improve user experience with the bot,
including direct message sending, customizable embeds, and art queue management.

Commands:
- /say: Sends a direct message to the channel with optional media attachments
- /embed: Creates a customizable embed that sends directly to a channel
- /artqueue: Manages an art request queue with filtering and tagging
"""

import os
import discord
from discord import app_commands
from discord.ext import commands
import re
import logging
import aiohttp
import io
import json
import datetime
from typing import Optional, List, Dict, Any, Union, Literal

logger = logging.getLogger(__name__)

class ArtQueueView(discord.ui.View):
    """Interactive view for art queue management"""
    
    def __init__(self, cog, entries, page=0, tag_filter=None, status_filter=None, ephemeral=True):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog
        self.entries = entries
        self.page = page
        self.total_pages = max(1, (len(entries) + 4) // 5)  # 5 entries per page
        self.tag_filter = tag_filter or []
        self.status_filter = status_filter
        self.ephemeral = ephemeral
        
        # Update button states
        self._update_buttons()
    
    def _update_buttons(self):
        """Update button states based on current page and filters"""
        # Disable prev button on first page
        self.prev_button.disabled = (self.page == 0)
        # Disable next button on last page
        self.next_button.disabled = (self.page >= self.total_pages - 1)
        
        # Update filter button label
        filter_label = "Filters: "
        if self.tag_filter:
            filter_label += f"{len(self.tag_filter)} tags"
        else:
            filter_label += "None"
        
        if self.status_filter:
            filter_label += f", {self.status_filter}"
            
        self.filter_button.label = filter_label
    
    async def get_current_page_embed(self):
        """Generate the embed for the current page"""
        start_idx = self.page * 5
        end_idx = min(start_idx + 5, len(self.entries))
        current_entries = self.entries[start_idx:end_idx]
        
        embed = discord.Embed(
            title="🎨 Art Request Queue", 
            description="Here are the current art requests:",
            color=discord.Color.purple()
        )
        
        # Add filters if any
        filter_text = ""
        if self.tag_filter:
            filter_text += f"Tags: {', '.join(self.tag_filter)}\n"
        if self.status_filter:
            filter_text += f"Status: {self.status_filter}\n"
            
        if filter_text:
            embed.add_field(
                name="🔍 Active Filters",
                value=filter_text,
                inline=False
            )
        
        # No entries found
        if not current_entries:
            embed.description = "No art requests found with the current filters."
            return embed
        
        # Build formatted entries
        for i, entry in enumerate(current_entries, start=1):
            # Format the entry information
            entry_text = f"**From:** {entry['from']}\n"
            entry_text += f"**To:** {entry['to']}\n"
            
            if entry['description']:
                desc_formatted = entry['description'].replace(';', '\n• ')
                entry_text += f"**Description:**\n`• {desc_formatted}`\n"
            
            if entry['tags']:
                entry_text += f"**Tags:** {', '.join(entry['tags'])}\n"
                
            entry_text += f"**Status:** {entry['status']}\n"
            
            # Add timestamps with better formatting
            entry_text += f"**Created:** {entry['timestamp']}\n"
            
            # Add last_edited timestamp if it exists
            if 'last_edited' in entry and entry['last_edited']:
                entry_text += f"**Last Edited:** {entry['last_edited']}\n"
            
            if 'reference_url' in entry and entry['reference_url']:
                ref_url = entry['reference_url']
                if ref_url.startswith('local:'):
                    # It's a local file path
                    local_path = ref_url.replace('local:', '')
                    entry_text += f"**Reference:** Local file ({os.path.basename(local_path)})\n"
                else:
                    # It's a regular URL
                    entry_text += f"**Reference:** [Link]({ref_url})\n"
            
            embed.add_field(
                name=f"#{start_idx + i}: {entry['title']} (ID: {entry['id']})",
                value=entry_text,
                inline=False
            )
        
        # Add pagination footer
        embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages} | Total: {len(self.entries)} requests")
        
        return embed
    
    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to previous page"""
        self.page = max(0, self.page - 1)
        self._update_buttons()
        
        embed = await self.get_current_page_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="➡️")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to next page"""
        self.page = min(self.total_pages - 1, self.page + 1)
        self._update_buttons()
        
        embed = await self.get_current_page_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="Filters: None", style=discord.ButtonStyle.primary, emoji="🔍")
    async def filter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open filter selection modal"""
        # Create and send the filter modal
        await interaction.response.send_modal(FilterModal(self))
    
    @discord.ui.button(label="Add Request", style=discord.ButtonStyle.success, emoji="➕")
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Add new art request"""
        # Create and send the add request modal
        await interaction.response.send_modal(AddRequestModal(self.cog))

class FilterModal(discord.ui.Modal, title="Filter Art Requests"):
    """Modal for filtering art requests"""
    
    tags = discord.ui.TextInput(
        label="Tags (comma separated)",
        placeholder="character, sketch, colored, etc.",
        required=False,
        max_length=100
    )
    
    status = discord.ui.TextInput(
        label="Status",
        placeholder="pending, in-progress, completed, etc.",
        required=False,
        max_length=20
    )
    
    def __init__(self, view):
        super().__init__()
        self.queue_view = view
        
        # Pre-populate fields with current filters
        if view.tag_filter:
            self.tags.default = ", ".join(view.tag_filter)
        
        if view.status_filter:
            self.status.default = view.status_filter
    
    async def on_submit(self, interaction: discord.Interaction):
        # Parse tag input into a list
        tag_input = self.tags.value.strip()
        if tag_input:
            tag_filter = [tag.strip().lower() for tag in tag_input.split(',') if tag.strip()]
        else:
            tag_filter = []
        
        # Get status
        status_filter = self.status.value.strip().lower() if self.status.value.strip() else None
        
        # Apply filters and refresh the queue
        filtered_entries = await self.queue_view.cog.filter_art_queue(tag_filter, status_filter)
        
        # Create a new view with the filtered results
        new_view = ArtQueueView(
            self.queue_view.cog, 
            filtered_entries, 
            page=0,  # Reset to first page
            tag_filter=tag_filter,
            status_filter=status_filter,
            ephemeral=self.queue_view.ephemeral
        )
        
        # Update the message
        embed = await new_view.get_current_page_embed()
        await interaction.response.edit_message(embed=embed, view=new_view)

class AddRequestModal(discord.ui.Modal, title="Add Art Request"):
    """Modal for adding a new art request"""
    
    def __init__(self, cog):
        super().__init__(title="Add Art Request")
        self.cog = cog
        
        # Create the TextInput fields
        self.title_input = discord.ui.TextInput(
            label="Title",
            placeholder="Brief title for your request",
            max_length=100
        )
        self.add_item(self.title_input)
        
        self.description_input = discord.ui.TextInput(
            label="Description",
            placeholder="Describe what you want; use ; for bullet points",
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.add_item(self.description_input)
        
        self.tags_input = discord.ui.TextInput(
            label="Tags (comma separated)",
            placeholder="character, sketch, colored, etc.",
            required=False,
            max_length=100
        )
        self.add_item(self.tags_input)
        
        self.to_user_input = discord.ui.TextInput(
            label="Request To",
            placeholder="Who is this request for?",
            required=True
        )
        self.add_item(self.to_user_input)
        
        self.reference_url_input = discord.ui.TextInput(
            label="Reference URL (optional)",
            placeholder="Link to reference image or materials",
            required=False
        )
        self.add_item(self.reference_url_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        # Parse inputs - getting value as strings
        tags_list = [tag.strip().lower() for tag in self.tags_input.value.split(',') if tag.strip()]
        
        # Create request object with only serializable values
        request = {
            "title": self.title_input.value,
            "description": self.description_input.value,
            "tags": tags_list,
            "from": interaction.user.name,
            "to": self.to_user_input.value,
            "status": "pending",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "reference_url": self.reference_url_input.value if self.reference_url_input.value.strip() else None
        }
        
        # Add to database
        success = await self.cog.add_art_request(request)
        
        if success:
            await interaction.response.send_message(
                f"✅ Art request '{self.title_input.value}' has been added to the queue!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Failed to add art request. Please try again later.",
                ephemeral=True
            )

class EditRequestModal(discord.ui.Modal, title="Edit Art Request"):
    """Modal for editing an art request"""
    
    def __init__(self, cog, request_data, request_id):
        super().__init__(title="Edit Art Request")
        self.cog = cog
        self.request_id = request_id
        
        # Create the TextInput fields with pre-filled data
        self.title_input = discord.ui.TextInput(
            label="Title",
            placeholder="Brief title for your request",
            max_length=100,
            default=request_data.get('title', '')
        )
        self.add_item(self.title_input)
        
        self.description_input = discord.ui.TextInput(
            label="Description",
            placeholder="Describe what you want; use ; for bullet points",
            style=discord.TextStyle.paragraph,
            required=True,
            default=request_data.get('description', '')
        )
        self.add_item(self.description_input)
        
        # Join tags with commas
        tags_str = ", ".join(request_data.get('tags', []))
        self.tags_input = discord.ui.TextInput(
            label="Tags (comma separated)",
            placeholder="character, sketch, colored, etc.",
            required=False,
            max_length=100,
            default=tags_str
        )
        self.add_item(self.tags_input)
        
        self.to_user_input = discord.ui.TextInput(
            label="Request To",
            placeholder="Who is this request for?",
            required=True,
            default=request_data.get('to', '')
        )
        self.add_item(self.to_user_input)
        
        self.reference_url_input = discord.ui.TextInput(
            label="Reference URL (optional)",
            placeholder="Link to reference image or materials",
            required=False,
            default=request_data.get('reference_url', '')
        )
        self.add_item(self.reference_url_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        # Parse inputs
        tags_list = [tag.strip().lower() for tag in self.tags_input.value.split(',') if tag.strip()]
        
        # Create update object
        updates = {
            "title": self.title_input.value,
            "description": self.description_input.value,
            "tags": tags_list,
            "to": self.to_user_input.value,
            "reference_url": self.reference_url_input.value if self.reference_url_input.value.strip() else None,
            "last_edited": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        
        # Update in database
        success = await self.cog.update_art_request(self.request_id, updates)
        
        if success:
            await interaction.response.send_message(
                f"✅ Art request '{self.title_input.value}' has been updated!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Failed to update art request. Please try again later.",
                ephemeral=True
            )

class DeleteConfirmView(discord.ui.View):
    """Confirmation view for deleting art requests"""
    
    def __init__(self, cog, request_id, request_title):
        super().__init__(timeout=60)  # 1 minute timeout
        self.cog = cog
        self.request_id = request_id
        self.request_title = request_title
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel deletion"""
        await interaction.response.edit_message(content="Deletion cancelled.", view=None)
    
    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirm deletion"""
        # Delete the request
        success = await self.cog.delete_art_request(self.request_id)
        
        if success:
            await interaction.response.edit_message(
                content=f"✅ Art request '{self.request_title}' has been deleted.",
                view=None
            )
        else:
            await interaction.response.edit_message(
                content="❌ Failed to delete the request. Please try again later.",
                view=None
            )

class QOLCommands(commands.Cog):
    """Commands for quality of life improvements"""
    
    def __init__(self, bot):
        self.bot = bot
        self.session = None
    
    async def cog_load(self):
        """Initialize the aiohttp session when the cog loads"""
        self.session = aiohttp.ClientSession()
    
    async def cog_unload(self):
        """Close the aiohttp session when the cog unloads"""
        if self.session:
            await self.session.close()
    
    async def fetch_media(self, url):
        """
        Fetches media from a URL and returns it as a file-like object.
        
        Args:
            url: The URL to fetch media from
            
        Returns:
            tuple: (filename, file_data)
        """
        if not self.session:
            self.session = aiohttp.ClientSession()
            
        async with self.session.get(url) as response:
            if response.status != 200:
                raise ValueError(f"Failed to fetch media: {response.status}")
                
            data = await response.read()
            
            # Get the filename from the URL or use a default
            content_disposition = response.headers.get('Content-Disposition')
            if content_disposition:
                filename_match = re.search(r'filename="?([^"]+)"?', content_disposition)
                if filename_match:
                    filename = filename_match.group(1)
                else:
                    filename = 'attachment'
            else:
                filename = url.split('/')[-1].split('?')[0] or 'attachment'
                
            # Add appropriate extension based on content-type if missing
            content_type = response.headers.get('Content-Type', '')
            if '.' not in filename:
                if 'image/png' in content_type:
                    filename += '.png'
                elif 'image/jpeg' in content_type or 'image/jpg' in content_type:
                    filename += '.jpg'
                elif 'image/gif' in content_type:
                    filename += '.gif'
                elif 'video/' in content_type:
                    filename += '.mp4'
                
            return filename, io.BytesIO(data)
    
    @app_commands.command(name="say", description="Makes the bot send a message with optional media")
    @app_commands.describe(
        message="The message to send (optional if media is provided)",
        channel="The channel to send the message to (defaults to current channel)"
    )
    async def say(
        self, 
        interaction: discord.Interaction, 
        message: Optional[str] = None,
        channel: Optional[discord.TextChannel] = None
    ):
        """
        Sends a message directly to the channel as the bot.
        Can include attached files directly from the command.
        
        Args:
            interaction: The interaction object
            message: The message to send (optional)
            channel: Optional channel to send the message to
        """
        try:
            # Need either a message or attached files
            if not message and not interaction.message and len(interaction.message.attachments) == 0:
                await interaction.response.send_message(
                    "Please provide a message or attach a file.",
                    ephemeral=True
                )
                return
                
            # Get target channel (current channel if not specified)
            target_channel = channel or interaction.channel
            
            # Check permissions
            if not target_channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.response.send_message(
                    f"I don't have permission to send messages in {target_channel.mention}.",
                    ephemeral=True
                )
                return
            
            # Prepare files to send
            files = []
            
            # Handle files directly attached to the command message
            if interaction.message and interaction.message.attachments:
                for attachment in interaction.message.attachments:
                    file_data = await attachment.read()
                    files.append(discord.File(io.BytesIO(file_data), filename=attachment.filename))
            
            # Send the message with any files
            if files:
                await target_channel.send(content=message, files=files)
                print(f"[/say] Sent message with {len(files)} files to #{target_channel.name}")
            else:
                await target_channel.send(content=message)
                print(f"[/say] Sent message to #{target_channel.name}")
            
            # Print the message content for logging
            print(f"[Message Content] {message if message else '[No text content]'}")
            
            # Confirm to the user (ephemeral so only they see it)
            await interaction.response.send_message(
                f"Message sent to {target_channel.mention}.",
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error in say command: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                f"An error occurred while sending the message: {str(e)}",
                ephemeral=True
            )
    
    @app_commands.command(name="embed", description="Creates a customizable embed")
    @app_commands.describe(
        title="Title of the embed",
        description="Main content of the embed (use ; for bullet points, \\n for line breaks)",
        color="Color of the embed (hex code like #FF0000 or color name like 'red')",
        channel="The channel to send the embed to (defaults to current channel)",
        header="Header text to display at the top",
        footer="Footer text to display at the bottom",
        image_url="URL of an image to include in the embed",
        thumbnail_url="URL of a thumbnail to display in the corner of the embed"
    )
    async def embed(
        self,
        interaction: discord.Interaction,
        title: str,
        description: Optional[str] = None,
        color: Optional[str] = "blue",
        channel: Optional[discord.TextChannel] = None,
        header: Optional[str] = None,
        footer: Optional[str] = None,
        image_url: Optional[str] = None,
        thumbnail_url: Optional[str] = None
    ):
        """
        Creates and sends a customizable embed directly to a channel.
        
        Args:
            interaction: The interaction object
            title: Title of the embed
            description: Main content of the embed (optional)
            color: Color of the embed (hex code or color name)
            channel: Channel to send the embed to (optional)
            header: Optional header text
            footer: Optional footer text
            image_url: Optional image URL for the main embed image
            thumbnail_url: Optional thumbnail URL
        """
        try:
            # Get target channel (current channel if not specified)
            target_channel = channel or interaction.channel
            
            # Check permissions
            if not target_channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.response.send_message(
                    f"I don't have permission to send messages in {target_channel.mention}.",
                    ephemeral=True
                )
                return
                
            # Parse the color
            embed_color = self._parse_color(color)
            
            # Create the embed
            embed = discord.Embed(
                title=title,
                color=embed_color
            )
            
            # Process the description if provided (handle formatting)
            if description:
                formatted_description = self._format_description(description)
                embed.description = formatted_description
            
            # Add header if provided
            if header:
                embed.set_author(name=header)
                
            # Add footer if provided
            if footer:
                embed.set_footer(text=footer)
                
            # Add image if provided
            if image_url:
                embed.set_image(url=image_url)
                
            # Add thumbnail if provided
            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)
            
            # Prepare files for attachments
            files = []
            if interaction.message and interaction.message.attachments:
                for attachment in interaction.message.attachments:
                    # Check if it's an image type that should be embedded
                    if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif']):
                        # If no image URL was provided, use the first image attachment in the embed
                        if not image_url and not embed.image.url:
                            embed.set_image(url=attachment.url)
                            continue
                    
                    # For non-image files or additional images, add them as attachments
                    file_data = await attachment.read()
                    files.append(
                        discord.File(io.BytesIO(file_data), filename=attachment.filename)
                    )
            
            # Send the embed directly to the channel
            await target_channel.send(embed=embed, files=files if files else None)
            
            # Print command info for logging
            print(f"[/embed] Sent embed to #{target_channel.name} with title: {title}")
            print(f"[Embed Content] {description if description else '[No description]'}")
            if files:
                print(f"[Embed Files] Attached {len(files)} files")
            
            # Confirm to the user (ephemeral so only they see it)
            await interaction.response.send_message(
                f"Embed sent to {target_channel.mention}.",
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error in embed command: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                f"An error occurred while creating the embed: {str(e)}",
                ephemeral=True
            )
    
    def _parse_color(self, color_str: str) -> discord.Color:
        """
        Parse a color string into a discord.Color object.
        
        Args:
            color_str: A color string (hex code or name)
            
        Returns:
            discord.Color: The parsed color
        """
        # Remove # from hex if present
        if color_str.startswith('#'):
            color_str = color_str[1:]
            
        # Try parsing as hex
        try:
            if len(color_str) == 6:
                return discord.Color.from_rgb(
                    int(color_str[0:2], 16),
                    int(color_str[2:4], 16),
                    int(color_str[4:6], 16)
                )
        except ValueError:
            pass
            
        # Try parsing as named color
        color_map = {
            "red": discord.Color.red(),
            "blue": discord.Color.blue(),
            "green": discord.Color.green(),
            "yellow": discord.Color.yellow(),
            "orange": discord.Color.orange(),
            "purple": discord.Color.purple(),
            "teal": discord.Color.teal(),
            "magenta": discord.Color.magenta(),
            "gold": discord.Color.gold(),
            "dark_red": discord.Color.dark_red(),
            "dark_blue": discord.Color.dark_blue(),
            "dark_green": discord.Color.dark_green(),
            "dark_teal": discord.Color.dark_teal(),
            "dark_purple": discord.Color.dark_purple(),
            "dark_orange": discord.Color.dark_orange(),
            "dark_gold": discord.Color.dark_gold(),
            "dark_magenta": discord.Color.dark_magenta(),
            "blurple": discord.Color.blurple(),
            "greyple": discord.Color.greyple(),
            "light_grey": discord.Color.light_grey(),
            "dark_grey": discord.Color.dark_grey(),
            "black": discord.Color.default(),
            "white": discord.Color.from_rgb(255, 255, 255)
        }
        
        return color_map.get(color_str.lower(), discord.Color.blue())
    
    def _format_description(self, description: str) -> str:
        """
        Format the description with bullet points and line breaks.
        
        Args:
            description: The raw description string
            
        Returns:
            str: The formatted description
        """
        # Replace literal \n with actual newlines
        description = description.replace('\\n', '\n')
        
        # Process semicolons as bullet points
        if ';' in description:
            parts = description.split(';')
            formatted_parts = []
            
            for part in parts:
                part = part.strip()
                if part:
                    formatted_parts.append(f"`• {part}`")
            
            return '\n'.join(formatted_parts)
        
        return description
    
    #
    # Art Queue Commands
    #
    
    async def initialize_art_queue(self):
        """Initialize the art queue in the database if it doesn't exist"""
        if not hasattr(self.bot, 'db') or not self.bot.db:
            logger.error("Database not initialized for art queue")
            return False
            
        try:
            # Initialize art_queue reference if it doesn't exist
            if 'art_queue' not in self.bot.db._refs:
                self.bot.db._refs['art_queue'] = self.bot.db._db.child('art_queue')
                self.bot.db._refs['art_queue_tags'] = self.bot.db._db.child('art_queue_tags')
                print("Art queue database references initialized")
            
            return True
        except Exception as e:
            logger.error(f"Failed to initialize art queue: {str(e)}", exc_info=True)
            return False
    
    async def get_all_art_requests(self) -> List[Dict[str, Any]]:
        """Get all art requests from the database"""
        if not await self.initialize_art_queue():
            return []
            
        try:
            # Get all requests
            requests_data = self.bot.db._refs['art_queue'].get()
            
            if not requests_data:
                return []
                
            # Convert to list format
            requests_list = []
            for request_id, request in requests_data.items():
                request['id'] = request_id
                requests_list.append(request)
                
            # Sort by timestamp (newest first)
            requests_list.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            
            return requests_list
        except Exception as e:
            logger.error(f"Failed to get art requests: {str(e)}", exc_info=True)
            return []
    
    async def get_all_tags(self) -> List[str]:
        """Get all unique tags used in art requests"""
        if not await self.initialize_art_queue():
            return []
            
        try:
            # Get tags from the dedicated tags collection
            tags_data = self.bot.db._refs['art_queue_tags'].get()
            
            if not tags_data:
                return []
                
            return list(tags_data.keys())
        except Exception as e:
            logger.error(f"Failed to get art tags: {str(e)}", exc_info=True)
            return []
    
    async def add_art_request(self, request: Dict[str, Any]) -> bool:
        """
        Add a new art request to the database
        
        Args:
            request: Dictionary containing request data
            
        Returns:
            bool: Success status
        """
        if not await self.initialize_art_queue():
            return False
            
        try:
            # Push the new request to get a unique ID
            new_ref = self.bot.db._refs['art_queue'].push()
            new_ref.set(request)
            request_id = new_ref.key
            
            print(f"[/artqueue] Added new request: {request['title']} (ID: {request_id})")
            
            # Update tags collection
            for tag in request.get('tags', []):
                self.bot.db._refs['art_queue_tags'].child(tag.lower()).set(True)
                
            return True
        except Exception as e:
            logger.error(f"Failed to add art request: {str(e)}", exc_info=True)
            return False
    
    async def update_art_request(self, request_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update an existing art request
        
        Args:
            request_id: ID of the request to update
            updates: Dictionary of fields to update
            
        Returns:
            bool: Success status
        """
        if not await self.initialize_art_queue():
            return False
            
        try:
            # Update the request
            self.bot.db._refs['art_queue'].child(request_id).update(updates)
            
            print(f"[/artqueue] Updated request: {request_id}")
            
            # If tags were updated, update tags collection
            if 'tags' in updates:
                for tag in updates['tags']:
                    self.bot.db._refs['art_queue_tags'].child(tag.lower()).set(True)
                    
            return True
        except Exception as e:
            logger.error(f"Failed to update art request: {str(e)}", exc_info=True)
            return False
    
    async def delete_art_request(self, request_id: str) -> bool:
        """
        Delete an art request
        
        Args:
            request_id: ID of the request to delete
            
        Returns:
            bool: Success status
        """
        if not await self.initialize_art_queue():
            return False
            
        try:
            # Delete the request
            self.bot.db._refs['art_queue'].child(request_id).delete()
            
            print(f"[/artqueue] Deleted request: {request_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete art request: {str(e)}", exc_info=True)
            return False
    
    async def filter_art_queue(self, tags: List[str] = None, status: str = None) -> List[Dict[str, Any]]:
        """
        Filter art requests by tags and status
        
        Args:
            tags: List of tags to filter by (AND logic - must have all)
            status: Status to filter by
            
        Returns:
            List of filtered requests
        """
        # Get all requests
        all_requests = await self.get_all_art_requests()
        
        # No filters, return all
        if not tags and not status:
            return all_requests
            
        # Apply filters
        filtered_requests = []
        
        for request in all_requests:
            # Status filter
            if status and request.get('status', '').lower() != status.lower():
                continue
                
            # Tags filter (must have ALL specified tags)
            if tags:
                request_tags = [tag.lower() for tag in request.get('tags', [])]
                if not all(tag.lower() in request_tags for tag in tags):
                    continue
                    
            # Passed all filters
            filtered_requests.append(request)
            
        return filtered_requests
    
    # Art Queue command group
    artqueue = app_commands.Group(
        name="artqueue", 
        description="Manage the art request queue"
    )
    
    @artqueue.command(name="show", description="View the art request queue")
    @app_commands.describe(
        tag_filter="Filter by tags (comma separated)",
        status="Filter by status",
        ephemeral="Whether to show the queue privately or to everyone"
    )
    async def art_queue_show(
        self, 
        interaction: discord.Interaction, 
        tag_filter: Optional[str] = None,
        status: Optional[str] = None,
        ephemeral: Optional[bool] = True
    ):
        """Display the art request queue with optional filtering"""
        await interaction.response.defer(ephemeral=ephemeral)
        
        # Run cleanup of old completed requests
        deleted_count = await self.cleanup_old_completed_requests()
        if deleted_count > 0:
            print(f"[/artqueue show] Auto-cleanup removed {deleted_count} old completed requests")
        
        # Parse tag filter
        tags = []
        if tag_filter:
            tags = [tag.strip().lower() for tag in tag_filter.split(',') if tag.strip()]
        
        # Get filtered requests
        requests = await self.filter_art_queue(tags, status)
        
        # Create view and embed
        view = ArtQueueView(
            self, 
            requests, 
            tag_filter=tags, 
            status_filter=status,
            ephemeral=ephemeral
        )
        
        # Get the embed for the first page
        embed = await view.get_current_page_embed()
        
        # Send the message
        await interaction.followup.send(embed=embed, view=view, ephemeral=ephemeral)
        
        print(f"[/artqueue show] Displayed queue with {len(requests)} entries")
        if tags:
            print(f"[/artqueue show] Tag filters: {', '.join(tags)}")
        if status:
            print(f"[/artqueue show] Status filter: {status}")
    
    async def cleanup_old_completed_requests(self):
        """Delete completed requests that are older than 10 days"""
        try:
            # Get all requests
            all_requests = await self.get_all_art_requests()
            current_time = datetime.datetime.now()
            deleted_count = 0
            
            for request in all_requests:
                # Only process completed requests
                if request.get('status', '').lower() != 'completed':
                    continue
                    
                # Parse the timestamp
                try:
                    # Get either last_edited (if exists) or timestamp
                    date_str = request.get('last_edited', request.get('timestamp', ''))
                    if not date_str:
                        continue
                        
                    request_date = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                    
                    # Calculate days since completion
                    days_since = (current_time - request_date).days
                    
                    # Delete if older than 10 days
                    if days_since >= 10:
                        # Delete local file if exists
                        reference_url = request.get('reference_url')
                        if reference_url and reference_url.startswith('local:'):
                            try:
                                local_path = reference_url.replace('local:', '')
                                if os.path.exists(local_path):
                                    os.remove(local_path)
                                    print(f"[Auto-cleanup] Removed local file: {local_path}")
                            except Exception as e:
                                print(f"[Auto-cleanup] Error removing file: {str(e)}")
                        
                        # Delete request
                        await self.delete_art_request(request.get('id'))
                        deleted_count += 1
                        print(f"[Auto-cleanup] Deleted completed request {request.get('id')} ({days_since} days old)")
                
                except (ValueError, TypeError) as e:
                    print(f"[Auto-cleanup] Error parsing date: {str(e)}")
                    continue
                    
            if deleted_count > 0:
                print(f"[Auto-cleanup] Deleted {deleted_count} completed requests older than 10 days")
                
            return deleted_count
        
        except Exception as e:
            logger.error(f"Error in auto-cleanup: {str(e)}", exc_info=True)
            return 0

    @artqueue.command(name="add", description="Add a new art request")
    @app_commands.describe(
        attachment="Upload a reference image or material (optional)"
    )
    async def art_queue_add(
        self, 
        interaction: discord.Interaction,
        attachment: Optional[discord.Attachment] = None
    ):
        """Add a new art request with optional attachment"""
        # Debug print to verify attachment is received
        if attachment:
            print(f"[/artqueue add] Received attachment: {attachment.filename} ({attachment.size} bytes)")
        
        # Get attachment info
        attachment_url = None
        local_path = None
        
        # Save attachment locally if provided
        if attachment:
            try:
                # Save to local storage
                local_path = await self.save_attachment_locally(attachment, str(interaction.user.id))
                
                # Use Discord CDN as fallback if local save fails
                if local_path:
                    attachment_url = f"local:{local_path}"
                    print(f"[/artqueue add] Saved to local path: {local_path}")
                else:
                    attachment_url = attachment.url
                    print(f"[/artqueue add] Using CDN URL: {attachment.url}")
            except Exception as e:
                print(f"[/artqueue add] Error handling attachment: {str(e)}")
                attachment_url = attachment.url
        
        # Send the modal with the attachment info
        modal = AddRequestModal(self)
        
        # If we have an attachment URL, set it in the modal
        if attachment_url:
            # Pre-fill the reference URL field with the attachment URL or local path
            for child in modal.children:
                if child.label == "Reference URL (optional)":
                    child.default = attachment_url
                    break
        
        await interaction.response.send_modal(modal)
        print(f"[/artqueue add] {interaction.user.name} opened add request modal")
    
    async def save_attachment_locally(self, attachment, user_id):
        """
        Downloads an attachment and saves it to a local folder
        
        Args:
            attachment: Discord attachment object
            user_id: ID of the user who uploaded it
            
        Returns:
            str: Local path to the saved file
        """
        try:
            # Create assets directory if it doesn't exist
            assets_dir = "assets/art_references"
            os.makedirs(assets_dir, exist_ok=True)
            
            # Create user directory if it doesn't exist
            user_dir = f"{assets_dir}/{user_id}"
            os.makedirs(user_dir, exist_ok=True)
            
            # Generate a filename with timestamp to avoid collisions
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{attachment.filename}"
            filepath = f"{user_dir}/{filename}"
            
            # Download the file content
            file_data = await attachment.read()
            
            # Write the file locally
            with open(filepath, 'wb') as f:
                f.write(file_data)
            
            print(f"[/artqueue] Saved attachment to {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"Error saving attachment: {str(e)}", exc_info=True)
            print(f"Failed to save attachment: {str(e)}")
            return None

    async def upload_to_firebase(self, file_data, filename, user_id):
        """Upload a file to Firebase Storage"""
        # This requires Firebase Storage configuration
        
        try:
            # The bot needs to be configured with Firebase Storage
            storage_bucket = self.bot.firebase_app.storage().bucket()
            
            # Create a unique path for the file
            file_path = f"art_references/{user_id}/{filename}"
            
            # Upload the file
            blob = storage_bucket.blob(file_path)
            blob.upload_from_string(
                file_data,
                content_type=self._get_content_type(filename)
            )
            
            # Make the file publicly accessible and get the URL
            blob.make_public()
            return blob.public_url
        
        except Exception as e:
            logger.error(f"Error uploading to Firebase: {str(e)}", exc_info=True)
            return None
        
    def _get_content_type(self, filename):
        """Get the content type based on file extension"""
        extension = filename.lower().split('.')[-1]
        content_types = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'mp4': 'video/mp4',
            'mov': 'video/quicktime',
            'pdf': 'application/pdf'
        }
        return content_types.get(extension, 'application/octet-stream')

    @artqueue.command(name="edit", description="Edit an existing art request")
    @app_commands.describe(
        id="ID of the request to edit",
        attachment="New reference image or material (optional)"
    )
    async def art_queue_edit(
        self,
        interaction: discord.Interaction,
        id: str,
        attachment: Optional[discord.Attachment] = None
    ):
        """Edit an existing art request with optional new attachment"""
        # Get all requests
        all_requests = await self.get_all_art_requests()
        
        # Find the request by ID
        found_request = None
        for request in all_requests:
            if request.get('id') == id:
                found_request = request
                break
        
        if not found_request:
            await interaction.response.send_message(
                f"❌ Request with ID '{id}' not found.",
                ephemeral=True
            )
            return
        
        # Check if user is authorized to edit (either the requester or the artist)
        if interaction.user.name != found_request.get('from') and interaction.user.name != found_request.get('to'):
            await interaction.response.send_message(
                "❌ You can only edit requests that you created or are assigned to you.",
                ephemeral=True
            )
            return
        
        # Handle new attachment if provided
        if attachment:
            # Save locally
            local_path = await self.save_attachment_locally(attachment, interaction.user.id)
            
            if local_path:
                # Update reference URL in the request data
                found_request['reference_url'] = f"local:{local_path}"
                print(f"[/artqueue edit] Updated reference to {local_path}")
            else:
                # Fall back to Discord CDN
                found_request['reference_url'] = attachment.url
                print(f"[/artqueue edit] Updated reference to CDN URL: {attachment.url}")
        
        # Open edit modal
        modal = EditRequestModal(self, found_request, id)
        await interaction.response.send_modal(modal)
        print(f"[/artqueue edit] Opened edit modal for request {id}")

    @artqueue.command(name="delete", description="Delete an art request")
    @app_commands.describe(
        id="ID of the request to delete"
    )
    async def art_queue_delete(
        self,
        interaction: discord.Interaction,
        id: str
    ):
        """Delete an art request after confirmation"""
        await interaction.response.defer(ephemeral=True)
        
        # Get all requests
        all_requests = await self.get_all_art_requests()
        
        # Find the request by ID
        found_request = None
        for request in all_requests:
            if request.get('id') == id:
                found_request = request
                break
        
        if not found_request:
            await interaction.followup.send(
                f"❌ Request with ID '{id}' not found.",
                ephemeral=True
            )
            return
        
        # Check if user is authorized to delete (only the requester can delete)
        if interaction.user.name != found_request.get('from'):
            await interaction.followup.send(
                "❌ You can only delete requests that you created.",
                ephemeral=True
            )
            return
        
        # Show confirmation
        view = DeleteConfirmView(self, id, found_request.get('title'))
        await interaction.followup.send(
            f"⚠️ Are you sure you want to delete the request '{found_request.get('title')}'?",
            view=view,
            ephemeral=True
        )
        
        # If there's a local reference file, clean it up when deleting
        reference_url = found_request.get('reference_url')
        if reference_url and reference_url.startswith('local:'):
            local_path = reference_url.replace('local:', '')
            try:
                os.remove(local_path)
                print(f"[/artqueue delete] Removed local file: {local_path}")
            except Exception as e:
                print(f"[/artqueue delete] Failed to remove local file: {str(e)}")

    @artqueue.command(name="tags", description="List all available tags")
    async def art_queue_tags(self, interaction: discord.Interaction):
        """Show all tags that have been used in art requests"""
        await interaction.response.defer(ephemeral=True)
        
        # Get all tags
        tags = await self.get_all_tags()
        
        if not tags:
            await interaction.followup.send(
                "No tags found in the art queue yet.",
                ephemeral=True
            )
            return
            
        # Create embed
        embed = discord.Embed(
            title="🏷️ Art Queue Tags",
            description="These tags can be used to filter art requests:",
            color=discord.Color.blue()
        )
        
        # Group tags alphabetically
        tags.sort()
        tag_groups = []
        current_group = []
        
        for tag in tags:
            current_group.append(tag)
            if len(current_group) >= 10:
                tag_groups.append(current_group)
                current_group = []
                
        if current_group:
            tag_groups.append(current_group)
            
        # Add fields for each group
        for i, group in enumerate(tag_groups, start=1):
            embed.add_field(
                name=f"Tags Group {i}",
                value=", ".join(f"`{tag}`" for tag in group),
                inline=False
            )
            
        # Add usage info
        embed.add_field(
            name="How to use tags",
            value="When filtering the queue, you can specify multiple tags separated by commas. "
                  "Only requests that have ALL specified tags will be shown.",
            inline=False
        )
        
        embed.set_footer(text=f"Total: {len(tags)} tags")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        print(f"[/artqueue tags] Listed {len(tags)} tags")
    
    @artqueue.command(name="update", description="Update the status of an art request")
    @app_commands.describe(
        id="ID number of the request (as shown in the queue)",
        status="New status (pending, in-progress, completed, etc.)"
    )
    async def art_queue_update(
        self,
        interaction: discord.Interaction,
        id: str,
        status: str
    ):
        """Update the status of an art request"""
        await interaction.response.defer(ephemeral=True)
        
        # Get all requests
        all_requests = await self.get_all_art_requests()
        
        # Find the request with matching ID
        found = False
        request_id = None
        
        for request in all_requests:
            if request.get('id') == id:
                request_id = id
                found = True
                break
                
        if not found:
            await interaction.followup.send(
                f"❌ Request with ID '{id}' not found.",
                ephemeral=True
            )
            return
            
        # Update the status
        success = await self.update_art_request(request_id, {"status": status})
        
        if success:
            await interaction.followup.send(
                f"✅ Updated request {id} to status: {status}",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ Failed to update the request. Please try again later.",
                ephemeral=True
            )

    @artqueue.command(name="help", description="Get help with the art queue commands")
    async def art_queue_help(self, interaction: discord.Interaction):
        """Show help information for art queue commands"""
        embed = discord.Embed(
            title="🎨 Art Queue Help",
            description="The art queue system allows you to manage art requests for your server.",
            color=discord.Color.purple()
        )
        
        # Add command descriptions
        embed.add_field(
            name="/artqueue show",
            value="View the art request queue. You can filter by tags and status.\n"
                  "Example: `/artqueue show tag_filter:portrait,colored status:pending`",
            inline=False
        )
        
        embed.add_field(
            name="/artqueue add",
            value="Add a new art request to the queue. Opens a form where you can enter details.",
            inline=False
        )
        
        embed.add_field(
            name="/artqueue tags",
            value="List all available tags that have been used in art requests.",
            inline=False
        )
        
        embed.add_field(
            name="/artqueue update",
            value="Update the status of an existing request.\n"
                  "Example: `/artqueue update id:12345 status:in-progress`",
            inline=False
        )
        
        # Tag usage
        embed.add_field(
            name="Using Tags",
            value="• Tags help categorize art requests\n"
                  "• Add multiple tags separated by commas\n"
                  "• Filter the queue by one or more tags\n"
                  "• Common tags include: `character`, `portrait`, `sketch`, `colored`, etc.",
            inline=False
        )
        
        # Status info
        embed.add_field(
            name="Request Status",
            value="• `pending`: Not yet started\n"
                  "• `in-progress`: Currently being worked on\n"
                  "• `completed`: Finished artwork\n"
                  "• `rejected`: Request declined\n"
                  "• `on-hold`: Temporarily paused",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        print(f"[/artqueue help] Displayed help information")

async def setup(bot):
    """Add the cog to the bot"""
    await bot.add_cog(QOLCommands(bot))
    print("QOL commands loaded")