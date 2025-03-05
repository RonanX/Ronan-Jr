"""
Action star system for tracking and managing character action economy.

Features:
- Star tracking and usage
- Move cooldown management
- Database integration
- Round-based refresh
"""

from typing import List, Optional, Dict, Tuple
import logging

logger = logging.getLogger(__name__)

class ActionStars:
    """
    Handles action star management for a character.
    
    Stars are the primary action economy resource:
    - Characters start with max_stars (default 5)
    - Stars refresh at the start of each round
    - Stars can be spent on moves and actions
    - Some moves have cooldowns
    """
    
    def __init__(self, max_stars: int = 5):
        self.max_stars = max_stars
        self.current_stars = max_stars
        self.used_moves: Dict[str, int] = {}  # name: rounds_remaining
        self.last_refresh_round = 0

    def can_use(self, cost: int = 0, move_name: Optional[str] = None) -> Tuple[bool, str]:
        """
        Check if an action/move can be used.
        
        Args:
            cost: Star cost (0 for free actions)
            move_name: Optional move name to check cooldown
            
        Returns:
            (can_use, reason) tuple
        """
        # Check for cooldown first
        if move_name and move_name in self.used_moves:
            return False, f"{move_name} is on cooldown for {self.used_moves[move_name]} more rounds"
            
        # Then check star cost
        if cost > self.current_stars:
            return False, f"Not enough stars ({self.current_stars}/{cost})"
            
        return True, ""

    def use_stars(self, cost: int = 0, move_name: Optional[str] = None) -> None:
        """
        Use stars for an action/move.
        
        Args:
            cost: Star cost (0 for free actions)
            move_name: Optional move to put on cooldown
        """
        self.current_stars = max(0, self.current_stars - cost)
        
        if move_name:
            # Track move usage (cooldown handled separately)
            logger.debug(f"Using {cost} stars for {move_name}")

    def start_cooldown(self, move_name: str, duration: int) -> None:
        """Put a move on cooldown"""
        if duration > 0:
            self.used_moves[move_name] = duration
            logger.debug(f"{move_name} on {duration} round cooldown")

    def refresh(self, round_number: Optional[int] = None) -> None:
        """
        Refresh stars and process cooldowns.
        
        Args:
            round_number: Current round for cooldown tracking
        """
        # Only refresh once per round
        if round_number and round_number <= self.last_refresh_round:
            return
            
        self.current_stars = self.max_stars
        
        # Update cooldowns
        if round_number:
            self.last_refresh_round = round_number
            expired = []
            for move, rounds in self.used_moves.items():
                if rounds <= 1:
                    expired.append(move)
                else:
                    self.used_moves[move] = rounds - 1
                    
            # Remove expired cooldowns
            for move in expired:
                del self.used_moves[move]

    def clear_cooldowns(self) -> None:
        """Clear all move cooldowns"""
        self.used_moves.clear()

    def to_dict(self) -> dict:
        """Convert to dictionary for storage"""
        return {
            "max_stars": self.max_stars,
            "current_stars": self.current_stars,
            "used_moves": self.used_moves,
            "last_refresh_round": self.last_refresh_round
        }

    def add_bonus_stars(self, amount: int) -> int:
        """
        Add bonus stars to the character's current stars.
        
        These are additional stars earned from successful attacks or other
        special actions, separate from the normal star refresh.
        
        Args:
            amount: Number of bonus stars to add
            
        Returns:
            New total star count
        """
        if amount <= 0:
            return self.current_stars
            
        # Add stars up to maximum
        old_stars = self.current_stars
        self.current_stars = min(self.max_stars, self.current_stars + amount)
        
        # Log the bonus
        added = self.current_stars - old_stars
        if added > 0:
            print(f"Added {added} bonus stars")
            
        return self.current_stars

    @classmethod
    def from_dict(cls, data: dict) -> 'ActionStars':
        """Create from dictionary data"""
        stars = cls(max_stars=data.get('max_stars', 5))
        stars.current_stars = data.get('current_stars', stars.max_stars)
        stars.used_moves = data.get('used_moves', {})
        stars.last_refresh_round = data.get('last_refresh_round', 0)
        return stars