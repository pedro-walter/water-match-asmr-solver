# Water Sort Puzzle Solver

An intelligent solver for water sort puzzles using A* search algorithm. Features include:
- Optimal solution finding (shortest path)
- Interactive unknown color revelation
- Bottle locking mechanics
- Beautiful console UI with ANSI colors
- Step-by-step visualization

## Features

- **A* Search Algorithm**: Finds optimal (shortest) solutions
- **Interactive Mode**: Press Enter to proceed through each move
- **Unknown Colors**: Solver pauses when unknowns are revealed for user identification
  - **NEW**: Reveal multiple consecutive unknowns at once (e.g., "3 RED" or "RED 3")
- **Bottle Locks**: Support for conditional bottle unlocking
  - Unlock after X bottles completed
  - Unlock after X bottles of specific color completed
- **Visual Display**: Colored emoji bottles in terminal
- **JSON Configuration**: Easy puzzle definition
- **Save State**: Press 's' during solving to save current state

## Installation

No dependencies required beyond Python 3.6+. Just clone and run!

```bash
cd water-match-solver
python3 main.py example_simple.json
```

## Usage

### Basic Usage

```bash
# Interactive mode (default) - press Enter between moves
python3 main.py example_simple.json

# Auto mode with delays
python3 main.py example_simple.json --auto --delay 1.0
```

### Command Line Options

```
python3 main.py <puzzle_file> [options]

Options:
  --auto              Automatic mode (use delays instead of keypresses)
  --delay SECONDS     Delay between moves in auto mode (default: 0.5)
```

## Example Puzzles

### Simple Puzzle (`example_simple.json`)
Basic 4-bottle puzzle with RED and BLUE colors. Good for testing.

```bash
python3 main.py example_simple.json
```

### Complex Puzzle (`example_complex.json`)
Features:
- UNKNOWN colors that must be revealed
- Locked bottles that unlock after conditions are met
- Tests interactive unknown revelation

```bash
python3 main.py example_complex.json
```

### Unknown Test (`example_with_unknown.json`)
Simple puzzle demonstrating unknown color revelation.

```bash
python3 main.py example_with_unknown.json
```

### Column Layout Example (`example_columns.json`)
Demonstrates:
- Column layout with skew offsets
- String notation for bottle contents
- Auto-numbering from top-to-bottom, left-to-right
- Color mnemonics

```bash
python3 main.py example_columns.json
```

## Puzzle Format

Define puzzles in JSON format. Two formats are supported:

### Format 1: Standard Bottles Array

```json
{
  "bottles": [
    {
      "number": 0,
      "contents": ["RED", "RED", "RED", "UNKNOWN"]
    },
    {
      "number": 1,
      "contents": ["BLUE", "BLUE", "BLUE", "BLUE"]
    },
    {
      "number": 2,
      "contents": [],
      "locked": {"count": 1, "color": "ANY"}
    }
  ]
}
```

### Format 2: Column Layout (NEW!)

Arrange bottles in columns with optional vertical skew. Bottles are auto-numbered top-to-bottom, left-to-right:

```json
{
  "columns": [
    {
      "skew": 0,
      "bottles": [
        {"contents": "GCAR"},
        {"contents": "GGPP"},
        {"contents": "AGRG"}
      ]
    },
    {
      "skew": 0.5,
      "bottles": [
        {"contents": "YOO", "locked": {"count": 6, "color": "ANY"}},
        {"contents": "?YOO"},
        {"contents": "???R", "locked": {"count": 2, "color": "CYAN"}}
      ]
    },
    {
      "bottles": [
        {"contents": "YAUP"},
        {"contents": "BARR"},
        {"contents": "OGUR"}
      ]
    }
  ]
}
```

**Column Layout Features:**
- `skew`: Vertical offset in bottle heights (0.5 = half bottle, 1.0 = one bottle, etc.)
- Bottles auto-numbered from top to bottom, then left to right
- Compact string notation for contents (see below)

### Bottle Properties

- **number**: Unique bottle identifier (auto-assigned in column layout)
- **contents**: Bottle contents in two formats:
  - **Array format**: `["RED", "BLUE", "GREEN"]` - full color names
  - **String format**: `"RBG"` - single-character mnemonics (see below)
- **locked** (optional): Lock condition with `count` and `color` fields

### String Notation for Contents

Use compact single-character mnemonics for bottle contents:

```json
{"contents": "RYBO"}  // Equivalent to ["RED", "YELLOW", "BLUE", "ORANGE"]
{"contents": "???R"}  // Three unknowns and a red
{"contents": ""}      // Empty bottle
```

**Color Mnemonics (order: RPAGYOUC?):**
- `R` = RED 🟥
- `P` = PURPLE 🟪
- `A` = GREY ⬜ (grAy)
- `G` = GREEN 🟩
- `Y` = YELLOW 🟨
- `O` = ORANGE 🟧
- `U` = BLUE 🟦 (blUe)
- `B` = BLUE 🟦 (alternative)
- `C` = CYAN 🩵
- `?` = UNKNOWN ❓

**Note:** Both `GREY` and `GRAY` spellings are supported in array format.

### Lock Conditions (Simplified Format)

