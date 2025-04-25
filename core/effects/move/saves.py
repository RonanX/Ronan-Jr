"""
Saving throw system for processing character saves against effects.
"""

import random
from typing import List, Optional, Set

from core.character import StatType

class SavingThrowProcessor:
    """
    Handles saving throw mechanics for effects.
    
    Processes saving throws against DCs with:
    - Support for all save types (STR, DEX, etc.)
    - Formatted messages for save results
    - Optional damage application
    - Half-damage on successful save option
    """
    def __init__(self, debug_mode=True):
        """Initialize the processor"""
        self.debug_mode = debug_mode
        self.targets_saved = set()  # Track which targets saved
        
    def debug_print(self, message):
        """Print debug messages if debug mode is enabled"""
        if self.debug_mode:
            print(f"[SaveProcessor] {message}")
    
    def schedule_save(self,
                     source, 
                     targets,
                     save_type: str,
                     save_dc: str,
                     effect_name: str,
                     half_on_save: bool = False,
                     damage: Optional[str] = None) -> None:
        """
        Schedule a saving throw to be processed later.
        This stores the save parameters for later execution.
        
        Args:
            source: Character causing the save
            targets: List of characters that need to save
            save_type: Type of save (str, dex, etc.)
            save_dc: DC formula (e.g. "8+prof+int")
            effect_name: Name of effect causing the save
            half_on_save: Whether to apply half damage on success
            damage: Optional damage formula to apply on failed save
        """
        save_params = {
            'source': source,
            'targets': targets,
            'save_type': save_type,
            'save_dc': save_dc,
            'effect_name': effect_name,
            'half_on_save': half_on_save,
            'damage': damage
        }
        
        # Store in source object for retrieval
        if not hasattr(source, '_pending_saves'):
            source._pending_saves = []
        source._pending_saves.append(save_params)
        
        self.debug_print(f"Scheduled save for {len(targets)} targets, type: {save_type}")
    
    async def process_save(self,
                         source, 
                         targets,
                         save_type: str,
                         save_dc: str,
                         effect_name: str,
                         half_on_save: bool = False,
                         damage: Optional[str] = None) -> List[str]:
        """
        Process a saving throw for a group of targets.
        Handles rolling, damage application, and messaging.
        
        Args:
            source: Character causing the save
            targets: List of characters that need to save
            save_type: Type of save (str, dex, etc.)
            save_dc: DC formula (e.g. "8+prof+int")
            effect_name: Name of effect causing the save
            half_on_save: Whether to apply half damage on success
            damage: Optional damage formula to apply on failed save
            
        Returns:
            List[str]: Messages describing the save results
        """
        # Import utilities here to avoid circular imports
        from utils.advanced_dice.calculator import DiceCalculator as DiceRoller
        
        self.debug_print(f"Processing saves for {len(targets)} targets")
        messages = []
        
        # Calculate actual DC
        dc_value = 10  # Default DC
        if save_dc:
            # Parse expressions like "8+prof+int"
            try:
                parts = save_dc.lower().replace(" ", "").split("+")
                dc_value = 0
                
                for part in parts:
                    if part.isdigit():
                        dc_value += int(part)
                    elif part == "prof":
                        dc_value += source.base_proficiency
                    elif part in ["str", "strength"]:
                        dc_value += source.stats.get_modifier(StatType.STRENGTH)
                    elif part in ["dex", "dexterity"]:
                        dc_value += source.stats.get_modifier(StatType.DEXTERITY)
                    elif part in ["con", "constitution"]:
                        dc_value += source.stats.get_modifier(StatType.CONSTITUTION)
                    elif part in ["int", "intelligence"]:
                        dc_value += source.stats.get_modifier(StatType.INTELLIGENCE)
                    elif part in ["wis", "wisdom"]:
                        dc_value += source.stats.get_modifier(StatType.WISDOM)
                    elif part in ["cha", "charisma"]:
                        dc_value += source.stats.get_modifier(StatType.CHARISMA)
            except Exception as e:
                self.debug_print(f"Error parsing save DC: {e}")
                
        self.debug_print(f"Calculated DC: {dc_value}")
            
        # Format a single message with all save results
        main_message = f"{save_type.upper()} Save DC {dc_value} | {effect_name}"
        
        # Process each target's save
        target_results = []
        for target in targets:
            # Get save modifier based on type
            save_mod = 0
            if save_type.lower() in ["str", "strength"]:
                save_mod = target.saves.get(StatType.STRENGTH, 0)
            elif save_type.lower() in ["dex", "dexterity"]:
                save_mod = target.saves.get(StatType.DEXTERITY, 0)
            elif save_type.lower() in ["con", "constitution"]:
                save_mod = target.saves.get(StatType.CONSTITUTION, 0)
            elif save_type.lower() in ["int", "intelligence"]:
                save_mod = target.saves.get(StatType.INTELLIGENCE, 0)
            elif save_type.lower() in ["wis", "wisdom"]:
                save_mod = target.saves.get(StatType.WISDOM, 0)
            elif save_type.lower() in ["cha", "charisma"]:
                save_mod = target.saves.get(StatType.CHARISMA, 0)
                
            # Roll the save
            roll_result = random.randint(1, 20)
            total = roll_result + save_mod
            
            # Check if save succeeds
            success = total >= dc_value
            if success:
                self.targets_saved.add(target.name)
                
            # Format target result
            result_text = f"{target.name}: {roll_result}+{save_mod}={total} | {'✅' if success else '❌'}"
            
            # Handle damage if applicable
            if damage:
                damage_dealt = 0
                
                if not success:
                    # Full damage on failure
                    damage_roll, _ = DiceRoller.roll_dice(damage, target)
                    damage_dealt = damage_roll
                elif half_on_save:
                    # Half damage on success with half_on_save
                    damage_roll, _ = DiceRoller.roll_dice(damage, target)
                    damage_dealt = damage_roll // 2
                    result_text += f" | Half dmg: {damage_dealt}"
                
                # Apply the damage
                if damage_dealt > 0:
                    # Handle any temp HP first
                    if target.resources.current_temp_hp > 0:
                        absorbed = min(target.resources.current_temp_hp, damage_dealt)
                        target.resources.current_temp_hp -= absorbed
                        damage_dealt -= absorbed
                        
                        if absorbed > 0:
                            result_text += f" | {absorbed} absorbed"
                    
                    # Apply remaining damage to regular HP
                    if damage_dealt > 0:
                        old_hp = target.resources.current_hp
                        target.resources.current_hp = max(0, old_hp - damage_dealt)
                        
                        if not success:
                            result_text += f" | {damage_dealt} damage"
            
            target_results.append(result_text)
            
        # Format final message with all results
        if target_results:
            formatted = f"🎯 `{main_message}` 🎯\n" + "\n".join(f"• `{result}`" for result in target_results)
            messages.append(formatted)
            
        return messages
