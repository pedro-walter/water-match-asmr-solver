#!/usr/bin/env python3
"""Test timeout handling with a deliberately limited iteration count."""

from play_area import PlayArea
from solver import Solver
from ui import ConsoleUI

def test_timeout():
    """Test that timeout is detected and reported properly."""
    print("Testing timeout detection with example_columns.json")
    print("="*60)
    print()

    play_area = PlayArea.load_from_json('example_columns.json')
    ui = ConsoleUI()
    solver = Solver(play_area)

    # Show initial state
    ui.render_game(play_area, "Initial state")

    # Use a very small iteration limit to trigger timeout
    print("\nTrying to solve with only 100 iterations (will timeout)...")

    def progress_callback(iteration, queue_size, explored, status):
        if status == "SEARCHING" and iteration % 10 == 0:
            print(f"\rIteration {iteration}...", end="", flush=True)
        elif status != "SEARCHING":
            print()
            ui.show_progress(iteration, queue_size, explored, status)

    moves, status = solver.solve_until_unknown(max_iterations=100,
                                               progress_callback=progress_callback)

    print()
    print(f"Status: {status}")
    print(f"Moves found: {len(moves)}")

    if status == "TIMEOUT":
        print("\n✓ Timeout was correctly detected and reported")
    else:
        print(f"\n❌ Expected TIMEOUT but got {status}")

if __name__ == "__main__":
    test_timeout()
