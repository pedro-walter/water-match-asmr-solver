use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicI64, Ordering};
use std::sync::{Arc, Mutex};

use dashmap::DashMap;
use dashmap::DashSet;
use dashmap::mapref::entry::Entry;

use crate::astar::{BestPartial, SearchStatus};
use crate::moves::{generate_valid_moves, is_revealing_unknown, is_unlocking_unknown_bottle};
use crate::types::GameState;

// ---------------------------------------------------------------------------
// Path reconstruction
//
// Walk parent pointers from `goal_key` back to the root (the None entry),
// collecting moves along the way, then reverse for chronological order.
// ---------------------------------------------------------------------------

#[allow(dead_code)]
fn reconstruct_path(
    visited: &HashMap<Vec<u8>, Option<(Vec<u8>, (u8, u8))>>,
    goal_key: &[u8],
) -> Vec<(usize, usize)> {
    let mut path = Vec::new();
    let mut current = goal_key.to_vec();
    loop {
        match visited.get(&current) {
            Some(Some((parent_key, mv))) => {
                path.push((mv.0 as usize, mv.1 as usize));
                current = parent_key.clone();
            }
            _ => break, // root (None entry) or missing key
        }
    }
    path.reverse();
    path
}

// ---------------------------------------------------------------------------
// Exhaustive DFS with global visited set
//
// Visits every reachable state exactly once.  When the stack empties the
// entire reachable graph has been explored — returns NoSolution as a proven
// fact, not just a budget timeout.
//
// Memory: O(unique states visited).  Each visited-map entry stores two
// 42-byte state keys + a 2-byte move ≈ ~130 bytes with HashMap overhead.
// At 1M states ≈ 130 MB; at 10M states ≈ 1.3 GB.
//
// The stack holds full GameState clones (~240 bytes each) for each
// discovered-but-not-yet-expanded state.  In practice its size tracks
// the visited map.
// ---------------------------------------------------------------------------

#[allow(dead_code)]
pub fn dfs_search(
    initial: GameState,
    max_iterations: u64,
    stop: Option<Arc<AtomicBool>>,
) -> (SearchStatus, BestPartial) {
    let mut best_partial = BestPartial::default();
    let mut iterations: u64 = 0;

    let initial_key = initial.to_key();

    // visited: state_key → None (root) | Some((parent_key, move_here))
    let mut visited: HashMap<Vec<u8>, Option<(Vec<u8>, (u8, u8))>> = HashMap::new();
    visited.insert(initial_key, None);

    // Explicit DFS stack — paths reconstructed via visited map, not stored here.
    let mut stack: Vec<GameState> = vec![initial];

    while let Some(state) = stack.pop() {
        iterations += 1;

        if iterations > max_iterations {
            return (SearchStatus::Timeout, best_partial);
        }
        if iterations % 2000 == 0 {
            if let Some(ref flag) = stop {
                if flag.load(Ordering::Relaxed) {
                    return (SearchStatus::Stopped, best_partial);
                }
            }
        }

        // Goal check
        if state.is_goal() {
            let path = reconstruct_path(&visited, &state.to_key());
            return (SearchStatus::Solved(path), best_partial);
        }

        // Best-partial tracking
        let completed = state.completed.0.count_ones() as u32;
        if completed > best_partial.completed_count {
            let path = reconstruct_path(&visited, &state.to_key());
            best_partial.update(path, completed, iterations);
        }

        let state_key = state.to_key();

        for (from, to) in generate_valid_moves(&state) {
            // Unknown-revealing moves pause the game — return path + this move.
            if is_revealing_unknown(&state, from) {
                let mut path = reconstruct_path(&visited, &state_key);
                path.push((from, to));
                return (SearchStatus::UnknownRevealed(path), best_partial);
            }

            if let Some(new_state) = state.apply_move(from, to) {
                // Bottle-unlock moves also pause the game.
                if is_unlocking_unknown_bottle(&state, &new_state) {
                    let mut path = reconstruct_path(&visited, &state_key);
                    path.push((from, to));
                    return (SearchStatus::BottleUnlocked(path), best_partial);
                }

                let new_key = new_state.to_key();
                if !visited.contains_key(&new_key) {
                    // Record parent pointer before pushing to stack.
                    visited.insert(
                        new_key,
                        Some((state_key.clone(), (from as u8, to as u8))),
                    );
                    stack.push(new_state);
                }
            }
        }
    }

    // Stack exhausted — every reachable state was visited, none was the goal.
    (SearchStatus::NoSolution, best_partial)
}

