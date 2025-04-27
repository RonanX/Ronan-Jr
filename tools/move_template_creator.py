"""
Move Template Creator

A user-friendly interface for creating complex move templates with
advanced parameters. This tool guides you through all available
move options and generates a properly formatted JSON file.

Usage:
python move_template_creator.py
"""

import os
import json
import inquirer
from inquirer import errors
from typing import Dict, List, Optional, Any, Union

# Ensure the output directory exists
MOVESETS_DIR = os.path.join('assets', 'movesets')
os.makedirs(MOVESETS_DIR, exist_ok=True)

# Define constants for choices
ROLL_TIMING_OPTIONS = ["instant", "active", "per_turn"]
AOE_MODE_OPTIONS = ["single", "multi"]
CATEGORY_OPTIONS = ["Offense", "Defense", "Utility", "Support"]

def validate_name(answers, current):
    """Validate that the name isn't empty"""
    if not current.strip():
        raise errors.ValidationError('', reason="Name cannot be empty")
    return True

def validate_number(answers, current):
    """Validate that input is a valid number or empty"""
    if not current.strip():
        return True
    try:
        int(current)
        return True
    except ValueError:
        raise errors.ValidationError('', reason="Please enter a valid number or leave empty")

def validate_json(answers, current):
    """Validate that input is valid JSON or empty"""
    if not current.strip():
        return True
    try:
        json.loads(current)
        return True
    except json.JSONDecodeError:
        raise errors.ValidationError('', reason="Please enter valid JSON or leave empty")

def get_basic_info() -> Dict[str, Any]:
    """Get basic move information from user"""
    questions = [
        inquirer.Text('name',
            message="Enter move name",
            validate=validate_name),
        inquirer.Text('description',
            message="Enter move description (use semicolons to separate aspects)"),
        inquirer.List('category',
            message="Select move category",
            choices=CATEGORY_OPTIONS)
    ]
    
    answers = inquirer.prompt(questions)
    print(f"\n✓ Created move: {answers['name']} ({answers['category']})\n")
    return answers

def get_resource_costs() -> Dict[str, Any]:
    """Get resource costs for the move"""
    questions = [
        inquirer.Text('mp_cost',
            message="MP cost (negative for MP gain, empty for none)",
            default="0"),
        inquirer.Text('hp_cost',
            message="HP cost (negative for healing, empty for none)",
            default="0"),
        inquirer.Text('star_cost',
            message="Action star cost (empty for none)",
            default="1"),
        inquirer.Text('uses',
            message="Number of uses per combat (-1 for unlimited, empty for none)")
    ]
    
    answers = inquirer.prompt(questions)
    # Convert to integers for non-empty values
    result = {}
    for key, value in answers.items():
        if value.strip():
            result[key] = int(value)
    
    print("\n✓ Resource costs configured\n")
    return result

def get_timing_parameters() -> Dict[str, Any]:
    """Get timing parameters for the move"""
    questions = [
        inquirer.Text('cast_time',
            message="Cast time in turns (empty for none)",
            validate=validate_number),
        inquirer.Text('duration',
            message="Active duration in turns (empty for none)",
            validate=validate_number),
        inquirer.Text('cooldown',
            message="Cooldown in turns (empty for none)",
            validate=validate_number),
        inquirer.Text('cast_description',
            message="Custom cast text (empty for default)")
    ]
    
    answers = inquirer.prompt(questions)
    # Convert to integers where appropriate
    result = {}
    for key in ['cast_time', 'duration', 'cooldown']:
        if answers[key] and answers[key].strip():
            result[key] = int(answers[key])
    
    # Add cast_description if not empty
    if answers['cast_description'] and answers['cast_description'].strip():
        result['cast_description'] = answers['cast_description']
    
    print("\n✓ Timing parameters configured\n")
    return result

