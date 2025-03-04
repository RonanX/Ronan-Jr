"""
## src/core/effects/move.py

Move Effect System Implementation - Simplified Version

Features:
- Phase-based duration tracking (cast -> active -> cooldown)
- Resource cost handling
- Attack roll processing with stat mods
- Multi-target support

Implementation Notes:
- Simplified async handling
- Clear state transitions
- Consistent message formatting
- Streamlined combat handling
"""

from typing import Optional, List, Dict, Any, Tuple, Set
from enum import Enum
import logging

from core.effects.base import BaseEffect, EffectCategory, EffectTiming
from core.effects.condition import ConditionType
from utils.advanced_dice.calculator import DiceCalculator

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
            roll_timing: str = "active",
            uses: Optional[int] = None,
            targets: Optional[List['Character']] = None,
            enable_heat_tracking: bool = False
        ):
            # Set up initial phases and state
            self.phases = {}
            
            if cast_time:
                self.phases[MoveState.CASTING] = {"duration": cast_time, "turns_completed": 0}
                self.state = MoveState.CASTING
            elif duration:
                self.phases[MoveState.ACTIVE] = {"duration": duration, "turns_completed": 0}
                self.state = MoveState.ACTIVE
            elif cooldown:
                self.phases[MoveState.COOLDOWN] = {"duration": cooldown, "turns_completed": 0}
                self.state = MoveState.COOLDOWN
            else:
                self.state = MoveState.INSTANT
                
            # Set up other phases if needed
            if duration and self.state != MoveState.ACTIVE:
                self.phases[MoveState.ACTIVE] = {"duration": duration, "turns_completed": 0}
            if cooldown and self.state != MoveState.COOLDOWN:
                self.phases[MoveState.COOLDOWN] = {"duration": cooldown, "turns_completed": 0}
            
            # Initial duration is based on first phase
            initial_duration = cast_time if cast_time else duration
            if initial_duration is None:
                initial_duration = cooldown if cooldown else 1  # Default to 1 for INSTANT
            
            # Initialize base effect
            super().__init__(
                name=name,
                duration=initial_duration,
                permanent=False,
                category=EffectCategory.STATUS,
                description=description,
                handles_own_expiry=True
            )
            
            # Resource costs
            self.star_cost = star_cost
            self.mp_cost = mp_cost
            self.hp_cost = hp_cost
            
            # Usage tracking
            self.uses = uses
            self.uses_remaining = uses
            
            # Combat parameters
            self.attack_roll = attack_roll
            self.damage = damage
            self.crit_range = crit_range
            self.save_type = save_type
            self.save_dc = save_dc
            self.half_on_save = half_on_save
            self.conditions = conditions or []
            
            # Set roll timing
            if isinstance(roll_timing, str):
                try:
                    self.roll_timing = RollTiming(roll_timing)
                except ValueError:
                    self.roll_timing = RollTiming.ACTIVE
            else:
                self.roll_timing = roll_timing
            
            # Additional properties
            self.cast_description = cast_description
            self.targets = targets or []
            self.enable_heat_tracking = enable_heat_tracking
            
            # Tracking variables
            self.last_processed_round = None
            self.last_processed_turn = None
            self.targets_hit = set()
            self.attacks_this_turn = 0
            self.aoe_mode = 'single'
            self.heat_stacks = 0
            self.marked_for_removal = False

    def get_emoji(self) -> str:
        """Get state-specific emoji"""
        return {
            MoveState.INSTANT: "⚡",
            MoveState.CASTING: "✨",
            MoveState.ACTIVE: "✨",
            MoveState.COOLDOWN: "⏳"
        }.get(self.state, "✨")

    def get_current_phase(self) -> Optional[Dict]:
        """Get the current phase info"""
        return self.phases.get(self.state)
    
    def get_remaining_turns(self) -> int:
        """Get the number of turns remaining in the current phase"""
        phase = self.get_current_phase()
        if not phase:
            return 0
        return max(0, phase["duration"] - phase["turns_completed"])
    
    def transition_state(self) -> Optional[str]:
        """
        Handle state transitions between phases.
        Returns a message if the state changes, None otherwise.
        """
        if self.state == MoveState.INSTANT:
            return None

        # Get current phase and check if we should transition
        phase = self.get_current_phase()
        if not phase or phase["turns_completed"] < phase["duration"]:
            return None

        # Determine next state and message
        next_state = None
        message = None
        
        # Find next valid state
        if self.state == MoveState.CASTING:
            if MoveState.ACTIVE in self.phases:
                next_state = MoveState.ACTIVE
                message = "activates!"
            elif MoveState.COOLDOWN in self.phases:
                next_state = MoveState.COOLDOWN
                message = "enters cooldown"
            else:
                message = "completes"
                self.marked_for_removal = True
                
        elif self.state == MoveState.ACTIVE:
            if MoveState.COOLDOWN in self.phases:
                next_state = MoveState.COOLDOWN
                message = "enters cooldown"
            else:
                message = "wears off"
                self.marked_for_removal = True
                
        elif self.state == MoveState.COOLDOWN:
            message = "cooldown has ended"
            self.marked_for_removal = True
        
        # Update state if transitioning
        if next_state:
            # Store old state for logging
            old_state = self.state
            
            # Update state
            self.state = next_state
            
            # Reset phase tracking for the new phase
            if phase := self.phases.get(next_state):
                phase["turns_completed"] = 0
            
            # Log transition for debugging
            logger.debug(f"Move transitioned from {old_state} to {next_state}")
        
        return message

    async def apply_costs(self, character) -> List[str]:
        """Apply resource costs and return messages"""
        messages = []
        
        # Apply MP cost
        if self.mp_cost != 0:
            # Handle MP gain or loss
            if self.mp_cost > 0:
                character.resources.current_mp = max(0, character.resources.current_mp - self.mp_cost)
                messages.append(f"Uses {self.mp_cost} MP")
            else:
                character.resources.current_mp = min(
                    character.resources.max_mp, 
                    character.resources.current_mp - self.mp_cost  # Negative cost = gain
                )
                messages.append(f"Gains {abs(self.mp_cost)} MP")
        
        # Apply HP cost
        if self.hp_cost != 0:
            # Handle HP gain or loss
            if self.hp_cost > 0:
                character.resources.current_hp = max(0, character.resources.current_hp - self.hp_cost)
                messages.append(f"Uses {self.hp_cost} HP")
            else:
                character.resources.current_hp = min(
                    character.resources.max_hp, 
                    character.resources.current_hp - self.hp_cost  # Negative cost = gain
                )
                messages.append(f"Heals {abs(self.hp_cost)} HP")
        
        return messages

    def can_use(self, round_number: Optional[int] = None) -> tuple[bool, Optional[str]]:
        """Check if move can be used based on cooldown and uses"""
        # Check if currently in cooldown phase
        if self.state == MoveState.COOLDOWN:
            if phase := self.get_current_phase():
                remaining = phase["duration"] - phase["turns_completed"]
                return False, f"On cooldown ({remaining} turns remaining)"
        
        # Check uses if tracked
        if self.uses is not None:
            if self.uses_remaining is None:
                self.uses_remaining = self.uses
            if self.uses_remaining <= 0:
                return False, f"No uses remaining (0/{self.uses})"
        
        return True, None

    async def should_roll(self, state: MoveState, force_roll: bool = False) -> bool:
        """Determine if we should roll based on timing and state"""
        if force_roll:
            return True
            
        if self.roll_timing == RollTiming.INSTANT:
            return state == MoveState.INSTANT
        elif self.roll_timing == RollTiming.ACTIVE:
            return state == MoveState.ACTIVE
        elif self.roll_timing == RollTiming.PER_TURN:
            return state == MoveState.ACTIVE
            
        return False

    async def process_attack(self, source: 'Character', reason: str, force_roll: bool = False) -> List[str]:
        """
        Process attack roll and damage if needed.
        Returns list of messages for each target.
        """
        # Skip if no attack roll defined
        if not self.attack_roll:
            return []
            
        # Check if we should roll based on timing
        if not await self.should_roll(self.state, force_roll):
            return []

        # Track attack count
        self.attacks_this_turn += 1

        messages = []
        
        # Import here to avoid circular import
        from utils.advanced_dice.attack_calculator import AttackCalculator, AttackParameters
        
        # Handle no targets case
        if not self.targets:
            # Set up attack parameters
            params = AttackParameters(
                roll_expression=self.attack_roll,
                character=source,
                targets=None,
                damage_str=self.damage,
                crit_range=self.crit_range,
                reason=reason
            )
            
            # Process attack
            message, _ = await AttackCalculator.process_attack(params)
            messages.append(message)
            return messages
        
        # Set up attack parameters for all targets
        params = AttackParameters(
            roll_expression=self.attack_roll,
            character=source,
            targets=self.targets,
            damage_str=self.damage,
            crit_range=self.crit_range,
            aoe_mode=self.aoe_mode,
            reason=reason
        )
        
        # Process attack with all targets
        message, hit_results = await AttackCalculator.process_attack(params)
        messages.append(message)
        
        # Process hit tracking for heat mechanic
        if hit_results:
            # Extract hit targets
            for target_name, hit_data in hit_results.items():
                if hit_data.get('hit', False):
                    self.targets_hit.add(target_name)
        
        # Handle heat tracking if enabled
        if self.enable_heat_tracking and self.targets_hit:
            # Source heat (attunement)
            if not hasattr(source, 'heat_stacks'):
                source.heat_stacks = 0
            
            source.heat_stacks += 1
            
            # Target heat (vulnerability) for each hit target
            for target_name in self.targets_hit:
                target = next((t for t in self.targets if t.name == target_name), None)
                if target:
                    if not hasattr(target, 'heat_stacks'):
                        target.heat_stacks = 0
                    target.heat_stacks += 1
        
        return messages

    async def on_apply(self, character, round_number: int) -> str:
        """Initial effect application"""
        self.initialize_timing(round_number, character.name)
        
        # Apply costs and format messages
        costs = []
        details = []
        timing_info = []
        
        # Apply resource costs
        cost_messages = await self.apply_costs(character)
        for msg in cost_messages:
            if "MP" in msg:
                costs.append(f"💙 MP: {self.mp_cost}")
            elif "HP" in msg and "Heal" not in msg:
                costs.append(f"❤️ HP: {self.hp_cost}")
            elif "Heal" in msg:
                costs.append(f"❤️ Heal: {abs(self.hp_cost)}")
        
        # Add star cost
        if self.star_cost > 0:
            costs.append(f"⭐ {self.star_cost}")
            
        # Add timing info
        if MoveState.CASTING in self.phases:
            cast_time = self.phases[MoveState.CASTING]["duration"]
            timing_info.append(f"🔄 {cast_time}T Cast")
        if MoveState.ACTIVE in self.phases:
            duration = self.phases[MoveState.ACTIVE]["duration"]
            timing_info.append(f"⏳ {duration}T Duration")
        if MoveState.COOLDOWN in self.phases:
            cooldown = self.phases[MoveState.COOLDOWN]["duration"]
            timing_info.append(f"⌛ {cooldown}T Cooldown")
            
        # Format target info if any
        if self.targets:
            target_names = ", ".join(t.name for t in self.targets)
            details.append(f"Target{'s' if len(self.targets) > 1 else ''}: {target_names}")
            
        # Process instant attack rolls here if needed
        attack_messages = []
        if self.attack_roll and self.roll_timing == RollTiming.INSTANT:
            attack_messages = await self.process_attack(character, self.name, force_roll=True)
                    
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
                    
            formatted_message += "\n" + "\n".join(detail_strings)
        
        # Now add any attack roll messages as separate bullets
        if attack_messages:
            for msg in attack_messages:
                # Format the attack message as a bullet point if it isn't already
                if not msg.startswith("•") and not msg.startswith("`"):
                    formatted_message += f"\n• {msg}"
                else:
                    formatted_message += f"\n{msg}"
        
        return formatted_message

    async def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
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
        transition_msg = self.transition_state()
        if transition_msg:
            messages.append(self.format_effect_message(f"{self.name} {transition_msg}"))
            
            # If we transitioned to active, process attack roll if timing is ACTIVE
            if self.state == MoveState.ACTIVE and self.attack_roll and self.roll_timing == RollTiming.ACTIVE:
                attack_msgs = await self.process_attack(character, self.name, force_roll=True)
                if attack_msgs:
                    messages.extend(attack_msgs)
    
        # Now handle the current state (which might have just changed)
        if self.state == MoveState.CASTING:
            # Show casting message with turns remaining
            remaining = self.get_remaining_turns()
            if not any("activates" in msg for msg in messages):  # Don't show if we just activated
                cast_msg = self.format_effect_message(
                    f"Casting {self.name}",
                    [f"{remaining} turns remaining"]
                )
                messages.append(cast_msg)
                
        elif self.state == MoveState.ACTIVE:
            # Process attack if timing is ACTIVE and we didn't just transition
            # This handles the case where we were already in ACTIVE state
            if self.attack_roll and self.roll_timing == RollTiming.ACTIVE and not any("activates" in msg for msg in messages):
                attack_msgs = await self.process_attack(character, self.name, force_roll=True)
                if attack_msgs:
                    messages.extend(attack_msgs)
            
            # Only add active message if we didn't just transition
            if not any("activates" in msg for msg in messages):
                # Show active message with description and turns remaining
                remaining = self.get_remaining_turns()
                
                details = []
                # Add description
                if self.description:
                    # Split description by semicolons for bullet points
                    if ';' in self.description:
                        for part in self.description.split(';'):
                            part = part.strip()
                            if part:
                                details.append(part)
                    else:
                        details.append(self.description)
                
                # Add remaining turns
                details.append(f"{remaining} turns remaining")
                
                active_msg = self.format_effect_message(
                    f"{self.name} active",
                    details
                )
                messages.append(active_msg)
            
            # Process per-turn attack rolls
            if self.attack_roll and self.roll_timing == RollTiming.PER_TURN:
                attack_msgs = await self.process_attack(character, self.name, force_roll=True)
                if attack_msgs:
                    messages.extend(attack_msgs)
            
        return messages

    async def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Handle phase transitions and duration tracking.
        """
        # Store these values for debugging and state tracking
        self.last_processed_round = round_number
        self.last_processed_turn = turn_name
        
        # Only process turn end effects for the effect owner
        if character.name != turn_name:
            return []
            
        messages = []
        
        # Complete this turn for the current phase
        phase = self.get_current_phase()
        if phase:
            phase["turns_completed"] += 1
        
        # Get remaining turns for messaging
        remaining = self.get_remaining_turns()
        
        # Handle phase transitions if the phase is complete
        transition_msg = self.transition_state()
        if transition_msg:
            messages.append(self.format_effect_message(f"{self.name} {transition_msg}"))
        
            # If marked for removal, ensure it gets removed
            if self.marked_for_removal:
                if hasattr(self, 'timing'):
                    self.timing.duration = 0
        else:
            # If phase not complete, show appropriate progress message
            if self.state == MoveState.CASTING:
                if remaining > 0:
                    messages.append(self.format_effect_message(
                        f"Casting {self.name}",
                        [f"{remaining} turns remaining"]
                    ))
                    
            elif self.state == MoveState.ACTIVE:
                if remaining > 0:
                    messages.append(self.format_effect_message(
                        f"{self.name} continues",
                        [f"{remaining} turns remaining"]
                    ))
                    
            elif self.state == MoveState.COOLDOWN:
                if remaining > 0:
                    messages.append(self.format_effect_message(
                        f"{self.name} cooldown",
                        [f"{remaining} turns remaining"]
                    ))
                else:
                    # If this is the last turn of cooldown, mark for removal
                    self.marked_for_removal = True
                    if hasattr(self, 'timing'):
                        self.timing.duration = 0
                    messages.append(self.format_effect_message(f"{self.name} cooldown has ended"))
        
        return messages
        
    @property
    def is_expired(self) -> bool:
        """
        Check if move effect is fully expired.
        A move is expired when marked for removal or all phases complete.
        """
        if self.marked_for_removal:
            return True
            
        if self.state == MoveState.INSTANT:
            return True
            
        current_phase = self.get_current_phase()
        if not current_phase:
            return True
            
        # Check if we're in the final phase with no more transitions available
        if self.state == MoveState.COOLDOWN:
            return current_phase["turns_completed"] >= current_phase["duration"]
        elif self.state == MoveState.ACTIVE and MoveState.COOLDOWN not in self.phases:
            return current_phase["turns_completed"] >= current_phase["duration"]
        elif self.state == MoveState.CASTING and MoveState.ACTIVE not in self.phases and MoveState.COOLDOWN not in self.phases:
            return current_phase["turns_completed"] >= current_phase["duration"]
            
        return False

    async def on_expire(self, character) -> Optional[str]:
        """Handle move expiry and ensure complete removal"""
        if self.state == MoveState.INSTANT:
            return None
            
        # Clear targets list
        self.targets = []
        
        # Mark for removal to ensure it gets deleted
        self.marked_for_removal = True
        
        # Set duration to 0 to ensure it gets removed
        if hasattr(self, 'timing'):
            self.timing.duration = 0
            
        return self.format_effect_message(f"{self.name} has ended")

    def to_dict(self) -> dict:
        """Convert to dictionary for storage with state preservation"""
        data = super().to_dict()
        
        # Add phase data
        phase_data = {state.value: phase for state, phase in self.phases.items()}
        
        # Add move-specific data
        data.update({
            "state": self.state.value,
            "phases": phase_data,
            "star_cost": self.star_cost,
            "mp_cost": self.mp_cost,
            "hp_cost": self.hp_cost,
            "cast_description": self.cast_description,
            "uses": self.uses,
            "uses_remaining": self.uses_remaining,
            "attack_roll": self.attack_roll,
            "damage": self.damage, 
            "crit_range": self.crit_range,
            "save_type": self.save_type,
            "save_dc": self.save_dc,
            "half_on_save": self.half_on_save,
            "conditions": [c.value if hasattr(c, 'value') else str(c) for c in self.conditions] if self.conditions else [],
            "roll_timing": self.roll_timing.value,
            "targets_hit": list(self.targets_hit),
            "aoe_mode": self.aoe_mode,
            "enable_heat_tracking": self.enable_heat_tracking,
            "marked_for_removal": self.marked_for_removal,
            "last_processed_round": self.last_processed_round,
            "last_processed_turn": self.last_processed_turn
        })
        
        # Remove None values to save space
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> 'MoveEffect':
        """Create from dictionary data"""
        try:
            # Extract phase durations
            phases = data.get('phases', {})
            cast_time = phases.get(MoveState.CASTING.value, {}).get('duration')
            duration = phases.get(MoveState.ACTIVE.value, {}).get('duration')
            cooldown = phases.get(MoveState.COOLDOWN.value, {}).get('duration')
            
            # Extract combat data
            attack_roll = data.get('attack_roll')
            damage = data.get('damage')
            crit_range = data.get('crit_range', 20)
            save_type = data.get('save_type')
            save_dc = data.get('save_dc')
            half_on_save = data.get('half_on_save', False)
            conditions = data.get('conditions', [])
            
            # Normalize roll timing
            roll_timing_str = data.get('roll_timing', RollTiming.ACTIVE.value)
            
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
                conditions=[ConditionType(c) if isinstance(c, str) else c for c in conditions] if conditions else [],
                roll_timing=roll_timing_str,
                uses=data.get('uses'),
                enable_heat_tracking=data.get('enable_heat_tracking', False)
            )
            
            # Restore state
            if state_value := data.get('state'):
                effect.state = MoveState(state_value)
                
            # Restore phase progress
            for state_str, phase_info in phases.items():
                state = MoveState(state_str)
                if state in effect.phases:
                    effect.phases[state]["turns_completed"] = phase_info.get('turns_completed', 0)
            
            # Restore usage tracking
            effect.uses_remaining = data.get('uses_remaining')
            
            # Restore combat state
            effect.targets_hit = set(data.get('targets_hit', []))
            effect.aoe_mode = data.get('aoe_mode', 'single')
            
            # Restore tracking information
            if timing_data := data.get('timing'):
                effect.timing = EffectTiming(**timing_data)
                
            effect.last_processed_round = data.get('last_processed_round')
            effect.last_processed_turn = data.get('last_processed_turn')
            effect.marked_for_removal = data.get('marked_for_removal', False)
                
            return effect
            
        except Exception as e:
            logger.error(f"Error reconstructing MoveEffect: {str(e)}")
            return None