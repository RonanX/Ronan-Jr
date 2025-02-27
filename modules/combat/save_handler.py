"""
Save and load system for initiative tracking.
Allows combat state to be saved, loaded, and restored.

This updated version stores saves in Firebase rather than local files.
"""

import discord
import json
import os
import glob
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

@dataclass
class InitiativeSaveData:
    """Data structure for initiative saves"""
    name: str
    order: List[str]  # Character names in initiative order
    current_turn: int  # Index of current turn
    round_number: int
    timestamp: str
    description: Optional[str] = None

class SaveConfirmView(discord.ui.View):
    """Confirmation view for potentially destructive operations"""
    def __init__(self):
        super().__init__(timeout=60.0)
        self.value = None

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.value = True
        self.stop()

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.value = False
        self.stop()

class AutosaveView(discord.ui.View):
    """View for enabling/disabling autosave"""
    def __init__(self):
        super().__init__(timeout=60.0)
        self.value = None

    @discord.ui.button(label="Enable Autosave", style=discord.ButtonStyle.primary)
    async def enable(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        self.value = True
        self.stop()

    @discord.ui.button(label="No Thanks", style=discord.ButtonStyle.secondary)
    async def disable(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        self.value = False
        self.stop()

class SaveHandler:
    """
    Handles saving and loading of initiative states.
    Saves states to Firebase for persistent storage.
    """
    
    def __init__(self, database, logger=None):
        self.db = database
        self.autosave_enabled = False
        self.logger = logger
        
        # Reference to initiative_saves in Firebase
        self._ensure_firebase_ref()
    
    def _ensure_firebase_ref(self):
        """Ensure we have a Firebase reference for initiative saves"""
        if not hasattr(self.db, '_refs'):
            return
            
        if 'initiative_saves' not in self.db._refs:
            # Create reference if it doesn't exist
            self.db._refs['initiative_saves'] = self.db._db.reference('initiative_saves')
        
    def debug_print(self, *args, **kwargs):
        """Print debug message if available"""
        print(*args, **kwargs)
    
    def _format_save_name(self, name: str) -> str:
        """Format a name for Firebase key (lowercase, underscores)"""
        # Handle special system saves
        if name in ["quicksave", "autosave"]:
            return name
            
        # Remove special characters and spaces
        return "".join(c if c.isalnum() else "_" for c in name.lower())
    
    async def list_saves(self) -> List[Dict[str, Any]]:
        """List all available saves from Firebase"""
        self._ensure_firebase_ref()
        saves = []
        
        try:
            # Get all saves
            if 'initiative_saves' in self.db._refs:
                save_data = self.db._refs['initiative_saves'].get()
                
                # Convert to list format
                if save_data:
                    for key, data in save_data.items():
                        saves.append({
                            "name": data.get("name", key),
                            "round": data.get("round_number", 1),
                            "characters": len(data.get("order", [])),
                            "timestamp": data.get("timestamp"),
                            "description": data.get("description")
                        })
            
            # Sort by timestamp (newest first)
            saves.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return saves
        except Exception as e:
            self.debug_print(f"Error listing saves: {e}")
            return []
    
    async def save(
            self, 
            interaction: discord.Interaction,
            order: List[str],
            current_turn: int,
            round_number: int,
            name: Optional[str] = None,
            description: Optional[str] = None
        ) -> Tuple[bool, str]:
        """
        Save initiative state to Firebase
        
        Args:
            interaction: Discord interaction for response
            order: List of character names in initiative order
            current_turn: Index of current character in order
            round_number: Current round number
            name: Optional custom name for the save
            description: Optional description
            
        Returns:
            (success, save_name)
        """
        self._ensure_firebase_ref()
        try:
            # Generate save name/key
            if name:
                save_name = self._format_save_name(name)
            else:
                # Auto-generate name with timestamp
                timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                save_name = f"save_{timestamp}"
                
            # Create save data
            save_data = {
                "name": name or save_name,
                "order": order,
                "current_turn": current_turn,
                "round_number": round_number,
                "timestamp": datetime.utcnow().isoformat(),
                "description": description
            }
            
            # Save to Firebase
            if 'initiative_saves' in self.db._refs:
                self.db._refs['initiative_saves'].child(save_name).set(save_data)
                self.debug_print(f"Combat state saved to Firebase: {save_name}")
            else:
                self.debug_print("ERROR: initiative_saves reference not available")
                return False, ""
                
            # Create response embed
            embed = discord.Embed(
                title="💾 Combat State Saved",
                description=f"Saved as: **{save_data['name']}**",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="Details",
                value=(
                    f"Round: {round_number}\n"
                    f"Characters: {len(order)}\n"
                    f"Current Turn: {order[current_turn]}"
                ),
                inline=False
            )
            
            if description:
                embed.add_field(
                    name="Description",
                    value=description,
                    inline=False
                )
                
            await interaction.followup.send(embed=embed)
            return True, save_name
            
        except Exception as e:
            self.debug_print(f"Error saving initiative state: {e}")
            error_embed = discord.Embed(
                title="❌ Save Error",
                description=f"Could not save initiative state: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
            return False, ""
    
    async def quicksave(
            self,
            interaction: discord.Interaction,
            order: List[str],
            current_turn: int,
            round_number: int
        ) -> bool:
        """
        Create/update quicksave in Firebase
        
        Args:
            interaction: Discord interaction for response
            order: List of character names in initiative order
            current_turn: Index of current character in order
            round_number: Current round number
            
        Returns:
            Success flag
        """
        self._ensure_firebase_ref()
        try:
            # Create save data
            save_data = {
                "name": "Quicksave",
                "order": order,
                "current_turn": current_turn,
                "round_number": round_number,
                "timestamp": datetime.utcnow().isoformat(),
                "description": "Quick save of combat state"
            }
            
            # Save to Firebase
            if 'initiative_saves' in self.db._refs:
                self.db._refs['initiative_saves'].child("quicksave").set(save_data)
                self.debug_print(f"Quicksave saved to Firebase: {len(order)} characters, round {round_number}")
            else:
                self.debug_print("ERROR: initiative_saves reference not available")
                return False
                
            # Create response embed
            embed = discord.Embed(
                title="💾 Quicksave Created",
                description=(
                    f"Round: {round_number}\n"
                    f"Characters: {len(order)}\n"
                    f"Current Turn: {order[current_turn]}"
                ),
                color=discord.Color.green()
            )
                
            await interaction.followup.send(embed=embed)
            return True
            
        except Exception as e:
            self.debug_print(f"Error creating quicksave: {e}")
            error_embed = discord.Embed(
                title="❌ Quicksave Error",
                description=f"Could not create quicksave: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
            return False
    
    async def autosave(
            self,
            order: List[str],
            current_turn: int,
            round_number: int
        ) -> bool:
        """
        Create/update autosave in Firebase (no interaction response)
        
        Args:
            order: List of character names in initiative order
            current_turn: Index of current character in order
            round_number: Current round number
            
        Returns:
            Success flag
        """
        self._ensure_firebase_ref()
        if not self.autosave_enabled:
            return False
            
        try:
            # Create save data
            save_data = {
                "name": "Autosave",
                "order": order,
                "current_turn": current_turn,
                "round_number": round_number,
                "timestamp": datetime.utcnow().isoformat(),
                "description": "Automatic save of combat state"
            }
            
            # Save to Firebase
            if 'initiative_saves' in self.db._refs:
                self.db._refs['initiative_saves'].child("autosave").set(save_data)
                self.debug_print(f"Autosave updated in Firebase: round {round_number}")
                return True
            else:
                self.debug_print("ERROR: initiative_saves reference not available")
                return False
            
        except Exception as e:
            self.debug_print(f"Error creating autosave: {e}")
            return False
    
    async def load_save(
            self,
            interaction: discord.Interaction,
            save_name: str
        ) -> Optional[InitiativeSaveData]:
        """
        Load a saved initiative state from Firebase
        
        Args:
            interaction: Discord interaction for response
            save_name: Name of save to load
            
        Returns:
            Loaded save data or None if error
        """
        self._ensure_firebase_ref()
        try:
            # Normalize save name
            save_key = self._format_save_name(save_name)
            
            # Check for exact match first
            save_data = None
            if 'initiative_saves' in self.db._refs:
                save_data = self.db._refs['initiative_saves'].child(save_key).get()
            
            # If not found, try case-insensitive search
            if not save_data and 'initiative_saves' in self.db._refs:
                all_saves = self.db._refs['initiative_saves'].get()
                if all_saves:
                    # Look through all saves for a name match
                    for key, data in all_saves.items():
                        if data.get("name", "").lower() == save_name.lower():
                            save_data = data
                            break
            
            # If still not found, notify user
            if not save_data:
                await interaction.followup.send(
                    f"❌ `Save '{save_name}' not found` ❌",
                    ephemeral=True
                )
                return None
                
            # Create return object
            return InitiativeSaveData(
                name=save_data.get("name", save_key),
                order=save_data.get("order", []),
                current_turn=save_data.get("current_turn", 0),
                round_number=save_data.get("round_number", 1),
                timestamp=save_data.get("timestamp", ""),
                description=save_data.get("description")
            )
            
        except Exception as e:
            self.debug_print(f"Error loading save: {e}")
            error_embed = discord.Embed(
                title="❌ Load Error",
                description=f"Could not load save: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
            return None
    
    async def create_load_embed(self, save_data: InitiativeSaveData) -> discord.Embed:
        """Create embed for loaded save"""
        embed = discord.Embed(
            title="📂 Combat State Loaded",
            description=f"Loaded: **{save_data.name}**",
            color=discord.Color.blue()
        )
        
        # Format timestamp
        time_str = ""
        if save_data.timestamp:
            try:
                timestamp = datetime.fromisoformat(save_data.timestamp)
                time_str = f" (Saved {timestamp.strftime('%m/%d %I:%M %p')})"
            except (ValueError, TypeError):
                pass
                
        # Add details
        embed.add_field(
            name="Details",
            value=(
                f"Round: {save_data.round_number}{time_str}\n"
                f"Characters: {len(save_data.order)}\n"
                f"Current Turn: {save_data.order[save_data.current_turn]}"
            ),
            inline=False
        )
        
        # Add initiative order
        order_text = ""
        for i, char_name in enumerate(save_data.order):
            if i == save_data.current_turn:
                order_text += f"▶️ **{char_name}**\n"
            else:
                order_text += f"⬜ {char_name}\n"
                
        embed.add_field(
            name="Initiative Order",
            value=order_text,
            inline=False
        )
        
        # Add description if any
        if save_data.description:
            embed.add_field(
                name="Description",
                value=save_data.description,
                inline=False
            )
            
        return embed
    
    async def enable_autosave(self, interaction: discord.Interaction) -> None:
        """Ask player if they want to enable autosave"""
        view = AutosaveView()
        
        await interaction.followup.send(
            "💾 Would you like to enable autosave?\nThis will automatically save the combat state after each turn.",
            view=view,
            ephemeral=True
        )
        
        await view.wait()
        
        if view.value:
            self.autosave_enabled = True
            self.debug_print("Autosave enabled")
            await interaction.followup.send(
                "✅ `Autosave enabled` ✅",
                ephemeral=True
            )
        else:
            self.autosave_enabled = False