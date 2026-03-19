#!/usr/bin/env python3
"""Test revealing multiple unknowns at once."""

from models import Color, Bottle
from play_area import PlayArea
from ui import ConsoleUI

def test_multi_unknown_prompt():
    """Test the prompt for multiple unknowns."""
    print("="*60)
    print("Testing Multi-Unknown Revelation Prompt")
    print("="*60)
    print()

    ui = ConsoleUI()

    # Test 1: Single unknown
    print("Test 1: Single unknown (should default to 1)")
    print("Try typing: RED")
    color, count = ui.prompt_for_revealed_color(bottle_number=5, unknown_count=1)
    print(f"Result: {color.name}, count={count}")
    print()

    # Test 2: Multiple unknowns with count
    print("Test 2: Multiple unknowns")
    print("Try typing: 3 BLUE  (or BLUE 3)")
    color, count = ui.prompt_for_revealed_color(bottle_number=5, unknown_count=3)
    print(f"Result: {color.name}, count={count}")
    print()

    # Test 3: Partial revelation
    print("Test 3: Multiple unknowns, partial reveal")
    print("Try typing: 2 GREEN  (out of 4 unknowns)")
    color, count = ui.prompt_for_revealed_color(bottle_number=5, unknown_count=4)
    print(f"Result: {color.name}, count={count}")
    print()

def test_revelation_logic():
    """Test the revelation logic for multiple unknowns."""
    print("="*60)
    print("Testing Revelation Logic")
    print("="*60)
    print()

    # Create a test bottle with multiple unknowns
    bottle = Bottle(5, [Color.RED, Color.UNKNOWN, Color.UNKNOWN, Color.UNKNOWN])

    play_area = PlayArea()
    play_area.bottles = [bottle]

    print(f"Initial bottle: {[c.name for c in bottle.contents]}")
    print()

    # Simulate revealing 2 unknowns as BLUE
    revealed_color = Color.BLUE
    reveal_count = 2

    start_position = len(bottle.contents) - 1  # Position 3 (top)
    print(f"Revealing top {reveal_count} unknowns as {revealed_color.name}...")

    for offset in range(reveal_count):
        position = start_position - offset
        if position >= 0 and bottle.contents[position] == Color.UNKNOWN:
            play_area.reveal_unknown(0, position, revealed_color)
            print(f"  Revealed position {position}: {bottle.contents[position].name}")

    print()
    print(f"After revelation: {[c.name for c in bottle.contents]}")
    print(f"Expected: ['RED', 'UNKNOWN', 'BLUE', 'BLUE']")
    print()

    # Check result
    expected = [Color.RED, Color.UNKNOWN, Color.BLUE, Color.BLUE]
    if bottle.contents == expected:
        print("✓ Revelation logic works correctly!")
    else:
        print("❌ Revelation logic failed!")
        print(f"Got: {bottle.contents}")
        print(f"Expected: {expected}")

if __name__ == "__main__":
    # Test the prompt
    test_multi_unknown_prompt()

    print()
    print("="*60)
    print()

    # Test the logic
    test_revelation_logic()
