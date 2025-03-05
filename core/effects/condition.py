"""
Condition effects implementation.
Handles various status conditions and their associated tags.
"""

from typing import List, Optional, Dict, Set
from enum import Enum
from .base import BaseEffect, EffectCategory, EffectTiming

class ConditionType(str, Enum):
    """Available condition types with their associated tags"""
    # Movement Conditions
    PRONE = "prone"
    GRAPPLED = "grappled"
    RESTRAINED = "restrained"
    AIRBORNE = "airborne"
    SLOWED = "slowed"

    # Combat Conditions
    BLINDED = "blinded"
    DEAFENED = "deafened"
    MARKED = "marked"
    GUARDED = "guarded"
    FLANKED = "flanked"

    # Control Conditions
    INCAPACITATED = "incapacitated"
    PARALYZED = "paralyzed"
    CHARMED = "charmed"
    FRIGHTENED = "frightened"
    CONFUSED = "confused"

    # Situational Conditions
    HIDDEN = "hidden"
    INVISIBLE = "invisible"
    UNDERWATER = "underwater"
    CONCENTRATING = "concentrating"
    SURPRISED = "surprised"

    # State Conditions
    BLEEDING = "bleeding"
    POISONED = "poisoned"
    SILENCED = "silenced"
    EXHAUSTED = "exhausted"

