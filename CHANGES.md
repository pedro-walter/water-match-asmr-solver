# Recent Improvements

## Simplified Lock Format

The lock condition format has been simplified for better readability.

### Old Format (No longer used)
```json
{
  "lock_condition": {
    "type": "any_completed",
    "count": 6
  }
}
```

```json
{
  "lock_condition": {
    "type": "color_completed",
    "count": 2,
    "color": "CYAN"
  }
}
```

### New Format (Current)
```json
{"locked": {"count": 6, "color": "ANY"}}
```

```json
{"locked": {"count": 2, "color": "CYAN"}}
```

**Benefits:**
- Simpler and more concise
- `"ANY"` is clearer than `"type": "any_completed"`
- Fewer fields to remember
- More intuitive to read and write

## Summary of All New Features

### 1. Column Display Layout ✅
- **NEW**: Bottles now display in vertical columns when using `columns` format
- Respects skew offsets for flexible positioning
- Bottles stack vertically within columns
- Much clearer visualization of complex puzzles
- Automatically used when `columns` format is detected
- Falls back to horizontal layout for standard format

**Example:**
```
                  #7
                ┌────┐
          #4    │ 🟥 │
        ┌────┐  │ 🟥 │
  #1    │ 🟧 │  │ 🟥 │
┌────┐  │ 🟧 │  │ 🟥 │
│ 🟪 │  │ 🟨 │  └────┘
│ 🟪 │  │ ❓ │    #8
│ 🟩 │  └────┘  ┌────┐
│ 🟩 │    #5 🔒  │ 🟥 │
└────┘  ┌────┐  │ 🟦 │
        │ 🟥 │  │ 🟩 │
        │ ❓ │  │ 🟧 │
        │ ❓ │  └────┘
        │ ❓ │
        └────┘
```

### 2. Simplified Bottle Labels ✅
- Changed from `"Bottle #XX"` to simply `"#XX"`
- Cleaner, more compact display
- Works in both horizontal and column layouts

### 3. Simplified Lock Format ✅
- Changed from `lock_condition` to `locked`
- Use `{"count": N, "color": "X"}` format
- `"color": "ANY"` for any completed bottle
- `"color": "RED"`, `"CYAN"`, etc. for specific colors

### 4. Color Mnemonics ✅
Single-character shortcuts for colors (order: **RPAGYOUC?**):
- `R` = RED 🟥
- `P` = PURPLE 🟪
- `A` = GREY ⬜ (grAy)
- `G` = GREEN 🟩
- `Y` = YELLOW 🟨
- `O` = ORANGE 🟧
- `U` or `B` = BLUE 🟦 (blUe)
- `C` = CYAN 🩵
- `?` = UNKNOWN ❓

### 5. String Notation for Bottle Contents ✅
Compact format using mnemonics:
```json
{"contents": "RYBO"}   // RED, YELLOW, BLUE, ORANGE
{"contents": "???R"}   // Three unknowns and a red
{"contents": ""}       // Empty bottle
```

### 6. GREY vs GRAY Support ✅
Both spellings accepted:
- `["GREY"]` ✓
- `["GRAY"]` ✓

### 7. Column Layout Format ✅
New JSON format for arranging bottles in columns:
```json
{
  "columns": [
    {
      "skew": 0,
      "bottles": [
        {"contents": "GCAR"},
        {"contents": "GGPP"}
      ]
    },
    {
      "skew": 0.5,
      "bottles": [
        {"contents": "YOO", "locked": {"count": 6, "color": "ANY"}},
        {"contents": "?YOO"}
      ]
    }
  ]
}
```

**Features:**
- `skew`: Vertical offset in bottle heights
- Auto-numbering: top-to-bottom, left-to-right
- Supports both array and string notation for contents
- Works with lock conditions

## Examples

### Example 1: Simple Lock (Standard Format)
```json
{
  "bottles": [
    {"number": 0, "contents": "RRR?"},
    {"number": 1, "contents": "BBB?"},
    {"number": 2, "contents": [], "locked": {"count": 1, "color": "ANY"}},
    {"number": 3, "contents": [], "locked": {"count": 1, "color": "RED"}}
  ]
}
```

### Example 2: Column Layout with Locks
```json
{
  "columns": [
    {
      "skew": 0,
      "bottles": [
        {"contents": "GCAR"},
        {"contents": "GGPP"}
      ]
    },
    {
      "skew": 0.5,
      "bottles": [
        {"contents": "YOO", "locked": {"count": 6, "color": "ANY"}},
        {"contents": "???R", "locked": {"count": 2, "color": "CYAN"}}
      ]
    }
  ]
}
```

## Migration Guide

### Updating Old Puzzles

**Before:**
```json
{
  "lock_condition": {
    "type": "any_completed",
    "count": 6
  }
}
```

**After:**
```json
{
  "locked": {"count": 6, "color": "ANY"}
}
```

**Before:**
```json
{
  "lock_condition": {
    "type": "color_completed",
    "count": 2,
    "color": "CYAN"
  }
}
```

**After:**
```json
{
  "locked": {"count": 2, "color": "CYAN"}
}
```

## Testing

All features have been tested and verified:

```bash
# Test simplified lock format
python3 test_new_format.py

# Test column layout
python3 test_columns.py

# Test UI alignment
python3 test_alignment.py
```

## Backward Compatibility

The old `lock_condition` format is still parsed internally but automatically converted to the new format. However, saved files will use the new `locked` format.
