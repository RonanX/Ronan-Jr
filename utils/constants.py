"""
Game Constants (src/utils/constants.py)

This file contains all constant values used throughout the bot. Centralizing these values
makes it easier to modify game rules and ensures consistency across the codebase.

Key Features:
- Discord-specific constants (Guild IDs)
- Game rule constants (AC, crit threshold, etc.)
- Damage types and categories
- Skill to ability score mappings
- Emoji mappings for formatting

When to Modify:
- Adding new game mechanics that need constants
- Changing game rules or default values
- Adding new categories of items/effects
- Updating Discord server IDs
- Adding new emoji mappings

Dependencies:
- None (this file should only contain constants)
"""

from typing import List, Dict, Set

# Discord Guild IDs where commands will be available
GUILD_IDS: List[int] = [
    421424814952284160,  # Your first guild
    968588058133942312   # Your second guild
]

# Combat constants
DEFAULT_AC: int = 10
CRIT_THRESHOLD: int = 20
DEFAULT_PROFICIENCY: int = 2

# Damage types
DAMAGE_TYPES: Set[str] = {
    # Physical
    "slashing", "piercing", "bludgeoning",
    
    # Magical
    "force", "psychic",
    
    # Elemental
    "fire", "ice", "electric", "acid", "poison", "thunder",
    
    # Energy
    "radiant", "necrotic",
    
    # Natural
    "sonic", "wind", "water",
    
    # Generic
    "physical", "magical", "all"
}

# Skill to ability score mapping
SKILL_ABILITY_MAP: Dict[str, str] = {
    # Strength
    "athletics": "strength",
    
    # Dexterity
    "acrobatics": "dexterity",
    "sleight_of_hand": "dexterity",
    "stealth": "dexterity",
    
    # Intelligence
    "arcana": "intelligence",
    "history": "intelligence",
    "investigation": "intelligence",
    "nature": "intelligence",
    "religion": "intelligence",
    
    # Wisdom
    "animal_handling": "wisdom",
    "insight": "wisdom",
    "medicine": "wisdom",
    "perception": "wisdom",
    "survival": "wisdom",
    
    # Charisma
    "deception": "charisma",
    "intimidation": "charisma",
    "performance": "charisma",
    "persuasion": "charisma"
}

# Default folders for organizing spells/moves
DEFAULT_FOLDERS: List[str] = [
    "offense",
    "defense", 
    "healing",
    "support",
    "utility",
    "movement"
]

# Emoji mappings for different elements/effects
EMOJI_MAP: Dict[str, str] = {
    # Elements
    "fire": "🔥",
    "water": "💧",
    "earth": "🌎",
    "air": "💨",
    "lightning": "⚡",
    "ice": "❄️",
    "light": "✨",
    "dark": "🌑",
    
    # Stats
    "hp": "❤️",
    "mp": "💙",
    "ac": "🛡️",
    
    # Effects
    "buff": "💪",
    "debuff": "🌀",
    "heal": "💖",
    "damage": "💥",
    "stun": "💫",
    "poison": "☠️",
    "bleed": "🩸",
    
    # States
    "success": "✅",
    "failure": "❌",
    "critical": "💯",
    "miss": "🎯"
}
