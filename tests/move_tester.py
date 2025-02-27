"""
Test harness for move system timing verification.
Simulates combat without Discord dependencies.
"""

import sys
sys.path.append("D:/Games/Campaigns/Ronan Jr")

from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field
from core.character import Character, Stats, Resources, DefenseStats, StatType
from core.effects.move import MoveEffect, MoveState
import logging

logger = logging.getLogger(__name__)

@dataclass
class TestMove:
    """Test configuration for a move"""
    character: str      # Name of character using move
    move_name: str     # Name of the move
    description: str   # Move description/effects
    round_number: int  # Which round to use it on
    on_turn: str      # Whose turn to use it during
    star_cost: int = 0
    mp_cost: int = 0
    hp_cost: int = 0
    cast_time: Optional[int] = None
    duration: Optional[int] = None
    cooldown: Optional[int] = None

@dataclass 
class TurnEmbed:
    """Simulates Discord embed for turn announcements"""
    title: str
    description: Optional[str] = None
    fields: List[Dict[str, str]] = field(default_factory=list)
    
    def add_field(self, name: str, value: str):
        """Add a field to the embed"""
        self.fields.append({"name": name, "value": value})
        
    def __str__(self) -> str:
        """Format embed for display"""
        output = [f"{self.title}"]
        if self.description:
            output.append(f"{self.description}")
        for field in self.fields:
            output.append(f"\n{field['name']}:")
            output.append(field['value'])
        return "\n".join(output)

@dataclass
class TurnResult:
    """Records what happened during a turn"""
    character: str
    round_number: int
    turn_start_embed: Optional[TurnEmbed] = None
    effect_updates: Optional[TurnEmbed] = None
    effects_applied: Set[str] = field(default_factory=set)
    effects_ended: Set[str] = field(default_factory=set)

class MoveTester:
    """Tests move system timing and state transitions"""
    
    def __init__(self):
        """Initialize test environment"""
        # Create test characters
        self.characters = {
            "Attacker": self._create_test_character("Attacker"),
            "Defender": self._create_test_character("Defender"),
            "Support": self._create_test_character("Support")
        }
        self.results: List[TurnResult] = []
        self.round_number = 0
        
    def _create_test_character(self, name: str) -> Character:
        """Create a basic test character"""
        stats = Stats(
            base={stat: 10 for stat in StatType},
            modified={stat: 10 for stat in StatType}
        )
        resources = Resources(
            current_hp=100,
            max_hp=100,
            current_mp=100,
            max_mp=100
        )
        defense = DefenseStats(
            base_ac=10,
            current_ac=10
        )
        return Character(name, stats, resources, defense)

    def _process_effects(self, character: str, phase: str) -> Tuple[List[str], List[str]]:
        """
        Process effects for a character.
        Returns (turn_messages, update_messages)
        """
        char = self.characters[character]
        turn_messages = []
        update_messages = []
        
        for effect in char.effects[:]:
            # Start of turn processing
            if phase == "start":
                if start_msgs := effect.on_turn_start(char, self.round_number, character):
                    if isinstance(start_msgs, list):
                        turn_messages.extend(start_msgs)
                    else:
                        turn_messages.append(start_msgs)
                        
            # End of turn processing
            elif phase == "end":
                if end_msgs := effect.on_turn_end(char, self.round_number, character):
                    if isinstance(end_msgs, list):
                        update_messages.extend(end_msgs)
                    else:
                        update_messages.append(end_msgs)
                        
                # Check for expired effects
                if effect.is_expired:
                    if expire_msg := effect.on_expire(char):
                        update_messages.append(expire_msg)
                    char.effects.remove(effect)
                    
        return turn_messages, update_messages

    def _create_turn_start_embed(self, character: str, effect_messages: List[str]) -> TurnEmbed:
        """Create turn announcement embed"""
        embed = TurnEmbed(f"{character}'s Turn")
        
        if effect_messages:
            embed.add_field("Active Effects", "\n".join(effect_messages))
            
        return embed

    def _create_effect_updates_embed(self, messages: List[str]) -> Optional[TurnEmbed]:
        """Create effect updates embed if needed"""
        if not messages:
            return None
            
        embed = TurnEmbed("Effects Update")
        embed.add_field("Updates", "\n".join(messages))
        return embed

    def process_turn(self, character: str, moves: List[TestMove]) -> TurnResult:
        """Process a single character's turn"""
        result = TurnResult(character, self.round_number)
        char = self.characters[character]
        
        # Apply moves for this turn
        for move in moves:
            if (move.round_number == self.round_number and 
                move.on_turn == character):
                effect = MoveEffect(
                    name=move.move_name,
                    description=move.description,
                    star_cost=move.star_cost,
                    mp_cost=move.mp_cost,
                    hp_cost=move.hp_cost,
                    cast_time=move.cast_time,
                    duration=move.duration,
                    cooldown=move.cooldown
                )
                msg = char.add_effect(effect, self.round_number)
                result.effects_applied.add(move.move_name)
        
        # Process turn start effects
        turn_msgs, _ = self._process_effects(character, "start")
        if turn_msgs:
            result.turn_start_embed = self._create_turn_start_embed(
                character, turn_msgs
            )
        
        # Process turn end effects
        _, update_msgs = self._process_effects(character, "end")
        if update_msgs:
            result.effect_updates = self._create_effect_updates_embed(
                update_msgs
            )
        
        return result

    def run_test(self, moves: List[TestMove], rounds: int = 4) -> List[str]:
        """Run full test simulation"""
        messages = ["=== Move System Test ==="]
        
        for round_num in range(1, rounds + 1):
            self.round_number = round_num
            messages.append(f"\n=== Round {round_num} ===")
            
            # Process each character's turn
            for char_name in self.characters:
                messages.append(f"\n{char_name}'s Turn:")
                result = self.process_turn(char_name, moves)
                self.results.append(result)
                
                # Add turn start embed
                if result.turn_start_embed:
                    messages.append(str(result.turn_start_embed))
                    
                # Add effect updates embed
                if result.effect_updates:
                    messages.append(str(result.effect_updates))
                
                # Add effect summaries
                if result.effects_applied:
                    messages.append(f"  Effects Started: {', '.join(result.effects_applied)}")
                if result.effects_ended:
                    messages.append(f"  Effects Ended: {', '.join(result.effects_ended)}")
            
            # End of round - refresh stars
            for char in self.characters.values():
                char.refresh_stars()
        
        return messages

