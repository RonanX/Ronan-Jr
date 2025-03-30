"""  
Character Data Structure (src/core/character.py)

This file defines the core Character class and related data structures. It handles all  
character-related data and operations, including stats, resources, effects, and proficiencies.  
"""

from dataclasses import dataclass, field  
from typing import Dict, List, Optional, Any, Tuple, Type, Set  
from enum import Enum  
from core.effects.base import EffectRegistry  
from core.effects.status import ACManager  
import logging  
from utils.action_stars import ActionStars

logger = logging.getLogger(__name__)

class StatType(Enum):  
    """Core stats that every character has"""  
    STRENGTH = "strength"  
    DEXTERITY = "dexterity"  
    CONSTITUTION = "constitution"  
    INTELLIGENCE = "intelligence"  
    WISDOM = "wisdom"  
    CHARISMA = "charisma"

class ProficiencyLevel(Enum):  
    """Different levels of proficiency a character can have"""  
    NONE = 0        # No proficiency bonus  
    PROFICIENT = 1  # Normal proficiency bonus  
    EXPERT = 2      # Double proficiency bonus

@dataclass  
class EffectFeedback:
    """
    Tracks recently expired effects to ensure their messages are displayed
    even after the effects are removed from the character.
    
    This solves the issue where expiry messages wouldn't show up because
    the effect would be removed from the character by the time the message
    needed to be displayed.
    """
    effect_name: str
    expiry_message: str
    round_expired: int
    turn_expired: str
    displayed: bool = False  # Whether this feedback has been displayed
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        return {
            "effect_name": self.effect_name,
            "expiry_message": self.expiry_message,
            "round_expired": self.round_expired,
            "turn_expired": self.turn_expired,
            "displayed": self.displayed
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'EffectFeedback':
        """Create from dictionary data"""
        feedback = cls(
            effect_name=data["effect_name"],
            expiry_message=data["expiry_message"],
            round_expired=data["round_expired"],
            turn_expired=data["turn_expired"]
        )
        feedback.displayed = data.get("displayed", False)
        return feedback

@dataclass  
class Stats:  
    """Container for character stats with base and modified values"""  
    base: Dict[StatType, int] = field(default_factory=dict)  
    modified: Dict[StatType, int] = field(default_factory=dict)  
     
    def get_modifier(self, stat: StatType, use_modified: bool = True) -> int:  
        """Calculate ability modifier using either base or modified stat"""  
        value = self.modified[stat] if use_modified else self.base[stat]  
        return (value - 10) // 2

@dataclass  
class Resources:  
    """Track character resources like HP and MP"""  
    current_hp: int  
    max_hp: int  
    current_mp: int  
    max_mp: int  
    current_temp_hp: int = 0  
    max_temp_hp: int = 0

    def add_temp_hp(self, amount: int) -> Tuple[int, int]:  
        """Add temporary HP, returns (current, max)"""  
        self.max_temp_hp = amount  
        self.current_temp_hp = amount  
        return self.current_temp_hp, self.max_temp_hp

    def remove_temp_hp(self, amount: int) -> Tuple[int, int]:  
        """Remove temporary HP and return tuple of (amount_absorbed, remaining_damage)"""  
        if self.current_temp_hp <= 0:  
            return 0, amount  
             
        absorbed = min(self.current_temp_hp, amount)  
        self.current_temp_hp -= absorbed  
         
        # If all temp HP is depleted, reset max as well  
        if self.current_temp_hp <= 0:  
            self.max_temp_hp = 0  
         
        return absorbed, amount - absorbed

    def clear_temp_hp(self) -> None:  
        """Remove all temporary HP"""  
        self.current_temp_hp = 0  
        self.max_temp_hp = 0

@dataclass  
class DefenseStats:  
    """Track AC and various defensive stats"""  
    base_ac: int  
    current_ac: int  
    natural_resistances: Dict[str, int] = field(default_factory=dict)  # Natural damage resistance percentages  
    natural_vulnerabilities: Dict[str, int] = field(default_factory=dict)  # Natural vulnerability percentages  
    damage_resistances: Dict[str, int] = field(default_factory=dict)  # Effect-based resistances  
    damage_vulnerabilities: Dict[str, int] = field(default_factory=dict)  # Effect-based vulnerabilities  
    ac_modifiers: List[int] = field(default_factory=list)  # Track AC changes

    def get_total_resistance(self, damage_type: str) -> int:  
        """Get total resistance percentage for a damage type"""  
        natural = self.natural_resistances.get(damage_type, 0)  
        effect = self.damage_resistances.get(damage_type, 0)  
        return min(100, natural + effect)  # Cap at 100%

    def get_total_vulnerability(self, damage_type: str) -> int:  
        """Get total vulnerability percentage for a damage type"""  
        natural = self.natural_vulnerabilities.get(damage_type, 0)  
        effect = self.damage_vulnerabilities.get(damage_type, 0)  
        return min(100, natural + effect)  # Cap at 100%

@dataclass  
class Proficiencies:  
    """Track character proficiencies in saves and skills"""  
    saves: Dict[StatType, ProficiencyLevel] = field(default_factory=lambda: {  
        stat: ProficiencyLevel.NONE for stat in StatType  
    })  
    skills: Dict[str, ProficiencyLevel] = field(default_factory=lambda: {  
        # Strength skills  
        "athletics": ProficiencyLevel.NONE,  
         
        # Dexterity skills  
        "acrobatics": ProficiencyLevel.NONE,  
        "sleight_of_hand": ProficiencyLevel.NONE,  
        "stealth": ProficiencyLevel.NONE,  
         
        # Intelligence skills  
        "arcana": ProficiencyLevel.NONE,  
        "history": ProficiencyLevel.NONE,  
        "investigation": ProficiencyLevel.NONE,  
        "nature": ProficiencyLevel.NONE,  
        "religion": ProficiencyLevel.NONE,  
         
        # Wisdom skills  
        "animal_handling": ProficiencyLevel.NONE,  
        "insight": ProficiencyLevel.NONE,  
        "medicine": ProficiencyLevel.NONE,  
        "mysticism": ProficiencyLevel.NONE,  
        "perception": ProficiencyLevel.NONE,  
        "survival": ProficiencyLevel.NONE,  
         
        # Charisma skills  
        "deception": ProficiencyLevel.NONE,  
        "intimidation": ProficiencyLevel.NONE,  
        "performance": ProficiencyLevel.NONE,  
        "persuasion": ProficiencyLevel.NONE  
    })

class Character:  
    """  
    Main character class that holds all information about a character  
     
    Version History:  
    1: Base character data without movesets  
    2: Added moveset support  
    3: Added custom parameters field  
    4: Added effect feedback system
    Future versions will add parameters as needed  
    """  
    CURRENT_VERSION = 4  # Update this when adding new features  
     
    def __init__(  
        self,  
        name: str,  
        stats: Stats,  
        resources: Resources,  
        defense: DefenseStats,  
        base_proficiency: int = 2,  
        version: int = CURRENT_VERSION  
    ):  
        self.name = name  
        self.stats = stats  
        self.resources = resources  
        self.defense = defense  
        self.base_proficiency = base_proficiency  
        self.version = version  
        self.effects: List["Effect"] = []  
        self.effect_feedback: List[EffectFeedback] = []  # Track recently expired effects
        self.proficiencies = Proficiencies()  
        self.action_stars = ActionStars()  
        self.style = None  # Will be set during character creation  
        self.custom_parameters: Dict[str, Any] = {}  # For future extensions  
         
        # Initialize derived stats  
        self._update_derived_stats()

        # Ensure the base AC exists first  
        if hasattr(self.defense, "current_ac"):  
            self.ac_manager = ACManager(self.defense.base_ac)  # This will be imported later  
         
        # Initialize moveset  
        from modules.moves.data import Moveset  
        self.moveset = Moveset()

    # Effect feedback methods
    def add_effect_feedback(self, effect_name: str, expiry_message: str, round_expired: int, turn_expired: str) -> None:
        """Add feedback for an expired effect"""
        # Check if feedback for this effect already exists
        for feedback in self.effect_feedback:
            if feedback.effect_name == effect_name and not feedback.displayed:
                # Already have pending feedback for this effect
                return
        
        # Add new feedback
        self.effect_feedback.append(EffectFeedback(
            effect_name=effect_name,
            expiry_message=expiry_message,
            round_expired=round_expired,
            turn_expired=turn_expired
        ))
    
    def get_pending_feedback(self) -> List[EffectFeedback]:
        """Get all pending (undisplayed) effect feedback"""
        return [f for f in self.effect_feedback if not f.displayed]
    
    def mark_feedback_displayed(self) -> None:
        """Mark all feedback as displayed"""
        for feedback in self.effect_feedback:
            feedback.displayed = True
    
    def clear_old_feedback(self) -> None:
        """Remove feedback that has been displayed"""
        self.effect_feedback = [f for f in self.effect_feedback if not f.displayed]

    # Move-related methods  
    def add_move(self, move_data) -> None:  
        """Add a move to the character's moveset"""  
        self.moveset.add_move(move_data)

    def get_move(self, name: str) -> Optional[Any]:  
        """Get a move by name"""  
        return self.moveset.get_move(name)

    def remove_move(self, name: str) -> bool:  
        """Remove a move. Returns True if found and removed."""  
        return self.moveset.remove_move(name)

    def list_moves(self) -> List[str]:  
        """Get list of all move names"""  
        return self.moveset.list_moves()

    def refresh_moves(self) -> None:  
        """Refresh all moves (uses, cooldowns)"""  
        self.moveset.refresh_all()  
    # End of Move-related methods

    def modify_ac(self, effect_id: str, amount: int, priority: int = 0) -> int:  
        """  
        Modify AC through the manager.  
        Returns new total AC.  
        """  
        # Import here to avoid circular import  
        from core.effects.status import ACManager  
        if not hasattr(self, 'ac_manager'):  
            self.ac_manager = ACManager(self.defense.base_ac)  
             
        new_ac = self.ac_manager.add_modifier(effect_id, amount, priority)  
        self.defense.current_ac = new_ac  
        return new_ac  
         
    def remove_ac_modifier(self, effect_id: str) -> int:  
        """  
        Remove an AC modifier.  
        Returns new total AC.  
        """  
        if hasattr(self, 'ac_manager'):  
            new_ac = self.ac_manager.remove_modifier(effect_id)  
            self.defense.current_ac = new_ac  
            return new_ac  
        return self.defense.current_ac  
     
    def can_use_move(self, cost: int, move_name: Optional[str] = None) -> tuple[bool, str]:  
        """Check if character can use a move with the given cost."""  
        return self.action_stars.can_use(cost, move_name)

    def use_move_stars(self, cost: int, move_name: Optional[str] = None) -> None:  
        """Use stars for a move."""  
        self.action_stars.use_stars(cost, move_name)

    def refresh_stars(self) -> None:  
        """Refresh action stars to maximum."""  
        self.action_stars.refresh()

    def clear_cooldowns(self) -> None:  
        """Clear all move cooldowns."""  
        self.action_stars.clear_cooldowns()  
         
        # Also clear cooldowns in moveset  
        if hasattr(self, 'moveset'):  
            self.moveset.refresh_all()

    def remove_effect(self, effect) -> bool:  
        """  
        Safely remove an effect from a character.  
        Returns True if effect was removed, False if not found.  
        """  
        try:  
            if effect in self.effects:  
                self.effects.remove(effect)  
                return True  
            return False  
        except ValueError:  
            logger.warning(f"Attempted to remove non-existent effect from {self.name}")  
            return False

    def clear_temporary_effects(self) -> List[str]:  
        """  
        Safely clear only temporary effects and return cleanup messages.  
        Preserves permanent effects and natural resistances/vulnerabilities.  
        """  
        messages = []  
        effects_to_remove = []  
         
        # First identify effects to remove  
        for effect in self.effects[:]:  # Copy list since we're modifying it  
            # Skip permanent effects  
            if hasattr(effect, 'permanent') and effect.permanent:  
                continue  
                 
            # Always process any move effects (they should be re-applied when a move is used)  
            if hasattr(effect, 'state'):  
                if msg := effect.on_expire(self):  
                    messages.append(msg)  
                effects_to_remove.append(effect)  
                continue  
                 
            # Process normal temporary effects  
            if not hasattr(effect, 'permanent') or not effect.permanent:  
                if msg := effect.on_expire(self):  
                    messages.append(msg)  
                effects_to_remove.append(effect)  
         
        # Now remove the effects  
        for effect in effects_to_remove:  
            if effect in self.effects:  # Double-check it's still there  
                self.effects.remove(effect)  
         
        # Reset resources affected by temporary effects  
        self.resources.current_temp_hp = 0  
        self.resources.max_temp_hp = 0  
         
        # Clear effect-based resistances/vulnerabilities  
        self.defense.damage_resistances = {}  
        self.defense.damage_vulnerabilities = {}  
         
        # Reset AC to base but preserve AC manager  
        if hasattr(self, 'ac_manager'):  
            self.ac_manager.reset()  
        self.defense.current_ac = self.defense.base_ac  
         
        # Clear any custom state attributes  
        custom_attributes = ['heat_stacks', 'frost_stacks']  
        for attr in custom_attributes:  
            if hasattr(self, attr):  
                delattr(self, attr)
                
        # Clear effect feedback
        self.effect_feedback = []
                 
        return messages

    def clear_combat_effects(self) -> List[str]:  
        """  
        Clear all effects that should reset at the start of combat,  
        including non-permanent effects and move cooldowns.  
        Preserves natural resistances/vulnerabilities.  
        """  
        messages = []  
         
        # Clear temporary effects  
        temp_messages = self.clear_temporary_effects()  
        if temp_messages:  
            messages.extend(temp_messages)  
         
        # Reset action stars  
        self.refresh_stars()  
         
        # Clear move cooldowns  
        self.clear_cooldowns()  
         
        # Reset moveset - clear all cooldowns and usage tracking  
        if hasattr(self, 'moveset'):  
            for move_name in self.list_moves():  
                move = self.get_move(move_name)  
                if move:  
                    # Reset usages if tracking uses  
                    if hasattr(move, 'uses') and move.uses is not None:  
                        move.uses_remaining = move.uses  
                         
                    # Clear cooldown tracking  
                    if hasattr(move, 'last_used_round'):  
                        move.last_used_round = None
                        
        # Clear effect feedback as well
        self.effect_feedback = []
         
        return messages

    def clear_all_effects(self, effect_type: Optional[Type] = None) -> List[str]:  
        """  
        Clear ALL effects matching the optional type, even permanent ones.  
        Much more aggressive than clear_temporary_effects().  
        Returns list of cleanup messages.  
        """  
        messages = []  
        effects_to_remove = []  
         
        for effect in self.effects:  
            if effect_type is None or isinstance(effect, effect_type):  
                if msg := effect.on_expire(self):  
                    messages.append(msg)  
                effects_to_remove.append(effect)  
         
        # Remove after iteration to avoid modification during iteration  
        for effect in effects_to_remove:  
            if effect in self.effects:  # Double-check it's still there  
                self.effects.remove(effect)
                
        # Clear effect feedback as well
        self.effect_feedback = []
                 
        return messages

    def set_save_proficiency(self, stat: StatType, level: ProficiencyLevel) -> None:  
        """Set proficiency level for a saving throw"""  
        self.proficiencies.saves[stat] = level  
        self._update_derived_stats()

    def set_skill_proficiency(self, skill: str, level: ProficiencyLevel) -> None:  
        """Set proficiency level for a skill"""  
        if skill in self.proficiencies.skills:  
            self.proficiencies.skills[skill] = level  
            self._update_derived_stats()

    def get_proficiency_bonus(self, proficiency_level: ProficiencyLevel) -> int:  
        """Calculate proficiency bonus based on level"""  
        return self.base_proficiency * proficiency_level.value

    def _update_derived_stats(self):  
        """Update any stats that are derived from other stats"""  
        # Calculate all skill modifiers  
        self.skills = {}  
        for skill, prof_level in self.proficiencies.skills.items():  
            stat = self._get_skill_stat(skill)  
            base_mod = self.stats.get_modifier(stat)  
            prof_bonus = self.get_proficiency_bonus(prof_level)  
            self.skills[skill] = base_mod + prof_bonus

        # Calculate saving throw modifiers  
        self.saves = {}  
        for stat in StatType:  
            base_mod = self.stats.get_modifier(stat)  
            prof_bonus = self.get_proficiency_bonus(self.proficiencies.saves.get(stat, ProficiencyLevel.NONE))  
            self.saves[stat] = base_mod + prof_bonus

        # Calculate spell save DC  
        highest_mod = max(  
            self.stats.get_modifier(stat)  
            for stat in [StatType.INTELLIGENCE, StatType.WISDOM, StatType.CHARISMA]  
        )  
        self.spell_save_dc = 8 + self.base_proficiency + highest_mod

    def _get_skill_stat(self, skill: str) -> StatType:  
            """Get the ability score associated with a skill"""  
            skill_stats = {  
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
                "mysticism": StatType.WISDOM,  # Added Wisdom-based magic skill  
                 
                # Charisma skills  
                "deception": StatType.CHARISMA,  
                "intimidation": StatType.CHARISMA,  
                "performance": StatType.CHARISMA,  
                "persuasion": StatType.CHARISMA  
            }  
            return skill_stats.get(skill, StatType.STRENGTH)

    def add_effect(self, effect, round_number: Optional[int] = None) -> str:  
        """Add an effect to the character and return feedback message"""  
        try:  
            # Take a snapshot of character state before changes  
            if hasattr(self, 'logger'):  
                self.logger.snapshot_character_state(self)  
                
            # Check for existing stacking effects  
            if hasattr(effect, 'add_stacks'):  
                for existing in self.effects:  
                    # Find matching effect types for stacking  
                    if isinstance(existing, type(effect)) and getattr(existing, 'name', '') == effect.name:  
                        # Stack the effect if supported  
                        return existing.add_stacks(  
                            getattr(effect, 'stacks', 1),  
                            self  
                        )  
             
            # Apply new effect  
            self.effects.append(effect)  
            # Use round 1 if no round number provided  
            current_round = round_number if round_number is not None else 1  
            return effect.on_apply(self, current_round)  
             
        except Exception as e:  
            logger.error(f"Error adding effect to {self.name}: {e}", exc_info=True)  
            return f"Error applying {effect.name}"

    def to_dict(self) -> dict:  
        """Convert character to dictionary for database storage"""  
        data = {  
            "version": self.version,  
            "name": self.name,  
            "stats": {  
                "base": {stat.value: value for stat, value in self.stats.base.items()},  
                "modified": {stat.value: value for stat, value in self.stats.modified.items()}  
            },  
            "resources": {  
                "current_hp": self.resources.current_hp,  
                "max_hp": self.resources.max_hp,  
                "current_mp": self.resources.current_mp,  
                "max_mp": self.resources.max_mp,  
                "current_temp_hp": self.resources.current_temp_hp,  
                "max_temp_hp": self.resources.max_temp_hp  
            },  
            "defense": {  
                "base_ac": self.defense.base_ac,  
                "current_ac": self.defense.current_ac,  
                "natural_resistances": self.defense.natural_resistances,  
                "natural_vulnerabilities": self.defense.natural_vulnerabilities,  
                "damage_resistances": self.defense.damage_resistances,  
                "damage_vulnerabilities": self.defense.damage_vulnerabilities,  
                "ac_modifiers": self.defense.ac_modifiers  
            },  
            "base_proficiency": self.base_proficiency,  
            "style": self.style.value if self.style else None,  
            "proficiencies": {  
                "saves": {  
                    stat.value: level.value  
                    for stat, level in self.proficiencies.saves.items()  
                },  
                "skills": {  
                    skill: level.value  
                    for skill, level in self.proficiencies.skills.items()  
                }  
            },  
            "effects": [effect.to_dict() for effect in self.effects],  
            "spell_save_dc": self.spell_save_dc,  
            "action_stars": self.action_stars.to_dict(),  
            "moveset": self.moveset.to_dict(),  # Add moveset to storage  
            "custom_parameters": self.custom_parameters,  # Store custom parameters
            "effect_feedback": [feedback.to_dict() for feedback in self.effect_feedback]  # Add effect feedback
        }  
        # Remove None values to save space  
        return {k: v for k, v in data.items() if v is not None}

    @classmethod  
    def from_dict(cls, data: dict) -> 'Character':  
        """Create a Character instance from a dictionary with version handling"""  
        version = data.get('version', 1)  # Default to version 1 if not specified  
         
        try:  
            # Convert stat dictionaries back to proper StatType enum keys  
            base_stats = {StatType(k): v for k, v in data['stats']['base'].items()}  
            modified_stats = {StatType(k): v for k, v in data['stats']['modified'].items()}  
             
            # Create component objects  
            stats = Stats(base=base_stats, modified=modified_stats)  
            resources = Resources(  
                current_hp=data['resources']['current_hp'],  
                max_hp=data['resources']['max_hp'],  
                current_mp=data['resources']['current_mp'],  
                max_mp=data['resources']['max_mp'],  
                current_temp_hp=data['resources'].get('current_temp_hp', 0),  
                max_temp_hp=data['resources'].get('max_temp_hp', 0)  
            )  
             
            # Ensure defense data exists with defaults  
            defense_data = data.get('defense', {})  
            base_ac = defense_data.get('base_ac', 10)  # Default AC of 10  
            defense = DefenseStats(  
                base_ac=base_ac,  
                current_ac=defense_data.get('current_ac', base_ac),  # Default to base_ac  
                natural_resistances=defense_data.get('natural_resistances', {}),  
                natural_vulnerabilities=defense_data.get('natural_vulnerabilities', {}),  
                damage_resistances=defense_data.get('damage_resistances', {}),  
                damage_vulnerabilities=defense_data.get('damage_vulnerabilities', {}),  
                ac_modifiers=defense_data.get('ac_modifiers', [])  
            )  
             
            # Create character instance with version  
            character = cls(  
                name=data['name'],  
                stats=stats,  
                resources=resources,  
                defense=defense,  
                base_proficiency=data.get('base_proficiency', 2),  
                version=version  
            )  
             
            # Version 1+: Load basic proficiencies and effects  
            if 'proficiencies' in data:  
                prof_data = data['proficiencies']  
                 
                # Load save proficiencies  
                for stat_str, level_value in prof_data.get('saves', {}).items():  
                    character.set_save_proficiency(  
                        StatType(stat_str),  
                        ProficiencyLevel(level_value)  
                    )  
                 
                # Load skill proficiencies  
                for skill, level_value in prof_data.get('skills', {}).items():  
                    character.set_skill_proficiency(  
                        skill,  
                        ProficiencyLevel(level_value)  
                    )  
             
            # Load effects  
            character.effects = []  
            for effect_data in data.get('effects', []):  
                # Import here to avoid circular import  
                from core.effects.base import EffectRegistry  
                if effect := EffectRegistry.from_dict(effect_data):  
                    character.effects.append(effect)

            # Version 2+: Load action stars and moveset  
            if version >= 2:  
                if 'action_stars' in data:  
                    character.action_stars = ActionStars.from_dict(data['action_stars'])  
                     
                if 'moveset' in data:  
                    # Import here to avoid circular import  
                    from modules.moves.data import Moveset  
                    character.moveset = Moveset.from_dict(data['moveset'])

            # Version 3+: Load custom parameters  
            if version >= 3:  
                character.custom_parameters = data.get('custom_parameters', {})
                
            # Version 4+: Load effect feedback
            if version >= 4:
                character.effect_feedback = []
                for feedback_data in data.get('effect_feedback', []):
                    character.effect_feedback.append(EffectFeedback.from_dict(feedback_data))
                 
            # Store unknown parameters for future versions  
            known_keys = {  
                'version', 'name', 'stats', 'resources', 'defense',  
                'base_proficiency', 'proficiencies', 'effects',  
                'action_stars', 'moveset', 'custom_parameters',  
                'spell_save_dc', 'style', 'effect_feedback'  
            }  
            unknown_params = {  
                k: v for k, v in data.items()  
                if k not in known_keys  
            }  
            if unknown_params:  
                character.custom_parameters.update(unknown_params)  
             
            # Update all derived stats  
            character._update_derived_stats()  
             
            return character  
             
        except Exception as e:  
            logger.error(f"Error reconstructing character: {str(e)}")  
            return None