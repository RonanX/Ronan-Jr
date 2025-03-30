"""
Enhanced Burn Effect Test with Discord-like UI

Tests burn effect duration and timing with improved clarity.
Displays results in a Discord-style interface with embeds, while still outputting to console.
"""

import asyncio
import sys
import os
import logging
from tkinter import ttk, scrolledtext, font
import tkinter as tk
from typing import List, Callable
import threading
import re

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(message)s')
logger = logging.getLogger(__name__)

# Add the src directory to the python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import game components
from core.character import Character, Stats, Resources, DefenseStats, StatType
from core.state import GameState, CombatLogger
from core.effects.burn_effect import BurnEffect
from core.effects.manager import apply_effect, process_effects, register_effects

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class RedirectText:
    """Redirect stdout to both console and text widget with improved handling"""
    def __init__(self, ui):
        self.terminal = sys.stdout
        self.ui = ui
        self.buffer = ""
        self.seen_lines = set()  # Track lines we've already processed
        self.console_output = True  # Control console output

    def toggle_console(self, enabled=True):
        """Enable or disable console output"""
        self.console_output = enabled

    def write(self, string):
        # Always write to terminal for critical content
        if '\n' not in string and string.strip() in ['ERROR', 'EXCEPTION']:
            self.terminal.write(string)
            
        # Buffer until we get a full line
        self.buffer += string
        
        # Process complete lines
        if '\n' in self.buffer:
            lines = self.buffer.split('\n')
            self.buffer = lines.pop()  # Keep incomplete line in buffer
            
            for line in lines:
                self._process_line(line + '\n')
        
    def _process_line(self, line):
        """Process a single line with formatting and deduplication"""
        # Skip empty lines
        if not line.strip():
            return
            
        # Skip if we've processed this line before (deduplication)
        line_key = line.strip()
        if line_key in self.seen_lines:
            return
        
        self.seen_lines.add(line_key)
        
        # Color console output based on message type
        if "===== SCENARIO" in line:
            colored_line = f"{Colors.HEADER}{line}{Colors.ENDC}"
            if self.console_output:
                self.terminal.write(f"\r{colored_line}")
            self.ui.add_message(line, "header")
        elif "Expected:" in line:
            colored_line = f"{Colors.CYAN}{line}{Colors.ENDC}"
            if self.console_output:
                self.terminal.write(f"\r{colored_line}")
            self.ui.add_message(line, "subheader")
        elif "Round " in line and ":" in line:
            colored_line = f"{Colors.GREEN}{line}{Colors.ENDC}"
            if self.console_output:
                self.terminal.write(f"\r{colored_line}")
            self.ui.add_message(line, "round")
        elif "Apply message:" in line or "Start message:" in line or "End message:" in line:
            if "fire damage" in line:
                colored_line = f"{Colors.RED}{line}{Colors.ENDC}"
                if self.console_output:
                    self.terminal.write(f"\r{colored_line}")
                self.ui.add_message(line, "damage", is_embed=True)
            elif "worn off" in line:
                colored_line = f"{Colors.YELLOW}{line}{Colors.ENDC}"
                if self.console_output:
                    self.terminal.write(f"\r{colored_line}")
                self.ui.add_message(line, "expire", is_embed=True)
            else:
                colored_line = f"{Colors.GREEN}{line}{Colors.ENDC}"
                if self.console_output:
                    self.terminal.write(f"\r{colored_line}")
                self.ui.add_message(line, "effect", is_embed=True)
        elif "HP:" in line and "/" in line:
            colored_line = f"{Colors.GREEN}{line}{Colors.ENDC}"
            if self.console_output:
                self.terminal.write(f"\r{colored_line}")
            self.ui.add_message(line, "health")
        elif "Character Status:" in line:
            colored_line = f"{Colors.BLUE}{line}{Colors.ENDC}"
            if self.console_output:
                self.terminal.write(f"\r{colored_line}")
            self.ui.add_message(line, "character-status")
        elif "Active Effects:" in line:
            colored_line = f"{Colors.YELLOW}{line}{Colors.ENDC}"
            if self.console_output:
                self.terminal.write(f"\r{colored_line}")
            self.ui.add_message(line, "effects-header")
        elif line.strip().startswith("Effect "):
            if self.console_output:
                self.terminal.write(line)
            self.ui.add_message(line, "effect-detail")
        elif "Processing" in line:
            colored_line = f"{Colors.CYAN}{line}{Colors.ENDC}"
            if self.console_output:
                self.terminal.write(f"\r{colored_line}")
            self.ui.add_message(line, "processing")
        elif "DEBUG:" in line:
            # Skip debug messages in UI, but show in console
            if self.console_output:
                colored_line = f"{Colors.CYAN}{line}{Colors.ENDC}"
                self.terminal.write(f"\r{colored_line}")
        else:
            # Default formatting for console
            if self.console_output:
                self.terminal.write(line)
            self.ui.add_message(line, "normal")
            
    def flush(self):
        self.terminal.flush()


