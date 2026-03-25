import heapq
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from math import ceil
from typing import List, Tuple, Optional, Dict
from models import Color
from play_area import PlayArea

try:
    import rust_solver as _rust_solver
    _RUST_AVAILABLE = True
except ImportError:
    _RUST_AVAILABLE = False


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------

class GameState:
    """Immutable, hashable representation of game state for search algorithm."""

    def __init__(self, bottles: tuple, locked_bottles: frozenset,
                 completed_bottles: frozenset, completed_colors: Dict[Color, int],
                 lock_conditions: Dict[int, 'LockCondition'] = None,
                 hidden_slots_state: frozenset = None):
        self.bottles = bottles  # tuple of tuples (actual colors, not masked)
        self.locked_bottles = locked_bottles
        self.completed_bottles = completed_bottles
        self.completed_colors = dict(completed_colors)
        self.lock_conditions = lock_conditions or {}
        # frozenset of (bottle_idx, slot_idx) pairs that are currently hidden
        self.hidden_slots_state = hidden_slots_state if hidden_slots_state is not None else frozenset()

    def __hash__(self):
        return hash((self.bottles, self.hidden_slots_state))

    def __eq__(self, other):
        if not isinstance(other, GameState):
            return False
        return self.bottles == other.bottles and self.hidden_slots_state == other.hidden_slots_state

    def is_goal(self) -> bool:
        for i, bottle_contents in enumerate(self.bottles):
            if len(bottle_contents) == 0:
                continue
            if len(bottle_contents) != 4:
                return False
            if not all(c == bottle_contents[0] for c in bottle_contents):
                return False
            if bottle_contents[0] == Color.UNKNOWN:
                return False
            # A bottle with any hidden slot is not complete
            if any((i, j) in self.hidden_slots_state for j in range(4)):
                return False
        return True

    def apply_move(self, from_idx: int, to_idx: int) -> Optional['GameState']:
        bottles_list = [list(bottle) for bottle in self.bottles]
        from_bottle = bottles_list[from_idx]
        to_bottle = bottles_list[to_idx]

        if len(from_bottle) == 0:
            return None
        if len(to_bottle) == 4:
            return None

        top_idx = len(from_bottle) - 1
        # Hidden top: cannot pour (hidden slots are always at bottom, but guard anyway)
        if (from_idx, top_idx) in self.hidden_slots_state:
            return None

        from_color = from_bottle[top_idx]
        if len(to_bottle) > 0 and to_bottle[-1] != from_color:
            return None

        # Count consecutive visible same-color slots from top (stop at hidden boundary)
        count = 1
        for i in range(top_idx - 1, -1, -1):
            if (from_idx, i) in self.hidden_slots_state:
                break
            if from_bottle[i] == from_color:
                count += 1
            else:
                break

        space_available = 4 - len(to_bottle)
        if space_available < count:
            return None

        for _ in range(count):
            color = from_bottle.pop()
            to_bottle.append(color)

        new_bottles = tuple(tuple(bottle) for bottle in bottles_list)

        # Auto-reveal hidden slot if it's now the new top of from_bottle
        new_hidden = set(self.hidden_slots_state)
        new_from = new_bottles[from_idx]
        if new_from:
            new_top = len(new_from) - 1
            if (from_idx, new_top) in new_hidden:
                revealed_color = new_from[new_top]
                new_hidden.discard((from_idx, new_top))
                # Reveal consecutive same-color hidden slots below
                for j in range(new_top - 1, -1, -1):
                    if (from_idx, j) in new_hidden and new_from[j] == revealed_color:
                        new_hidden.discard((from_idx, j))
                    else:
                        break
        hidden_slots_state_new = frozenset(new_hidden)

        # Completion: full, uniform, no UNKNOWN, no hidden slots remaining
        new_completed = set()
        new_completed_colors = {}
        for i, bottle_contents in enumerate(new_bottles):
            if (len(bottle_contents) == 4 and
                    bottle_contents[0] != Color.UNKNOWN and
                    all(c == bottle_contents[0] for c in bottle_contents) and
                    not any((i, j) in hidden_slots_state_new for j in range(4))):
                new_completed.add(i)
                color = bottle_contents[0]
                new_completed_colors[color] = new_completed_colors.get(color, 0) + 1

        new_locked = set()
        for bottle_idx, lock_condition in self.lock_conditions.items():
            if lock_condition.color is None:
                if len(new_completed) < lock_condition.count:
                    new_locked.add(bottle_idx)
            else:
                if new_completed_colors.get(lock_condition.color, 0) < lock_condition.count:
                    new_locked.add(bottle_idx)

        return GameState(
            new_bottles,
            frozenset(new_locked),
            frozenset(new_completed),
            new_completed_colors,
            self.lock_conditions,
            hidden_slots_state_new,
        )

    def to_key(self) -> bytes:
        """
        Compact bytes key: 2 color nibbles per byte, empty=15, UNKNOWN=14.
        N bottles × 4 slots → N*2 bytes, then sorted hidden (bottle_idx, slot_idx) pairs.
        """
        arr = bytearray()
        for bottle in self.bottles:
            padded = list(bottle) + [None] * (4 - len(bottle))
            for k in range(0, 4, 2):
                c1 = 15 if padded[k] is None else (14 if padded[k] == Color.UNKNOWN else padded[k].value)
                c2 = 15 if padded[k + 1] is None else (14 if padded[k + 1] == Color.UNKNOWN else padded[k + 1].value)
                arr.append((c1 << 4) | c2)
        # Append hidden slots as sorted (bottle_idx, slot_idx) byte pairs
        for bi, si in sorted(self.hidden_slots_state):
            arr.append(bi)
            arr.append(si)
        return bytes(arr)

    def __repr__(self):
        return f"GameState({len(self.bottles)} bottles, {len(self.completed_bottles)} complete)"


