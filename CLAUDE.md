# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

The project is a **Water Sort Puzzle Solver** — a Python game solver that uses parallel A* search to find optimal solutions for water sort puzzles. It requires no external dependencies beyond Python 3.6+.

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
python3 test_solver.py
python3 test_multi_unknown.py
python3 test_lock_fix.py

# Debug scripts (ad-hoc investigation tools, not part of test suite)
python3 debug_best_state.py
python3 debug_iteration.py
```

## Architecture Overview

The solver uses **parallel A* search** to find optimal solutions. Key architectural layers:

### Core Models (`models.py`)
- **Color**: Enum of 8 colors + UNKNOWN (RED, PURPLE, GREY, GREEN, YELLOW, ORANGE, BLUE, CYAN)
- **Bottle**: Container with up to 4 color units. Key methods: `add()`, `transfer_to()`, `count_consecutive_top()`
- **LockCondition**: Tracks when locked bottles unlock (e.g., "unlock after 2 RED bottles complete")

### Game State (`play_area.py`)
- **PlayArea**: Central mutable state manager holding:
  - List of `Bottle` objects
  - Lock conditions per bottle index
  - Completed bottles and colors tracking
  - Column layout metadata (visual only)
- Loads/saves puzzles from JSON via `load_from_json()` and `save_to_json()`
- `clone()` produces a deep copy for branching (used by solver and debug saves)

### Search Algorithm (`solver.py`)

#### Immutable Search State
- **GameState**: Immutable, hashable snapshot for A* nodes
  - Bottles stored as `tuple[tuple[Color]]` (hashable)
  - `to_key() -> bytes`: compact encoding — 2 colors per byte (nibbles), 42 bytes for a 21-bottle puzzle. Used as dict key instead of the full object to keep visited-state memory at ~180MB vs ~15GB.
  - `apply_move(src, dst)` returns a new `GameState` without mutating

#### Heuristic (adaptive)
- **If unknowns exist**: Unknown Bonus only (puzzle is unsolvable until all unknowns revealed — no point optimizing further)
- **If no unknowns**: `_color_fragmentation_heuristic` + empty bottle penalty
  - Counts how many separate runs each color is fragmented into across all bottles (including locked ones)
  - Lock penalty: `need * 4 + max(bottles_with_prereq - need, 0)` where `need` = locked bottles still requiring prerequisite color
  - `heuristic_weight` scaled up to 5.0 for puzzles with hard lock conditions (`_compute_lock_difficulty`)

#### Parallel A* (`Solver.solve_parallel`)
Entry point for all solving. Falls back to single-threaded if too few partitions.

1. **`_generate_partitions(depth=2)`** — enumerate every state reachable in 2 moves from the current position, skipping moves that would trigger interactive pauses (unknown revelation or bottle unlock). Produces ~50–200 diverse starting points.

2. **`ProcessPoolExecutor`** distributes partitions across all CPU cores. Each worker runs independent `_astar_search()` from its starting state and prepends its 2-move prefix to any solution found.

3. **Stop signal** via `mp.Manager().Event()` (must be a managed proxy — bare `mp.Event()` cannot be pickled for inter-process communication). When any worker finds a solution, the event is set and remaining futures are cancelled.

4. **Iteration budget**: `iter_per_partition = max_iterations // ceil(n_partitions / num_processes)`. Total wall-clock time ≈ single-threaded, but covers ~`num_processes`× more of the state space from diverse starting points.

**Why parallel search is dramatically faster for hard puzzles**: Single-threaded A* follows the heuristically "best" path and can get trapped in a large dead-end neighborhood for millions of iterations. Partitioning forces simultaneous exploration of diverse regions — one partition is likely to start near the actual solution path and finds it quickly. Analogy: drop 50 people at different spots in a maze; one will be near the exit.

#### Module-level functions (required for pickling)
All A* helpers must be module-level (not class methods) so `ProcessPoolExecutor` can pickle them:
- `_astar_search(initial_state, heuristic_weight, max_iterations, stop_event, progress_callback)` — the core loop, returns `(moves, status, best_partial_node, best_iteration)`
- `_parallel_worker(task)` — unpacks task tuple, calls `_astar_search`, prepends prefix moves
- `_generate_valid_moves`, `_heuristic`, `_color_fragmentation_heuristic`, `_unknown_bonus`, `_reconstruct_path`, `_is_revealing_unknown`, `_is_unlocking_unknown_bottle`, `_count_consecutive_top`

