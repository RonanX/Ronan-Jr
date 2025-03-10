"""
## src/modules/moves/data.py

Data structures for storing move information.
Handles both temporary and saved moves.

Features:
- Move data storage with versioning
- Moveset management with global references
- Backward compatibility with older versions
- JSON serialization for sharing
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

@dataclass
class MoveData:
    """
    Stores move information for saved moves.
    
    Version History:
    1: Initial version (name, description, costs, timing)
    2: Added uses/cooldown tracking
    3: Added basic attack parameters (attack_roll, damage)
    4: Added combat parameters (saves, conditions, roll timing)
    5: Added heat tracking support and target params
    6: Added move category support
    7: Deprecating save parameters (save_type, save_dc, half_on_save)
       Use description for save instructions instead
    """
    CURRENT_VERSION = 7

    # Version 1 parameters (base)
    name: str
    description: str
    mp_cost: int = 0
    hp_cost: int = 0
    star_cost: int = 0
    cast_time: Optional[int] = None
    duration: Optional[int] = None
    cast_description: Optional[str] = None

    # Version 2 parameters (uses/cooldown)
    uses: Optional[int] = None
    uses_remaining: Optional[int] = None
    cooldown: Optional[int] = None
    last_used_round: Optional[int] = None

    # Version 3 parameters (basic attack)
    attack_roll: Optional[str] = None  # e.g., "1d20+dex"
    damage: Optional[str] = None  # e.g., "2d6+str fire, 1d4 poison"
    crit_range: int = 20  # Natural roll needed for crit
    targets: Optional[int] = None  # Number of targets (for multi-target)
    
    # Version 4 parameters (combat)
    # These are deprecated in v7 but kept for backward compatibility
    save_type: Optional[str] = None  # str, dex, con, etc.
    save_dc: Optional[str] = None  # e.g., "8+prof+int"
    half_on_save: bool = False  # Whether save halves damage
    conditions: List[str] = field(default_factory=list)  # Applied conditions from ConditionType
    roll_timing: str = "active"  # When to apply rolls: "instant", "active" or "per_turn"
    
    # Version 5 parameters (enhanced combat)
    enable_heat_tracking: bool = False  # Whether to track heat stacks
    target_selection: str = "manual"    # How targets are selected: "manual", "random", "closest"
    
    # Version 6 parameters (UI enhancements)
    category: str = "Offense"    # Move category: "Offense", "Utility", "Defense", or custom
    
    # Version 7 parameters
    # No new fields, just better handling of description for saves
    
    version: int = CURRENT_VERSION
    custom_parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage"""
        data = {
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "mp_cost": self.mp_cost,
            "hp_cost": self.hp_cost,
            "star_cost": self.star_cost,
            "cast_time": self.cast_time,
            "duration": self.duration,
            "cast_description": self.cast_description,
            
            # Version 2+
            "uses": self.uses,
            "uses_remaining": self.uses_remaining,
            "cooldown": self.cooldown,
            "last_used_round": self.last_used_round,
            
            # Version 3+
            "attack_roll": self.attack_roll,
            "damage": self.damage,
            "crit_range": self.crit_range,
            "targets": self.targets,
            
            # Version 4+ (kept for backward compatibility)
            "save_type": self.save_type,
            "save_dc": self.save_dc,
            "half_on_save": self.half_on_save,
            "conditions": self.conditions,
            "roll_timing": self.roll_timing,
            
            # Version 5+
            "enable_heat_tracking": self.enable_heat_tracking,
            "target_selection": self.target_selection,
            
            # Version 6+
            "category": self.category,
            
            "custom_parameters": self.custom_parameters
        }
        # Remove None values
        return {k: v for k, v in data.items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: dict) -> 'MoveData':
        """
        Create from dictionary data with version handling.
        Newer versions will handle older move data formats.
        """
        # Extract base parameters
        version = data.get("version", 1)  # Default to version 1 if not specified
        
        # Create with required parameters
        move = cls(
            name=data["name"],
            description=data["description"],
            version=version
        )
        
        # Version 1 parameters
        move.mp_cost = data.get("mp_cost", 0)
        move.hp_cost = data.get("hp_cost", 0)
        move.star_cost = data.get("star_cost", 0)
        move.cast_time = data.get("cast_time")
        move.duration = data.get("duration")
        move.cast_description = data.get("cast_description")
            
        # Version 2+ parameters
        if version >= 2:
            move.uses = data.get("uses")
            move.uses_remaining = data.get("uses_remaining")
            move.cooldown = data.get("cooldown")
            move.last_used_round = data.get("last_used_round")
            
        # Version 3+ parameters
        if version >= 3:
            move.attack_roll = data.get("attack_roll")
            move.damage = data.get("damage")
            move.crit_range = data.get("crit_range", 20)
            move.targets = data.get("targets")
            
        # Version 4+ parameters
        if version >= 4:
            move.save_type = data.get("save_type")
            move.save_dc = data.get("save_dc")
            move.half_on_save = data.get("half_on_save", False)
            move.conditions = data.get("conditions", [])
            move.roll_timing = data.get("roll_timing", "active")
            
        # Version 5+ parameters
        if version >= 5:
            move.enable_heat_tracking = data.get("enable_heat_tracking", False)
            move.target_selection = data.get("target_selection", "manual")
            
        # Version 6+ parameters
        if version >= 6:
            move.category = data.get("category", "Offense")
        else:
            # Try to infer category from other fields for older versions
            if move.attack_roll or (move.damage and not move.save_type):
                move.category = "Offense"
            elif move.save_type and move.save_type in ["str", "dex", "con", "int", "wis", "cha"]:
                move.category = "Offense" 
            elif move.hp_cost < 0:  # Healing moves
                move.category = "Defense"
            else:
                # Default for older versions
                move.category = "Utility"
            
        # Store any unknown parameters for future versions
        known_keys = {
            "version", "name", "description", "mp_cost", "hp_cost", "star_cost",
            "cast_time", "duration", "cast_description", "uses", "uses_remaining",
            "cooldown", "last_used_round", "attack_roll", "damage", "crit_range",
            "targets", "save_type", "save_dc", "half_on_save", "conditions",
            "roll_timing", "enable_heat_tracking", "target_selection", "category",
            "custom_parameters"
        }
        
        # Store any unrecognized keys in custom_parameters
        custom_params = {
            k: v for k, v in data.items() 
            if k not in known_keys
        }
        if custom_params:
            move.custom_parameters.update(custom_params)
        
        # Also include custom_parameters from the data
        if "custom_parameters" in data and isinstance(data["custom_parameters"], dict):
            move.custom_parameters.update(data["custom_parameters"])
            
        return move
    
    def can_use(self, current_round: Optional[int] = None) -> tuple[bool, Optional[str]]:
        """
        Check if move can be used.
        Returns (can_use, reason) tuple.
        """
        # Check uses
        if self.uses is not None:
            if self.uses_remaining is None:
                self.uses_remaining = self.uses
            if self.uses_remaining <= 0:
                return False, f"No uses remaining (0/{self.uses})"
        
        # Check cooldown
        if (self.cooldown is not None and 
            self.last_used_round is not None and
            current_round is not None):
            rounds_since = current_round - self.last_used_round
            if rounds_since < self.cooldown:
                remaining = self.cooldown - rounds_since
                return False, f"On cooldown ({remaining} rounds remaining)"
        
        return True, None
    
    def use(self, current_round: Optional[int] = None) -> None:
        """Mark move as used"""
        # Track uses if configured
        if self.uses is not None:
            if self.uses_remaining is None:
                self.uses_remaining = self.uses
            self.uses_remaining = max(0, self.uses_remaining - 1)
            
        # Track cooldown if round provided
        if current_round is not None:
            self.last_used_round = current_round
    
    def refresh(self) -> None:
        """Refresh uses and reset cooldown"""
        if self.uses is not None:
            self.uses_remaining = self.uses
        self.last_used_round = None
        
    @property
    def needs_target(self) -> bool:
        """Whether this move needs a target"""
        return bool(self.attack_roll or (self.damage and not self.save_type))

