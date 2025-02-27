"""
## src/core/effects/move.py
Move Effect System Implementation

Features:
- Phase-based duration tracking (cast -> active -> cooldown)
- Resource cost validation
- Attack roll processing with stat mods
- Multi-target support
- Heat stack generation

Implementation Notes:
- Always maintain phase order: cast -> active -> cooldown
- Resource costs apply on initial cast
- Combat rolls integrated with phase system
- Clear message formatting with consistent backticks
"""

import re
from typing import Optional, List, Dict, Any, Tuple, Set
from enum import Enum
from dataclasses import dataclass, field
import logging

from core.effects.base import BaseEffect, EffectCategory, EffectTiming
from core.effects.condition import ConditionType, ConditionEffect
from utils.advanced_dice.attack_calculator import AttackCalculator, AttackParameters
from utils.advanced_dice.calculator import DiceCalculator
from core.character import StatType

logger = logging.getLogger(__name__)

class MoveState(Enum):
    """Possible states for a move effect"""
    INSTANT = "instant"     # No cast time or duration
    CASTING = "casting"     # In cast time phase
    ACTIVE = "active"      # Active duration
    COOLDOWN = "cooldown"  # In cooldown phase

class RollTiming(Enum):
    """When to process attack/damage rolls"""
    INSTANT = "instant"    # Roll immediately on use
    ACTIVE = "active"     # Roll when active phase starts
    PER_TURN = "per_turn" # Roll each turn during duration

@dataclass
class PhaseInfo:
    """Tracks state and timing for a single move phase"""
    duration: int
    turns_completed: int = 0
    
    def start(self, round_number: int):
        """Reset phase tracking"""
        self.turns_completed = 0
    
    def complete_turn(self, turn_name: str, effect_owner: str) -> bool:
        """Complete a turn if it belongs to effect owner"""
        if turn_name == effect_owner:
            self.turns_completed += 1
        return self.turns_completed >= self.duration

