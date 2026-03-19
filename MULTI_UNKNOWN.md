# Multiple Unknown Colors Feature

## Overview

When a move reveals UNKNOWN colors, the solver now supports revealing **multiple consecutive unknowns at once** with a single input.

## How It Works

### Single Unknown (Original Behavior)

When one unknown is revealed:
```
🔍 UNKNOWN color revealed in Bottle #5!
What color is it?
Available colors: RED, PURPLE, GREY, GREEN, YELLOW, ORANGE, BLUE, CYAN

> RED
```

### Multiple Unknowns (New Feature)

When multiple consecutive unknowns are revealed:
```
🔍 3 UNKNOWN colors revealed in Bottle #5!
What color(s) are they?
Format: 'COLOR' or 'COUNT COLOR' or 'COLOR COUNT'
Example: '3 RED' or 'RED 3' (means next 3 blocks are RED)
Available colors: RED, PURPLE, GREY, GREEN, YELLOW, ORANGE, BLUE, CYAN

> 3 RED
```

## Input Formats

### Format 1: Just the color (reveals 1 block)
```
> RED
```
Reveals the top 1 unknown as RED.

### Format 2: Count then color
```
> 3 RED
```
Reveals the top 3 unknowns as RED.

### Format 3: Color then count
```
> RED 3
```
Also reveals the top 3 unknowns as RED.

## Examples

### Example 1: All Same Color

Bottle has: `[?, ?, ?, RED]` (3 unknowns on top)

**Input:** `3 BLUE`

**Result:** `[BLUE, BLUE, BLUE, RED]`

### Example 2: Mixed Colors

Bottle has: `[?, ?, ?, RED]` (3 unknowns on top)

**First revelation:**
```
> 2 BLUE
```
**Result:** `[?, BLUE, BLUE, RED]`

**Solver continues and reveals the remaining unknown:**
```
🔍 UNKNOWN color revealed in Bottle #5!
> GREEN
```
**Final result:** `[GREEN, BLUE, BLUE, RED]`

### Example 3: Partial Revelation

If you have 4 unknowns but only know 2 of them:

```
🔍 4 UNKNOWN colors revealed in Bottle #5!
> 2 YELLOW
```

The solver will:
1. Reveal the top 2 as YELLOW
2. Resume solving
3. Ask about the remaining 2 unknowns later (if they get revealed)

## Implementation Details

### Counting Unknowns

The system counts **consecutive unknowns from the top** of the bottle:
- `[?, ?, ?, RED]` → 3 unknowns
- `[RED, ?, ?, ?]` → 3 unknowns (from top)
- `[?, RED, ?, ?]` → 2 unknowns (top 2, stops at RED)

### Revelation Order

Colors are revealed from **top to bottom**:
1. Top unknown (index 3) gets the color first
2. Then next down (index 2)
3. And so on

### Validation

The system prevents:
- Revealing more blocks than unknowns present
- Using UNKNOWN as a color
- Invalid counts (must be ≥ 1)

## Use Cases

### When to Use Multiple Revelation

1. **Clearly visible stacks**: When you can see multiple blocks are the same color
2. **Save time**: Instead of typing the same color 3 times, type it once with a count
3. **Pattern recognition**: When a bottle obviously has multiple of the same color

### When to Reveal Individually

1. **Uncertain**: When you're not sure if consecutive blocks are the same
2. **Mixed colors**: When the unknowns are different colors
3. **Safety**: Revealing one at a time lets you verify each step

## Testing

### Test the prompt:
```bash
python3 test_multi_unknown.py
```

### Test with example puzzle:
```bash
python3 main.py example_multi_unknown.json
```

This puzzle has 3 consecutive unknowns followed by a RED block. You can test:
- Revealing all 3: `3 BLUE`
- Revealing partially: `2 BLUE` then `1 GREEN`
- Revealing one at a time: `BLUE`, `BLUE`, `BLUE`

## Tips

1. **Count carefully**: Make sure you count the correct number of unknowns
2. **Use partial revelation**: If unsure, reveal what you know and let the solver ask again later
3. **Format flexibility**: Use whichever format is most natural (`3 RED` or `RED 3`)
4. **Single unknown default**: If you just type a color, it assumes count=1