class DiscordLikeUI(tk.Tk):
    """Discord-like UI for test visualization"""
    def __init__(self):
        super().__init__()
        self.title("Burn Effect Test - Discord UI")
        self.geometry("800x700")
        self.configure(bg="#36393f")  # Discord dark theme
        
        # Create main frame
        self.main_frame = tk.Frame(self, bg="#36393f")
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create header with Discord-like channel bar
        self.header = tk.Frame(self.main_frame, bg="#2f3136", height=40)
        self.header.pack(fill=tk.X, pady=(0, 10))
        
        # Channel icon
        self.channel_icon = tk.Label(
            self.header, 
            text="#", 
            font=("Helvetica", 16, "bold"),
            fg="#72767d",
            bg="#2f3136",
            padx=5
        )
        self.channel_icon.pack(side=tk.LEFT)
        
        # Channel name
        self.title_label = tk.Label(
            self.header, 
            text="burn-effect-test", 
            font=("Helvetica", 14),
            fg="#ffffff",
            bg="#2f3136",
            padx=0,
            pady=5
        )
        self.title_label.pack(side=tk.LEFT)

        # Add console output toggle
        self.console_var = tk.BooleanVar(value=True)
        self.console_check = tk.Checkbutton(
            self.header,
            text="Console Output",
            variable=self.console_var,
            fg="#ffffff",
            bg="#2f3136",
            selectcolor="#36393f",
            command=self.toggle_console
        )
        self.console_check.pack(side=tk.RIGHT, padx=10)
        
        # Create chat canvas with scrollbar
        self.chat_canvas = tk.Canvas(
            self.main_frame,
            bg="#36393f",
            highlightthickness=0,
            borderwidth=0
        )
        self.scrollbar = ttk.Scrollbar(
            self.main_frame, 
            orient=tk.VERTICAL, 
            command=self.chat_canvas.yview
        )
        self.chat_canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Create a frame inside the canvas for messages
        self.chat_frame = tk.Frame(self.chat_canvas, bg="#36393f")
        self.chat_canvas.create_window((0, 0), window=self.chat_frame, anchor="nw", tags="self.chat_frame")
        
        # Configure the canvas to resize with the frame
        def on_configure(event):
            self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
            self.chat_canvas.itemconfig("self.chat_frame", width=event.width)
        
        self.chat_frame.bind("<Configure>", on_configure)
        self.chat_canvas.bind("<Configure>", lambda e: self.chat_canvas.itemconfig("self.chat_frame", width=e.width))
        
        # Create status bar
        self.status_bar = tk.Label(
            self.main_frame, 
            text="Test ready", 
            font=("Helvetica", 8),
            fg="#999999",
            bg="#36393f",
            anchor=tk.W
        )
        self.status_bar.pack(fill=tk.X, pady=(10, 0))
        
        # User bar at bottom (like Discord input area)
        self.user_bar = tk.Frame(self.main_frame, bg="#40444b", height=50, pady=10, padx=10)
        self.user_bar.pack(fill=tk.X, pady=(10, 0))
        
        # Start button styled like Discord button
        self.start_button = tk.Button(
            self.user_bar,
            text="Run All Tests",
            font=("Helvetica", 10),
            bg="#7289da",
            fg="#ffffff",
            padx=10,
            pady=5,
            relief=tk.FLAT,
            command=self.run_test
        )
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        # Scenario 1 button
        self.scenario1_button = tk.Button(
            self.user_bar,
            text="Scenario 1",
            font=("Helvetica", 10),
            bg="#4f545c",
            fg="#ffffff",
            padx=10,
            pady=5,
            relief=tk.FLAT,
            command=lambda: self.run_scenario(1)
        )
        self.scenario1_button.pack(side=tk.LEFT, padx=5)
        
        # Scenario 2 button
        self.scenario2_button = tk.Button(
            self.user_bar,
            text="Scenario 2",
            font=("Helvetica", 10),
            bg="#4f545c",
            fg="#ffffff",
            padx=10,
            pady=5,
            relief=tk.FLAT,
            command=lambda: self.run_scenario(2)
        )
        self.scenario2_button.pack(side=tk.LEFT, padx=5)
        
        # Clear button
        self.clear_button = tk.Button(
            self.user_bar,
            text="Clear",
            font=("Helvetica", 10),
            bg="#f04747",
            fg="#ffffff",
            padx=10,
            pady=5,
            relief=tk.FLAT,
            command=self.clear_chat
        )
        self.clear_button.pack(side=tk.RIGHT, padx=5)
        
        # Redirect stdout
        self.redirect = RedirectText(self)
        sys.stdout = self.redirect
        
        # Register effects at startup
        register_effects()
    
    def toggle_console(self):
        """Toggle console output on/off"""
        self.redirect.toggle_console(self.console_var.get())
        status = "enabled" if self.console_var.get() else "disabled"
        self.update_status(f"Console output {status}")
    
    def add_message(self, content, tag="normal", is_embed=False):
        """Add a formatted message to the chat frame"""
        # Strip ANSI color codes for display
        content = re.sub(r'\033\[[0-9;]+m', '', content)
        
        # Create and pack the message frame
        message_frame = MessageFrame(
            self.chat_frame, 
            content.strip(), 
            tag,
            is_embed=is_embed
        )
        message_frame.pack(fill=tk.X, padx=10, pady=2, anchor="w")
        
        # Force update to get correct sizing
        self.update_idletasks()
        
        # Scroll to bottom
        self.chat_canvas.yview_moveto(1.0)
    
    def update_status(self, text):
        """Update the status bar text"""
        self.status_bar.config(text=text)
        self.update_idletasks()
    
    def clear_chat(self):
        """Clear all messages from the chat"""
        for widget in self.chat_frame.winfo_children():
            widget.destroy()
        # Clear the seen lines set to avoid deduplication issues
        self.redirect.seen_lines.clear()
    
    def run_test(self):
        """Run the test in a separate thread"""
        self.start_button.config(state=tk.DISABLED)
        self.scenario1_button.config(state=tk.DISABLED)
        self.scenario2_button.config(state=tk.DISABLED)
        self.update_status("Test running...")
        
        # Clear chat
        self.clear_chat()
        
        # Run the test in a separate thread
        threading.Thread(target=self._run_test_async).start()
    
    def _run_test_async(self):
        """Run the async test in a way compatible with tkinter"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_burn_test())
        loop.close()
        
        # Update UI when done
        self.after(100, lambda: self.update_status("Test complete"))
        self.after(100, lambda: self.start_button.config(state=tk.NORMAL))
        self.after(100, lambda: self.scenario1_button.config(state=tk.NORMAL))
        self.after(100, lambda: self.scenario2_button.config(state=tk.NORMAL))
    
    def run_scenario(self, scenario_num):
        """Run a specific scenario"""
        self.start_button.config(state=tk.DISABLED)
        self.scenario1_button.config(state=tk.DISABLED)
        self.scenario2_button.config(state=tk.DISABLED)
        self.update_status(f"Running Scenario {scenario_num}...")
        
        # Clear chat
        self.clear_chat()
        
        # Run the test in a separate thread
        threading.Thread(target=lambda: self._run_scenario_async(scenario_num)).start()
    
    def _run_scenario_async(self, scenario_num):
        """Run a specific scenario async"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        if scenario_num == 1:
            loop.run_until_complete(run_scenario_1())
        else:
            loop.run_until_complete(run_scenario_2())
            
        loop.close()
        
        # Update UI when done
        self.after(100, lambda: self.update_status(f"Scenario {scenario_num} complete"))
        self.after(100, lambda: self.start_button.config(state=tk.NORMAL))
        self.after(100, lambda: self.scenario1_button.config(state=tk.NORMAL))
        self.after(100, lambda: self.scenario2_button.config(state=tk.NORMAL))

