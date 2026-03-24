import os
import sys
from typing import List, Tuple
from models import Color, Bottle
from play_area import PlayArea
from utils import color_from_string, COLOR_MNEMONICS

# ANSI color codes
COLOR_CODES = {
    Color.RED: "\033[91m",
    Color.PURPLE: "\033[95m",
    Color.GREY: "\033[90m",
    Color.GREEN: "\033[92m",
    Color.YELLOW: "\033[93m",
    Color.ORANGE: "\033[38;5;208m",
    Color.BLUE: "\033[94m",
    Color.CYAN: "\033[96m",
    Color.UNKNOWN: "\033[37m",  # White
}

RESET = "\033[0m"
BOLD = "\033[1m"

# Highlight colors for move source/destination bottles
HIGHLIGHT_GREEN = "\033[92m"  # Source bottle border
HIGHLIGHT_RED = "\033[91m"    # Destination bottle border

# Color symbols using colored blocks
COLOR_SYMBOLS = {
    Color.RED: "🟥",
    Color.PURPLE: "🟪",
    Color.GREY: "⬜",
    Color.GREEN: "🟩",
    Color.YELLOW: "🟨",
    Color.ORANGE: "🟧",
    Color.BLUE: "🟦",
    Color.CYAN: "🩵 ",  # Cyan heart (no cyan square emoji exists)
    Color.UNKNOWN: "❓",
}

HIDDEN_BORDER = "\033[95m"  # Magenta/purple for hidden slot wall indicators


