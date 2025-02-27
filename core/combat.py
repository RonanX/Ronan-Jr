"""
Combat system core including compound moves and state management.

Features:
- Enhanced state transitions with proper timing
- Consistent message formatting following base.py standards
- Full combat logging integration
- Proper cooldown and duration tracking
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum
import logging

from core.effects.base import BaseEffect, CustomEffect, EffectCategory
from core.effects.condition import ConditionType, ConditionEffect
from utils.advanced_dice.attack_calculator import AttackCalculator, AttackParameters, DamageComponent
from utils.advanced_dice.calculator import DiceCalculator
from modules.combat.logger import CombatEventType

logger = logging.getLogger(__name__)

class EffectState(Enum):
    """Tracks the current phase of a compound effect"""
    CASTING = "casting"     # Initial cast time phase
    ACTIVE = "active"      # Main effect duration
    COOLDOWN = "cooldown"  # Recovery period
    COMPLETE = "complete"  # Effect has ended

@dataclass
class MoveParameters:
    """Parameters for a compound move"""
    name: str
    description: str
    mp_cost: int = 0
    hp_cost: int = 0
    star_cost: int = 1
    cast_time: Optional[int] = None
    cooldown: Optional[int] = None
    duration: Optional[int] = None
    cast_description: Optional[str] = None
    attack_roll: Optional[str] = None
    damage: Optional[str] = None
    damage_type: Optional[str] = None
    target_count: int = 1
    conditions: List[ConditionType] = None
    success_text: Optional[str] = None
    failure_text: Optional[str] = None
    
    def __post_init__(self):
        if self.conditions is None:
            self.conditions = []
            
    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary"""
        return {
            "name": self.name,
            "description": self.description,
            "mp_cost": self.mp_cost,
            "hp_cost": self.hp_cost,
            "star_cost": self.star_cost,
            "cast_time": self.cast_time,
            "cooldown": self.cooldown,
            "duration": self.duration,
            "cast_description": self.cast_description,
            "attack_roll": self.attack_roll,
            "damage": self.damage,
            "damage_type": self.damage_type,
            "target_count": self.target_count,
            "conditions": [c.value if hasattr(c, 'value') else str(c) for c in (self.conditions or [])],
            "success_text": self.success_text,
            "failure_text": self.failure_text
        }