Bottles can be locked until certain conditions are met. Use the `"locked"` field with `count` and `color`:

**Unlock after any X bottles completed:**
```json
{"locked": {"count": 6, "color": "ANY"}}
```

**Unlock after X bottles of specific color completed:**
```json
{"locked": {"count": 2, "color": "CYAN"}}
{"locked": {"count": 1, "color": "RED"}}
```

The `color` field accepts:
- `"ANY"` - any completed bottle counts
- Any valid color name (`"RED"`, `"BLUE"`, `"CYAN"`, etc.)

### Available Colors

All standard colors plus UNKNOWN:
- RED 🟥 (R)
- PURPLE 🟪 (P)
- GREY/GRAY ⬜ (A)
- GREEN 🟩 (G)
- YELLOW 🟨 (Y)
- ORANGE 🟧 (O)
- BLUE 🟦 (U or B)
- CYAN 🩵 (C)
- UNKNOWN ❓ (?) - for interactive revelation

## How It Works

### A* Search Algorithm

The solver uses A* search with a composite heuristic:

1. **Misplaced Colors**: Estimates moves needed based on colors not in final position
2. **Unknown Bonus**: Prioritizes revealing unknown colors
3. **Empty Bottle Penalty**: Favors states with more working space

### Interactive Unknown Handling

When an UNKNOWN color is about to be revealed:
1. Solver pauses execution
2. User is prompted to identify the color(s)
3. Game state is updated
4. Solving continues from updated state

**Multiple Unknown Revelation (NEW):**
When multiple consecutive unknowns are revealed, you can specify them all at once:
```
🔍 3 UNKNOWN colors revealed in Bottle #5!
What color(s) are they?
> 3 BLUE        # Reveals all 3 as BLUE
# or
> BLUE 3        # Same result
# or
> 2 BLUE        # Reveals top 2 as BLUE (solver will ask about remaining 1 later)
```

See [MULTI_UNKNOWN.md](MULTI_UNKNOWN.md) for detailed documentation.

## Project Structure

```
water-match-solver/
├── models.py              # Core classes (Color, Bottle, LockCondition)
├── play_area.py           # Game state management
├── solver.py              # A* search algorithm
├── ui.py                  # Console UI with ANSI colors
├── game_loop.py           # Interactive solver loop
├── utils.py               # JSON utilities
├── main.py                # CLI entry point
├── example_simple.json    # Simple test puzzle
├── example_complex.json   # Complex puzzle with unknowns
└── example_with_unknown.json  # Unknown revelation test
```

## Testing

Run the test suite:

```bash
# Test core functionality
python3 test_solver.py

# Test unknown detection
python3 test_unknown.py
```

## Display

The solver supports two display modes:

### Column Layout (with skew offsets)

When using the `columns` format, bottles are displayed in vertical columns with proper skew offsets:

```
                  #7
                ┌────┐
                │ 🟥 │
          #4    │ 🟥 │
        ┌────┐  │ 🟥 │
        │ 🟧 │  │ 🟥 │
  #1    │ 🟧 │  └────┘
┌────┐  │ 🟨 │    #8
│ 🟪 │  │ ❓ │  ┌────┐
│ 🟪 │  └────┘  │ 🟥 │
│ 🟩 │    #5 🔒  │ 🟦 │
│ 🟩 │  ┌────┐  │ 🟩 │
└────┘  │ 🟥 │  │ 🟧 │
        │ ❓ │  └────┘
  #2    │ ❓ │
┌────┐  │ ❓ │    #9
│ 🟩 │  └────┘  ┌────┐
│ 🟥 │          │ 🟦 │
│ 🟩 │    #6    │ ⬜ │
│ ⬜ │  ┌────┐  │ ⬜ │
└────┘  │ 🟪 │  │ 🟦 │
        │ 🟦 │  └────┘
  #3 🔒  │ ⬜ │
┌────┐  │ 🟨 │   #10
│    │  └────┘  ┌────┐
│ 🟧 │          │ ❓ │
│ 🟧 │          │ ❓ │
│ 🟨 │          │ ❓ │
└────┘          │ ❓ │
                └────┘ ✓
```

### Horizontal Layout (standard)

For puzzles without column layout, bottles are displayed side-by-side:

```
#0        #1        #2        #3
┌────┐    ┌────┐    ┌────┐    ┌────┐
│ 🟦 │    │ 🟥 │    │    │    │    │
│ 🟥 │    │ 🟦 │    │    │    │    │
│ 🟦 │    │ 🟥 │    │    │    │    │
│ 🟥 │    │ 🟦 │    │    │    │    │
└────┘    └────┘    └────┘    └────┘
```

**Display Features:**
- ✓ indicates completed bottles
- 🔒 indicates locked bottles
- ❓ indicates unknown colors
- #XX labels (simplified from "Bottle #XX")

## Tips for Creating Puzzles

1. **Solvability**: Ensure enough empty bottles for working space
2. **Unknown Placement**: Place unknowns where they must be revealed to solve
3. **Lock Design**: Use locks to add complexity and guide solution paths
4. **Testing**: Test with `--auto` mode first to verify solvability

## License

Feel free to use and modify as needed!
