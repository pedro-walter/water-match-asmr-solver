import heapq
from typing import List, Tuple, Optional, Dict
from models import Color
from play_area import PlayArea

class GameState:
    """Immutable, hashable representation of game state for search algorithm."""

    def __init__(self, bottles: tuple, locked_bottles: frozenset,
                 completed_bottles: frozenset, completed_colors: Dict[Color, int],
                 lock_conditions: Dict[int, 'LockCondition'] = None):
        """
        Create an immutable game state.

        Args:
            bottles: Tuple of tuples representing bottle contents
            locked_bottles: Frozenset of locked bottle indices
            completed_bottles: Frozenset of completed bottle indices
            completed_colors: Dictionary mapping Color to count
            lock_conditions: Dictionary mapping bottle number to LockCondition
        """
        self.bottles = bottles  # tuple of tuples
        self.locked_bottles = locked_bottles
        self.completed_bottles = completed_bottles
        self.completed_colors = dict(completed_colors)  # Make a copy
        self.lock_conditions = lock_conditions or {}

    def __hash__(self):
        """Hash based on bottle contents only for duplicate detection."""
        return hash(self.bottles)

    def __eq__(self, other):
        """Equality based on bottle contents."""
        if not isinstance(other, GameState):
            return False
        return self.bottles == other.bottles

    def is_goal(self) -> bool:
        """Check if this state represents a solved puzzle."""
        for bottle_contents in self.bottles:
            # Empty bottles are OK
            if len(bottle_contents) == 0:
                continue
            # Non-empty bottles must be complete (4 of the same color)
            if len(bottle_contents) != 4:
                return False
            if not all(c == bottle_contents[0] for c in bottle_contents):
                return False
            # Bottles with UNKNOWN colors are not complete
            if bottle_contents[0] == Color.UNKNOWN:
                return False
        return True

    def apply_move(self, from_idx: int, to_idx: int) -> Optional['GameState']:
        """
        Apply a move and return a new GameState.

        Args:
            from_idx: Source bottle index
            to_idx: Target bottle index

        Returns:
            New GameState after the move, or None if move is invalid
        """
        # Convert to mutable lists for modification
        bottles_list = [list(bottle) for bottle in self.bottles]

        from_bottle = bottles_list[from_idx]
        to_bottle = bottles_list[to_idx]

        # Validate move
        if len(from_bottle) == 0:
            return None
        if len(to_bottle) == 4:
            return None

        from_color = from_bottle[-1]

        # Check if target bottle can accept the color
        if len(to_bottle) > 0 and to_bottle[-1] != from_color:
            return None

        # Count consecutive colors from top of source
        count = 1
        for i in range(len(from_bottle) - 2, -1, -1):
            if from_bottle[i] == from_color:
                count += 1
            else:
                break

        # Check space in target
        space_available = 4 - len(to_bottle)
        if space_available < count:
            return None

        # Perform the transfer
        for _ in range(count):
            color = from_bottle.pop()
            to_bottle.append(color)

        # Convert back to tuples
        new_bottles = tuple(tuple(bottle) for bottle in bottles_list)

        # Update completed bottles and colors
        new_completed = set()
        new_completed_colors = {}

        for i, bottle_contents in enumerate(new_bottles):
            if len(bottle_contents) == 4 and all(c == bottle_contents[0] for c in bottle_contents):
                new_completed.add(i)
                color = bottle_contents[0]
                new_completed_colors[color] = new_completed_colors.get(color, 0) + 1

        # Update locked bottles based on new completion state
        new_locked = set()
        for bottle_idx, lock_condition in self.lock_conditions.items():
            # Check if lock condition is met
            if lock_condition.color is None:
                # ANY color - check total completed count
                if len(new_completed) < lock_condition.count:
                    new_locked.add(bottle_idx)
            else:
                # Specific color - check that color's count
                if new_completed_colors.get(lock_condition.color, 0) < lock_condition.count:
                    new_locked.add(bottle_idx)

        return GameState(
            new_bottles,
            frozenset(new_locked),
            frozenset(new_completed),
            new_completed_colors,
            self.lock_conditions
        )

    def __repr__(self):
        return f"GameState({len(self.bottles)} bottles, {len(self.completed_bottles)} complete)"


class SearchNode:
    """Node in the A* search tree."""

    def __init__(self, state: GameState, parent: Optional['SearchNode'] = None,
                 move: Optional[Tuple[int, int]] = None, g_score: int = 0, h_score: float = 0):
        """
        Create a search node.

        Args:
            state: The game state at this node
            parent: Parent node in the search tree
            move: The move that led to this state (from_idx, to_idx)
            g_score: Cost from start (number of moves)
            h_score: Heuristic estimate to goal
        """
        self.state = state
        self.parent = parent
        self.move = move
        self.g_score = g_score
        self.h_score = h_score

    def f_score(self) -> float:
        """Total score: g + h"""
        return self.g_score + self.h_score

    def __lt__(self, other):
        """Comparison for heapq (priority queue)."""
        return self.f_score() < other.f_score()

    def __repr__(self):
        return f"SearchNode(g={self.g_score}, h={self.h_score:.2f}, f={self.f_score():.2f})"


