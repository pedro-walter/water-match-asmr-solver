# Save State Feature

## Quick Save During Solving

When you see the prompt:
```
Press Enter to continue (or 's' to save)...
```

You can:
- **Press Enter**: Continue to the next move
- **Type 's' and press Enter**: Save the current game state to a file

## Saved File Naming

Files are automatically named with an incrementing counter:
- First save: `puzzle_name_state1.json`
- Second save: `puzzle_name_state2.json`
- Third save: `puzzle_name_state3.json`
- And so on...

This prevents overwriting previous saves.

## When Can You Save?

The save option is available at:
1. **Initial state** - Before starting the solver
2. **After each move** - During step-by-step visualization (interactive mode)
3. **During partial solution playback** - When viewing the best partial path

## Example Usage

```bash
# Start the solver in interactive mode
python3 main.py example_columns.json

# You'll see:
# Move #1: Bottle 6 → Bottle 9
# Press Enter to continue (or 's' to save)...

# Type 's' and press Enter:
s
# ✓ Saved current state to: example_columns_state1.json

# Continue solving, save again when needed:
s
# ✓ Saved current state to: example_columns_state2.json
```

## Saved State Files

Saved states are complete puzzle files that can be:
- Loaded and solved later: `python3 main.py example_columns_state1.json`
- Inspected manually
- Used for debugging
- Shared with others

## Other Save Methods

### 1. Save Best Partial Solution (Automatic)
When solver times out or finds no solution:
```
Would you like to save this state to a file for debugging? (y/n): y
Saved debug state to: example_columns_debug.json
```

### 2. Save Best State (Command Line)
```bash
python3 save_best_state.py example_columns.json output.json 10000
```

### 3. Programmatic Save
In your own scripts:
```python
from play_area import PlayArea

play_area = PlayArea.load_from_json('puzzle.json')
# ... make some moves ...
play_area.save_to_json('saved_state.json')
```

## Tips

- Save before complex moves to create restore points
- Save when you notice interesting patterns
- Save after unlocking bottles to debug lock conditions
- Save before unknown colors are revealed
- Use saved states to test different solving strategies