def run_tests():
    """Run test scenarios"""
    messages = []
    
    def clear_and_reset():
        """Reset test environment"""
        tester = MoveTester()
        # Clear any lingering effects
        for char in tester.characters.values():
            char.effects.clear()
            char.refresh_stars()
        return tester
        
    # Test 1: Basic Duration
    tester = clear_and_reset()
    
    # Test 1: Basic Duration
    messages = []
    messages.append("\n=== Test 1: Basic Duration ===")
    basic_moves = [
        TestMove(
            character="Attacker",
            move_name="Quick Strike",
            description="Basic attack with 2-turn effect",
            round_number=1,
            on_turn="Attacker",
            duration=2
        )
    ]
    messages.extend(tester.run_test(basic_moves, rounds=3))
    
    # Test 2: Cast Time -> Duration
    tester = clear_and_reset()
    messages.append("\n=== Test 2: Cast Time + Duration ===")
    cast_moves = [
        TestMove(
            character="Support",
            move_name="Healing Wave",
            description="AoE heal with cast time",
            round_number=1,
            on_turn="Support",
            cast_time=2,
            duration=2,
            star_cost=2
        )
    ]
    messages.extend(tester.run_test(cast_moves, rounds=5))
    
    # Test 3: Full Chain (Cast -> Active -> Cooldown)
    tester = clear_and_reset()
    messages.append("\n=== Test 3: Full Phase Chain ===")
    chain_moves = [
        TestMove(
            character="Defender",
            move_name="Ultimate Defense",
            description="Powerful defensive move",
            round_number=1,
            on_turn="Defender",
            cast_time=1,
            duration=2,
            cooldown=2,
            star_cost=3
        )
    ]
    messages.extend(tester.run_test(chain_moves, rounds=6))
    
    # Print results with turn structure
    print("\n".join(messages))
    
    # Print timing analysis
    print("\n=== Timing Analysis ===")
    for result in tester.results:
        if result.turn_start_embed or result.effect_updates:
            print(f"\nRound {result.round_number}, {result.character}:")
            if result.turn_start_embed:
                print(str(result.turn_start_embed))
            if result.effect_updates:
                print(str(result.effect_updates))

if __name__ == "__main__":
    run_tests()