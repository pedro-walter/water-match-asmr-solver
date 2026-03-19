#!/usr/bin/env python3
"""
Water Sort Puzzle Solver

A solver for water sort puzzles using A* search algorithm.
Supports bottle locking mechanics and interactive unknown color revelation.

Usage:
    python main.py <puzzle.json> [--auto] [--delay SECONDS]

Example:
    python main.py example_simple.json
    python main.py example_complex.json --auto --delay 1.0
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
        help='Path to the puzzle JSON file'
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
        default=10000000,
        help='Maximum solver iterations before timeout (default: 10000000)'
    )

    args = parser.parse_args()

    # Run the solver (interactive by default, unless --auto is specified)
    run_solver(args.puzzle_file, args.delay, interactive=not args.auto,
               max_iterations=args.max_iterations)

if __name__ == "__main__":
    main()
