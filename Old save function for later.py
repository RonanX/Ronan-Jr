# Old save function

class ConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.value = None

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.send_message("Confirmed.", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.send_message("Cancelled.", ephemeral=True)
        
async def autosave_initiative():
    try:
        doc_ref = db.reference('initiative_saves').child('current_battle_autosave')
        save_data = {
            'initiative_order': initiative_order,
            'current_turn': current_turn,
            'round_number': round_number
        }
        doc_ref.set(save_data)
        logging.info("Initiative state autosaved successfully.")
    except db.FirebaseError as e:
        logging.error(f"Firebase error during autosave: {e}")
        raise AutosaveError("Failed to save to Firebase database")
    except Exception as e:
        logging.error(f"Unexpected error during autosave: {e}")
        raise AutosaveError("An unexpected error occurred during autosave")

class AutosaveError(Exception):
    pass

async def update_initiative_state(ctx):
    global initiative_order, current_turn, round_number
    try:
        # Update the state variables here
        await autosave_initiative()
        await ctx.send("Initiative state updated and autosaved.", ephemeral=True)
    except AutosaveError as e:
        error_message = f"Failed to autosave: {str(e)}"
        logging.error(error_message)
        await ctx.send(error_message, ephemeral=True)
        
# Autosave function
async def save_init_internal(name: str):
    doc_ref = db.collection('initiative_saves').document(name)
    doc_ref.set({
        'initiative_order': initiative_order,
        'current_turn': current_turn,
        'round_number': round_number
    })
    print(f"Initiative state saved as '{name}'.")  # Debug feedback

# Save current initiative
import datetime

@bot.tree.command(name="save_init", description="Saves the current initiative state.")
@app_commands.describe(name="Name of the save (optional)")
async def save_init(interaction: discord.Interaction, name: str = None):
    await interaction.response.defer(ephemeral=True)
    
    global initiative_order, current_turn, round_number

    if name is None:
        name = "quicksave"
    
    save_data = {
        'initiative_order': [
            {
                'name': char['name'],
                'roll': char['roll'],
                'faction': character_data[char['name']].get('faction', 'Neutral')
            } for char in initiative_order
        ],
        'current_turn': current_turn,
        'round_number': round_number,
        'timestamp': datetime.datetime.now().isoformat(),
        'description': f"Round {round_number}, {initiative_order[current_turn]['name']}'s turn"
    }

    doc_ref = db.reference('initiative_saves').child(name)
    existing_save = doc_ref.get()
    
    if existing_save and name != "quicksave":
        confirm_view = ConfirmView()
        await interaction.followup.send(f"A save named '{name}' already exists. Do you want to overwrite it?", view=confirm_view, ephemeral=True)
        await confirm_view.wait()
        if not confirm_view.value:
            await interaction.followup.send("Save cancelled.", ephemeral=True)
            return

    doc_ref.set(save_data)
    await interaction.followup.send(f"Initiative saved as '{name}'.", ephemeral=True)
    await interaction.channel.send(f"Initiative state saved as '{name}'.")

# Load an existing initiative
@bot.hybrid_command(name="load_init", description="Loads a saved initiative state.")
@app_commands.describe(name="Name of the initiative save to load (use 'autosave' for the latest autosave)")
async def load_init(ctx, name: str):
    global initiative_order, current_turn, round_number, autosave_enabled

    if initiative_order:
        confirm_view = ConfirmView()
        confirm_msg = await ctx.send("An initiative is already running. Do you want to overwrite it?", view=confirm_view)
        await confirm_view.wait()
        await confirm_msg.delete()
        if not confirm_view.value:
            await ctx.send("Load canceled.", ephemeral=True)
            return

    # Get saved data
    doc_ref = db.reference('initiative_saves').child('current_battle_autosave' if name.lower() == 'autosave' else name)
    saved_data = doc_ref.get()
    
    if not saved_data:
        await ctx.send(f"No saved initiative found with the name '{name}'.")
        return

    try:
        # Load initiative data
        initiative_order = [
            {
                'name': char['name'],
                'roll': char['roll']
            } for char in saved_data['initiative_order']
        ]
        current_turn = saved_data['current_turn']
        round_number = saved_data.get('round_number', 1) - 1  # Subtract 1 so next turn shows correct round

        # Verify characters exist
        missing_chars = [char['name'] for char in initiative_order if char['name'] not in character_data]
        if missing_chars:
            await ctx.send(f"Warning: The following characters need to be recreated: {', '.join(missing_chars)}")
            return

        # Create display embed
        embed = discord.Embed(
            title=f"Initiative '{name}' Loaded", 
            color=discord.Color.blue()
        )
        
        # Show initiative order
        init_lines = []
        for i, char in enumerate(initiative_order):
            line = f"{char['name']} (Initiative: {char['roll']})"
            if i == current_turn:
                line = f"__**{line}**__ (Current Turn)"
            init_lines.append(line)
        
        embed.description = f"**Round {round_number + 1}**\n\n" + "\n".join(init_lines)
        embed.set_footer(text="Type /next to continue the battle!")
        await ctx.send(embed=embed)

        # Ask about autosave
        save_view = ConfirmView()
        save_msg = await ctx.send("Would you like to enable autosave for this battle?", view=save_view)
        await save_view.wait()
        await save_msg.delete()
        
        if save_view.value:
            autosave_enabled = True
            await ctx.send("Autosave enabled for this loaded battle.", ephemeral=True)
        else:
            autosave_enabled = False
            await ctx.send("Autosave not enabled for this loaded battle.", ephemeral=True)

    except Exception as e:
        logging.error(f"Error loading initiative: {str(e)}")
        await ctx.send(f"Error loading initiative data: {str(e)}")

# Autosave global function
async def autosave_initiative():
    try:
        doc_ref = db.reference('initiative_saves').child('current_battle_autosave')
        save_data = {
            'initiative_order': [
                {
                    'name': char['name'],
                    'roll': char['roll'],
                    'faction': character_data[char['name']].get('faction', 'Neutral')
                } for char in initiative_order
            ],
            'current_turn': current_turn,
            'round_number': round_number
        }
        doc_ref.set(save_data)
        logging.info("Initiative state autosaved successfully.")
    except db.FirebaseError as e:
        logging.error(f"Firebase error during autosave: {e}")
        raise AutosaveError("Failed to save to Firebase database")
    except Exception as e:
        logging.error(f"Unexpected error during autosave: {e}")
        raise AutosaveError("An unexpected error occurred during autosave")