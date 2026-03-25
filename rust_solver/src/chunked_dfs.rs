// ---------------------------------------------------------------------------
// Chunked Independent-Subtree DFS
//
// Splits the search space into independent subtrees (chunks) rooted K moves
// from the initial state.  Each chunk runs its own DFS with a completely
// local HashMap — when the chunk finishes its memory is freed immediately.
//
// Peak RAM ≈ N_threads × max_subtree_RAM
// instead of   total_reachable_states × entry_cost.
//
// Two parts:
//   Part 1 — Coordinator: generates chunks, distributes via a shared queue,
//             collects results, prints progress.
//   Part 2 — Worker (dfs_chunk): independent function, owns all its data,
//             no shared state, freed when it returns.
// ---------------------------------------------------------------------------

use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
// AtomicU64 used for done_count and best_completed_live progress counters
use std::sync::{Arc, Mutex, mpsc};
use std::time::Instant;

/// Free system RAM in MB (Linux only; returns 0 on other platforms).
fn free_ram_mb() -> u64 {
    #[cfg(target_os = "linux")]
    {
        if let Ok(content) = std::fs::read_to_string("/proc/meminfo") {
            for line in content.lines() {
                if line.starts_with("MemAvailable:") {
                    if let Some(kb) = line.split_whitespace().nth(1).and_then(|s| s.parse::<u64>().ok()) {
                        return kb / 1024;
                    }
                }
            }
        }
    }
    0
}

use crate::astar::{BestPartial, SearchStatus};
use crate::moves::{generate_valid_moves, is_revealing_unknown, is_unlocking_unknown_bottle};
use crate::types::GameState;

// ---------------------------------------------------------------------------
// Result returned by each worker to the coordinator
// ---------------------------------------------------------------------------

struct ChunkResult {
    best_partial: BestPartial,
    status: ChunkStatus,
}

enum ChunkStatus {
    Solved(Vec<(usize, usize)>),           // full path: prefix + local
    UnknownRevealed(Vec<(usize, usize)>),
    BottleUnlocked(Vec<(usize, usize)>),
    NoSolution,   // subtree fully exhausted — contributes to the NoSolution proof
    Stopped,      // cut short by stop flag or iteration budget
}

// ---------------------------------------------------------------------------
// Local path reconstruction (no shared state)
// ---------------------------------------------------------------------------

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
            _ => break,
        }
    }
    path.reverse();
    path
}

// ---------------------------------------------------------------------------
// Chunk generation — deduplicated BFS over prefix moves
//
// Returns one prefix (move sequence) per UNIQUE game state reachable in
// `depth` moves, skipping unknown-revealing and bottle-unlocking moves.
//
// Unlike `generate_partitions` in parallel.rs (which keeps every move
// sequence without deduplication), this tracks seen state keys so that
// states reachable via multiple paths only produce a single chunk.
//
// Queue entry cost: K×2 bytes (prefix moves only) — the full GameState is
// NOT stored here; workers replay the prefix on demand from `initial`.
// ---------------------------------------------------------------------------

fn generate_prefixes(
    initial: &GameState,
    depth: usize,
) -> Vec<Vec<(usize, usize)>> {
    use crate::moves::{generate_valid_moves, is_revealing_unknown, is_unlocking_unknown_bottle};

    // frontier: (prefix, state) — kept only for BFS expansion, not stored in queue
    let mut frontier: Vec<(Vec<(usize, usize)>, GameState)> = vec![(vec![], initial.clone())];
    let mut seen: HashSet<Vec<u8>> = HashSet::new();
    seen.insert(initial.to_key());

    for _ in 0..depth {
        let mut next = Vec::new();
        for (prefix, state) in &frontier {
            for (from, to) in generate_valid_moves(state) {
                if is_revealing_unknown(state, from) { continue; }
                if let Some(new_state) = state.apply_move(from, to) {
                    if is_unlocking_unknown_bottle(state, &new_state) { continue; }
                    let key = new_state.to_key();
                    if seen.insert(key) {
                        let mut p = prefix.clone();
                        p.push((from, to));
                        next.push((p, new_state));
                    }
                }
            }
        }
        if next.is_empty() { break; }
        frontier = next;
    }

    frontier.into_iter().map(|(prefix, _)| prefix).collect()
}

/// Replay `prefix` moves from `initial` to obtain the chunk's starting state.
/// Returns None only if the puzzle has changed in a way that makes a move invalid
/// (shouldn't happen in practice).
fn replay_prefix(initial: &GameState, prefix: &[(usize, usize)]) -> Option<GameState> {
    let mut state = initial.clone();
    for &(from, to) in prefix {
        state = state.apply_move(from, to)?;
    }
    Some(state)
}

// ---------------------------------------------------------------------------
// Part 2 — Worker
//
// Receives all inputs by value, owns all local data structures, has zero
// access to any shared state.  Memory is freed when this function returns.
// ---------------------------------------------------------------------------

