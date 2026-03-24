#!/usr/bin/env python3
"""
Interactive Puzzle Editor for Water Sort Puzzle Solver.

Allows users to build puzzles from scratch, edit bottle contents and locks,
organize bottles into columns, and launch the solver.
"""

import readline
import re
import sys
import termios
import tty
from datetime import datetime
from typing import Optional, List

from play_area import PlayArea
from models import Color
from ui import ConsoleUI
from utils import parse_bottle_contents, color_from_string
from game_loop import run_solver




def _show_msg(show_feedback, ui, msg, level):
    """Show message using show_feedback if available, otherwise ui.show_message."""
    if show_feedback:
        show_feedback(msg, level)
    else:
        ui.show_message(msg, level)


def _read_key() -> str:
    """Read a single keypress from stdin."""
    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch
    except Exception:
        return ""


def _cursor_edit(play_area: PlayArea, ui: ConsoleUI):
    """Interactive cursor-based bottle editing mode with slot-level control."""
    # Get all bottles in a flat list (in row order if row layout, otherwise by number)
    if play_area.row_layout:
        bottles_in_order = []
        for row in play_area.row_layout:
            for bottle_num in row['bottle_indices']:
                bottle = play_area.get_bottle_by_number(bottle_num)
                if bottle:
                    bottles_in_order.append(bottle)
    else:
        bottles_in_order = sorted(play_area.bottles, key=lambda b: b.number)

    if not bottles_in_order:
        print("\n✗ No bottles to edit")
        return

    # Cursor position: (bottle_index, slot_index 0=top, 3=bottom)
    cursor_bottle = 0
    cursor_slot = 0

    COLOR_MNEMONICS = {'R': 'RED', 'P': 'PURPLE', 'A': 'GREY', 'G': 'GREEN',
                      'Y': 'YELLOW', 'O': 'ORANGE', 'U': 'BLUE', 'C': 'CYAN', '?': 'UNKNOWN', 'J': 'UNKNOWN'}

    def _render_with_cursor():
        """Render bottles with cursor using UI methods."""
        ui.clear_screen()
        print(f"\033[1m=== Cursor Edit Mode ==={ui.move_count}\033[0m")
        print("↑↓: slot | ←→: bottle | RPAGYOUCJ: set color | H: toggle hidden | SPACE: clear | i: help | q: quit")
        print()

        current_bottle = bottles_in_order[cursor_bottle]

        # Call the appropriate render method with cursor info
        if play_area.column_layout:
            ui._render_columns(play_area, current_bottle, cursor_slot)
        elif play_area.row_layout:
            ui._render_rows(play_area, current_bottle, cursor_slot)
        else:
            ui._render_bottles_row(play_area, current_bottle, cursor_slot)

    while True:
        _render_with_cursor()

        # Read keypress
        ch = _read_key()

        if ch == 'q':
            break
        elif ch == 'i':
            ui.clear_screen()
            print("=== Cursor Edit Mode Help ===\n")
            print("Navigation:")
            print("  ↑ ↓ (up/down arrows): Move between slots (top to bottom)")
            print("  ← → (left/right arrows): Move to adjacent bottle\n")
            print("Editing:")
            print("  R P A G Y O U C ?: Set selected slot to that color")
            print("  H / h: Toggle hidden on selected slot (<H = cursor on hidden slot)")
            print("  Space: Clear selected slot (also clears hidden flag)\n")
            print("Hidden slots:")
            print("  A hidden slot shows its color with purple borders.")
            print("  It is revealed automatically when the slot directly above it is freed.")
            print("  Consecutive same-color hidden slots reveal together.")
            print("  ? slots are marked hidden by default.\n")
            print("Other:")
            print("  i: This help screen")
            print("  q: Quit cursor edit mode\n")
            print("Press any key to continue...")
            sys.stdout.flush()
            _read_key()

        elif ch == '\x1b':
            # Escape sequence - handle arrow keys
            next1 = _read_key()
            if next1 == '[':
                next2 = _read_key()
                if next2 == 'D':  # Left arrow
                    cursor_bottle = (cursor_bottle - 1) % len(bottles_in_order)
                elif next2 == 'C':  # Right arrow
                    cursor_bottle = (cursor_bottle + 1) % len(bottles_in_order)
                elif next2 == 'A':  # Up arrow
                    cursor_slot = (cursor_slot + 1) % 4
                elif next2 == 'B':  # Down arrow
                    cursor_slot = (cursor_slot - 1) % 4

        elif ch in ('h', 'H'):
            # Toggle hidden on selected slot
            current_bottle = bottles_in_order[cursor_bottle]
            if cursor_slot < len(current_bottle.contents):
                if cursor_slot in current_bottle.hidden_slots:
                    current_bottle.hidden_slots.discard(cursor_slot)
                else:
                    current_bottle.hidden_slots.add(cursor_slot)

        elif ch == ' ':
            # Clear selected slot (and remove hidden flag)
            current_bottle = bottles_in_order[cursor_bottle]
            if cursor_slot < len(current_bottle.contents):
                current_bottle.contents.pop(cursor_slot)
                current_bottle.hidden_slots.discard(cursor_slot)
                # Shift down hidden slot indices above the removed slot
                current_bottle.hidden_slots = {
                    i if i < cursor_slot else i - 1
                    for i in current_bottle.hidden_slots
                    if i != cursor_slot
                }
            current_bottle.is_complete = False
            play_area.update_locks()

        elif ch.upper() in COLOR_MNEMONICS:
            # Set selected slot to that color
            color_name = COLOR_MNEMONICS[ch.upper()]
            color = color_from_string(color_name)
            current_bottle = bottles_in_order[cursor_bottle]

            # Extend contents if needed (filling gaps with UNKNOWN, auto-hidden)
            while len(current_bottle.contents) <= cursor_slot:
                gap_idx = len(current_bottle.contents)
                current_bottle.contents.append(Color.UNKNOWN)
                current_bottle.hidden_slots.add(gap_idx)

            current_bottle.contents[cursor_slot] = color
            current_bottle.is_complete = False
            # Auto-hide UNKNOWN slots when added
            if color == Color.UNKNOWN:
                current_bottle.hidden_slots.add(cursor_slot)
            play_area.update_locks()


