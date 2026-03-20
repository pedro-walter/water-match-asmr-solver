---
name: Project Overview
description: Water Sort Puzzle Solver - interactive game solver with A* search and puzzle editor
type: project
---

# Water Sort Puzzle Solver

An interactive Python puzzle solver using A* search to find optimal solutions for water sort games. No external dependencies beyond Python 3.6+.

## What It Is

Water sort puzzles involve moving colored water between bottles to sort them. Each bottle holds 4 units of liquid. The goal is to complete each bottle (4 matching colors, no unknowns).

## Key Features

- **Interactive Solver**: Pause/resume solving, manually reveal unknown colors, save states
- **Puzzle Editor**: Build puzzles from scratch or edit existing ones with commands
- **Two Layout Modes**: Row layout (horizontal) and column layout (with per-bottle gaps for visual alignment)
- **Cursor Edit Mode**: `cedit` command with arrow keys to move between bottles/slots
- **Lock Mechanics**: Bottles can be locked until conditions are met (e.g., "unlock after 2 RED bottles complete")
- **JSON Persistence**: Save/load puzzles with support for multiple formats

## Running

```bash
# Solver mode
python3 main.py puzzle.json              # Interactive (press Enter between moves)
python3 main.py puzzle.json --auto       # Auto mode with default 0.5s delay
python3 main.py puzzle.json --auto --delay 1.0

# Editor mode
python3 main.py                          # Start blank editor
python3 main.py puzzle.json --edit       # Edit existing puzzle
python3 main.py puzzle.json              # Solve, then can press 'e' to edit
```

## Core Architecture

### Models (`models.py`)
- **Color**: Enum with 8 colors + UNKNOWN (RED, PURPLE, GREY, GREEN, YELLOW, ORANGE, BLUE, CYAN)
- **Bottle**: Container with up to 4 units, methods for transfer/completion checking
- **LockCondition**: Defines when a locked bottle unlocks (count + optional color)

### Game State (`play_area.py`)
- **PlayArea**: Central state manager
  - Holds bottles list, lock conditions, completed tracking
  - Loads/saves to JSON via `load_from_json()` / `save_to_json()`
  - Two layout modes: `row_layout` and `column_layout` (dicts with metadata)
  - Mutable (for editor), but cloned for solver to preserve original

### Solver (`solver.py`)
- **GameState**: Immutable, hashable state for A* search (tuple-based)
- **Solver**: A* implementation with adaptive heuristic
  - If unknowns exist: prioritizes revealing unknowns (puzzle unsolvable until revealed)
  - No unknowns: uses misplaced colors heuristic + empty bottle penalty
  - Returns move sequence as list of `(from_bottle_idx, to_bottle_idx)` tuples

### Interactive Loop (`game_loop.py`)
- **run_solver()**: Main entry point
  - Loads puzzle, clones original for file saving
  - Pauses solver when unknown is revealed
  - Prompts user for revealed color
  - Updates BOTH current state and original copy
  - Never saves current game state to original file (only revealed unknowns)
  - Offers to restore and retry if no solution found

### Editor (`editor.py`)
- **run_editor()**: Interactive command loop with text input
- **_cursor_edit()**: Keypress-based mode for slot-level editing (arrows + mnemonics)
- **_handle_*** functions: Command dispatch for operations like add, del, move, gap, etc.

### UI (`ui.py`)
- **ConsoleUI**: Terminal rendering with ANSI colors
  - `_render_columns()`: Vertical layout with gaps and skew
  - `_render_rows()`: Horizontal rows layout
  - `_render_bottles_row()`: Flat single-line layout
  - Cursor support: `cursor_bottle` and `cursor_slot` parameters

### Utilities (`utils.py`)
- **parse_bottle_contents()**: Converts string mnemonics (RPAGYOUC) to Color enums
- **load_json_puzzle()**: Loads and normalizes JSON (standard or column format)
- **convert_columns_to_bottles()**: Converts column layout to standard bottles array

## JSON Puzzle Format

### Standard Format
```json
{
  "bottles": [
    {"number": 0, "contents": ["RED", "BLUE", "RED"], "lock_condition": {"count": 1, "color": "ANY"}},
    {"number": 1, "contents": []}
  ]
}
```

### Column Format
```json
{
  "columns": [
    {"skew": 0.0, "gaps": [0.0, 0.5], "bottles": [
      {"contents": "RRR?"},
      {"contents": "BB"}
    ]},
    {"skew": 0.5, "bottles": [
      {"contents": "GYOB"}
    ]}
  ]
}
```

- **String notation**: Single chars = mnemonics (R=RED, P=PURPLE, A=GREY, G=GREEN, Y=YELLOW, O=ORANGE, U=BLUE, C=CYAN, ?=UNKNOWN, J=UNKNOWN)
- **Skew**: Global vertical offset per column (0.5 = half bottle height)
- **Gaps**: Per-bottle vertical spacing (new feature)

## File Organization

```
water-match-asmr-solver/
├── main.py                 # CLI entry point
├── game_loop.py           # Interactive solver loop
├── editor.py              # Puzzle editor
├── solver.py              # A* search implementation
├── play_area.py           # Game state management
├── models.py              # Core data structures (Color, Bottle)
├── ui.py                  # Terminal rendering
├── utils.py               # JSON and color utilities
├── CLAUDE.md              # Project documentation
├── test_*.py              # Test files
└── example_*.json         # Example puzzles
```

## Important Constraints

- **Bottle capacity**: Fixed at 4 units (hard-coded throughout)
- **State immutability in solver**: GameState uses tuples, mutations in PlayArea clones
- **Unknown handling**: When unknown revealed, entire search resumes from that point
- **Original preservation**: Editor modifies copies; solver keeps original separate
- **Lock evaluation**: During A* state expansion, not during move execution