// ---------------------------------------------------------------------------
// Parallel DFS with shared visited set
//
// Uses a DashMap (concurrent hashmap) as the shared visited set so multiple
// threads can each explore the state space without duplicating work.
//
// Termination detection via a pending counter:
//   pending = number of states that have been pushed but whose children have
//             not yet all been generated ("in-flight" states).
//   Initially 1 (the root).  A thread increments it before pushing each new
//   child, and decrements it after finishing all children for the state it
//   just popped.  When pending reaches 0, every reachable state has been
//   visited → NoSolution.
//
// This is correct because pending is always ≥ 1 while a thread is still
// processing a state (the decrement happens last), so 0 can only be observed
// once the stack is truly empty and no thread has outstanding work.
// ---------------------------------------------------------------------------

#[allow(dead_code)]
fn reconstruct_path_dashmap(
    visited: &DashMap<Vec<u8>, Option<(Vec<u8>, (u8, u8))>>,
    goal_key: &[u8],
) -> Vec<(usize, usize)> {
    let mut path = Vec::new();
    let mut current = goal_key.to_vec();
    loop {
        // Clone the stored value to release the shard lock before the next hop.
        let entry = visited.get(&current).map(|e| e.clone());
        match entry {
            Some(Some((parent_key, mv))) => {
                path.push((mv.0 as usize, mv.1 as usize));
                current = parent_key;
            }
            _ => break, // root (None entry) or missing — stop walking
        }
    }
    path.reverse();
    path
}

