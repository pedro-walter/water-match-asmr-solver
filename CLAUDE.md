# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

The project is a **Water Sort Puzzle Solver** — a Python game solver that uses A* search to find optimal solutions for water sort puzzles. It requires no external dependencies beyond Python 3.6+.

### Running the Solver

```bash
# Basic interactive mode (press Enter between moves)
python3 main.py <puzzle_file.json>

# Auto mode with delays
python3 main.py <puzzle_file.json> --auto --delay 1.0

# Common puzzle files
python3 main.py example_simple.json
python3 main.py example_complex.json
python3 main.py example_columns.json
```

### Running Tests

```bash
# Run a specific test
python3 test_solver.py
python3 test_unknown.py
python3 test_multi_unknown.py
python3 test_lock_fix.py

# Debug scripts (used during development)
python3 debug_best_state.py
python3 debug_iteration.py
```

## Architecture Overview

The solver uses **A* search** to find optimal solutions. Key architectural layers:

### Core Models (`models.py`)
- **Color**: Enum of 8 colors + UNKNOWN (RED, PURPLE, GREY, GREEN, YELLOW, ORANGE, BLUE, CYAN)
- **Bottle**: Represents a container with up to 4 color units. Methods include `add()`, `transfer_to()`, `count_consecutive_top()`
- **LockCondition**: Tracks when locked bottles unlock (e.g., "unlock after 2 RED bottles complete")

### Game State (`play_area.py`)
- **PlayArea**: Central state manager holding:
  - List of Bottle objects
  - Lock conditions per bottle
  - Completed bottles and colors tracking
  - Column layout metadata (for visual display)
- Loads/saves puzzles from JSON via `load_from_json()` and `save_to_json()`
- Tracks which bottles are complete (4 matching colors, no unknowns)

### Search Algorithm (`solver.py`)
- **GameState**: Immutable, hashable representation for A* search
  - Bottles stored as tuple of tuples (immutable for hashing)
  - Locked bottles, completed bottles tracked separately
  - Used for state deduplication and path tracking
- **Solver**: A* implementation with adaptive heuristic:
  - **If unknowns exist**: Uses only Unknown Bonus (puzzle is unsolvable until all unknowns revealed)
  - **If no unknowns**: Uses Misplaced Colors heuristic + Empty Bottle Penalty to solve
- Returns solution path as list of (from_bottle, to_bottle) moves

### Interactive Loop (`game_loop.py`)
- **run_solver()**: Main entry point managing:
  - Puzzle loading and display
  - Interactive unknown color revelation (pauses solver when unknown needs identification)
  - Move execution with visualization
  - State saving (press 's' during solving)
  - Support for batch unknown revelation (e.g., "3 BLUE" reveals 3 unknowns at once)

### UI & Utilities
- **ui.py**: ConsoleUI with ANSI color codes for terminal display
  - Supports two layouts: standard horizontal and column layout with skew offsets
  - Shows ✓ for completed bottles, 🔒 for locked bottles, ❓ for unknowns
- **utils.py**: JSON parsing and color string conversions (e.g., "R" → RED)

## Puzzle Format & Configuration

Puzzles are defined in JSON. Two formats are supported:

### Standard Format (bottles array)
```json
{
  "bottles": [
    {"number": 0, "contents": ["RED", "BLUE"], "locked": {"count": 1, "color": "ANY"}},
    {"number": 1, "contents": []}
  ]
}
```

### Column Layout Format
```json
{
  "columns": [
    {"skew": 0, "bottles": [
      {"contents": "RBG"},
      {"contents": "???"}
    ]},
    {"skew": 0.5, "bottles": [
      {"contents": "RYBO", "locked": {"count": 2, "color": "RED"}}
    ]}
  ]
}
```

**String Notation** (single-character mnemonics in order RPAGYOUC?):
- R=RED, P=PURPLE, A=GREY, G=GREEN, Y=YELLOW, O=ORANGE, U=BLUE, C=CYAN, ?=UNKNOWN
- Example: `"RBG?"` expands to `["RED", "BLUE", "GREEN", "UNKNOWN"]`

## Key Data Flows

1. **Puzzle Loading** → JSON → `utils.load_json_puzzle()` → `PlayArea.load_from_json()` → `models.Color/Bottle`
2. **Search** → `PlayArea` → `Solver.solve()` creates immutable `GameState` objects → A* with heuristic → returns move sequence
3. **Unknown Revelation** → Move requiring unknown → `game_loop.py` pauses → user input → state updated → search resumes
4. **Display** → `PlayArea` → `ConsoleUI.display_play_area()` → ANSI terminal output

## Command-Line Arguments

```
main.py <puzzle_file> [options]

--auto              Run automatically instead of interactive mode
--delay SECONDS     Delay between moves in auto mode (default: 0.5)
--max-iterations N  Maximum solver iterations (default: 10,000,000)
```

## Lock Mechanics

Bottles can be locked until conditions are met:
- Lock definition: `{"count": N, "color": "COLOR_NAME"}` or `{"count": N, "color": "ANY"}`
- Checked in `solver.py` when expanding search states
- `PlayArea` tracks `completed_bottles` set and `completed_colors` dict (color → count)
- `LockCondition.is_unlocked()` evaluates the condition

## Testing Notes

- No external test framework — tests use plain assertions
- Tests import directly from modules and instantiate classes
- Common test patterns:
  - Create `PlayArea`, load JSON, call `solver.solve()`
  - Check returned moves are valid
  - Verify final state is goal state
- Debug scripts (debug_*.py) are ad-hoc investigation tools, not part of test suite

## Important Notes for Future Development

- **Bottle capacity is fixed at 4** — hard-coded in transfer logic and completion checks
- **State immutability**: GameState uses tuples for hashing; mutations happen in PlayArea copies
- **Unknown handling**: When unknown is revealed, entire bottle layer must be re-searched from that point
- **Lock evaluation**: Happens during A* state expansion, not during move execution
- **Display columns**: Column layout is metadata only; doesn't affect puzzle logic
