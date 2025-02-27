"""
Message Formatting Utilities (src/utils/formatting.py)

This file contains utility functions for formatting messages and embeds in a consistent
way across the bot. All user-facing text formatting should use these utilities.

Key Features:
- Stat block formatting
- Resource bar formatting (HP/MP)
- Effect list formatting
- Skill list formatting
- Discord embed creation helpers

When to Modify:
- Changing how information is displayed to users
- Adding new types of formatted messages
- Updating emoji usage in messages
- Modifying embed layouts
- Adding new formatting utilities

Dependencies:
- discord.py for Embed creation
- constants.py for emoji mappings

IMPLEMENTATION MANDATES:
- Never use raw backticks in effect messages
- All formatting methods must be unicode-safe
- Use EMOJI_MAP for consistent emoji usage
- Complex messages should use bullet points
- Always use format_modifier() for stat changes
- Keep formatting consistent between embeds and text
"""

from typing import Dict, List, Optional, Union
from discord import Embed
from .constants import EMOJI_MAP

def format_modifier(value: int) -> str:
    """Format a stat modifier with proper sign"""
    return f"+{value}" if value >= 0 else str(value)

def format_stat_block(stats: Dict[str, int], mods: Dict[str, int]) -> str:
    """Format a block of stats with their modifiers"""
    lines = []
    for stat, value in stats.items():
        mod = mods.get(stat, 0)
        lines.append(f"{stat.capitalize()}: {value} ({format_modifier(mod)})")
    return "\n".join(lines)

def format_resources(current: int, maximum: int, emoji: str = "") -> str:
    """Format a resource bar (HP/MP)"""
    emoji = EMOJI_MAP.get(emoji.lower(), emoji)
    return f"{emoji}`{current}/{maximum}`"

def format_skill_list(skills: Dict[str, int]) -> str:
    """Format a character's skill list"""
    lines = []
    for skill, modifier in sorted(skills.items()):
        lines.append(f"{skill.replace('_', ' ').title()}: {format_modifier(modifier)}")
    return "\n".join(lines)

def format_effect_list(effects: List[Dict]) -> str:
    """Format a list of active effects"""
    if not effects:
        return "No active effects"
    
    lines = []
    for effect in effects:
        effect_type = effect.get('type', 'unknown')
        emoji = EMOJI_MAP.get(effect_type, '✨')
        duration = effect.get('duration', 'Permanent')
        description = effect.get('description', '')
        
        if isinstance(duration, int):
            duration = f"{duration} turn(s)"
            
        lines.append(f"{emoji} **{effect.get('name', effect_type)}** ({duration})")
        if description:
            lines.append(f"  └ {description}")
            
    return "\n".join(lines)

def create_character_embed(character) -> Embed:
    """Create a detailed character stats embed"""
    embed = Embed(title=f"{character.name}'s Stats", color=0x7289da)
    
    # Core resources
    resources = (
        f"{format_resources(character.resources.current_hp, character.resources.max_hp, 'hp')}\n"
        f"{format_resources(character.resources.current_mp, character.resources.max_mp, 'mp')}"
    )
    if character.resources.current_temp_hp:
        resources += f"\n{format_resources(character.resources.current_temp_hp, character.resources.max_temp_hp, 'shield')}"
    embed.add_field(name="Resources", value=resources, inline=True)
    
    # Combat stats
    combat_stats = f"🛡️ AC: {character.defense.current_ac}"
    if character.defense.current_ac != character.defense.base_ac:
        combat_stats += f" (Base: {character.defense.base_ac})"
    embed.add_field(name="Combat", value=combat_stats, inline=True)
    
    # Core stats with modifiers
    stats_text = format_stat_block(character.stats.base, {
        stat: character.stats.get_modifier(stat)
        for stat in character.stats.base.keys()
    })
    embed.add_field(name="Ability Scores", value=stats_text, inline=False)
    
    # Skills with proficiencies
    if hasattr(character, 'skills'):
        skills_text = format_skill_list(character.skills)
        embed.add_field(name="Skills", value=skills_text, inline=False)
    
    # Active effects
    if character.effects:
        effects_text = format_effect_list([
            effect.to_dict() for effect in character.effects
        ])
        embed.add_field(name="Active Effects", value=effects_text, inline=False)
    
    return embed

class MessageFormatter:
    """Handles consistent message formatting throughout the bot"""
    
    @staticmethod
    def effect(message: str, emoji: str = "✨") -> str:
        """Format an effect message"""
        if not message.strip().startswith("`"):
            message = f"`{message}`"
        return f"{emoji} {message}"
    
    @staticmethod
    def bullet(message: str) -> str:
        """Format a bullet point"""
        if not message.strip().startswith("•"):
            message = f"• {message}"
        if not message.strip().startswith("`"):
            message = f"`{message}`"
        return message
    
    @staticmethod
    def combat(message: str, emoji: str = "⚔️") -> str:
        """Format a combat message"""
        if not message.strip().startswith("`"):
            message = f"`{message}`"
        return f"{emoji} {message}"
    
    @staticmethod
    def format_list(messages: List[str], wrapper: Optional[str] = None) -> str:
        """Format a list of messages with optional wrapper"""
        formatted = []
        for msg in messages:
            if msg and isinstance(msg, str):
                if not msg.strip().startswith("`"):
                    msg = f"`{msg}`"
                formatted.append(msg)
        
        if wrapper:
            return f"{wrapper}\n" + "\n".join(formatted)
        return "\n".join(formatted)