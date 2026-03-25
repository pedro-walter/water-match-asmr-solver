import time
import os
import json
from play_area import PlayArea
from solver import Solver
from ui import ConsoleUI
from models import Color

def save_current_state(play_area: PlayArea, json_filepath: str, ui: ConsoleUI):
    """
    Save the current game state to a file.

    Args:
        play_area: Current PlayArea to save
        json_filepath: Original puzzle file path (used for naming)
        ui: UI instance for showing messages
    """
    # Generate filename based on current state
    base_name = os.path.splitext(json_filepath)[0]
    counter = 1
    while True:
        save_path = f"{base_name}_state{counter}.json"
        if not os.path.exists(save_path):
            break
        counter += 1

    try:
        play_area.save_to_json(save_path)
        ui.show_message(f"✓ Saved current state to: {save_path}", "success")
    except Exception as e:
        ui.show_message(f"❌ Failed to save: {e}", "error")
    print()

def save_revealed_unknowns(json_filepath: str, revealed_unknowns: dict, ui: ConsoleUI):
    """
    Update the original JSON file with only the revealed unknown colors.
    Does not save the current game state (moves applied).

    Args:
        json_filepath: Path to the original puzzle file
        revealed_unknowns: Dict mapping bottle_number -> {position: color}
        ui: UI instance for showing messages
    """
    if not revealed_unknowns:
        return

    # Load the original JSON
    with open(json_filepath, 'r') as f:
        data = json.load(f)

    # Update revealed unknowns in the JSON data
    if 'bottles' in data:
        # Standard format
        for bottle_data in data['bottles']:
            bottle_number = bottle_data['number']
            if bottle_number in revealed_unknowns:
                # Get revelations for this bottle
                revelations = revealed_unknowns[bottle_number]

                # Update contents
                if isinstance(bottle_data['contents'], str):
                    # String format - convert to list, update, convert back
                    from utils import parse_bottle_contents, COLOR_MNEMONICS
                    contents_list = parse_bottle_contents(bottle_data['contents'])

                    for position, color in revelations.items():
                        if position < len(contents_list):
                            contents_list[position] = color

                    # Convert back to string using mnemonics
                    mnemonic_reverse = {v: k for k, v in COLOR_MNEMONICS.items()}
                    contents_str = ''.join(mnemonic_reverse.get(c, '?') for c in contents_list)
                    bottle_data['contents'] = contents_str

                elif isinstance(bottle_data['contents'], list):
                    # Array format
                    for position, color in revelations.items():
                        if position < len(bottle_data['contents']):
                            bottle_data['contents'][position] = color.name

    elif 'columns' in data:
        # Column format - need to find bottles by auto-numbering
        bottle_num = 0
        for column in data['columns']:
            for bottle_data in column['bottles']:
                if bottle_num in revealed_unknowns:
                    revelations = revealed_unknowns[bottle_num]

                    # Update contents (same logic as above)
                    if isinstance(bottle_data['contents'], str):
                        from utils import parse_bottle_contents, COLOR_MNEMONICS
                        contents_list = parse_bottle_contents(bottle_data['contents'])

                        for position, color in revelations.items():
                            if position < len(contents_list):
                                contents_list[position] = color

                        mnemonic_reverse = {v: k for k, v in COLOR_MNEMONICS.items()}
                        contents_str = ''.join(mnemonic_reverse.get(c, '?') for c in contents_list)
                        bottle_data['contents'] = contents_str

                    elif isinstance(bottle_data['contents'], list):
                        for position, color in revelations.items():
                            if position < len(bottle_data['contents']):
                                bottle_data['contents'][position] = color.name

                bottle_num += 1

    # Save back to file
    with open(json_filepath, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')

    ui.show_message(f"Saved revealed unknowns to {json_filepath}", "info")

def infer_unknown_color(play_area: PlayArea):
    """
    Try to infer what the unknown color(s) must be using the constraint that
    each color appears a multiple of 4 times across all bottles.

    Returns the inferred Color if exactly one color has a non-multiple-of-4
    count and its deficit equals the total number of unknowns, else None.
    """
    from models import Color
    color_counts = {}
    total_unknown = 0

    for bottle in play_area.bottles:
        for color in bottle.contents:
            if color == Color.UNKNOWN:
                total_unknown += 1
            else:
                color_counts[color] = color_counts.get(color, 0) + 1

    if total_unknown == 0:
        return None

    # Colors whose count is not a multiple of 4 and how many more they need
    short_colors = {
        c: (4 - cnt % 4) % 4
        for c, cnt in color_counts.items()
        if cnt % 4 != 0
    }
    total_needed = sum(short_colors.values())

    if total_needed == total_unknown and len(short_colors) == 1:
        return next(iter(short_colors.keys()))

    return None


def run_solver(json_filepath: str, delay: float = 0.5, interactive: bool = True,
               max_iterations: int = 100000000, tree_size: int = 100000):
    """
    Run the interactive puzzle solver.

    Args:
        json_filepath: Path to the puzzle JSON file
        delay: Delay in seconds between moves for visualization (ignored if interactive=True)
        interactive: If True, wait for keypress between moves; if False, use delay
        max_iterations: Maximum solver iterations before timeout (default: 100 million)
        tree_size: MCTS tree node cap per thread before compaction (default: 100000)
    """
    try:
        # 1. Load game from JSON
        play_area = PlayArea.load_from_json(json_filepath)
        ui = ConsoleUI()
        solver = Solver(play_area)

        # Keep a copy of the original puzzle to update only with revealed unknowns
        original_play_area = play_area.clone()

        # Track revealed unknowns for partial saving
        # Format: {bottle_number: {position: color}}
        revealed_unknowns = {}

        # 2. Display initial state and diagnostics
        ui.render_game(play_area, "Initial puzzle state")

        # Show puzzle diagnostics
        print()
        print("Puzzle Information:")
        print(f"  • Total bottles: {len(play_area.bottles)}")
        empty_count = sum(1 for b in play_area.bottles if len(b.contents) == 0)
        print(f"  • Empty bottles: {empty_count}")
        locked_count = len([b for b in play_area.bottles if play_area.is_bottle_locked(b.number)])
        if locked_count > 0:
            print(f"  • Locked bottles: {locked_count}")
            for bottle in play_area.bottles:
                if play_area.is_bottle_locked(bottle.number):
                    cond = play_area.lock_conditions.get(bottle.number)
                    if cond:
                        color_str = cond.color.name if cond.color else "ANY"
                        print(f"    - Bottle #{bottle.number}: Unlock after {cond.count} {color_str} completed")
        unknown_count = sum(b.contents.count(__import__('models').Color.UNKNOWN) for b in play_area.bottles)
        if unknown_count > 0:
            print(f"  • Unknown colors: {unknown_count}")
        print()
        ui.print_color_counts(play_area)
        print()

        if interactive:
            response = ui.prompt_continue()
            if response == 's':
                save_current_state(play_area, json_filepath, ui)
            elif response == 'e':
                # Launch editor and return
                from editor import run_editor
                run_editor(json_filepath)
                return
        else:
            print("Starting solver in auto mode...")
            print()

        # 3. Interactive solving loop
        move_fail_count = 0
        MAX_MOVE_FAILURES = 3

        def progress_callback(iteration, queue_size, explored, status):
            """Callback to show solver progress."""
            ui.show_progress(iteration, queue_size, explored, status)

        while not play_area.is_game_complete():
            if move_fail_count >= MAX_MOVE_FAILURES:
                break

            # 3a. Solve until unknown or completion
            print(f"Starting solver (max {max_iterations:,} iterations)...")
            moves, status = solver.solve_parallel(max_iterations=max_iterations,
                                                  tree_size=tree_size,
                                                  progress_callback=progress_callback)

            if status == "TIMEOUT" or status == "NO_SOLUTION" or (status == "BOTTLE_UNLOCKED" and not moves):
                if status == "TIMEOUT":
                    print(f"\nSolver timed out after {max_iterations:,} iterations — no solution found within budget.")
                elif status == "NO_SOLUTION":
                    print(f"\nSolver exhausted the search space — no solution exists.")
                print()

                # If NO_SOLUTION, offer to restore original puzzle and try again
                if status == "NO_SOLUTION":
                    restore_puzzle = ui.prompt_yes_no("Would you like to restore the puzzle to its original state and try again with different colors?")
                    if restore_puzzle:
                        # Restore from the original puzzle we cloned at start
                        play_area = original_play_area.clone()
                        solver = Solver(play_area)
                        ui.move_count = 0
                        move_history = []
                        print()
                        print("Puzzle restored to original state. Restarting solver...")
                        print()
                        continue  # Restart the solve loop

                # Offer to show best partial solution
                best_moves, completed_count, best_iteration = solver.get_best_partial_solution()
                if completed_count > 0:
                    print(f"The solver found a partial solution with {completed_count} bottle(s) completed.")
                    print(f"Best state was found at iteration {best_iteration:,}")

                    # Offer to save the state
                    save_state = ui.prompt_yes_no("Would you like to save this state to a file for debugging?")
                    if save_state:
                        # Apply moves to get to best state, starting from the current play_area
                        debug_area = play_area.clone()
                        for move in best_moves:
                            debug_area.apply_move(*move)

                        debug_filename = json_filepath.replace('.json', '_debug.json')
                        debug_area.save_to_json(debug_filename)
                        print(f"Saved debug state to: {debug_filename}")
                        print()

                    show_partial = ui.prompt_yes_no("Would you like to see the path to this state?")

                    if show_partial:
                        print()
                        print(f"Showing path to best state ({completed_count} bottles completed)...")
                        print()

                        # Execute the best partial solution moves
                        for i, move in enumerate(best_moves, 1):
                            from_idx, to_idx = move
                            success = play_area.apply_move(from_idx, to_idx)

                            if not success:
                                ui.show_message(f"Failed to apply move {i}: {from_idx} → {to_idx}", "error")
                                break

                            # Display the move
                            ui.render_move(from_idx, to_idx, play_area)

                            # Pause for visualization
                            if interactive:
                                response = ui.prompt_continue()
                                if response == 's':
                                    save_current_state(play_area, json_filepath, ui)
                                elif response == 'e':
                                    # Launch editor and return
                                    from editor import run_editor
                                    run_editor(json_filepath)
                                    return
                            else:
                                time.sleep(delay)

                        print()
                        ui.show_message(f"Reached best state with {completed_count} bottle(s) completed", "info")
                break

            if not moves:
                # No moves returned but not solved - something went wrong
                ui.show_message("Solver returned no moves", "error")
                break

            # 3b. Execute moves step by step with rewind support
            # History: list of (play_area_snapshot, move, move_count_snapshot) before each move
            move_history = []
            i = 0
            while i < len(moves):
                move = moves[i]
                from_idx, to_idx = move

                # Note which bottles are locked before this move (needed for BOTTLE_UNLOCKED detection)
                locked_before = {
                    j for j, b in enumerate(play_area.bottles)
                    if play_area.is_bottle_locked(b.number)
                }

                # Save snapshot before applying (for rewind)
                move_history.append((play_area.clone(), ui.move_count))

                # Apply the move
                success = play_area.apply_move(from_idx, to_idx)

                if not success:
                    move_history.pop()  # Remove the snapshot for failed move
                    move_fail_count += 1
                    ui.show_message(
                        f"Failed to apply move: {from_idx} → {to_idx} "
                        f"(attempt {move_fail_count}/{MAX_MOVE_FAILURES})",
                        "error"
                    )
                    # Resync solver with actual play_area state before retrying
                    solver.resume_from(play_area)
                    if move_fail_count >= MAX_MOVE_FAILURES:
                        ui.show_message("Too many move failures — stopping solver.", "error")
                    break

                # Move succeeded — reset failure counter
                move_fail_count = 0

                # Display the move
                ui.render_move(from_idx, to_idx, play_area)


                # Check if this was the last move and it revealed an unknown
                if i == len(moves) - 1 and status == "UNKNOWN_REVEALED":
                    if interactive:
                        print()
                    else:
                        time.sleep(delay)

                    from_bottle = play_area.bottles[from_idx]
                    to_bottle = play_area.bottles[to_idx]
                    bottle_with_unknown = None
                    bottle_idx_with_unknown = None

                    # Check if there's an unknown at the top of source bottle now
                    if from_bottle.get_top_color() == Color.UNKNOWN:
                        bottle_with_unknown = from_bottle
                        bottle_idx_with_unknown = from_idx
                    elif to_bottle.get_top_color() == Color.UNKNOWN:
                        # Unknown might have been transferred - check target
                        bottle_with_unknown = to_bottle
                        bottle_idx_with_unknown = to_idx

                    # Count consecutive unknowns from the top
                    unknown_count = 0
                    if bottle_with_unknown:
                        for j in range(len(bottle_with_unknown.contents) - 1, -1, -1):
                            if bottle_with_unknown.contents[j] == Color.UNKNOWN:
                                unknown_count += 1
                            else:
                                break

                    # 3c. Try to infer color from count constraints, else prompt
                    inferred = infer_unknown_color(play_area)
                    if inferred is not None:
                        ui.show_message(
                            f"Inferred: all unknowns must be {inferred.name} "
                            f"(only color with non-multiple-of-4 count)",
                            "info"
                        )
                        revealed_color, reveal_count = inferred, unknown_count
                    else:
                        revealed_color, reveal_count = ui.prompt_for_revealed_color(
                            bottle_with_unknown.number if bottle_with_unknown else None,
                            unknown_count
                        )

                    # Reveal the color(s) in the appropriate bottle
                    if bottle_idx_with_unknown is not None:
                        bottle_number = play_area.bottles[bottle_idx_with_unknown].number

                        # Track revelations for saving
                        if bottle_number not in revealed_unknowns:
                            revealed_unknowns[bottle_number] = {}

                        # Reveal from top downward in BOTH current play_area and original_play_area
                        start_position = len(play_area.bottles[bottle_idx_with_unknown].contents) - 1
                        for offset in range(reveal_count):
                            position = start_position - offset
                            if position >= 0 and play_area.bottles[bottle_idx_with_unknown].contents[position] == Color.UNKNOWN:
                                play_area.reveal_unknown(bottle_idx_with_unknown, position, revealed_color)

                                # Also update original play area with the revealed color
                                original_bottle = original_play_area.get_bottle_by_number(bottle_number)
                                if original_bottle and position < len(original_bottle.contents):
                                    original_bottle.contents[position] = revealed_color

                                # Track this revelation
                                revealed_unknowns[bottle_number][position] = revealed_color

                    if reveal_count > 1:
                        ui.show_message(f"Updated {reveal_count} UNKNOWNs to {revealed_color.name}", "success")
                    else:
                        ui.show_message(f"Updated UNKNOWN to {revealed_color.name}", "success")

                    # Save only the original puzzle with revealed unknowns to file
                    try:
                        original_play_area.save_to_json(json_filepath)
                        ui.show_message(f"Updated {json_filepath} with revealed colors", "success")
                    except Exception as e:
                        ui.show_message(f"Warning: Could not save to file: {e}", "warning")

                    if not interactive:
                        time.sleep(delay)

                    # 3d. Resume solving from updated state
                    solver.resume_from(play_area)
                    break

                # Check if this was the last move and it unlocked a bottle with unknown/empty contents
                if i == len(moves) - 1 and status == "BOTTLE_UNLOCKED":
                    if interactive:
                        print()
                    else:
                        time.sleep(delay)

                    # Find which bottle was just unlocked with all-unknown or empty contents
                    for bottle_idx, bottle in enumerate(play_area.bottles):
                        if bottle_idx not in locked_before:
                            continue
                        if play_area.is_bottle_locked(bottle.number):
                            continue
                        # Known-color slots are always visible — strip them from hidden_slots
                        bottle.hidden_slots = {
                            i for i in bottle.hidden_slots
                            if i < len(bottle.contents) and bottle.contents[i] == Color.UNKNOWN
                        }
                        original_bottle = original_play_area.get_bottle_by_number(bottle.number)
                        if original_bottle:
                            original_bottle.hidden_slots = bottle.hidden_slots.copy()
                        # This bottle was just unlocked — check if contents need to be revealed
                        is_all_unknown = len(bottle.contents) > 0 and all(
                            c == Color.UNKNOWN for c in bottle.contents
                        )
                        is_empty = len(bottle.contents) == 0
                        if not (is_all_unknown or is_empty):
                            continue

                        bottle_number = bottle.number

                        # Show inference hint if possible
                        inferred = infer_unknown_color(play_area)
                        if inferred is not None:
                            ui.show_message(
                                f"Hint: based on color counts, all unknowns should be {inferred.name}",
                                "info"
                            )

                        new_contents = ui.prompt_for_unlocked_bottle_contents(bottle_number, is_all_unknown)

                        # Update the bottle in the current play area
                        bottle.contents = new_contents
                        bottle.is_complete = False
                        # Auto-hide unknowns only if they are BELOW a known-color slot.
                        # Unknowns at or above the highest known slot remain accessible
                        # and will trigger UNKNOWN_REVEALED when reached by the solver.
                        highest_known_idx = max(
                            (i for i, c in enumerate(new_contents) if c != Color.UNKNOWN),
                            default=-1
                        )
                        bottle.hidden_slots = {
                            i for i, c in enumerate(new_contents)
                            if c == Color.UNKNOWN and i < highest_known_idx
                        }
                        if (len(new_contents) == 4 and len(set(new_contents)) == 1
                                and new_contents[0] != Color.UNKNOWN
                                and not bottle.hidden_slots):
                            bottle.is_complete = True
                        play_area.update_locks()

                        # Mirror update in original play area for saving
                        original_bottle = original_play_area.get_bottle_by_number(bottle_number)
                        if original_bottle:
                            original_bottle.contents = new_contents.copy()
                            original_bottle.hidden_slots = bottle.hidden_slots.copy()
                            original_bottle.is_complete = bottle.is_complete
                        original_play_area.update_locks()

                        # Track revelations for saving
                        if bottle_number not in revealed_unknowns:
                            revealed_unknowns[bottle_number] = {}
                        for pos, color in enumerate(new_contents):
                            revealed_unknowns[bottle_number][pos] = color

                        if new_contents:
                            ui.show_message(
                                f"Bottle #{bottle_number} contents set: "
                                + " ".join(c.name for c in new_contents),
                                "success"
                            )
                        else:
                            ui.show_message(f"Bottle #{bottle_number} confirmed empty", "success")

                        # Save original puzzle with new contents
                        try:
                            original_play_area.save_to_json(json_filepath)
                            ui.show_message(f"Updated {json_filepath}", "success")
                        except Exception as e:
                            ui.show_message(f"Warning: Could not save to file: {e}", "warning")

                        if not interactive:
                            time.sleep(delay)

                        # Resume solving from updated state
                        solver.resume_from(play_area)
                        break

                    break  # Break move loop to re-solve with updated state

                # Pause for visualization
                if interactive:
                    response = ui.prompt_continue(can_rewind=len(move_history) > 0)
                    if response == 's':
                        save_current_state(play_area, json_filepath, ui)
                    elif response == 'e':
                        # Launch editor and return
                        from editor import run_editor
                        run_editor(json_filepath)
                        return
                    elif response == 'b' and move_history:
                        # Rewind: restore previous state
                        prev_area, prev_move_count = move_history.pop()
                        play_area = prev_area
                        ui.move_count = prev_move_count
                        solver.resume_from(play_area)
                        ui.render_game(play_area, f"Rewound to move #{prev_move_count}")
                        # Step back so the next iteration replays this move
                        i -= 1
                        continue
                else:
                    time.sleep(delay)

                i += 1

            # Check if game is complete after this batch of moves
            if play_area.is_game_complete():
                break

        # 4. Show completion or final state
        if play_area.is_game_complete():
            ui.show_completion(ui.move_count)
            ui.render_game(play_area, "Final state - All bottles complete!")
        else:
            save_current_state(play_area, json_filepath, ui)

    except FileNotFoundError:
        print(f"Error: Puzzle file '{json_filepath}' not found")
    except ValueError as e:
        print(f"Error loading puzzle: {e}")
    except KeyboardInterrupt:
        print("\n\nSolver interrupted by user")
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