class CastTimeEffect(CustomEffect):
    """
    Handles complex moves with multiple phases.
    
    Features:
    - Proper state transitions
    - Phase-specific messaging
    - Combat log integration
    - Duration tracking per phase
    """
    def __init__(self, name: str, cast_time: int, description: str, **kwargs):
        # Initialize with first phase duration
        super().__init__(
            name=name,
            duration=cast_time,
            description=description,
            permanent=False,
            bullets=[]
        )
        self.category = EffectCategory.STATUS
        self.state = EffectState.CASTING if cast_time else EffectState.ACTIVE
        self._cast_time = cast_time
        self._duration = kwargs.get('next_duration')
        self._cooldown = kwargs.get('cooldown')
        self.cast_description = kwargs.get('cast_description', '')
        self.params = kwargs.get('params')
        
        # Track remaining time for each phase
        self._remaining = {
            EffectState.CASTING: cast_time,
            EffectState.ACTIVE: kwargs.get('next_duration'),
            EffectState.COOLDOWN: kwargs.get('cooldown')
        }
        
        # Initialize bullets for each state
        self._bullets = {
            EffectState.CASTING: [description] if description else [],
            EffectState.ACTIVE: [description] if description else [],
            EffectState.COOLDOWN: []
        }

    def get_phase_emoji(self) -> str:
        """Get emoji for current phase"""
        return {
            EffectState.CASTING: "✨",
            EffectState.ACTIVE: "✨", 
            EffectState.COOLDOWN: "⏳",
            EffectState.COMPLETE: "✨"
        }.get(self.state, "✨")
        
    def _update_remaining_time(self, current_round: int, turn_name: str) -> bool:
        """
        Update remaining time for current phase.
        Returns True if phase should end.
        """
        if self.state == EffectState.COMPLETE:
            return False
            
        # Only update on affected character's turn
        if turn_name != self.timing.start_turn:
            return False
            
        current = self._remaining[self.state]
        if current is None:  # Handle permanent effects
            return False
            
        current -= 1
        self._remaining[self.state] = current
        return current <= 0

    def _transition_state(self) -> Optional[str]:
        """
        Handle state transitions.
        Returns transition message if state changed.
        """
        if self.state == EffectState.CASTING:
            self.state = EffectState.ACTIVE
            self._duration = self._remaining[EffectState.ACTIVE]
            return f"{self.name} activates!"
            
        elif self.state == EffectState.ACTIVE:
            if self._remaining[EffectState.COOLDOWN]:
                self.state = EffectState.COOLDOWN
                self._duration = self._remaining[EffectState.COOLDOWN]
                return f"{self.name} enters cooldown"
            else:
                self.state = EffectState.COMPLETE
                return f"{self.name} has ended"
                
        elif self.state == EffectState.COOLDOWN:
            self.state = EffectState.COMPLETE
            return f"{self.name} cooldown has ended"
            
        return None

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process start of turn effects"""
        if character.name != turn_name:
            return []
            
        emoji = self.get_phase_emoji()
        details = []

        if self.state == EffectState.CASTING:
            # Default to "prepares" if no cast description
            msg = f"{character.name} {self.cast_description or 'prepares'} {self.name}"
            
            # Only add turn count if turns remain and they're not None
            if self._remaining[self.state] is not None:
                details.append(f"Cast Time: {self._remaining[self.state]} turn{'s' if self._remaining[self.state] != 1 else ''} remaining")
            
            # Add any bullet points that exist
            if self._bullets[self.state]:
                details.extend(self._bullets[self.state])
            
        elif self.state == EffectState.ACTIVE:
            msg = f"{self.name} continues"
            
            # Only add duration for non-None remaining turns
            if self._remaining[self.state] is not None:
                details.append(f"Duration: {self._remaining[self.state]} turn{'s' if self._remaining[self.state] != 1 else ''} remaining")
            
            # Add any bullet points that exist
            if self._bullets[self.state]:
                details.extend(self._bullets[self.state])
            
        elif self.state == EffectState.COOLDOWN:
            msg = f"{self.name} Cooldown"
            if self._remaining[self.state] is not None:
                details.append(f"{self._remaining[self.state]} turn{'s' if self._remaining[self.state] != 1 else ''} remaining")
            
        else:
            return []

        # Only return messages if we have details
        if details:
            return [self.format_effect_message(msg, details)]
        # Otherwise just return the basic message
        return [self.format_effect_message(msg)]

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process end of turn effects and state transitions"""
        if character.name != turn_name:
            return []

        messages = []
        should_transition = self._update_remaining_time(round_number, turn_name)

        if should_transition:
            if transition_msg := self._transition_state():
                messages.append(self.format_effect_message(transition_msg))
                
                # Add follow-up details for new state
                if self.state == EffectState.ACTIVE and self._bullets[self.state]:
                    messages.extend([
                        self.format_effect_message(
                            "Effect Details",
                            self._bullets[self.state]
                        )
                    ])
        else:
            # Normal turn end update
            if self.state != EffectState.COMPLETE:
                remaining = self._remaining[self.state]
                if remaining is not None:
                    state_msg = {
                        EffectState.CASTING: f"{self.name} continues casting",
                        EffectState.ACTIVE: f"{self.name} continues",
                        EffectState.COOLDOWN: f"{self.name} cooldown continues"
                    }[self.state]
                    
                    details = []
                    if remaining > 0:
                        details.append(f"{remaining} turn{'s' if remaining != 1 else ''} remaining")
                    if self._bullets[self.state]:
                        details.extend(self._bullets[self.state])
                        
                    messages.append(self.format_effect_message(state_msg, details))

        return messages

    def on_expire(self, character) -> str:
        """Handle effect expiry"""
        if transition_msg := self._transition_state():
            return self.format_effect_message(transition_msg)
        return self.format_effect_message(f"{self.name} has ended")

    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        # Create base data
        data = {
            "name": self.name,
            "duration": self._duration,
            "description": self.description,
            "permanent": self.permanent,
            "category": self.category.value if self.category else None,
            "timing": self.timing.__dict__ if self.timing else None,
            "state": self.state.value,
            "remaining": {k.value: v for k, v in self._remaining.items()},
            "bullets": {k.value: v for k, v in self._bullets.items()},
            "cast_description": self.cast_description
        }
        
        # Safely add params if they exist
        if hasattr(self, 'params'):
            if hasattr(self.params, 'to_dict'):
                data["params"] = self.params.to_dict()
            elif self.params is not None:
                data["params"] = self.params
        
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'CastTimeEffect':
        """Create from dictionary data"""
        effect = cls(
            name=data['name'],
            cast_time=data.get('remaining', {}).get(EffectState.CASTING.value),
            description=data.get('description', ''),
            next_duration=data.get('remaining', {}).get(EffectState.ACTIVE.value),
            cooldown=data.get('remaining', {}).get(EffectState.COOLDOWN.value),
            cast_description=data.get('cast_description'),
            params=data.get('params')
        )
        
        # Restore state
        effect.state = EffectState(data['state'])
        effect._remaining = {
            EffectState(k): v for k, v in data.get('remaining', {}).items()
        }
        effect._bullets = {
            EffectState(k): v for k, v in data.get('bullets', {}).items()
        }
        
        if timing_data := data.get('timing'):
            effect.timing = EffectTiming(**timing_data)
            
        return effect