fn dfs_chunk(
    prefix: Vec<(usize, usize)>,
    start_state: GameState,
    stop: Arc<AtomicBool>,
) -> ChunkResult {
    let mut best_partial = BestPartial::default();
    let mut local_iters: u64 = 0;

    // Completely local — not shared with any other worker.
    let mut visited: HashMap<Vec<u8>, Option<(Vec<u8>, (u8, u8))>> = HashMap::new();
    visited.insert(start_state.to_key(), None); // root has no parent

    let mut stack: Vec<GameState> = vec![start_state];

    while let Some(state) = stack.pop() {
        if stop.load(Ordering::Relaxed) {
            return ChunkResult { best_partial, status: ChunkStatus::Stopped };
        }

        local_iters += 1;

        // Goal check — reconstruct full path and signal other workers to stop.
        if state.is_goal() {
            let local_path = reconstruct_path(&visited, &state.to_key());
            let mut full = prefix;
            full.extend_from_slice(&local_path);
            stop.store(true, Ordering::Relaxed);
            return ChunkResult { best_partial, status: ChunkStatus::Solved(full) };
        }

        // Best-partial tracking (clone prefix since the loop continues).
        let completed = state.completed.0.count_ones() as u32;
        if completed > best_partial.completed_count {
            let local_path = reconstruct_path(&visited, &state.to_key());
            let mut full = prefix.clone();
            full.extend_from_slice(&local_path);
            best_partial.update(full, completed, local_iters);
        }

        let state_key = state.to_key();

        for (from, to) in generate_valid_moves(&state) {
            // Unknown-revealing moves pause the game — return path + triggering move.
            if is_revealing_unknown(&state, from) {
                let mut local_path = reconstruct_path(&visited, &state_key);
                local_path.push((from, to));
                let mut full = prefix;
                full.extend_from_slice(&local_path);
                stop.store(true, Ordering::Relaxed);
                return ChunkResult {
                    best_partial,
                    status: ChunkStatus::UnknownRevealed(full),
                };
            }

            if let Some(new_state) = state.apply_move(from, to) {
                if is_unlocking_unknown_bottle(&state, &new_state) {
                    let mut local_path = reconstruct_path(&visited, &state_key);
                    local_path.push((from, to));
                    let mut full = prefix;
                    full.extend_from_slice(&local_path);
                    stop.store(true, Ordering::Relaxed);
                    return ChunkResult {
                        best_partial,
                        status: ChunkStatus::BottleUnlocked(full),
                    };
                }

                let new_key = new_state.to_key();
                if !visited.contains_key(&new_key) {
                    visited.insert(
                        new_key,
                        Some((state_key.clone(), (from as u8, to as u8))),
                    );
                    stack.push(new_state);
                }
            }
        }
    }

    // Stack exhausted — this chunk's entire subtree was visited with no goal found.
    ChunkResult { best_partial, status: ChunkStatus::NoSolution }
}

// ---------------------------------------------------------------------------
// Part 1 — Coordinator
//
// Generates all K-move prefixes, places them in a work queue, and feeds them
// to N worker threads.  Results are collected after all threads finish.
// Progress is printed by workers using shared atomic counters.
// ---------------------------------------------------------------------------

