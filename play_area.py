from typing import List, Tuple, Dict, Optional
import copy
from models import Bottle, Color, LockCondition
from utils import load_json_puzzle, save_json_puzzle, color_from_string, color_to_string

class PlayArea:
    def __init__(self):
        self.bottles: List[Bottle] = []
        self.lock_conditions: Dict[int, LockCondition] = {}
        self.completed_bottles: set = set()
        self.completed_colors: Dict[Color, int] = {}
        # Layout metadata for display
        self.column_layout: Optional[List[Dict]] = None  # List of {skew, bottle_indices}
        self.row_layout: Optional[List[Dict]] = None  # List of {bottle_indices} for row mode

    def add_bottle(self, number: int, contents: list = None):
        """Add a bottle to the play area."""
        if contents is None:
            contents = []
        self.bottles.append(Bottle(number, contents))

    @staticmethod
    def load_from_json(filepath: str) -> 'PlayArea':
        """
        Load a PlayArea from a JSON file.

        Args:
            filepath: Path to the JSON file

        Returns:
            PlayArea instance populated with data from the file
        """
        data = load_json_puzzle(filepath)
        play_area = PlayArea()

        # Store layout metadata if present
        if 'column_layout' in data:
            play_area.column_layout = data['column_layout']
        if 'row_layout' in data:
            play_area.row_layout = data['row_layout']

        for bottle_data in data['bottles']:
            number = bottle_data['number']
            contents = [color_from_string(c) for c in bottle_data['contents']]

            bottle = Bottle(number, contents)
            play_area.bottles.append(bottle)

            # Check if bottle is complete
            if len(bottle.contents) == 4 and bottle.all_colors_equal() and bottle.contents[-1] != Color.UNKNOWN:
                bottle.is_complete = True
                play_area.completed_bottles.add(number)
                color = bottle.contents[0]
                play_area.completed_colors[color] = play_area.completed_colors.get(color, 0) + 1

            # Add lock condition if present (simplified format: count + color)
            if 'lock_condition' in bottle_data:
                lock_data = bottle_data['lock_condition']
                count = lock_data['count']
                color_str = lock_data['color']

                # Parse color: "ANY" means None (any color), otherwise parse the color name
                if color_str.upper() == 'ANY':
                    color = None
                else:
                    color = color_from_string(color_str)

                play_area.lock_conditions[number] = LockCondition(count, color)

        return play_area

    def save_to_json(self, filepath: str) -> None:
        """
        Save the current PlayArea state to a JSON file.

        Args:
            filepath: Path to save the JSON file
        """
        bottles_data = []

        for bottle in self.bottles:
            bottle_dict = {
                'number': bottle.number,
                'contents': [color_to_string(c) for c in bottle.contents]
            }

            # Add lock condition if present (simplified format)
            if bottle.number in self.lock_conditions:
                lock_cond = self.lock_conditions[bottle.number]
                lock_dict = {
                    'count': lock_cond.count,
                    'color': 'ANY' if lock_cond.color is None else color_to_string(lock_cond.color)
                }
                bottle_dict['lock_condition'] = lock_dict

            bottles_data.append(bottle_dict)

        data = {'bottles': bottles_data}

        # Include layout metadata if present
        if self.column_layout is not None:
            data['column_layout'] = self.column_layout
        if self.row_layout is not None:
            data['row_layout'] = self.row_layout

        save_json_puzzle(data, filepath)

    def is_bottle_locked(self, bottle_number: int) -> bool:
        """
        Check if a bottle is currently locked.

        Args:
            bottle_number: The bottle number to check

        Returns:
            True if the bottle is locked, False otherwise
        """
        if bottle_number not in self.lock_conditions:
            return False

        lock_condition = self.lock_conditions[bottle_number]
        return not lock_condition.is_unlocked(len(self.completed_bottles), self.completed_colors)

    def update_locks(self) -> None:
        """Update completion tracking and re-evaluate lock conditions."""
        self.completed_bottles.clear()
        self.completed_colors.clear()

        for bottle in self.bottles:
            if bottle.is_complete:
                self.completed_bottles.add(bottle.number)
                color = bottle.contents[0]
                self.completed_colors[color] = self.completed_colors.get(color, 0) + 1
            elif len(bottle.contents) == 4 and bottle.all_colors_equal() and bottle.contents[-1] != Color.UNKNOWN:
                # Mark as complete if it wasn't already
                bottle.is_complete = True
                self.completed_bottles.add(bottle.number)
                color = bottle.contents[0]
                self.completed_colors[color] = self.completed_colors.get(color, 0) + 1

    def get_valid_moves(self) -> List[Tuple[int, int]]:
        """
        Get all valid moves in the current game state.

        Returns:
            List of (from_index, to_index) tuples representing valid moves
        """
        valid_moves = []

        for i, from_bottle in enumerate(self.bottles):
            # Skip if bottle is locked, complete, or empty
            if self.is_bottle_locked(from_bottle.number):
                continue
            if from_bottle.is_complete:
                continue
            if from_bottle.is_empty():
                continue

            for j, to_bottle in enumerate(self.bottles):
                if i == j:
                    continue

                # Skip if target bottle is locked, complete, or full
                if self.is_bottle_locked(to_bottle.number):
                    continue
                if to_bottle.is_complete:
                    continue
                if to_bottle.is_full():
                    continue

                # Check if transfer is valid
                from_color = from_bottle.get_top_color()

                # Empty bottle can accept any color
                if to_bottle.is_empty():
                    valid_moves.append((i, j))
                    continue

                # Non-empty bottle must have matching top color
                to_color = to_bottle.get_top_color()
                if from_color == to_color:
                    # Check if there's enough space
                    amount_to_transfer = from_bottle.count_consecutive_top()
                    space_available = 4 - len(to_bottle.contents)
                    if space_available >= amount_to_transfer:
                        valid_moves.append((i, j))

        return valid_moves

    def apply_move(self, from_idx: int, to_idx: int) -> bool:
        """
        Execute a move from one bottle to another.

        Args:
            from_idx: Index of the source bottle
            to_idx: Index of the target bottle

        Returns:
            True if the move was successful, False otherwise
        """
        if from_idx < 0 or from_idx >= len(self.bottles):
            return False
        if to_idx < 0 or to_idx >= len(self.bottles):
            return False

        from_bottle = self.bottles[from_idx]
        to_bottle = self.bottles[to_idx]

        success = from_bottle.transfer_to(to_bottle)

        if success:
            self.update_locks()

        return success

    def is_game_complete(self) -> bool:
        """
        Check if the game is complete (all non-empty bottles are complete).

        Returns:
            True if the game is complete, False otherwise
        """
        for bottle in self.bottles:
            if not bottle.is_empty() and not bottle.is_complete:
                return False
        return True

    def reveal_unknown(self, bottle_idx: int, position: int, color: Color) -> None:
        """
        Reveal an UNKNOWN color at a specific position in a bottle.

        Args:
            bottle_idx: Index of the bottle
            position: Position of the unknown color (0 = bottom, 3 = top)
            color: The actual color to replace UNKNOWN with
        """
        if bottle_idx < 0 or bottle_idx >= len(self.bottles):
            return

        bottle = self.bottles[bottle_idx]
        if position < 0 or position >= len(bottle.contents):
            return

        if bottle.contents[position] == Color.UNKNOWN:
            bottle.contents[position] = color

    def to_game_state(self):
        """
        Convert PlayArea to an immutable GameState for the solver.

        Returns:
            GameState instance
        """
        # This will be implemented once solver.py is created
        # For now, we'll import it later
        from solver import GameState

        bottles_tuple = tuple(bottle.to_tuple() for bottle in self.bottles)
        locked_bottles = frozenset(
            i for i, bottle in enumerate(self.bottles)
            if self.is_bottle_locked(bottle.number)
        )
        completed_bottles = frozenset(
            i for i, bottle in enumerate(self.bottles)
            if bottle.is_complete
        )

        # Convert lock_conditions from bottle-NUMBER keys to bottle-INDEX keys
        # so GameState.apply_move can use them consistently with indices
        number_to_index = {bottle.number: i for i, bottle in enumerate(self.bottles)}
        index_lock_conditions = {
            number_to_index[num]: cond
            for num, cond in self.lock_conditions.items()
            if num in number_to_index
        }

        return GameState(bottles_tuple, locked_bottles, completed_bottles,
                        self.completed_colors, index_lock_conditions)

    def clone(self) -> 'PlayArea':
        """
        Create a deep copy of the PlayArea.

        Returns:
            A new PlayArea instance with copied data
        """
        return copy.deepcopy(self)

    def get_bottle_by_number(self, number: int) -> Optional[Bottle]:
        """Get a bottle by its number."""
        for bottle in self.bottles:
            if bottle.number == number:
                return bottle
        return None

    def set_bottle_contents(self, bottle_number: int, colors: List[Color]) -> None:
        """
        Set bottle contents and re-evaluate completion status.

        Args:
            bottle_number: The bottle number to modify
            colors: List of Color enums to set
        """
        bottle = self.get_bottle_by_number(bottle_number)
        if bottle is None:
            raise ValueError(f"Bottle {bottle_number} not found")

        bottle.contents = colors.copy()
        bottle.is_complete = False

        # Check if now complete
        if len(bottle.contents) == 4 and bottle.all_colors_equal() and bottle.contents[-1] != Color.UNKNOWN:
            bottle.is_complete = True

        self.update_locks()

    def set_lock(self, bottle_number: int, count: int, color: Optional[Color] = None) -> None:
        """
        Set a lock condition on a bottle.

        Args:
            bottle_number: The bottle number to lock
            count: Number of bottles that need to be completed
            color: Color to match (None for ANY)
        """
        self.lock_conditions[bottle_number] = LockCondition(count, color)
        self.update_locks()

    def remove_lock(self, bottle_number: int) -> None:
        """
        Remove a lock condition from a bottle.

        Args:
            bottle_number: The bottle number to unlock
        """
        if bottle_number in self.lock_conditions:
            del self.lock_conditions[bottle_number]
        self.update_locks()

    def add_new_bottle(self, contents: List[Color] = None) -> int:
        """
        Add a new bottle and return its number.

        Args:
            contents: Initial contents (default: empty)

        Returns:
            The number assigned to the new bottle
        """
        if self.bottles:
            number = max(b.number for b in self.bottles) + 1
        else:
            number = 0

        if contents is None:
            contents = []

        self.add_bottle(number, contents)
        return number

    def remove_bottle(self, bottle_number: int) -> None:
        """
        Remove a bottle and its lock condition.

        Args:
            bottle_number: The bottle number to remove
        """
        # Remove from bottles list
        self.bottles = [b for b in self.bottles if b.number != bottle_number]

        # Remove lock condition if present
        if bottle_number in self.lock_conditions:
            del self.lock_conditions[bottle_number]

        # Remove from column layout if present
        if self.column_layout:
            for column in self.column_layout:
                if 'bottle_indices' in column:
                    column['bottle_indices'] = [
                        idx for idx in column['bottle_indices'] if idx != bottle_number
                    ]

        # Remove from row layout if present
        if self.row_layout:
            for row in self.row_layout:
                if 'bottle_indices' in row:
                    row['bottle_indices'] = [
                        idx for idx in row['bottle_indices'] if idx != bottle_number
                    ]

        self.update_locks()

    def renumber_bottles_by_rows(self) -> None:
        """
        Renumber all bottles sequentially based on their row positions.
        Row 0 gets numbers 0,1,2,...
        Row 1 gets numbers starting from len(row0),...
        And so on.
        """
        if not self.row_layout:
            return

        # Create a mapping from old number to new number
        number_map = {}
        new_number = 0

        # Go through each row and reassign numbers
        for row in self.row_layout:
            for old_number in row['bottle_indices']:
                number_map[old_number] = new_number
                new_number += 1

        # Update bottle numbers
        for bottle in self.bottles:
            if bottle.number in number_map:
                bottle.number = number_map[bottle.number]

        # Update row layout with new numbers
        for row in self.row_layout:
            row['bottle_indices'] = [number_map.get(num, num) for num in row['bottle_indices']]

        # Update lock conditions with new bottle numbers
        new_lock_conditions = {}
        for old_num, lock in self.lock_conditions.items():
            if old_num in number_map:
                new_lock_conditions[number_map[old_num]] = lock
            else:
                new_lock_conditions[old_num] = lock
        self.lock_conditions = new_lock_conditions

        # Update completed bottles tracking
        new_completed = set()
        for old_num in self.completed_bottles:
            if old_num in number_map:
                new_completed.add(number_map[old_num])
            else:
                new_completed.add(old_num)
        self.completed_bottles = new_completed

        self.update_locks()

    def renumber_bottles_by_columns(self) -> None:
        """
        Renumber all bottles sequentially based on their column positions.
        Column 0 gets numbers 0, 1, 2, … (top to bottom),
        Column 1 continues from there, and so on.
        """
        if not self.column_layout:
            return

        number_map = {}
        new_number = 0

        for column in self.column_layout:
            for old_number in column['bottle_indices']:
                number_map[old_number] = new_number
                new_number += 1

        for bottle in self.bottles:
            if bottle.number in number_map:
                bottle.number = number_map[bottle.number]

        for column in self.column_layout:
            column['bottle_indices'] = [number_map.get(n, n) for n in column['bottle_indices']]

        new_lock_conditions = {}
        for old_num, lock in self.lock_conditions.items():
            new_lock_conditions[number_map.get(old_num, old_num)] = lock
        self.lock_conditions = new_lock_conditions

        new_completed = {number_map.get(n, n) for n in self.completed_bottles}
        self.completed_bottles = new_completed

        self.update_locks()

    def __repr__(self):
        return f"PlayArea(bottles={len(self.bottles)}, completed={len(self.completed_bottles)})"
