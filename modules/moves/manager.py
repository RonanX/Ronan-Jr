"""
## src/modules/moves/manager.py
Manager for move system integration.

Handles move creation, validation, and formatting.
Acts as a bridge between the move data system and effect system.

Features:
- Move validation
- Effect creation from moves
- Move info formatting
- Move state tracking
"""

import discord
from core.effects.move import MoveEffect, RollTiming
from core.effects.condition import ConditionType
from typing import Optional, List, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

class MoveManager:
    """Handles the integration between moves and the effect system"""
    
    @staticmethod
    def create_effect_from_data(
            move_data: 'MoveData',
            round_number: Optional[int] = None,
            targets: Optional[List['Character']] = None
        ) -> MoveEffect:
        """Create a MoveEffect from MoveData"""
        # Process conditions
        conditions = []
        if hasattr(move_data, 'conditions') and move_data.conditions:
            for cond_name in move_data.conditions:
                try:
                    cond_name = cond_name.strip().upper()
                    conditions.append(ConditionType[cond_name])
                except (KeyError, ValueError):
                    logger.warning(f"Invalid condition: {cond_name}")
                    
        # Get roll timing
        roll_timing = RollTiming.ACTIVE
        if hasattr(move_data, 'roll_timing') and move_data.roll_timing:
            try:
                if isinstance(move_data.roll_timing, str):
                    roll_timing = RollTiming(move_data.roll_timing)
                else:
                    roll_timing = move_data.roll_timing
            except ValueError:
                logger.warning(f"Invalid roll timing: {move_data.roll_timing}")
        
        # Create effect
        return MoveEffect(
            name=move_data.name,
            description=move_data.description,
            star_cost=move_data.star_cost,
            mp_cost=move_data.mp_cost,
            hp_cost=move_data.hp_cost,
            cast_time=move_data.cast_time,
            duration=move_data.duration,
            cooldown=move_data.cooldown,
            cast_description=move_data.cast_description,
            attack_roll=getattr(move_data, 'attack_roll', None),
            damage=getattr(move_data, 'damage', None),
            crit_range=getattr(move_data, 'crit_range', 20),
            save_type=getattr(move_data, 'save_type', None),
            save_dc=getattr(move_data, 'save_dc', None),
            half_on_save=getattr(move_data, 'half_on_save', False),
            conditions=conditions,
            roll_timing=roll_timing,
            uses=move_data.uses,
            targets=targets,
            enable_heat_tracking=getattr(move_data, 'enable_heat_tracking', False)
        )

    @staticmethod
    def validate_move_data(move_data: 'MoveData') -> Tuple[bool, Optional[str]]:
        """Validate move data for consistency"""
        # Check required fields
        if not move_data.name:
            return False, "Move must have a name"
            
        # Validate resource costs
        if move_data.mp_cost < -1000 or move_data.mp_cost > 1000:
            return False, "MP cost must be between -1000 and 1000"
            
        if move_data.hp_cost < -1000 or move_data.hp_cost > 1000:
            return False, "HP cost must be between -1000 and 1000"
            
        if move_data.star_cost < 0 or move_data.star_cost > 5:
            return False, "Star cost must be between 0 and 5"
            
        # Validate timing
        if move_data.cast_time is not None and move_data.cast_time < 0:
            return False, "Cast time cannot be negative"
            
        if move_data.duration is not None and move_data.duration < 0:
            return False, "Duration cannot be negative"
            
        if move_data.cooldown is not None and move_data.cooldown < 0:
            return False, "Cooldown cannot be negative"
            
        # Validate uses
        if move_data.uses is not None and move_data.uses < 1:
            return False, "Uses must be at least 1"
            
        # Validate combat parameters
        if hasattr(move_data, 'attack_roll') and move_data.attack_roll:
            if not move_data.attack_roll.lower().startswith(('1d20', 'd20')):
                return False, "Attack roll must use d20"
                
        if hasattr(move_data, 'crit_range') and move_data.crit_range:
            if move_data.crit_range < 1 or move_data.crit_range > 20:
                return False, "Crit range must be between 1 and 20"
                
        # All checks passed
        return True, None

    @staticmethod
    def format_move_info(move_data: 'MoveData') -> str:
        """Format move information for display"""
        lines = []
        
        # Description
        if move_data.description:
            lines.append(move_data.description.replace(';', '\n• '))
            lines.append("")
        
        # Costs
        costs = []
        if move_data.star_cost > 0:
            costs.append(f"⭐ {move_data.star_cost} stars")
        if move_data.mp_cost != 0:
            prefix = "💙 " if move_data.mp_cost > 0 else "💙 Gain "
            costs.append(f"{prefix}{abs(move_data.mp_cost)} MP")
        if move_data.hp_cost != 0:
            prefix = "❤️ " if move_data.hp_cost > 0 else "❤️ Heal "
            costs.append(f"{prefix}{abs(move_data.hp_cost)} HP")
        
        if costs:
            lines.append("**Costs:** " + ", ".join(costs))
        
        # Timing
        timing = []
        if move_data.cast_time:
            timing.append(f"Cast Time: {move_data.cast_time} turns")
        if move_data.duration:
            timing.append(f"Duration: {move_data.duration} turns")
        if move_data.cooldown:
            timing.append(f"Cooldown: {move_data.cooldown} turns")
        
        if timing:
            lines.append("**Timing:** " + " | ".join(timing))
        
        # Combat info
        combat_info = []
        if hasattr(move_data, 'attack_roll') and move_data.attack_roll:
            combat_info.append(f"Attack: {move_data.attack_roll}")
            
            if hasattr(move_data, 'roll_timing') and move_data.roll_timing:
                combat_info.append(f"Timing: {move_data.roll_timing}")
                
            if hasattr(move_data, 'crit_range') and move_data.crit_range != 20:
                combat_info.append(f"Crit Range: {move_data.crit_range}+")
                
        if hasattr(move_data, 'damage') and move_data.damage:
            combat_info.append(f"Damage: {move_data.damage}")
            
        if hasattr(move_data, 'save_type') and move_data.save_type:
            save_info = f"Save: {move_data.save_type.upper()}"
            if hasattr(move_data, 'save_dc') and move_data.save_dc:
                save_info += f" (DC {move_data.save_dc})"
            if hasattr(move_data, 'half_on_save') and move_data.half_on_save:
                save_info += " (Half on save)"
            combat_info.append(save_info)
            
        if combat_info:
            lines.append("**Combat:** " + " | ".join(combat_info))
        
        # Conditions
        if hasattr(move_data, 'conditions') and move_data.conditions:
            conditions = []
            for cond in move_data.conditions:
                if isinstance(cond, str):
                    conditions.append(cond.upper())
                else:
                    conditions.append(cond.name if hasattr(cond, 'name') else str(cond))
                    
            if conditions:
                lines.append("**Conditions:** " + ", ".join(conditions))
        
        # Uses
        if move_data.uses is not None:
            uses = move_data.uses_remaining if move_data.uses_remaining is not None else move_data.uses
            lines.append(f"**Uses:** {uses}/{move_data.uses}")
            
        # Cast text
        if move_data.cast_description:
            lines.append(f"**Cast Text:** {character.name} {move_data.cast_description} {move_data.name}")
            
        return "\n".join(lines)
    
