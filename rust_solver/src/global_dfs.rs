// ---------------------------------------------------------------------------
// Parallel Global-Dedup Greedy DFS
//
// All threads share a single DashMap<u64, (u64, u8, u8)>:
//   key   = 64-bit hash of state.to_key()
//   value = (parent_hash, from_bottle, to_bottle)
//   root  = sentinel (parent_hash=0, from=255, to=255)
//
// State ownership: `DashMap::insert()` returns the previous value; a
// `None` result means this thread is the first to see this state and
// therefore owns it (pushes it onto its local stack).  Any other thread
// that later hashes to the same state gets `Some(...)` back and skips it.
// This gives true global deduplication across all threads with no locks
// on the hot path beyond DashMap's internal per-shard RwLocks.
//
// Memory: ~28 bytes/state (DashMap uses hashbrown internally, same as
// std HashMap — sharding overhead is a fixed ~4 KB regardless of size).
// ---------------------------------------------------------------------------

use std::collections::VecDeque;
use std::hash::{Hash, Hasher};
use std::collections::hash_map::DefaultHasher;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, mpsc};

use dashmap::DashMap;

use crate::astar::{BestPartial, SearchStatus};
use crate::heuristic::heuristic;
use crate::moves::{generate_valid_moves, is_revealing_unknown, is_unlocking_unknown_bottle};
use crate::types::GameState;

const LOG_INTERVAL: u64 = 100_000;
const SPINNER: &[char] = &['|', '/', '-', '\\'];

fn free_ram_mb() -> u64 {
    #[cfg(target_os = "linux")]
    {
        if let Ok(content) = std::fs::read_to_string("/proc/meminfo") {
            for line in content.lines() {
                if line.starts_with("MemAvailable:") {
                    if let Some(kb) = line.split_whitespace().nth(1)
                        .and_then(|s| s.parse::<u64>().ok())
                    {
                        return kb / 1024;
                    }
                }
            }
        }
    }
    0
}

fn hash_state(state: &GameState) -> u64 {
    let mut h = DefaultHasher::new();
    state.to_key().hash(&mut h);
    h.finish()
}

/// Walk the parent-hash chain in the shared map to reconstruct moves.
/// Root sentinel: from == 255.
fn reconstruct_path(visited: &DashMap<u64, (u64, u8, u8)>, goal_hash: u64) -> Vec<(usize, usize)> {
    let mut path = Vec::new();
    let mut cur = goal_hash;
    loop {
        // Copy the value out immediately so we don't hold the shard lock.
        let (parent, from, to) = *visited.get(&cur).expect("hash missing during reconstruct");
        if from == 255 { break; } // root sentinel
        path.push((from as usize, to as usize));
        cur = parent;
    }
    path.reverse();
    path
}

/// Walk `prefix` moves from `initial`, inserting each intermediate state
/// into the shared map (first-writer-wins via `entry().or_insert()`).
/// Returns the hash + state of the partition root, or None if a move is
/// invalid (shouldn't happen in practice).
fn prepare_partition(
    visited: &DashMap<u64, (u64, u8, u8)>,
    initial: &GameState,
    initial_hash: u64,
    prefix: &[(usize, usize)],
) -> Option<(u64, GameState)> {
    let mut cur_hash = initial_hash;
    let mut cur_state = initial.clone();
    for &(from, to) in prefix {
        let new_state = cur_state.apply_move(from, to)?;
        let new_hash = hash_state(&new_state);
        visited.entry(new_hash).or_insert((cur_hash, from as u8, to as u8));
        cur_hash = new_hash;
        cur_state = new_state;
    }
    Some((cur_hash, cur_state))
}

// ---------------------------------------------------------------------------
// Per-worker types
// ---------------------------------------------------------------------------

struct WorkerResult {
    best_partial: BestPartial,
    status: WorkerStatus,
}

enum WorkerStatus {
    Solved(Vec<(usize, usize)>),
    UnknownRevealed(Vec<(usize, usize)>),
    BottleUnlocked(Vec<(usize, usize)>),
    NoSolution,
    Stopped,
}