class MessageFrame(tk.Frame):
    """A frame that looks like a Discord message or embed"""
    def __init__(self, parent, message_content, tag="normal", is_embed=False, **kwargs):
        # Create frame with Discord-like styling
        if is_embed:
            # Embed style (colored left border)
            bg_color = "#36393f"
            bd_color = self._get_embed_color(tag)
            super().__init__(parent, bg=bg_color, highlightbackground=bd_color, 
                          highlightcolor=bd_color, highlightthickness=4, 
                          padx=5, pady=5, **kwargs)
        else:
            # Regular message style
            super().__init__(parent, bg="#36393f", padx=5, pady=5, **kwargs)
        
        # Add message content
        self.content = tk.Label(
            self, 
            text=message_content,
            justify=tk.LEFT,
            anchor="w",
            wraplength=650,
            bg="#36393f", 
            fg=self._get_text_color(tag),
            font=self._get_font(tag)
        )
        self.content.pack(fill=tk.X, expand=True, anchor="w")
    
    def _get_text_color(self, tag):
        """Get text color based on tag"""
        colors = {
            "header": "#7289da",
            "subheader": "#ffffff",
            "round": "#43b581",
            "effect": "#43b581",
            "damage": "#f04747",
            "expire": "#faa61a",
            "health": "#43b581",
            "character-status": "#7289da",
            "effects-header": "#faa61a",
            "effect-detail": "#99aab5",
            "processing": "#99aab5",
            "normal": "#ffffff"
        }
        return colors.get(tag, "#ffffff")
    
    def _get_font(self, tag):
        """Get font based on tag"""
        fonts = {
            "header": ("Helvetica", 12, "bold"),
            "subheader": ("Helvetica", 11, "italic"),
            "round": ("Helvetica", 11, "bold"),
            "effect": ("Helvetica", 10),
            "damage": ("Helvetica", 10),
            "expire": ("Helvetica", 10),
            "health": ("Helvetica", 10),
            "character-status": ("Helvetica", 11, "bold"),
            "effects-header": ("Helvetica", 10, "bold"),
            "effect-detail": ("Helvetica", 10),
            "processing": ("Helvetica", 10, "italic"),
            "normal": ("Helvetica", 10)
        }
        return fonts.get(tag, ("Helvetica", 10))
    
    def _get_embed_color(self, tag):
        """Get embed left border color based on tag"""
        colors = {
            "effect": "#43b581",  # Green
            "damage": "#f04747",  # Red
            "expire": "#faa61a",  # Yellow
            "normal": "#4f545c"   # Gray
        }
        return colors.get(tag, "#4f545c")

