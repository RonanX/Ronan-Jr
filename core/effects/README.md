# Ronan Jr Effect System

This document explains the effect system used in the Ronan Jr game, including both standard effects and move effects.

## Overview

The effect system provides a framework for applying temporary and permanent effects to characters during gameplay. Effects can modify stats, apply damage over time, alter combat capabilities, and more.

### Key Components

- **BaseEffect**: The foundation class for all effects
- **EffectManager**: Handles application and removal of effects
- **MoveEffect**: Specialized effect system for character moves
- **EffectRegistry**: Central registry for all available effect types

## Standard Effects vs. Move Effects

### Standard Effects

Standard effects are simpler, synchronous effects that follow the base effect lifecycle:

- **Creation**: Effects are instantiated with parameters like name, duration, etc.
- **Application**: `on_apply()` called when added to a character
- **Processing**: `on_turn_start()` and `on_turn_end()` called during turns
- **Expiration**: `on_expire()` called when the effect is removed

Examples include: BurnEffect, ACEffect, DebugEffect, etc.

### Move Effects

Move effects are more complex, asynchronous effects designed specifically for character abilities:

- **Asynchronous**: Can perform async operations like attack rolls
- **Phase System**: Move through casting, active, and cooldown phases
- **Bridge Function**: Uses a bridge to connect with the bot's systems
- **Independent Manager**: Has its own manager in `core/effects/move/manager.py`

Move effects use their own implementation of the base effect hooks while maintaining compatibility with the overall system.

## Duration Handling

Effect duration is handled with two key properties:

1. **Display Duration** (`_display_duration`): What the user sees
2. **Internal Duration** (`_internal_duration`): Actual turns tracked internally

Special handling exists for effects applied "during own turn" vs. "not during own turn":

- **During own turn**: Application turn is "free", but displayed duration adjusts for user clarity
- **Not during own turn**: Internal and display duration are the same

## Using Effect Templates

The system includes a template (`effect_template.py`) to accelerate new effect creation:

```python
from core.effects.base import BaseEffect

class YourEffect(BaseEffect):
    def __init__(self, name="Your Effect", duration=3):
        super().__init__(
            name=name, 
            duration=duration,
            emoji="✨"  # Choose your effect's emoji
        )
        # Add your custom properties here
        
    def on_apply(self, character, round_number):
        # First call parent to initialize timing and state
        message = super().on_apply(character, round_number)
        
        # Add your custom application logic
        
        return message
        
    # Use standard implementations where possible
    def on_turn_start(self, character, round_number, turn_name):
        return self.standard_turn_start(character, round_number, turn_name)
        
    def on_turn_end(self, character, round_number, turn_name):
        return self.standard_turn_end(character, round_number, turn_name)
```

## Bulk Testing Support

The system supports a "bulk" parameter to apply multiple effects at once for testing:

```python
# Example of a bulk-compatible effect implementation
def __init__(self, name="Effect Name", duration=3, bulk=False):
    super().__init__(name=name, duration=duration)
    self.bulk = bulk
    
    if bulk:
        # Configure for bulk testing mode
        self.debug_mode = True
```

This allows for using the effect with bulk test commands in `commands/effects.py`.

## Best Practices

1. **Use standard helpers** when possible (standard_turn_start, standard_turn_end)
2. **Respect timing parameters** (`is_during_own_turn`) for proper duration calculation
3. **Use consistent message formatting** with `format_effect_message()`
4. **Add debug logging** with `self.debug()` for complex effects
5. **Ensure proper serialization** with `to_dict()` and `from_dict()`

## Integrating a New Effect

1. Create your effect class inheriting from BaseEffect
2. Implement required methods (on_apply, on_expire, etc.)
3. Register your effect with EffectRegistry
4. Add commands to utilize your effect

For move effects, you'll need to follow additional steps to integrate with the move system bridge.
