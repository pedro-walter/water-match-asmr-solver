# Water Sort Puzzle Solver - Memory Index

Quick reference for working on this project.

## Core Information
- [project_overview.md](project_overview.md) - What the project is, architecture, running it
- [architecture_patterns.md](architecture_patterns.md) - Design decisions, key patterns, solver heuristics, state management
- [development_notes.md](development_notes.md) - Testing, common workflows, gotchas (includes critical solver gotchas)
- [recent_features.md](recent_features.md) - Latest: A* solver fixes for locked puzzles (2026-03-20), column gaps, cursor fixes

## Quick Start
```bash
# Run interactive solver
python3 main.py puzzle.json

# Run editor (no args = start blank)
python3 main.py

# Run editor on existing puzzle
python3 main.py puzzle.json --edit
```

## Critical Solver Notes
- Heuristic must ignore locked-bottle unknowns (see development_notes.md gotcha #3)
- UNKNOWN bottles must NOT count as completed (gotcha #2)
- Uniform UNKNOWN bottles must be allowed to pour into empty (gotcha #4)
- Weighted A* (w=2.0) used for >12 bottles for tractable search times
