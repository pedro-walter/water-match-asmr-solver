#!/usr/bin/env python3
"""Test unknown color revelation."""

from play_area import PlayArea
from solver import Solver
from ui import ConsoleUI

def test_unknown_revelation():
    """Test that unknowns are detected and revealed."""
    print("Testing unknown revelation...")

    # Load puzzle with unknown
    play_area = PlayArea.load_from_json("example_with_unknown.json")
    ui = ConsoleUI()

    # Display initial state
    ui.render_game(play_area, "Puzzle with UNKNOWN that must be revealed")

    # Create solver and check if it detects unknown
    solver = Solver(play_area)
    moves, status = solver.solve_until_unknown()

    print(f"\nSolver status: {status}")
    print(f"Number of moves before unknown: {len(moves)}")

    if status == "UNKNOWN_REVEALED":
        print("✓ Solver correctly detected that an unknown will be revealed!")
        print(f"Move that reveals unknown: Bottle {moves[-1][0]} → Bottle {moves[-1][1]}")
        return True
    elif status == "SOLVED":
        print("✗ Solver thinks puzzle is solved without revealing unknown")
        return False
    elif status == "NO_SOLUTION":
        print("✗ Solver found no solution")
        return False

if __name__ == "__main__":
    success = test_unknown_revelation()
    if success:
        print("\n✓ Unknown detection test passed!")
    else:
        print("\n✗ Unknown detection test failed!")
