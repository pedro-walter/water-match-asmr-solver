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

def run_solver(json_filepath: str, delay: float = 0.5, interactive: bool = True,
               max_iterations: int = 10000000):
    """
    Run the interactive puzzle solver.

    Args:
        json_filepath: Path to the puzzle JSON file
        delay: Delay in seconds between moves for visualization (ignored if interactive=True)
        interactive: If True, wait for keypress between moves; if False, use delay
        max_iterations: Maximum solver iterations before timeout (default: 10 million)
    """
    try:
        # 1. Load game from JSON
        play_area = PlayArea.load_from_json(json_filepath)
        ui = ConsoleUI()
        solver = Solver(play_area)

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

        if interactive:
            response = ui.prompt_continue()
            if response == 's':
                save_current_state(play_area, json_filepath, ui)
        else:
            print("Starting solver in auto mode...")
            print()

        # 3. Interactive solving loop
        def progress_callback(iteration, queue_size, explored, status):
            """Callback to show solver progress."""
            ui.show_progress(iteration, queue_size, explored, status)

        while not play_area.is_game_complete():
            # 3a. Solve until unknown or completion
            print(f"Starting solver (max {max_iterations:,} iterations)...")
            moves, status = solver.solve_until_unknown(max_iterations=max_iterations,
                                                      progress_callback=progress_callback)

            if status == "TIMEOUT" or status == "NO_SOLUTION":
                # Detailed message already shown by progress_callback
                # Don't clear screen - let user see the error message
                print()

                # Offer to show best partial solution
                best_moves, completed_count, best_iteration = solver.get_best_partial_solution()
                if completed_count > 0:
                    print(f"The solver found a partial solution with {completed_count} bottle(s) completed.")
                    print(f"Best state was found at iteration {best_iteration:,}")

                    # Offer to save the state
                    save_state = ui.prompt_yes_no("Would you like to save this state to a file for debugging?")
                    if save_state:
                        # Apply moves to get to best state
                        debug_area = PlayArea.load_from_json(json_filepath)
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
                            else:
                                time.sleep(delay)

                        print()
                        ui.show_message(f"Reached best state with {completed_count} bottle(s) completed", "info")
                break

            if not moves:
                # No moves returned but not solved - something went wrong
                ui.show_message("Solver returned no moves", "error")
                break

            # 3b. Execute moves step by step
            for i, move in enumerate(moves):
                from_idx, to_idx = move

                # Apply the move
                success = play_area.apply_move(from_idx, to_idx)

                if not success:
                    ui.show_message(f"Failed to apply move: {from_idx} → {to_idx}", "error")
                    break

                # Display the move
                ui.render_move(from_idx, to_idx, play_area)

                # Check if this was the last move and it revealed an unknown
                if i == len(moves) - 1 and status == "UNKNOWN_REVEALED":
                    if interactive:
                        print()
                    else:
                        time.sleep(delay)

                    # Find which bottle had the unknown revealed
                    # The unknown would be at the top of the source bottle after transfer
                    # Or newly revealed in the source bottle
                    from_bottle = play_area.bottles[from_idx]
                    to_bottle = play_area.bottles[to_idx]
                    bottle_with_unknown = None
                    bottle_idx_with_unknown = None

                    # Check if there's an unknown at the top of source bottle now
                    from models import Color
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
                        for i in range(len(bottle_with_unknown.contents) - 1, -1, -1):
                            if bottle_with_unknown.contents[i] == Color.UNKNOWN:
                                unknown_count += 1
                            else:
                                break

                    # 3c. Prompt user for revealed color(s)
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

                        # Reveal from top downward
                        start_position = len(play_area.bottles[bottle_idx_with_unknown].contents) - 1
                        for offset in range(reveal_count):
                            position = start_position - offset
                            if position >= 0 and play_area.bottles[bottle_idx_with_unknown].contents[position] == Color.UNKNOWN:
                                play_area.reveal_unknown(bottle_idx_with_unknown, position, revealed_color)
                                # Track this revelation
                                revealed_unknowns[bottle_number][position] = revealed_color

                    if reveal_count > 1:
                        ui.show_message(f"Updated {reveal_count} UNKNOWNs to {revealed_color.name}", "success")
                    else:
                        ui.show_message(f"Updated UNKNOWN to {revealed_color.name}", "success")

                    # Save only the revealed unknowns back to the original JSON file
                    try:
                        save_revealed_unknowns(json_filepath, revealed_unknowns, ui)
                    except Exception as e:
                        ui.show_message(f"Warning: Could not save to file: {e}", "warning")

                    if not interactive:
                        time.sleep(delay)

                    # 3d. Resume solving from updated state
                    solver.resume_from(play_area)
                    break

                # Pause for visualization
                if interactive:
                    response = ui.prompt_continue()
                    if response == 's':
                        save_current_state(play_area, json_filepath, ui)
                else:
                    time.sleep(delay)

            # Check if game is complete after this batch of moves
            if play_area.is_game_complete():
                break

        # 4. Show completion or final state
        if play_area.is_game_complete():
            ui.show_completion(ui.move_count)
            ui.render_game(play_area, "Final state - All bottles complete!")
        # else:
        #     ui.render_game(play_area, "Current state")

        # 5. Optionally save final state
        # play_area.save_to_json("puzzle_solved.json")

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