#[allow(dead_code)]
pub fn parallel_dfs_search(
    initial: GameState,
    num_threads: usize,
    max_iterations: u64,
    stop: Arc<AtomicBool>,
) -> (SearchStatus, BestPartial) {
    let visited: Arc<DashMap<Vec<u8>, Option<(Vec<u8>, (u8, u8))>>> =
        Arc::new(DashMap::new());
    let stack: Arc<Mutex<Vec<GameState>>> = Arc::new(Mutex::new(Vec::new()));
    // pending: counts states that have been pushed but not yet fully processed.
    let pending: Arc<AtomicI64> = Arc::new(AtomicI64::new(1));
    let result: Arc<Mutex<Option<SearchStatus>>> = Arc::new(Mutex::new(None));
    let global_best: Arc<Mutex<BestPartial>> = Arc::new(Mutex::new(BestPartial::default()));
    let total_iterations: Arc<AtomicI64> = Arc::new(AtomicI64::new(0));

    // Insert root into visited and stack.
    visited.insert(initial.to_key(), None);
    stack.lock().unwrap().push(initial);

    std::thread::scope(|s| {
        for _ in 0..num_threads {
            let visited = Arc::clone(&visited);
            let stack = Arc::clone(&stack);
            let pending = Arc::clone(&pending);
            let result = Arc::clone(&result);
            let global_best = Arc::clone(&global_best);
            let stop = Arc::clone(&stop);
            let total_iterations = Arc::clone(&total_iterations);

            s.spawn(move || {
                'outer: loop {
                    if stop.load(Ordering::Relaxed) {
                        return;
                    }
                    if result.lock().unwrap().is_some() {
                        return;
                    }

                    // Try to get work.
                    let state = stack.lock().unwrap().pop();
                    let state = match state {
                        Some(s) => s,
                        None => {
                            // Stack empty — if all work is done we are finished.
                            if pending.load(Ordering::SeqCst) == 0 {
                                let mut r = result.lock().unwrap();
                                if r.is_none() {
                                    *r = Some(SearchStatus::NoSolution);
                                }
                                stop.store(true, Ordering::Relaxed);
                            }
                            std::thread::yield_now();
                            continue;
                        }
                    };

                    // Iteration budget.
                    let iters = total_iterations.fetch_add(1, Ordering::Relaxed) as u64;
                    if iters >= max_iterations {
                        let mut r = result.lock().unwrap();
                        if r.is_none() {
                            *r = Some(SearchStatus::Timeout);
                        }
                        stop.store(true, Ordering::Relaxed);
                        pending.fetch_sub(1, Ordering::SeqCst);
                        return;
                    }

                    // Goal check.
                    if state.is_goal() {
                        let path = reconstruct_path_dashmap(&visited, &state.to_key());
                        let mut r = result.lock().unwrap();
                        if r.is_none() {
                            *r = Some(SearchStatus::Solved(path));
                        }
                        stop.store(true, Ordering::Relaxed);
                        pending.fetch_sub(1, Ordering::SeqCst);
                        return;
                    }

                    // Best-partial tracking.
                    let completed = state.completed.0.count_ones() as u32;
                    {
                        let mut bp = global_best.lock().unwrap();
                        if completed > bp.completed_count {
                            let path = reconstruct_path_dashmap(&visited, &state.to_key());
                            bp.update(path, completed, iters);
                        }
                    }

                    let state_key = state.to_key();

                    for (from, to) in generate_valid_moves(&state) {
                        // Unknown-revealing moves pause the game.
                        if is_revealing_unknown(&state, from) {
                            let mut path = reconstruct_path_dashmap(&visited, &state_key);
                            path.push((from, to));
                            let mut r = result.lock().unwrap();
                            if r.is_none() {
                                *r = Some(SearchStatus::UnknownRevealed(path));
                            }
                            stop.store(true, Ordering::Relaxed);
                            pending.fetch_sub(1, Ordering::SeqCst);
                            continue 'outer;
                        }

                        if let Some(new_state) = state.apply_move(from, to) {
                            // Bottle-unlock moves pause the game.
                            if is_unlocking_unknown_bottle(&state, &new_state) {
                                let mut path = reconstruct_path_dashmap(&visited, &state_key);
                                path.push((from, to));
                                let mut r = result.lock().unwrap();
                                if r.is_none() {
                                    *r = Some(SearchStatus::BottleUnlocked(path));
                                }
                                stop.store(true, Ordering::Relaxed);
                                pending.fetch_sub(1, Ordering::SeqCst);
                                continue 'outer;
                            }

                            let new_key = new_state.to_key();
                            // Atomic check-then-insert: only one thread will see Vacant.
                            match visited.entry(new_key) {
                                Entry::Vacant(e) => {
                                    e.insert(Some((state_key.clone(), (from as u8, to as u8))));
                                    pending.fetch_add(1, Ordering::SeqCst);
                                    stack.lock().unwrap().push(new_state);
                                }
                                Entry::Occupied(_) => {} // already visited
                            }
                        }
                    }

                    // All children of this state have been generated.
                    pending.fetch_sub(1, Ordering::SeqCst);
                }
            });
        }
    });

    let bp = global_best.lock().unwrap().clone();
    let r = result.lock().unwrap().take().unwrap_or(SearchStatus::NoSolution);
    (r, bp)
}

// ---------------------------------------------------------------------------
// Two-phase DFS: phase 1 checks solvability with minimal RAM
//
// Uses DashSet<Vec<u8>> (keys only, ~42 bytes/entry) instead of the
// DashMap with parent pointers (~130 bytes/entry).  This is ~3× less RAM
// during the expensive exhaustive phase.
//
// Returns the outcome and the best completion count seen.  No move paths are
// recorded — the caller runs MCTS (phase 2) to reconstruct the actual path
// once solvability is confirmed.
// ---------------------------------------------------------------------------

#[derive(Debug, PartialEq)]
pub enum Phase1Result {
    Solvable,
    UnknownRevealed,
    BottleUnlocked,
    NoSolution,
    Timeout,
    #[allow(dead_code)]
    Stopped,
}

