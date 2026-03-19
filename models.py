from enum import Enum
from typing import Optional

# Add mnemonics to colors, in order: RPAGYOUC?
# Accept both GREY AND GRAY
class Color(Enum):
    RED = 0
    PURPLE = 1
    GREY = 2
    GREEN = 3
    YELLOW = 4
    ORANGE = 5
    BLUE = 6
    CYAN = 7
    UNKNOWN = 99

class InvalidContentsException(Exception):
    pass

class Bottle:
    def __init__(self, number: int, contents: list = None):
        if contents is None:
            contents = []
        for color in contents:
            if not isinstance(color, Color):
                raise InvalidContentsException('Tried creating a bottle with invalid contents')
        self.number = number
        self.contents = contents
        self.is_complete = False

    def add(self, color: Color) -> bool:
        """Add a color to the bottle. Returns True if successful, False otherwise."""
        if self.is_complete:
            return False
        if len(self.contents) == 0:
            self.contents.append(color)
            return True
        elif len(self.contents) < 4 and self.contents[-1] == color:
            self.contents.append(color)
            if len(self.contents) == 4 and self.all_colors_equal() and color != Color.UNKNOWN:
                self.is_complete = True
            return True
        else:
            return False

    def all_colors_equal(self) -> bool:
        """Check if all colors in the bottle are the same."""
        if len(self.contents) <= 1:
            return True
        for i in range(len(self.contents) - 1):
            if self.contents[i] != self.contents[i+1]:
                return False
        return True

    def transfer_to(self, target_bottle: 'Bottle') -> bool:
        """Transfer colors from this bottle to target bottle. Returns True if successful."""
        if self.is_complete:
            return False
        if target_bottle.is_complete:
            return False
        elif len(self.contents) == 0:
            return False
        elif len(target_bottle.contents) == 4:
            return False

        color_to_transfer = self.contents[-1]

        # If target is empty, allow transfer
        if len(target_bottle.contents) == 0:
            pass
        # If target has colors, check if top color matches
        elif target_bottle.contents[-1] != color_to_transfer:
            return False

        # Count consecutive colors from top
        amount_to_transfer = self.count_consecutive_top()

        space_available_in_target = 4 - len(target_bottle.contents)
        if space_available_in_target < amount_to_transfer:
            return False

        for _ in range(amount_to_transfer):
            color = self.contents.pop()
            success = target_bottle.add(color)
            if not success:
                # Rollback if add fails (shouldn't happen with our checks)
                self.contents.append(color)
                return False

        return True

    def get_top_color(self) -> Optional[Color]:
        """Get the color at the top of the bottle."""
        if len(self.contents) == 0:
            return None
        return self.contents[-1]

    def count_consecutive_top(self) -> int:
        """Count how many consecutive colors of the same type are at the top."""
        if len(self.contents) == 0:
            return 0

        top_color = self.contents[-1]
        count = 1

        for i in range(len(self.contents) - 2, -1, -1):
            if self.contents[i] == top_color:
                count += 1
            else:
                break

        return count

    def to_tuple(self) -> tuple:
        """Convert bottle contents to immutable tuple for state representation."""
        return tuple(self.contents)

    def has_unknown(self) -> bool:
        """Check if bottle contains any UNKNOWN colors."""
        return Color.UNKNOWN in self.contents

    def is_empty(self) -> bool:
        """Check if bottle is empty."""
        return len(self.contents) == 0

    def is_full(self) -> bool:
        """Check if bottle is full."""
        return len(self.contents) == 4

    def __repr__(self):
        return f"Bottle({self.number}, {[c.name for c in self.contents]})"

class LockCondition:
    """Represents a condition for unlocking a locked bottle."""

    def __init__(self, count: int, color: Optional[Color] = None):
        """
        Create a lock condition.

        Args:
            count: Number of bottles that need to be completed
            color: Color to match (None or "ANY" for any color)
        """
        self.count = count
        self.color = color  # None means ANY

    def is_unlocked(self, completed_count: int, completed_colors: dict) -> bool:
        """
        Check if the lock condition has been met.

        Args:
            completed_count: Total number of completed bottles
            completed_colors: Dictionary mapping Color to count of completed bottles with that color

        Returns:
            True if the lock condition is met, False otherwise
        """
        if self.color is None:
            # ANY color - count total completed bottles
            return completed_count >= self.count
        else:
            # Specific color
            return completed_colors.get(self.color, 0) >= self.count

    def __repr__(self):
        if self.color is None:
            return f"LockCondition(count={self.count}, color=ANY)"
        return f"LockCondition(count={self.count}, color={self.color.name})"
