---
name: Recent Features
description: Latest work - A* solver fixes for large locked puzzles, column gaps, cursor fixes
type: project
---

# Recent Features

## A* Solver Fixes for Large Puzzles with Locks (2026-03-20)

**Commit**: `344377d` - "Fix A* solver failing on large puzzles with locked bottles"

**Problem**: Level 126 (21 bottles, 2 locked with UNKNOWNs, 1 empty) caused the solver to loop indefinitely without finding a solution or reporting failure.

### Three Bugs Fixed

**Bug 1: Heuristic blind to locked-bottle unknowns** (`solver.py:_heuristic`)
- When unknowns existed only in locked bottles, `_heuristic` returned constant `_unknown_bonus` (since locked bottles never change during search)
- Made A* degenerate into BFS with zero guidance, causing state space explosion
- **Fix**: Only count unknowns in non-locked bottles when choosing heuristic mode

**Bug 2: UNKNOWN bottles wrongly counted as completed** (`solver.py:GameState.apply_move`)
- `apply_move` checked `all(c == bottle_contents[0] for c in bottle_contents)` without filtering `Color.UNKNOWN`
- Locked bottles with 4 UNKNOWNs were marked "completed", inflating `completed_colors`
- This prevented lock conditions from being met (e.g., needed 3 GREEN but count was wrong)
- **Fix**: Added `bottle_contents[0] != Color.UNKNOWN` guard to completion check

**Bug 3: Uniform UNKNOWN bottles couldn't pour** (`solver.py:_generate_valid_moves`)
- The "don't pour uniform bottle into empty" optimization treated 4 UNKNOWNs as uniform
- Since UNKNOWNs only match empty bottles, this blocked the ONLY valid move to reveal unknowns
- **Fix**: `is_uniform` now excludes bottles where `from_color == Color.UNKNOWN`

### Solver Improvements Added

1. **Weighted A*** (`heuristic_weight`): w=2.0 for >12 bottles, trades optimality for speed
2. **Lock-aware heuristic** (`_color_fragmentation_heuristic`): adds `need * 4` penalty per missing completed bottle for each lock condition
3. **Disruption heuristic**: counts color-change boundaries in bottles, takes max with fragmentation
4. **Reverse-move pruning**: filters `(B, A)` moves when parent move was `(A, B)`
5. **Skips locked bottles** in heuristic calculation (they can't be acted on)

### Result
Level 126: solved (UNKNOWN_REVEALED) in 49 moves, 32k iterations, ~5 seconds. Previously looped forever.

---

## Column Gaps (Previous Session)

**Commit**: `c63be6e`

Per-bottle vertical spacing in column layouts. Commands: `col N gap M V` to set, `col N gap M` to view.

## Cursor Rendering in Column Layouts (Previous Session)

**Commit**: `c63be6e`

Fixed cursor marker `<` not displaying in cedit mode for column layouts. All `_render_*` methods now accept cursor parameters.
