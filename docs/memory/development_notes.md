---
name: Development Notes
description: Testing workflows, common patterns, gotchas, and debugging tips
type: project
---

# Development Notes

## Testing Workflow

### Quick Syntax Check
```bash
python3 -m py_compile *.py
```

### Testing New Features
Pattern: Create small test script for quick validation
```python
from play_area import PlayArea
from models import Color
from ui import ConsoleUI

# Create test state
pa = PlayArea()
pa.add_bottle(0, [Color.RED, Color.RED])
# Test your feature
ui = ConsoleUI()
ui.render_game(pa)
```

### Running Tests
```bash
python3 test_solver.py          # Core solver test (passes)
python3 test_lock_fix.py        # Lock mechanics test
# Note: test_unknown.py and test_multi_unknown.py require example_with_unknown.json
# which doesn't exist — these tests have pre-existing failures
```

### Testing Solver on Large Puzzles
```python
from play_area import PlayArea
from solver import Solver
import time

pa = PlayArea.load_from_json('level_126.json')
solver = Solver(pa)
start = time.time()

def progress(iteration, queue_size, closed_size, status):
    if iteration % 10000 == 0 or status != 'SEARCHING':
        print(f'iter={iteration}, q={queue_size}, vis={closed_size}, t={time.time()-start:.1f}s')

moves, status = solver.solve_until_unknown(max_iterations=500000, progress_callback=progress)
print(f'Result: {status}, moves: {len(moves)}')
```

### Manual Testing in Editor
```bash
python3 main.py                    # Start blank
# Commands to test:
> layout cols
> col add RRRG
> col 1 gap 1 0.5
> col 1 gap 1
> cedit
# (in cedit: arrow keys, mnemonics R/P/A/G/Y/O/U/C/?, Space to clear, q to quit)
> save test.json
> play
```

---

## Common Patterns & Workflows

### Adding a New Editor Command

1. **Create handler function** (place before `_print_help()`):
```python
def _handle_my_command(user_input: str, play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle 'my command' commands."""
    parts = user_input.split()
    # Validate, perform operation, provide feedback
    _show_msg(show_feedback, ui, "Command result", "success")
```

2. **Add dispatch** in main loop (line ~341):
```python
elif user_input.lower().startswith('my command'):
    _handle_my_command(user_input, play_area, ui, show_feedback)
```

3. **Update help text** in `_print_help()`:
```python
print("  my command ARG   Description here")
```

### Adding a New Rendering Mode

1. Extend **PlayArea** with layout metadata (e.g., `play_area.new_layout`)
2. Create **UI render method**: `_render_new_layout(play_area, cursor_bottle=None, cursor_slot=None)`
3. Update editor rendering switch in `_cursor_edit()`
4. Update game_loop rendering switch in `render_game()` similarly

### Modifying Bottle Data During Solve

**Rule**: Never modify `play_area` directly during solving. Use these patterns:

**To update original puzzle**:
```python
original_play_area.reveal_unknown(bottle_idx, position, color)
original_play_area.save_to_json(json_filepath)
```

**To update solver state**:
```python
play_area.reveal_unknown(bottle_idx, position, color)
solver.resume_from(play_area)
```

---

## Known Gotchas

### 1. Bottle Capacity (HARD CONSTRAINT)
Bottle capacity is 4 units, hard-coded in multiple places:
- `Bottle.transfer_to()`: checks `len(to_bottle.contents) < 4`
- `play_area.is_game_complete()`: checks `len(bottle.contents) == 4`
- `GameState.apply_move()`: `space_available = 4 - len(to_bottle)`
- Cursor slot range: `(cursor_slot +/- 1) % 4`
- Rendering: 4 content lines per bottle

**Impact**: Don't try to support variable bottle sizes without major refactor.

### 2. UNKNOWN Bottles Must NOT Be "Completed" (Fixed 2026-03-20)
`GameState.apply_move` completion check MUST filter `Color.UNKNOWN`:
```python
if (len(bottle_contents) == 4 and
        bottle_contents[0] != Color.UNKNOWN and
        all(c == bottle_contents[0] for c in bottle_contents)):
```
Without the UNKNOWN check, locked bottles with 4 UNKNOWNs get counted as completed, inflating `completed_colors` and preventing lock conditions from being met.