# ---------------------------------------------------------------------------
# SearchNode
# ---------------------------------------------------------------------------

class SearchNode:
    """Node in the A* search tree."""

    def __init__(self, state: GameState, parent: Optional['SearchNode'] = None,
                 move: Optional[Tuple[int, int]] = None, g_score: int = 0, h_score: float = 0):
        self.state = state
        self.parent = parent
        self.move = move
        self.g_score = g_score
        self.h_score = h_score

    def f_score(self) -> float:
        return self.g_score + self.h_score

    def __lt__(self, other):
        return self.f_score() < other.f_score()

    def __repr__(self):
        return f"SearchNode(g={self.g_score}, h={self.h_score:.2f}, f={self.f_score():.2f})"


# ---------------------------------------------------------------------------
# Module-level pure functions
# (must be at module level so multiprocessing workers can pickle/call them)
# ---------------------------------------------------------------------------

def _count_consecutive_top(bottle: tuple, hidden: frozenset = frozenset(), bottle_idx: int = 0) -> int:
    """Count consecutive visible same-color slots from the top, stopping at hidden boundaries."""
    if len(bottle) == 0:
        return 0
    top_idx = len(bottle) - 1
    if (bottle_idx, top_idx) in hidden:
        return 0  # Top is hidden, cannot pour
    top_color = bottle[top_idx]
    count = 1
    for i in range(top_idx - 1, -1, -1):
        if (bottle_idx, i) in hidden:
            break
        if bottle[i] == top_color:
            count += 1
        else:
            break
    return count