def print_character_status(character: Character, round_num: int):
    """Print character status in a clear format"""
    print(f"\n==== Character Status: {character.name} (Round {round_num}) ====")
    print(f"HP: {character.resources.current_hp}/{character.resources.max_hp}")
    
    # Show active effects
    print(f"Active Effects: {len(character.effects)}")
    for i, effect in enumerate(character.effects):
        effect_type = effect.__class__.__name__
        if hasattr(effect, 'timing'):
            print(f"  Effect {i+1}: {effect_type} '{effect.name}'")
            print(f"    Start Round: {effect.timing.start_round}")
            print(f"    Duration: {effect.duration}")
            print(f"    Application Round: {getattr(effect, '_application_round', 'N/A')}")
            print(f"    Application Turn: {getattr(effect, '_application_turn', 'N/A')}")
            print(f"    Will Expire Next: {getattr(effect, '_will_expire_next', False)}")
            print(f"    Marked for Expiry: {getattr(effect, '_marked_for_expiry', False)}")
            print(f"    Expiry Message Sent: {getattr(effect, '_expiry_message_sent', False)}")
        else:
            print(f"  Effect {i+1}: {effect_type} '{effect.name}' (No timing info)")

async def run_scenario_1():
    """Run just scenario 1: Effect applied DURING character's turn"""
    print("\n======== BURN EFFECT TIMING TEST ========\n")
    
    # Create test character
    char1 = Character(
        name="test",
        stats=Stats(
            base={stat: 10 for stat in StatType},
            modified={stat: 10 for stat in StatType}
        ),
        resources=Resources(
            current_hp=50,
            max_hp=50,
            current_mp=50,
            max_mp=50
        ),
        defense=DefenseStats(
            base_ac=10,
            current_ac=10
        )
    )
    
    print("\n===== SCENARIO 1: Effect applied DURING character's turn =====\n")
    print("Expected: Effect should last through the next turn and show a proper worn-off message")
    
    # Apply burn effect to char1 during round 1
    round_num = 1
    print(f"\nRound {round_num}: Applying burn effect to {char1.name} (duration=1)")
    burn_effect = BurnEffect("1", duration=1)
    apply_msg = await apply_effect(char1, burn_effect, round_num)
    print(f"Apply message: {apply_msg}")
    
    # Show character state
    print_character_status(char1, round_num)
    
    # Process end of turn for char1 (round 1)
    print(f"\nProcessing end of turn for {char1.name} (Round {round_num})")
    was_skipped, _, end_msgs = await process_effects(char1, round_num, char1.name)
    for msg in end_msgs:
        print(f"End message: {msg}")
    
    # Advance to round 2 (char1's turn again)
    round_num = 2
    print(f"\nRound {round_num}: {char1.name}'s turn")
    
    # Process start of turn for char1 (round 2)
    print(f"Processing start of turn for {char1.name}")
    was_skipped, start_msgs, _ = await process_effects(char1, round_num, char1.name)
    for msg in start_msgs:
        print(f"Start message: {msg}")
    
    # Check HP after processing
    print(f"{char1.name} HP: {char1.resources.current_hp}/{char1.resources.max_hp}")
    
    # Process end of turn for char1 (round 2)
    print(f"\nProcessing end of turn for {char1.name} (Round {round_num})")
    was_skipped, _, end_msgs = await process_effects(char1, round_num, char1.name)
    for msg in end_msgs:
        print(f"End message: {msg}")
    
    # Show character state after processing
    print_character_status(char1, round_num)
    
    # Advance to round 3 to verify cleanup
    round_num = 3
    print(f"\nAdvancing to Round {round_num} (verification)")
    
    # Process start of turn for char1 (round 3)
    print(f"Processing start of turn for {char1.name}")
    was_skipped, start_msgs, _ = await process_effects(char1, round_num, char1.name)
    for msg in start_msgs:
        print(f"Start message: {msg}")
    
    # Process end of turn for char1 (round 3)
    print(f"Processing end of turn for {char1.name}")
    was_skipped, _, end_msgs = await process_effects(char1, round_num, char1.name)
    for msg in end_msgs:
        print(f"End message: {msg}")
    
    # Check character state after processing
    print_character_status(char1, round_num)