### Interactive Loop (`game_loop.py`)
- **`run_solver()`**: Main entry point managing:
  - Puzzle loading, display, and color count diagnostics
  - Calls `solver.solve_parallel()` in a loop until puzzle complete
  - **UNKNOWN_REVEALED**: solver pauses; `infer_unknown_color()` tries to auto-infer (if exactly one color is short of a multiple-of-4 and the deficit equals total unknowns); otherwise prompts user
  - **BOTTLE_UNLOCKED**: solver pauses; detects newly-unlocked bottles whose contents are empty or all-unknown; prompts user for actual contents
  - Move execution with visualization and optional interactive stepping
  - State saving (press `s` during solving or at any pause)

- **`infer_unknown_color(play_area)`**: Color count inference — each color must appear a multiple-of-4 times total. If exactly one color is short and the deficit equals the total unknown count, auto-reveals without asking.

### UI & Utilities
- **`ui.py`**: ConsoleUI with ANSI color codes
  - Two layouts: standard horizontal and column layout with skew offsets
  - Shows ✓ for completed bottles, 🔒 for locked, ❓ for unknowns
  - `print_color_counts(play_area)`: shows each color count with ✓ (multiple of 4) or warning if short
- **`utils.py`**: JSON parsing and color string conversions (e.g., `"R"` → RED)
- **`editor.py`**: Interactive puzzle editor; renders color counts on every cycle

## Puzzle Format & Configuration

Two JSON formats are supported:

### Standard Format
```json
{
  "bottles": [
    {"number": 0, "contents": ["RED", "BLUE"], "lock_condition": {"count": 1, "color": "ANY"}},
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

**String Notation** (single-character mnemonics):
- R=RED, P=PURPLE, A=GREY, G=GREEN, Y=YELLOW, O=ORANGE, U=BLUE, C=CYAN, ?=UNKNOWN
- Example: `"RGYC"` expands to `["RED", "GREEN", "YELLOW", "CYAN"]`

## Key Data Flows

1. **Puzzle Loading** → JSON → `utils.load_json_puzzle()` → `PlayArea.load_from_json()` → `models.Color/Bottle`
2. **Search** → `PlayArea` → `Solver.solve_parallel()` → partitions → `ProcessPoolExecutor` → `_astar_search()` per worker → first solution wins → move sequence returned
3. **Unknown Revelation** → move hits UNKNOWN → `game_loop.py` pauses → auto-infer or user input → `PlayArea` updated → `solver.resume_from()` → search resumes
4. **Bottle Unlock** → locked bottle opens → contents empty/unknown → `game_loop.py` prompts user → `PlayArea` updated → search resumes
5. **Display** → `PlayArea` → `ConsoleUI.display_play_area()` → ANSI terminal output

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
- Evaluated during A* state expansion (not during move execution)
- `PlayArea` tracks `completed_bottles` set and `completed_colors` dict (color → count)
- `LockCondition.is_unlocked()` evaluates the condition
- When a bottle unlocks and has empty/unknown contents, the interactive loop pauses to ask the user

## Testing Notes

- No external test framework — tests use plain assertions
- Tests import directly from modules and instantiate classes
- Common pattern: create `PlayArea`, load JSON, call `solver.solve_parallel()`, verify final state
- Debug scripts (`debug_*.py`) are ad-hoc investigation tools, not part of the test suite

## Important Notes for Future Development

- **Bottle capacity is fixed at 4** — hard-coded in transfer logic and completion checks
- **State immutability**: `GameState` uses tuples; mutations happen on `PlayArea` copies. Never mutate a `GameState`.
- **Module-level functions are required**: Any function called inside a `ProcessPoolExecutor` worker must be defined at module level (not as a class/instance method). Bound methods cannot be pickled.
- **Manager vs bare Event**: Use `mp.Manager().Event()` for the stop signal — bare `mp.Event()` raises a pickling error when passed to worker processes.
- **Memory**: `best_g` dict uses `GameState.to_key()` (bytes) as key, not the full `GameState`. At 4M states this is ~180MB vs ~15GB.
- **Unknown handling**: When an unknown is revealed, `solver.resume_from()` rebuilds `current_state` and the entire search restarts from the updated position.
- **Lock evaluation**: Happens during A* state expansion; locked bottles are excluded from valid move targets.
- **Display columns**: Column layout is metadata only; doesn't affect puzzle logic or search.
- **Color count invariant**: Every color must appear a multiple-of-4 times across all bottles. The solver and editor both surface violations; `infer_unknown_color()` exploits this to auto-reveal unknowns.
