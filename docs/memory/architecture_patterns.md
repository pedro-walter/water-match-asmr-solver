---
name: Architecture Patterns
description: Design decisions, key patterns, and how different systems interact
type: project
---

# Architecture & Design Patterns

## State Management Pattern

### Dual PlayArea Strategy (Solver)
When running the solver, **two separate PlayArea instances are maintained**:

```python
# In game_loop.py:
original_play_area = play_area.clone()  # Cloned at start
# During solving:
# - play_area: used for moves, state changes, solving
# - original_play_area: kept pristine, only unknowns revealed
# - saves to file: always original_play_area (never current game state)
```

**Why**: Preserve original puzzle definition. When unknown is revealed, only that single color at that position is updated in the original. This allows retry-on-failure without user re-entering unknowns.

**Pattern**: Immutable original + mutable working copy

### Mutable Editor State
The editor works directly on PlayArea instances. When editing:
- Single PlayArea instance modified in place
- `play_area.clone()` used only when launching solver
- Methods like `set_bottle_contents()`, `add_new_bottle()`, `remove_bottle()` mutate directly

**Why**: Editor needs full control to add/modify/delete bottles dynamically.

---

## Layout System Design

### Two Layout Modes (Mutually Exclusive)

1. **Row Layout**: Horizontal organization
   - `play_area.row_layout = [{'bottle_indices': [0,1,2]}, {'bottle_indices': [3,4,5]}]`
   - Rendering: `_render_rows()`
   - Default for new puzzles (user preference)
   - Renumbering preserves order: row 0 gets 0,1,2... row 1 gets 3,4,5...

2. **Column Layout**: Vertical organization with global skew + per-bottle gaps
   - `play_area.column_layout = [{'skew': 0.0, 'gaps': [0.0, 0.5], 'bottle_indices': [0,1]}]`
   - Rendering: `_render_columns()` (calculates positions based on skew + cumulative gaps)
   - Global `skew`: offset for entire column
   - Per-bottle `gaps`: spacing before each bottle (new feature)

3. **Default (No Layout)**: Single-line horizontal
   - Used when neither row_layout nor column_layout is set
   - Rendering: `_render_bottles_row()`

**Interaction Rule**: Setting `layout rows` clears `column_layout` (set to None). Setting `layout cols` clears `row_layout`.

### Gap Rendering Calculation

```python
gap_offset = 0
for i in range(bottle_position + 1):  # Cumulative sum
    if i < len(gaps):
        gap_offset += int(gaps[i] * 8)  # 8 lines = 1 bottle_height

row_start = skew_offset + gap_offset + (bottle_position * bottle_height)
```

**Key**: Gaps accumulate. Each gap value is in bottle-heights (0.5 = 4 lines).

---

## Cursor Editing Pattern (Keypress-Based)

### Input Handling (No Curses)
Uses raw `termios/tty` for single keypress reading:
```python
def _read_key() -> str:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch
```

**Why**: Avoids curses complexity. Provides immediate keypress feedback for arrow keys.

### Cursor Position Tracking
Two indices:
- `cursor_bottle`: Index into `bottles_in_order` list
- `cursor_slot`: 0=top (closest to surface), 3=bottom

**Arrow Key Mapping**:
- Up arrow (`\x1b[A`): `cursor_slot = (cursor_slot + 1) % 4`
- Down arrow (`\x1b[B`): `cursor_slot = (cursor_slot - 1) % 4`
- Left arrow (`\x1b[D`): `cursor_bottle = (cursor_bottle - 1) % len(...)`
- Right arrow (`\x1b[C`): `cursor_bottle = (cursor_bottle + 1) % len(...)`

**Color Mnemonics** (Direct slot setting):
- Pressing R/P/A/G/Y/O/U/C/? directly sets that color at selected slot
- Extends bottle contents if needed with UNKNOWN padding

### Rendering with Cursor
Cursor marker `<` appears after symbol when selected:
```
Normal:     | R |
Cursor:     | R |<  # Shows cursor at this slot
Empty:      |   |
Empty+Cur:  |   |<
```

---

## Command Dispatch Pattern (Editor)

Text input commands use prefix matching + handler functions:

```python
if command == 'help':
    show_help = True
elif command.startswith('col '):
    if ' gap' in command:
        _handle_col_gap(...)
    else:
        _handle_col_command(...)
elif command.startswith('add '):
    _handle_add(...)
# etc.
```