async def run_scenario_2():
    """Run just scenario 2: Effect applied BEFORE character's turn"""
    print("\n======== BURN EFFECT TIMING TEST ========\n")
    
    # Create test character
    char2 = Character(
        name="test2",
        stats=Stats(
            base={stat: 10 for stat in StatType},
            modified={stat: 10 for stat in StatType}
        ),
        resources=Resources(
            current_hp=50,
            max_hp=50,
            current_mp=50,
            max_mp=50
        ),
        defense=DefenseStats(
            base_ac=10,
            current_ac=10
        )
    )
    
    print("\n===== SCENARIO 2: Effect applied BEFORE character's turn =====\n")
    print("Expected: Effect should last one turn and show a proper worn-off message")
    
    # Reset to round 1
    round_num = 1
    
    # Apply burn effect to char2 before their turn (during char1's turn)
    print(f"Round {round_num}: Applying burn effect to {char2.name} (duration=1)")
    burn_effect = BurnEffect("1", duration=1)
    apply_msg = await apply_effect(char2, burn_effect, round_num)
    print(f"Apply message: {apply_msg}")
    
    # Check HP before processing
    print(f"{char2.name} HP: {char2.resources.current_hp}/{char2.resources.max_hp}")
    
    # Show character state
    print_character_status(char2, round_num)
    
    # Process char2's turn (round 1)
    print(f"\nProcessing turn for {char2.name} (Round {round_num})")
    was_skipped, start_msgs, _ = await process_effects(char2, round_num, char2.name)
    for msg in start_msgs:
        print(f"Start message: {msg}")
    
    # Check HP after processing
    print(f"{char2.name} HP: {char2.resources.current_hp}/{char2.resources.max_hp}")
    
    # Process end of turn for char2 (round 1)
    was_skipped, _, end_msgs = await process_effects(char2, round_num, char2.name)
    for msg in end_msgs:
        print(f"End message: {msg}")
    
    # Show character state after processing
    print_character_status(char2, round_num)
    
    # Advance to round 2
    round_num = 2
    print(f"\nRound {round_num}: Processing turn for {char2.name}")
    
    # Process start of turn for char2 (round 2)
    was_skipped, start_msgs, _ = await process_effects(char2, round_num, char2.name)
    for msg in start_msgs:
        print(f"Start message: {msg}")
    
    # Process end of turn for char2 (round 2)
    was_skipped, _, end_msgs = await process_effects(char2, round_num, char2.name)
    for msg in end_msgs:
        print(f"End message: {msg}")
    
    # Check character state after processing
    print_character_status(char2, round_num)
    
    # Advance to round 3 to verify cleanup
    round_num = 3
    print(f"\nAdvancing to Round {round_num} (verification)")
    
    # Process start of turn for char2 (round 3)
    print(f"Processing start of turn for {char2.name}")
    was_skipped, start_msgs, _ = await process_effects(char2, round_num, char2.name)
    for msg in start_msgs:
        print(f"Start message: {msg}")
    
    # Process end of turn for char2 (round 3)
    print(f"Processing end of turn for {char2.name}")
    was_skipped, _, end_msgs = await process_effects(char2, round_num, char2.name)
    for msg in end_msgs:
        print(f"End message: {msg}")
    
    # Check character state after processing
    print_character_status(char2, round_num)

