// ---------------------------------------------------------------------------
// Parallel Global-Dedup Greedy DFS  (disk-backed parent store)
//
// HOT PATH  — dedup only:
//   DashSet<u64>  ~10 bytes/entry  →  ~1 billion states in 10 GB RAM
//
// COLD PATH  — path reconstruction (done once, at solution time):
//   Append-only disk files, one per thread.
//   Record: 18 bytes  [key:u64 | parent:u64 | from:u8 | to:u8]
//   At solution time: scan all files once into a temporary HashMap,
//   walk the parent chain, return the move sequence.
//
// Parent info is written to disk for every newly-claimed state.
// The DashSet only stores the 8-byte key; the 10-byte value stays on disk.
// ---------------------------------------------------------------------------

use std::collections::{HashMap, VecDeque};
use std::hash::{Hash, Hasher};
use std::collections::hash_map::DefaultHasher;
use std::io::{BufWriter, BufReader, Read, Write};
use std::fs::File;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, mpsc};

use dashmap::DashSet;

use crate::astar::{BestPartial, SearchStatus};
use crate::heuristic::heuristic;
use crate::moves::{generate_valid_moves, is_revealing_unknown, is_unlocking_unknown_bottle};
use crate::types::GameState;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LOG_INTERVAL: u64 = 100_000;
const SPINNER: &[char] = &['|', '/', '-', '\\'];
const RECORD_SIZE: usize = 18; // key(8) + parent(8) + from(1) + to(1)
const WRITE_BUF: usize = 8 << 20; // 8 MB write buffer per thread

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

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

fn disk_path(thread_idx: usize) -> PathBuf {
    std::env::temp_dir().join(format!(
        "water_solver_{:08x}_{}.bin",
        std::process::id(),
        thread_idx,
    ))
}

/// Write one 18-byte record to a buffered disk file.
fn write_record(w: &mut BufWriter<File>, key: u64, parent: u64, from: u8, to: u8) {
    w.write_all(&key.to_le_bytes()).expect("disk write failed");
    w.write_all(&parent.to_le_bytes()).expect("disk write failed");
    w.write_all(&[from, to]).expect("disk write failed");
}

// ---------------------------------------------------------------------------
// Path reconstruction (called once, after search completes)
//
// Scans every disk file into a single HashMap, then walks the parent-hash
// chain from goal_hash back to the root sentinel (from == 255).
// Memory cost: ~28 bytes × total_states_visited — acceptable for the
// common case where a solution is found before billions of states.
// ---------------------------------------------------------------------------

fn reconstruct_path_from_disk(
    disk_files: &[PathBuf],
    goal_hash: u64,
) -> Vec<(usize, usize)> {
    let mut map: HashMap<u64, (u64, u8, u8)> = HashMap::new();
    let mut buf = [0u8; RECORD_SIZE];

    for path in disk_files {
        if let Ok(f) = File::open(path) {
            let mut reader = BufReader::new(f);
            while reader.read_exact(&mut buf).is_ok() {
                let key    = u64::from_le_bytes(buf[0..8].try_into().unwrap());
                let parent = u64::from_le_bytes(buf[8..16].try_into().unwrap());
                let from   = buf[16];
                let to     = buf[17];
                map.insert(key, (parent, from, to));
            }
        }
    }

    let mut path = Vec::new();
    let mut cur = goal_hash;
    loop {
        let &(parent, from, to) = map.get(&cur).expect("hash missing during path reconstruction");
        if from == 255 { break; } // root sentinel
        path.push((from as usize, to as usize));
        cur = parent;
    }
    path.reverse();
    path
}

// ---------------------------------------------------------------------------
// Partition prefix preparation
//
// Inserts prefix-chain states into the dedup set and writes their parent
// records to the coordinator disk file. First-writer-wins for states that
// appear in multiple prefix paths.
// ---------------------------------------------------------------------------

fn prepare_partition(
    visited: &DashSet<u64>,
    disk: &mut BufWriter<File>,
    initial: &GameState,
    initial_hash: u64,
    prefix: &[(usize, usize)],
) -> Option<(u64, GameState)> {
    let mut cur_hash  = initial_hash;
    let mut cur_state = initial.clone();

    for &(from, to) in prefix {
        let new_state = cur_state.apply_move(from, to)?;
        let new_hash  = hash_state(&new_state);
        if visited.insert(new_hash) {
            write_record(disk, new_hash, cur_hash, from as u8, to as u8);
        }
        cur_hash  = new_hash;
        cur_state = new_state;
    }
    Some((cur_hash, cur_state))
}