**Pattern**: Longest-match-first (check specific patterns before general ones)

### Handler Function Signature
```python
def _handle_*(user_input: str, play_area: PlayArea, ui: ConsoleUI, ..., show_feedback=None):
    # Validate input
    # Perform operation
    # Call show_feedback(msg, level) instead of ui.show_message()
    # (feedback deferred until after screen clear for visibility)
```

---

## Lock Condition Mechanics

### Definition
```python
lock_condition = LockCondition(count=2, color=Color.RED)
```

### Checking During Solving
In `play_area.is_bottle_locked()`:
```python
return not lock_condition.is_unlocked(
    len(completed_bottles),
    completed_colors  # dict mapping Color -> count
)
```

The condition evaluates `count` completed bottles of `color` (or ANY color if `color=None`).

### Updating
Happens after every move: `play_area.update_locks()` re-evaluates completion status.

---

## Solver Architecture

### GameState (Immutable for Hashing)
```python
GameState(
    bottles=tuple(tuple(colors) for each_bottle),  # Tuples all the way down
    locked_bottles=frozenset([bottle_indices]),
    completed_bottles=frozenset([bottle_indices]),
    completed_colors={Color: count},
    lock_conditions={bottle_num: LockCondition}
)
```

**Why immutable/hashable**: Required for A* open/closed sets deduplication.

### Heuristic Selection (Updated 2026-03-20)
```python
# Count unknowns ONLY in non-locked bottles
accessible_unknowns = count unknowns excluding locked bottles

if accessible_unknowns > 0:
    heuristic = unknown_bonus  # Prioritize revealing accessible unknowns
else:
    heuristic = color_fragmentation + disruption + lock_deficit
    # color_fragmentation: colors spread across N bottles need N-1 moves
    # disruption: color-change boundaries in bottles
    # lock_deficit: need * 4 penalty for each unmet lock condition
```

**Critical**: Never count locked-bottle unknowns as "accessible" — they can't be acted on until unlocked.

### Weighted A*
For puzzles with >12 bottles, `heuristic_weight = 2.0` is applied to h(n). This trades optimality for speed, essential for 20+ bottle puzzles.

### Move Generation Pruning
1. **Single empty target**: Only pour into the first empty bottle (symmetry breaking)
2. **No uniform-to-empty**: Skip pouring uniform bottles into empty (no-op), EXCEPT for UNKNOWN bottles (must be allowed to reveal unknowns)
3. **Reverse-move pruning**: Don't undo the parent's move (A->B then B->A)

### Completion Check
A bottle is "completed" when:
- Length == 4
- First element != Color.UNKNOWN (critical: UNKNOWN bottles must NOT be counted)
- All elements equal

---

## JSON Normalization Pattern

### Load-Time Conversion (`utils.py`)

1. **Column format -> Standard bottles format**
   - `convert_columns_to_bottles()` auto-numbers bottles top-to-bottom, left-to-right
   - Creates `column_layout` metadata with skew/gaps/bottle_indices
   - Preserves column structure for display

2. **String contents -> Color array**
   - Mnemonics (RPAGYOUC?) -> Color names
   - Stored as array in bottles dict

3. **Backward compatibility**
   - Old `'locked'` field -> `'lock_condition'`
   - Missing fields -> defaults (skew=0, gaps=[], etc.)

### Save-Time Format (`play_area.py`)
Always saves in **standard bottles format** (single flat array):
```json
{
  "bottles": [...],
  "column_layout": [...],
  "row_layout": [...]
}
```

Metadata (layouts) preserved as-is for display reconstruction.

---

## Display Rendering Pipeline

### Render Order (game_loop + editor)
1. `ui.clear_screen()`
2. Show feedback message (if any) from previous command
3. Render game state (bottles) using appropriate layout method
4. Show help text (if requested)

**Why this order**: Feedback and help are visible before game state.

### Cursor Rendering Integration
All `_render_*` methods accept optional cursor parameters:
- `_render_rows(play_area, cursor_bottle=None, cursor_slot=None)`
- `_render_columns(play_area, cursor_bottle=None, cursor_slot=None)`
- `_render_bottles_row(play_area, cursor_bottle=None, cursor_slot=None)`

Cursor marker `<` displays when bottle and slot match current position.
