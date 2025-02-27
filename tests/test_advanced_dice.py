"""
Concise test suite for the advanced dice rolling system.
"""

import pytest
import pytest_asyncio
import os
import re
import sys
import logging
from unittest.mock import Mock

# Add src to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from core.character import Character, Stats, Resources, DefenseStats, StatType
from utils.advanced_dice.calculator import DiceCalculator
from utils.advanced_dice.attack_calculator import AttackCalculator, AttackParameters

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class TestStats:
    """Mimics character stats for testing"""
    def __init__(self):
        self.value = 16  # +3 modifier
    def __sub__(self, other):
        return self.value - other

@pytest.fixture
def test_character():
    """Create test character with numeric stats"""
    char = Mock(spec=Character)
    char.name = "Test"
    
    # Create stat object that handles math operations
    char.stats.base = Mock()
    char.stats.base.str = TestStats()
    char.stats.modified = char.stats.base
    
    char.defense = Mock(spec=DefenseStats)
    char.defense.current_ac = 15
    return char

class TestDiceRolls:
    """Test basic dice functionality"""
    
    def test_basic_roll(self):
        """Test simple dice roll"""
        total, formatted, _ = DiceCalculator.calculate_complex("2d6")
        assert formatted.startswith("🎲 `")
        assert "[" in formatted
        assert total > 0

    def test_stat_modifier(self, test_character):
        """Test stat modifier addition"""
        total, formatted, _ = DiceCalculator.calculate_complex("d20+str", test_character)
        print(f"Output: {formatted}")
        assert "+3" in formatted
        assert "=" in formatted

    def test_multihit(self):
        """Test multihit formatting"""
        total, formatted, _ = DiceCalculator.calculate_complex("3d20 multihit 2")
        print(f"Output: {formatted}")
        assert "→" in formatted
        assert formatted.count("[") == 2

class TestAttackRolls:
    """Test attack roll functionality"""
    
    def test_basic_attack(self, test_character):
        """Test basic attack roll"""
        target = test_character
        params = AttackParameters(
            roll_expression="d20+str",
            character=test_character,
            targets=[target],
            damage_str="2d6 slashing"
        )
        message, embed = AttackCalculator.process_attack(params)
        print(f"Attack output: {message}")
        assert "🎲" in message
        assert test_character.name in message
        assert "AC 15" in message
        assert any(x in message for x in ["HIT", "MISS"])

    def test_multihit_attack(self, test_character):
        """Test multihit formatting"""
        params = AttackParameters(
            roll_expression="3d20 multihit 2",
            character=test_character,
            targets=[test_character],
            damage_str="1d6 slashing"
        )
        message, embed = AttackCalculator.process_attack(params)
        print(f"Multihit output: {message}")
        assert "Hits:" in message
        assert "→" in message

    def test_aoe_attack(self, test_character):
        """Test AoE attack"""
        targets = []
        for i in range(3):
            target = Mock(spec=Character)
            target.name = f"Target{i}"
            target.defense = Mock(spec=DefenseStats)
            target.defense.current_ac = 15
            targets.append(target)
            
        params = AttackParameters(
            roll_expression="d20+str",
            character=test_character,
            targets=targets,
            damage_str="2d6 fire",
            aoe_mode="single"
        )
        message, embed = AttackCalculator.process_attack(params)
        print(f"AoE output: {message}")
        assert "Hits:" in message
        for t in targets:
            assert t.name in message

if __name__ == "__main__":
    pytest.main([__file__, "-v"])