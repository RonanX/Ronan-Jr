"""
## src/modules/moves/data.py

Data structures for storing move information.
Handles both temporary and saved moves.

Features:
- Move data storage with versioning
- Moveset management with global references
- Backward compatibility with older versions
- JSON serialization for sharing

Example JSON import:

```json
{
  "reference": "character_moveset",
  "moves": {
    "quick_strike": {
      "name": "Quick Strike",
      "description": "A swift attack; Deals light damage; Can be used to start combos",
      "mp_cost": 0,
      "star_cost": 1,
      "attack_roll": "1d20+dex",
      "damage": "1d6+dex slashing",
      "category": "Offense",
      "version": 8
    },
    "power_blast": {
      "name": "Power Blast",
      "description": "A powerful energy attack; Pushes targets back; Can hit multiple enemies",
      "mp_cost": 15,
      "star_cost": 3,
      "cooldown": 3,
      "attack_roll": "1d20+int",
      "damage": "3d6+int force",
      "category": "Offense",
      "advanced_json": {
        "bonus_on_hit": {"mp": 2, "note": "Power Surge"},
        "aoe_mode": "single"
      },
      "version": 8
    },
    "healing_light": {
      "name": "Healing Light",
      "description": "Bathes allies in healing light; Restores health; Removes minor conditions",
      "mp_cost": 10,
      "hp_cost": -15,
      "star_cost": 2,
      "duration": 1,
      "category": "Defense",
      "version": 8
    },
    "ethereal_dash": {
      "name": "Ethereal Dash",
      "description": "Phase through solid matter; Move through obstacles; Escape grapples",
      "mp_cost": 8,
      "star_cost": 1,
      "cooldown": 0,
      "category": "Utility", 
      "version": 8
    }
  }
}

"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
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
    7: Deprecated save parameters and heat tracking
    8: Added bonus_on_hit, removed deprecated parameters
    
    Moveset Creation Guidelines:
    ----------------------------
    Star Cost Guidelines:
      - Light/Quick Attack: 1 star
      - Medium/Combo Attack: 2 stars
      - Heavy/Raw Heavy Attack: 3-5 stars (based on power level)
      - Utility/Defense: Varies based on usefulness (typically 1-2 stars)
    
    Resource Guidelines:
      - MP Cost: Primary resource cost for most moves
      - Cooldowns: Only moves with 3+ stars should have cooldowns
      - Uses: Alternative to MP cost for limited-use abilities
      - Some powerful moves may have both MP cost and cooldown
      - Some character-specific moves may have cooldown but no MP cost
    
    Naming/Description:
      - Move names should be concise and descriptive
      - Descriptions can use semicolons to separate different aspects
      - Include damage type in damage field (e.g., "1d6+str slashing")
      
    Combat Parameters:
      - attack_roll: Format as "1d20+stat" or variants
      - damage: Format as "XdY+stat damage_type"
      - multihit: Format attack as "XdY multihit Z" where Z is number of attacks
      - advantage/disadvantage: Add "advantage" or "disadvantage" to attack roll
    
    Advanced Parameters:
      - bonus_on_hit: Use for resource bonuses or effects that trigger on hit
      - aoe_mode: Use "single" for one roll against multiple targets, "multi" for separate rolls

    Category Guidelines:
      - Offense: Attacks, damage dealing moves, debuffs
      - Defense: Healing, shields, protective effects, buffs
      - Utility: Movement, positioning, resource management, non-combat effects
    """
    CURRENT_VERSION = 8

    # Version 1 parameters (base)
    name: str
    description: str

    # Add version as a proper field
    version: int = CURRENT_VERSION

    mp_cost: int = 0  # Primary resource cost - varies based on power
    hp_cost: int = 0  # Negative for healing effects
    star_cost: int = 0  # 1=Light, 2=Medium, 3-5=Heavy based on power level
    cast_time: Optional[int] = None  # Turns required to cast before effect triggers
    duration: Optional[int] = None  # How many turns the effect lasts after activation
    cast_description: Optional[str] = None  # Custom text for casting phase

    # Version 2 parameters (uses/cooldown)
    uses: Optional[int] = None  # Limited uses per combat (-1 for unlimited)
    uses_remaining: Optional[int] = None  # Current uses remaining
    cooldown: Optional[int] = None  # Recommended only for 3+ star moves
    last_used_round: Optional[int] = None  # Round when last used (for cooldown tracking)

    # Version 3 parameters (basic attack)
    attack_roll: Optional[str] = None  # e.g., "1d20+dex", "1d20+str advantage", "3d20 multihit 2"
    damage: Optional[str] = None  # e.g., "2d6+str fire, 1d4 poison"
    crit_range: int = 20  # Natural roll needed for crit
    targets: Optional[int] = None  # Number of targets (for multi-target)
    
    # Version 4+ parameters (combat)
    conditions: List[str] = field(default_factory=list)  # Applied conditions
    roll_timing: str = "active"  # When to apply rolls: "instant", "active" or "per_turn"
    
    # Version 6 parameters (UI enhancements)
    category: str = "Offense"  # Move category: "Offense", "Utility", "Defense", or custom
    
    # Version 8 parameters
    bonus_on_hit: Optional[Dict[str, Any]] = None  # Resource bonuses on hit
    aoe_mode: Optional[str] = None  # How AoE is handled: "single" or "multi"
    custom_parameters: Dict[str, Any] = field(default_factory=dict)  # For extensibility

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
            
            # Version 4+
            "conditions": self.conditions,
            "roll_timing": self.roll_timing,
            
            # Version 6+
            "category": self.category,
            
            # Version 8+
            "bonus_on_hit": self.bonus_on_hit,
            "aoe_mode": self.aoe_mode,
            
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
            move.conditions = data.get("conditions", [])
            move.roll_timing = data.get("roll_timing", "active")
            
        # Version 6+ parameters
        if version >= 6:
            move.category = data.get("category", "Offense")
        else:
            # Try to infer category from other fields for older versions
            if move.attack_roll or (move.damage and not data.get("save_type")):
                move.category = "Offense"
            elif data.get("save_type") and data.get("save_type") in ["str", "dex", "con", "int", "wis", "cha"]:
                move.category = "Offense" 
            elif move.hp_cost < 0:  # Healing moves
                move.category = "Defense"
            else:
                # Default for older versions
                move.category = "Utility"
        
        # Special handling for bonus_on_hit to support both direct and nested formats
        bonus_on_hit = data.get("bonus_on_hit")
        if bonus_on_hit:
            # If it's already a dictionary, use it directly
            if isinstance(bonus_on_hit, dict):
                move.bonus_on_hit = bonus_on_hit
            # If it's a string, try to parse it as JSON
            elif isinstance(bonus_on_hit, str):
                try:
                    import json
                    move.bonus_on_hit = json.loads(bonus_on_hit)
                except:
                    # If parsing fails, set a default value
                    move.bonus_on_hit = {"stars": 1}
            # Handle other types as needed
            else:
                # For any other type, set a default value
                move.bonus_on_hit = {"stars": 1}
        else:
            # Check for legacy parameters
            if data.get("enable_heat_tracking", False) or data.get("enable_hit_bonus", False):
                move.bonus_on_hit = {"stars": 1}
        
        # Version 8+ parameters
        if version >= 8:
            # Only set if not already set by bonus_on_hit handling
            if not hasattr(move, 'bonus_on_hit') or move.bonus_on_hit is None:
                move.bonus_on_hit = data.get("bonus_on_hit")
            move.aoe_mode = data.get("aoe_mode", "single")
        
        # Handle advanced_json if present (usually from test harness or Discord commands)
        advanced_json = data.get("advanced_json")
        if advanced_json:
            # Handle nested bonus_on_hit
            if isinstance(advanced_json, dict) and "bonus_on_hit" in advanced_json:
                move.bonus_on_hit = advanced_json["bonus_on_hit"]
            
            # Handle aoe_mode
            if isinstance(advanced_json, dict) and "aoe_mode" in advanced_json:
                move.aoe_mode = advanced_json["aoe_mode"]
        
        # Store any unknown parameters for future versions
        known_keys = {
            "version", "name", "description", "mp_cost", "hp_cost", "star_cost",
            "cast_time", "duration", "cast_description", "uses", "uses_remaining",
            "cooldown", "last_used_round", "attack_roll", "damage", "crit_range",
            "targets", "conditions", "roll_timing", "category", 
            "bonus_on_hit", "aoe_mode", "custom_parameters", "advanced_json",
            # Include deprecated keys to prevent them from going to custom_parameters
            "save_type", "save_dc", "half_on_save", "enable_heat_tracking", 
            "target_selection", "enable_hit_bonus"
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
    
    def validate(self) -> Tuple[bool, Optional[str]]:
        """
        Validate the move data according to established guidelines.
        Returns (is_valid, error_message)
        """
        # Validate required fields
        if not self.name:
            return False, "Move must have a name"
            
        # Validate star costs
        if self.star_cost < 0 or self.star_cost > 5:
            return False, "Star cost must be between 0 and 5"
        
        # Validate cooldown (should only be present for 3+ star moves)
        if self.cooldown and self.cooldown > 0 and self.star_cost < 3:
            return False, "Warning: Cooldowns typically only used for 3+ star moves"
        
        # Validate attack_roll format if present
        if self.attack_roll:
            if not ("d20" in self.attack_roll.lower() or "d20" in self.attack_roll.lower().split(' ')):
                return False, "Attack roll must use d20"
        
        # Validate damage includes type if present
        if self.damage and " " not in self.damage:
            return False, "Damage should include damage type (e.g., '1d6 slashing')"
        
        return True, None

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
        return bool(self.attack_roll or self.damage)

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