#!/usr/bin/env python3
"""Quick test script to verify the solver works."""

from play_area import PlayArea
from solver import Solver
from ui import ConsoleUI
from game_loop import run_solver

def test_simple_puzzle():
    """Test solving the simple puzzle."""
    print("Testing simple puzzle...")

    # Load the puzzle
    play_area = PlayArea.load_from_json("example_simple.json")
    ui = ConsoleUI()

    # Display initial state
    ui.render_game(play_area, "Initial State")

    # Create solver and solve
    solver = Solver(play_area)
    moves, status = solver.solve_until_unknown()

    print(f"\nSolver status: {status}")
    print(f"Number of moves: {len(moves)}")

    if status == "SOLVED":
        print("✓ Puzzle has a solution!")

        # Apply moves to verify
        for i, (from_idx, to_idx) in enumerate(moves):
            success = play_area.apply_move(from_idx, to_idx)
            if not success:
                print(f"✗ Move {i+1} failed: {from_idx} → {to_idx}")
                return False

        # Check if complete
        if play_area.is_game_complete():
            print("✓ Puzzle successfully solved!")
            ui.render_game(play_area, f"Solved in {len(moves)} moves")
            return True
        else:
            print("✗ Puzzle not complete after applying moves")
            return False

    elif status == "NO_SOLUTION":
        print("✗ No solution found")
        return False

    return False

def test_complex_puzzle():
    """Test loading the complex puzzle (with unknowns)."""
    print("\n" + "="*50)
    print("Testing complex puzzle loading...")

    try:
        play_area = PlayArea.load_from_json("example_complex.json")
        ui = ConsoleUI()

        ui.render_game(play_area, "Complex Puzzle (with UNKNOWNs and locks)")

        print("\nLocked bottles:")
        for i, bottle in enumerate(play_area.bottles):
            if play_area.is_bottle_locked(bottle.number):
                print(f"  - Bottle #{bottle.number}")

        print("\n✓ Complex puzzle loaded successfully")
        return True

    except Exception as e:
        print(f"✗ Error loading complex puzzle: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success1 = test_simple_puzzle()
    success2 = test_complex_puzzle()

    print("\n" + "="*50)
    if success1 and success2:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed")