def run_editor(puzzle_file: Optional[str] = None):
    """
    Main entry point for the interactive editor.

    Args:
        puzzle_file: Optional path to a puzzle JSON file to load and edit
    """
    ui = ConsoleUI()

    if puzzle_file:
        # Load existing puzzle
        try:
            play_area = PlayArea.load_from_json(puzzle_file)
            ui.show_message(f"Loaded puzzle from {puzzle_file}", "success")
            print()
        except Exception as e:
            ui.show_message(f"Error loading puzzle: {e}", "error")
            print()
            import sys
            sys.exit(1)
    else:
        # Create new empty puzzle
        play_area = PlayArea()

    _loop(play_area, ui, puzzle_file)


def _loop(play_area: PlayArea, ui: ConsoleUI, puzzle_file: Optional[str] = None):
    """Main editor loop."""
    ui.move_count = 0  # Reset move counter for editor display
    selected_column = None  # Track which column to add to in column mode
    selected_row = None  # Track which row to add to in row mode
    last_message = None  # Store last message to display
    show_help = [False]  # Use list so flag persists across loop iterations
    dirty = [False]  # True when there are unsaved changes

    # Default to row layout if no layout is set and puzzle is new (being created)
    # Only auto-set if no bottles exist yet (brand new puzzle)
    if not play_area.column_layout and not play_area.row_layout and not play_area.bottles:
        play_area.row_layout = [{'bottle_indices': []}]

    def show_feedback(msg: str, level: str = "info"):
        """Show and store feedback message."""
        nonlocal last_message
        last_message = (msg, level)

    while True:
        # Clear screen first
        ui.clear_screen()

        # Show last message/feedback if any (BEFORE game state)
        if last_message:
            msg, level = last_message
            if level == "success":
                print(f"✓ {msg}")
            elif level == "error":
                print(f"✗ {msg}")
            elif level == "warning":
                print(f"⚠ {msg}")
            else:
                print(f"ℹ {msg}")
            print()
            last_message = None

        # Then render game state with selection indicator
        selection_text = ""
        if selected_column is not None:
            selection_text = f" [Column {selected_column} selected]"
        elif selected_row is not None:
            selection_text = f" [Row {selected_row} selected]"
        header = f"=== Puzzle Editor ==={selection_text}"

        # Render without clearing (we already cleared above)
        print(f"\033[1m{header}\033[0m")
        print(f"Move #{ui.move_count}")
        print()

        # Use appropriate layout: column, row, or default horizontal
        if play_area.column_layout:
            ui._render_columns(play_area, show_gap_markers=True, show_col_numbers=True)
        elif play_area.row_layout:
            ui._render_rows(play_area, show_row_numbers=True)
        else:
            ui._render_bottles_row(play_area)

        print()
        ui.print_color_counts(play_area)
        print()

        # Show help text AFTER game area if requested
        if show_help[0]:
            _print_help()
            print()
            show_help[0] = False

        # Show command prompt with help hint
        try:
            user_input = input("> (type 'help') ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            if _handle_quit(ui, play_area, puzzle_file, dirty[0]):
                sys.exit(0)
            continue

        if not user_input:
            continue

        # Dispatch command
        try:
            if user_input.lower() in ('q', 'quit'):
                if _handle_quit(ui, play_area, puzzle_file, dirty[0]):
                    break
                # else: cancelled, stay in loop

            elif user_input.lower() == 'help':
                show_help[0] = True

            elif user_input.lower() == 'cedit':
                _cursor_edit(play_area, ui)
                show_feedback("Exited cursor edit mode", "info")
                dirty[0] = True

            elif user_input.lower() == 'play':
                _handle_play(play_area, ui, puzzle_file)
                break

            elif user_input.lower().startswith('save'):
                _handle_save(user_input, play_area, ui, show_feedback, puzzle_file)
                dirty[0] = False

            elif user_input.lower() == 'layout rows':
                _handle_layout_rows(play_area, ui, show_feedback)
                selected_column = None
                selected_row = None
                dirty[0] = True

            elif user_input.lower() == 'layout cols':
                _handle_layout_cols(play_area, ui, show_feedback)
                selected_column = None
                selected_row = None
                dirty[0] = True

            elif user_input.lower().startswith('select col '):
                parts = user_input.split()
                if len(parts) >= 3 and parts[2].isdigit():
                    col_num = int(parts[2])
                    if play_area.column_layout and 0 < col_num <= len(play_area.column_layout):
                        selected_column = col_num
                        show_feedback(f"Selected column {col_num}", "success")
                    else:
                        raise ValueError(f"Column {col_num} does not exist")
                else:
                    raise ValueError("Format: 'select col N' (e.g., 'select col 1')")

            elif user_input.lower().startswith('col ') and ' select' in user_input.lower():
                parts = user_input.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    col_num = int(parts[1])
                    if play_area.column_layout and 0 < col_num <= len(play_area.column_layout):
                        selected_column = col_num
                        show_feedback(f"Selected column {col_num}", "success")
                    else:
                        raise ValueError(f"Column {col_num} does not exist")
                else:
                    raise ValueError("Format: 'col N select' (e.g., 'col 1 select')")

            elif user_input.lower() == 'col add':
                _handle_col_add(play_area, ui, show_feedback)
                selected_column = len(play_area.column_layout) if play_area.column_layout else None
                dirty[0] = True

            elif user_input.lower().startswith('select row '):
                parts = user_input.split()
                if len(parts) >= 3 and parts[2].isdigit():
                    row_num = int(parts[2])
                    if play_area.row_layout and 0 < row_num <= len(play_area.row_layout):
                        selected_row = row_num
                        selected_column = None  # Clear column selection
                        show_feedback(f"Selected row {row_num}", "success")
                    else:
                        raise ValueError(f"Row {row_num} does not exist")
                else:
                    raise ValueError("Format: 'select row N' (e.g., 'select row 1')")

            elif user_input.lower().startswith('row ') and ' select' in user_input.lower():
                parts = user_input.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    row_num = int(parts[1])
                    if play_area.row_layout and 0 < row_num <= len(play_area.row_layout):
                        selected_row = row_num
                        selected_column = None  # Clear column selection
                        show_feedback(f"Selected row {row_num}", "success")
                    else:
                        raise ValueError(f"Row {row_num} does not exist")
                else:
                    raise ValueError("Format: 'row N select' (e.g., 'row 1 select')")

            elif user_input.lower() == 'row add':
                _handle_row_add(play_area, ui, show_feedback)
                selected_row = len(play_area.row_layout) if play_area.row_layout else None
                selected_column = None
                dirty[0] = True

            elif re.match(r'^col\s+\d+\s+gaps\s*$', user_input.lower()):
                _handle_col_gaps_display(user_input, play_area, ui, show_feedback)

            elif user_input.lower().startswith('col ') and ' gap' in user_input.lower():
                _handle_col_gap(user_input, play_area, ui, show_feedback)
                dirty[0] = True

            elif user_input.lower().startswith('col '):
                _handle_col_command(user_input, play_area, ui, show_feedback)
                dirty[0] = True

            elif user_input.lower().startswith('add '):
                _handle_add(user_input, play_area, ui, selected_column, selected_row, show_feedback)
                dirty[0] = True

            elif user_input.lower() in ('add',):
                _handle_add_wizard(play_area, ui, selected_column, selected_row, show_feedback)
                dirty[0] = True

            elif user_input.lower().startswith(('del ', 'remove ')):
                _handle_remove(user_input, play_area, ui, show_feedback)
                dirty[0] = True

            elif user_input.lower().startswith('move '):
                _handle_move(user_input, play_area, ui, show_feedback)
                dirty[0] = True

            elif user_input.lower() == 'renumber':
                _handle_renumber(play_area, ui, show_feedback)
                dirty[0] = True

            elif _is_quick_set(user_input):
                _handle_quick_set(user_input, play_area, ui, show_feedback)
                dirty[0] = True

            elif user_input.isdigit():
                _handle_bottle_wizard(int(user_input), play_area, ui, show_feedback)
                dirty[0] = True

            else:
                show_feedback(f"Unknown command: {user_input}. Type 'help' for commands.", "error")

        except ValueError as e:
            show_feedback(f"Error: {e}", "error")
        except Exception as e:
            show_feedback(f"Unexpected error: {e}", "error")


def _is_quick_set(user_input: str) -> bool:
    """Check if input matches quick-set pattern: digit + mnemonics."""
    return bool(re.match(r'^(\d+)([RPAGYOUCBJrpagyoucbj?]+)$', user_input))


def _handle_quick_set(user_input: str, play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle quick-set: e.g., '1RRRG' sets bottle 1 to RED/RED/RED/GREEN."""
    match = re.match(r'^(\d+)([RPAGYOUCBJrpagyoucbj?]+)$', user_input)
    if not match:
        return

    bottle_number = int(match.group(1))
    mnemonic_str = match.group(2)

    # Parse contents
    try:
        colors = parse_bottle_contents(mnemonic_str)
    except ValueError as e:
        raise ValueError(f"Invalid color mnemonics: {e}")

    # Check if bottle exists
    if play_area.get_bottle_by_number(bottle_number) is None:
        raise ValueError(f"Bottle {bottle_number} does not exist")

    # Set contents
    play_area.set_bottle_contents(bottle_number, colors)
    msg = f"Bottle #{bottle_number} contents updated"
    if show_feedback:
        show_feedback(msg, "success")
    else:
        _show_msg(show_feedback, ui, msg, "success")


def _handle_bottle_wizard(bottle_number: int, play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Interactive wizard for editing a single bottle."""
    bottle = play_area.get_bottle_by_number(bottle_number)
    if bottle is None:
        raise ValueError(f"Bottle {bottle_number} does not exist")

    is_locked = play_area.is_bottle_locked(bottle_number)

    # Show current state
    print()
    print(f"Editing Bottle #{bottle_number}")
    current_contents = ''.join([c.name[0] for c in bottle.contents])
    if current_contents:
        print(f"  Current contents: {current_contents}")
    else:
        print(f"  Current contents: (empty)")

    if is_locked:
        lock = play_area.lock_conditions[bottle_number]
        color_str = 'ANY' if lock.color is None else lock.color.name
        print(f"  Current lock: {lock.count} {color_str}")
    else:
        print(f"  Current lock: (none)")

    print()

    # Prompt for contents
    while True:
        user_input = input("Contents (mnemonics, empty to keep): ").strip()
        if not user_input:
            break

        try:
            colors = parse_bottle_contents(user_input)
            play_area.set_bottle_contents(bottle_number, colors)
            _show_msg(show_feedback, ui, f"Bottle #{bottle_number} contents updated", "success")
            break
        except ValueError as e:
            print(f"Invalid input: {e}. Try again.")

    # Prompt for lock
    while True:
        user_input = input(
            "Lock? (e.g. '2 RED' or '3 ANY', empty to keep, 'none' to clear): "
        ).strip()

        if not user_input:
            break

        if user_input.lower() == 'none':
            play_area.remove_lock(bottle_number)
            _show_msg(show_feedback, ui, f"Bottle #{bottle_number} unlocked", "success")
            break

        try:
            count, color = _parse_lock_input(user_input)
            play_area.set_lock(bottle_number, count, color)
            color_str = 'ANY' if color is None else color.name
            _show_msg(show_feedback, ui, f"Bottle #{bottle_number} locked: {count} {color_str}", "success")
            break
        except ValueError as e:
            print(f"Invalid lock: {e}. Try again.")


def _parse_lock_input(user_input: str) -> tuple:
    """
    Parse lock input like '2 RED' or '3 ANY'.

    Returns:
        (count, color) where color is Color enum or None for ANY
    """
    parts = user_input.split()
    if len(parts) != 2:
        raise ValueError("Format: 'COUNT COLOR' (e.g., '2 RED' or '3 ANY')")

    try:
        count = int(parts[0])
    except ValueError:
        raise ValueError("Count must be a number")

    if count < 0:
        raise ValueError("Count must be non-negative")

    color_str = parts[1].upper()
    if color_str == 'ANY':
        return count, None
    else:
        try:
            color = color_from_string(color_str)
            return count, color
        except ValueError:
            raise ValueError(f"Invalid color: {color_str}")


def _handle_add(user_input: str, play_area: PlayArea, ui: ConsoleUI, selected_column: Optional[int] = None, selected_row: Optional[int] = None, show_feedback=None):
    """Handle 'add MNEMONICS' command — also prompts for optional lock."""
    parts = user_input.split(maxsplit=1)
    if len(parts) < 2:
        raise ValueError("Format: 'add MNEMONICS' (e.g., 'add RRRG')")

    mnemonic_str = parts[1].strip()
    try:
        colors = parse_bottle_contents(mnemonic_str)
    except ValueError as e:
        raise ValueError(f"Invalid color mnemonics: {e}")

    number = play_area.add_new_bottle(colors)
    bottle = play_area.get_bottle_by_number(number)
    bottle.hidden_slots = {i for i, c in enumerate(colors) if c == Color.UNKNOWN}

    # Add to selected row or column if in layout mode
    if play_area.row_layout:
        if selected_row is not None and 0 < selected_row <= len(play_area.row_layout):
            row_idx = selected_row - 1
            play_area.row_layout[row_idx]['bottle_indices'].append(number)
        elif play_area.row_layout:
            # Default to last row if no selection
            play_area.row_layout[-1]['bottle_indices'].append(number)
    elif play_area.column_layout:
        if selected_column is not None and 0 < selected_column <= len(play_area.column_layout):
            col_idx = selected_column - 1
            play_area.column_layout[col_idx]['bottle_indices'].append(number)
        elif play_area.column_layout:
            # Default to last column if no selection
            play_area.column_layout[-1]['bottle_indices'].append(number)

    _show_msg(show_feedback, ui, f"Bottle #{number} added with contents", "success")


def _handle_add_wizard(play_area: PlayArea, ui: ConsoleUI, selected_column: Optional[int] = None, selected_row: Optional[int] = None, show_feedback=None):
    """Handle 'add' command with wizard."""
    print()
    print("Add new bottle")
    print()

    # --- Contents ---
    while True:
        user_input = input("Contents (mnemonics, empty for empty bottle): ").strip()
        try:
            if user_input:
                colors = parse_bottle_contents(user_input)
            else:
                colors = []
            number = play_area.add_new_bottle(colors)
            bottle = play_area.get_bottle_by_number(number)
            bottle.hidden_slots = {i for i, c in enumerate(colors) if c == Color.UNKNOWN}

            # Add to selected row or column if in layout mode
            if play_area.row_layout:
                if selected_row is not None and 0 < selected_row <= len(play_area.row_layout):
                    row_idx = selected_row - 1
                    play_area.row_layout[row_idx]['bottle_indices'].append(number)
                elif play_area.row_layout:
                    play_area.row_layout[-1]['bottle_indices'].append(number)
            elif play_area.column_layout:
                if selected_column is not None and 0 < selected_column <= len(play_area.column_layout):
                    col_idx = selected_column - 1
                    play_area.column_layout[col_idx]['bottle_indices'].append(number)
                elif play_area.column_layout:
                    play_area.column_layout[-1]['bottle_indices'].append(number)
            break
        except ValueError as e:
            print(f"Invalid input: {e}. Try again.")

    # --- Lock (optional) ---
    while True:
        lock_input = input("Lock? (e.g. '2 RED' or '3 ANY', empty to skip): ").strip()
        if not lock_input:
            break
        try:
            count, color = _parse_lock_input(lock_input)
            play_area.set_lock(number, count, color)
            color_str = 'ANY' if color is None else color.name
            _show_msg(show_feedback, ui, f"Bottle #{number} added with lock: {count} {color_str}", "success")
            return
        except ValueError as e:
            print(f"Invalid lock: {e}. Try again.")

    _show_msg(show_feedback, ui, f"Bottle #{number} added", "success")


def _handle_remove(user_input: str, play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle 'del N' or 'remove N' command."""
    parts = user_input.split()
    if len(parts) < 2:
        raise ValueError("Format: 'del N' or 'remove N'")

    try:
        bottle_number = int(parts[1])
    except ValueError:
        raise ValueError("Bottle number must be an integer")

    if play_area.get_bottle_by_number(bottle_number) is None:
        raise ValueError(f"Bottle {bottle_number} does not exist")

    play_area.remove_bottle(bottle_number)
    _show_msg(show_feedback, ui, f"Bottle #{bottle_number} removed", "success")


def _handle_move(user_input: str, play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle 'move N col M' or 'move N row M' command."""
    parts = user_input.split()
    if len(parts) < 4 or parts[2] not in ('col', 'row'):
        raise ValueError("Format: 'move N col M' or 'move N row M' (e.g., 'move 0 col 2' or 'move 0 row 1')")

    try:
        bottle_number = int(parts[1])
        target_number = int(parts[3])
    except ValueError:
        raise ValueError("Bottle and target numbers must be integers")

    if play_area.get_bottle_by_number(bottle_number) is None:
        raise ValueError(f"Bottle {bottle_number} does not exist")

    layout_type = parts[2]

    if layout_type == 'col':
        if not play_area.column_layout:
            raise ValueError("No column layout active. Use 'layout cols' first.")

        col_idx = target_number - 1
        if col_idx < 0 or col_idx >= len(play_area.column_layout):
            raise ValueError(f"Column {target_number} does not exist")

        # Remove bottle from its current column
        for column in play_area.column_layout:
            if bottle_number in column['bottle_indices']:
                column['bottle_indices'].remove(bottle_number)

        # Add to target column
        play_area.column_layout[col_idx]['bottle_indices'].append(bottle_number)
        _show_msg(show_feedback, ui, f"Bottle #{bottle_number} moved to column {target_number}", "success")

    elif layout_type == 'row':
        if not play_area.row_layout:
            raise ValueError("No row layout active. Use 'layout rows' first.")

        row_idx = target_number - 1
        if row_idx < 0 or row_idx >= len(play_area.row_layout):
            raise ValueError(f"Row {target_number} does not exist")

        # Remove bottle from its current row
        for row in play_area.row_layout:
            if bottle_number in row['bottle_indices']:
                row['bottle_indices'].remove(bottle_number)

        # Add to target row
        play_area.row_layout[row_idx]['bottle_indices'].append(bottle_number)

        # Renumber bottles sequentially by row
        play_area.renumber_bottles_by_rows()

        _show_msg(show_feedback, ui, f"Bottle #{bottle_number} moved to row {target_number} (bottles renumbered)", "success")


def _handle_renumber(play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle 'renumber' command - renumber bottles by current layout order."""
    if play_area.column_layout:
        play_area.renumber_bottles_by_columns()
        _show_msg(show_feedback, ui, "Bottles renumbered sequentially by column", "success")
    elif play_area.row_layout:
        play_area.renumber_bottles_by_rows()
        _show_msg(show_feedback, ui, "Bottles renumbered sequentially by row", "success")
    else:
        raise ValueError("No layout active. Use 'layout rows' or 'layout cols' first.")


def _handle_layout_cols(play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle 'layout cols' command."""
    bottle_numbers = [b.number for b in play_area.bottles]
    if play_area.column_layout is None:
        # Create one column with all bottles
        play_area.column_layout = [{
            'skew': 0.0,
            'gaps': [0.0] * len(bottle_numbers),
            'bottle_indices': bottle_numbers
        }]
        play_area.row_layout = None
        _show_msg(show_feedback, ui, "Column layout created with 1 column", "success")
    else:
        _show_msg(show_feedback, ui, "Already in column layout mode", "info")


def _handle_col_add(play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle 'col add' command - create empty column."""
    if not play_area.column_layout:
        play_area.column_layout = []

    play_area.column_layout.append({
        'skew': 0.0,
        'gaps': [],
        'bottle_indices': []
    })
    col_num = len(play_area.column_layout)
    _show_msg(show_feedback, ui, f"Column {col_num} created", "success")


def _handle_col_gaps_display(user_input: str, play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle 'col N gaps' — show all gap values for a column with edit hints."""
    parts = user_input.split()
    if len(parts) < 2 or not parts[1].isdigit():
        raise ValueError("Format: 'col N gaps'")

    col_num = int(parts[1])
    if not play_area.column_layout or col_num < 1 or col_num > len(play_area.column_layout):
        raise ValueError(f"Column {col_num} does not exist")

    col_idx = col_num - 1
    column = play_area.column_layout[col_idx]
    bottle_indices = column['bottle_indices']
    gaps = column.get('gaps', [])

    print()
    print(f"Column {col_num} gaps  ({len(bottle_indices)} bottles, skew={column.get('skew', 0.0):.1f}):")
    print()

    def gap_val(i):
        return gaps[i] if i < len(gaps) else 0.0

    if not bottle_indices:
        print("  (no bottles)")
    else:
        g0 = gap_val(0)
        tag = " ← set with:  col {col_num} gap 0 VALUE".format(col_num=col_num)
        print(f"  Before #{bottle_indices[0]}: {g0:.2f}{tag}")
        for pos, btn in enumerate(bottle_indices[:-1]):
            next_btn = bottle_indices[pos + 1]
            g = gap_val(pos + 1)
            tag = f" ← set with:  col {col_num} gap {pos + 1} VALUE"
            print(f"  Between #{btn} and #{next_btn}: {g:.2f}{tag}")
    print()


def _handle_col_gap(user_input: str, play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle 'col N gap M [VALUE]' commands to set/view gaps between bottles in a column."""
    parts = user_input.split()

    # Format: col N gap M [VALUE]
    # col 1 gap 0 0.5  -> set gap before bottle 0 in column 1 to 0.5
    # col 1 gap 0      -> show gap before bottle 0 in column 1

    if len(parts) < 4:
        raise ValueError("Format: 'col N gap M [VALUE]' (e.g., 'col 1 gap 0 0.5' or 'col 1 gap 0')")

    try:
        col_num = int(parts[1])
        bottle_idx = int(parts[3])
    except (ValueError, IndexError):
        raise ValueError("Column number and bottle index must be integers")

    if not play_area.column_layout or col_num < 1 or col_num > len(play_area.column_layout):
        raise ValueError(f"Column {col_num} does not exist")

    col_idx = col_num - 1
    column = play_area.column_layout[col_idx]

    # Initialize gaps if not present
    if 'gaps' not in column:
        column['gaps'] = [0.0] * len(column['bottle_indices'])

    if bottle_idx < 0 or bottle_idx > len(column['bottle_indices']):
        raise ValueError(f"Bottle index {bottle_idx} out of range (0-{len(column['bottle_indices'])})")

    if len(parts) > 4:
        # Set gap value
        try:
            value = float(parts[4])
        except (ValueError, IndexError):
            raise ValueError("Gap value must be a number")

        # Ensure gaps array is large enough
        while len(column['gaps']) <= bottle_idx:
            column['gaps'].append(0.0)

        column['gaps'][bottle_idx] = value
        _show_msg(show_feedback, ui, f"Column {col_num}: gap before bottle {bottle_idx} set to {value}", "success")
    else:
        # Show current gap value
        if bottle_idx < len(column['gaps']):
            current_gap = column['gaps'][bottle_idx]
            _show_msg(show_feedback, ui, f"Column {col_num}: gap before bottle {bottle_idx} = {current_gap}", "info")
        else:
            _show_msg(show_feedback, ui, f"Column {col_num}: gap before bottle {bottle_idx} not set (default: 0.0)", "info")


def _handle_col_command(user_input: str, play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle 'col N add MNEMONICS' or 'col N add' commands."""
    parts = user_input.split(maxsplit=3)

    if len(parts) < 3 or parts[2] != 'add':
        raise ValueError("Format: 'col N add [MNEMONICS]' (e.g., 'col 1 add RRRG')")

    try:
        col_number = int(parts[1])
    except ValueError:
        raise ValueError("Column number must be an integer")

    if not play_area.column_layout:
        play_area.column_layout = []

    # Ensure column exists
    while len(play_area.column_layout) < col_number:
        play_area.column_layout.append({'skew': 0.0, 'gaps': [], 'bottle_indices': []})

    col_idx = col_number - 1

    # Parse optional contents
    if len(parts) > 3:
        mnemonic_str = parts[3]
        try:
            colors = parse_bottle_contents(mnemonic_str)
        except ValueError as e:
            raise ValueError(f"Invalid color mnemonics: {e}")
    else:
        colors = []

    # Add bottle to column
    number = play_area.add_new_bottle(colors)
    bottle = play_area.get_bottle_by_number(number)
    bottle.hidden_slots = {i for i, c in enumerate(colors) if c == Color.UNKNOWN}
    play_area.column_layout[col_idx]['bottle_indices'].append(number)
    # Add corresponding gap entry (default to 0.0)
    play_area.column_layout[col_idx]['gaps'].append(0.0)
    _show_msg(show_feedback, ui, f"Bottle #{number} added to column {col_number}", "success")


def _handle_layout_rows(play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle 'layout rows' command."""
    if play_area.row_layout is None:
        # Create one row with all bottles
        play_area.row_layout = [{
            'bottle_indices': [b.number for b in play_area.bottles]
        }]
        play_area.column_layout = None
        _show_msg(show_feedback, ui, "Row layout created with 1 row", "success")
    else:
        # Already in row layout, just reset to single row
        play_area.row_layout = [{
            'bottle_indices': [b.number for b in play_area.bottles]
        }]
        play_area.column_layout = None
        _show_msg(show_feedback, ui, "Row layout reset to 1 row", "success")


def _handle_row_add(play_area: PlayArea, ui: ConsoleUI, show_feedback=None):
    """Handle 'row add' command - create empty row."""
    if not play_area.row_layout:
        play_area.row_layout = []
        play_area.column_layout = None

    play_area.row_layout.append({
        'bottle_indices': []
    })
    row_num = len(play_area.row_layout)
    _show_msg(show_feedback, ui, f"Row {row_num} created", "success")


def _handle_save(user_input: str, play_area: PlayArea, ui: ConsoleUI, show_feedback=None, puzzle_file: Optional[str] = None):
    """Handle 'save [filename]' command."""
    parts = user_input.split(maxsplit=1)

    if len(parts) > 1:
        # Filename explicitly provided
        filename = parts[1].strip()
    elif puzzle_file:
        # No filename provided, but a puzzle was loaded - ask if they want to overwrite
        print()
        response = input(f"Save to original file '{puzzle_file}'? (y/n): ").strip().lower()
        if response in ('y', 'yes'):
            filename = puzzle_file
        else:
            # Generate default filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"puzzle_{timestamp}.json"
            print(f"Saving to new file: {filename}")
    else:
        # No filename provided and no puzzle was loaded - use default timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"puzzle_{timestamp}.json"

    try:
        play_area.save_to_json(filename)
        _show_msg(show_feedback, ui, f"Puzzle saved to {filename}", "success")
    except Exception as e:
        raise ValueError(f"Failed to save: {e}")


def _handle_play(play_area: PlayArea, ui: ConsoleUI, show_feedback=None, puzzle_file: Optional[str] = None):
    """Handle 'play' command - launch solver."""
    if not play_area.bottles:
        raise ValueError("Cannot play: puzzle has no bottles")

    # Check if puzzle is solvable (has at least one non-empty bottle)
    has_content = any(not b.is_empty() for b in play_area.bottles)
    if not has_content:
        raise ValueError("Cannot play: puzzle has no contents")

    print()
    print("Launching solver...")
    print()

    import os
    if puzzle_file:
        # Save current editor state to the puzzle file and run solver directly against it,
        # so reveals and unlocks are persisted to the original file in real time.
        play_area.save_to_json(puzzle_file)
        try:
            run_solver(puzzle_file, delay=0.5, interactive=True, max_iterations=10000000)
        except Exception as e:
            _show_msg(show_feedback, ui, f"Solver error: {e}", "error")
    else:
        # No file yet — use a temp file for the session
        temp_filename = ".puzzle_temp.json"
        play_area.save_to_json(temp_filename)
        try:
            run_solver(temp_filename, delay=0.5, interactive=True, max_iterations=10000000)
        except Exception as e:
            _show_msg(show_feedback, ui, f"Solver error: {e}", "error")
        finally:
            if os.path.exists(temp_filename):
                os.remove(temp_filename)


def _handle_quit(ui: ConsoleUI, play_area: PlayArea = None, puzzle_file: Optional[str] = None, dirty: bool = False):
    """Handle quit command. Returns True if quit confirmed, False if cancelled."""
    if dirty and play_area is not None:
        print()
        response = input("You have unsaved changes. Save before quitting? (y/n/cancel): ").strip().lower()
        if response in ('y', 'yes'):
            _handle_save('save', play_area, ui, puzzle_file=puzzle_file)
        elif response not in ('n', 'no'):
            return False  # cancel
    print()
    print("Exiting editor.")
    return True


def _print_help():
    """Print command reference."""
    print()
    print("=== Editor Commands ===")
    print()
    print("Bottle Operations:")
    print("  1RRRG          Quick-set bottle 1 to RED/RED/RED/GREEN")
    print("  1              Edit bottle 1 (contents + lock wizard)")
    print("  add RRRG       Add new bottle with contents")
    print("  add            Add new bottle (with wizard)")
    print("  del N          Delete bottle N")
    print("  remove N       Delete bottle N (alias)")
    print()
    print("Layout Management:")
    print("  layout rows    Switch to row layout (organize bottles by rows)")
    print("  layout cols    Switch to column layout (organize bottles by columns)")
    print()
    print("Row Management:")
    print("  row add        Create a new empty row (and select it)")
    print("  select row N   Select row N for adding (e.g., 'select row 2')")
    print("  row N select   Select row N (alias, e.g., 'row 2 select')")
    print()
    print("Column Management:")
    print("  col add        Create a new empty column (and select it)")
    print("  select col N   Select column N for adding (e.g., 'select col 2')")
    print("  col N select   Select column N (alias, e.g., 'col 2 select')")
    print("  col N add RRRG Add bottle with contents to column N")
    print("  col N gaps     Show all gaps for column N with edit hints")
    print("  col N gap M V  Set gap before bottle at position M (0=before 1st, 1=between 1st&2nd…)")
    print("  col N gap M    Show current gap at position M")
    print("  move N col M   Move bottle N to column M")
    print("  move N row M   Move bottle N to row M (auto-renumbers)")
    print("  renumber       Renumber all bottles sequentially by current layout order")
    print()
    print("Puzzle Management:")
    print("  save [FILE]    Save puzzle to JSON file (or ask to overwrite original)")
    print("  play           Launch solver with current puzzle")
    print()
    print("Other:")
    print("  cedit          Cursor-based editing mode (arrow keys to move, mnemonics to set colors)")
    print("  help           Show this help")
    print("  q / quit       Exit editor")
    print()
