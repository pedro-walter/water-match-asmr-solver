# Water Sort Puzzle Solver

An intelligent solver for water sort puzzles with a parallel Rust backend and interactive console UI.

## Features

- **Three search algorithms** — parallel MCTS (default), exhaustive DFS (proves unsolvable), or pure Python A*
- **Parallel Rust solver** — uses all CPU cores via Rayon; falls back to pure Python with `--algorithm python`
- **Interactive puzzle editor** — build and edit puzzles from the terminal
- **Unknown color revelation** — solver pauses when a hidden color is uncovered; auto-infers when possible
- **Bottle lock mechanics** — conditional unlocking based on completed bottle counts / colors
- **Step-by-step visualization** — ANSI colored console UI with emoji bottles

---

## Installation

### Prerequisites

| Tool | Minimum version | Notes |
|------|----------------|-------|
| Python | 3.8 | 3.10+ recommended |
| Rust toolchain | 1.70 | only needed for the Rust solver |
| maturin | 1.0 | builds the Rust extension |

The pure-Python fallback (`--algorithm python`) requires **only Python** — no Rust needed.

---

### Linux / macOS / WSL

```bash
# 1. Install Rust (skip if already installed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install maturin
pip install maturin

# 4. Build the Rust extension and install it into the venv
maturin develop --release

# 5. Run
python3 main.py example_simple.json
```

> **WSL tip:** everything above works identically inside a WSL2 shell. Use the Linux path for Rust and your WSL Python, not the Windows-side Python.

---

### Windows (native)

```powershell
# 1. Install Rust from https://rustup.rs — run the installer and restart your terminal

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1      # PowerShell
# or: .venv\Scripts\activate.bat  # Command Prompt

# 3. Install maturin
pip install maturin

# 4. Build the Rust extension
maturin develop --release

# 5. Run
python main.py example_simple.json
```