// ---------------------------------------------------------------------------
// Worker — runs a greedy DFS from a single starting state.
// Owns its local stack; all other data is shared read-only or via DashMap.
// ---------------------------------------------------------------------------

fn dfs_worker(
    start_hash: u64,
    start_state: GameState,
    visited: &DashMap<u64, (u64, u8, u8)>,
    stop: &AtomicBool,
    total_states: &AtomicU64,
) -> WorkerResult {
    let mut best_partial = BestPartial::default();
    let mut local_iters: u64 = 0;

    let mut stack: Vec<(GameState, u64)> = vec![(start_state, start_hash)];

    while let Some((state, state_hash)) = stack.pop() {
        if stop.load(Ordering::Relaxed) {
            return WorkerResult { best_partial, status: WorkerStatus::Stopped };
        }

        local_iters += 1;

        // Progress: print when this thread crosses a LOG_INTERVAL boundary.
        if local_iters % LOG_INTERVAL == 0 {
            let total = total_states.load(Ordering::Relaxed);
            let spin = SPINNER[((total / LOG_INTERVAL) % 4) as usize];
            let used_mb = total * 28 / 1_000_000;
            eprint!(
                "\r{} [global-dfs] {}M states | ~{} MB used | free: {} MB   ",
                spin,
                total / 1_000_000,
                used_mb,
                free_ram_mb(),
            );
        }

        if state.is_goal() {
            stop.store(true, Ordering::Relaxed);
            eprintln!();
            let path = reconstruct_path(visited, state_hash);
            return WorkerResult { best_partial, status: WorkerStatus::Solved(path) };
        }

        // Best-partial tracking.
        let completed = state.completed.0.count_ones() as u32;
        if completed > best_partial.completed_count {
            let path = reconstruct_path(visited, state_hash);
            best_partial.update(path, completed, local_iters);
        }

        let moves = generate_valid_moves(&state);
        let mut children: Vec<(f32, GameState, u64, u8, u8)> = Vec::new();

        for (from, to) in moves {
            if is_revealing_unknown(&state, from) {
                let mut path = reconstruct_path(visited, state_hash);
                path.push((from, to));
                stop.store(true, Ordering::Relaxed);
                eprintln!();
                return WorkerResult { best_partial, status: WorkerStatus::UnknownRevealed(path) };
            }

            if let Some(new_state) = state.apply_move(from, to) {
                if is_unlocking_unknown_bottle(&state, &new_state) {
                    let mut path = reconstruct_path(visited, state_hash);
                    path.push((from, to));
                    stop.store(true, Ordering::Relaxed);
                    eprintln!();
                    return WorkerResult { best_partial, status: WorkerStatus::BottleUnlocked(path) };
                }

                let new_hash = hash_state(&new_state);

                // Global dedup: only this thread (the first inserter) processes the state.
                if visited.insert(new_hash, (state_hash, from as u8, to as u8)).is_none() {
                    total_states.fetch_add(1, Ordering::Relaxed);
                    let h = heuristic(&new_state);
                    children.push((h, new_state, new_hash, from as u8, to as u8));
                }
            }
        }

        // Sort descending by h so the best child (lowest h) sits on top of the stack.
        children.sort_unstable_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));

        for (_, new_state, new_hash, _from, _to) in children {
            stack.push((new_state, new_hash));
        }
    }

    WorkerResult { best_partial, status: WorkerStatus::NoSolution }
}

// ---------------------------------------------------------------------------
// Coordinator
// ---------------------------------------------------------------------------

