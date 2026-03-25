#!/usr/bin/env python3
"""
Water Sort Puzzle Solver

A solver for water sort puzzles using A* search algorithm.
Supports bottle locking mechanics and interactive unknown color revelation.

Usage:
    python main.py [puzzle.json] [options]

Examples:
    python main.py                          # Launch editor (new puzzle)
    python main.py example_simple.json      # Solve puzzle
    python main.py example.json --edit      # Edit existing puzzle
    python main.py example.json --auto --delay 1.0
"""

import argparse
from game_loop import run_solver

def main():
    parser = argparse.ArgumentParser(
        description="Solve water sort puzzles with A* search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py example_simple.json
  python main.py example_complex.json --auto --delay 1.0
        """
    )

    parser.add_argument(
        'puzzle_file',
        nargs='?',
        default=None,
        help='Path to the puzzle JSON file (optional; launches editor if omitted)'
    )

    parser.add_argument(
        '--auto',
        action='store_true',
        help='Automatic mode: use delays instead of waiting for keypresses'
    )

    parser.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='Delay in seconds between moves in auto mode (default: 0.5)'
    )

    parser.add_argument(
        '--max-iterations',
        type=int,
        default=100000000,
        help='Maximum solver iterations before timeout (default: 100000000)'
    )

    parser.add_argument(
        '--tree-size',
        type=int,
        default=100000,
        help='MCTS tree size cap per thread before compaction (default: 100000). '
             'Lower = less RAM, more frequent commits. Higher = more exploration per move.'
    )

    parser.add_argument(
        '--algorithm',
        choices=['mcts', 'dfs', 'python'],
        default='mcts',
        help='Search algorithm: mcts (default, parallel Monte Carlo), '
             'dfs (exhaustive depth-first — can prove no solution exists), '
             'python (original Python A*, no Rust)'
    )

    parser.add_argument(
        '--chunk-depth',
        type=int,
        default=4,
        help='DFS chunk depth K (default: 4). The search space is split into all '
             'states reachable in K moves; each becomes an independent DFS worker. '
             'Higher K = more chunks, smaller per-chunk RAM, more cross-chunk overlap.'
    )

    parser.add_argument(
        '--edit',
        action='store_true',
        help='Load puzzle file for editing instead of solving'
    )

    args = parser.parse_args()

    if args.puzzle_file:
        if args.edit:
            # Load puzzle for editing
            from editor import run_editor
            run_editor(args.puzzle_file)
        else:
            # Run the solver (interactive by default, unless --auto is specified)
            run_solver(args.puzzle_file, args.delay, interactive=not args.auto,
                       max_iterations=args.max_iterations, tree_size=args.tree_size,
                       chunk_depth=args.chunk_depth, algorithm=args.algorithm)
    else:
        # Launch the editor with a new puzzle
        from editor import run_editor
        run_editor()

if __name__ == "__main__":
    main()