> **Note:** You may need the [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (select "Desktop development with C++") for the Rust linker. If the build fails with a linker error, install those tools and retry.

> **Windows Terminal** is strongly recommended for correct ANSI color rendering. The classic `cmd.exe` may display garbled escape codes.

---

### Skipping the Rust build

If you only want to try the solver without installing Rust:

```bash
python3 main.py example_simple.json --algorithm python
```

This uses the original Python A* implementation. It is slower and cannot prove a puzzle unsolvable, but has zero additional dependencies.

---

## Quick Start

```bash
# Solve a puzzle interactively (press Enter between moves)
python3 main.py example_simple.json

# Solve automatically with a 1-second delay between moves
python3 main.py example_simple.json --auto --delay 1.0

# Open the puzzle editor (create a new puzzle)
python3 main.py

# Load an existing puzzle for editing
python3 main.py example_complex.json --edit
```

---

## Command-Line Reference

```
python3 main.py [puzzle_file] [options]

positional arguments:
  puzzle_file           JSON puzzle file to solve or edit (optional; launches
                        editor when omitted)

options:
  --auto                Automatic mode: use delays instead of waiting for
                        keypresses
  --delay SECONDS       Delay between moves in auto mode (default: 0.5)
  --algorithm {mcts,dfs,python}
                        Search algorithm (default: mcts)
  --max-iterations N    Maximum solver iterations before giving up
                        (default: 100000000)
  --tree-size N         MCTS tree node cap per thread before compaction
                        (default: 100000). Lower = less RAM, more frequent
                        commits. Higher = more exploration per move.
  --edit                Load puzzle file into the editor instead of solving
```

---

## Algorithms

### `mcts` (default) — Parallel Monte Carlo Tree Search

Runs on all CPU cores using Rayon. Explores the state space probabilistically via UCB1 selection and greedy rollouts. Periodically compacts the tree to bound RAM usage (controlled by `--tree-size`).

- **Best for:** most puzzles — fast, RAM-bounded, scales with core count
- **Limitation:** cannot prove a puzzle is unsolvable; returns `TIMEOUT` instead

```bash
python3 main.py puzzle.json --algorithm mcts --tree-size 50000
```

### `dfs` — Parallel Exhaustive DFS (two-phase)

**Phase 1** runs a parallel DFS using a shared `DashSet` (keys only, ~42 bytes/state) to exhaustively explore all reachable states. Uses ~3× less RAM than storing full parent pointers.

**Phase 2** runs MCTS to reconstruct the actual move path once phase 1 confirms a solution exists.

- **Best for:** proving a puzzle has no solution, or when you need certainty
- **RAM note:** every visited state is kept in memory. Lower `--max-iterations` to cap usage:

| `--max-iterations` | approximate peak RAM |
|----|-----|
| 1,000,000 | ~50 MB |
| 5,000,000 | ~240 MB |
| 10,000,000 | ~480 MB |
| 100,000,000 (default) | ~4.8 GB |

```bash
python3 main.py puzzle.json --algorithm dfs --max-iterations 5000000
```

### `python` — Original Python A*

Pure-Python parallel A* with no Rust dependency. Slower and uses more RAM for large puzzles, but requires no build step.

```bash
python3 main.py puzzle.json --algorithm python
```

---

## Puzzle Format

Two JSON formats are supported.

### Standard format

```json
{
  "bottles": [
    {"number": 0, "contents": ["RED", "BLUE", "GREEN", "YELLOW"]},
    {"number": 1, "contents": ["UNKNOWN", "UNKNOWN", "RED", "RED"]},
    {"number": 2, "contents": [], "locked": {"count": 2, "color": "RED"}},
    {"number": 3, "contents": []}
  ]
}
```

### Column layout format

Arrange bottles in columns with optional vertical skew. Bottles are auto-numbered top-to-bottom, left-to-right.

```json
{
  "columns": [
    {
      "skew": 0,
      "bottles": [
        {"contents": "GCAR"},
        {"contents": "GGPP"}
      ]
    },
    {
      "skew": 0.5,
      "bottles": [
        {"contents": "YOO", "locked": {"count": 6, "color": "ANY"}},
        {"contents": "?YOO"}
      ]
    },
    {
      "bottles": [
        {"contents": "YAUP"},
        {"contents": ""}
      ]
    }
  ]
}
```

### String notation

Bottle contents can be written as a compact string using single-character mnemonics:

| Char | Color |
|------|-------|
| `R` | RED |
| `P` | PURPLE |
| `A` | GREY (grAy) |
| `G` | GREEN |
| `Y` | YELLOW |
| `O` | ORANGE |
| `U` | BLUE (blUe) |
| `C` | CYAN |
| `?` | UNKNOWN |

```json
{"contents": "RYBO"}   // RED, YELLOW, BLUE, ORANGE
{"contents": "???R"}   // three unknowns then RED
{"contents": ""}       // empty bottle
```

### Lock conditions

```json
{"locked": {"count": 6, "color": "ANY"}}    // unlock after any 6 bottles completed
{"locked": {"count": 2, "color": "CYAN"}}   // unlock after 2 CYAN bottles completed
```

---

## Example Puzzles

| File | Description |
|------|-------------|
| `example_simple.json` | 4-bottle RED/BLUE — good for a quick test |
| `example_complex.json` | Unknown colors + locked bottles |
| `example_columns.json` | Column layout with skew offsets |

---

## Project Structure

```
water-match-solver/
├── main.py                # CLI entry point
├── game_loop.py           # Interactive solver loop
├── solver.py              # Python A* + Rust solver bridge
├── editor.py              # Interactive puzzle editor
├── models.py              # Color, Bottle, LockCondition
├── play_area.py           # Mutable game state (load/save JSON)
├── ui.py                  # ANSI console UI
├── utils.py               # JSON parsing helpers
├── pyproject.toml         # maturin build config
├── rust_solver/           # Rust extension (PyO3 + Rayon)
│   ├── Cargo.toml
│   └── src/
│       ├── lib.rs          # Python bindings
│       ├── parallel.rs     # Algorithm dispatcher
│       ├── mcts.rs         # Monte Carlo Tree Search
│       ├── dfs.rs          # Exhaustive DFS (single + parallel, two-phase)
│       ├── moves.rs        # Move generation
│       ├── types.rs        # GameState, Bottle, Color
│       ├── heuristic.rs    # Fragmentation heuristic
│       └── astar.rs        # Shared result types (BestPartial, SearchStatus)
├── example_simple.json
├── example_complex.json
└── example_columns.json
```

---

## Testing

```bash
python3 test_solver.py
python3 test_multi_unknown.py
python3 test_lock_fix.py
```

---

## Rebuilding after Rust changes

```bash
# Linux / macOS / WSL
maturin develop --release

# Windows (PowerShell)
maturin develop --release
```

Changes to Python files take effect immediately with no rebuild.

---

## License

Feel free to use and modify as needed.