### 3. Heuristic Must Ignore Locked-Bottle Unknowns (Fixed 2026-03-20)
When deciding which heuristic to use, only count unknowns in NON-LOCKED bottles:
```python
for i, bottle in enumerate(state.bottles):
    if i not in state.locked_bottles:
        accessible_unknown_count += bottle.count(Color.UNKNOWN)
```
If unknowns only exist in locked bottles, using `_unknown_bonus` returns a constant (locked bottles don't change), making A* degenerate into BFS.

### 4. Uniform UNKNOWN Bottles Must Be Allowed to Pour (Fixed 2026-03-20)
The "don't pour uniform bottle into empty" optimization must exempt UNKNOWN:
```python
is_uniform = (from_consecutive == len(from_bottle)) and from_color != Color.UNKNOWN
```
Without this, newly-unlocked UNKNOWN bottles have NO valid moves (UNKNOWN only matches empty targets, but uniform-to-empty is blocked).

### 5. Layout Mutual Exclusivity
Setting one layout clears the other:
```python
if layout == 'rows':
    play_area.row_layout = [...]
    play_area.column_layout = None  # Must explicitly clear!
```

### 6. Cursor Position Wrapping
Cursor wraps around edges with modulo. Edge case: `len(bottles_in_order) == 0` causes division by zero. Check `if not bottles_in_order: return` at start of `_cursor_edit()`.

### 7. Gap Values in Rendering
Gap values are in **bottle-heights** (float):
- 0.5 = 4 lines of spacing (since bottle_height=8)
- Rendering multiplies by 8: `int(gap * 8)`
- Cumulative calculation adds gaps, then multiplies once

### 8. JSON Format Conversion
Column format is converted to standard format at load time, saved as standard format. If user edits bottles in editor, column indices might get out of sync. Always call `play_area.update_locks()` after structural changes.

### 9. Unknown Handling in Solver
Unknown colors are treated specially:
- Solver pauses when unknown is revealed
- User enters color via prompt
- **Both** play_area and original_play_area updated at same position
- Solver resumes from play_area state

**Impact**: If you modify unknown handling, ensure both copies stay in sync.

### 10. Feedback Message Timing
Messages must be shown AFTER screen clear, BEFORE game state render.

---

## Solver Performance Characteristics

### Weighted A*
- `heuristic_weight`: 1.0 for <=12 bottles, 2.0 for >12 bottles
- Trades optimality for speed — essential for large puzzles
- Weight applied as: `h_score = heuristic(state) * weight`

### Heuristic Components
1. **Color fragmentation**: colors in N bottles need N-1 moves (admissible)
2. **Disruption**: color-change boundaries per bottle (admissible)
3. **Lock deficit**: `need * 4` per unmet lock condition (guides toward unlocking)
4. Final = `max(fragmentation, disruption) + lock_penalty`

### Typical Performance
- Small puzzles (<10 bottles): instant, optimal solutions
- Medium puzzles (10-14 bottles): seconds, near-optimal
- Large puzzles (15-21 bottles): 5-30 seconds with weighted A*
- Level 126 (21 bottles, locked): ~5 seconds, 49 moves, 32k iterations

### Queue Health Indicators
- Healthy: queue stays small (<500), visited grows steadily
- Unhealthy: queue grows unbounded = weak heuristic or too broad search
- Stuck: queue tiny but visited huge = search is narrow but cycling, may need different weight

---

## Debugging Tips

### Print Debugging in Solver
```python
def progress_callback(iteration, queue_size, explored, status):
    if iteration % 10000 == 0:
        print(f"[DEBUG] iteration={iteration}, queue={queue_size}, explored={explored}")
```

### Inspect Best Partial State
```python
path, completed, it = solver.get_best_partial_solution()
best = solver.best_partial_node.state
print(f'Completed colors: {best.completed_colors}')
print(f'Locked: {best.locked_bottles}')
for i, b in enumerate(best.bottles):
    if len(b) > 0 and i not in best.completed_bottles:
        print(f'  Bottle {i}: {[c.name for c in b]}')
```

### Inspect PlayArea State
```python
print(f"Bottles: {len(pa.bottles)}")
print(f"Completed: {pa.completed_bottles}")
print(f"Locks: {pa.lock_conditions}")
for bottle in pa.bottles:
    print(f"  #{bottle.number}: {[c.name for c in bottle.contents]} (complete={bottle.is_complete})")
```

---

## Committing Changes

Always run checks before committing:
```bash
python3 -m py_compile *.py          # Syntax check
python3 test_solver.py              # Core solver test
python3 main.py example_simple.json # Manual test load
```
