# Effect System Documentation

## Overview

The Effects System is designed to handle status effects with consistent duration tracking, message 
formatting, and state transitions. This README explains how to use the enhanced system with standardized 
helper methods and templates.

## Core Components

1. **BaseEffect** (core/effects/base.py): 
   - Base class with lifecycle hooks and helper methods
   - Handles state transitions and duration tracking
   - Provides standardized message formatting

2. **Template Effect** (examples/template_effect.py):
   - Starting point for new effects
   - Demonstrates proper implementation patterns
   - Contains examples for common effect types

3. **Effect Registry** (core/effects/manager.py):
   - Central registry for effect types
   - Handles effect creation and serialization
   - Provides effect application and removal

## Effect Lifecycle

Effects transition through these states:

```
CREATED → ACTIVE → EXPIRING → EXPIRED → REMOVED
```

- **CREATED**: Initial state after instantiation
- **ACTIVE**: Normal active state during effect duration
- **EXPIRING**: Final turn state before expiry (for warnings)
- **EXPIRED**: Ready for removal
- **REMOVED**: Fully removed from character

## Timing Behavior

Duration handling depends on when the effect was applied:

- **During Own Turn**: Applied during character's turn
  - Duration tick starts on the NEXT turn
  - For effects with duration=1, they last until the end of the NEXT turn
  
- **Not During Own Turn**: Applied outside character's turn
  - Duration tick starts on the CURRENT turn
  - For effects with duration=1, they expire at the end of the CURRENT turn

## Using the Helpers

### Message Formatting

```python
# Standard active message
self.create_standard_active_message(character, remaining_turns)

# Standard continues message
self.create_standard_continues_message(character, remaining_turns)

# Final turn message
self.create_standard_final_message(character)

# Standard expiry message
self.create_standard_expiry_message(character)

# Generic format with emoji and details
self.format_effect_message(message, details=[], emoji="✨")
```

### Turn Processing

```python
# Process turn start using standard handling with custom logic
standard_turn_start(character, round_number, turn_name, custom_logic)

# Process turn end using standard handling with custom logic
standard_turn_end(character, round_number, turn_name, custom_logic)
```

### Custom Logic Methods

When implementing custom logic for standard turn processing:

```python
def custom_turn_start_logic(self, character, round_number=None, turn_name=None):
    messages = []
    # Your custom logic here
    return messages

def custom_turn_end_logic(self, character, round_number=None, turn_name=None):
    messages = []
    # Your custom logic here
    return messages
```

## Creating a New Effect

1. **Copy the Template**: Start with template_effect.py
2. **Rename the Class**: Change TemplateEffect to your effect name
3. **Customize Parameters**: Add your effect-specific parameters to __init__
4. **Implement Logic**: Fill in custom_turn_start_logic and custom_turn_end_logic
5. **Update Lifecycle**: Modify on_apply and on_expire if needed
6. **Add Serialization**: Update to_dict and from_dict methods

## Common Patterns

### Basic Effect

```python
class SimpleEffect(BaseEffect):
    def __init__(self, name="Simple Effect", duration=3, value=1, **kwargs):
        super().__init__(name=name, duration=duration, **kwargs)
        self.value = value
        
    def custom_turn_start_logic(self, character, round_number=None, turn_name=None):
        messages = []
        messages.append(self.format_effect_message(
            f"{self.name} is active on {character.name}",
            details=[f"Value: {self.value}"]
        ))
        return messages
```

### Damage Over Time (DoT)

```python
def custom_turn_start_logic(self, character, round_number=None, turn_name=None):
    messages = []
    damage = roll_damage(self.damage_formula)
    old_hp = character.resources.current_hp
    character.resources.current_hp = max(0, old_hp - damage)
    messages.append(self.format_effect_message(
        f"{character.name} takes {damage} damage",
        details=[f"HP: {old_hp} → {character.resources.current_hp}"]
    ))
    return messages
```

### Stacking Effect

```python
def add_stack(self, amount=1, character=None):
    old_stacks = self.stacks
    self.stacks = min(self.max_stacks, self.stacks + amount)
    return format_message(f"Stacks: {old_stacks} → {self.stacks}")
    
def remove_stack(self, character, amount=1):
    old_stacks = self.stacks
    self.stacks = max(0, self.stacks - amount)
    if self.stacks == 0:
        return True, format_message(f"All stacks removed")
    return False, format_message(f"Stacks: {old_stacks} → {self.stacks}")
```

## Using force_during Parameter

To control when an effect starts counting its duration:

```python
@app_commands.command(name="effect")
async def effect_command(
    interaction: Interaction,
    character: str,
    duration: int = 3,
    force_during: Optional[bool] = None,
):
    # Create effect
    effect = MyEffect(duration=duration)
    
    # Override timing if force_during is specified
    if force_during is not None:
        effect.is_during_own_turn = force_during
        
    # Apply effect
    message = await apply_effect(
        character=target_char,
        effect=effect,
        round_number=current_round,
        initiative_tracker=initiative_tracker
    )
```

## Troubleshooting

### Effect Expires Too Early

- Check if effect applied with "during own turn" = False
- Verify internal_duration is set correctly
- Use debug_mode=True to see duration calculations

### Effect Never Expires

- Check if permanent=True was set
- Verify turn processing is being called
- Ensure duration is not None

### Custom Logic Not Called

- Check if custom_logic is correctly passed to standard methods
- Verify method signatures match what's expected
- Test with print statements in custom logic

## Best Practices

1. **Use Standard Helpers**: Let base implementations handle duration and state
2. **Add Descriptive Messages**: Include details with formatted messages
3. **Handle Cleanup**: Reverse any stat changes in on_expire
4. **Test Both Timings**: Test both "during own turn" and "not during" scenarios
5. **Enable Debug Mode**: Use debug_mode=True during development

## Example Implementations

For examples of working effects:
- debug_effect.py: Simple diagnostic effect
- burn_effect.py: Standard DoT effect
- poison_effect.py: Stackable DoT effect
- template_effect.py: Starting point for new effects

## Parameter Reference

Common effect parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| name | Display name | "Effect" |
| duration | Turns effect lasts | 3 |
| permanent | Never expires by duration | False |
| category | Effect category | CUSTOM |
| process_timing | When effect processes | "both" |
| emoji | Icon for messages | "✨" |
| debug_mode | Enable verbose logging | False |