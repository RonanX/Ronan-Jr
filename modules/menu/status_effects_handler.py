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
    def format_effects(effects: List[Any], character: Any = None) -> List[str]:
        """Format effect descriptions with better organization and visuals"""
        effect_texts = []
        
        # Add temp HP first if present
        if character:
            temp_hp_text = StatusEffectHandler.format_temp_hp(character)
            if temp_hp_text:
                effect_texts.append(temp_hp_text)
                effect_texts.append("─" * 40)  # Separator line
        
        # Merge stacking effects first
        effects = StatusEffectHandler.merge_stacking_effects(effects)
        
        for effect in effects:
            # Skip placeholder effects
            if getattr(effect, 'type', '') == 'placeholder':
                continue

            effect_name = getattr(effect, 'name', 'Unknown Effect')
            
            # Handle conditions differently
            if hasattr(effect, 'conditions'):
                condition_details = StatusEffectHandler.format_condition_details(effect)
                if condition_details:
                    effect_texts.extend(condition_details)
                    effect_texts.append("─" * 40)
                continue
                
            # Handle other effects
            description = StatusEffectHandler.get_effect_description(effect_name)
            
            # Header with name and basic description
            header = [f"**{effect_name}**"]
            if description:
                header.append(f"• {description}")
            
            # Details section
            details = []
            
            # Duration info (except for stacking effects)
            if not any(x in effect_name.lower() for x in ['frostbite', 'heat']):
                if getattr(effect, 'permanent', False):
                    details.append("**Duration:** `Permanent`")
                elif hasattr(effect, 'duration') and effect.duration:
                    details.append(f"**Duration:** `{effect.duration} turn(s)`")
            
            # Effect-specific details
            if effect_name.lower() == 'frostbite':
                stacks = getattr(effect, 'stacks', 0)
                details.extend([
                    f"**Stacks:** `{stacks}/5`",
                    f"**Movement Speed:** `-{stacks * 5} ft`",
                    f"**Attack Roll:** `-{stacks}`"
                ])
                if stacks >= 5:
                    details.extend([
                        "**Status:** `Frozen Solid`",
                        "**Effects:**",
                        "• `Cannot take actions`",
                        "• `AC reduced to 5`"
                    ])
                    
            elif effect_name.lower() == 'heat':
                stacks = getattr(effect, 'stacks', 0)
                source = getattr(effect, 'source', 'Unknown')
                details.extend([
                    f"**Source:** `{source}`",
                    f"**Heat Stacks:** `{stacks}/3`",
                    f"**AC Reduction:** `-{stacks}`"
                ])
                if stacks >= 3:
                    details.append("**Status:** `Vulnerable to fire damage`")
                if hasattr(effect, 'duration') and effect.duration:
                    details.append(f"**Duration:** `{effect.duration} turn(s)`")
                    
            elif effect_name.lower() == 'phoenix pursuit':
                details.extend([
                    "**Effects:**",
                    "• `Movement Speed: +5 ft`",
                    "• `Quick Attack Cost: -2 MP`",
                    "• `Attack Roll: +2`",
                    "• `Ember Shift available as free action`",
                    "• `Duration refreshes on critical hit`"
                ])
                if hasattr(effect, 'duration') and effect.duration:
                    details.append(f"**Duration:** `{effect.duration} turn(s)`")
                    
            elif 'burn' in effect_name.lower():
                damage = getattr(effect, 'damage_dice', 'N/A')
                details.append(f"**Damage per Turn:** `{damage}`")
                    
            elif 'ac' in effect_name.lower():
                amount = getattr(effect, 'amount', 0)
                sign = '+' if amount > 0 else ''
                details.append(f"**AC Modified:** `{sign}{amount}`")
                
            # Custom effect handling
            elif hasattr(effect, 'description'):
                desc = getattr(effect, 'description', '')
                if desc:
                    if ';' in desc:
                        bullets = [b.strip() for b in desc.split(';') if b.strip()]
                        details.append("**Effects:**")
                        details.extend(f"• `{bullet}`" for bullet in bullets)
                    else:
                        details.append(f"**Effect:** `{desc}`")
            
            # Combine everything with proper spacing and separator
            effect_texts.append("\n".join(header + details))
            effect_texts.append("─" * 40)  # Separator line
                
        return effect_texts[:-1]  # Remove last separator
    