import json
from typing import Any, Dict, List
from models import Color

# Color mnemonics mapping: RPAGYOUC?
COLOR_MNEMONICS = {
    'R': Color.RED,
    'P': Color.PURPLE,
    'A': Color.GREY,      # grAy
    'G': Color.GREEN,
    'Y': Color.YELLOW,
    'O': Color.ORANGE,
    'U': Color.BLUE,      # blUe
    'B': Color.BLUE,      # Alternative for BLUE
    'C': Color.CYAN,
    '?': Color.UNKNOWN,
    'J': Color.UNKNOWN,   # Alternative for UNKNOWN
}

def color_from_string(name: str) -> Color:
    """Convert a color name string to a Color enum value."""
    name = name.upper()

    # Support both GREY and GRAY
    if name == 'GRAY':
        name = 'GREY'

    try:
        return Color[name]
    except KeyError:
        raise ValueError(f"Invalid color name: {name}")

def color_from_mnemonic(char: str) -> Color:
    """Convert a single character mnemonic to a Color enum value."""
    char = char.upper()
    if char in COLOR_MNEMONICS:
        return COLOR_MNEMONICS[char]
    raise ValueError(f"Invalid color mnemonic: {char}")

def color_to_string(color: Color) -> str:
    """Convert a Color enum value to a string."""
    return color.name

def parse_bottle_contents(contents: Any) -> List[Color]:
    """
    Parse bottle contents from either a list of color names or a string of mnemonics.

    Args:
        contents: Either a list like ["RED", "BLUE"] or a string like "RB"

    Returns:
        List of Color enums

    Raises:
        ValueError: If contents format is invalid
    """
    if isinstance(contents, str):
        # String notation: each character is a color mnemonic
        return [color_from_mnemonic(char) for char in contents]
    elif isinstance(contents, list):
        # List notation: each element is a color name
        return [color_from_string(name) for name in contents]
    else:
        raise ValueError(f"Invalid contents format: {type(contents)}")