CONDITION_PROPERTIES = {
    ConditionType.PRONE: {
        "emoji": "🔻",
        "apply_message": "{} falls prone",
        "status_message": "Prone: Movement halved, must use half to stand",
        "remove_message": "{} stands up",
        "turn_effects": [
            "• Ranged attacks against you have disadvantage",
            "• Melee attacks within 5 ft have advantage",
            "• Your attacks have disadvantage"
        ],
        "tags": ["prone", "disadvantage_attack", "vulnerable_melee"]
    },
    ConditionType.GRAPPLED: {
        "emoji": "✋",
        "apply_message": "{} is grappled",
        "status_message": "Grappled: Movement speed becomes 0",
        "remove_message": "{} breaks free from the grapple",
        "turn_effects": [
            "• Cannot move or be moved",
            "• Can attempt to break free using an action"
        ],
        "tags": ["grappled", "no_movement"]
    },
    ConditionType.RESTRAINED: {
        "emoji": "🕸️",
        "apply_message": "{} becomes restrained",
        "status_message": "Restrained: Cannot move, attacks affected",
        "remove_message": "{} is no longer restrained",
        "turn_effects": [
            "• Speed becomes 0",
            "• Attacks against you have advantage",
            "• Your attacks have disadvantage",
            "• Disadvantage on DEX saves"
        ],
        "tags": ["restrained", "no_movement", "disadvantage_attack"]
    },
    ConditionType.AIRBORNE: {
        "emoji": "🌪️",
        "apply_message": "{} is launched into the air",
        "status_message": "Airborne: Hovering above ground",
        "remove_message": "{} returns to the ground",
        "turn_effects": [
            "• Out of melee range from grounded enemies",
            "• Immune to ground-based effects",
            "• Can be knocked prone (will fall)"
        ],
        "tags": ["airborne", "flying"]
    },
    ConditionType.SLOWED: {
        "emoji": "🐌",
        "apply_message": "{} is slowed",
        "status_message": "Slowed: Movement speed halved",
        "remove_message": "{} is no longer slowed",
        "turn_effects": [
            "• Movement speed is halved",
            "• Cannot take reactions"
        ],
        "tags": ["slowed", "half_movement", "no_reactions"]
    },
    ConditionType.BLINDED: {
        "emoji": "👁️",
        "apply_message": "{} is blinded",
        "status_message": "Blinded: Cannot see",
        "remove_message": "{} can see again",
        "turn_effects": [
            "• Automatically fail sight-based checks",
            "• Attacks against you have advantage",
            "• Your attacks have disadvantage"
        ],
        "tags": ["blinded", "disadvantage_attack"]
    },
    ConditionType.DEAFENED: {
        "emoji": "👂",
        "apply_message": "{} is deafened",
        "status_message": "Deafened: Cannot hear",
        "remove_message": "{} can hear again",
        "turn_effects": [
            "• Automatically fail hearing-based checks",
            "• Cannot receive verbal commands"
        ],
        "tags": ["deafened"]
    },
    ConditionType.MARKED: {
        "emoji": "🎯",
        "apply_message": "{} is marked",
        "status_message": "Marked: Tagged for follow-up",
        "remove_message": "{} is no longer marked",
        "turn_effects": [
            "• Next attack against you has advantage",
            "• Moving triggers reactions from marker"
        ],
        "tags": ["marked", "vulnerable"]
    },
    ConditionType.GUARDED: {
        "emoji": "🛡️",
        "apply_message": "{} takes a defensive stance",
        "status_message": "Guarded: Enhanced defenses",
        "remove_message": "{} lowers their guard",
        "turn_effects": [
            "• Attacks against you have disadvantage",
            "• Advantage on DEX saves",
            "• Reaction to reduce damage"
        ],
        "tags": ["guarded", "defensive"]
    },
    ConditionType.FLANKED: {
        "emoji": "⚔️",
        "apply_message": "{} is flanked",
        "status_message": "Flanked: Surrounded by enemies",
        "remove_message": "{} is no longer flanked",
        "turn_effects": [
            "• Attacks against you have advantage",
            "• Cannot take reactions"
        ],
        "tags": ["flanked", "vulnerable", "no_reactions"]
    },
    ConditionType.INCAPACITATED: {
        "emoji": "💫",
        "apply_message": "{} is incapacitated",
        "status_message": "Incapacitated: Cannot take actions",
        "remove_message": "{} regains their senses",
        "turn_effects": [
            "• Cannot take actions or reactions",
            "• Cannot move",
            "• Automatically fail STR and DEX saves"
        ],
        "tags": ["incapacitated", "no_actions", "no_movement"]
    },
    ConditionType.PARALYZED: {
        "emoji": "⚡",
        "apply_message": "{} is paralyzed",
        "status_message": "Paralyzed: Cannot move or act",
        "remove_message": "{} can move again",
        "turn_effects": [
            "• Cannot move or take actions",
            "• Automatically fail STR and DEX saves",
            "• Attacks against you have advantage",
            "• Melee hits are critical hits"
        ],
        "tags": ["paralyzed", "no_movement", "no_actions"]
    },
    ConditionType.CHARMED: {
        "emoji": "💝",
        "apply_message": "{} is charmed",
        "status_message": "Charmed: Friendly to source",
        "remove_message": "{} breaks free from the charm",
        "turn_effects": [
            "• Cannot attack the charmer",
            "• Charmer has advantage on social checks",
            "• Disadvantage against charmer's effects"
        ],
        "tags": ["charmed"]
    },
    ConditionType.FRIGHTENED: {
        "emoji": "😨",
        "apply_message": "{} becomes frightened",
        "status_message": "Frightened: Must move away from source",
        "remove_message": "{} overcomes their fear",
        "turn_effects": [
            "• Must move away from source if possible",
            "• Cannot willingly move closer",
            "• Disadvantage while source is visible"
        ],
        "tags": ["frightened", "disadvantage_near_source"]
    },
    ConditionType.CONFUSED: {
        "emoji": "💫",
        "apply_message": "{} becomes confused",
        "status_message": "Confused: Actions unpredictable",
        "remove_message": "{} regains clarity",
        "turn_effects": [
            "• Roll for random action each turn",
            "• May attack self or allies",
            "• May waste action doing nothing"
        ],
        "tags": ["confused", "random_actions"]
    },
    ConditionType.HIDDEN: {
        "emoji": "👥",
        "apply_message": "{} becomes hidden",
        "status_message": "Hidden: Concealed from others",
        "remove_message": "{} is revealed",
        "turn_effects": [
            "• Attacks against you have disadvantage",
            "• Your attacks have advantage",
            "• Location must be guessed"
        ],
        "tags": ["hidden", "advantage_attack"]
    },
    ConditionType.INVISIBLE: {
        "emoji": "👻",
        "apply_message": "{} turns invisible",
        "status_message": "Invisible: Cannot be seen",
        "remove_message": "{} becomes visible",
        "turn_effects": [
            "• Attacks against you have disadvantage",
            "• Your attacks have advantage",
            "• Can hide without cover"
        ],
        "tags": ["invisible", "advantage_attack"]
    },
    ConditionType.UNDERWATER: {
        "emoji": "💧",
        "apply_message": "{} is submerged",
        "status_message": "Underwater: Submerged in liquid",
        "remove_message": "{} surfaces",
        "turn_effects": [
            "• Most attacks have disadvantage",
            "• Fire damage reduced/negated",
            "• Must hold breath or drown"
        ],
        "tags": ["underwater", "disadvantage_attack"]
    },
    ConditionType.CONCENTRATING: {
        "emoji": "🎯",
        "apply_message": "{} begins concentrating",
        "status_message": "Concentrating: Maintaining effect",
        "remove_message": "{} loses concentration",
        "turn_effects": [
            "• Must make CON save when damaged",
            "• DC 10 or half damage taken",
            "• Failure ends concentration"
        ],
        "tags": ["concentrating"]
    },
    ConditionType.SURPRISED: {
        "emoji": "😱",
        "apply_message": "{} is surprised",
        "status_message": "Surprised: Caught off guard",
        "remove_message": "{} regains composure",
        "turn_effects": [
            "• Cannot move or take actions",
            "• Cannot take reactions until turn ends",
            "• Attacks against you have advantage"
        ],
        "tags": ["surprised", "no_actions", "no_reactions"]
    },
    ConditionType.BLEEDING: {
        "emoji": "🩸",
        "apply_message": "{} starts bleeding",
        "status_message": "Bleeding: Taking damage over time",
        "remove_message": "{} stops bleeding",
        "turn_effects": [
            "• Take 1d4 damage at start of turn",
            "• Can be stopped with medicine check",
            "• Leaves blood trail"
        ],
        "tags": ["bleeding", "dot"]
    },
    ConditionType.POISONED: {
        "emoji": "☠️",
        "apply_message": "{} is poisoned",
        "status_message": "Poisoned: System compromised",
        "remove_message": "{} is cured of poison",
        "turn_effects": [
            "• Disadvantage on all rolls",
            "• Take 1d4 poison damage per turn",
            "• Cannot regain HP"
        ],
        "tags": ["poisoned", "disadvantage_all"]
    },
    ConditionType.SILENCED: {
        "emoji": "🤫",
        "apply_message": "{} is silenced",
        "status_message": "Silenced: Cannot make sound",
        "remove_message": "{} can speak again",
        "turn_effects": [
            "• Cannot cast verbal spells",
            "• Cannot speak or yell",
            "• Advantage on stealth checks"
        ],
        "tags": ["silenced", "no_verbal"]
    },
    ConditionType.EXHAUSTED: {
        "emoji": "😫",
        "apply_message": "{} becomes exhausted",
        "status_message": "Exhausted: Severely fatigued",
        "remove_message": "{} recovers from exhaustion",
        "turn_effects": [
            "• Disadvantage on all checks",
            "• Speed halved",
            "• Max HP reduced by half"
        ],
        "tags": ["exhausted", "disadvantage_all", "half_movement"]
    }
}

