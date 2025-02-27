from typing import Dict, List, Optional, Any
from enum import Enum
from core.character import StatType, ProficiencyLevel

import logging
logger = logging.getLogger(__name__)

class CreatureType(Enum):
    """Base types for character creation"""
    CHUA = "chua"
    FAIRY = "fairy"

class ChuaStyle(Enum):
    """Combat styles for Chua characters"""
    TANK = "tank"
    RUSHER = "rusher"
    ELEMENTAL = "elemental"
    BALANCER = "balancer"
    # All possible hybrid combinations
    HYBRID_TANK_RUSHER = "hybrid_tank_rusher"
    HYBRID_TANK_ELEMENTAL = "hybrid_tank_elemental"
    HYBRID_RUSHER_ELEMENTAL = "hybrid_rusher_elemental"

class FairyType(Enum):
    """Types of Fairies"""
    ENERGY = "energy"
    MIND = "mind"
    SPELL = "spell"
    FIGHTING = "fighting"
    SPIRIT = "spirit"
    OMNI = "omni"

# Define all available skills
SKILLS = {
    # Strength skills
    "athletics": StatType.STRENGTH,
    
    # Dexterity skills
    "acrobatics": StatType.DEXTERITY,
    "sleight_of_hand": StatType.DEXTERITY,
    "stealth": StatType.DEXTERITY,
    
    # Intelligence skills
    "arcana": StatType.INTELLIGENCE,
    "history": StatType.INTELLIGENCE,
    "investigation": StatType.INTELLIGENCE,
    "nature": StatType.INTELLIGENCE,
    "religion": StatType.INTELLIGENCE,
    
    # Wisdom skills
    "animal_handling": StatType.WISDOM,
    "insight": StatType.WISDOM,
    "medicine": StatType.WISDOM,
    "perception": StatType.WISDOM,
    "survival": StatType.WISDOM,
    "mysticism": StatType.WISDOM,  # Added: Wisdom-based magic skill
    
    # Charisma skills
    "deception": StatType.CHARISMA,
    "intimidation": StatType.CHARISMA,
    "performance": StatType.CHARISMA,
    "persuasion": StatType.CHARISMA
}

# Special DC bonuses for styles that enhance spellcasting
SPELLCASTING_BONUSES = {
    ChuaStyle.ELEMENTAL: 2,  # Pure elementals get +2 to spell DC
    ChuaStyle.HYBRID_TANK_ELEMENTAL: 1,  # Hybrid with elemental gets +1
    ChuaStyle.HYBRID_RUSHER_ELEMENTAL: 1,  # Hybrid with elemental gets +1
}

# Preset proficiencies for quick character creation
PRESET_PROFICIENCIES = {
    # Chua Styles
    ChuaStyle.TANK: {
        "saves": {
            "strength": ProficiencyLevel.PROFICIENT.value,
            "constitution": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "athletics": ProficiencyLevel.PROFICIENT.value,
            "intimidation": ProficiencyLevel.PROFICIENT.value
        }
    },
    ChuaStyle.RUSHER: {
        "saves": {
            "dexterity": ProficiencyLevel.PROFICIENT.value,
            "wisdom": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "acrobatics": ProficiencyLevel.PROFICIENT.value,
            "stealth": ProficiencyLevel.PROFICIENT.value
        }
    },
    ChuaStyle.ELEMENTAL: {
        "saves": {
            "intelligence": ProficiencyLevel.PROFICIENT.value,
            "wisdom": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "arcana": ProficiencyLevel.PROFICIENT.value,
            "mysticism": ProficiencyLevel.PROFICIENT.value
        }
    },
    ChuaStyle.BALANCER: {
        "saves": {
            "constitution": ProficiencyLevel.PROFICIENT.value,
            "wisdom": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "athletics": ProficiencyLevel.PROFICIENT.value,
            "acrobatics": ProficiencyLevel.PROFICIENT.value,
            "mysticism": ProficiencyLevel.PROFICIENT.value
        }
    },
    ChuaStyle.HYBRID_TANK_RUSHER: {
        "saves": {
            "strength": ProficiencyLevel.PROFICIENT.value,
            "dexterity": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "athletics": ProficiencyLevel.PROFICIENT.value,
            "acrobatics": ProficiencyLevel.PROFICIENT.value,
            "intimidation": ProficiencyLevel.PROFICIENT.value
        }
    },
    ChuaStyle.HYBRID_TANK_ELEMENTAL: {
        "saves": {
            "strength": ProficiencyLevel.PROFICIENT.value,
            "intelligence": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "athletics": ProficiencyLevel.PROFICIENT.value,
            "arcana": ProficiencyLevel.PROFICIENT.value,
            "mysticism": ProficiencyLevel.PROFICIENT.value
        }
    },
    ChuaStyle.HYBRID_RUSHER_ELEMENTAL: {
        "saves": {
            "dexterity": ProficiencyLevel.PROFICIENT.value,
            "intelligence": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "acrobatics": ProficiencyLevel.PROFICIENT.value,
            "arcana": ProficiencyLevel.PROFICIENT.value,
            "stealth": ProficiencyLevel.PROFICIENT.value
        }
    },
    
    # Fairy Types
    FairyType.ENERGY: {
        "saves": {
            "constitution": ProficiencyLevel.PROFICIENT.value,
            "charisma": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "athletics": ProficiencyLevel.PROFICIENT.value,
            "arcana": ProficiencyLevel.PROFICIENT.value,
            "intimidation": ProficiencyLevel.PROFICIENT.value
        }
    },
    FairyType.MIND: {
        "saves": {
            "wisdom": ProficiencyLevel.PROFICIENT.value,
            "intelligence": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "insight": ProficiencyLevel.PROFICIENT.value,
            "perception": ProficiencyLevel.PROFICIENT.value,
            "mysticism": ProficiencyLevel.PROFICIENT.value
        }
    },
    FairyType.SPELL: {
        "saves": {
            "intelligence": ProficiencyLevel.PROFICIENT.value,
            "wisdom": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "arcana": ProficiencyLevel.PROFICIENT.value,
            "mysticism": ProficiencyLevel.PROFICIENT.value,
            "religion": ProficiencyLevel.PROFICIENT.value
        }
    },
    FairyType.FIGHTING: {
        "saves": {
            "strength": ProficiencyLevel.PROFICIENT.value,
            "dexterity": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "athletics": ProficiencyLevel.PROFICIENT.value,
            "acrobatics": ProficiencyLevel.PROFICIENT.value,
            "intimidation": ProficiencyLevel.PROFICIENT.value
        }
    },
    FairyType.SPIRIT: {
        "saves": {
            "wisdom": ProficiencyLevel.PROFICIENT.value,
            "charisma": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "mysticism": ProficiencyLevel.PROFICIENT.value,
            "religion": ProficiencyLevel.PROFICIENT.value,
            "perception": ProficiencyLevel.PROFICIENT.value
        }
    },
    FairyType.OMNI: {
        "saves": {
            "wisdom": ProficiencyLevel.PROFICIENT.value,
            "charisma": ProficiencyLevel.PROFICIENT.value
        },
        "skills": {
            "arcana": ProficiencyLevel.PROFICIENT.value,
            "mysticism": ProficiencyLevel.PROFICIENT.value,
            "insight": ProficiencyLevel.PROFICIENT.value,
            "perception": ProficiencyLevel.PROFICIENT.value
        }
    }
}