def _generate_valid_moves(state: GameState) -> List[Tuple[int, int]]:
    valid_moves = []
    hidden = state.hidden_slots_state

    first_empty_idx = None
    for j, bottle in enumerate(state.bottles):
        if len(bottle) == 0 and j not in state.locked_bottles and j not in state.completed_bottles:
            first_empty_idx = j
            break

    for i, from_bottle in enumerate(state.bottles):
        if i in state.locked_bottles:
            continue
        if i in state.completed_bottles:
            continue
        if len(from_bottle) == 0:
            continue

        top_idx = len(from_bottle) - 1
        if (i, top_idx) in hidden:
            continue  # Top is hidden, cannot pour from this bottle

        from_color = from_bottle[top_idx]
        from_consecutive = _count_consecutive_top(from_bottle, hidden, i)
        # Uniform: all visible slots are the same color (from_consecutive == visible slot count)
        visible_len = top_idx + 1  # slots from 0 to top_idx inclusive
        # Count how many visible slots exist (those not in hidden)
        visible_count = sum(1 for k in range(visible_len) if (i, k) not in hidden)
        is_uniform = (from_consecutive == visible_count) and from_color != Color.UNKNOWN

        for j, to_bottle in enumerate(state.bottles):
            if i == j:
                continue
            if j in state.locked_bottles:
                continue
            if j in state.completed_bottles:
                continue
            if len(to_bottle) == 4:
                continue

            if len(to_bottle) == 0:
                if j != first_empty_idx:
                    continue
                if is_uniform:
                    continue
                valid_moves.append((i, j))
                continue

            to_color = to_bottle[-1]
            if from_color == to_color:
                space = 4 - len(to_bottle)
                if space >= from_consecutive:
                    valid_moves.append((i, j))

    return valid_moves


def _is_revealing_unknown(state: GameState, move: Tuple[int, int]) -> bool:
    from_idx, _ = move
    from_bottle = state.bottles[from_idx]
    if len(from_bottle) == 0:
        return False
    top_idx = len(from_bottle) - 1
    top_color = from_bottle[top_idx]
    if top_color == Color.UNKNOWN:
        return True
    count = _count_consecutive_top(from_bottle, state.hidden_slots_state, from_idx)
    if count < len(from_bottle):
        revealed_idx = len(from_bottle) - count - 1
        if from_bottle[revealed_idx] == Color.UNKNOWN:
            return True
    return False


def _is_unlocking_unknown_bottle(state: GameState, new_state: GameState) -> bool:
    """Return True if a newly-unlocked bottle has all-unknown or empty contents."""
    newly_unlocked = state.locked_bottles - new_state.locked_bottles
    for unlocked_idx in newly_unlocked:
        bottle_contents = new_state.bottles[unlocked_idx]
        if len(bottle_contents) == 0 or all(c == Color.UNKNOWN for c in bottle_contents):
            return True
    return False


def _heuristic(state: GameState) -> float:
    accessible_unknown_count = 0
    for i, bottle in enumerate(state.bottles):
        if i not in state.locked_bottles:
            accessible_unknown_count += bottle.count(Color.UNKNOWN)
    if accessible_unknown_count > 0:
        return _unknown_bonus(state)
    return _color_fragmentation_heuristic(state)


def _unknown_bonus(state: GameState) -> float:
    unknown_count = sum(bottle.count(Color.UNKNOWN) for bottle in state.bottles)
    return -0.5 * unknown_count


def _color_fragmentation_heuristic(state: GameState) -> float:
    color_bottles: Dict[Color, int] = {}
    disruption = 0

    for i, bottle in enumerate(state.bottles):
        if len(bottle) == 0:
            continue
        if i in state.completed_bottles:
            continue

        seen_in_bottle = set(c for c in bottle if c != Color.UNKNOWN)
        for color in seen_in_bottle:
            color_bottles[color] = color_bottles.get(color, 0) + 1

        if i not in state.locked_bottles:
            for j in range(1, len(bottle)):
                if bottle[j] != bottle[j - 1]:
                    disruption += 1

    fragmentation = sum(count - 1 for count in color_bottles.values())
    base = max(fragmentation, disruption)

    lock_penalty = 0
    for bottle_idx, lock_cond in state.lock_conditions.items():
        if bottle_idx not in state.locked_bottles:
            continue
        if lock_cond.color is not None:
            have = state.completed_colors.get(lock_cond.color, 0)
            need = lock_cond.count - have
            if need > 0:
                bottles_with_prereq = color_bottles.get(lock_cond.color, 0)
                prereq_fragmentation = max(bottles_with_prereq - need, 0)
                lock_penalty += need * 4 + prereq_fragmentation

    return base + lock_penalty


def _reconstruct_path(node: SearchNode) -> List[Tuple[int, int]]:
    path = []
    current = node
    while current.parent is not None:
        if current.move is not None:
            path.append(current.move)
        current = current.parent
    path.reverse()
    return path