pub fn parallel_dfs_phase1(
    initial: GameState,
    num_threads: usize,
    max_iterations: u64,
    stop: Arc<AtomicBool>,
) -> (Phase1Result, u32) {
    let visited: Arc<DashSet<Vec<u8>>> = Arc::new(DashSet::new());
    let stack: Arc<Mutex<Vec<GameState>>> = Arc::new(Mutex::new(Vec::new()));
    let pending: Arc<AtomicI64> = Arc::new(AtomicI64::new(1));
    let result: Arc<Mutex<Option<Phase1Result>>> = Arc::new(Mutex::new(None));
    let best_completed: Arc<AtomicI64> = Arc::new(AtomicI64::new(0));
    let total_iterations: Arc<AtomicI64> = Arc::new(AtomicI64::new(0));

    visited.insert(initial.to_key());
    stack.lock().unwrap().push(initial);

    std::thread::scope(|s| {
        for _ in 0..num_threads {
            let visited = Arc::clone(&visited);
            let stack = Arc::clone(&stack);
            let pending = Arc::clone(&pending);
            let result = Arc::clone(&result);
            let best_completed = Arc::clone(&best_completed);
            let stop = Arc::clone(&stop);
            let total_iterations = Arc::clone(&total_iterations);

            s.spawn(move || {
                'outer: loop {
                    if stop.load(Ordering::Relaxed) {
                        return;
                    }
                    if result.lock().unwrap().is_some() {
                        return;
                    }

                    let state = stack.lock().unwrap().pop();
                    let state = match state {
                        Some(s) => s,
                        None => {
                            if pending.load(Ordering::SeqCst) == 0 {
                                let mut r = result.lock().unwrap();
                                if r.is_none() {
                                    *r = Some(Phase1Result::NoSolution);
                                }
                                stop.store(true, Ordering::Relaxed);
                            }
                            std::thread::yield_now();
                            continue;
                        }
                    };

                    let iters = total_iterations.fetch_add(1, Ordering::Relaxed) as u64;
                    if iters >= max_iterations {
                        let mut r = result.lock().unwrap();
                        if r.is_none() {
                            *r = Some(Phase1Result::Timeout);
                        }
                        stop.store(true, Ordering::Relaxed);
                        pending.fetch_sub(1, Ordering::SeqCst);
                        return;
                    }

                    if state.is_goal() {
                        let mut r = result.lock().unwrap();
                        if r.is_none() {
                            *r = Some(Phase1Result::Solvable);
                        }
                        stop.store(true, Ordering::Relaxed);
                        pending.fetch_sub(1, Ordering::SeqCst);
                        return;
                    }

                    // Track best completion count (no path — just the number).
                    let completed = state.completed.0.count_ones() as i64;
                    let mut prev = best_completed.load(Ordering::Relaxed);
                    while completed > prev {
                        match best_completed.compare_exchange_weak(
                            prev, completed, Ordering::Relaxed, Ordering::Relaxed,
                        ) {
                            Ok(_) => break,
                            Err(actual) => prev = actual,
                        }
                    }

                    for (from, to) in generate_valid_moves(&state) {
                        if is_revealing_unknown(&state, from) {
                            let mut r = result.lock().unwrap();
                            if r.is_none() {
                                *r = Some(Phase1Result::UnknownRevealed);
                            }
                            stop.store(true, Ordering::Relaxed);
                            pending.fetch_sub(1, Ordering::SeqCst);
                            continue 'outer;
                        }

                        if let Some(new_state) = state.apply_move(from, to) {
                            if is_unlocking_unknown_bottle(&state, &new_state) {
                                let mut r = result.lock().unwrap();
                                if r.is_none() {
                                    *r = Some(Phase1Result::BottleUnlocked);
                                }
                                stop.store(true, Ordering::Relaxed);
                                pending.fetch_sub(1, Ordering::SeqCst);
                                continue 'outer;
                            }

                            let new_key = new_state.to_key();
                            // DashSet::insert returns true only for a new entry —
                            // this is the atomic check-then-insert equivalent.
                            if visited.insert(new_key) {
                                pending.fetch_add(1, Ordering::SeqCst);
                                stack.lock().unwrap().push(new_state);
                            }
                        }
                    }

                    pending.fetch_sub(1, Ordering::SeqCst);
                }
            });
        }
    });

    let completed = best_completed.load(Ordering::Relaxed) as u32;
    let r = result.lock().unwrap().take().unwrap_or(Phase1Result::NoSolution);
    (r, completed)
}
