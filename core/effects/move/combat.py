"""
Combat processing system for handling attacks, damage, and bonuses.
"""

import random
import re
from typing import Dict, List, Set, Any, Optional
from core.character import StatType

class BonusOnHit:
    """
    Manages bonuses applied when an attack hits.
    """
    def __init__(self, stars=0, mp=0, hp=0, custom_note=None, debug_mode=True):
        """Initialize bonus tracker with specified values"""
        self.mp_bonus = mp
        self.hp_bonus = hp
        self.star_bonus = stars
        self.custom_note = custom_note
        self.debug_mode = debug_mode
        self.hit_count = 0
        
    def debug(self, message):
        """Print debug message if debug mode is enabled"""
        if self.debug_mode:
            print(f"[BonusOnHit] {message}")
    
    def reset(self):
        """Reset hit counter for new attack processing"""
        self.hit_count = 0
        self.debug("Reset hit counter")
        
    def register_hit(self):
        """Register a successful hit"""
        self.hit_count += 1
        self.debug(f"Registered hit. Total hits: {self.hit_count}")
        
    def get_hit_count(self) -> int:
        """Get the number of registered hits"""
        return self.hit_count
        
    def has_any_bonuses(self) -> bool:
        """Check if there are any bonuses to apply"""
        return (self.mp_bonus != 0 or self.hp_bonus != 0 or 
                self.star_bonus != 0 or self.custom_note is not None)
    
    def apply_bonuses(self, character):
        """
        Apply bonuses based on hit count
        
        Args:
            character: Character to receive bonuses
            
        Returns:
            str: Formatted message describing applied bonuses
        """
        if self.hit_count <= 0:
            return None
            
        bonus_parts = []
        
        # Apply MP bonus (multiplied by hit count)
        if self.mp_bonus != 0:
            total_mp = self.mp_bonus * self.hit_count
            if self.mp_bonus > 0:
                # Add MP
                old_mp = character.resources.current_mp
                character.resources.current_mp = min(
                    character.resources.max_mp,
                    old_mp + total_mp
                )
                bonus_parts.append(f"💙 MP: +{total_mp} ({character.resources.current_mp}/{character.resources.max_mp})")
            else:
                # Reduce MP
                old_mp = character.resources.current_mp
                character.resources.current_mp = max(
                    0,
                    old_mp + total_mp  # total_mp is negative
                )
                bonus_parts.append(f"💙 MP: {total_mp} ({character.resources.current_mp}/{character.resources.max_mp})")
        
        # Apply HP bonus (multiplied by hit count)
        if self.hp_bonus != 0:
            total_hp = self.hp_bonus * self.hit_count
            if self.hp_bonus > 0:
                # Heal HP
                old_hp = character.resources.current_hp
                character.resources.current_hp = min(
                    character.resources.max_hp,
                    old_hp + total_hp
                )
                bonus_parts.append(f"❤️ HP: +{total_hp} ({character.resources.current_hp}/{character.resources.max_hp})")
            else:
                # Damage HP
                old_hp = character.resources.current_hp
                character.resources.current_hp = max(
                    0,
                    old_hp + total_hp  # total_hp is negative
                )
                bonus_parts.append(f"❤️ HP: {total_hp} ({character.resources.current_hp}/{character.resources.max_hp})")
        
        # Apply star bonus (multiplied by hit count)
        if self.star_bonus > 0:
            total_stars = self.star_bonus * self.hit_count
            if hasattr(character, 'action_stars'):
                if hasattr(character.action_stars, 'add_stars'):
                    character.action_stars.add_stars(total_stars)
                    # Get current/max after adding
                    current_stars = character.action_stars.current_stars
                    max_stars = character.action_stars.max_stars
                else:
                    # Fallback
                    old_stars = character.action_stars.current_stars
                    character.action_stars.current_stars = min(
                        character.action_stars.max_stars,
                        old_stars + total_stars
                    )
                    current_stars = character.action_stars.current_stars
                    max_stars = character.action_stars.max_stars
                
                bonus_parts.append(f"⭐ +{total_stars} ({current_stars}/{max_stars})")
        
        # Add custom note with hit count multiplier
        if self.custom_note:
            if self.hit_count > 1:
                # Format with multiplier for multiple hits
                bonus_parts.append(f"{self.custom_note} x{self.hit_count}")
            else:
                bonus_parts.append(f"{self.custom_note}")
            
        # Format the bonus message with backticks for consistency
        if bonus_parts:
            return f"`{self.hit_count} {'Hits' if self.hit_count > 1 else 'Hit'}! | {' | '.join(bonus_parts)}`"
        
        return None
        
    @classmethod
    def from_dict(cls, data: Dict) -> 'BonusOnHit':
        """Create from dictionary data"""
        if not data:
            return cls()
            
        # Handle different formats
        if isinstance(data, dict):
            # Extract values with defaults
            stars = data.get("stars", 0)
            mp = data.get("mp", 0)
            hp = data.get("hp", 0)
            custom_note = data.get("note", None)
            
            instance = cls(stars=stars, mp=mp, hp=hp, custom_note=custom_note)
            return instance
        elif isinstance(data, (int, float)):
            # Simple numeric value (legacy support)
            return cls(stars=int(data))
        else:
            # Unknown format, return default
            return cls()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage"""
        result = {}
        if self.star_bonus != 0:
            result["stars"] = self.star_bonus
        if self.mp_bonus != 0:
            result["mp"] = self.mp_bonus
        if self.hp_bonus != 0:
            result["hp"] = self.hp_bonus
        if self.custom_note:
            result["note"] = self.custom_note
        
        return result

class CombatProcessor:
    """
    Handles attack rolls and damage application.
    """
    def __init__(self, debug_mode=False):
        """Initialize the combat processor"""
        self.debug_mode = debug_mode
        self.aoe_mode = "single"  # Default AOE mode
    
    def debug(self, message):
        """Print debug message if debug mode is enabled"""
        if self.debug_mode:
            print(f"[CombatProcessor] {message}")
    
    def perform_sync_attack(self,
                           source,
                           targets,
                           attack_roll: str,
                           damage: Optional[str] = None,
                           crit_range: int = 20,
                           reason: str = "Attack",
                           bonus_on_hit: Optional[BonusOnHit] = None) -> List[str]:
        """
        Process attack rolls and damage against targets synchronously.
        This version returns formatted messages immediately for inclusion in effect messages.
        
        Args:
            source: Character making the attack
            targets: List of target characters
            attack_roll: Dice formula for attack roll
            damage: Dice formula for damage
            crit_range: Natural roll for critical hit
            reason: Reason for the attack (move name)
            bonus_on_hit: Bonus tracker for hits
            
        Returns:
            List[str]: Messages describing results
        """
        messages = []
        
        # Ensure we have targets
        if not targets:
            return ["No targets specified for attack."]
        
        self.debug(f"Processing sync attack (count: {len(targets)})")
        
        # Set default bonus_on_hit if none provided
        if bonus_on_hit is None:
            bonus_on_hit = BonusOnHit()
            
        self.debug(f"Using hit bonus tracker: {bonus_on_hit.__dict__}")
        
        # Reset bonus counter for new attack
        bonus_on_hit.reset()
        
        # Format attack results message based on roll type
        is_multihit = 'multihit' in attack_roll.lower()
        has_advantage = 'advantage' in attack_roll.lower() and 'disadvantage' not in attack_roll.lower()
        has_disadvantage = 'disadvantage' in attack_roll.lower()
        
        # Get the attack modifier from the character's stats
        stat_mod = self._get_stat_modifier(source, attack_roll)
        
        # Multi-hit parsing
        multihit_count = 1
        if is_multihit:
            multihit_match = re.search(r'multihit\s+(\d+)', attack_roll.lower())
            if multihit_match:
                try:
                    multihit_count = int(multihit_match.group(1))
                except ValueError:
                    multihit_count = 1
                    
        # Determine hit/miss
        hit_targets = []
        
        # Generate attack roll(s)
        attack_rolls = []
        if is_multihit:
            # Roll multiple times for multihit
            for i in range(min(3, len(targets))):
                if has_advantage:
                    roll1, roll2 = random.randint(1, 20), random.randint(1, 20)
                    roll_value = max(roll1, roll2)
                    final_roll = roll_value + stat_mod + multihit_count
                    attack_rolls.append((roll1, roll2, final_roll, True, False))
                elif has_disadvantage:
                    roll1, roll2 = random.randint(1, 20), random.randint(1, 20)
                    roll_value = min(roll1, roll2)
                    final_roll = roll_value + stat_mod + multihit_count
                    attack_rolls.append((roll1, roll2, final_roll, False, True))
                else:
                    roll_value = random.randint(1, 20)
                    final_roll = roll_value + stat_mod + multihit_count
                    attack_rolls.append((roll_value, None, final_roll, False, False))
        else:
            # Single roll or one roll per target in multi mode
            if self.aoe_mode == 'single' or len(targets) == 1:
                if has_advantage:
                    roll1, roll2 = random.randint(1, 20), random.randint(1, 20)
                    roll_value = max(roll1, roll2)
                    final_roll = roll_value + stat_mod
                    attack_rolls.append((roll1, roll2, final_roll, True, False))
                elif has_disadvantage:
                    roll1, roll2 = random.randint(1, 20), random.randint(1, 20)
                    roll_value = min(roll1, roll2)
                    final_roll = roll_value + stat_mod
                    attack_rolls.append((roll1, roll2, final_roll, False, True))
                else:
                    roll_value = random.randint(1, 20)
                    final_roll = roll_value + stat_mod
                    attack_rolls.append((roll_value, None, final_roll, False, False))
            else:
                # Multi mode - one roll per target
                for target in targets:
                    if has_advantage:
                        roll1, roll2 = random.randint(1, 20), random.randint(1, 20)
                        roll_value = max(roll1, roll2)
                        final_roll = roll_value + stat_mod
                        attack_rolls.append((roll1, roll2, final_roll, True, False))
                    elif has_disadvantage:
                        roll1, roll2 = random.randint(1, 20), random.randint(1, 20)
                        roll_value = min(roll1, roll2)
                        final_roll = roll_value + stat_mod
                        attack_rolls.append((roll1, roll2, final_roll, False, True))
                    else:
                        roll_value = random.randint(1, 20)
                        final_roll = roll_value + stat_mod
                        attack_rolls.append((roll_value, None, final_roll, False, False))
        
        # Check which targets are hit based on AC
        if self.aoe_mode == 'single' or is_multihit:
            # Single mode or multihit - one roll applied to all targets or one roll per hit
            main_roll = attack_rolls[0][2]  # Use the first roll's final value
            for target in targets:
                if main_roll >= target.defense.current_ac:
                    hit_targets.append(target)
                    bonus_on_hit.register_hit()
                    self.debug(f"Target hit: {target.name}")
        else:
            # Multi mode - separate roll for each target
            for i, target in enumerate(targets):
                if i < len(attack_rolls) and attack_rolls[i][2] >= target.defense.current_ac:
                    hit_targets.append(target)
                    bonus_on_hit.register_hit()
                    self.debug(f"Target hit: {target.name}")
        
        # Format the message based on roll type and AOE mode
        if is_multihit:
            # Format multihit message - format changes based on advantage/disadvantage
            roll_strings = []
            for i, (roll1, roll2, final_roll, is_adv, is_disadv) in enumerate(attack_rolls):
                if is_adv:
                    roll_strings.append(f"[{roll1},{roll2}]+{stat_mod}+{multihit_count} → {final_roll}")
                elif is_disadv:
                    roll_strings.append(f"[{roll1},{roll2}]+{stat_mod}+{multihit_count} → {final_roll}")
                else:
                    roll_strings.append(f"[{roll1}]+{stat_mod}+{multihit_count} → {final_roll}")
            
            roll_string = f"{attack_roll}: {', '.join(roll_strings)}"
            
            # Process damage for hit targets
            total_damage = 0
            if hit_targets and damage:
                damage_values = []
                for _ in range(len(hit_targets)):
                    # Parse the damage formula
                    damage_dice = self._parse_damage_formula(damage)
                    damage_val = self._roll_damage(damage_dice, stat_mod)
                    damage_values.append(damage_val)
                    total_damage += damage_val
                
                damage_type = self._extract_damage_type(damage)
                damage_text = f" | 🏹 {' + '.join(map(str, damage_values))} {damage_type}"
                
                hits_count = len(hit_targets)
                hits_total = min(3, len(targets))
                
                messages.append(f"🎲 {roll_string} | Hits: {hits_count}/{hits_total} → {', '.join(t.name for t in hit_targets)}{damage_text} | 📝 {reason}")
            else:
                hits_count = len(hit_targets)
                hits_total = min(3, len(targets))
                
                if hits_count > 0:
                    messages.append(f"🎲 {roll_string} | Hits: {hits_count}/{hits_total} → {', '.join(t.name for t in hit_targets)} | 📝 {reason}")
                else:
                    messages.append(f"🎲 {roll_string} | Hits: 0/{hits_total} | MISS | 📝 {reason}")
        
        elif self.aoe_mode == 'single':
            # Single AOE mode - one roll applies to all targets
            roll1, roll2, final_roll, is_adv, is_disadv = attack_rolls[0]
            
            if is_adv:
                roll_string = f"{attack_roll}: [{roll1},{roll2}]+{stat_mod} → {final_roll} (advantage)"
            elif is_disadv:
                roll_string = f"{attack_roll}: [{roll1},{roll2}]+{stat_mod} → {final_roll} (disadvantage)"
            else:
                roll_string = f"{attack_roll}: [{roll1}]+{stat_mod} → {final_roll}"
            
            # Format target results
            target_results = []
            total_damage = 0
            
            for target in targets:
                hit = target in hit_targets
                hit_icon = "✅" if hit else "❌"
                
                if hit and damage:
                    # Parse damage formula and roll damage
                    damage_dice = self._parse_damage_formula(damage)
                    damage_val = self._roll_damage(damage_dice, stat_mod)
                    total_damage += damage_val
                    damage_type = self._extract_damage_type(damage)
                    
                    target_results.append(f"{target.name} {hit_icon} ({damage_val} {damage_type})")
                else:
                    target_results.append(f"{target.name} {hit_icon}")
            
            messages.append(f"🎲 {roll_string} | 🎯 {', '.join(target_results)} | 📝 {reason}")
            
            if total_damage > 0:
                messages.append(f"Total Damage: {total_damage}")
        
        else:  # aoe_mode == 'multi'
            # Multi AOE mode - separate roll for each target
            result_lines = []
            total_damage = 0
            hits_count = len(hit_targets)
            
            # Add header with hit summary
            result_lines.append(f"🎲 {attack_roll} | Hits: {hits_count}/{len(targets)}")
            
            # Add individual target results
            for i, target in enumerate(targets):
                if i < len(attack_rolls):
                    roll1, roll2, final_roll, is_adv, is_disadv = attack_rolls[i]
                    
                    if is_adv:
                        roll_text = f"[{roll1},{roll2}]+{stat_mod} → {final_roll}"
                    elif is_disadv:
                        roll_text = f"[{roll1},{roll2}]+{stat_mod} → {final_roll}"
                    else:
                        roll_text = f"[{roll1}]+{stat_mod} → {final_roll}"
                    
                    hit = target in hit_targets
                    hit_icon = "✅" if hit else "❌"
                    ac_text = f"AC {target.defense.current_ac}"
                    
                    if hit and damage:
                        # Parse damage formula and roll damage
                        damage_dice = self._parse_damage_formula(damage)
                        damage_val = self._roll_damage(damage_dice, stat_mod)
                        total_damage += damage_val
                        damage_type = self._extract_damage_type(damage)
                        
                        result_lines.append(f"• 🎯 {target.name} {hit_icon} {ac_text} | {roll_text} | ⚡ {damage_val} {damage_type}")
                    else:
                        result_lines.append(f"• 🎯 {target.name} {hit_icon} {ac_text} | {roll_text}" + (" | MISS" if not hit else ""))
            
            result_lines.append(f"📝 {reason}")
            
            if total_damage > 0:
                result_lines.append(f"Total Damage: {total_damage}")
                
            messages.append("\n".join(result_lines))
        
        # Apply bonuses and add bonus message
        if hit_targets and bonus_on_hit.has_any_bonuses():
            self.debug(f"Applying bonuses for {len(hit_targets)} hits")
            bonus_message = bonus_on_hit.apply_bonuses(source)
            if bonus_message:
                self.debug(f"Bonus message: {bonus_message}")
                messages.append(f"{bonus_message}")
                
                # Add custom note if present
                if bonus_on_hit.custom_note:
                    messages.append(f"{bonus_on_hit.custom_note}")
        
        return messages
    
    async def process_attack(self,
                           source,
                           targets,
                           attack_roll: str,
                           damage: Optional[str] = None,
                           crit_range: int = 20,
                           reason: str = "Attack",
                           bonus_on_hit: Optional[BonusOnHit] = None) -> List[str]:
        """
        Process attack rolls and damage against targets.
        
        This is the async version used for delayed execution.
        For immediate results, use perform_sync_attack instead.
        """
        # For compatibility, just call the sync version
        # In the future this could be enhanced with true async processing
        return self.perform_sync_attack(
            source=source,
            targets=targets,
            attack_roll=attack_roll,
            damage=damage,
            crit_range=crit_range,
            reason=reason,
            bonus_on_hit=bonus_on_hit
        )
    
    def preview_attack(self, source, targets, attack_roll, reason=None):
        """
        Creates a preview message for an attack without executing it.
        This helps with synchronous message formatting.
        """
        if not targets:
            return "No targets"
            
        target_names = []
        for target in targets:
            target_names.append(target.name)
        
        target_str = ", ".join(target_names)
        reason_text = f" ({reason})" if reason else ""
        return f"{attack_roll} against {target_str}{reason_text}"
    
    def _get_stat_modifier(self, character, attack_roll: str) -> int:
        """Extract the correct stat modifier from character for an attack roll"""
        # Default modifier
        stat_mod = 0
        
        # Extract the modifier from the attack roll string if present
        if "+" in attack_roll:
            stat_parts = attack_roll.split("+")
            if len(stat_parts) > 1:
                stat_name = stat_parts[1].lower().strip()
                
                # Match stat name to character's stats
                if stat_name == "str" or stat_name == "strength":
                    if hasattr(character, 'stats') and hasattr(character.stats, 'modified'):
                        value = character.stats.modified.get(StatType.STRENGTH, 10)
                        stat_mod = (value - 10) // 2
                elif stat_name == "dex" or stat_name == "dexterity":
                    if hasattr(character, 'stats') and hasattr(character.stats, 'modified'):
                        value = character.stats.modified.get(StatType.DEXTERITY, 10)
                        stat_mod = (value - 10) // 2
                elif stat_name == "con" or stat_name == "constitution":
                    if hasattr(character, 'stats') and hasattr(character.stats, 'modified'):
                        value = character.stats.modified.get(StatType.CONSTITUTION, 10)
                        stat_mod = (value - 10) // 2
                elif stat_name == "int" or stat_name == "intelligence":
                    if hasattr(character, 'stats') and hasattr(character.stats, 'modified'):
                        value = character.stats.modified.get(StatType.INTELLIGENCE, 10)
                        stat_mod = (value - 10) // 2
                elif stat_name == "wis" or stat_name == "wisdom":
                    if hasattr(character, 'stats') and hasattr(character.stats, 'modified'):
                        value = character.stats.modified.get(StatType.WISDOM, 10)
                        stat_mod = (value - 10) // 2
                elif stat_name == "cha" or stat_name == "charisma":
                    if hasattr(character, 'stats') and hasattr(character.stats, 'modified'):
                        value = character.stats.modified.get(StatType.CHARISMA, 10)
                        stat_mod = (value - 10) // 2
                else:
                    # Try to parse it as a number for backwards compatibility
                    try:
                        stat_mod = int(stat_name)
                    except ValueError:
                        pass
        
        return stat_mod
    
    def _parse_damage_formula(self, damage_str: str) -> List[int]:
        """Parse damage formula into dice components"""
        # Extract dice formula from the damage string (e.g., "2d6+str fire" -> "2d6")
        dice_match = re.search(r'(\d+)d(\d+)', damage_str)
        if dice_match:
            num_dice = int(dice_match.group(1))
            die_size = int(dice_match.group(2))
            return [die_size] * num_dice
        else:
            # Default to 1d8 if no valid dice formula
            return [8]
    
    def _roll_damage(self, dice: List[int], stat_mod: int) -> int:
        """Roll damage dice and add modifier"""
        # Roll each die and sum the results
        damage = sum(random.randint(1, die) for die in dice) + stat_mod
        return max(1, damage)  # Minimum damage of 1
    
    def _extract_damage_type(self, damage_str: str) -> str:
        """Extract damage type from damage string"""
        # Remove dice formula and stat modifier
        without_dice = re.sub(r'\d+d\d+(\+\w+)?', '', damage_str).strip()
        
        # Default to "damage" if no type specified
        if not without_dice:
            return "damage"
        
        # Return the first word as damage type if multiple words
        return without_dice.split()[0]