# Point-based system configuration
PROFICIENCY_CONFIG = {
    # Points for saves and skills
    "max_saves": 2,  # Maximum saving throw proficiencies
    "base_points": 2,  # Base skill proficiency points
    # Additional skill points for special types
    ChuaStyle.BALANCER: 1,  # Total of 3 skill points
    FairyType.OMNI: 2,      # Total of 4 skill points

    # Hybrid types get extra points
    ChuaStyle.HYBRID_TANK_RUSHER: 1,
    ChuaStyle.HYBRID_TANK_ELEMENTAL: 1,
    ChuaStyle.HYBRID_RUSHER_ELEMENTAL: 1
}

def get_proficiency_limits(prof_bonus: int) -> Dict[str, Any]:
    """Calculate proficiency-based limits
    
    Args:
        prof_bonus (int): Base proficiency bonus (+1 to +5)
    
    Returns:
        Dict with saves, skills, and expertise limits
    """
    # Calculate limits based on proficiency bonus
    saves = 1 if prof_bonus < 3 else 2  # More saves at +3 and above
    skills = prof_bonus + 1  # Skills scale with proficiency
    can_expertise = prof_bonus >= 4  # Expertise at +4 and above
    
    return {
        "saves": saves,
        "skills": skills,
        "can_expertise": can_expertise
    }

# Return total points
def get_available_points(character_type: Enum) -> int:
    """Get available proficiency points for a character type"""
    return PROFICIENCY_CONFIG.get(character_type, PROFICIENCY_CONFIG["base_points"])

def get_preset_proficiencies(character_type: Enum) -> Dict:
    """Get preset proficiencies for a character type"""
    logger.info(f"Getting preset proficiencies for type: {character_type}")
    
    # Get raw presets - this already has the correct structure
    presets = PRESET_PROFICIENCIES.get(character_type, {
        "saves": {},
        "skills": {}
    })
    
    logger.info(f"Using preset proficiencies: {presets}")
    return presets

def get_skill_stat(skill: str) -> StatType:
    """Get the associated stat for a skill"""
    return SKILLS.get(skill, StatType.STRENGTH)  # Default to strength if unknown

def calculate_spell_save_dc(character_type: Enum, proficiency: int, highest_mod: int) -> int:
    """Calculate spell save DC including style-based bonuses
    
    Args:
        character_type: The character's style/type
        proficiency: Character's proficiency bonus
        highest_mod: Highest of INT/WIS/CHA modifiers
    
    Returns:
        int: Final spell save DC
    """
    base_dc = 8 + proficiency + highest_mod
    style_bonus = SPELLCASTING_BONUSES.get(character_type, 0)
    return base_dc + style_bonus