class ConditionEffect(BaseEffect):
    """
    Handles character conditions and their associated tags.
    
    Properties:
        conditions: List of active conditions
        tags: Set of associated tags for game logic
        source: Optional source of the condition
    """
    
    def __init__(
        self,
        conditions: List[ConditionType],
        duration: Optional[int] = None,
        permanent: bool = False,
        source: Optional[str] = None
    ):
        name = " & ".join([cond.value.title() for cond in conditions])
        super().__init__(
            name=name,
            duration=duration,
            permanent=permanent,
            category=EffectCategory.STATUS
        )
        self.conditions = conditions
        self.source = source
        self.tags = set()
        
        # Collect all tags from conditions
        for condition in conditions:
            if props := CONDITION_PROPERTIES.get(condition):
                self.tags.update(props["tags"])

    def on_apply(self, character, round_number: int) -> str:
        """Apply conditions and their tags with enhanced formatting"""
        self.initialize_timing(round_number, character.name)
        
        # Add condition tags to character
        if not hasattr(character, 'condition_tags'):
            character.condition_tags = set()
        character.condition_tags.update(self.tags)
        
        # Generate application messages with proper formatting
        messages = []
        details = []
        
        # Gather primary message and details
        for condition in self.conditions:
            if props := CONDITION_PROPERTIES.get(condition):
                emoji = props["emoji"]
                msg = props["apply_message"].format(character.name)
                messages.append(f"{emoji} {msg}")
                
                # Add mechanical effect as a detail
                if turn_effects := props.get("turn_effects", []):
                    for effect in turn_effects:
                        details.append(effect.strip())
        
        # Add duration info if applicable
        if self.duration:
            details.append(f"Duration: {self.duration} turns")
        elif self.permanent:
            details.append("Duration: Permanent")
            
        # Get source if provided
        if self.source:
            details.append(f"Source: {self.source}")
                
        # Format using combined message for all conditions
        primary_message = "; ".join(messages)
        return self.format_effect_message(
            primary_message,
            details
        )

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process start of turn effects with improved formatting"""
        if character.name != turn_name:
            return []
            
        messages = []
        
        # Create a single message with all active conditions
        condition_effects = []
        condition_details = []
        
        # Collect effects for each condition
        for condition in self.conditions:
            if props := CONDITION_PROPERTIES.get(condition):
                emoji = props["emoji"]
                status = props["status_message"]
                condition_effects.append(f"{emoji} {condition.value.title()}: {status}")
                
                # Add turn effects as details
                if turn_effects := props.get("turn_effects", []):
                    for effect in turn_effects:
                        condition_details.append(effect)
        
        # Add duration info
        if not self.permanent and self.duration:
            rounds_completed = round_number - self.timing.start_round
            turns_remaining = max(0, self.duration - rounds_completed)
            if turns_remaining > 0:
                condition_details.append(f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining")
                
        # Create the formatted message
        if condition_effects:
            main_message = "; ".join(condition_effects)
            messages.append(self.format_effect_message(
                main_message,
                condition_details
            ))
                
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process turn end with improved duration tracking"""
        if character.name != turn_name or self.permanent:
            return []
            
        # Calculate remaining turns
        turns_remaining, should_expire = self.process_duration(round_number, turn_name)
        
        # Create message based on remaining duration
        if should_expire:
            # Create list of condition names
            condition_names = [cond.value.title() for cond in self.conditions]
            
            if len(condition_names) == 1:
                condition_text = condition_names[0]
            elif len(condition_names) == 2:
                condition_text = f"{condition_names[0]} and {condition_names[1]}"
            else:
                condition_text = f"{', '.join(condition_names[:-1])}, and {condition_names[-1]}"
                
            return [self.format_effect_message(
                f"{condition_text} will wear off from {character.name}"
            )]
        elif turns_remaining > 0:
            # Format duration message
            details = [f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"]
            
            # Get condition names
            condition_names = [cond.value.title() for cond in self.conditions]
            if len(condition_names) == 1:
                condition_text = condition_names[0]
            elif len(condition_names) == 2:
                condition_text = f"{condition_names[0]} and {condition_names[1]}"
            else:
                condition_text = f"{', '.join(condition_names[:-1])}, and {condition_names[-1]}"
                
            return [self.format_effect_message(
                f"{condition_text} continues to affect {character.name}",
                details
            )]
            
        return []

    def on_expire(self, character) -> str:
        """Remove conditions and their tags with improved formatting"""
        if hasattr(character, 'condition_tags'):
            character.condition_tags.difference_update(self.tags)
            
        # Generate removal messages with proper formatting
        messages = []
        
        # Get emojis and removal messages
        for condition in self.conditions:
            if props := CONDITION_PROPERTIES.get(condition):
                emoji = props["emoji"]
                msg = props["remove_message"].format(character.name)
                messages.append(f"{emoji} {msg}")
                
        # Format as a single message for all conditions
        primary_message = "; ".join(messages)
        return self.format_effect_message(primary_message)

    def get_status_text(self, character) -> str:
        """Format condition status for character sheet display"""
        messages = []
        
        # Create header based on number of conditions
        condition_names = [cond.value.title() for cond in self.conditions]
        if len(condition_names) == 1:
            condition_header = condition_names[0]
        elif len(condition_names) == 2:
            condition_header = f"{condition_names[0]} & {condition_names[1]}"
        else:
            condition_header = f"Multiple Conditions ({len(condition_names)})"
            
        messages.append(f"⚠️ **{condition_header}**")
        
        # Add details for each condition
        for condition in self.conditions:
            if props := CONDITION_PROPERTIES.get(condition):
                emoji = props["emoji"]
                status = props["status_message"]
                messages.append(f"• {emoji} `{condition.value.title()}`: {status}")
                
                # Add first effect as a subpoint if available
                if turn_effects := props.get("turn_effects", []):
                    messages.append(f"  ↳ `{turn_effects[0]}`")
                    if len(turn_effects) > 1:
                        messages.append(f"  ↳ `+{len(turn_effects)-1} more effects`")
                
        # Add duration info
        if self.duration:
            turns = "turn" if self.duration == 1 else "turns"
            
            # Calculate remaining if possible
            if self.timing and hasattr(character, 'round_number'):
                rounds_passed = character.round_number - self.timing.start_round
                remaining = max(0, self.duration - rounds_passed)
                messages.append(f"• `{remaining} {turns} remaining`")
            else:
                messages.append(f"• `Duration: {self.duration} {turns}`")
        elif self.permanent:
            messages.append("• `Permanent`")
            
        # Add source if available
        if self.source:
            messages.append(f"• `Source: {self.source}`")
            
        return "\n".join(messages)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            "conditions": [c.value for c in self.conditions],
            "source": self.source,
            "tags": list(self.tags)
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'ConditionEffect':
        """Create from dictionary data"""
        conditions = [ConditionType(c) for c in data.get('conditions', [])]
        effect = cls(
            conditions=conditions,
            duration=data.get('duration'),
            permanent=data.get('permanent', False),
            source=data.get('source')
        )
        if data.get('timing'):
            effect.timing = EffectTiming(**data['timing'])
        effect.tags = set(data.get('tags', []))
        return effect