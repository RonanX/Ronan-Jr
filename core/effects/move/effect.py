"""
Core implementation of the MoveEffect class with FIXED timing and message logic.

FIXES:
1. Clear separation: turn start processes attacks, turn end shows status
2. No double processing - each timing method called once per turn
3. Proper message formatting for turn announcements
4. Uses consolidated timing system
"""

import logging
from typing import Optional, List, Dict, Any, Set, Union, Tuple

from core.effects.base import BaseEffect, EffectCategory, EffectState
from core.effects.rollmod import RollModifierType, RollModifierEffect
from core.effects.condition import ConditionType

# Import consolidated timing system
from .timing import MoveEffectTiming, MovePhase, RollTiming
from .combat import CombatProcessor, BonusOnHit
from .saves import SavingThrowProcessor

logger = logging.getLogger(__name__)

class MoveEffect(BaseEffect):
    """
    Move effect with FIXED timing and message logic.
    
    Clear responsibilities:
    - Turn START: Process attacks, return messages for turn announcement
    - Turn END: Show status updates, execute transitions, handle removal
    - Apply: Handle initial costs and instant effects
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
        conditions: Optional[List[ConditionType]] = None,
        roll_timing: str = "active",
        uses: Optional[int] = None,
        targets: Optional[List['Character']] = None,
        bonus_on_hit: Optional[Dict] = None,
        aoe_mode: str = 'single',
        enable_heat_tracking: bool = False,
        enable_hit_bonus: bool = False,
        roll_modifier: Optional[Dict[str, Any]] = None,
        save_type: Optional[str] = None,
        save_dc: Optional[str] = None,
        half_on_save: bool = False
    ):
        """Initialize a move effect with consolidated timing"""
        # Use duration for BaseEffect (0 if None)
        actual_duration = 0 if duration is None else duration
        
        super().__init__(
            name=name,
            duration=actual_duration,
            permanent=False,
            category=EffectCategory.STATUS,
            description=description,
            process_timing="both",
            emoji="✨",
            debug_mode=True
        )
        
        # Disable BaseEffect duration management
        self._ignore_base_duration = True
        
        # Store parameters
        self.star_cost = star_cost
        self.mp_cost = mp_cost
        self.hp_cost = hp_cost
        self.cast_description = cast_description
        self.attack_roll = attack_roll
        self.damage = damage
        self.crit_range = crit_range
        self.conditions = conditions or []
        self.uses = uses
        self.uses_remaining = uses
        self.save_type = save_type
        self.save_dc = save_dc
        self.half_on_save = half_on_save
        self.targets = targets or []
        
        # Initialize timing system
        self.timing = MoveEffectTiming(
            cast_time=cast_time,
            duration=duration,
            cooldown=cooldown,
            debug_mode=True
        )
        
        # Combat processors
        self.combat = CombatProcessor(debug_mode=True)
        self.saves = SavingThrowProcessor(debug_mode=True)
        self.combat.aoe_mode = aoe_mode
        
        # Auto-detect roll timing for instant effects
        is_instant = not cast_time and not duration and not cooldown
        has_only_cooldown = not cast_time and not duration and cooldown
        
        if (is_instant or has_only_cooldown) and attack_roll:
            print(f"[Move-{name}] Auto-detected INSTANT attack")
            roll_timing = "instant"
        
        # Set roll timing
        try:
            self.roll_timing = RollTiming(roll_timing)
        except (ValueError, TypeError):
            self.roll_timing = RollTiming.ACTIVE
            print(f"[Move-{name}] Invalid roll timing '{roll_timing}', defaulting to ACTIVE")
        
        # Initialize bonus on hit
        if bonus_on_hit is None and (enable_heat_tracking or enable_hit_bonus):
            bonus_on_hit = {'stars': 1}
        
        self.bonus_on_hit = BonusOnHit.from_dict(bonus_on_hit)
        
        # Initialize roll modifier if provided
        self.roll_modifier_data = roll_modifier
        self.roll_modifier_effect = None
        if roll_modifier:
            self._init_roll_modifier(roll_modifier, name, duration)
        
        # State tracking
        self.last_attack_round = None  # Track when we last processed attacks
        
        print(f"[Move-{name}] Created with timing: cast={cast_time}, duration={duration}, cooldown={cooldown}")

    def _init_roll_modifier(self, roll_modifier: Dict[str, Any], move_name: str, duration: Optional[int]):
        """Initialize roll modifier effect if configured"""
        if not roll_modifier:
            return
            
        # Extract modifier parameters
        mod_type = roll_modifier.get('type', 'bonus')
        mod_value = roll_modifier.get('value', 0)
        mod_duration = roll_modifier.get('duration', duration or 1)
        
        # Create the appropriate effect based on type
        if mod_type == 'bonus':
            self.roll_modifier_effect = RollModifierEffect(
                name=f"{move_name} Bonus",
                modifier_type=RollModifierType.BONUS,
                modifier_value=mod_value,
                duration=mod_duration,
                source=move_name
            )
        elif mod_type == 'advantage':
            self.roll_modifier_effect = RollModifierEffect(
                name=f"{move_name} Advantage",
                modifier_type=RollModifierType.ADVANTAGE,
                duration=mod_duration,
                source=move_name
            )
        elif mod_type == 'disadvantage':
            self.roll_modifier_effect = RollModifierEffect(
                name=f"{move_name} Disadvantage",
                modifier_type=RollModifierType.DISADVANTAGE,
                duration=mod_duration,
                source=move_name
            )

    def apply_costs(self, character) -> List[str]:
        """Apply resource costs to the character"""
        messages = []
        print(f"[Move-{self.name}] Applying costs to {character.name}")
        
        # Apply MP cost
        if self.mp_cost != 0 and hasattr(character, 'resources'):
            if self.mp_cost > 0:
                character.resources.current_mp = max(0, character.resources.current_mp - self.mp_cost)
                messages.append(f"{character.name} spends {self.mp_cost} MP")
            else:
                restore_amount = abs(self.mp_cost)
                actual_restore = min(restore_amount, character.resources.max_mp - character.resources.current_mp)
                character.resources.current_mp += actual_restore
                if actual_restore > 0:
                    messages.append(f"{character.name} restores {actual_restore} MP")
        
        # Apply HP cost
        if self.hp_cost != 0 and hasattr(character, 'resources'):
            if self.hp_cost > 0:
                character.resources.current_hp = max(0, character.resources.current_hp - self.hp_cost)
                messages.append(f"{character.name} spends {self.hp_cost} HP")
            else:
                heal_amount = abs(self.hp_cost)
                actual_heal = min(heal_amount, character.resources.max_hp - character.resources.current_hp)
                character.resources.current_hp += actual_heal
                if actual_heal > 0:
                    messages.append(f"{character.name} heals {actual_heal} HP")
        
        # Apply Star cost
        if self.star_cost > 0 and hasattr(character, 'action_stars'):
            character.action_stars.current_stars = max(0, character.action_stars.current_stars - self.star_cost)
            messages.append(f"{character.name} spends {self.star_cost} ⭐")
        
        return messages

    def on_apply(self, character, round_number: int) -> str:
        """Apply the effect with fixed timing and proper formatting"""
        print(f"[Move-{self.name}] Applying to {character.name} on round {round_number}")
        
        # Apply resource costs
        cost_messages = self.apply_costs(character)
        
        # Apply roll modifier if configured
        if self.roll_modifier_effect:
            if 'roll_modifiers' not in character.custom_parameters:
                character.custom_parameters['roll_modifiers'] = []
            character.custom_parameters['roll_modifiers'].append(self.roll_modifier_effect)
        
        # Build info parts for display
        info_parts = []
        
        # Add costs
        if self.mp_cost > 0:
            info_parts.append(f"💙 {self.mp_cost} MP")
        if self.hp_cost > 0:
            info_parts.append(f"❤️ {self.hp_cost} HP")
        if self.star_cost > 0:
            info_parts.append(f"⭐ {self.star_cost}")
        
        # Add timing info
        if self.timing.cast_time and self.timing.cast_time > 0:
            info_parts.append(f"🔄 {self.timing.cast_time}T Cast")
        if self.timing.duration and self.timing.duration > 0:
            info_parts.append(f"⏱️ {self.timing.duration}T Duration")
        if self.timing.cooldown and self.timing.cooldown > 0:
            info_parts.append(f"⌛ {self.timing.cooldown}T Cooldown")
        
        # Handle instant effects
        attack_messages = []
        is_instant = self.timing.current_phase == MovePhase.INSTANT
        
        if self.attack_roll and (is_instant or self.roll_timing == RollTiming.INSTANT):
            print(f"[Move-{self.name}] Processing INSTANT attack")
            self.last_attack_round = round_number
            
            self.bonus_on_hit.reset()
            attack_results = self.combat.perform_sync_attack(
                source=character,
                targets=self.targets,
                attack_roll=self.attack_roll,
                damage=self.damage,
                crit_range=self.crit_range,
                reason=self.name,
                bonus_on_hit=self.bonus_on_hit
            )
            
            if attack_results:
                attack_messages = attack_results
        
        # Build main message
        if self.cast_description and self.timing.current_phase == MovePhase.CASTING:
            main_message = f"{character.name} {self.cast_description} {self.name}"
        else:
            main_message = f"{character.name} uses {self.name}"
        
        # Add info parts
        if info_parts:
            main_message += f" | {' | '.join(info_parts)}"
        
        # Format final message
        formatted_message = self.format_effect_message(main_message, [])
        
        # Add attack results as bullets
        if attack_messages:
            for result in attack_messages:
                formatted_message += f"\n• `{result}`"
        
        print(f"[Move-{self.name}] Apply complete")
        return formatted_message

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process turn START - Handle attacks and return messages for turn announcement.
        
        Expected format:
        - Move name with bullet description
        - Attack results as additional bullets
        - Bonus messages as separate bullets
        """
        messages = []
        
        # Process timing - this handles decrements and marks transitions
        should_process_attacks, just_activated = self.timing.process_turn_start(
            round_number, turn_name, character.name
        )
        
        # Skip if not this character's turn
        if character.name != turn_name:
            return messages
        
        print(f"[Move-{self.name}] Turn start for {character.name} on round {round_number}")
        
        # Check if we're in active phase and should process attacks
        current_phase = self.timing.current_phase
        if current_phase == MovePhase.ACTIVE and should_process_attacks and self.attack_roll:
            # Determine attack timing
            should_attack = False
            
            if self.roll_timing == RollTiming.PER_TURN:
                # Always attack each turn during active phase
                should_attack = True
                print(f"[Move-{self.name}] Processing PER_TURN attack")
            elif self.roll_timing == RollTiming.ACTIVE and self.last_attack_round != round_number:
                # Attack once when active starts (but not if we already attacked this round)
                should_attack = True
                print(f"[Move-{self.name}] Processing ACTIVE attack (first turn)")
            
            if should_attack:
                self.last_attack_round = round_number
                
                # Reset and process attack
                self.bonus_on_hit.reset()
                attack_results = self.combat.perform_sync_attack(
                    source=character,
                    targets=self.targets,
                    attack_roll=self.attack_roll,
                    damage=self.damage,
                    crit_range=self.crit_range,
                    reason=self.name,
                    bonus_on_hit=self.bonus_on_hit
                )
                
                # Format messages for turn announcement
                if attack_results:
                    # Add move name with description
                    main_msg = f"**{self.name}**"
                    if self.description:
                        # Format description with bullet points (semicolon-separated)
                        desc_parts = [part.strip() for part in self.description.split(';') if part.strip()]
                        for part in desc_parts:
                            main_msg += f"\n• `{part}`"
                    
                    messages.append(main_msg)
                    
                    # Add attack results
                    for result in attack_results:
                        messages.append(f"• `{result}`")
        
        # Handle casting phase display
        elif current_phase == MovePhase.CASTING:
            # Show casting message similar to on_apply but with remaining cast time
            cast_msg = f"**{self.name}** (casting)"
            if self.cast_description:
                cast_msg += f"\n• `{self.cast_description}`"
            if self.description:
                desc_parts = [part.strip() for part in self.description.split(';') if part.strip()]
                for part in desc_parts:
                    cast_msg += f"\n• `{part}`"
            
            remaining = self.timing.get_remaining_turns()
            if remaining > 0:
                cast_msg += f"\n• `{remaining} turn{'s' if remaining != 1 else ''} remaining`"
            
            messages.append(cast_msg)
        
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """
        Process turn END - Show status updates, execute transitions, handle removal.
        
        Returns status messages for the effect update embed.
        """
        messages = []
        
        # Skip if not this character's turn
        if character.name != turn_name:
            return messages
        
        print(f"[Move-{self.name}] Turn end for {character.name} on round {round_number}")
        
        # Override BaseEffect duration to prevent it from interfering
        if hasattr(self, '_ignore_base_duration') and self._ignore_base_duration:
            self._duration_remaining = 999
        
        # Process timing - this shows status and executes transitions
        status_msg, should_remove = self.timing.process_turn_end(
            round_number, turn_name, character.name
        )
        
        # Handle status message
        if status_msg:
            if "activates" in status_msg:
                # Transition to active
                messages.append(self.format_effect_message(f"{self.name} {status_msg}"))
                
                # Process delayed ACTIVE attack if needed
                if (self.roll_timing == RollTiming.ACTIVE and 
                    self.attack_roll and 
                    self.last_attack_round != round_number):
                    
                    print(f"[Move-{self.name}] Processing delayed ACTIVE attack after transition")
                    self.last_attack_round = round_number
                    
                    self.bonus_on_hit.reset()
                    attack_results = self.combat.perform_sync_attack(
                        source=character,
                        targets=self.targets,
                        attack_roll=self.attack_roll,
                        damage=self.damage,
                        crit_range=self.crit_range,
                        reason=self.name,
                        bonus_on_hit=self.bonus_on_hit
                    )
                    
                    if attack_results:
                        for result in attack_results:
                            messages.append(f"• `{result}`")
                            
            elif "enters cooldown" in status_msg:
                # Transition to cooldown
                messages.append(self.format_effect_message(f"{self.name} {status_msg}"))
                
            elif "has worn off" in status_msg:
                # Effect expiring - add to feedback for proper display
                if hasattr(character, 'add_effect_feedback'):
                    expiry_msg = self.format_effect_message(f"{self.name} {status_msg}")
                    character.add_effect_feedback(
                        effect_name=self.name,
                        expiry_message=expiry_msg,
                        round_expired=round_number,
                        turn_expired=character.name
                    )
                    print(f"[Move-{self.name}] Added expiry feedback")
                
            else:
                # Regular status update
                messages.append(self.format_effect_message(f"{self.name} {status_msg}"))
        
        # Mark for removal if needed
        if should_remove:
            self.state = EffectState.EXPIRED
            print(f"[Move-{self.name}] Marked for removal at turn end")
        
        return messages

    def on_expire(self, character) -> str:
        """Handle effect expiration"""
        print(f"[Move-{self.name}] Expiring from {character.name}")
        
        # Clear targets
        self.targets = []
        
        # Don't return message - handled by feedback system
        return ""

    @property
    def is_expired(self) -> bool:
        """Check if the effect should be removed"""
        if hasattr(self, 'state') and self.state == EffectState.EXPIRED:
            return True
        return self.timing.should_be_removed

    def get_phase_name(self) -> str:
        """Get current phase name for display"""
        return self.timing.current_phase.value

    async def execute_pending_operations(self) -> List[str]:
        """Execute any pending async operations (none needed in fixed system)"""
        return []

    def to_dict(self) -> dict:
        """Convert to dictionary for storage - bypasses BaseEffect to avoid timing conflicts"""
        data = {
            # Basic effect info
            "effect_type": self.__class__.__name__,
            "name": self.name,
            "description": self.description,
            "category": self.category.value if hasattr(self.category, 'value') else str(self.category),
            "state": self.state.value if hasattr(self.state, 'value') else str(self.state),
            "permanent": False,  # Move effects are never permanent
            
            # Move-specific data
            "star_cost": self.star_cost,
            "mp_cost": self.mp_cost,
            "hp_cost": self.hp_cost,
            "timing": self.timing.to_dict(),
            "attack_roll": self.attack_roll,
            "damage": self.damage,
            "crit_range": self.crit_range,
            "roll_timing": self.roll_timing.value,
            "targets": [t.name for t in self.targets] if self.targets else [],
            "bonus_on_hit": self.bonus_on_hit.to_dict() if self.bonus_on_hit else None,
            "last_attack_round": self.last_attack_round,
            "conditions": self.conditions,
            "cast_description": self.cast_description,
            "uses": self.uses,
            "uses_remaining": self.uses_remaining,
            "save_type": self.save_type,
            "save_dc": self.save_dc,
            "half_on_save": self.half_on_save
        }
        
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'MoveEffect':
        """Create from dictionary data"""
        # Extract timing data
        timing_data = data.get("timing", {})
        
        instance = cls(
            name=data.get("name", "Unknown Move"),
            description=data.get("description", ""),
            star_cost=data.get("star_cost", 0),
            mp_cost=data.get("mp_cost", 0),
            hp_cost=data.get("hp_cost", 0),
            cast_time=timing_data.get("cast_time"),
            duration=timing_data.get("duration"),
            cooldown=timing_data.get("cooldown"),
            attack_roll=data.get("attack_roll"),
            damage=data.get("damage"),
            crit_range=data.get("crit_range", 20),
            roll_timing=data.get("roll_timing", "active"),
            cast_description=data.get("cast_description"),
            uses=data.get("uses"),
            save_type=data.get("save_type"),
            save_dc=data.get("save_dc"),
            half_on_save=data.get("half_on_save", False),
            conditions=data.get("conditions", [])
        )
        
        # Restore timing state
        if timing_data:
            instance.timing = MoveEffectTiming.from_dict(timing_data)
        
        # Restore other state
        instance.last_attack_round = data.get("last_attack_round")
        instance.uses_remaining = data.get("uses_remaining", instance.uses)
        
        # Restore effect state
        if "state" in data:
            try:
                instance.state = EffectState(data["state"])
            except (ValueError, TypeError):
                instance.state = EffectState.ACTIVE
        
        return instance