@dataclass
class Moveset:
    """
    Collection of moves for a character.
    
    Can be:
    1. Character-specific with local moves
    2. Reference to a global moveset
    3. Hybrid with both reference and overrides
    """
    reference: Optional[str] = None  # Reference to global moveset
    moves: Dict[str, MoveData] = field(default_factory=dict)  # Local moves
    
    def add_move(self, move: MoveData) -> None:
        """Add a move to the local set"""
        self.moves[move.name.lower()] = move
    
    def get_move(self, name: str) -> Optional[MoveData]:
        """Get a move by name (case insensitive)"""
        return self.moves.get(name.lower())
    
    def remove_move(self, name: str) -> bool:
        """Remove a move by name. Returns True if found and removed."""
        name_lower = name.lower()
        if name_lower in self.moves:
            del self.moves[name_lower]
            return True
        return False
    
    def list_moves(self) -> List[str]:
        """Get list of all move names"""
        return [move.name for move in self.moves.values()]
    
    def get_moves_by_category(self, category: Optional[str] = None) -> List[MoveData]:
        """Get all moves in a specific category or all moves if category is None"""
        if category is None:
            return list(self.moves.values())
        
        return [
            move for move in self.moves.values() 
            if move.category.lower() == category.lower()
        ]
    
    def refresh_all(self) -> None:
        """Refresh all moves"""
        for move in self.moves.values():
            move.refresh()
    
    def clear(self) -> None:
        """Clear all moves"""
        self.moves.clear()
        self.reference = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        base = {
            "reference": self.reference,
            "moves": {}
        }
        
        # Add all moves
        for move_name, move in self.moves.items():
            base["moves"][move_name] = move.to_dict()
            
        return base
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Moveset':
        """Create from dictionary data"""
        moveset = cls(
            reference=data.get("reference")
        )
        
        # Load moves dictionary
        moves_data = data.get("moves", {})
        for move_name, move_data in moves_data.items():
            # Handle string names vs dictionary keys
            if isinstance(move_data, dict):
                # Create move from data
                move = MoveData.from_dict(move_data)
                moveset.add_move(move)
                
        return moveset