def _astar_search(
    initial_state: GameState,
    heuristic_weight: float,
    max_iterations: int,
    stop_event=None,
    progress_callback=None,
) -> Tuple[List[Tuple[int, int]], str, Optional[SearchNode], int]:
    """
    Core A* search loop.

    Returns (moves, status, best_partial_node, best_partial_iteration).
    Module-level so multiprocessing workers can use it without pickling bound methods.

    status values: SOLVED | UNKNOWN_REVEALED | BOTTLE_UNLOCKED |
                   NO_SOLUTION | TIMEOUT | STOPPED
    """
    open_set = []
    best_g: Dict[bytes, int] = {}
    iteration = 0

    start_node = SearchNode(
        initial_state,
        g_score=0,
        h_score=_heuristic(initial_state) * heuristic_weight,
    )
    heapq.heappush(open_set, start_node)
    best_g[initial_state.to_key()] = 0

    best_node = start_node
    best_completed_count = len(start_node.state.completed_bottles)
    best_iteration = 0

    while open_set:
        iteration += 1

        if iteration > max_iterations:
            if progress_callback:
                progress_callback(iteration, len(open_set), len(best_g), "TIMEOUT")
            return [], "TIMEOUT", best_node, best_iteration

        # Check external stop signal (from parallel coordinator) every 2000 iters
        if stop_event is not None and iteration % 2000 == 0 and stop_event.is_set():
            return [], "STOPPED", best_node, best_iteration

        if progress_callback and iteration % 1000 == 0:
            progress_callback(iteration, len(open_set), len(best_g), "SEARCHING")

        current = heapq.heappop(open_set)

        if current.state.is_goal():
            if progress_callback:
                progress_callback(iteration, len(open_set), len(best_g), "SOLVED")
            return _reconstruct_path(current), "SOLVED", best_node, best_iteration

        if current.g_score > best_g.get(current.state.to_key(), float('inf')):
            continue

        completed_count = len(current.state.completed_bottles)
        if completed_count > best_completed_count:
            best_completed_count = completed_count
            best_node = current
            best_iteration = iteration

        valid_moves = _generate_valid_moves(current.state)

        if current.move is not None:
            prev_from, prev_to = current.move
            valid_moves = [(f, t) for f, t in valid_moves
                           if not (f == prev_to and t == prev_from)]

        for move in valid_moves:
            if _is_revealing_unknown(current.state, move):
                if progress_callback:
                    progress_callback(iteration, len(open_set), len(best_g), "UNKNOWN_REVEALED")
                path = _reconstruct_path(current)
                path.append(move)
                return path, "UNKNOWN_REVEALED", best_node, best_iteration

            new_state = current.state.apply_move(*move)
            if new_state is None:
                continue

            if _is_unlocking_unknown_bottle(current.state, new_state):
                if progress_callback:
                    progress_callback(iteration, len(open_set), len(best_g), "BOTTLE_UNLOCKED")
                path = _reconstruct_path(current)
                path.append(move)
                return path, "BOTTLE_UNLOCKED", best_node, best_iteration

            g_score = current.g_score + 1
            new_key = new_state.to_key()
            if g_score >= best_g.get(new_key, float('inf')):
                continue

            best_g[new_key] = g_score
            h_score = _heuristic(new_state) * heuristic_weight
            successor = SearchNode(new_state, current, move, g_score, h_score)
            heapq.heappush(open_set, successor)

    if progress_callback:
        progress_callback(iteration, 0, len(best_g), "NO_SOLUTION")
    return [], "NO_SOLUTION", best_node, best_iteration


def _parallel_worker(task: tuple) -> Tuple[List, str]:
    """
    Module-level worker function for ProcessPoolExecutor.
    Runs A* from a partitioned starting state and prepends the prefix moves.
    """
    state, prefix_moves, heuristic_weight, max_iterations, stop_event = task

    if stop_event is not None and stop_event.is_set():
        return [], "STOPPED"

    moves, status, _, _ = _astar_search(
        state, heuristic_weight, max_iterations, stop_event=stop_event
    )

    if moves is not None and len(moves) > 0:
        moves = list(prefix_moves) + moves
    elif status in ("SOLVED",):
        moves = list(prefix_moves)  # Partition start is already the goal

    return moves, status


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

