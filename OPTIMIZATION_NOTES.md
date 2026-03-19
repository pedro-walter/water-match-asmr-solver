# A* Search Optimization Notes

## Why Threading Won't Help

A* search is inherently **sequential** because:

1. **Priority Queue Ordering**: States must be explored in order of their f-score (g + h). The algorithm needs to always pick the lowest-cost state next.

2. **Closed Set Dependencies**: Each iteration checks if a state was already visited. Parallel exploration could lead to:
   - Race conditions on the closed set
   - Duplicate work
   - Lost optimality guarantees

3. **Python's GIL**: Python's Global Interpreter Lock prevents true parallelism for CPU-bound tasks. Threading would add overhead without speed benefits.

## What Actually Helps

### 1. Better Heuristics (Most Impact)
The current heuristic guides the search. Improvements:
- Weight completed bottles higher
- Prioritize moves that consolidate colors
- Penalize moves that mix colors

### 2. Intelligent Pruning
- Skip obviously bad moves
- Detect dead-end states early
- Limit depth in certain branches

### 3. Memory/Speed Optimizations
- Use faster data structures
- Cache repeated calculations
- Reduce state copying overhead

### 4. Alternative: Parallel Search Strategies
Run multiple independent searches with different parameters:
- Different heuristic weights
- Different move orderings
- Different initial strategies

## Current Performance

The solver is already quite fast:
- **1,000 iterations in <1 second**
- Processing ~250,000 states in ~400 seconds
- The bottleneck is search space size, not CPU speed

## The Real Issue

Your puzzle has:
- 22 bottles
- 6 locked bottles with complex conditions
- 3 unknown colors
- Only 1 empty bottle

This creates an **exponentially large search space**. The solver explored 250,000+ states and is still searching because the path to complete 2 CYAN bottles (to unlock bottle 5) is complex.

## Practical Solutions

### Option 1: Improve the Heuristic
Make the heuristic better at recognizing progress toward CYAN completion.

### Option 2: Add Subgoals
Teach the solver to recognize that unlocking bottle 5 is a necessary subgoal.

### Option 3: Simplify the Puzzle
- Add more empty bottles for working space
- Reduce lock complexity
- Separate the unknown revelation from other goals

### Option 4: Iterative Deepening
Instead of pure A*, use iterative deepening to find approximate solutions faster.

## Recommendation

Let the current search finish (it's already at 400k+ iterations). The 10M limit should be enough to find a solution or determine if one exists.

If it times out, we can:
1. Improve the heuristic to prioritize CYAN completion
2. Add domain-specific knowledge about locks
3. Use a different search strategy (IDA*, beam search, etc.)
