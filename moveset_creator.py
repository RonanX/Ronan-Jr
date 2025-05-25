"""
Moveset Creator GUI
A user-friendly interface for creating movesets for the Ronan Jr Discord bot.

Save this as: moveset_creator.py
Run with: python moveset_creator.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import json
import os
from typing import Dict, Any, Optional

class MovesetCreator:
    # Export directory path
    EXPORT_DIR = r"D:\Games\Campaigns\Ronan Jr\assets\moveset json's"
    
    def __init__(self, root):
        self.root = root
        self.root.title("Ronan Jr Moveset Creator")
        self.root.geometry("1200x800")
        
        # Current moveset data
        self.moveset = {
            "reference": "",
            "moves": {}
        }
        self.current_move_key = None
        
        # Setup UI
        self.setup_ui()
        self.setup_tooltips()
        
    def setup_ui(self):
        """Create the main UI layout"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        # Left panel - Move list
        left_frame = ttk.LabelFrame(main_frame, text="Moves", padding="10")
        left_frame.grid(row=0, column=0, rowspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        
        # Moveset reference
        ttk.Label(left_frame, text="Moveset Name:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        self.reference_var = tk.StringVar()
        self.reference_entry = ttk.Entry(left_frame, textvariable=self.reference_var, width=25)
        self.reference_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=(0, 5))
        
        # Move list
        self.move_listbox = tk.Listbox(left_frame, width=30, height=20)
        self.move_listbox.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        self.move_listbox.bind('<<ListboxSelect>>', self.on_move_select)
        
        # Move list scrollbar
        list_scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=self.move_listbox.yview)
        list_scrollbar.grid(row=1, column=2, sticky=(tk.N, tk.S))
        self.move_listbox.configure(yscrollcommand=list_scrollbar.set)
        
        # Move list buttons
        button_frame = ttk.Frame(left_frame)
        button_frame.grid(row=2, column=0, columnspan=2, pady=5)
        
        ttk.Button(button_frame, text="New Move", command=self.new_move).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Duplicate", command=self.duplicate_move).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Delete", command=self.delete_move).pack(side=tk.LEFT, padx=2)
        
        # Top panel - Move details
        top_frame = ttk.LabelFrame(main_frame, text="Move Details", padding="10")
        top_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 5))
        
        # Create notebook for organized tabs
        self.notebook = ttk.Notebook(top_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Tab 1: Basic Info
        basic_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(basic_frame, text="Basic Info")
        self.setup_basic_tab(basic_frame)
        
        # Tab 2: Combat
        combat_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(combat_frame, text="Combat")
        self.setup_combat_tab(combat_frame)
        
        # Tab 3: Timing
        timing_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(timing_frame, text="Timing")
        self.setup_timing_tab(timing_frame)
        
        # Tab 4: Advanced
        advanced_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(advanced_frame, text="Advanced")
        self.setup_advanced_tab(advanced_frame)
        
        # Bottom panel - JSON preview
        bottom_frame = ttk.LabelFrame(main_frame, text="JSON Preview", padding="10")
        bottom_frame.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.json_text = scrolledtext.ScrolledText(bottom_frame, width=60, height=15, wrap=tk.NONE)
        self.json_text.pack(fill=tk.BOTH, expand=True)
        
        # Bottom buttons
        bottom_buttons = ttk.Frame(main_frame)
        bottom_buttons.grid(row=2, column=0, columnspan=2, pady=10)
        
        ttk.Button(bottom_buttons, text="Save Move", command=self.save_current_move).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_buttons, text="Load Moveset", command=self.load_moveset).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_buttons, text="Save Moveset", command=self.save_moveset).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_buttons, text="Clear All", command=self.clear_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_buttons, text="Export to Assets", command=self.export_json).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_buttons, text="Copy JSON", command=self.copy_to_clipboard).pack(side=tk.LEFT, padx=5)
        
    def setup_basic_tab(self, parent):
        """Setup the basic info tab"""
        # Name (moved to row 0 since we removed move key)
        ttk.Label(parent, text="Name:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.name_var = tk.StringVar()
        self.name_var.trace_add("write", self.update_json_preview_wrapper)
        ttk.Entry(parent, textvariable=self.name_var, width=30).grid(row=0, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=2)
        
        # Description
        ttk.Label(parent, text="Description:").grid(row=1, column=0, sticky=(tk.W, tk.N), pady=2)
        self.desc_text = tk.Text(parent, width=40, height=4, wrap=tk.WORD)
        self.desc_text.grid(row=1, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=2)
        self.desc_text.bind("<KeyRelease>", self.update_json_preview_wrapper)
        ttk.Label(parent, text="Use semicolons (;) to separate bullet points", 
                 font=('TkDefaultFont', 8)).grid(row=2, column=1, columnspan=2, sticky=tk.W)
        
        # Category
        ttk.Label(parent, text="Category:").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.category_var = tk.StringVar(value="Offense")
        self.category_var.trace_add("write", self.update_json_preview_wrapper)
        category_combo = ttk.Combobox(parent, textvariable=self.category_var, 
                                     values=["Offense", "Defense", "Utility"], 
                                     state="readonly", width=15)
        category_combo.grid(row=3, column=1, sticky=tk.W, pady=2)
        
        # Resource costs
        ttk.Label(parent, text="Resource Costs:", font=('TkDefaultFont', 10, 'bold')).grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(10, 5))
        
        # MP Cost
        ttk.Label(parent, text="MP Cost:").grid(row=5, column=0, sticky=tk.W, pady=2)
        self.mp_cost_var = tk.IntVar(value=0)
        self.mp_cost_var.trace_add("write", self.update_json_preview_wrapper)
        ttk.Spinbox(parent, from_=-100, to=100, textvariable=self.mp_cost_var, width=10).grid(row=5, column=1, sticky=tk.W, pady=2)
        ttk.Label(parent, text="(negative values restore MP)").grid(row=5, column=2, sticky=tk.W, padx=5)
        
        # HP Cost
        ttk.Label(parent, text="HP Cost:").grid(row=6, column=0, sticky=tk.W, pady=2)
        self.hp_cost_var = tk.IntVar(value=0)
        self.hp_cost_var.trace_add("write", self.update_json_preview_wrapper)
        ttk.Spinbox(parent, from_=-100, to=100, textvariable=self.hp_cost_var, width=10).grid(row=6, column=1, sticky=tk.W, pady=2)
        ttk.Label(parent, text="(negative values heal HP)").grid(row=6, column=2, sticky=tk.W, padx=5)
        
        # Star Cost
        ttk.Label(parent, text="Star Cost:").grid(row=7, column=0, sticky=tk.W, pady=2)
        self.star_cost_var = tk.IntVar(value=1)
        self.star_cost_var.trace_add("write", self.update_json_preview_wrapper)
        ttk.Spinbox(parent, from_=0, to=5, textvariable=self.star_cost_var, width=10).grid(row=7, column=1, sticky=tk.W, pady=2)
        
    def setup_combat_tab(self, parent):
        """Setup the combat tab"""
        # Attack roll
        ttk.Label(parent, text="Attack Roll:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.attack_roll_var = tk.StringVar()
        self.attack_roll_var.trace_add("write", self.update_json_preview_wrapper)
        ttk.Entry(parent, textvariable=self.attack_roll_var, width=30).grid(row=0, column=1, sticky=(tk.W, tk.E), pady=2)
        ttk.Label(parent, text="e.g., 1d20+dex, 1d20+str advantage").grid(row=0, column=2, sticky=tk.W, padx=5)
        
        # Damage
        ttk.Label(parent, text="Damage:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.damage_var = tk.StringVar()
        self.damage_var.trace_add("write", self.update_json_preview_wrapper)
        ttk.Entry(parent, textvariable=self.damage_var, width=30).grid(row=1, column=1, sticky=(tk.W, tk.E), pady=2)
        ttk.Label(parent, text="e.g., 2d6+str fire, 1d4 poison").grid(row=1, column=2, sticky=tk.W, padx=5)
        
        # Crit range
        ttk.Label(parent, text="Crit Range:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.crit_range_var = tk.IntVar(value=20)
        self.crit_range_var.trace_add("write", self.update_json_preview_wrapper)
        ttk.Spinbox(parent, from_=1, to=20, textvariable=self.crit_range_var, width=10).grid(row=2, column=1, sticky=tk.W, pady=2)
        
        # Roll timing
        ttk.Label(parent, text="Roll Timing:").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.roll_timing_var = tk.StringVar(value="active")
        self.roll_timing_var.trace_add("write", self.update_json_preview_wrapper)
        self.timing_combo = ttk.Combobox(parent, textvariable=self.roll_timing_var,
                                   values=["instant", "active", "per_turn"],
                                   state="readonly", width=15)
        self.timing_combo.grid(row=3, column=1, sticky=tk.W, pady=2)
        ttk.Label(parent, text="Auto-set to instant if no cast time/duration").grid(row=3, column=2, sticky=tk.W, padx=5)
        
        # AOE Mode
        ttk.Label(parent, text="AOE Mode:").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.aoe_mode_var = tk.StringVar(value="single")
        self.aoe_mode_var.trace_add("write", self.update_json_preview_wrapper)
        aoe_combo = ttk.Combobox(parent, textvariable=self.aoe_mode_var,
                                values=["single", "multi"],
                                state="readonly", width=15)
        aoe_combo.grid(row=4, column=1, sticky=tk.W, pady=2)
        ttk.Label(parent, text="single = one roll for all, multi = roll per target").grid(row=4, column=2, sticky=tk.W, padx=5)
        
        # Conditions
        ttk.Label(parent, text="Conditions:").grid(row=5, column=0, sticky=(tk.W, tk.N), pady=2)
        
        conditions_frame = ttk.Frame(parent)
        conditions_frame.grid(row=5, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=2)
        
        self.condition_vars = {}
        conditions = ["prone", "stunned", "blinded", "restrained", "grappled", "poisoned", 
                     "charmed", "frightened", "paralyzed", "incapacitated"]
        
        for i, condition in enumerate(conditions):
            var = tk.BooleanVar()
            var.trace_add("write", self.update_json_preview_wrapper)
            self.condition_vars[condition] = var
            ttk.Checkbutton(conditions_frame, text=condition, variable=var).grid(
                row=i//3, column=i%3, sticky=tk.W, padx=5, pady=1
            )
        
    def setup_timing_tab(self, parent):
        """Setup the timing tab"""
        # Cast time
        ttk.Label(parent, text="Cast Time:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.cast_time_var = tk.IntVar(value=0)
        self.cast_time_var.trace_add("write", self.auto_update_roll_timing)
        ttk.Spinbox(parent, from_=0, to=10, textvariable=self.cast_time_var, width=10).grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(parent, text="turns (0 = instant cast)").grid(row=0, column=2, sticky=tk.W, padx=5)
        
        # Duration
        ttk.Label(parent, text="Duration:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.duration_var = tk.IntVar(value=0)
        self.duration_var.trace_add("write", self.auto_update_roll_timing)
        ttk.Spinbox(parent, from_=0, to=10, textvariable=self.duration_var, width=10).grid(row=1, column=1, sticky=tk.W, pady=2)
        ttk.Label(parent, text="turns (0 = instant effect)").grid(row=1, column=2, sticky=tk.W, padx=5)
        
        # Cooldown
        ttk.Label(parent, text="Cooldown:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.cooldown_var = tk.IntVar(value=0)
        self.cooldown_var.trace_add("write", self.update_json_preview_wrapper)
        ttk.Spinbox(parent, from_=0, to=10, textvariable=self.cooldown_var, width=10).grid(row=2, column=1, sticky=tk.W, pady=2)
        ttk.Label(parent, text="turns (0 = no cooldown)").grid(row=2, column=2, sticky=tk.W, padx=5)
        
        # Cast description
        ttk.Label(parent, text="Cast Description:").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.cast_desc_var = tk.StringVar()
        self.cast_desc_var.trace_add("write", self.update_json_preview_wrapper)
        ttk.Entry(parent, textvariable=self.cast_desc_var, width=40).grid(row=3, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=2)
        ttk.Label(parent, text="e.g., 'begins channeling', 'prepares'").grid(row=4, column=1, columnspan=2, sticky=tk.W)
        
        # Uses
        ttk.Label(parent, text="Limited Uses:").grid(row=5, column=0, sticky=tk.W, pady=2)
        self.uses_enabled_var = tk.BooleanVar(value=False)
        self.uses_enabled_var.trace_add("write", self.update_json_preview_wrapper)
        self.uses_check = ttk.Checkbutton(parent, text="Enable", variable=self.uses_enabled_var,
                                         command=self.toggle_uses)
        self.uses_check.grid(row=5, column=1, sticky=tk.W, pady=2)
        
        self.uses_var = tk.IntVar(value=1)
        self.uses_var.trace_add("write", self.update_json_preview_wrapper)
        self.uses_spin = ttk.Spinbox(parent, from_=1, to=10, textvariable=self.uses_var, width=10, state="disabled")
        self.uses_spin.grid(row=5, column=2, sticky=tk.W, pady=2)
        
    def setup_advanced_tab(self, parent):
        """Setup the advanced tab"""
        # Bonus on hit
        bonus_frame = ttk.LabelFrame(parent, text="Bonus on Hit", padding="5")
        bonus_frame.grid(row=0, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        self.bonus_enabled_var = tk.BooleanVar(value=False)
        self.bonus_enabled_var.trace_add("write", self.update_json_preview_wrapper)
        ttk.Checkbutton(bonus_frame, text="Enable Bonus on Hit", 
                       variable=self.bonus_enabled_var,
                       command=self.toggle_bonus).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=2)
        
        # Bonus fields
        ttk.Label(bonus_frame, text="Stars:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.bonus_stars_var = tk.IntVar(value=0)
        self.bonus_stars_var.trace_add("write", self.update_json_preview_wrapper)
        self.bonus_stars_spin = ttk.Spinbox(bonus_frame, from_=0, to=5, textvariable=self.bonus_stars_var, 
                                           width=10, state="disabled")
        self.bonus_stars_spin.grid(row=1, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(bonus_frame, text="MP:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.bonus_mp_var = tk.IntVar(value=0)
        self.bonus_mp_var.trace_add("write", self.update_json_preview_wrapper)
        self.bonus_mp_spin = ttk.Spinbox(bonus_frame, from_=-50, to=50, textvariable=self.bonus_mp_var,
                                        width=10, state="disabled")
        self.bonus_mp_spin.grid(row=2, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(bonus_frame, text="HP:").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.bonus_hp_var = tk.IntVar(value=0)
        self.bonus_hp_var.trace_add("write", self.update_json_preview_wrapper)
        self.bonus_hp_spin = ttk.Spinbox(bonus_frame, from_=-50, to=50, textvariable=self.bonus_hp_var,
                                        width=10, state="disabled")
        self.bonus_hp_spin.grid(row=3, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(bonus_frame, text="Note:").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.bonus_note_var = tk.StringVar()
        self.bonus_note_var.trace_add("write", self.update_json_preview_wrapper)
        self.bonus_note_entry = ttk.Entry(bonus_frame, textvariable=self.bonus_note_var, 
                                         width=30, state="disabled")
        self.bonus_note_entry.grid(row=4, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=2)
        
        # Roll modifier
        modifier_frame = ttk.LabelFrame(parent, text="Roll Modifier", padding="5")
        modifier_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        self.modifier_enabled_var = tk.BooleanVar(value=False)
        self.modifier_enabled_var.trace_add("write", self.update_json_preview_wrapper)
        ttk.Checkbutton(modifier_frame, text="Enable Roll Modifier",
                       variable=self.modifier_enabled_var,
                       command=self.toggle_modifier).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=2)
        
        ttk.Label(modifier_frame, text="Type:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.modifier_type_var = tk.StringVar(value="bonus")
        self.modifier_type_var.trace_add("write", self.update_json_preview_wrapper)
        self.modifier_type_combo = ttk.Combobox(modifier_frame, textvariable=self.modifier_type_var,
                                               values=["bonus", "advantage", "disadvantage"],
                                               state="disabled", width=15)
        self.modifier_type_combo.grid(row=1, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(modifier_frame, text="Value:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.modifier_value_var = tk.IntVar(value=2)
        self.modifier_value_var.trace_add("write", self.update_json_preview_wrapper)
        self.modifier_value_spin = ttk.Spinbox(modifier_frame, from_=-10, to=10, 
                                              textvariable=self.modifier_value_var,
                                              width=10, state="disabled")
        self.modifier_value_spin.grid(row=2, column=1, sticky=tk.W, pady=2)
        ttk.Label(modifier_frame, text="(for bonus type only)").grid(row=2, column=2, sticky=tk.W, padx=5)
        
        # NEW: Roll modifier target selection
        ttk.Label(modifier_frame, text="Target:").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.modifier_target_var = tk.StringVar(value="caster")
        self.modifier_target_var.trace_add("write", self.update_json_preview_wrapper)
        self.modifier_target_combo = ttk.Combobox(modifier_frame, textvariable=self.modifier_target_var,
                                                 values=["caster", "target", "both"],
                                                 state="disabled", width=15)
        self.modifier_target_combo.grid(row=3, column=1, sticky=tk.W, pady=2)
        ttk.Label(modifier_frame, text="Who gets the modifier").grid(row=3, column=2, sticky=tk.W, padx=5)
        
    def auto_update_roll_timing(self, *args):
        """Auto-update roll timing when cast time or duration changes"""
        cast_time = self.cast_time_var.get()
        duration = self.duration_var.get()
        
        # If both cast time and duration are 0, set to instant and disable combo
        if cast_time == 0 and duration == 0:
            self.roll_timing_var.set("instant")
            self.timing_combo.config(state="disabled")
        else:
            # Enable combo and set to active if it was instant
            self.timing_combo.config(state="readonly")
            if self.roll_timing_var.get() == "instant":
                self.roll_timing_var.set("active")
        
        # Also update the JSON preview
        self.update_json_preview()
        
    def update_json_preview_wrapper(self, *args):
        """Wrapper for update_json_preview to work with trace callbacks"""
        self.update_json_preview()
            
    def toggle_uses(self):
        """Toggle the uses spinbox based on checkbox"""
        if self.uses_enabled_var.get():
            self.uses_spin.config(state="normal")
        else:
            self.uses_spin.config(state="disabled")
            
    def toggle_bonus(self):
        """Toggle bonus on hit fields"""
        state = "normal" if self.bonus_enabled_var.get() else "disabled"
        self.bonus_stars_spin.config(state=state)
        self.bonus_mp_spin.config(state=state)
        self.bonus_hp_spin.config(state=state)
        self.bonus_note_entry.config(state=state)
        
    def toggle_modifier(self):
        """Toggle roll modifier fields"""
        state = "normal" if self.modifier_enabled_var.get() else "disabled"
        self.modifier_type_combo.config(state="readonly" if self.modifier_enabled_var.get() else "disabled")
        self.modifier_value_spin.config(state=state)
        self.modifier_target_combo.config(state="readonly" if self.modifier_enabled_var.get() else "disabled")
        
    def new_move(self):
        """Create a new move"""
        self.clear_move_fields()
        self.current_move_key = None
        self.update_json_preview()
        
    def duplicate_move(self):
        """Duplicate the selected move"""
        selection = self.move_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a move to duplicate.")
            return
            
        old_key = self.move_listbox.get(selection[0])
        new_key = f"{old_key}_copy"
        
        # Find unique key
        counter = 1
        while new_key in self.moveset["moves"]:
            new_key = f"{old_key}_copy{counter}"
            counter += 1
            
        # Copy move data
        self.moveset["moves"][new_key] = self.moveset["moves"][old_key].copy()
        self.moveset["moves"][new_key]["name"] = f"{self.moveset['moves'][new_key]['name']} (Copy)"
        
        self.update_move_list()
        self.select_move(new_key)
        
    def delete_move(self):
        """Delete the selected move"""
        selection = self.move_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a move to delete.")
            return
            
        move_key = self.move_listbox.get(selection[0])
        if messagebox.askyesno("Confirm Delete", f"Delete move '{move_key}'?"):
            del self.moveset["moves"][move_key]
            self.update_move_list()
            self.new_move()
            
    def on_move_select(self, event):
        """Handle move selection from list"""
        selection = self.move_listbox.curselection()
        if selection:
            move_key = self.move_listbox.get(selection[0])
            self.load_move(move_key)
            
    def load_move(self, move_key):
        """Load a move into the form"""
        if move_key not in self.moveset["moves"]:
            return
            
        self.current_move_key = move_key
        move = self.moveset["moves"][move_key]
        
        # Basic info
        self.name_var.set(move.get("name", ""))
        self.desc_text.delete(1.0, tk.END)
        self.desc_text.insert(1.0, move.get("description", ""))
        self.category_var.set(move.get("category", "Offense"))
        
        # Resource costs
        self.mp_cost_var.set(move.get("mp_cost", 0))
        self.hp_cost_var.set(move.get("hp_cost", 0))
        self.star_cost_var.set(move.get("star_cost", 1))
        
        # Combat
        self.attack_roll_var.set(move.get("attack_roll", ""))
        self.damage_var.set(move.get("damage", ""))
        self.crit_range_var.set(move.get("crit_range", 20))
        self.roll_timing_var.set(move.get("roll_timing", "active"))
        self.aoe_mode_var.set(move.get("aoe_mode", "single"))
        
        # Conditions
        conditions = move.get("conditions", [])
        for condition, var in self.condition_vars.items():
            var.set(condition in conditions)
            
        # Timing
        self.cast_time_var.set(move.get("cast_time", 0))
        self.duration_var.set(move.get("duration", 0))
        self.cooldown_var.set(move.get("cooldown", 0))
        self.cast_desc_var.set(move.get("cast_description", ""))
        
        # Check if timing should be auto-updated
        self.auto_update_roll_timing()
        
        # Uses
        if "uses" in move and move["uses"] is not None:
            self.uses_enabled_var.set(True)
            self.uses_var.set(move["uses"])
            self.uses_spin.config(state="normal")
        else:
            self.uses_enabled_var.set(False)
            self.uses_spin.config(state="disabled")
            
        # Bonus on hit
        bonus = move.get("bonus_on_hit", {})
        if bonus:
            self.bonus_enabled_var.set(True)
            self.bonus_stars_var.set(bonus.get("stars", 0))
            self.bonus_mp_var.set(bonus.get("mp", 0))
            self.bonus_hp_var.set(bonus.get("hp", 0))
            self.bonus_note_var.set(bonus.get("note", ""))
            self.toggle_bonus()
        else:
            self.bonus_enabled_var.set(False)
            self.toggle_bonus()
            
        # Roll modifier
        modifier = move.get("roll_modifier", {})
        if modifier:
            self.modifier_enabled_var.set(True)
            self.modifier_type_var.set(modifier.get("type", "bonus"))
            self.modifier_value_var.set(modifier.get("value", 2))
            self.modifier_target_var.set(modifier.get("target", "caster"))
            self.toggle_modifier()
        else:
            self.modifier_enabled_var.set(False)
            self.toggle_modifier()
            
        self.update_json_preview()
        
    def save_current_move(self):
        """Save the current move to the moveset"""
        move_name = self.name_var.get().strip()
        if not move_name:
            messagebox.showerror("Error", "Move name is required!")
            return
            
        # Use move name as key (replace spaces with underscores and make lowercase)
        move_key = move_name.lower().replace(" ", "_")
        
        # Build move data
        move_data = {
            "name": move_name,
            "description": self.desc_text.get(1.0, tk.END).strip(),
            "mp_cost": self.mp_cost_var.get(),
            "hp_cost": self.hp_cost_var.get(),
            "star_cost": self.star_cost_var.get(),
            "category": self.category_var.get(),
            "version": 10  # Updated to version 10
        }
        
        # Add optional fields only if they have values
        if self.attack_roll_var.get().strip():
            move_data["attack_roll"] = self.attack_roll_var.get().strip()
            
        if self.damage_var.get().strip():
            move_data["damage"] = self.damage_var.get().strip()
            
        if self.crit_range_var.get() != 20:
            move_data["crit_range"] = self.crit_range_var.get()
            
        if self.cast_time_var.get() > 0:
            move_data["cast_time"] = self.cast_time_var.get()
            
        if self.duration_var.get() > 0:
            move_data["duration"] = self.duration_var.get()
            
        if self.cooldown_var.get() > 0:
            move_data["cooldown"] = self.cooldown_var.get()
            
        if self.cast_desc_var.get().strip():
            move_data["cast_description"] = self.cast_desc_var.get().strip()
            
        # Roll timing (always include, but check for auto-set instant)
        move_data["roll_timing"] = self.roll_timing_var.get()
            
        # AOE mode
        if self.aoe_mode_var.get() != "single":
            move_data["aoe_mode"] = self.aoe_mode_var.get()
            
        # Conditions
        conditions = [cond for cond, var in self.condition_vars.items() if var.get()]
        if conditions:
            move_data["conditions"] = conditions
            
        # Uses
        if self.uses_enabled_var.get():
            move_data["uses"] = self.uses_var.get()
            
        # Bonus on hit
        if self.bonus_enabled_var.get():
            bonus = {}
            if self.bonus_stars_var.get() != 0:
                bonus["stars"] = self.bonus_stars_var.get()
            if self.bonus_mp_var.get() != 0:
                bonus["mp"] = self.bonus_mp_var.get()
            if self.bonus_hp_var.get() != 0:
                bonus["hp"] = self.bonus_hp_var.get()
            if self.bonus_note_var.get().strip():
                bonus["note"] = self.bonus_note_var.get().strip()
            if bonus:
                move_data["bonus_on_hit"] = bonus
                
        # Roll modifier
        if self.modifier_enabled_var.get():
            modifier = {
                "type": self.modifier_type_var.get(),
                "target": self.modifier_target_var.get()
            }
            if self.modifier_type_var.get() == "bonus":
                modifier["value"] = self.modifier_value_var.get()
            move_data["roll_modifier"] = modifier
        
        # Update moveset
        self.moveset["moves"][move_key] = move_data
        self.current_move_key = move_key
        
        # Update display
        self.update_move_list()
        self.select_move(move_key)
        self.update_json_preview()
        
        messagebox.showinfo("Success", f"Move '{move_name}' saved!")
        
    def clear_move_fields(self):
        """Clear all move input fields"""
        self.name_var.set("")
        self.desc_text.delete(1.0, tk.END)
        self.category_var.set("Offense")
        
        self.mp_cost_var.set(0)
        self.hp_cost_var.set(0)
        self.star_cost_var.set(1)
        
        self.attack_roll_var.set("")
        self.damage_var.set("")
        self.crit_range_var.set(20)
        self.roll_timing_var.set("active")
        self.aoe_mode_var.set("single")
        
        for var in self.condition_vars.values():
            var.set(False)
            
        self.cast_time_var.set(0)
        self.duration_var.set(0)
        self.cooldown_var.set(0)
        self.cast_desc_var.set("")
        
        self.uses_enabled_var.set(False)
        self.uses_spin.config(state="disabled")
        
        self.bonus_enabled_var.set(False)
        self.toggle_bonus()
        
        self.modifier_enabled_var.set(False)
        self.toggle_modifier()
        
        # Re-enable timing combo
        self.timing_combo.config(state="readonly")
        
    def update_move_list(self):
        """Update the move listbox"""
        self.move_listbox.delete(0, tk.END)
        for move_key in sorted(self.moveset["moves"].keys()):
            self.move_listbox.insert(tk.END, move_key)
            
    def select_move(self, move_key):
        """Select a move in the listbox"""
        items = self.move_listbox.get(0, tk.END)
        if move_key in items:
            index = items.index(move_key)
            self.move_listbox.selection_clear(0, tk.END)
            self.move_listbox.selection_set(index)
            self.move_listbox.see(index)
            
    def update_json_preview(self):
        """Update the JSON preview"""
        # Update reference
        self.moveset["reference"] = self.reference_var.get() or "unnamed_moveset"
        
        # Clear and update preview
        self.json_text.delete(1.0, tk.END)
        json_str = json.dumps(self.moveset, indent=2)
        self.json_text.insert(1.0, json_str)
        
    def load_moveset(self):
        """Load a moveset from file"""
        filename = filedialog.askopenfilename(
            title="Load Moveset",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if not filename:
            return
            
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
                
            # Validate structure
            if "moves" not in data:
                messagebox.showerror("Error", "Invalid moveset format: missing 'moves' key")
                return
                
            self.moveset = data
            self.reference_var.set(data.get("reference", ""))
            
            self.update_move_list()
            self.new_move()
            self.update_json_preview()
            
            messagebox.showinfo("Success", f"Loaded {len(self.moveset['moves'])} moves!")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load moveset: {str(e)}")
            
    def save_moveset(self):
        """Save the moveset to file"""
        if not self.moveset["moves"]:
            messagebox.showwarning("Warning", "No moves to save!")
            return
            
        filename = filedialog.asksaveasfilename(
            title="Save Moveset",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if not filename:
            return
            
        try:
            # Update reference
            self.moveset["reference"] = self.reference_var.get() or "unnamed_moveset"
            
            with open(filename, 'w') as f:
                json.dump(self.moveset, f, indent=2)
                
            messagebox.showinfo("Success", f"Saved {len(self.moveset['moves'])} moves to {os.path.basename(filename)}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save moveset: {str(e)}")
            
    def export_json(self):
        """Export the JSON to the movesets directory"""
        # Update reference
        self.moveset["reference"] = self.reference_var.get() or "unnamed_moveset"
        
        # Set the export directory
        export_dir = self.EXPORT_DIR
        
        # Create directory if it doesn't exist
        try:
            os.makedirs(export_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create directory: {str(e)}")
            return
        
        # Generate filename based on moveset reference
        base_filename = self.reference_var.get() or "unnamed_moveset"
        base_filename = base_filename.replace(" ", "_").lower()
        filename = os.path.join(export_dir, f"{base_filename}.json")
        
        # Check if file exists and ask for overwrite confirmation
        if os.path.exists(filename):
            if not messagebox.askyesno("File Exists", 
                                     f"'{base_filename}.json' already exists. Overwrite?"):
                # If user doesn't want to overwrite, generate a unique filename
                counter = 1
                while os.path.exists(os.path.join(export_dir, f"{base_filename}_{counter}.json")):
                    counter += 1
                filename = os.path.join(export_dir, f"{base_filename}_{counter}.json")
        
        try:
            with open(filename, 'w') as f:
                json.dump(self.moveset, f, indent=2)
                
            messagebox.showinfo("Exported", 
                              f"Moveset exported to:\n{os.path.basename(filename)}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export moveset: {str(e)}")
            
    def copy_to_clipboard(self):
        """Copy the JSON to clipboard"""
        # Update reference
        self.moveset["reference"] = self.reference_var.get() or "unnamed_moveset"
        
        json_str = json.dumps(self.moveset, indent=2)
        
        self.root.clipboard_clear()
        self.root.clipboard_append(json_str)
        
        messagebox.showinfo("Copied", "JSON copied to clipboard!")
        
    def clear_all(self):
        """Clear all data"""
        if self.moveset["moves"] and not messagebox.askyesno("Confirm Clear", "Clear all moves?"):
            return
            
        self.moveset = {"reference": "", "moves": {}}
        self.reference_var.set("")
        self.update_move_list()
        self.new_move()
        self.update_json_preview()
        
    def setup_tooltips(self):
        """Setup helpful tooltips"""
        # This would require additional tooltip library
        # For now, we have inline help text
        pass

def main():
    root = tk.Tk()
    app = MovesetCreator(root)
    root.mainloop()

if __name__ == "__main__":
    main()