class Solver:
    """A* search solver for water sort puzzles."""

    def __init__(self, initial_play_area: PlayArea):
        self.initial_play_area = initial_play_area
        self.current_state = initial_play_area.to_game_state()
        self.best_partial_node = None
        self.best_partial_iteration = 0
        self._rust_best_partial = None  # (moves, completed_count, iteration) from Rust

        num_bottles = len(initial_play_area.bottles)
        if num_bottles <= 12:
            self.heuristic_weight = 1.0
        else:
            lock_difficulty = self._compute_lock_difficulty(initial_play_area)
            self.heuristic_weight = 2.0 + lock_difficulty

    def _compute_lock_difficulty(self, play_area: PlayArea) -> float:
        """
        Estimate extra heuristic weight needed based on lock difficulty.
        Returns a value in [0, 3] added on top of the base weight of 2.0.
        """
        if not play_area.lock_conditions:
            return 0.0

        empty_bottles = sum(1 for b in play_area.bottles if len(b.contents) == 0)
        buffer_count = max(empty_bottles, 1)

        bottles_per_color: Dict[Color, int] = {}
        for bottle in play_area.bottles:
            seen = set(c for c in bottle.contents if c != Color.UNKNOWN)
            for color in seen:
                bottles_per_color[color] = bottles_per_color.get(color, 0) + 1

        max_ratio = 0.0
        for _, lock_cond in play_area.lock_conditions.items():
            if lock_cond.color is None:
                continue
            spread = bottles_per_color.get(lock_cond.color, 0)
            ratio = max(spread - lock_cond.count, 0) / buffer_count
            max_ratio = max(max_ratio, ratio)

        return min(max_ratio, 3.0)

    # ------------------------------------------------------------------
    # Single-threaded search
    # ------------------------------------------------------------------

    def solve_until_unknown(self, max_iterations: int = 100000000,
                            progress_callback=None) -> Tuple[List[Tuple[int, int]], str]:
        """
        Run A* search (single-threaded) until an unknown is revealed or puzzle is solved.
        """
        moves, status, best_node, best_iter = _astar_search(
            self.current_state,
            self.heuristic_weight,
            max_iterations,
            progress_callback=progress_callback,
        )
        self.best_partial_node = best_node
        self.best_partial_iteration = best_iter
        return moves, status

    # ------------------------------------------------------------------
    # Parallel search
    # ------------------------------------------------------------------

    def _generate_partitions(self, depth: int = 2) -> List[Tuple[List, GameState]]:
        """
        Enumerate all states reachable in `depth` moves from the current state.
        Stops before moves that would reveal unknowns or unlock hidden bottles
        (those are handled by the interactive loop, not the parallel workers).

        Returns list of (prefix_moves, starting_state).
        """
        current_level: List[Tuple[List, GameState]] = [([], self.current_state)]

        for _ in range(depth):
            next_level: List[Tuple[List, GameState]] = []
            for prefix, state in current_level:
                for move in _generate_valid_moves(state):
                    # Skip moves that would trigger an interactive pause
                    if _is_revealing_unknown(state, move):
                        continue
                    new_state = state.apply_move(*move)
                    if new_state is None:
                        continue
                    if _is_unlocking_unknown_bottle(state, new_state):
                        continue
                    next_level.append((prefix + [move], new_state))
            if not next_level:
                break
            current_level = next_level

        return current_level

    def _state_to_dict(self, state: GameState) -> dict:
        """Serialize GameState to the dict format expected by rust_solver.solve_parallel."""
        bottles = [list(c.value if c != Color.UNKNOWN else 99 for c in bottle)
                   for bottle in state.bottles]
        locked_bottles = list(state.locked_bottles)
        completed_bottles = list(state.completed_bottles)
        completed_colors = {c.value: count for c, count in state.completed_colors.items()}
        lock_conditions = {}
        for bi, lc in state.lock_conditions.items():
            lock_conditions[bi] = {
                "count": lc.count,
                "color": lc.color.value if lc.color is not None else -1,
            }
        hidden_slots = [[bi, si] for bi, si in sorted(state.hidden_slots_state)]
        return {
            "bottles": bottles,
            "locked_bottles": locked_bottles,
            "completed_bottles": completed_bottles,
            "completed_colors": completed_colors,
            "lock_conditions": lock_conditions,
            "hidden_slots": hidden_slots,
        }

    def solve_parallel(
        self,
        max_iterations: int = 100000000,
        tree_size: int = 100000,
        algorithm: str = "mcts",
        num_processes: int = None,
        progress_callback=None,
    ) -> Tuple[List[Tuple[int, int]], str]:
        """
        Parallel search using the selected algorithm.

        algorithm:
          "mcts"   — Rust MCTS with parallel partitioning (default)
          "dfs"    — Rust exhaustive DFS; proves NoSolution when space is fully explored
          "python" — Original Python A* (no Rust)
        """
        if _RUST_AVAILABLE and algorithm != "python":
            print(f"Using Rust solver ({algorithm.upper()})...")
            state_dict = self._state_to_dict(self.current_state)
            moves, status, bp_moves, bp_completed, bp_iter = _rust_solver.solve_parallel(
                state_dict, self.heuristic_weight, max_iterations, tree_size, algorithm
            )
            self._rust_best_partial = (list(bp_moves), int(bp_completed), int(bp_iter))
            return list(moves), status

        if num_processes is None:
            num_processes = mp.cpu_count()

        min_partitions = num_processes * 2
        partitions = None
        for depth in range(2, 6):
            partitions = self._generate_partitions(depth=depth)
            n = len(partitions)
            if n >= min_partitions:
                break
            if n == 0:
                break

        n = len(partitions)
        if n < min_partitions:
            print(f"Only {n} partitions found (tried up to depth {depth}), running single-threaded.")
            return self.solve_until_unknown(max_iterations, progress_callback)

        # Normalise iterations so each core does ≈ max_iterations total work.
        # ceil(n / num_processes) = sequential rounds per core.
        rounds_per_core = ceil(n / num_processes)
        iter_per_partition = max(max_iterations // rounds_per_core, 200_000)

        print(f"Parallel A*: {n} partitions | {num_processes} workers | "
              f"{iter_per_partition:,} iter/partition "
              f"(~{rounds_per_core} rounds/core)")

        completed = 0
        best_no_sol_status = "TIMEOUT"
        self.best_partial_node = None

        with mp.Manager() as manager:
            stop_event = manager.Event()

            tasks = [
                (state, tuple(prefix), self.heuristic_weight, iter_per_partition, stop_event)
                for prefix, state in partitions
            ]

            with ProcessPoolExecutor(max_workers=num_processes) as executor:
                futures = {executor.submit(_parallel_worker, task): i
                           for i, task in enumerate(tasks)}
                try:
                    for future in as_completed(futures):
                        try:
                            moves, status = future.result()
                        except Exception as exc:
                            print(f"  Worker raised: {exc}")
                            completed += 1
                            continue

                        completed += 1

                        if progress_callback:
                            progress_callback(completed, n - completed, completed, status)
                        else:
                            print(f"  [{completed}/{n}] {status}"
                                  + (f"  {len(moves)} moves" if moves else ""))

                        if status not in ("TIMEOUT", "NO_SOLUTION", "STOPPED"):
                            stop_event.set()
                            for f in futures:
                                f.cancel()
                            return moves, status

                        if status == "NO_SOLUTION":
                            best_no_sol_status = "NO_SOLUTION"

                except KeyboardInterrupt:
                    stop_event.set()
                    raise

        return [], best_no_sol_status

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def resume_from(self, current_play_area: PlayArea) -> None:
        self.current_state = current_play_area.to_game_state()

    def get_best_partial_solution(self) -> Tuple[List[Tuple[int, int]], int, int]:
        if _RUST_AVAILABLE and self._rust_best_partial is not None:
            return self._rust_best_partial
        if self.best_partial_node is None:
            return [], 0, 0
        path = _reconstruct_path(self.best_partial_node)
        completed_count = len(self.best_partial_node.state.completed_bottles)
        return path, completed_count, self.best_partial_iteration
