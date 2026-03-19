# Plan: Interactive Puzzle Editor Mode

## Context
Running `python3 main.py` with no puzzle file should drop into an interactive editor
where the user can build a play area from scratch, edit bottle contents and locks,
organize bottles into manual columns, then launch the solver or save to JSON.

## Files to Modify / Create
- `main.py` — make `puzzle_file` optional (`nargs='?'`), route to `run_editor()` when absent
- `play_area.py` — add mutation helpers the editor needs
- `editor.py` (NEW) — the full editor REPL

---

## 1. main.py changes
Make `puzzle_file` a positional optional:
```python
parser.add_argument('puzzle_file', nargs='?', default=None, ...)
```
At the bottom:
```python
if args.puzzle_file:
    run_solver(args.puzzle_file, ...)
else:
    from editor import run_editor
    run_editor()
```

---

## 2. play_area.py — new mutation methods

Add to `PlayArea`:

**`set_bottle_contents(bottle_number, colors: List[Color])`**
- Find bottle by number, replace `bottle.contents`, reset `bottle.is_complete`
- Re-check if now complete (len==4, all equal, not UNKNOWN) and set flag
- Call `update_locks()`

**`set_lock(bottle_number, count, color)`** (color=None means ANY)
- `self.lock_conditions[bottle_number] = LockCondition(count, color)`
- Call `update_locks()`

**`remove_lock(bottle_number)`**
- `del self.lock_conditions[bottle_number]` if present
- Call `update_locks()`

**`add_new_bottle(contents=None) -> int`**
- `number = max(b.number for b in self.bottles) + 1` (or 0 if empty)
- `add_bottle(number, contents)` (existing method)
- Return `number`

**`remove_bottle(bottle_number)`**
- Remove from `self.bottles` list
- Remove from `self.lock_conditions` if present
- Remove from `column_layout` bottle_indices if `column_layout` is set
- Call `update_locks()`

---

## 3. editor.py — REPL

### Entry point
```python
def run_editor():
    play_area = PlayArea()
    ui = ConsoleUI()
    _loop(play_area, ui)
```

### Main loop
After every command: `ui.render_game(play_area, header)` where header shows the mode.

### Command dispatch

| Input | Action |
|---|---|
| `1???R` (digit + mnemonics) | Quick-set bottle 1 contents to `???R` |
| `1` (digit only) | Bottle wizard for bottle 1 |
| `add [MNEMONIC]` | Add new bottle (to last column if in col mode) |
| `col N add [MNEMONIC]` | Add new bottle to column N (creates col if needed) |
| `col add` | Create a new empty column |
| `del N` / `remove N` | Remove bottle N |
| `move N col M` | Move bottle N to column M |
| `layout rows` | Set `play_area.column_layout = None` |
| `layout cols` | Auto-initialize `column_layout` from existing bottles if needed |
| `save [filename]` | Save to JSON (default: `puzzle_<timestamp>.json`) |
| `play` | Call `run_solver()` and exit editor |
| `help` | Print command reference |
| `q` / `quit` | Exit |

### Quick-set regex
`^(\d+)([RPAGYOUCBrpagyoucb?]+)$` — digit prefix + only mnemonic chars
Parse contents with `parse_bottle_contents()` from `utils.py` (already handles strings).

### Bottle wizard (typing just a number)
```
Bottle #N: [current contents]  [LOCKED: 2 RED]
Contents (mnemonics, empty to keep): > RRRG
Locked? (e.g. '2 RED' or '3 ANY', empty for none, 'none' to clear): > 2 RED
```
Lock parsing: split on space → `(count, color_str)` → validate count is int, color via
`color_from_string()` from `utils.py`, "ANY" → `None`.

### Column management
`play_area.column_layout` structure (existing):
```python
[{'skew': 0.0, 'bottle_indices': [0, 1, 2]}, ...]
```
- `col N add` → column index is N-1; append new bottle number to `column_layout[N-1]['bottle_indices']`
- `col add` → append `{'skew': 0.0, 'bottle_indices': []}` to `column_layout`
- `move B col M` → remove B from its current column's indices, add to column M-1
- `layout cols` → if `column_layout` is None, create one column with all bottles
- `layout rows` → set `column_layout = None`

### Error handling
Wrap each command in try/except, show `ui.show_message(..., "error")` on ValueError.
Unknown command → show message + suggest `help`.

---

## Verification
1. `python3 main.py` — launches editor, shows empty grid
2. `add RRRG` — bottle #0 appears with RED/RED/RED/GREEN contents
3. `col 1 add BBBB` — bottle goes to column 1 in column view
4. `0YYYY` — quick-sets bottle 0 to all YELLOW, screen refreshes
5. `1` — wizard prompts contents + lock for bottle 1
6. `layout rows` / `layout cols` — switches display
7. `save test.json` — writes valid JSON loadable by `PlayArea.load_from_json`
8. `play` — hands off to `run_solver` with the built play area
9. `python3 main.py test.json` — still works normally
10. Run `python3 test_solver.py` — passes (no regressions)