pub fn global_dfs_search(
    initial: GameState,
    stop: Arc<AtomicBool>,
) -> (SearchStatus, BestPartial) {
    // Trivial cases before spinning up threads.
    if initial.is_goal() {
        return (SearchStatus::Solved(vec![]), BestPartial::default());
    }

    let num_threads = rayon::current_num_threads();

    // Generate K-move prefixes for initial work distribution.
    // Try increasing depths until we have enough partitions to keep all threads busy.
    let mut prefixes: Vec<Vec<(usize, usize)>> = Vec::new();
    for depth in 2..=6 {
        prefixes = crate::chunked_dfs::generate_prefixes(&initial, depth);
        if prefixes.len() >= num_threads * 2 || prefixes.is_empty() {
            break;
        }
    }

    if prefixes.is_empty() {
        return (SearchStatus::NoSolution, BestPartial::default());
    }

    // Shared visited map — root state inserted with sentinel parent.
    let visited: Arc<DashMap<u64, (u64, u8, u8)>> = Arc::new(DashMap::new());
    let initial_hash = hash_state(&initial);
    visited.insert(initial_hash, (0, 255, 255));

    // Build work items: walk each prefix chain, insert intermediate states,
    // collect the (hash, state) for each partition root.
    let work: Vec<(u64, GameState)> = prefixes
        .iter()
        .filter_map(|p| prepare_partition(&visited, &initial, initial_hash, p))
        .collect();

    let total_partitions = work.len();
    eprintln!(
        "Global DFS: {} partitions | {} threads | {} initial states in map",
        total_partitions, num_threads, visited.len(),
    );

    let queue: Arc<Mutex<VecDeque<(u64, GameState)>>> =
        Arc::new(Mutex::new(work.into_iter().collect()));

    let (result_tx, result_rx) = mpsc::channel::<WorkerResult>();
    let global_best: Arc<Mutex<BestPartial>> = Arc::new(Mutex::new(BestPartial::default()));
    let total_states: Arc<AtomicU64> = Arc::new(AtomicU64::new(visited.len() as u64));
    let exhausted_count: Arc<AtomicU64> = Arc::new(AtomicU64::new(0));

    std::thread::scope(|s| {
        for _ in 0..num_threads {
            let queue       = Arc::clone(&queue);
            let visited     = Arc::clone(&visited);
            let stop        = Arc::clone(&stop);
            let result_tx   = result_tx.clone();
            let global_best = Arc::clone(&global_best);
            let total_states = Arc::clone(&total_states);
            let exhausted_count = Arc::clone(&exhausted_count);

            s.spawn(move || {
                loop {
                    if stop.load(Ordering::Relaxed) { break; }

                    let item = queue.lock().unwrap().pop_front();
                    let (start_hash, start_state) = match item {
                        None => break,
                        Some(x) => x,
                    };

                    let res = dfs_worker(
                        start_hash, start_state,
                        &visited, &stop, &total_states,
                    );

                    // Merge best partial.
                    global_best.lock().unwrap().merge_from(&res.best_partial);

                    if matches!(res.status, WorkerStatus::NoSolution) {
                        exhausted_count.fetch_add(1, Ordering::Relaxed);
                    }

                    result_tx.send(res).ok();
                }
            });
        }
    });

    drop(result_tx);
    eprintln!(); // finish the \r progress line

    // Drain results and determine the final outcome.
    let global_best = global_best.lock().unwrap().clone();
    let exhausted = exhausted_count.load(Ordering::Relaxed) as usize;
    let mut winning: Option<SearchStatus> = None;
    let mut had_interrupt = false;

    for res in result_rx {
        match res.status {
            WorkerStatus::Solved(moves)           if winning.is_none() => {
                winning = Some(SearchStatus::Solved(moves));
            }
            WorkerStatus::UnknownRevealed(moves)  if winning.is_none() => {
                winning = Some(SearchStatus::UnknownRevealed(moves));
            }
            WorkerStatus::BottleUnlocked(moves)   if winning.is_none() => {
                winning = Some(SearchStatus::BottleUnlocked(moves));
            }
            WorkerStatus::Stopped => { had_interrupt = true; }
            _ => {}
        }
    }

    if let Some(status) = winning {
        return (status, global_best);
    }
    if exhausted == total_partitions && !had_interrupt {
        return (SearchStatus::NoSolution, global_best);
    }
    (SearchStatus::Stopped, global_best)
}
