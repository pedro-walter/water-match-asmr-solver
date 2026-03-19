#!/usr/bin/env python3
"""Test the lock fix with the initial puzzle."""

from play_area import PlayArea
from solver import Solver
from ui import ConsoleUI

def test_lock_fix():
    """Test that the solver now finds unknowns with proper lock evaluation."""
    print("="*60)
    print("Testing Lock Fix with Initial Puzzle")
    print("="*60)
    print()

    play_area = PlayArea.load_from_json('example_columns.json')
    solver = Solver(play_area)
    ui = ConsoleUI()

    print("Running solver with 500,000 iterations...")
    print()

    def progress_callback(iteration, queue_size, explored, status):
        if status == "SEARCHING" and iteration % 10000 == 0:
            print(f"\rIteration {iteration:,} | Queue: {queue_size:,} | Explored: {explored:,}", end="", flush=True)
        elif status != "SEARCHING":
            print()
            ui.show_progress(iteration, queue_size, explored, status)

    moves, status = solver.solve_until_unknown(max_iterations=500000,
                                               progress_callback=progress_callback)

    print()
    print(f"Status: {status}")
    print(f"Moves: {len(moves)}")
    print()

    if status == "UNKNOWN_REVEALED":
        print("✓✓✓ UNKNOWN FOUND! ✓✓✓")
        print()
        print(f"Path to unknown ({len(moves)} moves):")
        for i, (from_idx, to_idx) in enumerate(moves, 1):
            print(f"  {i}. Bottle {from_idx} → Bottle {to_idx}")
        print()

        # Apply moves and show the final state
        for from_idx, to_idx in moves[:-1]:  # All except last
            play_area.apply_move(from_idx, to_idx)

        print("State before revealing unknown:")
        from_idx, to_idx = moves[-1]
        from_bottle = play_area.bottles[from_idx]
        to_bottle = play_area.bottles[to_idx]
        print(f"  From bottle {from_idx}: {[c.name for c in from_bottle.contents]}")
        print(f"  To bottle {to_idx}: {[c.name for c in to_bottle.contents]}")
        print()

    elif status == "SOLVED":
        print("✓ Puzzle was solved completely!")
    elif status == "TIMEOUT":
        print("⏱️  Solver timed out")
        best_moves, completed_count, best_iteration = solver.get_best_partial_solution()
        print(f"Best state: {completed_count} bottles completed at iteration {best_iteration:,}")
    elif status == "NO_SOLUTION":
        print("❌ No solution exists")

if __name__ == "__main__":
    test_lock_fix()