class Solver:
    """A* search solver for water sort puzzles."""

    def __init__(self, initial_play_area: PlayArea):
        """
        Initialize the solver with a starting game state.

        Args:
            initial_play_area: The initial PlayArea configuration
        """
        self.initial_play_area = initial_play_area
        self.current_state = initial_play_area.to_game_state()
        self.best_partial_node = None  # Best state found when no complete solution exists
        self.best_partial_iteration = 0  # Iteration when best state was found

    def solve_until_unknown(self, max_iterations: int = 10000000,
                           progress_callback=None) -> Tuple[List[Tuple[int, int]], str]:
        """
        Run A* search until an unknown is revealed or puzzle is solved.

        Args:
            max_iterations: Maximum number of iterations before timeout
            progress_callback: Optional callback function(iteration, queue_size, closed_size)

        Returns:
            Tuple of (moves_list, status) where status is:
            - "SOLVED": Puzzle is completely solved
            - "UNKNOWN_REVEALED": A move would reveal an UNKNOWN
            - "NO_SOLUTION": No solution found
            - "TIMEOUT": Max iterations reached
        """
        open_set = []
        # Maps state -> best g_score seen so far (replaces separate closed_set)
        best_g: Dict[GameState, int] = {}
        iteration = 0

        start_node = SearchNode(
            self.current_state,
            g_score=0,
            h_score=self._heuristic(self.current_state)
        )

        heapq.heappush(open_set, start_node)
        best_g[self.current_state] = 0

        # Track best state found (most completed bottles)
        best_node = start_node
        best_completed_count = len(start_node.state.completed_bottles)

        while open_set:
            iteration += 1

            # Check timeout
            if iteration > max_iterations:
                if progress_callback:
                    progress_callback(iteration, len(open_set), len(best_g), "TIMEOUT")
                # Store best partial solution
                self.best_partial_node = best_node
                return [], "TIMEOUT"

            # Progress reporting every 1000 iterations
            if progress_callback and iteration % 1000 == 0:
                progress_callback(iteration, len(open_set), len(best_g), "SEARCHING")
            current = heapq.heappop(open_set)

            # Check if goal
            if current.state.is_goal():
                if progress_callback:
                    progress_callback(iteration, len(open_set), len(best_g), "SOLVED")
                path = self._reconstruct_path(current)
                return path, "SOLVED"

            # Skip if a better path to this state was already expanded
            if current.g_score > best_g.get(current.state, float('inf')):
                continue

            # Track best state (most completed bottles)
            completed_count = len(current.state.completed_bottles)
            if completed_count > best_completed_count:
                best_completed_count = completed_count
                best_node = current
                self.best_partial_iteration = iteration

            # Generate valid moves
            valid_moves = self._generate_valid_moves(current.state)

            for move in valid_moves:
                # Check if move reveals unknown
                if self._is_revealing_unknown(current.state, move):
                    if progress_callback:
                        progress_callback(iteration, len(open_set), len(best_g), "UNKNOWN_REVEALED")
                    path = self._reconstruct_path(current)
                    path.append(move)
                    return path, "UNKNOWN_REVEALED"

                # Apply move
                new_state = current.state.apply_move(*move)
                if new_state is None:
                    continue

                # Only enqueue if this is the best path to this state
                g_score = current.g_score + 1
                if g_score >= best_g.get(new_state, float('inf')):
                    continue

                best_g[new_state] = g_score
                h_score = self._heuristic(new_state)
                successor = SearchNode(new_state, current, move, g_score, h_score)

                heapq.heappush(open_set, successor)

        # Exhausted search space
        if progress_callback:
            progress_callback(iteration, 0, len(best_g), "NO_SOLUTION")

        # Store best partial solution
        self.best_partial_node = best_node
        return [], "NO_SOLUTION"

    def resume_from(self, current_play_area: PlayArea) -> None:
        """
        Resume solving from an updated state (after unknown revealed).

        Args:
            current_play_area: The updated PlayArea with revealed color
        """
        self.current_state = current_play_area.to_game_state()

    def get_best_partial_solution(self) -> Tuple[List[Tuple[int, int]], int, int]:
        """
        Get the best partial solution found during the last search.

        Returns:
            Tuple of (moves_list, completed_count, iteration) where:
            - moves_list: List of moves to reach the best state
            - completed_count: Number of bottles completed in that state
            - iteration: Iteration number when this best state was found
        """
        if self.best_partial_node is None:
            return [], 0, 0

        path = self._reconstruct_path(self.best_partial_node)
        completed_count = len(self.best_partial_node.state.completed_bottles)
        return path, completed_count, self.best_partial_iteration

    def _generate_valid_moves(self, state: GameState) -> List[Tuple[int, int]]:
        """
        Generate all valid moves from the current state.

        Args:
            state: The current game state

        Returns:
            List of (from_idx, to_idx) tuples
        """
        valid_moves = []

        # Find the first empty, unlocked, non-completed bottle index.
        # We only allow pouring into this one empty to avoid symmetric states.
        first_empty_idx = None
        for j, bottle in enumerate(state.bottles):
            if len(bottle) == 0 and j not in state.locked_bottles and j not in state.completed_bottles:
                first_empty_idx = j
                break

        for i, from_bottle in enumerate(state.bottles):
            # Skip locked, completed, or empty bottles
            if i in state.locked_bottles:
                continue
            if i in state.completed_bottles:
                continue
            if len(from_bottle) == 0:
                continue

            from_color = from_bottle[-1]
            from_consecutive = self._count_consecutive_top(from_bottle)

            # Skip pouring a uniform bottle into an empty — it's a no-op shuffle
            is_uniform = (from_consecutive == len(from_bottle))

            for j, to_bottle in enumerate(state.bottles):
                if i == j:
                    continue

                # Skip locked, completed, or full bottles
                if j in state.locked_bottles:
                    continue
                if j in state.completed_bottles:
                    continue
                if len(to_bottle) == 4:
                    continue

                if len(to_bottle) == 0:
                    # Only pour into the first empty bottle (symmetry breaking)
                    if j != first_empty_idx:
                        continue
                    # Don't pour a uniform bottle into empty — pointless swap
                    if is_uniform:
                        continue
                    valid_moves.append((i, j))
                    continue

                # Non-empty bottle must have matching top color
                to_color = to_bottle[-1]
                if from_color == to_color:
                    space = 4 - len(to_bottle)
                    if space >= from_consecutive:
                        valid_moves.append((i, j))

        return valid_moves

    def _is_revealing_unknown(self, state: GameState, move: Tuple[int, int]) -> bool:
        """
        Check if a move would reveal an UNKNOWN color.

        Args:
            state: Current game state
            move: The move to check (from_idx, to_idx)

        Returns:
            True if the move reveals an UNKNOWN
        """
        from_idx, to_idx = move
        from_bottle = state.bottles[from_idx]

        if len(from_bottle) == 0:
            return False

        # Check if there's an UNKNOWN in the colors being transferred
        top_color = from_bottle[-1]
        if top_color == Color.UNKNOWN:
            return True

        # Check if removing top colors reveals an UNKNOWN
        count = self._count_consecutive_top(from_bottle)
        if count < len(from_bottle):
            # There's a color below the transferred ones
            revealed_idx = len(from_bottle) - count - 1
            if from_bottle[revealed_idx] == Color.UNKNOWN:
                return True

        return False

    def _heuristic(self, state: GameState) -> float:
        """
        Calculate heuristic estimate for the state.

        If unknowns exist, focus only on revealing them (puzzle is unsolvable until then).
        If no unknowns, focus on solving the puzzle.

        Args:
            state: The game state to evaluate

        Returns:
            Heuristic score (lower is better)
        """
        # Check if there are any unknowns remaining
        unknown_count = 0
        for bottle in state.bottles:
            unknown_count += bottle.count(Color.UNKNOWN)

        if unknown_count > 0:
            # Unknowns exist: ignore everything else, just reveal them
            return self._unknown_bonus(state)
        else:
            # No unknowns: focus on solving the puzzle
            return self._color_fragmentation_heuristic(state)

    def _color_fragmentation_heuristic(self, state: GameState) -> float:
        """
        For each color, count how many bottles it's spread across.
        Merging N bottles into 1 requires at least N-1 moves.
        Admissible: each move reduces a color's bottle count by at most 1.
        """
        # Map each color to the number of (non-completed) bottles it appears in
        color_bottles: Dict[Color, int] = {}

        for i, bottle in enumerate(state.bottles):
            if len(bottle) == 0:
                continue
            if i in state.completed_bottles:
                continue

            seen_in_bottle = set()
            for color in bottle:
                seen_in_bottle.add(color)
            for color in seen_in_bottle:
                color_bottles[color] = color_bottles.get(color, 0) + 1

        # Each color spread across N bottles needs at least N-1 moves
        return sum(count - 1 for count in color_bottles.values())

    def _unknown_bonus(self, state: GameState) -> float:
        """
        Give bonus for states with fewer unknowns.
        Encourages revealing unknowns early.
        """
        unknown_count = 0
        for bottle in state.bottles:
            unknown_count += bottle.count(Color.UNKNOWN)

        # Negative = bonus (lower f-score)
        return -0.5 * unknown_count

    def _count_consecutive_top(self, bottle: tuple) -> int:
        """Count consecutive colors from the top of a bottle."""
        if len(bottle) == 0:
            return 0

        top_color = bottle[-1]
        count = 1

        for i in range(len(bottle) - 2, -1, -1):
            if bottle[i] == top_color:
                count += 1
            else:
                break

        return count

    def _reconstruct_path(self, node: SearchNode) -> List[Tuple[int, int]]:
        """
        Reconstruct the path from start to this node.

        Args:
            node: The goal node

        Returns:
            List of moves from start to goal
        """
        path = []
        current = node

        while current.parent is not None:
            if current.move is not None:
                path.append(current.move)
            current = current.parent

        path.reverse()
        return path
