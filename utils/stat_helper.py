"""
Centralized stat handling system.
Provides consistent stat access across different character data formats.
"""

from typing import Union, Dict, Any, Optional, List, Tuple
from core.character import StatType
import logging

logger = logging.getLogger(__name__)

class StatHelper:
    """Helper class for consistent stat handling"""
    
    @staticmethod
    def get_stat_value(character: 'Character', stat_type: StatType, use_modified: bool = True) -> int:
        """
        Get a stat value from a character, handling both dict and object formats.
        
        Args:
            character: Character object
            stat_type: StatType enum value
            use_modified: Whether to use modified or base stats
        
        Returns:
            Stat value (defaults to 10 if not found)
        """
        try:
            stats = character.stats.modified if use_modified else character.stats.base
            
            if isinstance(stats, dict):
                # Dictionary format from database
                return stats.get(stat_type.value, 10)
            else:
                # Object format
                return getattr(stats, stat_type.value, 10)
                
        except Exception as e:
            logger.error(f"Error getting stat value for {stat_type}: {e}")
            return 10

    @staticmethod
    def get_stat_modifier(character: 'Character', stat_type: StatType, use_modified: bool = True) -> int:
        """
        Calculate ability modifier for a stat.
        
        Args:
            character: Character object
            stat_type: StatType enum value
            use_modified: Whether to use modified or base stats
        
        Returns:
            Calculated ability modifier
        """
        value = StatHelper.get_stat_value(character, stat_type, use_modified)
        return (value - 10) // 2

    @staticmethod
    def parse_stat_name(stat_str: str) -> Optional[StatType]:
        """
        Convert a stat string to StatType enum.
        Handles both short (str) and long (strength) formats.
        
        Args:
            stat_str: String representation of stat
            
        Returns:
            StatType enum or None if invalid
        """
        stat_map = {
            'str': StatType.STRENGTH,
            'dex': StatType.DEXTERITY,
            'con': StatType.CONSTITUTION,
            'int': StatType.INTELLIGENCE,
            'wis': StatType.WISDOM,
            'cha': StatType.CHARISMA,
            'strength': StatType.STRENGTH,
            'dexterity': StatType.DEXTERITY,
            'constitution': StatType.CONSTITUTION,
            'intelligence': StatType.INTELLIGENCE,
            'wisdom': StatType.WISDOM,
            'charisma': StatType.CHARISMA
        }
        
        try:
            return stat_map.get(stat_str.lower())
        except Exception as e:
            logger.error(f"Error parsing stat name '{stat_str}': {e}")
            return None

    @staticmethod
    def format_modifier(mod_value: int) -> str:
        """Format a modifier value with proper sign"""
        return f"+{mod_value}" if mod_value >= 0 else str(mod_value)

    @staticmethod
    def validate_stats(stats: Dict[str, Any]) -> bool:
        """
        Validate stat dictionary format.
        
        Args:
            stats: Dictionary of stats to validate
            
        Returns:
            True if valid, False if invalid
        """
        try:
            # Check for required stat types
            required_stats = {stat.value for stat in StatType}
            provided_stats = set(stats.keys())
            
            # All required stats present
            if not required_stats.issubset(provided_stats):
                logger.warning("Missing required stats")
                return False
                
            # Validate stat values
            for stat, value in stats.items():
                if not isinstance(value, int):
                    logger.warning(f"Invalid stat value for {stat}: {value}")
                    return False
                if value < 0:
                    logger.warning(f"Negative stat value for {stat}: {value}")
                    return False
                    
            return True
            
        except Exception as e:
            logger.error(f"Error validating stats: {e}")
            return False

    @staticmethod
    def get_highest_stat(character: 'Character', 
                        stat_types: Optional[List[StatType]] = None,
                        use_modified: bool = True) -> Tuple[StatType, int]:
        """
        Get highest stat and its value from a list of stats.
        Useful for finding spellcasting modifiers.
        
        Args:
            character: Character object
            stat_types: List of stats to check (defaults to all)
            use_modified: Whether to use modified stats
            
        Returns:
            Tuple of (StatType, value)
        """
        try:
            # Default to all stats if none specified
            stats_to_check = stat_types or list(StatType)
            
            highest_stat = None
            highest_value = -1
            
            for stat_type in stats_to_check:
                value = StatHelper.get_stat_value(character, stat_type, use_modified)
                if value > highest_value:
                    highest_value = value
                    highest_stat = stat_type
                    
            return (highest_stat, highest_value)
            
        except Exception as e:
            logger.error(f"Error getting highest stat: {e}")
            return (StatType.STRENGTH, 10)  # Safe default

    @staticmethod
    def convert_to_dict(stats: Any) -> Dict[str, int]:
        """
        Convert any stat format to dictionary format.
        
        Args:
            stats: Stats in any format (dict or object)
            
        Returns:
            Dictionary of stats
        """
        try:
            if isinstance(stats, dict):
                return stats
                
            return {
                stat.value: getattr(stats, stat.value, 10)
                for stat in StatType
            }
            
        except Exception as e:
            logger.error(f"Error converting stats to dict: {e}")
            return {stat.value: 10 for stat in StatType}

    @staticmethod
    def calculate_spell_save_dc(character: 'Character', 
                              stat_types: Optional[List[StatType]] = None) -> int:
        """
        Calculate spell save DC using highest applicable stat.
        
        Args:
            character: Character object
            stat_types: List of stats to consider (defaults to INT/WIS/CHA)
            
        Returns:
            Calculated spell save DC
        """
        try:
            # Default to spellcasting stats
            default_stats = [
                StatType.INTELLIGENCE,
                StatType.WISDOM,
                StatType.CHARISMA
            ]
            stats_to_check = stat_types or default_stats
            
            # Get highest stat modifier
            _, highest_value = StatHelper.get_highest_stat(
                character,
                stats_to_check
            )
            highest_mod = (highest_value - 10) // 2
            
            # Calculate DC (8 + prof + mod)
            return 8 + character.base_proficiency + highest_mod
            
        except Exception as e:
            logger.error(f"Error calculating spell save DC: {e}")
            return 8  # Safe default

    @staticmethod
    def copy_stats(source: Dict[str, int]) -> Dict[str, int]:
        """
        Create a deep copy of stats dictionary.
        Useful for tracking original values when applying effects.
        
        Args:
            source: Original stats dictionary
            
        Returns:
            New copy of stats dictionary
        """
        return {stat: value for stat, value in source.items()}