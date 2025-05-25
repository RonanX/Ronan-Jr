"""
Update to status_effects_handler.py to support displaying stat effects.

This extends the existing handler to properly format stat effects in the UI.
"""

from typing import Any, List, Optional
from discord import Embed, Color
from core.effects.condition import ConditionType, CONDITION_PROPERTIES

class StatusEffectHandler:
    """Handles formatting and display of status effects"""
    
    @staticmethod
    def add_special_resources(embed: Embed, character: Any) -> None:
        """Add special resource tracking to the status embed"""
        # AEP (Arcane Energy Points)
        aep = getattr(character, 'aep', 0)
        if aep > 0:
            progress = int((aep / 25) * 100)
            bar = '█' * (progress // 10) + '░' * (10 - (progress // 10))
            text = [f"Points: {aep}/25", f"Progress: {bar} {progress}%"]
            if aep >= 25:
                text.append("✨ **Arcane Ascension Ready!** ✨")
            embed.add_field(name="Arcane Energy", value="\n".join(text), inline=False)

        # Royal Fury
        fury = getattr(character, 'royal_fury', 0)
        if fury > 0:
            text = f"Points: {fury}/30"
            if fury >= 30:
                text += "\n👑 **Royal Fury Ready!** 👑"
            embed.add_field(name="Royal Fury", value=text, inline=False)

    @staticmethod
    def merge_stacking_effects(effects: List[Any]) -> List[Any]:
        """Merge effects that can stack (like Frostbite and Heat)"""
        merged = []
        stacking_effects = {}  # Dict to hold effects by name
        
        for effect in effects:
            effect_name = getattr(effect, 'name', '').lower()
            
            # Handle stackable effects
            if effect_name in ['frostbite', 'heat', 'phoenix pursuit']:
                if effect_name in stacking_effects:
                    # Add stacks to existing effect
                    existing = stacking_effects[effect_name]
                    if hasattr(existing, 'stacks'):
                        if effect_name == 'phoenix pursuit':
                            # For Phoenix Pursuit, just refresh duration
                            existing.duration = max(existing.duration, effect.duration)
                        else:
                            # For other effects, add stacks
                            existing.stacks = min(
                                5 if effect_name == 'frostbite' else 3,
                                existing.stacks + effect.stacks
                            )
                else:
                    stacking_effects[effect_name] = effect
            else:
                merged.append(effect)
        
        # Add merged stacking effects back to the list
        merged.extend(stacking_effects.values())
        return merged

    @staticmethod
    def get_effect_description(effect_name: str) -> str:
        """Get a description for each effect type"""
        descriptions = {
            'temporary hp': "A temporary buffer that absorbs damage before regular HP is affected.",
            'temp hp': "A temporary buffer that absorbs damage before regular HP is affected.",
            'burn': "A searing flame that deals continuous damage over time.",
            'frostbite': "Accumulating ice that slows movement and attacks. At 5 stacks, the target freezes solid.",
            'phoenix pursuit': "Empowered by embers, granting enhanced mobility and combat prowess.",
            'heat': "Weakened by intense heat, reducing defenses. At 3 stacks, becomes vulnerable to fire.",
            'ac boost': "Enhanced defensive capabilities through magical or physical means.",
            'ac reduction': "Compromised defenses, making the target easier to hit.",
            'regeneration': "Natural or magical healing that restores health over time.",
            'mana regen': "Accelerated magical energy recovery.",
            'shock': "Electrical damage that may temporarily stun the target.",
            'bleed': "Open wounds that cause escalating damage over time.",
            'confusion': "Mental interference that may cause erratic behavior.",
            'vulnerability': "A weakness to specific types of damage.",
            'resistance': "Enhanced protection against specific types of damage.",
            
            # Stat effects
            'strength boost': "Enhanced physical power, improving attack damage and athletics.",
            'strength reduction': "Diminished physical power, reducing attack damage and athletics ability.",
            'dexterity boost': "Improved agility and reflexes, enhancing accuracy and evasion.",
            'dexterity reduction': "Reduced agility and reflexes, impairing accuracy and evasion.",
            'constitution boost': "Increased stamina and resilience, improving health and endurance.",
            'constitution reduction': "Decreased stamina and resilience, weakening health and endurance.",
            'intelligence boost': "Enhanced mental acuity, improving arcane aptitude and knowledge.",
            'intelligence reduction': "Diminished mental acuity, reducing arcane aptitude and knowledge.",
            'wisdom boost': "Improved awareness and intuition, enhancing perception and mysticism.",
            'wisdom reduction': "Impaired awareness and intuition, reducing perception and mysticism.",
            'charisma boost': "Magnified presence and charm, improving social interactions and influence.",
            'charisma reduction': "Weakened presence and charm, reducing social interactions and influence.",

            # Movement Conditions
            'prone': "Target is lying on the ground. Ranged attacks are harder, but melee attacks are easier.",
            'grappled': "Target's movement is reduced to 0 and cannot be moved by non-grappling effects.",
            'restrained': "Target's movement is reduced to 0 and suffers combat penalties.",
            'airborne': "Target is temporarily lifted off the ground, avoiding melee combat and ground effects.",
            'slowed': "Target's movement speed is halved and cannot take reactions.",

            # Combat Conditions
            'blinded': "Target cannot see, suffering major combat penalties.",
            'deafened': "Target cannot hear, failing sound-based checks.",
            'marked': "Target is tagged for follow-up attacks, making them vulnerable.",
            'guarded': "Target has taken a defensive stance, improving their defenses.",
            'flanked': "Target is surrounded by enemies, losing tactical advantages.",

            # Control Conditions
            'incapacitated': "Target cannot take actions or reactions and fails certain saves.",
            'paralyzed': "Target cannot move or act, and melee hits are critical.",
            'charmed': "Target cannot attack the source and is vulnerable to their effects.",
            'frightened': "Target must move away from the source when possible.",
            'confused': "Target's actions are randomly determined each turn.",

            # Situational Conditions
            'hidden': "Target is concealed and harder to hit.",
            'invisible': "Target cannot be seen, granting combat advantages.",
            'underwater': "Target is submerged, affecting combat abilities.",
            'concentrating': "Target is maintaining an effect that requires concentration.",
            'surprised': "Target is caught off guard, losing their first turn.",

            # State Conditions
            'bleeding': "Target takes damage over time and leaves a blood trail.",
            'poisoned': "Target suffers from poison effects and penalties.",
            'silenced': "Target cannot cast verbal spells or make sound.",
            'exhausted': "Target suffers from severe fatigue penalties.",
        }
        return descriptions.get(effect_name.lower(), "")

    @staticmethod
    def format_temp_hp(character: Any) -> Optional[str]:
        """Format temp HP display for status menu"""
        current_temp = getattr(character.resources, 'current_temp_hp', 0)
        max_temp = getattr(character.resources, 'max_temp_hp', 0)
        
        if current_temp <= 0:
            return None
            
        # Format with consistent styling
        header = ["**Temporary HP Shield**"]
        header.append("• A protective barrier that absorbs damage before regular HP is affected")
        
        details = []
        if current_temp < max_temp:
            details.append(f"**Remaining Shield:** `{current_temp}/{max_temp}`")
        else:
            details.append(f"**Shield Amount:** `{current_temp}`")
        
        return "\n".join(header + details)

    @staticmethod
    def format_condition_details(effect: Any) -> List[str]:
        """Get detailed condition information for character sheet"""
        details = []
        
        # Try to get condition type
        if hasattr(effect, 'conditions'):
            for condition in effect.conditions:
                if props := CONDITION_PROPERTIES.get(condition):
                    emoji = props["emoji"]
                    name = condition.value.title()
                    description = StatusEffectHandler.get_effect_description(condition.value)
                    
                    # Add header
                    details.append(f"{emoji} **{name}**")
                    if description:
                        details.append(f"• {description}")
                    
                    # Add mechanical effects
                    if turn_effects := props.get("turn_effects", []):
                        details.append("**Effects:**")
                        details.extend(turn_effects)
                        
                    if hasattr(effect, 'duration') and effect.duration:
                        details.append(f"**Duration:** `{effect.duration} turn(s)`")
                        
        return details
    
    @staticmethod
    def format_move_effect(effect: Any, character: Any) -> List[str]:
        """Format move effect for status display"""
        lines = []
        
        # Get state emoji based on current effect system
        emoji = "✨"
        if hasattr(effect, 'get_emoji'):
            emoji = effect.get_emoji()
        elif hasattr(effect, '_get_emoji'):
            emoji = effect._get_emoji()
            
        # Get effect state in a compatible way
        state = None
        state_name = ""
        if hasattr(effect, 'get_phase_name') and callable(getattr(effect, 'get_phase_name')):
            state_name = effect.get_phase_name()
        elif hasattr(effect, 'state'):
            state = effect.state
            state_name = state.value.title() if hasattr(state, 'value') else str(state)
            
        # Add header with name and state
        if state_name:
            lines.append(f"{emoji} **{effect.name}** ({state_name})")
        else:
            lines.append(f"{emoji} **{effect.name}**")
        
        # Split description into bullet points if it contains semicolons
        description = getattr(effect, 'description', '')
        if description:
            if ';' in description:
                for part in description.split(';'):
                    if part := part.strip():
                        lines.append(f"• {part}")
            else:
                lines.append(f"• {description}")
        
        # Add phase timing information - support both old and new systems
        phase_info_added = False
        
        # Try new system first
        if hasattr(effect, 'get_remaining_turns') and callable(getattr(effect, 'get_remaining_turns')):
            phase = state_name.lower() if state_name else ""
            remaining = effect.get_remaining_turns()
            
            if remaining is not None:
                if "cast" in phase:
                    lines.append(f"• Casting completes in {remaining} turn(s)")
                    phase_info_added = True
                elif "active" in phase:
                    lines.append(f"• {remaining} turn(s) remaining")
                    phase_info_added = True
                elif "cooldown" in phase:
                    lines.append(f"• Cooldown: {remaining} turn(s) remaining")
                    phase_info_added = True
        
        # Fall back to old system if no phase info was added
        if not phase_info_added and state:
            current_phase = None
            remaining_turns = None
            
            # Try to get phase info from the effect
            if hasattr(effect, 'phases') and effect.phases:
                current_phase = effect.phases.get(state)
                if current_phase:
                    remaining_turns = current_phase.duration - current_phase.turns_completed
            
            # Add phase-specific details
            if remaining_turns is not None:
                if hasattr(state, 'value'):
                    if state.value == 'casting':
                        lines.append(f"• Cast Time: {remaining_turns} turn(s) remaining")
                    elif state.value == 'active':
                        lines.append(f"• Duration: {remaining_turns} turn(s) remaining")
                    elif state.value == 'cooldown':
                        lines.append(f"• Cooldown: {remaining_turns} turn(s) remaining")
        
        # Show target information
        if hasattr(effect, 'targets') and effect.targets:
            if isinstance(effect.targets, list) and len(effect.targets) > 0:
                # Get target names, handling various target formats
                target_names = []
                for target in effect.targets:
                    if hasattr(target, 'name'):
                        target_names.append(target.name)
                    elif isinstance(target, str):
                        target_names.append(target)
                    else:
                        target_names.append(str(target))
                
                if target_names:
                    lines.append(f"• Targets: {', '.join(target_names)}")
            elif hasattr(effect.targets, 'name'):
                lines.append(f"• Target: {effect.targets.name}")
        
        # Add cost information
        costs = []
        if hasattr(effect, 'mp_cost') and effect.mp_cost:
            if effect.mp_cost > 0:
                costs.append(f"MP: {effect.mp_cost}")
            else:
                costs.append(f"MP Gain: {abs(effect.mp_cost)}")
        
        if hasattr(effect, 'hp_cost') and effect.hp_cost:
            if effect.hp_cost > 0:
                costs.append(f"HP: {effect.hp_cost}")
            else:
                costs.append(f"Healing: {abs(effect.hp_cost)}")
        
        if hasattr(effect, 'star_cost') and effect.star_cost:
            costs.append(f"Stars: {effect.star_cost}")
        
        if costs:
            lines.append(f"• Costs: {', '.join(costs)}")
        
        # Add combat information
        combat_info = []
        if hasattr(effect, 'attack_roll') and effect.attack_roll:
            combat_info.append(f"Attack: {effect.attack_roll}")
        
        if hasattr(effect, 'damage') and effect.damage:
            combat_info.append(f"Damage: {effect.damage}")
            
        if hasattr(effect, 'save_type') and effect.save_type:
            save_info = f"Save: {effect.save_type.upper()}"
            if hasattr(effect, 'save_dc') and effect.save_dc:
                save_info += f" DC {effect.save_dc}"
            if hasattr(effect, 'half_on_save') and effect.half_on_save:
                save_info += " (Half on save)"
            combat_info.append(save_info)
            
        if combat_info:
            lines.append(f"• {' | '.join(combat_info)}")
        
        return lines

    @staticmethod
    def format_stat_effect(effect: Any, character: Any) -> List[str]:
        """Format stat effect for status display"""
        lines = []
        
        # Get base information
        emoji = getattr(effect, '_get_emoji', lambda: "💪")()
        stat_type = getattr(effect, 'stat_type', None)
        amount = getattr(effect, 'amount', 0)
        duration = getattr(effect, 'duration', None)
        permanent = getattr(effect, 'permanent', False)
        
        if not stat_type:
            return []
        
        # Get stat name
        stat_name = stat_type.name.title() if hasattr(stat_type, 'name') else str(stat_type)
        
        # Add header
        if amount >= 0:
            lines.append(f"{emoji} **{stat_name} Boost**")
        else:
            lines.append(f"{emoji} **{stat_name} Reduction**")
        
        # Add description
        description = StatusEffectHandler.get_effect_description(effect.name.lower())
        if description:
            lines.append(f"• {description}")
        
        # Get stat information
        try:
            if hasattr(character, 'stats'):
                # Get base and modified values for the stat
                base_value = character.stats.base.get(stat_type, 10)
                modified_value = character.stats.modified.get(stat_type, base_value)
                
                # Calculate modifiers
                base_mod = (base_value - 10) // 2
                current_mod = (modified_value - 10) // 2
                mod_change = current_mod - base_mod
                
                # Format sign
                sign = "+" if amount > 0 else ""
                
                # Add stat info
                lines.append(f"• **Modification:** `{sign}{amount}`")
                lines.append(f"• **Base Value:** `{base_value} ({base_mod:+})`")
                lines.append(f"• **Current Value:** `{modified_value} ({current_mod:+})`")
                
                # Add modifier impact if changed
                if mod_change != 0:
                    lines.append(f"• **Modifier Change:** `{mod_change:+}`")
        except Exception as e:
            # Fallback if we can't get stat info
            sign = "+" if amount > 0 else ""
            lines.append(f"• **Modification:** `{sign}{amount}`")
        
        # Add duration info
        if permanent:
            lines.append("• **Duration:** `Permanent`")
        elif duration is not None:
            s = "s" if duration != 1 else ""
            lines.append(f"• **Duration:** `{duration} turn{s}`")
        
        return lines

    @staticmethod
    def format_effects(effects: List[Any], character: Any = None) -> List[str]:
        """Format effect descriptions with better organization and visuals"""
        effect_texts = []
        
        # Add temp HP first if present
        if character:
            temp_hp_text = StatusEffectHandler.format_temp_hp(character)
            if temp_hp_text:
                effect_texts.append(temp_hp_text)
                effect_texts.append("─" * 40)  # Separator line
        
        # Early return if no effects
        if not effects or len(effects) == 0:
            return effect_texts
        
        # Merge stacking effects first
        effects = StatusEffectHandler.merge_stacking_effects(effects)
        
        # Group effects by type for better organization
        stat_effects = []
        ac_effects = []
        condition_effects = []
        move_effects = []
        other_effects = []
        
        for effect in effects:
            # Skip placeholder effects
            if getattr(effect, 'type', '') == 'placeholder':
                continue
            
            # Categorize by effect type
            effect_name = getattr(effect, 'name', 'Unknown Effect').lower()
            
            # Check if this is a stat effect
            if hasattr(effect, 'stat_type'):
                stat_effects.append(effect)
                continue
                
            # Check if this is an AC effect
            if 'ac ' in effect_name or effect_name.startswith('ac '):
                ac_effects.append(effect)
                continue
                
            # Check if this is a condition effect
            if hasattr(effect, 'conditions'):
                condition_effects.append(effect)
                continue
                
            # Check if this is a move effect
            if (hasattr(effect, 'state') or 
                hasattr(effect, 'phases') or 
                hasattr(effect, 'get_phase_name') or 
                hasattr(effect, 'phase') or
                hasattr(effect, 'cast_time') or
                hasattr(effect, 'star_cost')):
                move_effects.append(effect)
                continue
                
            # Otherwise, add to other effects
            other_effects.append(effect)
        
        # Format each category of effects
        
        # 1. Format stat effects
        for effect in stat_effects:
            try:
                # Use specialized formatter for stat effects
                formatted_text = StatusEffectHandler.format_stat_effect(effect, character)
                if formatted_text:
                    effect_texts.extend(formatted_text)
                    effect_texts.append("─" * 40)  # Separator line
            except Exception as e:
                # Fallback if formatter fails
                effect_texts.append(f"**{effect.name}**")
                effect_texts.append("─" * 40)  # Separator line
                
        # 2. Format AC effects
        for effect in ac_effects:
            try:
                # Basic formatting for AC effects
                emoji = getattr(effect, '_get_emoji', lambda: "🛡️")()
                amount = getattr(effect, 'amount', 0)
                sign = "+" if amount > 0 else ""
                
                effect_texts.append(f"{emoji} **{effect.name}**")
                description = StatusEffectHandler.get_effect_description(effect_name)
                if description:
                    effect_texts.append(f"• {description}")
                
                effect_texts.append(f"• **AC Modified:** `{sign}{amount}`")
                
                if getattr(effect, 'permanent', False):
                    effect_texts.append("• **Duration:** `Permanent`")
                elif hasattr(effect, 'duration') and effect.duration:
                    s = "s" if effect.duration != 1 else ""
                    effect_texts.append(f"• **Duration:** `{effect.duration} turn{s}`")
                
                effect_texts.append("─" * 40)  # Separator line
            except Exception as e:
                # Fallback
                effect_texts.append(f"**{effect.name}**")
                effect_texts.append("─" * 40)  # Separator line
                
        # 3. Format condition effects
        for effect in condition_effects:
            try:
                condition_details = StatusEffectHandler.format_condition_details(effect)
                if condition_details:
                    effect_texts.extend(condition_details)
                    effect_texts.append("─" * 40)  # Separator line
            except Exception as e:
                # Fallback
                effect_texts.append(f"**{effect.name}**")
                effect_texts.append("─" * 40)  # Separator line
                
        # 4. Format move effects
        for effect in move_effects:
            try:
                move_lines = StatusEffectHandler.format_move_effect(effect, character)
                if move_lines:
                    effect_texts.extend(move_lines)
                    effect_texts.append("─" * 40)  # Separator line
            except Exception as e:
                # Fallback
                effect_texts.append(f"**{effect.name}**")
                effect_texts.append("─" * 40)  # Separator line
                
        # 5. Format other effects
        for effect in other_effects:
            try:
                effect_name = getattr(effect, 'name', 'Unknown Effect')
                description = StatusEffectHandler.get_effect_description(effect_name)
                
                # Header with name
                header = [f"**{effect_name}**"]
                if description:
                    header.append(f"• {description}")
                
                # Details section
                details = []
                
                # Duration info
                if getattr(effect, 'permanent', False):
                    details.append("**Duration:** `Permanent`")
                elif hasattr(effect, 'duration') and effect.duration:
                    s = "s" if effect.duration != 1 else ""
                    details.append(f"**Duration:** `{effect.duration} turn{s}`")
                
                # Effect-specific details based on type
                if hasattr(effect, 'description'):
                    desc = getattr(effect, 'description', '')
                    if desc:
                        if ';' in desc:
                            bullets = [b.strip() for b in desc.split(';') if b.strip()]
                            details.append("**Effects:**")
                            details.extend(f"• `{bullet}`" for bullet in bullets)
                        else:
                            details.append(f"**Effect:** `{desc}`")
                
                # Combine everything
                effect_texts.append("\n".join(header + details))
                effect_texts.append("─" * 40)  # Separator line
            except Exception as e:
                # Fallback
                effect_texts.append(f"**{effect.name}**")
                effect_texts.append("─" * 40)  # Separator line
        
        # Add pending effect feedback if any exists
        if hasattr(character, 'effect_feedback'):
            pending_feedback = [f for f in character.effect_feedback if not f.displayed]
            if pending_feedback:
                if effect_texts:
                    effect_texts.append("")
                effect_texts.append("**Recent Effect Updates:**")
                for feedback in pending_feedback:
                    # Simply append the expiry message, which is already formatted
                    effect_texts.append(f"• `{feedback.effect_name} has worn off`")
        
        # Remove last separator if any
        return effect_texts[:-1] if effect_texts else []