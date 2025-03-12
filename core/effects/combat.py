"""
src/core/effects/combat.py:

Combat-focused effects like damage over time and offensive debuffs.

IMPLEMENTATION MANDATES:
- Use DamageType enum for all damage typing
- All DOT effects must support both flat and dice values
- Stack-based effects must track their own cleanup
- Always show remaining duration in on_turn_end()
- All combat effects must properly interact with resistances/vulnerabilities
- Source effects (like Phoenix Pursuit) must track their targets
"""

import random
from core.effects.base import BaseEffect, EffectCategory, EffectTiming
from core.effects.status import ACEffect
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from enum import Enum, auto
from dataclasses import dataclass
from utils.dice import DiceRoller

class BurnEffect(BaseEffect):
    """Applies burn damage at the start of each turn"""
    def __init__(self, damage: str, duration: Optional[int] = None):
        super().__init__(
            name="Burn",
            duration=duration,
            permanent=False,
            category=EffectCategory.COMBAT
        )
        self.damage = damage
        self.last_damage = 0  # Track last damage dealt for messages
        
    def _roll_damage(self, character) -> int:
        """Roll damage if dice notation, otherwise return static value"""
        if isinstance(self.damage, str) and ('d' in self.damage.lower() or 'D' in self.damage):
            total, _ = DiceRoller.roll_dice(self.damage, character)
            return total
        return int(self.damage)

    def on_apply(self, character, round_number: int) -> str:
        """Apply burn effect with formatted message"""
        self.initialize_timing(round_number, character.name)
        
        # Format duration text
        duration_text = ""
        if self.duration:
            turns = "turn" if self.duration == 1 else "turns"
            duration_text = f"for {self.duration} {turns}"
        elif self.permanent:
            duration_text = "permanently"
        
        # Return formatted message using base class method
        return self.format_effect_message(
            f"{character.name} is burning",
            [
                f"Taking {self.damage} fire damage per turn",
                duration_text
            ],
            emoji="🔥"
        )

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process burn damage at start of affected character's turn"""
        if character.name != turn_name:
            return []
            
        # Skip if rounds completed exceeds duration
        rounds_completed = round_number - self.timing.start_round
        if not self.permanent and self.duration and rounds_completed >= self.duration:
            return []
                
        # Roll/calculate damage
        damage = self._roll_damage(character)
        self.last_damage = damage
        
        # Apply damage
        old_hp = character.resources.current_hp
        
        # Handle temp HP first
        absorbed = 0
        if character.resources.current_temp_hp > 0:
            absorbed = min(character.resources.current_temp_hp, damage)
            character.resources.current_temp_hp -= absorbed
            damage -= absorbed
            
        # Apply remaining damage to regular HP
        character.resources.current_hp = max(0, character.resources.current_hp - damage)
        
        # Create message details
        details = []
        if absorbed > 0:
            details.append(f"{absorbed} absorbed by temp HP")
        details.append(f"HP: {character.resources.current_hp}/{character.resources.max_hp}")
        
        # Get duration info
        if not self.permanent and self.duration:
            turns_remaining = max(0, self.duration - rounds_completed)
            if turns_remaining > 0:
                plural = "s" if turns_remaining != 1 else ""
                details.append(f"{turns_remaining} turn{plural} remaining")
        
        # Return formatted message
        return [self.format_effect_message(
            f"{character.name} takes {self.last_damage} fire damage from burn",
            details,
            emoji="🔥"
        )]

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Handle duration tracking at end of turn"""
        if character.name != turn_name or self.permanent:
            return []
            
        # Calculate remaining turns
        turns_remaining, should_expire = self.process_duration(round_number, turn_name)
        
        # Format message based on remaining duration
        if should_expire:
            return [self.format_effect_message(
                f"Burn effect will wear off from {character.name}",
                emoji="🔥"
            )]
        elif turns_remaining > 0:
            return [self.format_effect_message(
                f"Burn effect continues",
                [f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"],
                emoji="🔥"
            )]
            
        return []
    
    def on_expire(self, character) -> str:
        """Clean message when effect expires"""
        return self.format_effect_message(
            f"Burn effect has worn off from {character.name}",
            emoji="🔥"
        )
        
    def get_status_text(self, character) -> str:
        """Format status text for character sheet display"""
        lines = [f"🔥 **{self.name}**"]
        
        # Add damage info
        lines.append(f"• `Damage: {self.damage} per turn`")
        if self.last_damage:
            lines.append(f"• `Last damage: {self.last_damage}`")
            
        # Add duration info
        if self.timing and self.timing.duration is not None:
            if hasattr(character, 'round_number'):
                rounds_passed = character.round_number - self.timing.start_round
                remaining = max(0, self.timing.duration - rounds_passed)
                lines.append(f"• `{remaining} turn{'s' if remaining != 1 else ''} remaining`")
        elif self.permanent:
            lines.append("• `Permanent`")
            
        return "\n".join(lines)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            "damage": self.damage,
            "last_damage": self.last_damage
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'BurnEffect':
        """Create from dictionary data"""
        effect = cls(
            damage=data.get('damage', "1d4"),
            duration=data.get('duration')
        )
        effect.last_damage = data.get('last_damage', 0)
        
        # Restore timing if it exists
        if timing_data := data.get('timing'):
            effect.timing = EffectTiming(**timing_data)
            
        return effect
    
class SourceHeatWaveEffect(BaseEffect):
    """
    Phoenix Pursuit effect for the source character.
    
    Key features:
    - Heat stack tracking (0-3)
    - State management (building/activated)
    - Duration refresh on activation
    - Combat stat modifications
    
    Mechanics:
    - Stacks build up to 3
    - At 3 stacks, activates Phoenix Pursuit
    - Duration refreshes on activation
    - Can hit multiple targets
    """
    def __init__(self):
        super().__init__(
            "Phoenix Pursuit",
            duration=3,  # Initial duration for stack building
            permanent=False,
            category=EffectCategory.COMBAT
        )
        self.stacks = 0
        self.activated = False
        self.last_refresh = None  # Track when duration was last refreshed
        self.targets = set()  # Track affected targets

    def on_apply(self, character, round_number: int) -> str:
        """Initialize timing and display initial message"""
        self.initialize_timing(round_number, character.name)
        self.last_refresh = round_number
        
        return f"🔥 `Phoenix energy builds within {character.name}`\n" + \
               f"• `Heat Level: {self.stacks}/3`"

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Show pursuit status at start of turn"""
        if character.name != turn_name:
            return []

        if self.activated:
            return [f"🔥 Phoenix Pursuit Active on {character.name}\n" + \
                   "• Movement Speed +5 ft\n" + \
                   "• DEX Score +4\n" + \
                   "• Quick Attack MP -2\n" + \
                   "• Ember Shift available"]
        else:
            return [f"🔥 Heat Attunement: {self.stacks}/3\n" + \
                   "• Awaiting full attunement"]

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Handle duration tracking and state updates"""
        if character.name != turn_name:
            return []

        # Calculate remaining duration
        rounds_since_refresh = round_number - self.last_refresh
        if turn_name == self.timing.start_turn:
            rounds_since_refresh += 1
        turns_remaining = max(0, self.duration - rounds_since_refresh)

        if turns_remaining <= 0:
            # If we're not activated and duration expires, reduce stacks
            if not self.activated:
                self.stacks = max(0, self.stacks - 1)
                if self.stacks > 0:
                    # Reset duration if we still have stacks
                    self.last_refresh = round_number
                    self.timing.duration = 3
                    return [f"🔥 `Heat Level reduced to {self.stacks}/3`"]
                else:
                    # Mark for removal if no stacks
                    self.timing.duration = 0
                    return [f"🔥 `Heat dissipates from {character.name}`"]
            else:
                # Mark activated state for removal
                self.timing.duration = 0
                return [f"🔥 `Phoenix Pursuit fades from {character.name}`"]
        
        # Still active - show status
        if self.activated:
            return [f"🔥 `Phoenix Pursuit Active`\n" + \
                   f"• `{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining`"]
        else:
            return [f"🔥 `Heat Attunement: {self.stacks}/3`\n" + \
                   f"• `{turns_remaining} turn{'s' if turns_remaining != 1 else ''} until reset`"]

    def on_expire(self, character) -> str:
        """Clean up effect state"""
        msg = "🔥 `"
        if self.activated:
            msg += f"Phoenix Pursuit has worn off from {character.name}`"
        else:
            msg += f"Heat has dissipated from {character.name}`"
            
        # Clear state
        self.stacks = 0
        self.activated = False
        self.targets.clear()
        return msg

    def add_stacks(self, amount: int, character) -> str:
        """Update stacks and handle activation state"""
        old_stacks = self.stacks
        self.stacks = min(3, self.stacks + amount)
        was_activated = self.activated

        # Check for activation
        if self.stacks >= 3 and not was_activated:
            self.activated = True
            # Reset duration and update refresh time
            self._duration = 3
            self.timing.duration = 3
            self.last_refresh = self.timing.start_round
            
            return f"🔥 `{character.name}'s Phoenix Pursuit activates!`\n" + \
                   "• `Movement and combat abilities enhanced`\n" + \
                   "• `Duration: 3 turns`"
        
        elif was_activated:
            # Already activated - refresh duration
            self._duration = 3
            self.timing.duration = 3
            self.last_refresh = self.timing.start_round
            
            return f"🔥 `{character.name}'s Phoenix Pursuit refreshed`\n" + \
                   "• `Duration reset to 3 turns`"
        else:
            return f"🔥 `{character.name}'s heat increases`\n" + \
                   f"• `Heat Level: {self.stacks}/3`"

    def add_target(self, target_name: str) -> None:
        """Track a new target affected by the heat"""
        self.targets.add(target_name)

    def get_status_text(self, character) -> str:
        """Format effect for status display"""
        text = []
        
        if not self.activated:
            text = [
                "🔥 **Phoenix Pursuit (Building)**",
                f"• `Heat Level: {self.stacks}/3`",
                "• `Status: Awaiting full attunement`"
            ]
            
            if self.timing and self.last_refresh:
                rounds_passed = 0
                if self.timing.start_round:
                    rounds_passed = character.round_number - self.last_refresh
                remaining = max(0, self.duration - rounds_passed)
                text.append(f"• `{remaining} turn{'s' if remaining != 1 else ''} until reset`")
        else:
            text = [
                "🔥 **Phoenix Pursuit (Active)**",
                "**Effects:**",
                "• `Movement Speed: +5 ft`",
                "• `DEX Score: +4`",
                "• `Quick Attack: -2 MP`",
                "• `Ember Shift: Available`"
            ]
            
            if self.timing and self.last_refresh:
                rounds_passed = 0
                if self.timing.start_round:
                    rounds_passed = character.round_number - self.last_refresh
                remaining = max(0, self.duration - rounds_passed)
                text.append(f"\n• `Duration: {remaining} turn{'s' if remaining != 1 else ''}`")
                
            if self.targets:
                text.append("\n**Active Targets:**")
                for target in sorted(self.targets):
                    text.append(f"• `{target}`")
                
        return "\n".join(text)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            "stacks": self.stacks,
            "activated": self.activated,
            "last_refresh": self.last_refresh,
            "targets": list(self.targets)
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'SourceHeatWaveEffect':
        """Create from dictionary data"""
        effect = cls()
        effect.stacks = data.get('stacks', 0)
        effect.activated = data.get('activated', False)
        effect.last_refresh = data.get('last_refresh')
        effect.targets = set(data.get('targets', []))
        
        # Restore timing if it exists
        if timing_data := data.get('timing'):
            effect.timing = EffectTiming(**timing_data)
            
        return effect

class TargetHeatWaveEffect(BaseEffect):
    """Heat effect for the target character"""
    def __init__(self, source_character: str, stacks: int = 0, duration: int = 3):
        super().__init__(
            "Heat",
            duration=duration,
            permanent=False,
            category=EffectCategory.COMBAT
        )
        self.source = source_character
        self.stacks = min(3, stacks)
        self.effect_id = f"heat_ac_{source_character}"  # Unique ID for AC manager

    def on_apply(self, character, round_number: int) -> str:
        """Apply heat effect and create AC reduction"""
        self.initialize_timing(round_number, character.name)
        
        # Apply AC reduction through manager
        character.modify_ac(self.effect_id, -self.stacks, priority=50)
        
        messages = []
        messages.append(self.format_effect_message(
            f"Heat effect on {character.name} ({self.stacks}/3)",
            [f"AC reduced by {self.stacks}"]
        ))
        
        # Apply fire vulnerability at 3 stacks
        if self.stacks >= 3:
            character.defense.damage_vulnerabilities["fire"] = 50
            messages.append(self.format_effect_message(
                "Maximum heat reached!",
                ["Now vulnerable to fire damage"]
            ))
        
        return "\n".join(messages)

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Show heat status at start of turn"""
        if character.name == turn_name:
            details = [f"AC reduced by {self.stacks}"]
            if self.stacks >= 3:
                details.append("Vulnerable to fire")
                
            return [self.format_effect_message(
                f"Heat Level: {self.stacks}/3",
                details
            )]
        return []

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Handle duration tracking and effect updates"""
        if character.name == turn_name and not self.permanent:
            turns_remaining, should_expire = self.process_duration(round_number, turn_name)
            messages = []
            
            if turns_remaining and turns_remaining > 0:
                details = [
                    f"{turns_remaining} turns remaining",
                    f"AC reduced by {self.stacks}"
                ]
                if self.stacks >= 3:
                    details.append("Vulnerable to fire")
                messages.append(self.format_effect_message(
                    f"Heat Level: {self.stacks}/3",
                    details
                ))
            elif should_expire:
                messages.append(self.format_effect_message(
                    f"Heat effect wearing off from {character.name}",
                    [f"Current level: {self.stacks}/3"]
                ))
            
            return messages
        return []

    def on_expire(self, character) -> str:
        """Clean up all effects when heat expires"""
        try:
            # Remove AC modification through manager
            character.remove_ac_modifier(self.effect_id)

            # Remove vulnerability if it was applied
            if self.stacks >= 3 and "fire" in character.defense.damage_vulnerabilities:
                del character.defense.damage_vulnerabilities["fire"]
                
            return self.format_effect_message(f"Heat effect has worn off from {character.name}")
            
        except Exception as e:
            logger.error(f"Error cleaning up Heat effect: {str(e)}")
            return self.format_effect_message(
                f"Heat effect expired from {character.name}",
                ["(Cleanup error occurred)"]
            )

    def add_stacks(self, amount: int, character) -> str:
        """Add heat stacks and update AC reduction"""
        old_stacks = self.stacks
        new_stacks = min(3, old_stacks + amount)
        self.stacks = new_stacks
        
        # Update AC reduction through manager
        character.modify_ac(self.effect_id, -self.stacks, priority=50)
        
        messages = []
        if old_stacks < 3 and new_stacks >= 3:
            character.defense.damage_vulnerabilities["fire"] = 50
            messages.append(self.format_effect_message(
                f"{character.name} burning up!",
                [f"Heat Level {new_stacks}/3",
                 f"AC reduced by {new_stacks}",
                 "Now vulnerable to fire"]
            ))
        else:
            messages.append(self.format_effect_message(
                f"{character.name}'s heat increases",
                [f"Level {new_stacks}/3",
                 f"AC reduced by {new_stacks}"]
            ))
            
        return "\n".join(messages)
    
class DamageCategory(Enum):
    """Categories for grouping damage types"""
    PHYSICAL = "physical"
    MAGICAL = "magical"
    SPECIAL = "special"

class DamageType(Enum):
    # Physical damage types
    SLASHING = "slashing"
    PIERCING = "piercing"
    BLUDGEONING = "bludgeoning"
    
    # Magical damage types
    FIRE = "fire"
    ICE = "ice"
    ELECTRIC = "electric"
    RADIANT = "radiant"
    NECROTIC = "necrotic"
    ACID = "acid"
    POISON = "poison"
    PSYCHIC = "psychic"
    THUNDER = "thunder"
    FORCE = "force"
    SONIC = "sonic"
    WIND = "wind"
    WATER = "water"
    
    # Special types
    GENERIC = "generic"
    TRUE = "true"

    def __str__(self):
        return self.value

    @classmethod
    def from_string(cls, damage_type: str) -> 'DamageType':
        """Convert string to DamageType, defaulting to GENERIC"""
        try:
            return cls[damage_type.upper()]
        except KeyError:
            return cls.GENERIC

    def get_category(self) -> DamageCategory:
        if self in [DamageType.SLASHING, DamageType.PIERCING, DamageType.BLUDGEONING]:
            return DamageCategory.PHYSICAL
        elif self in [DamageType.TRUE, DamageType.GENERIC]:
            return DamageCategory.SPECIAL
        return DamageCategory.MAGICAL

class DamageResult:
    """Contains detailed information about damage calculation"""
    def __init__(self, 
                 final_damage: int,
                 original_damage: int,
                 absorbed_by_temp_hp: int = 0,
                 resistance_reduction: int = 0,
                 vulnerability_increase: int = 0,
                 weakness_reduction: int = 0):
        self.final_damage = final_damage
        self.original_damage = original_damage
        self.absorbed_by_temp_hp = absorbed_by_temp_hp
        self.resistance_reduction = resistance_reduction
        self.vulnerability_increase = vulnerability_increase
        self.weakness_reduction = weakness_reduction
        
    def get_description(self) -> List[str]:
        """Format damage calculation into readable output"""
        messages = []
        
        # Build main damage message
        if self.original_damage == self.final_damage:
            messages.append(f"{self.final_damage} damage")
            return messages
            
        # When damage was modified
        modifiers = []
        
        # Add resistance breakdown
        if self.resistance_reduction > 0:
            resist_text = f"Resisted ({self.resistance_reduction}%)"
            modifiers.append(resist_text)
            
        # Add vulnerability
        if self.vulnerability_increase > 0:
            vuln_text = f"Vulnerable ({self.vulnerability_increase}%)"
            modifiers.append(vuln_text)
            
        # Format final message
        damage_text = f"{self.original_damage} → {self.final_damage} damage"
        if modifiers:
            damage_text += f" [{' | '.join(modifiers)}]"
            
        messages.append(damage_text)
        
        # Add temp HP absorption if any
        if self.absorbed_by_temp_hp > 0:
            shield_text = f"{self.absorbed_by_temp_hp} absorbed by shield"
            messages.append(shield_text)
            
        return messages

class DamageCalculator:
    """Handles damage calculations including resistances and vulnerabilities"""
    
    @staticmethod
    def calculate_damage(
        base_damage: int,
        damage_type: DamageType,
        target: 'Character',
        attacker: Optional['Character'] = None
    ) -> DamageResult:
        """Calculate final damage after applying resistances and vulnerabilities"""
        if isinstance(damage_type, str):
            damage_type = DamageType.from_string(damage_type)
            
        if damage_type == DamageType.TRUE:
            return DamageResult(base_damage, base_damage)
            
        # Get all damage modifiers
        total_res = target.defense.get_total_resistance(str(damage_type))
        total_vul = target.defense.get_total_vulnerability(str(damage_type))
        weakness = 0
        
        # Attacker weakness
        if attacker:
            for effect in attacker.effects:
                if isinstance(effect, WeaknessEffect):
                    if effect.applies_to_damage_type(damage_type):
                        weakness += effect.percentage
        
        # Calculate damage before temp HP
        multiplier = (100 - total_res + total_vul - weakness) / 100
        modified_damage = round(base_damage * max(0, multiplier))
        
        # Handle temp HP
        absorbed = 0
        final_damage = modified_damage
        temp_hp_effects = [e for e in target.effects if isinstance(e, TempHPEffect)]
        
        for effect in sorted(temp_hp_effects, key=lambda e: e.remaining):  # Use lowest remaining first
            if final_damage <= 0:
                break
            temp_absorbed, final_damage = effect.absorb_damage(final_damage)
            absorbed += temp_absorbed
            
        return DamageResult(
            final_damage=final_damage,
            original_damage=base_damage,
            absorbed_by_temp_hp=absorbed,
            resistance_reduction=total_res,
            vulnerability_increase=total_vul,
            weakness_reduction=weakness
        )

class ResistanceEffect(BaseEffect):
    """
    Adds resistance to specific damage types.
    
    Features:
    - Supports percentage-based resistance
    - Combines with existing resistances (natural and other effects)
    - Visual feedback during combat
    - Proper duration tracking
    """
    def __init__(self, damage_type: str, percentage: int, duration: Optional[int] = None):
        name = f"{damage_type.title()} Resistance"
        super().__init__(
            name=name, 
            duration=duration, 
            category=EffectCategory.COMBAT
        )
        self.damage_type = DamageType.from_string(damage_type)
        self.percentage = percentage

    def on_apply(self, character, round_number: int) -> str:
        """Apply resistance and show total after stacking"""
        self.initialize_timing(round_number, character.name)
        
        # Add to effect-based resistances
        character.defense.damage_resistances[str(self.damage_type)] = self.percentage
        
        # Calculate total resistance
        total = character.defense.get_total_resistance(str(self.damage_type))
        natural = character.defense.natural_resistances.get(str(self.damage_type), 0)
        
        # Create details for message
        details = []
        
        # Add natural resistance info if any
        if natural > 0:
            details.append(f"Natural resistance: {natural}%")
            details.append(f"Effect resistance: {self.percentage}%")
            details.append(f"Total resistance: {total}%")
        else:
            details.append(f"Resistance: {self.percentage}%")
            
        # Add duration info
        if self.duration:
            details.append(f"Duration: {self.duration} turns")
        elif self.permanent:
            details.append("Duration: Permanent")
        
        # Return formatted message
        return self.format_effect_message(
            f"{character.name} gains {self.damage_type} resistance",
            details,
            emoji="🛡️"
        )

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Display resistance effect at start of character's turn"""
        if character.name != turn_name:
            return []
            
        # Calculate total resistance
        total = character.defense.get_total_resistance(str(self.damage_type))
        natural = character.defense.natural_resistances.get(str(self.damage_type), 0)
        effect = character.defense.damage_resistances.get(str(self.damage_type), 0)
        
        # Format details
        details = []
        
        # Add resistance breakdown
        if natural > 0:
            details.append(f"Natural: {natural}% | Effect: {effect}% | Total: {total}%")
        else:
            details.append(f"Resistance: {self.percentage}%")
            
        # Add duration info if applicable
        if not self.permanent and self.duration:
            rounds_completed = round_number - self.timing.start_round
            turns_remaining = max(0, self.duration - rounds_completed)
            if turns_remaining > 0:
                details.append(f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining")
        
        # Return formatted message
        return [self.format_effect_message(
            f"{character.name} resists {self.damage_type} damage",
            details,
            emoji="🛡️"
        )]

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Track duration and show expiry warning"""
        if character.name != turn_name or self.permanent:
            return []
            
        # Calculate remaining turns
        turns_remaining, should_expire = self.process_duration(round_number, turn_name)
        
        # Create expiry warning if needed
        if should_expire:
            return [self.format_effect_message(
                f"{self.damage_type} resistance will wear off from {character.name}",
                emoji="🛡️"
            )]
        elif turns_remaining > 0:
            # Format with duration
            return [self.format_effect_message(
                f"{self.damage_type} resistance continues",
                [f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"],
                emoji="🛡️"
            )]
            
        return []

    def on_expire(self, character) -> str:
        """Remove resistance and show remaining"""
        if str(self.damage_type) in character.defense.damage_resistances:
            del character.defense.damage_resistances[str(self.damage_type)]
            
            # Check remaining resistance
            natural = character.defense.natural_resistances.get(str(self.damage_type), 0)
            
            # Format message based on natural resistance
            if natural > 0:
                return self.format_effect_message(
                    f"{self.damage_type} resistance expired from {character.name}",
                    [f"Natural {natural}% resistance remains"],
                    emoji="🛡️"
                )
                
            return self.format_effect_message(
                f"{self.damage_type} resistance expired from {character.name}",
                emoji="🛡️"
            )
            
        return self.format_effect_message(
            f"{self.damage_type} resistance expired from {character.name}",
            emoji="🛡️"
        )

    def get_status_text(self, character) -> str:
        """Format resistance status for character sheet"""
        total = character.defense.get_total_resistance(str(self.damage_type))
        natural = character.defense.natural_resistances.get(str(self.damage_type), 0)
        
        text = [f"🛡️ **{self.damage_type.title()} Resistance**"]
        
        # Show breakdown if there's natural resistance
        if natural > 0:
            text.extend([
                f"• `Natural: {natural}%`",
                f"• `Effect: {self.percentage}%`",
                f"• `Total: {total}%`"
            ])
        else:
            text.append(f"• `Amount: {self.percentage}%`")
            
        # Add duration info
        if self.timing and self.timing.duration is not None:
            if hasattr(character, 'round_number'):
                rounds_passed = character.round_number - self.timing.start_round
                remaining = max(0, self.timing.duration - rounds_passed)
                text.append(f"• `{remaining} turn{'s' if remaining != 1 else ''} remaining`")
        elif self.permanent:
            text.append("• `Permanent`")
            
        return "\n".join(text)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            "damage_type": str(self.damage_type),
            "percentage": self.percentage
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'ResistanceEffect':
        """Create from saved dictionary data"""
        effect = cls(
            damage_type=data.get('damage_type', 'generic'),
            percentage=data.get('percentage', 0),
            duration=data.get('duration')
        )
        # Restore timing if it exists
        if timing_data := data.get('timing'):
            effect.timing = EffectTiming(**timing_data)
        return effect

class VulnerabilityEffect(BaseEffect):
    """
    Adds vulnerability to specific damage types.
    
    Features:
    - Supports percentage-based vulnerability
    - Combines with existing vulnerabilities (natural and other effects)
    - Visual feedback during combat
    - Proper duration tracking
    """
    def __init__(self, damage_type: str, percentage: int, duration: Optional[int] = None):
        name = f"{damage_type.title()} Vulnerability"
        super().__init__(
            name=name, 
            duration=duration, 
            category=EffectCategory.COMBAT
        )
        self.damage_type = DamageType.from_string(damage_type)
        self.percentage = percentage

    def on_apply(self, character, round_number: int) -> str:
        """Apply vulnerability and show total after stacking"""
        self.initialize_timing(round_number, character.name)
        
        # Add to effect-based vulnerabilities
        character.defense.damage_vulnerabilities[str(self.damage_type)] = self.percentage
        
        # Calculate total vulnerability
        total = character.defense.get_total_vulnerability(str(self.damage_type))
        natural = character.defense.natural_vulnerabilities.get(str(self.damage_type), 0)
        
        # Create details for message
        details = []
        
        # Add natural vulnerability info if any
        if natural > 0:
            details.append(f"Natural vulnerability: {natural}%")
            details.append(f"Effect vulnerability: {self.percentage}%")
            details.append(f"Total vulnerability: {total}%")
        else:
            details.append(f"Vulnerability: {self.percentage}%")
            
        # Add duration info
        if self.duration:
            details.append(f"Duration: {self.duration} turns")
        elif self.permanent:
            details.append("Duration: Permanent")
        
        # Return formatted message
        return self.format_effect_message(
            f"{character.name} gains {self.damage_type} vulnerability",
            details,
            emoji="⚠️"
        )

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Display vulnerability effect at start of character's turn"""
        if character.name != turn_name:
            return []
            
        # Calculate total vulnerability
        total = character.defense.get_total_vulnerability(str(self.damage_type))
        natural = character.defense.natural_vulnerabilities.get(str(self.damage_type), 0)
        effect = character.defense.damage_vulnerabilities.get(str(self.damage_type), 0)
        
        # Format details
        details = []
        
        # Add vulnerability breakdown
        if natural > 0:
            details.append(f"Natural: {natural}% | Effect: {effect}% | Total: {total}%")
        else:
            details.append(f"Vulnerability: {self.percentage}%")
            
        # Add duration info if applicable
        if not self.permanent and self.duration:
            rounds_completed = round_number - self.timing.start_round
            turns_remaining = max(0, self.duration - rounds_completed)
            if turns_remaining > 0:
                details.append(f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining")
        
        # Return formatted message
        return [self.format_effect_message(
            f"{character.name} vulnerable to {self.damage_type} damage",
            details,
            emoji="⚠️"
        )]

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Track duration and show expiry warning"""
        if character.name != turn_name or self.permanent:
            return []
            
        # Calculate remaining turns
        turns_remaining, should_expire = self.process_duration(round_number, turn_name)
        
        # Create expiry warning if needed
        if should_expire:
            return [self.format_effect_message(
                f"{self.damage_type} vulnerability will wear off from {character.name}",
                emoji="⚠️"
            )]
        elif turns_remaining > 0:
            # Format with duration
            return [self.format_effect_message(
                f"{self.damage_type} vulnerability continues",
                [f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"],
                emoji="⚠️"
            )]
            
        return []

    def on_expire(self, character) -> str:
        """Remove vulnerability and show remaining"""
        if str(self.damage_type) in character.defense.damage_vulnerabilities:
            del character.defense.damage_vulnerabilities[str(self.damage_type)]
            
            # Check remaining vulnerability
            natural = character.defense.natural_vulnerabilities.get(str(self.damage_type), 0)
            
            # Format message based on natural vulnerability
            if natural > 0:
                return self.format_effect_message(
                    f"{self.damage_type} vulnerability expired from {character.name}",
                    [f"Natural {natural}% vulnerability remains"],
                    emoji="⚠️"
                )
                
            return self.format_effect_message(
                f"{self.damage_type} vulnerability expired from {character.name}",
                emoji="⚠️"
            )
            
        return self.format_effect_message(
            f"{self.damage_type} vulnerability expired from {character.name}",
            emoji="⚠️"
        )

    def get_status_text(self, character) -> str:
        """Format vulnerability status for character sheet"""
        total = character.defense.get_total_vulnerability(str(self.damage_type))
        natural = character.defense.natural_vulnerabilities.get(str(self.damage_type), 0)
        
        text = [f"⚠️ **{self.damage_type.title()} Vulnerability**"]
        
        # Show breakdown if there's natural vulnerability
        if natural > 0:
            text.extend([
                f"• `Natural: {natural}%`",
                f"• `Effect: {self.percentage}%`",
                f"• `Total: {total}%`"
            ])
        else:
            text.append(f"• `Amount: {self.percentage}%`")
            
        # Add duration info
        if self.timing and self.timing.duration is not None:
            if hasattr(character, 'round_number'):
                rounds_passed = character.round_number - self.timing.start_round
                remaining = max(0, self.timing.duration - rounds_passed)
                text.append(f"• `{remaining} turn{'s' if remaining != 1 else ''} remaining`")
        elif self.permanent:
            text.append("• `Permanent`")
            
        return "\n".join(text)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            "damage_type": str(self.damage_type),
            "percentage": self.percentage
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'VulnerabilityEffect':
        """Create from saved dictionary data"""
        effect = cls(
            damage_type=data.get('damage_type', 'generic'),
            percentage=data.get('percentage', 0),
            duration=data.get('duration')
        )
        # Restore timing if it exists
        if timing_data := data.get('timing'):
            effect.timing = EffectTiming(**timing_data)
        return effect
    
class WeaknessEffect(BaseEffect):
    """Reduces damage dealt of specific types"""
    def __init__(self, damage_type: str, percentage: int, duration: Optional[int] = None):
        super().__init__(
            f"{percentage}% {damage_type} weakness",
            duration=duration,
            category=EffectCategory.COMBAT
        )
        self.damage_type = DamageType.from_string(damage_type)
        self.percentage = percentage

    def applies_to_damage_type(self, damage_type: DamageType) -> bool:
        if isinstance(damage_type, str):
            damage_type = DamageType.from_string(damage_type)
            
        return (
            self.damage_type == damage_type or
            self.damage_type == DamageType.GENERIC or
            (self.damage_type.get_category() == damage_type.get_category() and 
             damage_type != DamageType.TRUE)
        )

class TempHPEffect(BaseEffect):
    """Provides temporary hit points that absorb damage"""
    def __init__(self, amount: int, duration: Optional[int] = None):
        super().__init__(
            f"Temporary HP Shield",
            duration=duration,
            permanent=duration is None,  # Make permanent if no duration specified
            category=EffectCategory.RESOURCE
        )
        self.amount = amount
        self.remaining = amount
        self.applied = False  # Track if currently applied to avoid double-application

    def on_apply(self, character, round_number: int) -> str:
        """Apply temp HP to character's resources"""
        self.initialize_timing(round_number, character.name)
        
        if not self.applied:
            character.resources.current_temp_hp = self.amount
            character.resources.max_temp_hp = self.amount
            self.applied = True
            
            if self.permanent:
                return f"💟 `{character.name} gained {self.amount} temporary HP shield`"
            return f"💟 `{character.name} gained {self.amount} temporary HP shield for {self.duration} turns`"
        return ""
    
    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Handle duration tracking"""
        if character.name == turn_name and not self.permanent:
            turns_remaining = self.process_duration(round_number, turn_name)[0]
            if turns_remaining > 0:
                return [f"Shield will last {turns_remaining} more turn{'s' if turns_remaining != 1 else ''}"]
        return []

    def on_expire(self, character) -> str:
        """Clean up temp HP when effect expires"""
        if self.applied:
            character.resources.current_temp_hp = 0
            character.resources.max_temp_hp = 0
            self.applied = False
            return f"💟 `Temporary HP Shield has worn off from {character.name}`"
        return ""

    def absorb_damage(self, damage: int) -> Tuple[int, int]:
        """Returns (damage_absorbed, remaining_damage)"""
        if self.remaining <= 0:
            return 0, damage
        
        absorbed = min(self.remaining, damage)
        self.remaining -= absorbed
        
        # Update character's current temp HP
        if hasattr(self, '_character'):
            self._character.resources.current_temp_hp = self.remaining
            
        return absorbed, damage - absorbed

    def get_status_text(self, character) -> str:
        """Get status text with progress bar"""
        percentage = (self.remaining / self.amount) * 100 if self.amount > 0 else 0
        blocks = int(percentage / 10)
        bar = '█' * blocks + '░' * (10 - blocks)
        
        status = [
            f"**Temporary HP Shield**",
            "• A protective barrier that absorbs damage before regular HP is affected",
            f"**Shield Integrity:** `{self.remaining}/{self.amount}` ({percentage:.1f}%)",
            f"**Status:** `{bar}`"
        ]
        
        if self.duration and self.duration > 0:
            status.append(f"**Duration:** `{self.duration} turn(s)`")
            
        return "\n".join(status)
        
    @property
    def is_expired(self) -> bool:
        """Check if temp HP is depleted or duration expired"""
        return super().is_expired or self.remaining <= 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            "amount": self.amount,
            "remaining": self.remaining,
            "applied": self.applied
        })
        return data
        
    @classmethod
    def from_dict(cls, data: dict) -> 'TempHPEffect':
        """Create from dictionary data"""
        effect = cls(
            amount=data.get('amount', 0),
            duration=data.get('duration')
        )
        effect.remaining = data.get('remaining', effect.amount)
        effect.applied = data.get('applied', False)
        return effect
    
class ShockEffect(BaseEffect):
    """
    Applies a chance-based shock effect that can damage and stun.
    
    Features:
    - Configurable trigger chance (default 50%)
    - Support for dice notation in damage
    - Stun on successful shock proc (skips turn)
    - Duration tracking
    - Permanent option
    """
    def __init__(
        self, 
        damage: str, 
        chance: int = 50, 
        duration: Optional[int] = None,
        permanent: bool = False
    ):
        super().__init__(
            name="Shock",
            duration=duration,
            permanent=permanent,
            category=EffectCategory.COMBAT
        )
        self.damage = damage
        self.chance = min(100, max(0, chance))  # Clamp between 0-100
        self.last_damage = 0
        self.triggered_this_turn = False
        
    def _roll_damage(self, character) -> int:
        """Roll damage if dice notation, otherwise return static value"""
        if isinstance(self.damage, str) and ('d' in self.damage.lower() or 'D' in self.damage):
            total, _ = DiceRoller.roll_dice(self.damage, character)
            return total
        return int(self.damage)

    def on_apply(self, character, round_number: int) -> str:
        """Apply initial shock effect"""
        self.initialize_timing(round_number, character.name)
        
        # Format duration text
        details = []
        details.append(f"Damage: {self.damage} lightning")
        details.append(f"Shock Chance: {self.chance}%")
        
        if self.permanent:
            details.append("Effect is permanent")
        elif self.duration:
            details.append(f"Duration: {self.duration} turns")
        
        # Return formatted message using base class method
        return self.format_effect_message(
            f"{character.name} is afflicted by Shock",
            details,
            emoji="⚡"
        )

    def on_turn_start(self, character, round_number: int, turn_name: str) -> List[str]:
        """Process shock check at start of affected character's turn"""
        if character.name != turn_name:
            return []
            
        # Reset trigger status for new turn
        self.triggered_this_turn = False
            
        # Skip if rounds completed exceeds duration
        if not self.permanent and self.duration:
            rounds_completed = round_number - self.timing.start_round
            if rounds_completed >= self.duration:
                return []
                
        # Roll to see if shock triggers
        roll = random.randint(1, 100)
        messages = []
        
        shock_success = roll <= self.chance
        
        if shock_success:
            # Roll/calculate damage
            damage = self._roll_damage(character)
            self.last_damage = damage
            
            # Apply damage
            old_hp = character.resources.current_hp
            
            # Handle temp HP first
            absorbed = 0
            if character.resources.current_temp_hp > 0:
                absorbed = min(character.resources.current_temp_hp, damage)
                character.resources.current_temp_hp -= absorbed
                damage -= absorbed
                
            # Apply remaining damage to regular HP
            character.resources.current_hp = max(0, character.resources.current_hp - damage)
            
            # Create message details
            details = []
            if absorbed > 0:
                details.append(f"{absorbed} absorbed by temp HP")
            details.append(f"HP: {character.resources.current_hp}/{character.resources.max_hp}")
            
            # Mark as triggered
            self.triggered_this_turn = True
            
            # Apply skip effect for one turn
            skip = SkipEffect(duration=1, reason="Shocked")
            skip_msg = skip.on_apply(character, round_number)
            
            # Add to character's effects
            character.effects.append(skip)
            
            # Format shock message
            shock_msg = self.format_effect_message(
                f"{character.name} is shocked for {self.last_damage} lightning damage",
                details,
                emoji="⚡"
            )
            
            messages.append(shock_msg)
            messages.append(skip_msg)
        else:
            # Only show a message on failed check during combat
            if hasattr(character, 'round_number') or round_number > 1:
                messages.append(self.format_effect_message(
                    f"{character.name} resists shock",
                    [f"Rolled {roll} (needed {self.chance} or less)"],
                    emoji="⚡"
                ))
        
        # Get duration info
        if not self.permanent and self.duration:
            turns_remaining = max(0, self.duration - (round_number - self.timing.start_round))
            if turns_remaining > 0:
                plural = "s" if turns_remaining != 1 else ""
                details = [f"{turns_remaining} turn{plural} remaining"]
                if not self.triggered_this_turn:
                    details.append(f"Next check: {self.chance}% chance")
                status_msg = self.format_effect_message(
                    f"Shock effect active",
                    details,
                    emoji="⚡"
                )
                messages.append(status_msg)
        
        return messages

    def on_turn_end(self, character, round_number: int, turn_name: str) -> List[str]:
        """Handle duration tracking at end of turn"""
        if character.name != turn_name or self.permanent:
            return []
            
        # Calculate remaining turns
        turns_remaining, should_expire = self.process_duration(round_number, turn_name)
        
        # Format message based on remaining duration
        if should_expire:
            return [self.format_effect_message(
                f"Shock effect will wear off from {character.name}",
                emoji="⚡"
            )]
        elif turns_remaining > 0:
            return [self.format_effect_message(
                f"Shock effect continues",
                [f"{turns_remaining} turn{'s' if turns_remaining != 1 else ''} remaining"],
                emoji="⚡"
            )]
            
        return []
    
    def on_expire(self, character) -> str:
        """Clean message when effect expires"""
        return self.format_effect_message(
            f"Shock effect has worn off from {character.name}",
            emoji="⚡"
        )
        
    def get_status_text(self, character) -> str:
        """Format status text for character sheet display"""
        lines = [f"⚡ **{self.name}**"]
        
        # Add damage and chance info
        lines.append(f"• `Damage: {self.damage} per trigger`")
        lines.append(f"• `Trigger Chance: {self.chance}%`")
        if self.last_damage and self.triggered_this_turn:
            lines.append(f"• `Last damage: {self.last_damage}`")
            
        # Add duration info
        if self.timing and self.timing.duration is not None:
            if hasattr(character, 'round_number'):
                rounds_passed = character.round_number - self.timing.start_round
                remaining = max(0, self.timing.duration - rounds_passed)
                lines.append(f"• `{remaining} turn{'s' if remaining != 1 else ''} remaining`")
        elif self.permanent:
            lines.append("• `Permanent`")
            
        return "\n".join(lines)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        data = super().to_dict()
        data.update({
            "damage": self.damage,
            "chance": self.chance,
            "last_damage": self.last_damage,
            "triggered_this_turn": self.triggered_this_turn
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'ShockEffect':
        """Create from dictionary data"""
        effect = cls(
            damage=data.get('damage', "1d4"),
            chance=data.get('chance', 50),
            duration=data.get('duration'),
            permanent=data.get('permanent', False)
        )
        effect.last_damage = data.get('last_damage', 0)
        effect.triggered_this_turn = data.get('triggered_this_turn', False)
        
        # Restore timing if it exists
        if timing_data := data.get('timing'):
            effect.timing = EffectTiming(**timing_data)
            
        return effect