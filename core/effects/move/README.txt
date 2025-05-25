# Move Effect System Documentation

## Overview
The Move Effect System is a comprehensive framework for handling combat moves in the Ronan Jr Discord bot. It manages move phases (casting, active, cooldown), resource costs, combat rolls, and various effects.

## Moveset JSON Format

### Basic Structure
```json
{
  "reference": "moveset_name",
  "moves": {
    "move_key": {
      "name": "Move Name",
      "description": "Move description; Can use semicolons; For bullet points",
      "version": 9,
      // ... other parameters
    }
  }
}
```

### Move Parameters

#### Basic Parameters (Required)
- **name** (string): The display name of the move
- **description** (string): Move description. Use semicolons (`;`) to separate bullet points
- **version** (int): Move data version (current: 9)

#### Resource Costs
- **mp_cost** (int): Mana points cost (negative values restore MP)
- **hp_cost** (int): Hit points cost (negative values heal HP)
- **star_cost** (int): Action stars cost (0-5 stars)

#### Timing Parameters
- **cast_time** (int): Turns required to cast before activation
- **duration** (int): Turns the effect lasts after activation
- **cooldown** (int): Turns before the move can be used again
- **cast_description** (string): Custom casting message

#### Combat Parameters
- **attack_roll** (string): Attack roll formula (e.g., "1d20+dex", "1d20+str advantage")
- **damage** (string): Damage formula (e.g., "2d6+str fire", "1d4 poison")
- **crit_range** (int): Natural roll needed for critical hit (default: 20)
- **targets** (int): Number of targets for multi-target moves
- **aoe_mode** (string): "single" (one roll for all) or "multi" (roll per target)

#### Effect Parameters
- **conditions** (list): Conditions applied on hit (e.g., ["prone", "stunned"])
- **roll_timing** (string): When to roll - "instant", "active", or "per_turn"
- **category** (string): Move category - "Offense", "Defense", or "Utility"

#### Advanced Parameters
- **uses** (int): Limited uses per combat (null for unlimited)
- **bonus_on_hit** (dict): Bonuses applied on hit:
  ```json
  {
    "stars": 1,     // Action stars gained
    "mp": 5,        // MP gained/lost
    "hp": -10,      // HP gained/lost (negative heals)
    "note": "text"  // Custom note
  }
  ```
- **roll_modifier** (dict): Roll modifiers to apply:
  ```json
  {
    "type": "bonus",      // "bonus", "advantage", or "disadvantage"
    "value": 2,           // For bonus type
    "duration": 3         // How long it lasts
  }
  ```

#### Save Parameters (Future Implementation)
- **save_type** (string): Save type (str, dex, con, int, wis, cha)
- **save_dc** (string): DC formula (e.g., "8+prof+int")
- **half_on_save** (bool): Whether to deal half damage on successful save

### Example Moves

#### Basic Attack
```json
{
  "name": "Quick Strike",
  "description": "A swift attack; Deals light damage; Can start combos",
  "mp_cost": 0,
  "hp_cost": 0,
  "star_cost": 1,
  "attack_roll": "1d20+dex",
  "damage": "1d6+dex slashing",
  "category": "Offense",
  "version": 9
}
```

#### Spell with Cast Time
```json
{
  "name": "Fireball",
  "description": "Channels fire magic; Creates an explosive blast; Burns the area",
  "mp_cost": 15,
  "star_cost": 2,
  "cast_time": 2,
  "duration": 0,
  "cooldown": 3,
  "attack_roll": "1d20+int",
  "damage": "3d6 fire",
  "aoe_mode": "single",
  "category": "Offense",
  "version": 9
}
```

#### Buff/Healing Move
```json
{
  "name": "Healing Light",
  "description": "Bathes allies in healing light; Restores health; Removes minor ailments",
  "mp_cost": 10,
  "hp_cost": -20,
  "star_cost": 2,
  "duration": 2,
  "category": "Defense",
  "version": 9
}
```

#### Move with Bonuses
```json
{
  "name": "Energy Drain",
  "description": "Drains life force; Steals energy; Weakens the target",
  "mp_cost": 8,
  "star_cost": 2,
  "attack_roll": "1d20+int",
  "damage": "2d4 necrotic",
  "bonus_on_hit": {
    "mp": 5,
    "hp": -5,
    "note": "Life Steal"
  },
  "category": "Offense",
  "version": 9
}
```

## Move Effect Phases

### 1. **Instant Phase**
- No cast time, duration, or cooldown
- Executes immediately and completes
- Good for quick attacks or instant effects

### 2. **Casting Phase**
- Occurs when `cast_time > 0`
- Character prepares the move
- Can be interrupted
- Transitions to Active phase when complete

### 3. **Active Phase**
- Main effect duration
- Attack rolls happen based on `roll_timing`
- Displays remaining turns
- Transitions to Cooldown or expires

### 4. **Cooldown Phase**
- Recovery period after move use
- Move cannot be used during cooldown
- Only displays in end-of-turn updates

## Roll Timing Options

- **instant**: Rolls immediately when move is used
- **active**: Rolls once when entering active phase
- **per_turn**: Rolls every turn during active phase

## Category Guidelines

- **Offense**: Attacks, damage, debuffs
- **Defense**: Healing, shields, buffs, protection
- **Utility**: Movement, resource management, non-combat

## Star Cost Guidelines

| Cost | Move Type |
|------|-----------|
| 1⭐ | Light attacks, minor utility |
| 2⭐ | Standard attacks, most effects |
| 3⭐ | Powerful attacks, major effects |
| 4-5⭐ | Ultimate moves, game-changers |

## Best Practices

1. **Descriptions**: Keep focused on flavor, not mechanics
2. **Star Costs**: Balance based on power level
3. **Cooldowns**: Generally for 3+ star moves only
4. **Resource Costs**: MP for most moves, HP for risky moves
5. **Duration**: Consider combat length (usually 3-5 rounds)
6. **Uses**: Alternative to MP cost for limited abilities

## Custom Parameters

The `custom_parameters` field stores any unrecognized data for forward compatibility. This allows older versions to load newer movesets without losing data.

## Version History

- **v1-8**: Various incremental updates
- **v9**: Added roll_modifier support, reorganized parameters