class MovesetManager:
    """
    Central manager for all moveset operations.
    Provides a single interface for all moveset-related operations.
    """
    
    def __init__(self, bot):
        self.bot = bot
        
    async def get_character_movesets(self, character_name: str) -> Tuple[Dict[str, MoveData], Optional[str]]:
        """
        Get all movesets available to a character (both local and global).
        Returns a tuple of (moves_dict, global_reference)
        """
        char = self.bot.game_state.get_character(character_name)
        if not char:
            return {}, None
            
        local_moves = {}
        global_ref = char.moveset.reference
        
        # Get local moves
        for move_name in char.list_moves():
            move = char.get_move(move_name)
            local_moves[move_name.lower()] = move
            
        return local_moves, global_ref
        
    async def export_character_moveset(self, character_name: str, include_cooldowns: bool = False) -> Optional[str]:
        """
        Export a character's moveset to JSON for sharing
        """
        char = self.bot.game_state.get_character(character_name)
        if not char:
            return None
            
        # Create a clean copy of the moveset without cooldown/usage state
        export_moveset = Moveset()
        
        for move_name in char.list_moves():
            move = char.get_move(move_name)
            
            # Create a copy of the move
            move_copy = MoveData(
                name=move.name,
                description=move.description,
                mp_cost=move.mp_cost,
                hp_cost=move.hp_cost,
                star_cost=move.star_cost,
                cast_time=move.cast_time,
                duration=move.duration,
                cooldown=move.cooldown,
                cast_description=move.cast_description,
                attack_roll=move.attack_roll,
                damage=move.damage,
                crit_range=move.crit_range,
                save_type=move.save_type,
                save_dc=move.save_dc,
                half_on_save=move.half_on_save,
                roll_timing=move.roll_timing,
                uses=move.uses
            )
            
            # Optionally include current cooldown/usage state
            if include_cooldowns:
                move_copy.last_used_round = move.last_used_round
                move_copy.uses_remaining = move.uses_remaining
                
            export_moveset.add_move(move_copy)
            
        # Export to JSON
        return MoveLoader.export_moveset(export_moveset, pretty=True)
        
    async def import_moveset_to_character(self, character_name: str, json_data: str) -> Tuple[bool, str, int]:
        """
        Import a moveset to a character from JSON
        Returns (success, message, move_count)
        """
        char = self.bot.game_state.get_character(character_name)
        if not char:
            return False, f"Character '{character_name}' not found", 0
            
        # Parse JSON
        moveset = MoveLoader.import_moveset(json_data)
        if not moveset:
            return False, "Failed to parse moveset JSON", 0
            
        # Count existing moves that will be overwritten
        existing_names = set(char.list_moves())
        import_names = set(moveset.list_moves())
        overwrite_count = len(existing_names.intersection(import_names))
            
        # Add moves to character
        move_count = 0
        for move_name in moveset.list_moves():
            move = moveset.get_move(move_name)
            if move:
                char.add_move(move)
                move_count += 1
                
        # Save character
        await self.bot.db.save_character(char)
        
        # Generate result message
        if overwrite_count > 0:
            return True, f"Imported {move_count} moves ({overwrite_count} overwritten)", move_count
        else:
            return True, f"Imported {move_count} moves", move_count
            
    async def refresh_all_character_moves(self, character_name: str) -> Tuple[bool, int]:
        """
        Refresh all moves for a character (reset cooldowns and uses)
        Returns (success, refreshed_count)
        """
        char = self.bot.game_state.get_character(character_name)
        if not char:
            return False, 0
            
        # Refresh all moves
        char.refresh_moves()
        
        # Save character
        await self.bot.db.save_character(char)
        
        return True, len(char.list_moves())
        
    async def share_character_move(self, character_name: str, move_name: str) -> Tuple[bool, str, Optional[str]]:
        """
        Share a single move to the global move database
        Returns (success, message, share_id)
        """
        char = self.bot.game_state.get_character(character_name)
        if not char:
            return False, f"Character '{character_name}' not found", None
            
        # Get move
        move = char.get_move(move_name)
        if not move:
            return False, f"Move '{move_name}' not found", None
            
        # Create clean copy
        move_copy = MoveData(
            name=move.name,
            description=move.description,
            mp_cost=move.mp_cost,
            hp_cost=move.hp_cost,
            star_cost=move.star_cost,
            cast_time=move.cast_time,
            duration=move.duration,
            cooldown=move.cooldown,
            cast_description=move.cast_description,
            attack_roll=move.attack_roll,
            damage=move.damage,
            crit_range=move.crit_range,
            save_type=move.save_type,
            save_dc=move.save_dc,
            half_on_save=move.half_on_save,
            roll_timing=move.roll_timing,
            uses=move.uses
        )
        
        # Share move
        try:
            share_id = await self.bot.db.share_move(move_copy.to_dict())
            return True, f"Move '{move_name}' shared successfully", share_id
        except Exception as e:
            return False, f"Failed to share move: {str(e)}", None

