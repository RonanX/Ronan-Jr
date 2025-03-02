"""
## src/core/effects/move.py

Move Effect System Implementation - Refactored Version

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
        """
        Complete a turn if it belongs to effect owner.
        Returns True if the phase is complete.
        
        Fixed: Only count a turn if it's the effect owner's turn
        """
        if turn_name == effect_owner:
            self.turns_completed += 1
            
        # A phase is complete when we've finished the correct number of turns
        return self.turns_completed >= self.duration

class PhaseManager:
    """
    Handles phase transitions and duration tracking for moves.
    This extracts the state management logic from MoveEffect.
    """
    def __init__(
        self,
        cast_time: Optional[int] = None,
        duration: Optional[int] = None,
        cooldown: Optional[int] = None,
    ):
        # Initialize phases
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
            
        self.marked_for_removal = False
        
    def get_current_phase(self) -> Optional[PhaseInfo]:
        """Get the current phase info"""
        return self.phases.get(self.state)
    
    def start_phase(self, round_number: int):
        """Start current phase tracking"""
        if phase := self.get_current_phase():
            phase.start(round_number)
    
    def complete_turn(self, turn_name: str, effect_owner: str) -> bool:
        """
        Process a completed turn for the current phase.
        Returns True if the phase is complete.
        
        Fixed: Ensure we're properly tracking turn completion
        """
        phase = self.get_current_phase()
        if not phase:
            return False
            
        # Delegate to PhaseInfo and return result
        return phase.complete_turn(turn_name, effect_owner)
    
    def transition_state(self) -> Optional[str]:
        """
        Handle state transitions between phases.
        Returns a message if the state changes, None otherwise.
        
        Fixed: Only transition when phase is actually complete
        """
        if self.state == MoveState.INSTANT:
            return None

        next_state = None
        message = None
        
        # Find next valid state
        if self.state == MoveState.CASTING:
            if self.phases.get(MoveState.ACTIVE):
                next_state = MoveState.ACTIVE
                message = "activates!"
            elif self.phases.get(MoveState.COOLDOWN):
                next_state = MoveState.COOLDOWN
                message = "enters cooldown"
            else:
                message = "completes"
                self.marked_for_removal = True
                
        elif self.state == MoveState.ACTIVE:
            if self.phases.get(MoveState.COOLDOWN):
                next_state = MoveState.COOLDOWN
                message = "enters cooldown"
            else:
                message = "wears off"
                self.marked_for_removal = True
                
        elif self.state == MoveState.COOLDOWN:
            message = "cooldown ended"
            self.marked_for_removal = True
        
        # Update state if transitioning
        if next_state:
            # Store old state for logging
            old_state = self.state
            
            # Update state
            self.state = next_state
            
            # Reset phase tracking for the new phase
            if phase := self.phases.get(next_state):
                phase.turns_completed = 0
            
            # Log transition for debugging
            logger.debug(f"Move transitioned from {old_state} to {next_state}")
        
        return message

    def is_expired(self) -> bool:
        """
        Check if move effect is fully expired.
        A move is expired when marked for removal or all phases complete.
        """
        if self.marked_for_removal:
            return True
            
        if self.state == MoveState.INSTANT:
            return True
            
        current_phase = self.phases.get(self.state)
        if not current_phase:
            return True
            
        # Check if we're in the final phase with no more transitions available
        if self.state == MoveState.COOLDOWN:
            return current_phase.turns_completed >= current_phase.duration
        elif self.state == MoveState.ACTIVE and not self.phases.get(MoveState.COOLDOWN):
            return current_phase.turns_completed >= current_phase.duration
        elif self.state == MoveState.CASTING and not self.phases.get(MoveState.ACTIVE) and not self.phases.get(MoveState.COOLDOWN):
            return current_phase.turns_completed >= current_phase.duration
            
        return False
    
    def get_remaining_turns(self) -> int:
        """Get the number of turns remaining in the current phase"""
        phase = self.get_current_phase()
        if not phase:
            return 0
        return max(0, phase.duration - phase.turns_completed)
    
    def to_dict(self) -> dict:
        """Convert phase manager to dictionary for storage"""
        phase_data = {}
        for state, phase in self.phases.items():
            if phase:
                phase_data[state.value] = {
                    "duration": phase.duration,
                    "turns_completed": phase.turns_completed
                }
                
        return {
            "state": self.state.value,
            "phases": phase_data,
            "marked_for_removal": self.marked_for_removal
        }
    
    @classmethod
    def from_dict(cls, data: dict, cast_time=None, duration=None, cooldown=None) -> 'PhaseManager':
        """Create from dictionary data"""
        manager = cls(cast_time, duration, cooldown)
        
        # Restore state
        if state_value := data.get('state'):
            manager.state = MoveState(state_value)
            
        # Restore phase progress
        phase_data = data.get('phases', {})
        for state_str, phase_info in phase_data.items():
            state = MoveState(state_str)
            if phase := manager.phases.get(state):
                phase.turns_completed = phase_info.get('turns_completed', 0)
                
        # Restore removal state
        manager.marked_for_removal = data.get('marked_for_removal', False)
        
        return manager

class CombatProcessor:
    """
    Handles attack rolls, damage processing, and target tracking.
    This extracts combat mechanics from MoveEffect.
    """
    def __init__(
        self,
        attack_roll: Optional[str] = None,
        damage: Optional[str] = None,
        crit_range: int = 20,
        save_type: Optional[str] = None,
        save_dc: Optional[str] = None,
        half_on_save: bool = False,
        conditions: Optional[List[ConditionType]] = None,
        roll_timing = RollTiming.ACTIVE,
        enable_heat_tracking: bool = False
    ):
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
        self.targets: List['Character'] = []
        self.targets_hit: Set[str] = set()
        self.attacks_this_turn = 0
        self.last_roll_result = None
        
        # Heat tracking
        self.enable_heat_tracking = enable_heat_tracking
        self.heat_stacks = 0
    
    def set_targets(self, targets: List['Character']):
        """Set the targets for this combat processor"""
        self.targets = targets or []
    
    def should_roll(self, state: MoveState, force_roll: bool = False) -> bool:
        """Determine if we should roll based on timing and state"""
        if force_roll:
            return True
            
        if self.roll_timing == RollTiming.INSTANT:
            return state == MoveState.INSTANT
        elif self.roll_timing == RollTiming.ACTIVE:
            return state == MoveState.ACTIVE
        elif self.roll_timing == RollTiming.PER_TURN:
            return True
            
        return False
    
    def process_attack(self, source: 'Character', move_name: str, state: MoveState, force_roll: bool = False) -> List[str]:
        """
        Process attack roll and damage if needed.
        Returns list of messages for each target.
        """
        # Skip if no attack roll defined
        if not self.attack_roll:
            return []
            
        # Check if we should roll based on timing
        if not self.should_roll(state, force_roll):
            return []

        # Track attack count
        self.attacks_this_turn += 1

        messages = []
        
        # Log the attack attempt for combat log
        if hasattr(source, 'combat_logger') and source.combat_logger:
            source.combat_logger.add_event(
                "ATTACK_ATTEMPTED",
                f"{source.name} attacks with {move_name}",
                source.name,
                {
                    "move_name": move_name,
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
                reason=move_name
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
                reason=move_name
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
                        f"{source.name} hits {target.name} with {move_name}",
                        target.name,
                        {
                            "move_name": move_name,
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
                        f"{source.name} misses {target.name} with {move_name}",
                        target.name,
                        {
                            "move_name": move_name,
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
    
    def clear_targets(self):
        """Clear all targets"""
        self.targets = []
    
    def to_dict(self) -> dict:
        """Convert combat processor to dictionary for storage"""
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
        state_data["attacks_this_turn"] = self.attacks_this_turn
        
        # Target names for storage
        target_names = [t.name for t in self.targets] if self.targets else []
        
        return {
            "combat": combat_data,
            "state_data": state_data,
            "target_names": target_names,
            "targets_hit": list(self.targets_hit),
            "enable_heat_tracking": self.enable_heat_tracking
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CombatProcessor':
        """Create from dictionary data"""
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
        enable_heat_tracking = data.get('enable_heat_tracking', False)
        
        # Normalize roll timing to handle both string and enum values
        if isinstance(roll_timing_str, str):
            # Already a string, processor constructor will convert it
            normalized_roll_timing = roll_timing_str
        else:  
            # This might happen if it was saved as a dict or something else
            try:
                normalized_roll_timing = RollTiming(str(roll_timing_str))
            except (ValueError, TypeError):
                normalized_roll_timing = RollTiming.ACTIVE
        
        # Create processor
        processor = cls(
            attack_roll=attack_roll,
            damage=damage,
            crit_range=crit_range,
            save_type=save_type,
            save_dc=save_dc,
            half_on_save=half_on_save,
            conditions=[ConditionType(c) for c in conditions] if conditions else [],
            roll_timing=normalized_roll_timing,
            enable_heat_tracking=enable_heat_tracking
        )
        
        # Restore state data
        if state_data := data.get('state_data', {}):
            processor.heat_stacks = state_data.get('heat_stacks', 0)
            processor.attacks_this_turn = state_data.get('attacks_this_turn', 0)
            
        # Restore targets hit
        processor.targets_hit = set(data.get('targets_hit', []))
        
        # Note: targets themselves will need to be restored at runtime
        return processor

class ResourceManager:
    """
    Handles resource costs and usage tracking for moves.
    This extracts resource management from MoveEffect.
    """
    def __init__(
        self,
        star_cost: int = 0,
        mp_cost: int = 0,
        hp_cost: int = 0,
        uses: Optional[int] = None,
    ):
        self.star_cost = max(0, star_cost)
        self.mp_cost = mp_cost
        self.hp_cost = hp_cost
        self.uses = uses
        self.uses_remaining = uses
        self.initial_resources_applied = False
    
    def apply_costs(self, character) -> List[str]:
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
    
    def use_move(self) -> bool:
        """
        Mark a move as used, tracking uses if applicable.
        Returns True if the move could be used, False if out of uses.
        """
        if self.uses is not None:
            if self.uses_remaining is None:
                self.uses_remaining = self.uses
                
            if self.uses_remaining <= 0:
                return False
                
            self.uses_remaining -= 1
            
        return True
    
    def to_dict(self) -> dict:
        """Convert resource manager to dictionary for storage"""
        return {
            "star_cost": self.star_cost,
            "mp_cost": self.mp_cost,
            "hp_cost": self.hp_cost,
            "uses": self.uses,
            "uses_remaining": self.uses_remaining,
            "initial_resources_applied": self.initial_resources_applied
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ResourceManager':
        """Create from dictionary data"""
        manager = cls(
            star_cost=data.get('star_cost', 0),
            mp_cost=data.get('mp_cost', 0),
            hp_cost=data.get('hp_cost', 0),
            uses=data.get('uses'),
        )
        manager.uses_remaining = data.get('uses_remaining')
        manager.initial_resources_applied = data.get('initial_resources_applied', True)
        return manager

class MoveEffect(BaseEffect):
    """
    Handles move execution with phase-based state tracking.
    Each state (cast/active/cooldown) is a separate phase with its own timing.
    
    This is a refactored version that uses helper classes to manage different aspects:
    - PhaseManager: Handles state transitions and phases
    - CombatProcessor: Handles attack rolls and targets
    - ResourceManager: Handles costs and usage
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
            # Initialize the phase manager first
            self.phase_manager = PhaseManager(cast_time, duration, cooldown)
            
            # Set initial duration based on first phase
            initial_duration = cast_time if cast_time else duration
            if initial_duration is None:
                initial_duration = cooldown if cooldown else 1  # Default to 1 for INSTANT
                
            # Initialize base effect using the duration from phase manager
            super().__init__(
                name=name,
                duration=initial_duration,
                permanent=False,
                category=EffectCategory.STATUS,
                description=description,
                handles_own_expiry=True
            )
            
            # Initialize helper components
            self.resource_manager = ResourceManager(star_cost, mp_cost, hp_cost, uses)
            self.combat_processor = CombatProcessor(
                attack_roll, damage, crit_range, save_type, save_dc, half_on_save,
                conditions, roll_timing, enable_heat_tracking
            )
            self.combat_processor.set_targets(targets)
            
            # Additional properties
            self.cast_description = cast_description
            
            # Tracking variables
            self.last_processed_round = None
            self.last_processed_turn = None
            
            # For convenience/backward compatibility
            self.state = self.phase_manager.state
            self.phases = self.phase_manager.phases

    def _get_emoji(self) -> str:
        """Get state-specific emoji"""
        return {
            MoveState.INSTANT: "⚡",
            MoveState.CASTING: "✨",
            MoveState.ACTIVE: "🌟",
            MoveState.COOLDOWN: "⏳"
        }.get(self.state, "✨")

    def _transition_state(self) -> Optional[str]:
        """
        Handle state transitions and phase duration resets.
        Returns a message if the state changes, None otherwise.
        
        This improved version ensures:
        1. Proper phase reset when transitioning
        2. Correct duration tracking between phases
        3. Clear messaging for state changes
        """
        # Get the transition message from the phase manager
        message = self.phase_manager.transition_state()
        
        # Update our reference to the current state
        self.state = self.phase_manager.state
        
        # If we're transitioning to a new phase, update timing
        if message:
            # If transitioning to COOLDOWN, remove targets
            if self.state == MoveState.COOLDOWN:
                self.combat_processor.clear_targets()
                
            # If marked for removal, set timing duration to 0
            if self.phase_manager.marked_for_removal:
                if hasattr(self, 'timing'):
                    self.timing.duration = 0
                    
            # Return the transition message with the move name
            return f"{self.name} {message}"
            
        return None

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
            lines.append(f"Casting {self.name}")
            if phase:
                remaining = max(0, phase.duration - phase.turns_completed)
                lines.append(f"{remaining} turns remaining")
                
                # Check if this is the last turn of casting
                if remaining == 0:
                    # We should transition immediately
                    transition_msg = self._transition_state()
                    if transition_msg:
                        return self.format_effect_message(transition_msg)
                
        elif self.state == MoveState.ACTIVE:
            lines.append(f"{self.name} active")
            
            # Add description as bullet points
            if self.description and lines:
                # Split description by semicolons for bullet points
                if ';' in self.description:
                    for part in self.description.split(';'):
                        part = part.strip()
                        if part:
                            lines.append(part)
                else:
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
                    f"{self.name} cooldown",
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
        if self.resource_manager.uses is not None:
            if self.resource_manager.uses_remaining is None:
                self.resource_manager.uses_remaining = self.resource_manager.uses
            if self.resource_manager.uses_remaining <= 0:
                return False, "No uses remaining"
        
        return True, None

    def on_apply(self, character, round_number: int) -> str:
        """Initial effect application"""
        self.initialize_timing(round_number, character.name)
        self.phase_manager.start_phase(round_number)
        
        # First part: Process costs and apply initial effect
        costs = []
        details = []
        timing_info = []
        
        # Apply resource costs
        resource_messages = self.resource_manager.apply_costs(character)
        for msg in resource_messages:
            if "MP" in msg:
                costs.append(f"💙 MP: {self.resource_manager.mp_cost if self.resource_manager.mp_cost > 0 else '-' + str(abs(self.resource_manager.mp_cost))}")
            elif "HP" in msg:
                if self.resource_manager.hp_cost > 0:
                    costs.append(f"❤️ HP: {self.resource_manager.hp_cost}")
                else:
                    costs.append(f"❤️ Heal: {abs(self.resource_manager.hp_cost)}")
        
        # Add star cost
        if self.resource_manager.star_cost > 0:
            costs.append(f"⭐ {self.resource_manager.star_cost}")
            
        # Add timing info
        if self.phases.get(MoveState.CASTING):
            cast_time = self.phases[MoveState.CASTING].duration
            timing_info.append(f"🔄 {cast_time}T Cast")
        if self.phases.get(MoveState.ACTIVE):
            duration = self.phases[MoveState.ACTIVE].duration
            timing_info.append(f"⏳ {duration}T Duration")
        if self.phases.get(MoveState.COOLDOWN):
            cooldown = self.phases[MoveState.COOLDOWN].duration
            timing_info.append(f"⌛ {cooldown}T Cooldown")
            
        # Format target info if any
        if self.combat_processor.targets:
            target_names = ", ".join(t.name for t in self.combat_processor.targets)
            details.append(f"Target{'s' if len(self.combat_processor.targets) > 1 else ''}: {target_names}")
            
        # Process attack based on timing
        if self.combat_processor.attack_roll and self.combat_processor.roll_timing == RollTiming.INSTANT:
            attack_messages = self.combat_processor.process_attack(character, self.name, self.state, force_roll=True)
            if attack_messages:
                details.extend(attack_messages)
                
        # Build the primary message
        if self.cast_description:
            main_message = f"{character.name} {self.cast_description} {self.name}"
        else:
            if self.state == MoveState.INSTANT:
                main_message = f"{character.name} uses {self.name}"
            elif self.state == MoveState.CASTING:
                main_message = f"{character.name} begins casting {self.name}"
            else:
                main_message = f"{character.name} uses {self.name}"
                
        # Build supplementary info parts
        info_parts = []
        
        # Add costs and timing
        if costs:
            info_parts.append(" | ".join(costs))
        if timing_info:
            info_parts.append(" | ".join(timing_info))
            
        # Format output
        if info_parts:
            main_message = f"{main_message} | {' | '.join(info_parts)}"
            
        # Create the primary formatted message
        formatted_message = self.format_effect_message(main_message)
            
        # Add bullets for details
        if details:
            detail_strings = []
            for detail in details:
                if not detail.startswith("•") and not detail.startswith("`"):
                    detail_strings.append(f"• `{detail}`")
                else:
                    detail_strings.append(detail)
                    
            return formatted_message + "\n" + "\n".join(detail_strings)
        else:
            return formatted_message

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process start of turn effects including resource costs and state updates"""
        # Store these values for debugging and state tracking
        self.last_processed_round = round_number
        self.last_processed_turn = turn_name
        
        # Only process effect changes on the owner's turn
        if character.name != turn_name:
            return []

        messages = []
        
        # First, check if we need to transition phases BEFORE showing any messages
        # This ensures we start the turn in the proper phase
        current_phase = self.phases.get(self.state)
        if current_phase and current_phase.turns_completed >= current_phase.duration:
            # We've already completed enough turns, transition immediately
            transition_msg = self._transition_state()
            if transition_msg:
                messages.append(self.format_effect_message(transition_msg))
                
                # If we transitioned to active, process attack
                if self.state == MoveState.ACTIVE and self.combat_processor.attack_roll and self.combat_processor.roll_timing == RollTiming.ACTIVE:
                    attack_msgs = self.combat_processor.process_attack(character, self.name, self.state, force_roll=True)
                    if attack_msgs:
                        messages.extend(attack_msgs)
                        
        # Now handle the current state (which might have just changed)
        if self.state == MoveState.ACTIVE:
            if self.description:
                # Only add active message if we didn't just transition
                if not messages:
                    remaining = 0
                    if phase := self.phases.get(self.state):
                        remaining = max(0, phase.duration - phase.turns_completed)
                    
                    active_msg = self.format_effect_message(
                        f"{self.name} active",
                        [self.description, f"{remaining} turns remaining"]
                    )
                    messages.append(active_msg)
            
            # Process per-turn resource costs - TODO: Add config for per-turn costs
            
            # Process attack if timing is per_turn
            if self.combat_processor.attack_roll and self.combat_processor.roll_timing == RollTiming.PER_TURN:
                attack_msgs = self.combat_processor.process_attack(character, self.name, self.state, force_roll=True)
                if attack_msgs:
                    messages.extend(attack_msgs)
                    
        elif self.state == MoveState.CASTING:
            current_phase = self.phases.get(self.state)
            if current_phase:
                remaining = max(0, current_phase.duration - current_phase.turns_completed)
                # Only add casting message if we didn't just transition
                if not messages:
                    cast_msg = self.format_effect_message(
                        f"Casting {self.name}",
                        [f"{remaining} turns remaining"]
                    )
                    messages.append(cast_msg)
            
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Handle phase transitions and duration tracking.
        Improved version with better cooldown message handling.
        
        Fixed version makes sure:
        1. Turn counting is correct (only on character's own turn)
        2. Phase transitions happen at the right time
        3. Duration is properly tracked
        """
        # Store these values for debugging and state tracking
        self.last_processed_round = round_number
        self.last_processed_turn = turn_name
        
        # Only process turn end effects for the effect owner
        if character.name != turn_name:
            return []
            
        messages = []
        
        # Get current phase info
        current_phase = self.phases.get(self.state)
        if not current_phase:
            return []
            
        # Complete this turn for the current phase
        phase_complete = self.phase_manager.complete_turn(turn_name, character.name)
        
        # Handle phase transitions if the phase is complete
        if phase_complete:
            # Process attacks on transition to ACTIVE if needed
            if self.state == MoveState.CASTING and self.phases.get(MoveState.ACTIVE):
                # Check if we should process attack roll on transition
                if self.combat_processor.attack_roll and self.combat_processor.roll_timing == RollTiming.ACTIVE:
                    attack_msgs = self.combat_processor.process_attack(character, self.name, MoveState.ACTIVE, force_roll=True)
                    if attack_msgs:
                        messages.extend(attack_msgs)
            
            # Transition to next phase
            transition_msg = self._transition_state()
            if transition_msg:
                messages.append(self.format_effect_message(transition_msg))
            
            # If marked for removal, ensure it gets removed
            if self.phase_manager.marked_for_removal:
                if hasattr(self, 'timing'):
                    self.timing.duration = 0
        else:
            # If phase not complete, show appropriate progress message
            remaining = current_phase.duration - current_phase.turns_completed
            
            if self.state == MoveState.CASTING:
                messages.append(self.format_effect_message(
                    f"Casting {self.name}",
                    [f"{remaining} turns remaining"]
                ))
                    
            elif self.state == MoveState.ACTIVE:
                messages.append(self.format_effect_message(
                    f"{self.name} continues",
                    [f"{remaining} turns remaining"]
                ))
                    
            elif self.state == MoveState.COOLDOWN:
                if remaining > 0:  # Only show cooldown message if turns remaining
                    messages.append(self.format_effect_message(
                        f"{self.name} cooldown",
                        [f"{remaining} turns remaining"]
                    ))
                else:
                    # If this is the last turn of cooldown, mark for removal
                    self.phase_manager.marked_for_removal = True
                    if hasattr(self, 'timing'):
                        self.timing.duration = 0
                    messages.append(self.format_effect_message(f"{self.name} cooldown ended"))
        
        return messages
        
    @property
    def is_expired(self) -> bool:
        """
        Check if move effect is fully expired.
        A move is expired when marked for removal or all phases complete.
        """
        return self.phase_manager.is_expired()

    def on_expire(self, character) -> Optional[str]:
        """Handle move expiry and ensure complete removal"""
        if self.state == MoveState.INSTANT:
            return None
            
        # Clear targets list
        self.combat_processor.clear_targets()
        
        # Mark for removal to ensure it gets deleted
        self.phase_manager.marked_for_removal = True
        
        # Set duration to 0 to ensure it gets removed
        if hasattr(self, 'timing'):
            self.timing.duration = 0
            
        return self.format_effect_message(f"{self.name} has ended")

    def to_dict(self) -> dict:
        """Convert to dictionary for storage with state preservation"""
        data = super().to_dict()
        
        # Add data from components
        data.update({
            **self.phase_manager.to_dict(),
            **self.combat_processor.to_dict(),
            **self.resource_manager.to_dict(),
            "cast_description": self.cast_description,
            "last_processed_round": self.last_processed_round,
            "last_processed_turn": self.last_processed_turn,
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
            
            # Restore phase manager state directly
            if state_value := data.get('state'):
                effect.state = MoveState(state_value)
                effect.phase_manager.state = effect.state
                
            # Restore phase progress
            for state_str, phase_info in phase_data.items():
                state = MoveState(state_str)
                if phase := effect.phases.get(state):
                    phase.turns_completed = phase_info.get('turns_completed', 0)
            
            # Restore resource manager state
            effect.resource_manager.uses_remaining = data.get('uses_remaining')
            effect.resource_manager.initial_resources_applied = data.get('initial_resources_applied', True)
            
            # Restore combat processor state
            if state_data := data.get('state_data', {}):
                effect.combat_processor.heat_stacks = state_data.get('heat_stacks', 0)
                effect.combat_processor.attacks_this_turn = state_data.get('attacks_this_turn', 0)
            effect.combat_processor.targets_hit = set(data.get('targets_hit', []))
            
            # Restore timing information
            if timing_data := data.get('timing'):
                effect.timing = EffectTiming(**timing_data)
                
            # Restore processing tracking
            effect.last_processed_round = data.get('last_processed_round')
            effect.last_processed_turn = data.get('last_processed_turn')
            effect.phase_manager.marked_for_removal = data.get('marked_for_removal', False)
                
            return effect
            
        except Exception as e:
            logger.error(f"Error reconstructing MoveEffect: {str(e)}")
            return None