def get_combat_parameters() -> Dict[str, Any]:
    """Get combat parameters for the move"""
    # First, check if this is a combat move
    combat_move = inquirer.confirm("Is this a combat move with attack/damage?", default=True)
    
    if not combat_move:
        print("\n✓ Non-combat move configured\n")
        return {}
    
    questions = [
        inquirer.Text('attack_roll',
            message="Attack roll formula (e.g., 1d20+str, 1d20+dex advantage)"),
        inquirer.Text('damage',
            message="Damage formula (e.g., 2d6+str fire, 1d8 radiant)"),
        inquirer.Text('crit_range',
            message="Critical hit range (20 for standard, empty for default)",
            validate=validate_number),
        inquirer.List('roll_timing',
            message="When to process attack roll",
            choices=ROLL_TIMING_OPTIONS)
    ]
    
    answers = inquirer.prompt(questions)
    
    # Build result with only non-empty values
    result = {}
    for key, value in answers.items():
        if isinstance(value, str) and not value.strip():
            continue
        if key == 'crit_range' and value.strip():
            result[key] = int(value)
        else:
            result[key] = value
    
    # Ask about saving throws if damage is present
    if 'damage' in result:
        save_info = get_save_parameters()
        result.update(save_info)
    
    # Ask about AoE mode if attack_roll is present
    if 'attack_roll' in result:
        use_aoe = inquirer.confirm("Configure AoE mode for multiple targets?", default=False)
        if use_aoe:
            aoe_mode = inquirer.list_input(
                message="How to handle multiple targets",
                choices=AOE_MODE_OPTIONS)
            
            if aoe_mode != "single":  # Only include if not default
                result['aoe_mode'] = aoe_mode
    
    print("\n✓ Combat parameters configured\n")
    return result

def get_save_parameters() -> Dict[str, Any]:
    """Get saving throw parameters if applicable"""
    has_save = inquirer.confirm("Does this move require a saving throw?", default=False)
    
    if not has_save:
        return {}
    
    save_types = ["str", "dex", "con", "int", "wis", "cha"]
    
    questions = [
        inquirer.List('save_type',
            message="Select saving throw type",
            choices=save_types),
        inquirer.Text('save_dc',
            message="Save DC formula (e.g., 8+prof+int)"),
        inquirer.Confirm('half_on_save',
            message="Half damage on successful save?",
            default=False)
    ]
    
    answers = inquirer.prompt(questions)
    return answers

def get_bonus_on_hit() -> Optional[Dict[str, Any]]:
    """Get bonus on hit parameters if applicable"""
    has_bonus = inquirer.confirm("Does this move provide bonus on hit?", default=False)
    
    if not has_bonus:
        return None
    
    bonus_types = [
        "stars - Action stars gained on hit",
        "mp - MP gained on hit",
        "hp - HP gained on hit",
        "custom - Define a custom bonus"
    ]
    
    bonus_type = inquirer.list_input(
        message="Select bonus type",
        choices=bonus_types)
    
    bonus_type = bonus_type.split(' - ')[0]  # Get just the type
    
    bonus_value = inquirer.text(
        message=f"Enter {bonus_type} bonus amount",
        validate=validate_number)
    
    bonus = {bonus_type: int(bonus_value)}
    
    # Add custom note if desired
    has_note = inquirer.confirm("Add a custom note to display with the bonus?", default=False)
    if has_note:
        note = inquirer.text(message="Enter bonus note text")
        if note and note.strip():
            bonus["note"] = note
    
    return bonus

def get_conditions() -> Optional[List[str]]:
    """Get conditions to apply with the move"""
    has_conditions = inquirer.confirm("Does this move apply conditions?", default=False)
    
    if not has_conditions:
        return None
    
    available_conditions = [
        "prone", "grappled", "restrained", "airborne", "slowed",
        "blinded", "deafened", "marked", "guarded", "flanked",
        "incapacitated", "paralyzed", "charmed", "frightened", "confused",
        "hidden", "invisible", "underwater", "concentrating", "surprised",
        "bleeding", "poisoned", "silenced", "exhausted"
    ]
    
    questions = [
        inquirer.Checkbox('conditions',
            message="Select conditions to apply (space to select, enter to confirm)",
            choices=available_conditions)
    ]
    
    answers = inquirer.prompt(questions)
    return answers['conditions'] if answers['conditions'] else None

def get_roll_modifier() -> Optional[Dict[str, Any]]:
    """Get roll modifier parameters if applicable"""
    has_modifier = inquirer.confirm("Does this move apply a roll modifier?", default=False)
    
    if not has_modifier:
        return None
    
    modifier_types = ["bonus", "advantage", "disadvantage"]
    
    questions = [
        inquirer.List('type',
            message="Select modifier type",
            choices=modifier_types),
        inquirer.Text('value',
            message="Modifier value (for bonus type)",
            default="1",
            validate=validate_number),
        inquirer.Confirm('next_roll',
            message="Apply only to next roll?",
            default=False)
    ]
    
    answers = inquirer.prompt(questions)
    
    # Convert value to int
    answers['value'] = int(answers['value'])
    
    # If type is not bonus and value is 1, we can leave it out as it's the default
    if answers['type'] != "bonus" and answers['value'] == 1:
        answers.pop('value')
    
    return answers