class CompoundMove:
    """Handles complex moves with multiple components"""
    
    def __init__(self, params: MoveParameters):
        self.params = params
        self.description_bullets = [d.strip() for d in params.description.split(';')]
        
    async def validate_resources(self, character) -> tuple[bool, str]:
        """Check if character has required resources"""
        if self.params.hp_cost > 0:
            if character.resources.current_hp <= self.params.hp_cost:
                return False, f"Not enough HP ({character.resources.current_hp}/{self.params.hp_cost})"
                
        if self.params.mp_cost > 0:
            if character.resources.current_mp < self.params.mp_cost:
                return False, f"Not enough MP ({character.resources.current_mp}/{self.params.mp_cost})"
                
        can_use, reason = character.can_use_move(self.params.star_cost, self.params.name)
        if not can_use:
            return False, reason
            
        return True, ""
        
    def consume_resources(self, character) -> None:
        """Consume move resources from character"""
        if self.params.hp_cost != 0:
            character.resources.current_hp = max(
                0,
                min(
                    character.resources.current_hp - self.params.hp_cost,
                    character.resources.max_hp
                )
            )
                
        if self.params.mp_cost != 0:
            character.resources.current_mp = max(
                0,
                min(
                    character.resources.current_mp - self.params.mp_cost,
                    character.resources.max_mp
                )
            )
                
        character.use_move_stars(self.params.star_cost, self.params.name)

    async def process_attack(self, source, targets) -> tuple[bool, str, List[str]]:
        """Process attack rolls and damage"""
        try:
            if not self.params.attack_roll:
                return True, "", []

            damage_components = []
            if self.params.damage and self.params.damage_type:
                damage_components.append(DamageComponent(
                    roll_expression=self.params.damage,
                    damage_type=self.params.damage_type,
                    character=source
                ))
                
            params = AttackParameters(
                roll_expression=self.params.attack_roll,
                character=source,
                targets=targets,
                damage_components=damage_components,
                aoe_mode='multi' if self.params.target_count > 1 else 'single',
                reason=self.params.name
            )
            
            results = await AttackCalculator.process_attacks(params)
            
            hit = any(result.hit for result in results)
            messages = []
            
            for result in results:
                if result.hit:
                    crit_msg = "💥 CRITICAL HIT!" if result.is_crit else None
                    damage_parts = []
                    
                    for damage_roll in result.damage_rolls:
                        emoji = {
                            'fire': '🔥', 'cold': '❄️', 'lightning': '⚡',
                            'force': '✨', 'radiant': '☀️', 'necrotic': '💀',
                            'acid': '🧪', 'poison': '☠️', 'psychic': '🧠',
                            'thunder': '🔊'
                        }.get(damage_roll.type.lower(), '⚔️')
                        
                        damage_parts.append(f"{emoji} {damage_roll.amount} {damage_roll.type}")
                    
                    # Format damage message
                    if damage_parts:
                        damage_msg = f"{result.target_name} takes " + ", ".join(damage_parts)
                        messages.append(self.format_effect_message(damage_msg))
                    
                    if crit_msg:
                        messages.append(self.format_effect_message(crit_msg))
                        
            return hit, results[0].message if results else "", messages
            
        except Exception as e:
            logger.error(f"Error processing attack: {str(e)}", exc_info=True)
            return False, str(e), []

    def create_cast_effect(self, duration: Optional[int] = None) -> BaseEffect:
        """Create effect for the move"""
        # Use provided duration or parameters
        cast_time = duration or self.params.cast_time
        
        # For moves that activate immediately
        if not cast_time and self.params.duration:
            effect = CastTimeEffect(
                name=self.params.name,
                cast_time=None,  # No cast time
                description=self.params.description,
                next_duration=self.params.duration,
                cooldown=self.params.cooldown,
                cast_description=self.params.cast_description,
                params=self.params
            )
            effect.state = EffectState.ACTIVE
            return effect
            
        # For pure cooldown moves
        if not cast_time and not self.params.duration and self.params.cooldown:
            effect = CastTimeEffect(
                name=self.params.name,
                cast_time=None,
                description=self.params.description,
                cooldown=self.params.cooldown,
                cast_description=self.params.cast_description,
                params=self.params
            )
            effect.state = EffectState.COOLDOWN
            return effect

        # Normal case with cast time
        return CastTimeEffect(
            name=self.params.name,
            cast_time=cast_time,
            description=self.params.description,
            next_duration=self.params.duration,
            cooldown=self.params.cooldown,
            cast_description=self.params.cast_description,
            params=self.params
        )

    def apply_conditions(self, target, duration: Optional[int] = None) -> str:
        """Apply move conditions to target"""
        if not self.params.conditions:
            return ""
            
        effect = ConditionEffect(
            conditions=self.params.conditions,
            duration=duration
        )
        
        return target.add_effect(effect)
        
    def get_feedback_message(self, hit: bool) -> str:
        """Get appropriate feedback message based on hit/miss"""
        if hit:
            if self.params.success_text:
                return self.params.success_text
            return f"{self.params.name} hits!"
        else:
            if self.params.failure_text:
                return self.params.failure_text
            return f"{self.params.name} misses!"