pub fn chunked_dfs_search(
    initial: GameState,
    chunk_depth: usize,
    stop: Arc<AtomicBool>,
) -> (SearchStatus, BestPartial) {
    let prefixes = generate_prefixes(&initial, chunk_depth);
    let total_chunks = prefixes.len();

    if total_chunks == 0 {
        if initial.is_goal() {
            return (SearchStatus::Solved(vec![]), BestPartial::default());
        }
        return (SearchStatus::NoSolution, BestPartial::default());
    }

    let num_threads = rayon::current_num_threads();
    let queue_mb = total_chunks * chunk_depth * 2 / 1_000_000 + 1;
    eprintln!(
        "Chunked DFS: K={} | {} threads | {} chunks (~{} MB queue)",
        chunk_depth, num_threads, total_chunks, queue_mb
    );

    // Queue stores only prefix moves (~K×2 bytes each).
    // Workers replay the prefix from `initial` on pickup (~negligible CPU).
    let queue: Arc<Mutex<VecDeque<Vec<(usize, usize)>>>> =
        Arc::new(Mutex::new(prefixes.into_iter().collect()));
    let initial = Arc::new(initial);

    // Unbounded result channel: workers send, coordinator drains after scope.
    let (result_tx, result_rx) = mpsc::channel::<ChunkResult>();

    // Shared counters — updated by workers, read for progress display.
    let done_count: Arc<AtomicU64> = Arc::new(AtomicU64::new(0));
    let best_completed_live: Arc<AtomicU64> = Arc::new(AtomicU64::new(0));
    let start_time = Arc::new(Instant::now());

    // Spawn N worker threads.  scope() blocks until all threads finish,
    // so all result_tx clones are dropped before we collect from result_rx.
    std::thread::scope(|s| {
        for _ in 0..num_threads {
            let queue = Arc::clone(&queue);
            let initial = Arc::clone(&initial);
            let result_tx = result_tx.clone();
            let stop = Arc::clone(&stop);
            let done_count = Arc::clone(&done_count);
            let best_completed_live = Arc::clone(&best_completed_live);
            let start_time = Arc::clone(&start_time);

            s.spawn(move || {
                loop {
                    if stop.load(Ordering::Relaxed) {
                        break;
                    }
                    let chunk = queue.lock().unwrap().pop_front();
                    match chunk {
                        None => break,
                        Some(prefix) => {
                            // Replay prefix moves from initial to get the chunk's
                            // starting state — O(K) CPU, no stored GameState in queue.
                            let start_state = match replay_prefix(&initial, &prefix) {
                                Some(s) => s,
                                None => continue, // invalid prefix, skip
                            };
                            let result = dfs_chunk(
                                prefix,
                                start_state,
                                Arc::clone(&stop),
                            );

                            // Update live best-completion counter.
                            let this_best = result.best_partial.completed_count as u64;
                            let mut prev = best_completed_live.load(Ordering::Relaxed);
                            while this_best > prev {
                                match best_completed_live.compare_exchange_weak(
                                    prev, this_best, Ordering::Relaxed, Ordering::Relaxed,
                                ) {
                                    Ok(_) => break,
                                    Err(actual) => prev = actual,
                                }
                            }

                            // Progress: print every 20 completed chunks (in-place spinner).
                            let local_done = done_count.fetch_add(1, Ordering::Relaxed) + 1;
                            let remaining = total_chunks.saturating_sub(local_done as usize);
                            if local_done % 20 == 0 || local_done == total_chunks as u64 {
                                const SPINNER: &[char] = &['|', '/', '-', '\\'];
                                let spin = SPINNER[((local_done / 20) % 4) as usize];
                                let elapsed = start_time.elapsed().as_secs_f64();
                                let eta_str = if local_done > 0 && remaining > 0 {
                                    let eta_secs = elapsed / local_done as f64 * remaining as f64;
                                    if eta_secs < 60.0 {
                                        format!("{:.0}s", eta_secs)
                                    } else if eta_secs < 3600.0 {
                                        format!("{:.0}m{:.0}s", eta_secs / 60.0, eta_secs % 60.0)
                                    } else {
                                        format!("{:.0}h{:.0}m", eta_secs / 3600.0, (eta_secs % 3600.0) / 60.0)
                                    }
                                } else {
                                    "---".to_string()
                                };
                                eprint!(
                                    "\r{} [DFS] {}/{} done | {} in queue | depth: {} | best: {} bottles | RAM: {} MB | ETA: {}    ",
                                    spin,
                                    local_done,
                                    total_chunks,
                                    remaining,
                                    chunk_depth,
                                    best_completed_live.load(Ordering::Relaxed),
                                    free_ram_mb(),
                                    eta_str,
                                );
                            }

                            result_tx.send(result).ok();
                        }
                    }
                }
                // result_tx clone dropped here → channel closes when all threads exit
            });
        }
    }); // scope blocks until all N threads finish; all result_tx clones dropped

    // Leave the terminal on a clean line after the spinner.
    eprintln!();

    // Drop the coordinator's original sender so result_rx terminates.
    drop(result_tx);

    // Collect all buffered results and determine the final outcome.
    let mut global_best = BestPartial::default();
    let mut exhausted_count: usize = 0;
    let mut had_timeout = false;
    let mut winning: Option<SearchStatus> = None;

    for chunk_result in result_rx {
        global_best.merge_from(&chunk_result.best_partial);

        // Record the first winning result; keep tallying NoSolution for the proof.
        match chunk_result.status {
            ChunkStatus::Solved(moves) if winning.is_none() => {
                winning = Some(SearchStatus::Solved(moves));
            }
            ChunkStatus::UnknownRevealed(moves) if winning.is_none() => {
                winning = Some(SearchStatus::UnknownRevealed(moves));
            }
            ChunkStatus::BottleUnlocked(moves) if winning.is_none() => {
                winning = Some(SearchStatus::BottleUnlocked(moves));
            }
            ChunkStatus::NoSolution => {
                exhausted_count += 1;
            }
            ChunkStatus::Stopped => {
                had_timeout = true;
            }
            _ => {} // duplicate winning results from other workers — ignore
        }
    }

    if let Some(status) = winning {
        return (status, global_best);
    }

    // NoSolution is proven only if every chunk exhausted its subtree without
    // hitting the iteration limit.
    if exhausted_count == total_chunks && !had_timeout {
        (SearchStatus::NoSolution, global_best)
    } else {
        (SearchStatus::Timeout, global_best)
    }
}