def get_advanced_parameters() -> Dict[str, Any]:
    """Get all advanced parameters for the move"""
    advanced_params = {}
    
    # Bonus on hit
    bonus = get_bonus_on_hit()
    if bonus:
        advanced_params['bonus_on_hit'] = bonus
    
    # Conditions
    conditions = get_conditions()
    if conditions:
        advanced_params['conditions'] = conditions
    
    # Roll modifier
    roll_mod = get_roll_modifier()
    if roll_mod:
        advanced_params['roll_modifier'] = roll_mod
    
    # Allow custom JSON input for anything else
    custom_json = inquirer.confirm("Add additional custom parameters?", default=False)
    if custom_json:
        custom_text = inquirer.text(
            message="Enter custom parameters as JSON",
            validate=validate_json)
        
        if custom_text and custom_text.strip():
            try:
                custom_params = json.loads(custom_text)
                # Merge with existing params
                advanced_params.update(custom_params)
            except json.JSONDecodeError:
                print("Warning: Invalid JSON, custom parameters not added")
    
    return advanced_params

def create_move_template():
    """Create a complete move template by gathering all parameters"""
    print("\n=== MOVE TEMPLATE CREATOR ===\n")
    print("Let's create a new move template! Answer the following questions.\n")
    
    # Get all parameter groups
    basic_info = get_basic_info()
    resource_costs = get_resource_costs()
    timing_params = get_timing_parameters()
    combat_params = get_combat_parameters()
    advanced_params = get_advanced_parameters()
    
    # Combine all parameters
    move_data = {**basic_info, **resource_costs, **timing_params, **combat_params}
    
    # Add advanced parameters at top level or in advanced_params field
    if advanced_params:
        if inquirer.confirm("Store advanced parameters in 'advanced_params' field?", default=True):
            move_data['advanced_params'] = advanced_params
        else:
            # Merge directly with move_data
            move_data.update(advanced_params)
    
    # Add version
    move_data['version'] = 8  # Current version from code
    
    return move_data

def save_template(move_data: Dict[str, Any]):
    """Save the move template to a JSON file"""
    # Create filename from move name
    filename = move_data['name'].lower().replace(' ', '_') + '.json'
    filepath = os.path.join(MOVESETS_DIR, filename)
    
    # Create output structure - single move or moveset
    output_structure = inquirer.list_input(
        message="Output format",
        choices=["Single move", "Complete moveset"])
    
    if output_structure == "Complete moveset":
        # Create full moveset structure
        move_id = move_data['name'].lower().replace(' ', '_')
        output_data = {
            "version": 8,
            "moves": {
                move_id: move_data
            }
        }
    else:
        # Just the move itself
        output_data = move_data
    
    # Save to file
    with open(filepath, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n✅ Move template saved to: {filepath}")
    
    # Display the generated JSON for reference
    print("\nGenerated JSON:")
    print(json.dumps(output_data, indent=2))

def main():
    """Main function to run the move template creator"""
    try:
        move_data = create_move_template()
        
        # Preview the move
        print("\n=== MOVE PREVIEW ===\n")
        print(f"Name: {move_data['name']}")
        print(f"Description: {move_data['description']}")
        print(f"Category: {move_data['category']}")
        
        # Resource costs
        costs = []
        if move_data.get('mp_cost', 0) != 0:
            sign = '-' if move_data['mp_cost'] > 0 else '+'
            costs.append(f"MP: {sign}{abs(move_data['mp_cost'])}")
        if move_data.get('hp_cost', 0) != 0:
            sign = '-' if move_data['hp_cost'] > 0 else '+'
            costs.append(f"HP: {sign}{abs(move_data['hp_cost'])}")
        if move_data.get('star_cost', 0) > 0:
            costs.append(f"Stars: {move_data['star_cost']}")
        if costs:
            print(f"Cost: {', '.join(costs)}")
        
        # Timing
        timing = []
        if move_data.get('cast_time'):
            timing.append(f"Cast: {move_data['cast_time']}T")
        if move_data.get('duration'):
            timing.append(f"Duration: {move_data['duration']}T")
        if move_data.get('cooldown'):
            timing.append(f"Cooldown: {move_data['cooldown']}T")
        if timing:
            print(f"Timing: {', '.join(timing)}")
        
        # Combat
        if move_data.get('attack_roll'):
            print(f"Attack: {move_data['attack_roll']}")
        if move_data.get('damage'):
            print(f"Damage: {move_data['damage']}")
        
        # Save or continue
        if inquirer.confirm("Save this move template?", default=True):
            save_template(move_data)
            print("\nMove template creation complete!")
        else:
            print("\nTemplate creation cancelled.")
    
    except KeyboardInterrupt:
        print("\n\nTemplate creation cancelled.")
    except Exception as e:
        print(f"\nError creating template: {str(e)}")

if __name__ == "__main__":
    main()