class ConsoleUI:
    """Console UI for displaying the water sort puzzle."""

    def __init__(self):
        self.move_count = 0
        self.bottle_width = 8  # Width of a bottle display including borders
        self.bottle_height = 8  # Height of a bottle display (label + borders + 4 content + blank separator)

    def clear_screen(self):
        """Clear the terminal screen."""
        os.system('clear' if os.name != 'nt' else 'cls')

    def render_game(self, play_area: PlayArea, message: str = "",
                    highlight_from: int = None, highlight_to: int = None):
        """
        Display the complete game state.

        Args:
            play_area: The PlayArea to render
            message: Optional message to display
            highlight_from: Bottle index to highlight green (source)
            highlight_to: Bottle index to highlight red (destination)
        """
        self.clear_screen()

        print(f"{BOLD}=== Water Sort Puzzle ==={RESET}")
        print(f"Move #{self.move_count}")
        print()

        if message:
            print(message)
            print()

        # Build highlight set: index -> ANSI color code
        highlights = {}
        if highlight_from is not None:
            highlights[highlight_from] = HIGHLIGHT_GREEN
        if highlight_to is not None:
            highlights[highlight_to] = HIGHLIGHT_RED

        # Use appropriate layout: column, row, or default horizontal
        if play_area.column_layout:
            self._render_columns(play_area, highlights=highlights)
        elif play_area.row_layout:
            self._render_rows(play_area, highlights=highlights)
        else:
            self._render_bottles_row(play_area, highlights=highlights)

        print()

    def _render_columns(self, play_area: PlayArea, cursor_bottle=None, cursor_slot=None, show_gap_markers=False, highlights=None, show_col_numbers=False):
        """Render bottles in vertical column layout with skew offsets."""
        if not play_area.column_layout:
            return

        # Calculate positions for each bottle
        bottle_positions = {}  # Maps bottle_number to (row_start, col_index)
        max_row = 0
        # gap_markers: grid_row -> list of (col_idx, gap_value) for show_gap_markers mode
        gap_markers = {}

        for col_idx, column_info in enumerate(play_area.column_layout):
            skew = column_info['skew']
            bottle_indices = column_info['bottle_indices']
            gaps = column_info.get('gaps', [])

            # skew of 1.0 = one full bottle height of vertical offset
            skew_offset = round(skew * self.bottle_height)

            for bottle_position, bottle_num in enumerate(bottle_indices):
                # Calculate cumulative gap offset (sum of all gaps before and at this bottle position)
                # gap of 1.0 = exactly one bottle height; use round() so 0.5 stays a clean half
                gap_offset = 0
                for i in range(bottle_position + 1):
                    if i < len(gaps):
                        gap_offset += round(gaps[i] * self.bottle_height)

                # Each bottle takes bottle_height rows, bottles stack downward
                row_start = skew_offset + gap_offset + (bottle_position * self.bottle_height)
                bottle_positions[bottle_num] = (row_start, col_idx)
                max_row = max(max_row, row_start + self.bottle_height)

                # Track gap marker for the gap immediately before this bottle
                if show_gap_markers and bottle_position < len(gaps):
                    gap_val = gaps[bottle_position]
                    gap_rows = round(gap_val * self.bottle_height)
                    if gap_rows > 0:
                        gap_start = row_start - gap_rows
                        mid_row = gap_start + gap_rows // 2
                        gap_markers.setdefault(mid_row, []).append((col_idx, gap_val))

        # Create grid: list of lines, each line has slots for each column
        num_columns = len(play_area.column_layout)
        grid = [[' ' * self.bottle_width for _ in range(num_columns)] for _ in range(max_row)]

        # Place each bottle in the grid
        highlights = highlights or {}
        for bottle_idx, bottle in enumerate(play_area.bottles):
            if bottle.number not in bottle_positions:
                continue

            row_start, col_idx = bottle_positions[bottle.number]
            is_locked = play_area.is_bottle_locked(bottle.number)
            hl = highlights.get(bottle_idx)

            # Generate bottle lines with cursor info
            show_cursor = cursor_bottle is not None and cursor_slot is not None and bottle == cursor_bottle
            bottle_lines = self._get_bottle_lines(bottle, is_locked, show_cursor, cursor_slot if show_cursor else None, highlight=hl)

            # Place in grid
            for line_offset, line_text in enumerate(bottle_lines):
                grid[row_start + line_offset][col_idx] = line_text

        # Print column number headers if in editor mode
        if show_col_numbers:
            col_header = '  '.join(f"{'C' + str(i+1):^{self.bottle_width}}" for i in range(num_columns))
            print(f"\033[2m{col_header}\033[0m")

        # Render grid, injecting gap markers into the blank rows between bottles
        for row_idx, row in enumerate(grid):
            if show_gap_markers and row_idx in gap_markers:
                for col_idx, gap_val in gap_markers[row_idx]:
                    visible = f"↕{gap_val:.1f}"
                    marker = f"\033[2m{visible:<{self.bottle_width}}\033[0m"
                    row[col_idx] = marker
            print('  '.join(row))

    def _get_bottle_lines(self, bottle: Bottle, is_locked: bool, show_cursor: bool = False, cursor_slot: int = None, highlight: str = None) -> list:
        """Get the 8 lines for displaying a bottle. Optionally show cursor at cursor_slot.
        If highlight is set (an ANSI color code), borders are colored."""
        lines = []
        h = highlight or ""
        r = RESET if highlight else ""

        # Line 0: Label (two spaces after #XX in both cases)
        if is_locked:
            label = f"  {h}#{bottle.number}{r} 🔒"
        else:
            label = f"  {h}#{bottle.number}{r}   "
        if bottle.number < 10:
            label += " "
        lines.append(label)

        # Line 1: Top border
        lines.append(f"{h}┌────┐{r}  ")

        # Lines 2-5: Content (4 levels from top to bottom)
        for level in range(3, -1, -1):
            if level < len(bottle.contents):
                is_hidden = bottle.is_slot_hidden(level)
                color = bottle.contents[level]
                symbol = COLOR_SYMBOLS.get(color, "?")
                lb = f"{HIDDEN_BORDER}│{RESET}" if is_hidden else f"{h}│{r}"
                rb = f"{HIDDEN_BORDER}│{RESET}" if is_hidden else f"{h}│{r}"
            else:
                is_hidden = False
                symbol = " "
                lb = f"{h}│{r}"
                rb = f"{h}│{r}"

            # Add cursor if this is the selected slot
            if show_cursor and cursor_slot is not None and level == cursor_slot:
                cursor_marker = "<H" if (level < len(bottle.contents) and is_hidden) else "< "
                if level < len(bottle.contents):
                    lines.append(f"{lb} {symbol} {rb}{cursor_marker}")
                else:
                    lines.append(f"{h}│{r}    {h}│{r}{cursor_marker}")
            else:
                if level < len(bottle.contents):
                    lines.append(f"{lb} {symbol} {rb}  ")
                else:
                    lines.append(f"{h}│{r}    {h}│{r}  ")

        # Line 6: Bottom border
        if bottle.is_complete:
            lines.append(f"{h}└────┘{r} ✓")
        else:
            lines.append(f"{h}└────┘{r}  ")

        # Line 7: Blank separator (makes bottle_height=8, so gap=1.0 = 8 lines, gap=0.5 = 4 lines)
        lines.append("        ")

        return lines

    def _render_bottles_row(self, play_area: PlayArea, cursor_bottle=None, cursor_slot=None, highlights=None):
        """Render all bottles in a row. Optionally show cursor at cursor_bottle/cursor_slot."""
        bottles = play_area.bottles
        highlights = highlights or {}
        lines = []

        # Header line with bottle numbers
        header = ""
        for idx, bottle in enumerate(bottles):
            is_locked = play_area.is_bottle_locked(bottle.number)
            hl = highlights.get(idx)
            h = hl or ""
            r = RESET if hl else ""
            lock_icon = "  🔒" if is_locked else ""
            header += f"{h}#{bottle.number}{r}  {lock_icon}      "
        lines.append(header)

        # Top border
        border_top = ""
        for idx, _ in enumerate(bottles):
            hl = highlights.get(idx)
            h = hl or ""
            r = RESET if hl else ""
            border_top += f"{h}┌────┐{r}         "
        lines.append(border_top)

        # Content lines (4 levels from top to bottom)
        for level in range(3, -1, -1):
            line = ""
            for idx, bottle in enumerate(bottles):
                hl = highlights.get(idx)
                h = hl or ""
                r = RESET if hl else ""

                if level < len(bottle.contents):
                    is_hidden = bottle.is_slot_hidden(level)
                    color = bottle.contents[level]
                    symbol = COLOR_SYMBOLS.get(color, "?")
                    lb = f"{HIDDEN_BORDER}│{RESET}" if is_hidden else f"{h}│{r}"
                    rb = f"{HIDDEN_BORDER}│{RESET}" if is_hidden else f"{h}│{r}"
                else:
                    is_hidden = False
                    symbol = " "
                    lb = f"{h}│{r}"
                    rb = f"{h}│{r}"

                if cursor_bottle is not None and cursor_slot is not None and bottle == cursor_bottle and level == cursor_slot:
                    cursor_marker = "<H" if (level < len(bottle.contents) and is_hidden) else "< "
                    line += f"{lb} {symbol} {rb}{cursor_marker}       "
                else:
                    if level < len(bottle.contents):
                        line += f"{lb} {symbol} {rb}         "
                    else:
                        line += f"{h}│{r}    {h}│{r}         "
            lines.append(line)

        # Bottom border
        border_bottom = ""
        for idx, bottle in enumerate(bottles):
            hl = highlights.get(idx)
            h = hl or ""
            r = RESET if hl else ""
            if bottle.is_complete:
                border_bottom += f"{h}└────┘{r} ✓       "
            else:
                border_bottom += f"{h}└────┘{r}         "
        lines.append(border_bottom)

        for line in lines:
            print(line)

    def render_bottle(self, bottle: Bottle, is_locked: bool = False):
        """
        Display a single bottle vertically.

        Args:
            bottle: The bottle to render
            is_locked: Whether the bottle is locked
        """
        lock_text = " 🔒" if is_locked else ""
        print(f"Bottle #{bottle.number}{lock_text}")
        print("┌────┐")

        # Display from top to bottom (index 3 to 0)
        for i in range(3, -1, -1):
            if i < len(bottle.contents):
                color = bottle.contents[i]
                symbol = COLOR_SYMBOLS.get(color, "?")
                print(f"│ {symbol} │")
            else:
                print("│    │")

        if bottle.is_complete:
            print("└────┘ ✓")
        else:
            print("└────┘")

    def _render_rows(self, play_area: PlayArea, cursor_bottle=None, cursor_slot=None, highlights=None, show_row_numbers=False):
        """Render bottles organized in rows (stacked vertically). Optionally show cursor."""
        if not play_area.row_layout:
            return

        highlights = highlights or {}
        # Map bottle number -> index for highlight lookup
        num_to_idx = {b.number: i for i, b in enumerate(play_area.bottles)}

        for row_idx, row_info in enumerate(play_area.row_layout):
            bottle_indices = row_info['bottle_indices']
            if show_row_numbers:
                print(f"\033[2mR{row_idx + 1}\033[0m")
            if not bottle_indices:
                print(f"[Row {row_idx + 1}: empty]")
                continue

            bottle_map = {b.number: b for b in play_area.bottles}
            row_bottles = [bottle_map[num] for num in bottle_indices if num in bottle_map]

            lines = []

            # Header line with bottle numbers
            header = ""
            for bottle in row_bottles:
                is_locked = play_area.is_bottle_locked(bottle.number)
                hl = highlights.get(num_to_idx.get(bottle.number))
                h = hl or ""
                r = RESET if hl else ""
                header += f" {h}#{bottle.number}{r}"
                if bottle.number < 10:
                    header += " "
                if is_locked:
                    header += f" 🔒  "
                else:
                    header += f"     "
            lines.append(header)

            # Top border
            border_top = ""
            for bottle in row_bottles:
                hl = highlights.get(num_to_idx.get(bottle.number))
                h = hl or ""
                r = RESET if hl else ""
                border_top += f"{h}┌────┐{r}   "
            lines.append(border_top)

            # Content lines (4 levels from top to bottom)
            for level in range(3, -1, -1):
                line = ""
                for bottle in row_bottles:
                    hl = highlights.get(num_to_idx.get(bottle.number))
                    h = hl or ""
                    r = RESET if hl else ""

                    if level < len(bottle.contents):
                        is_hidden = bottle.is_slot_hidden(level)
                        color = bottle.contents[level]
                        symbol = COLOR_SYMBOLS.get(color, "?")
                        lb = f"{HIDDEN_BORDER}│{RESET}" if is_hidden else f"{h}│{r}"
                        rb = f"{HIDDEN_BORDER}│{RESET}" if is_hidden else f"{h}│{r}"
                    else:
                        is_hidden = False
                        symbol = " "
                        lb = f"{h}│{r}"
                        rb = f"{h}│{r}"

                    if cursor_bottle is not None and cursor_slot is not None and bottle == cursor_bottle and level == cursor_slot:
                        cursor_marker = "<H" if (level < len(bottle.contents) and is_hidden) else "< "
                        line += f"{lb} {symbol} {rb}{cursor_marker} "
                    else:
                        if level < len(bottle.contents):
                            line += f"{lb} {symbol} {rb}   "
                        else:
                            line += f"{h}│{r}    {h}│{r}   "
                lines.append(line)

            # Bottom border
            border_bottom = ""
            for bottle in row_bottles:
                hl = highlights.get(num_to_idx.get(bottle.number))
                h = hl or ""
                r = RESET if hl else ""
                if bottle.is_complete:
                    border_bottom += f"{h}└────┘{r} ✓ "
                else:
                    border_bottom += f"{h}└────┘{r}   "
            lines.append(border_bottom)

            for line in lines:
                print(line)

            if row_idx < len(play_area.row_layout) - 1:
                print()

    def render_move(self, from_idx: int, to_idx: int, play_area: PlayArea):
        """
        Display the game state after a move.

        Args:
            from_idx: Source bottle index
            to_idx: Target bottle index
            play_area: The PlayArea after the move
        """
        self.move_count += 1

        from_bottle = play_area.bottles[from_idx]
        to_bottle = play_area.bottles[to_idx]

        message = (f"{BOLD}Move #{self.move_count}:{RESET} "
                   f"{HIGHLIGHT_GREEN}Bottle #{from_bottle.number}{RESET} → "
                   f"{HIGHLIGHT_RED}Bottle #{to_bottle.number}{RESET}")
        self.render_game(play_area, message,
                        highlight_from=from_idx, highlight_to=to_idx)

    def prompt_for_revealed_color(self, bottle_number: int = None, unknown_count: int = 1) -> tuple:
        """
        Prompt the user to identify revealed UNKNOWN color(s).

        Args:
            bottle_number: The bottle number where the unknown is revealed
            unknown_count: Number of consecutive unknowns being revealed

        Returns:
            Tuple of (Color, count) - the color and how many blocks of that color
        """
        print()
        if bottle_number is not None:
            if unknown_count > 1:
                print(f"{BOLD}🔍 {unknown_count} UNKNOWN colors revealed in Bottle #{bottle_number}!{RESET}")
            else:
                print(f"{BOLD}🔍 UNKNOWN color revealed in Bottle #{bottle_number}!{RESET}")
        else:
            if unknown_count > 1:
                print(f"{BOLD}🔍 {unknown_count} UNKNOWN colors revealed!{RESET}")
            else:
                print(f"{BOLD}🔍 UNKNOWN color revealed!{RESET}")

        if unknown_count > 1:
            print("What color(s) are they?")
            print("Format: 'COLOR' or 'COUNT COLOR' or 'COLOR COUNT'")
            print("Example: '3 RED' or 'RED 3' or '3 R' (means next 3 blocks are RED)")
        else:
            print("What color is it?")

        print("Available colors: RED, PURPLE, GREY, GREEN, YELLOW, ORANGE, BLUE, CYAN")
        print("Or use mnemonics: R, P, A, G, Y, O, U, B, C")
        print()

        while True:
            try:
                user_input = input("> ").strip().upper()
                parts = user_input.split()

                # Try to parse count and color
                count = 1
                color_str = user_input

                if len(parts) == 2:
                    # Could be "COUNT COLOR" or "COLOR COUNT"
                    if parts[0].isdigit():
                        count = int(parts[0])
                        color_str = parts[1]
                    elif parts[1].isdigit():
                        color_str = parts[0]
                        count = int(parts[1])
                elif len(parts) == 1:
                    # Just color, count defaults to 1
                    color_str = parts[0]

                # Validate count
                if count < 1:
                    print("Count must be at least 1")
                    continue
                if count > unknown_count:
                    print(f"Cannot specify more than {unknown_count} blocks (only {unknown_count} unknowns revealed)")
                    continue

                # Parse color - check if it's a mnemonic first
                color_str_upper = color_str.upper()
                if color_str_upper in COLOR_MNEMONICS:
                    color = COLOR_MNEMONICS[color_str_upper]
                else:
                    color = color_from_string(color_str)

                if color == Color.UNKNOWN:
                    print("Please enter an actual color, not UNKNOWN or J")
                    continue

                return color, count

            except ValueError:
                print(f"Invalid input. Please try again.")
                print("Format: 'COLOR' or 'COUNT COLOR' or 'COLOR COUNT'")

    def print_color_counts(self, play_area: PlayArea) -> None:
        """
        Print a color count table showing how many of each color exist across
        all bottles, highlighting colors whose count is not a multiple of 4.
        """
        color_counts = {}
        unknown_count = 0

        for bottle in play_area.bottles:
            for color in bottle.contents:
                if color == Color.UNKNOWN:
                    unknown_count += 1
                else:
                    color_counts[color] = color_counts.get(color, 0) + 1

        if not color_counts and unknown_count == 0:
            print("  (no colors yet)")
            return

        # Build display entries sorted by color name
        entries = []
        for color in sorted(color_counts, key=lambda c: c.name):
            count = color_counts[color]
            deficit = (4 - count % 4) % 4
            code = COLOR_CODES.get(color, "")
            symbol = COLOR_SYMBOLS.get(color, "")
            if deficit == 0:
                label = f"{code}{symbol} {color.name}:{count}✓{RESET}"
            else:
                label = f"{COLOR_CODES[Color.YELLOW]}{symbol} {color.name}:{count}(+{deficit}){RESET}"
            entries.append(label)

        if unknown_count > 0:
            entries.append(f"{COLOR_CODES[Color.UNKNOWN]}❓ UNKNOWN:{unknown_count}{RESET}")

        # Print in rows of 4
        print("Color counts  (✓ = multiple of 4):")
        row_size = 4
        for i in range(0, len(entries), row_size):
            print("  " + "   ".join(entries[i:i + row_size]))

    def show_message(self, msg: str, level: str = "info"):
        """
        Display a status message.

        Args:
            msg: The message to display
            level: Message level (info, success, error, warning)
        """
        if level == "success":
            print(f"{COLOR_CODES[Color.GREEN]}{BOLD}{msg}{RESET}")
        elif level == "error":
            print(f"{COLOR_CODES[Color.RED]}{BOLD}{msg}{RESET}")
        elif level == "warning":
            print(f"{COLOR_CODES[Color.YELLOW]}{BOLD}{msg}{RESET}")
        else:
            print(msg)

    def show_solution_summary(self, moves: List[Tuple[int, int]], play_area: PlayArea):
        """
        Display a summary of the solution.

        Args:
            moves: List of (from_idx, to_idx) moves
            play_area: The PlayArea instance
        """
        print()
        print(f"{BOLD}Solution Summary:{RESET}")
        print(f"Total moves: {len(moves)}")
        print()

        for i, (from_idx, to_idx) in enumerate(moves, 1):
            from_bottle = play_area.bottles[from_idx]
            to_bottle = play_area.bottles[to_idx]
            print(f"{i}. Bottle #{from_bottle.number} → Bottle #{to_bottle.number}")

    def prompt_for_unlocked_bottle_contents(self, bottle_number: int, is_all_unknown: bool) -> List[Color]:
        """
        Prompt user to identify the contents of a newly-unlocked bottle.

        Args:
            bottle_number: The bottle number that was just unlocked
            is_all_unknown: True if contents are all UNKNOWN, False if empty

        Returns:
            List of Color enums from bottom to top (may be empty)
        """
        print()
        if is_all_unknown:
            print(f"{BOLD}🔓 Bottle #{bottle_number} unlocked! Its contents are hidden.{RESET}")
        else:
            print(f"{BOLD}🔓 Bottle #{bottle_number} unlocked! It appears empty in the puzzle file.{RESET}")
        print("What are its contents? Enter colors from bottom to top.")
        print("Format: compact string (e.g., 'JJCY'), space-separated (e.g., 'R G B Y'), or full names")
        print("Press Enter if the bottle is genuinely empty.")
        print("Available: RED(R), PURPLE(P), GREY(A), GREEN(G), YELLOW(Y), ORANGE(O), BLUE(U), CYAN(C), UNKNOWN(J/?)")
        print()

        while True:
            try:
                user_input = input("> ").strip().upper()

                if not user_input:
                    return []

                colors = []
                # If no spaces and every char is a valid mnemonic, parse as compact string
                if ' ' not in user_input and all(ch in COLOR_MNEMONICS for ch in user_input):
                    colors = [COLOR_MNEMONICS[ch] for ch in user_input]
                else:
                    for part in user_input.split():
                        if part in COLOR_MNEMONICS:
                            colors.append(COLOR_MNEMONICS[part])
                        else:
                            colors.append(color_from_string(part))

                if len(colors) > 4:
                    print("A bottle can hold at most 4 colors. Please re-enter.")
                    continue

                if colors and all(c == Color.UNKNOWN for c in colors):
                    print("An unlocked bottle cannot be entirely unknown. Enter at least one known color.")
                    continue

                return colors

            except ValueError:
                print("Invalid input. Please try again.")

    def prompt_continue(self, message: str = None, can_rewind: bool = False) -> str:
        """
        Prompt the user to continue, save, rewind, or edit.

        Args:
            message: Custom prompt message (auto-generated if None)
            can_rewind: Whether 'b' (back) is available

        Returns:
            's' if user wants to save
            'e' if user wants to edit
            'b' if user wants to go back
            empty string otherwise
        """
        if message is None:
            opts = "'s' save, 'e' edit"
            if can_rewind:
                opts += ", 'b' back"
            message = f"[Enter] next ({opts})... "
        response = input(message).strip().lower()
        return response

    def prompt_yes_no(self, message: str) -> bool:
        """
        Prompt the user for a yes/no answer.

        Args:
            message: The question to ask

        Returns:
            True for yes, False for no
        """
        while True:
            response = input(f"{message} (y/n): ").strip().lower()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no']:
                return False
            else:
                print("Please answer 'y' or 'n'")

    def show_completion(self, move_count: int):
        """Show puzzle completion message."""
        print()
        print(f"{COLOR_CODES[Color.GREEN]}{BOLD}🎉 Puzzle solved in {move_count} moves!{RESET}")
        print()

    def show_progress(self, iteration: int, queue_size: int, explored: int, status: str):
        """
        Show solver progress.

        Args:
            iteration: Current iteration number
            queue_size: Number of states in queue
            explored: Number of states explored
            status: Current status (SEARCHING, SOLVED, UNKNOWN_REVEALED, TIMEOUT, NO_SOLUTION)
        """
        if status == "SEARCHING":
            # Clear line and show progress
            print(f"\r⏳ Searching... Iteration: {iteration:,} | Queue: {queue_size:,} | Explored: {explored:,}", end="", flush=True)
        elif status == "SOLVED":
            # Clear the progress line and show success
            print(f"\r✓ Solution found after {iteration:,} iterations (explored {explored:,} states)          ")
        elif status == "UNKNOWN_REVEALED":
            # Clear the progress line and show that an unknown was found
            print(f"\r🔍 Unknown color found after {iteration:,} iterations (explored {explored:,} states)      ")
        elif status == "TIMEOUT":
            print()  # New line after progress
            print()
            print(f"{COLOR_CODES[Color.YELLOW]}{BOLD}⏱️  TIMEOUT{RESET}")
            print(f"The solver reached the maximum iteration limit ({iteration:,} iterations).")
            print(f"Explored {explored:,} unique states without finding a solution.")
            print()
            print("This happened because:")
            print("  • The puzzle is too complex and needs more iterations")
            print("  • The puzzle may be unsolvable in its current state")
            print("  • There may be locked bottles blocking progress")
            print()
            print("Suggestions:")
            print("  • Check if any bottles are locked and need to be unlocked first")
            print("  • Verify the puzzle has enough empty bottles for working space")
            print("  • Try solving step by step instead of all at once")
        elif status == "NO_SOLUTION":
            print()  # New line after progress
            print()
            print(f"{COLOR_CODES[Color.RED]}{BOLD}❌ NO SOLUTION EXISTS{RESET}")
            print(f"Exhausted the entire search space after {iteration:,} iterations.")
            print(f"Explored {explored:,} unique states and found no path to completion.")
            print()
            print("This means the puzzle is UNSOLVABLE because:")
            print("  • Not enough empty bottles for working space")
            print("  • Locked bottles are blocking necessary moves")
            print("  • The color distribution makes completion impossible")
            print("  • Unknown colors may need to be revealed first")
            print()
            print("Suggestions:")
            print("  • Add more empty bottles to the puzzle")
            print("  • Check lock conditions on bottles")
            print("  • Verify unknown colors are correctly placed")