# Enhanced print function
def print_character_status(character: Character, round_num: int):
    """Print character status in a clear format with improved effect details"""
    print(f"\n==== Character Status: {character.name} (Round {round_num}) ====")
    print(f"HP: {character.resources.current_hp}/{character.resources.max_hp}")
    
    # Show active effects
    print(f"Active Effects: {len(character.effects)}")
    for i, effect in enumerate(character.effects):
        effect_type = effect.__class__.__name__
        if hasattr(effect, 'timing'):
            print(f"  Effect {i+1}: {effect_type} '{effect.name}'")
            print(f"    Start Round: {effect.timing.start_round}")
            print(f"    Duration: {effect.duration}")
            print(f"    Application Round: {getattr(effect, '_application_round', 'N/A')}")
            print(f"    Application Turn: {getattr(effect, '_application_turn', 'N/A')}")
            print(f"    Will Expire Next: {getattr(effect, '_will_expire_next', False)}")
            print(f"    Marked for Expiry: {getattr(effect, '_marked_for_expiry', False)}")
            print(f"    Expiry Message Sent: {getattr(effect, '_expiry_message_sent', False)}")
        else:
            print(f"  Effect {i+1}: {effect_type} '{effect.name}' (No timing info)")

    # Show effect feedback
    print(f"Effect Feedback: {len(character.effect_feedback)}")
    for i, feedback in enumerate(character.effect_feedback):
        print(f"  Feedback {i+1}: {feedback.effect_name}")
        print(f"    Message: {feedback.expiry_message}")
        print(f"    Expired on round: {feedback.round_expired}")
        print(f"    Displayed: {feedback.displayed}")
            
async def run_burn_test():
    """Run both burn effect timing test scenarios with improved output"""
    print("\n======== BURN EFFECT TIMING TEST ========\n")
    
    # Run scenario 1
    await run_scenario_1()
    
    # Run scenario 2
    await run_scenario_2()
    
    print("\n======== TEST COMPLETE ========")

if __name__ == "__main__":
    app = DiscordLikeUI()
    app.mainloop()