def convert_columns_to_bottles(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert column layout format to standard bottles format.

    Column layout allows bottles to be arranged vertically with skew offsets.
    Bottles are auto-numbered from top to bottom, left to right.

    Args:
        data: Dictionary with "columns" array

    Returns:
        Dictionary with "bottles" array in standard format plus "column_layout" metadata
    """
    if 'columns' not in data:
        return data

    # Collect all bottles with their positions
    bottle_positions = []  # List of (skew, column_idx, bottle_idx, bottle_data)
    column_layout = []  # Metadata for display: [{skew, bottle_indices}]

    for col_idx, column in enumerate(data['columns']):
        skew = column.get('skew', 0)  # Vertical offset in bottle heights
        bottles_in_column = column.get('bottles', [])

        column_info = {
            'skew': skew,
            'bottle_indices': []
        }

        for bottle_idx, bottle_data in enumerate(bottles_in_column):
            # Calculate vertical position: bottle index + skew
            vertical_pos = bottle_idx + skew
            bottle_positions.append((vertical_pos, col_idx, bottle_idx, bottle_data))

        column_layout.append(column_info)

    # Sort by column (left to right), then by vertical position (top to bottom)
    bottle_positions.sort(key=lambda x: (x[1], x[0]))

    # Create numbered bottles and track their indices per column
    bottles = []
    bottle_to_column = {}  # Maps bottle number to column index

    for number, (_, col_idx, _, bottle_data) in enumerate(bottle_positions):
        # Ensure bottle_data is a dict
        if not isinstance(bottle_data, dict):
            bottle_data = {}

        # Parse contents (could be string or array)
        if 'contents' in bottle_data:
            contents_raw = bottle_data['contents']
            if isinstance(contents_raw, str):
                # Convert string mnemonics to color names
                colors = parse_bottle_contents(contents_raw)
                bottle_data['contents'] = [color.name for color in colors]
            # If it's already a list, leave it as is

        # Normalize lock format: convert "locked" to "lock_condition" for backward compatibility
        if 'locked' in bottle_data:
            lock = bottle_data['locked']
            bottle_data['lock_condition'] = {
                'count': lock['count'],
                'color': lock['color']
            }
            del bottle_data['locked']

        # Add bottle number
        bottle_data['number'] = number
        bottles.append(bottle_data)

        # Track which column this bottle belongs to
        column_layout[col_idx]['bottle_indices'].append(number)

    return {
        'bottles': bottles,
        'column_layout': column_layout
    }

def load_json_puzzle(filepath: str) -> Dict[str, Any]:
    """
    Load a puzzle from a JSON file.

    Supports two formats:
    1. Standard format with "bottles" array
    2. Column layout format with "columns" array (auto-numbers bottles)

    Args:
        filepath: Path to the JSON file

    Returns:
        Dictionary containing the puzzle data in standard format

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file contains invalid JSON
        ValueError: If JSON doesn't match expected schema
    """
    with open(filepath, 'r') as f:
        data = json.load(f)

    # Convert column layout to standard format if needed
    if 'columns' in data:
        data = convert_columns_to_bottles(data)
    else:
        # Normalize standard format: convert string contents and "locked" field
        if 'bottles' in data:
            for bottle_data in data['bottles']:
                # Convert string contents to array
                if 'contents' in bottle_data and isinstance(bottle_data['contents'], str):
                    colors = parse_bottle_contents(bottle_data['contents'])
                    bottle_data['contents'] = [color.name for color in colors]

                # Normalize lock format: convert "locked" to "lock_condition"
                if 'locked' in bottle_data:
                    lock = bottle_data['locked']
                    bottle_data['lock_condition'] = {
                        'count': lock['count'],
                        'color': lock['color']
                    }
                    del bottle_data['locked']

    validate_json_schema(data)
    return data

def validate_json_schema(data: Dict[str, Any]) -> None:
    """
    Validate that JSON data matches the expected puzzle schema.

    Args:
        data: Dictionary containing puzzle data

    Raises:
        ValueError: If data doesn't match schema
    """
    if not isinstance(data, dict):
        raise ValueError("JSON data must be an object")

    if 'bottles' not in data:
        raise ValueError("JSON data must contain 'bottles' key")

    bottles = data['bottles']
    if not isinstance(bottles, list):
        raise ValueError("'bottles' must be an array")

    for i, bottle in enumerate(bottles):
        if not isinstance(bottle, dict):
            raise ValueError(f"Bottle at index {i} must be an object")

        if 'number' not in bottle:
            raise ValueError(f"Bottle at index {i} missing 'number' field")

        if not isinstance(bottle['number'], int):
            raise ValueError(f"Bottle at index {i} 'number' must be an integer")

        if 'contents' not in bottle:
            raise ValueError(f"Bottle at index {i} missing 'contents' field")

        contents = bottle['contents']
        if not isinstance(contents, list):
            raise ValueError(f"Bottle at index {i} 'contents' must be an array")

        if len(contents) > 4:
            raise ValueError(f"Bottle at index {i} has more than 4 colors")

        # Validate each color
        for j, color_name in enumerate(contents):
            if not isinstance(color_name, str):
                raise ValueError(f"Bottle at index {i}, color at position {j} must be a string")
            try:
                color_from_string(color_name)
            except ValueError:
                raise ValueError(f"Bottle at index {i}, invalid color '{color_name}' at position {j}")

        # Validate lock condition if present (simplified format: count + color)
        if 'lock_condition' in bottle:
            lock_cond = bottle['lock_condition']
            if not isinstance(lock_cond, dict):
                raise ValueError(f"Bottle at index {i} 'lock_condition' must be an object")

            if 'count' not in lock_cond:
                raise ValueError(f"Bottle at index {i} lock_condition missing 'count' field")

            if not isinstance(lock_cond['count'], int) or lock_cond['count'] < 0:
                raise ValueError(f"Bottle at index {i} lock_condition 'count' must be a non-negative integer")

            if 'color' not in lock_cond:
                raise ValueError(f"Bottle at index {i} lock_condition missing 'color' field")

            color_str = lock_cond['color']
            if not isinstance(color_str, str):
                raise ValueError(f"Bottle at index {i} lock_condition 'color' must be a string")

            # Validate color (must be a valid color name or "ANY")
            if color_str.upper() != 'ANY':
                try:
                    color_from_string(color_str)
                except ValueError:
                    raise ValueError(f"Bottle at index {i} lock_condition has invalid color '{color_str}'")

def save_json_puzzle(data: Dict[str, Any], filepath: str) -> None:
    """
    Save puzzle data to a JSON file.

    Args:
        data: Dictionary containing puzzle data
        filepath: Path to save the JSON file
    """
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