class MoveEffect(BaseEffect):
    """
    Handles move execution with phase-based state tracking.
    Each state (cast/active/cooldown) is a separate phase with its own timing.
    """
    def __init__(
            self,
            name: str,
            description: str,
            star_cost: int = 0,
            mp_cost: int = 0,
            hp_cost: int = 0,
            cast_time: Optional[int] = None,
            duration: Optional[int] = None,
            cooldown: Optional[int] = None,
            cast_description: Optional[str] = None,
            attack_roll: Optional[str] = None,
            damage: Optional[str] = None,
            crit_range: int = 20,
            save_type: Optional[str] = None,
            save_dc: Optional[str] = None,
            half_on_save: bool = False,
            conditions: Optional[List[ConditionType]] = None,
            roll_timing: RollTiming = RollTiming.ACTIVE,
            uses: Optional[int] = None,
            targets: Optional[List['Character']] = None,
            enable_heat_tracking: bool = False
        ):
            # Set initial duration based on first phase
            initial_duration = cast_time if cast_time else duration
            if initial_duration is None:
                initial_duration = cooldown if cooldown else 1  # Default to 1 for INSTANT
                
            super().__init__(
                name=name,
                duration=initial_duration,
                permanent=False,
                category=EffectCategory.STATUS,
                description=description,
                handles_own_expiry=True
            )
            
            # Move costs and limits
            self.star_cost = max(0, star_cost)
            self.mp_cost = mp_cost
            self.hp_cost = hp_cost
            self.uses = uses
            self.uses_remaining = uses
            self.cast_description = cast_description
            
            # Combat parameters
            self.attack_roll = attack_roll
            self.damage = damage
            self.crit_range = crit_range
            self.save_type = save_type
            self.save_dc = save_dc
            self.half_on_save = half_on_save
            self.conditions = conditions or []
            
            # Handle roll timing enum or string
            if isinstance(roll_timing, str):
                try:
                    self.roll_timing = RollTiming(roll_timing)
                except ValueError:
                    self.roll_timing = RollTiming.ACTIVE
            else:
                self.roll_timing = roll_timing
            
            # Target tracking
            self.targets = targets or []  
            self.targets_hit: Set[str] = set()
            self.attacks_this_turn = 0
            self.last_roll_result = None
            
            # Heat tracking (optional)
            self.enable_heat_tracking = enable_heat_tracking
            self.heat_stacks = 0
            
            # Phase tracking
            self.phases = {
                MoveState.CASTING: PhaseInfo(cast_time) if cast_time else None,
                MoveState.ACTIVE: PhaseInfo(duration) if duration else None,
                MoveState.COOLDOWN: PhaseInfo(cooldown) if cooldown else None
            }
            
            # Set initial state
            if cast_time:
                self.state = MoveState.CASTING
            elif duration:
                self.state = MoveState.ACTIVE
            elif cooldown:
                self.state = MoveState.COOLDOWN
            else:
                self.state = MoveState.INSTANT
                
            # Prevent duplicate processing
            self.last_processed_round = None
            self.last_processed_turn = None
            self.initial_resources_applied = False

    def _get_emoji(self) -> str:
        """Get state-specific emoji"""
        return {
            MoveState.INSTANT: "⚡",
            MoveState.CASTING: "✨",
            MoveState.ACTIVE: "🌟",
            MoveState.COOLDOWN: "⏳"
        }.get(self.state, "✨")

    def _start_phase(self, round_number: int):
        """Start current phase tracking"""
        if phase := self.phases.get(self.state):
            phase.start(round_number)

    def _transition_state(self) -> Optional[str]:
        """
        Handle state transitions and phase duration resets.
        Returns a message if the state changes, None otherwise.
        
        This improved version ensures:
        1. Proper phase reset when transitioning
        2. Correct duration tracking between phases
        3. Clear messaging for state changes
        """
        if self.state == MoveState.INSTANT:
            return None

        next_state = None
        message = None
        
        # Find next valid state
        if self.state == MoveState.CASTING:
            if self.phases.get(MoveState.ACTIVE):
                next_state = MoveState.ACTIVE
                message = f"{self.name} activates!"
            elif self.phases.get(MoveState.COOLDOWN):
                next_state = MoveState.COOLDOWN
                message = f"{self.name} enters cooldown"
            else:
                message = f"{self.name} completes"
                
        elif self.state == MoveState.ACTIVE:
            if self.phases.get(MoveState.COOLDOWN):
                next_state = MoveState.COOLDOWN
                message = f"{self.name} enters cooldown"
            else:
                message = f"{self.name} wears off"
                
        elif self.state == MoveState.COOLDOWN:
            message = f"{self.name} cooldown ended"
        
        # Update state if transitioning
        if next_state:
            # Store old state for logging
            old_state = self.state
            
            # Update state
            self.state = next_state
            
            # Reset phase tracking for the new phase
            if phase := self.phases.get(next_state):
                phase.turns_completed = 0
                
                # Reset timing information for duration tracking
                if hasattr(self, 'timing') and self.timing:
                    # Start counting from current round
                    if hasattr(self, 'last_processed_round') and self.last_processed_round:
                        self.timing.start_round = self.last_processed_round
                        
                    # Set duration based on the new phase
                    self.timing.duration = phase.duration
            
            # Log transition for debugging
            print(f"Move '{self.name}' transitioned from {old_state} to {next_state}")
        
        return message
 
    def get_turn_start_text(self, character) -> str:
        """
        Get status text for turn announcement embed.
        Shows current state and relevant details.
        """
        if self.state == MoveState.INSTANT:
            return None
            
        # Don't show cooldowns in turn announcement
        if self.state == MoveState.COOLDOWN:
            return None
            
        lines = []
        phase = self.phases.get(self.state)
        
        # Build status message
        if self.state == MoveState.CASTING:
            lines.append(f"{character.name} continues casting {self.name}")
            if phase:
                remaining = phase.duration - phase.turns_completed
                lines.append(f"Cast Time: {remaining} turn(s) remaining")
            if self.star_cost > 0:
                lines.append(f"Star Cost: {self.star_cost} per turn")
                
        elif self.state == MoveState.ACTIVE:
            lines.append(f"{self.name} continues")
            if phase:
                remaining = phase.duration - phase.turns_completed
                lines.append(f"Duration: {remaining} turn(s) remaining")
            if self.description:
                lines.append(self.description)
                
        return self.format_effect_message(
            lines[0],
            lines[1:] if len(lines) > 1 else None
        )

    def get_turn_end_text(self, character) -> Optional[str]:
        """
        Get update text for turn end embed.
        Shows state transitions and important changes.
        """
        if self.state == MoveState.INSTANT:
            return None
            
        phase = self.phases.get(self.state)
        if not phase:
            return None
            
        remaining = phase.duration - phase.turns_completed
        
        # Show cooldown status for entire duration
        if self.state == MoveState.COOLDOWN:
            if remaining > 0:
                return self.format_effect_message(
                    f"{self.name} Cooldown",
                    [f"{remaining} turn{'s' if remaining != 1 else ''} remaining"]
                )
            else:
                return self.format_effect_message(f"{self.name} cooldown has ended")
                
        # Handle phase transitions
        if remaining <= 0:
            msg = self._transition_state()
            if msg:
                return self.format_effect_message(msg)
                
        return None

    def can_use(self, round_number: Optional[int] = None) -> tuple[bool, Optional[str]]:
        """Check if move can be used based on cooldown and uses"""
        # Check if currently in cooldown phase
        if self.state == MoveState.COOLDOWN:
            if phase := self.phases.get(self.state):
                remaining = phase.duration - phase.turns_completed
                return False, f"On cooldown ({remaining} turns remaining)"
        
        # Check uses if tracked
        if self.uses is not None:
            if self.uses_remaining is None:
                self.uses_remaining = self.uses
            if self.uses_remaining <= 0:
                return False, "No uses remaining"
        
        return True, None

    def _process_attack(self, source: 'Character', force_roll: bool = False) -> List[str]:
        """
        Process attack roll and damage if needed.
        Returns list of messages for each target.
        """
        # Skip if no attack roll defined
        if not self.attack_roll:
            return []
            
        # Check if we should roll based on timing
        should_roll = force_roll
        if not should_roll:
            if self.roll_timing == RollTiming.INSTANT:
                should_roll = self.state == MoveState.INSTANT
            elif self.roll_timing == RollTiming.ACTIVE:
                should_roll = self.state == MoveState.ACTIVE
            elif self.roll_timing == RollTiming.PER_TURN:
                should_roll = True
                
        if not should_roll:
            return []

        # Track attack count
        if not hasattr(self, 'attacks_this_turn'):
            self.attacks_this_turn = 0
        self.attacks_this_turn += 1

        messages = []
        
        # Log the attack attempt for combat log
        if hasattr(source, 'combat_logger') and source.combat_logger:
            source.combat_logger.add_event(
                "ATTACK_ATTEMPTED",
                f"{source.name} attacks with {self.name}",
                source.name,
                {
                    "move_name": self.name,
                    "targets": [t.name for t in self.targets] if self.targets else [],
                    "attack_roll": self.attack_roll,
                    "damage": self.damage
                }
            )
        
        # Handle no targets case
        if not self.targets:
            # Set up attack parameters
            params = AttackParameters(
                roll_expression=self.attack_roll,
                character=source,
                targets=None,
                damage_str=self.damage,
                crit_range=self.crit_range,
                reason=self.name
            )
            
            # Process attack
            message, _ = AttackCalculator.process_attack(params)
            messages.append(message)
            return messages
        
        # Process each target separately
        for target in self.targets:
            # Set up attack parameters
            params = AttackParameters(
                roll_expression=self.attack_roll,
                character=source,
                targets=[target],  # Single target for this roll
                damage_str=self.damage,
                crit_range=self.crit_range,
                reason=self.name
            )
            
            # Process attack
            message, result = AttackCalculator.process_attack(params)
            
            # Handle hit tracking
            hit = False
            if "**HIT!**" in message or "**CRITICAL HIT!**" in message:
                hit = True
                self.targets_hit.add(target.name)
                
                # Log hit for combat log
                if hasattr(source, 'combat_logger') and source.combat_logger:
                    source.combat_logger.add_event(
                        "ATTACK_HIT",
                        f"{source.name} hits {target.name} with {self.name}",
                        target.name,
                        {
                            "move_name": self.name,
                            "damage_dealt": result.get("damage_dealt", 0),
                            "is_critical": "**CRITICAL HIT!**" in message,
                            "attack_roll_value": result.get("attack_roll_value", 0)
                        }
                    )
            else:
                # Log miss for combat log
                if hasattr(source, 'combat_logger') and source.combat_logger:
                    source.combat_logger.add_event(
                        "ATTACK_MISS",
                        f"{source.name} misses {target.name} with {self.name}",
                        target.name,
                        {
                            "move_name": self.name,
                            "attack_roll_value": result.get("attack_roll_value", 0),
                            "target_ac": target.defense.current_ac
                        }
                    )
            
            # Handle heat tracking if enabled
            if self.enable_heat_tracking and hit:
                # Source heat (attunement)
                if not hasattr(source, 'heat_stacks'):
                    source.heat_stacks = 0
                source.heat_stacks += 1
                
                # Target heat (vulnerability)
                if not hasattr(target, 'heat_stacks'):
                    target.heat_stacks = 0
                target.heat_stacks += 1
            
            messages.append(message)
        
        return messages

    def _apply_resource_costs(self, character) -> List[str]:
        """Apply resource costs and return messages"""
        messages = []
        
        # Apply MP cost
        if self.mp_cost != 0:
            # Handle MP gain or loss
            if self.mp_cost > 0:
                character.resources.current_mp = max(0, character.resources.current_mp - self.mp_cost)
                messages.append(f"💙 Uses {self.mp_cost} MP")
            else:
                character.resources.current_mp = min(
                    character.resources.max_mp, 
                    character.resources.current_mp - self.mp_cost  # Negative cost = gain
                )
                messages.append(f"💙 Gains {abs(self.mp_cost)} MP")
        
        # Apply HP cost
        if self.hp_cost != 0:
            # Handle HP gain or loss
            if self.hp_cost > 0:
                character.resources.current_hp = max(0, character.resources.current_hp - self.hp_cost)
                messages.append(f"❤️ Uses {self.hp_cost} HP")
            else:
                character.resources.current_hp = min(
                    character.resources.max_hp, 
                    character.resources.current_hp - self.hp_cost  # Negative cost = gain
                )
                messages.append(f"❤️ Heals {abs(self.hp_cost)} HP")
        
        # Track that resources have been applied
        self.initial_resources_applied = True
        
        return messages

    def on_apply(self, character, round_number: int) -> str:
        """Initial effect application"""
        self.initialize_timing(round_number, character.name)
        self._start_phase(round_number)
        
        lines = []
        details = []
        cost_messages = []
        
        # Apply resource costs
        cost_messages = self._apply_resource_costs(character)
        
        # Build initial message
        if self.cast_description:
            lines.append(f"{character.name} {self.cast_description} {self.name}")
        else:
            if self.state == MoveState.INSTANT:
                lines.append(f"{character.name} uses {self.name}")
            elif self.state == MoveState.CASTING:
                lines.append(f"{character.name} begins casting {self.name}")
            else:
                lines.append(f"{character.name} uses {self.name}")
        
        # Add phase info
        if self.state == MoveState.CASTING:
            if phase := self.phases.get(self.state):
                details.append(f"Cast Time: {phase.duration} turns")
        elif self.state == MoveState.ACTIVE:
            if phase := self.phases.get(self.state):
                details.append(f"Duration: {phase.duration} turns")
        
        # Add cost details
        if self.star_cost > 0:
            details.append(f"⭐ {self.star_cost} stars")
            
        # Add target details if any
        if self.targets:
            details.append(f"Targets: {', '.join(t.name for t in self.targets)}")
                    
        # Add description
        if self.description:
            details.append(self.description)
        
        # Process instant attack if needed
        attack_messages = []
        if self.attack_roll and (self.roll_timing == RollTiming.INSTANT or self.state == MoveState.INSTANT):
            attack_messages = self._process_attack(character, force_roll=True)
            
        # Format primary message with details
        primary_message = self.format_effect_message(
            lines[0],
            details if details else None
        )
        
        # If we have attack messages, add them
        if attack_messages:
            return primary_message + "\n" + "\n".join(attack_messages)
        else:
            return primary_message

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process start of turn effects including resource costs and state updates"""
        if character.name != turn_name:
            return []

        messages = []
        current_phase = self.phases.get(self.state)
        
        # Show active state effects
        if self.state == MoveState.ACTIVE:
            if self.description:
                messages.append(self.format_effect_message(
                    f"{self.name} active",
                    [self.description]
                ))
            
            # Process per-turn resource costs - TODO: Add config for per-turn costs
            
            # Process attack if timing is per_turn
            if self.attack_roll and self.roll_timing == RollTiming.PER_TURN:
                attack_msgs = self._process_attack(character, force_roll=True)
                if attack_msgs:
                    messages.extend(attack_msgs)
                    
        elif self.state == MoveState.CASTING:
            messages.append(self.format_effect_message(
                f"Casting {self.name}",
                [f"{current_phase.duration - current_phase.turns_completed} turns remaining"]
            ))
            
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Handle phase transitions and duration tracking.
        Improved version with better cooldown message handling.
        """
        if character.name != turn_name:
            return []
            
        messages = []
        phase = self.phases.get(self.state)
        
        # Skip processing if no current phase
        if not phase:
            return []
            
        # Track processing round for transitions
        self.last_processed_round = round_number
        self.last_processed_turn = turn_name
            
        # Complete turn for current phase
        phase_complete = phase.complete_turn(turn_name, character.name)
        
        # Handle phase transitions
        if phase_complete:
            # Handle transition to ACTIVE - process attack if needed
            if self.state == MoveState.CASTING and self.attack_roll and self.roll_timing == RollTiming.ACTIVE:
                attack_msgs = self._process_attack(character, force_roll=True)
                if attack_msgs:
                    messages.extend(attack_msgs)
            
            # Transition to next phase
            transition_msg = self._transition_state()
            if transition_msg:
                messages.append(self.format_effect_message(transition_msg))
            
            # If transitioning to COOLDOWN, remove from targets
            if self.state == MoveState.COOLDOWN:
                self.targets = []
                
            # If all phases completed, mark for removal
            if (self.state == MoveState.COOLDOWN and phase_complete) or (
                self.state == MoveState.ACTIVE and phase_complete and not self.phases.get(MoveState.COOLDOWN)):
                # Mark effect for removal by setting duration to 0
                if hasattr(self, 'timing'):
                    self.timing.duration = 0
        else:
            # Format appropriate message based on state
            if self.state == MoveState.CASTING:
                remaining = phase.duration - phase.turns_completed
                messages.append(self.format_effect_message(
                    f"Casting {self.name}",
                    [f"{remaining} turns remaining"]
                ))
                    
            elif self.state == MoveState.ACTIVE:
                remaining = phase.duration - phase.turns_completed
                messages.append(self.format_effect_message(
                    f"{self.name} continues",
                    [f"{remaining} turns remaining"]
                ))
                    
            elif self.state == MoveState.COOLDOWN:
                remaining = phase.duration - phase.turns_completed
                if remaining > 0:  # Only show message if cooldown is still active
                    messages.append(self.format_effect_message(
                        f"{self.name} cooldown",
                        [f"{remaining} turns remaining"]
                    ))
                else:
                    # If this is the last turn of cooldown, prepare for removal
                    if hasattr(self, 'timing'):
                        self.timing.duration = 0
        
        return messages
        
    @property
    def is_expired(self) -> bool:
        """
        Check if move effect is fully expired.
        
        A move is expired when:
        1. It's an instant move (no phases)
        2. All phases have completed their duration
        3. We're in the final phase and it's complete
        """
        if self.state == MoveState.INSTANT:
            return True
            
        current_phase = self.phases.get(self.state)
        if not current_phase:
            return True
            
        # Check if we still have future phases
        if self.state == MoveState.CASTING:
            return False  # Still have active/cooldown phase
        elif self.state == MoveState.ACTIVE:
            if self.phases.get(MoveState.COOLDOWN):
                return False  # Still have cooldown phase
                
        # Check current phase completion
        return current_phase.turns_completed >= current_phase.duration

    def _process_saves(self, source: 'Character', targets_hit: Set[str]) -> List[str]:
        """Process saving throws for affected targets"""
        if not self.save_type or not self.save_dc:
            return []
            
        messages = []
        for target_name in targets_hit:
            target = next((t for t in self.targets if t.name == target_name), None)
            if not target:
                continue
                
            # Calculate save DC
            dc = 8  # Base DC
            if '+prof' in self.save_dc:
                dc += source.base_proficiency
            # Add stat modifiers
            for stat in StatType:
                if f'+{stat.value}' in self.save_dc:
                    dc += source.stats.get_modifier(stat)
                    
            # Build roll expression
            save_expr = f"1d20+({self.save_type})"
            
            # Roll save
            total, formatted, _ = DiceCalculator.calculate_complex(
                save_expr,
                character=target,
                concise=True
            )
            
            # Check result
            saved = total >= dc
            messages.append(
                self.format_effect_message(
                    f"{target_name}'s {self.save_type.upper()} Save: {formatted} vs DC {dc}",
                    [f"{'✅ Success' if saved else '❌ Failure'}"]
                )
            )
            
            # Apply effects on failed save
            if not saved:
                # Apply conditions
                for condition in self.conditions:
                    effect = ConditionEffect(
                        [condition],
                        duration=self.duration
                    )
                    msg = target.add_effect(effect)
                    if msg:
                        messages.append(msg)
                        
                # Apply effects
                if self.half_on_save:
                    messages.append(f"• {target_name} takes full damage")
            
        return messages

    def on_expire(self, character) -> Optional[str]:
        """Handle move expiry"""
        if self.state == MoveState.INSTANT:
            return None
            
        return self.format_effect_message(f"{self.name} has ended")

    def to_dict(self) -> dict:
        """Convert to dictionary for storage with state preservation"""
        data = super().to_dict()
        
        # Save phase data with full state
        phase_data = {}
        for state, phase in self.phases.items():
            if phase:
                phase_data[state.value] = {
                    "duration": phase.duration,
                    "turns_completed": phase.turns_completed
                }
                
        # Save combat data
        combat_data = {}
        if self.attack_roll:
            combat_data["attack_roll"] = self.attack_roll
        if self.damage:
            combat_data["damage"] = self.damage
        if self.crit_range != 20:
            combat_data["crit_range"] = self.crit_range
        if self.save_type:
            combat_data["save_type"] = self.save_type
            combat_data["save_dc"] = self.save_dc
            combat_data["half_on_save"] = self.half_on_save
        if self.conditions:
            combat_data["conditions"] = [c.value for c in self.conditions]
        if self.roll_timing != RollTiming.ACTIVE:
            combat_data["roll_timing"] = self.roll_timing.value
            
        # Save heat and target state
        state_data = {}
        if self.heat_stacks:
            state_data["heat_stacks"] = self.heat_stacks
        if hasattr(self, 'attacks_this_turn'):
            state_data["attacks_this_turn"] = self.attacks_this_turn
            
        # Trim targets from data for more compact serialization
        target_names = [t.name for t in self.targets] if self.targets else []
        
        data.update({
            "star_cost": self.star_cost,
            "mp_cost": self.mp_cost,
            "hp_cost": self.hp_cost,
            "cast_description": self.cast_description,
            "uses": self.uses,
            "uses_remaining": self.uses_remaining,
            "state": self.state.value,
            "phases": phase_data,
            "combat": combat_data,
            "state_data": state_data,
            "target_names": target_names,
            "last_processed_round": self.last_processed_round,
            "last_processed_turn": self.last_processed_turn,
            "enable_heat_tracking": self.enable_heat_tracking
        })
        
        # Remove any None values to save space
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> 'MoveEffect':
        """Create from dictionary data"""
        try:
            # Extract phase durations first
            phase_data = data.get('phases', {})
            cast_time = None
            duration = None
            cooldown = None
            
            if cast_phase := phase_data.get(MoveState.CASTING.value, {}):
                cast_time = cast_phase.get('duration')
            if active_phase := phase_data.get(MoveState.ACTIVE.value, {}):
                duration = active_phase.get('duration')
            if cooldown_phase := phase_data.get(MoveState.COOLDOWN.value, {}):
                cooldown = cooldown_phase.get('duration')
            
            # Extract combat data
            combat_data = data.get('combat', {})
            attack_roll = combat_data.get('attack_roll')
            damage = combat_data.get('damage')
            crit_range = combat_data.get('crit_range', 20)
            save_type = combat_data.get('save_type')
            save_dc = combat_data.get('save_dc')
            half_on_save = combat_data.get('half_on_save', False)
            conditions = combat_data.get('conditions', [])
            roll_timing_str = combat_data.get('roll_timing', RollTiming.ACTIVE.value)
            
            # Create base effect
            effect = cls(
                name=data['name'],
                description=data.get('description', ''),
                star_cost=data.get('star_cost', 0),
                mp_cost=data.get('mp_cost', 0),
                hp_cost=data.get('hp_cost', 0),
                cast_time=cast_time,
                duration=duration,
                cooldown=cooldown,
                cast_description=data.get('cast_description'),
                attack_roll=attack_roll,
                damage=damage, 
                crit_range=crit_range,
                save_type=save_type,
                save_dc=save_dc,
                half_on_save=half_on_save,
                conditions=[ConditionType(c) for c in conditions] if conditions else [],
                roll_timing=roll_timing_str,
                uses=data.get('uses'),
                enable_heat_tracking=data.get('enable_heat_tracking', False)
            )
            
            # Restore state
            if state_value := data.get('state'):
                effect.state = MoveState(state_value)
                
            # Restore uses
            effect.uses_remaining = data.get('uses_remaining')
            
            # Restore phase progress
            for state_str, phase_info in phase_data.items():
                state = MoveState(state_str)
                if phase := effect.phases.get(state):
                    phase.turns_completed = phase_info.get('turns_completed', 0)
            
            # Restore timing information
            if timing_data := data.get('timing'):
                effect.timing = EffectTiming(**timing_data)
                
            # Restore state data
            if state_data := data.get('state_data', {}):
                effect.heat_stacks = state_data.get('heat_stacks', 0)
                if 'attacks_this_turn' in state_data:
                    effect.attacks_this_turn = state_data['attacks_this_turn']
            
            # Restore processing tracking
            effect.last_processed_round = data.get('last_processed_round')
            effect.last_processed_turn = data.get('last_processed_turn')
            effect.initial_resources_applied = data.get('initial_resources_applied', True)
            
            # We'll have to restore targets at runtime
            effect.targets = []
            effect.targets_hit = set(data.get('targets_hit', []))
                
            return effect
            
        except Exception as e:
            logger.error(f"Error reconstructing MoveEffect: {str(e)}")
            return None