// ---------------------------------------------------------------------------
// Per-worker result types
// ---------------------------------------------------------------------------

struct WorkerResult {
    best_partial: BestPartial,
    status: WorkerStatus,
}

enum WorkerStatus {
    Solved           { goal_hash: u64 },
    UnknownRevealed  { pre_hash: u64, from: usize, to: usize },
    BottleUnlocked   { pre_hash: u64, from: usize, to: usize },
    NoSolution,
    Stopped,
}

// ---------------------------------------------------------------------------
// Worker — greedy DFS from a single starting state
// ---------------------------------------------------------------------------

fn dfs_worker(
    start_hash:   u64,
    start_state:  GameState,
    visited:      &DashSet<u64>,
    stop:         &AtomicBool,
    total_states: &AtomicU64,
    disk:         &mut BufWriter<File>,
) -> WorkerResult {
    let mut best_partial = BestPartial::default();
    let mut local_iters: u64 = 0;

    let mut stack: Vec<(GameState, u64)> = vec![(start_state, start_hash)];

    while let Some((state, state_hash)) = stack.pop() {
        if stop.load(Ordering::Relaxed) {
            return WorkerResult { best_partial, status: WorkerStatus::Stopped };
        }

        local_iters += 1;

        if local_iters % LOG_INTERVAL == 0 {
            let total = total_states.load(Ordering::Relaxed);
            let spin  = SPINNER[((total / LOG_INTERVAL) % 4) as usize];
            eprint!(
                "\r{} [global-dfs] {}M states | ~{} MB RAM | free: {} MB   ",
                spin,
                total / 1_000_000,
                total * 10 / 1_000_000, // ~10 bytes/entry in DashSet
                free_ram_mb(),
            );
        }

        if state.is_goal() {
            stop.store(true, Ordering::Relaxed);
            return WorkerResult {
                best_partial,
                status: WorkerStatus::Solved { goal_hash: state_hash },
            };
        }

        // Track best partial — path is left empty (disk-based reconstruction
        // is deferred to solution time; inline reconstruction would require
        // a full disk scan here which is too expensive).
        let completed = state.completed.0.count_ones() as u32;
        if completed > best_partial.completed_count {
            best_partial.update(vec![], completed, local_iters);
        }

        let moves = generate_valid_moves(&state);
        let mut children: Vec<(f32, GameState, u64, u8, u8)> = Vec::new();

        for (from, to) in moves {
            if is_revealing_unknown(&state, from) {
                return WorkerResult {
                    best_partial,
                    status: WorkerStatus::UnknownRevealed {
                        pre_hash: state_hash,
                        from,
                        to,
                    },
                };
            }

            if let Some(new_state) = state.apply_move(from, to) {
                if is_unlocking_unknown_bottle(&state, &new_state) {
                    return WorkerResult {
                        best_partial,
                        status: WorkerStatus::BottleUnlocked {
                            pre_hash: state_hash,
                            from,
                            to,
                        },
                    };
                }

                let new_hash = hash_state(&new_state);

                // Claim this state; only proceed if we're the first to see it.
                if visited.insert(new_hash) {
                    write_record(disk, new_hash, state_hash, from as u8, to as u8);
                    total_states.fetch_add(1, Ordering::Relaxed);
                    let h = heuristic(&new_state);
                    children.push((h, new_state, new_hash, from as u8, to as u8));
                }
            }
        }

        // Sort descending so the best (lowest h) child is on top of the stack.
        children.sort_unstable_by(|a, b|
            b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal)
        );

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
    if initial.is_goal() {
        return (SearchStatus::Solved(vec![]), BestPartial::default());
    }

    let num_threads = rayon::current_num_threads();

    // Generate K-move prefixes for work distribution.
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

    // Allocate disk file paths upfront: [0] = coordinator, [1..] = workers.
    let all_disk_paths: Vec<PathBuf> = (0..=num_threads)
        .map(disk_path)
        .collect();

    // Coordinator file: initial state + prefix chain intermediates.
    let mut coord_writer = BufWriter::with_capacity(
        1 << 20,
        File::create(&all_disk_paths[0]).expect("failed to create coordinator disk file"),
    );

    let visited: Arc<DashSet<u64>> = Arc::new(DashSet::new());
    let initial_hash = hash_state(&initial);
    visited.insert(initial_hash);
    write_record(&mut coord_writer, initial_hash, 0, 255, 255); // root sentinel

    let work: Vec<(u64, GameState)> = prefixes
        .iter()
        .filter_map(|p| prepare_partition(&visited, &mut coord_writer, &initial, initial_hash, p))
        .collect();

    coord_writer.flush().expect("coordinator flush failed");

    let total_partitions = work.len();
    eprintln!(
        "Global DFS: {} partitions | {} threads | {} prefix states | disk: {}",
        total_partitions, num_threads, visited.len(),
        all_disk_paths[0].display(),
    );

    let queue: Arc<Mutex<VecDeque<(u64, GameState)>>> =
        Arc::new(Mutex::new(work.into_iter().collect()));

    let (result_tx, result_rx)      = mpsc::channel::<WorkerResult>();
    let global_best: Arc<Mutex<BestPartial>> = Arc::new(Mutex::new(BestPartial::default()));
    let total_states: Arc<AtomicU64> = Arc::new(AtomicU64::new(visited.len() as u64));
    let exhausted_count: Arc<AtomicU64> = Arc::new(AtomicU64::new(0));

    std::thread::scope(|s| {
        for thread_idx in 0..num_threads {
            let file_path      = all_disk_paths[thread_idx + 1].clone();
            let queue          = Arc::clone(&queue);
            let visited        = Arc::clone(&visited);
            let stop           = Arc::clone(&stop);
            let result_tx      = result_tx.clone();
            let global_best    = Arc::clone(&global_best);
            let total_states   = Arc::clone(&total_states);
            let exhausted_count = Arc::clone(&exhausted_count);

            s.spawn(move || {
                let mut writer = BufWriter::with_capacity(
                    WRITE_BUF,
                    File::create(&file_path).expect("failed to create worker disk file"),
                );

                loop {
                    if stop.load(Ordering::Relaxed) { break; }

                    let item = queue.lock().unwrap().pop_front();
                    let (start_hash, start_state) = match item {
                        None    => break,
                        Some(x) => x,
                    };

                    let res = dfs_worker(
                        start_hash, start_state,
                        &visited, &stop, &total_states, &mut writer,
                    );

                    global_best.lock().unwrap().merge_from(&res.best_partial);

                    if matches!(res.status, WorkerStatus::NoSolution) {
                        exhausted_count.fetch_add(1, Ordering::Relaxed);
                    }

                    result_tx.send(res).ok();
                }

                writer.flush().ok(); // ensure all records reach disk
            });
        }
    });

    drop(result_tx);
    eprintln!(); // end the \r progress line

    // Collect results.
    let global_best  = global_best.lock().unwrap().clone();
    let exhausted    = exhausted_count.load(Ordering::Relaxed) as usize;
    let mut winning: Option<WorkerStatus> = None;
    let mut had_interrupt = false;

    for res in result_rx {
        match res.status {
            WorkerStatus::Solved { .. }
            | WorkerStatus::UnknownRevealed { .. }
            | WorkerStatus::BottleUnlocked { .. }
                if winning.is_none() => { winning = Some(res.status); }
            WorkerStatus::Stopped => { had_interrupt = true; }
            _ => {}
        }
    }

    // Reconstruct path from disk (if we have a winner) then clean up.
    let final_status = match winning {
        Some(WorkerStatus::Solved { goal_hash }) => {
            eprintln!("Reconstructing path from disk...");
            let path = reconstruct_path_from_disk(&all_disk_paths, goal_hash);
            eprintln!("Path reconstructed: {} moves", path.len());
            SearchStatus::Solved(path)
        }
        Some(WorkerStatus::UnknownRevealed { pre_hash, from, to }) => {
            let mut path = reconstruct_path_from_disk(&all_disk_paths, pre_hash);
            path.push((from, to));
            SearchStatus::UnknownRevealed(path)
        }
        Some(WorkerStatus::BottleUnlocked { pre_hash, from, to }) => {
            let mut path = reconstruct_path_from_disk(&all_disk_paths, pre_hash);
            path.push((from, to));
            SearchStatus::BottleUnlocked(path)
        }
        _ => {
            if exhausted == total_partitions && !had_interrupt {
                SearchStatus::NoSolution
            } else {
                SearchStatus::Stopped
            }
        }
    };

    // Delete temp files.
    for path in &all_disk_paths {
        let _ = std::fs::remove_file(path);
    }

    (final_status, global_best)
}
