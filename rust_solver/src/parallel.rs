use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use rayon::prelude::*;

use crate::astar::{BestPartial, SearchStatus};
use crate::mcts::mcts_search;
use crate::moves::{generate_valid_moves, is_revealing_unknown, is_unlocking_unknown_bottle};
use crate::types::GameState;

/// Result type shared across Rayon threads.
#[derive(Clone)]
pub struct SolveResult {
    pub moves: Vec<(usize, usize)>,
    pub status: &'static str,
    pub best_partial: BestPartial,
}

/// Generate all states reachable in `depth` moves, skipping unknown-revealing
/// and bottle-unlocking moves (mirrors Python _generate_partitions).
pub(crate) fn generate_partitions(initial: &GameState, depth: usize) -> Vec<(Vec<(usize, usize)>, GameState)> {
    let mut current: Vec<(Vec<(usize, usize)>, GameState)> = vec![(vec![], initial.clone())];

    for _ in 0..depth {
        let mut next = Vec::new();
        for (prefix, state) in &current {
            for (from, to) in generate_valid_moves(state) {
                if is_revealing_unknown(state, from) { continue; }
                if let Some(new_state) = state.apply_move(from, to) {
                    if is_unlocking_unknown_bottle(state, &new_state) { continue; }
                    let mut new_prefix = prefix.clone();
                    new_prefix.push((from, to));
                    next.push((new_prefix, new_state));
                }
            }
        }
        if next.is_empty() { break; }
        current = next;
    }

    current
}

pub fn solve_parallel(
    initial: GameState,
    heuristic_weight: f32,
    max_iterations: u64,
    tree_size: usize,
    chunk_depth: usize,
    stop: Arc<AtomicBool>,
    algorithm: &str,
) -> SolveResult {
    if algorithm == "dfs" {
        let (status, bp) = crate::chunked_dfs::chunked_dfs_search(
            initial, chunk_depth, stop,
        );
        return search_status_to_result(status, vec![], bp);
    }
    let num_threads = rayon::current_num_threads();
    let min_partitions = num_threads * 2;

    // Try increasing depth until we have enough partitions
    let mut partitions = Vec::new();
    for depth in 2..=5 {
        partitions = generate_partitions(&initial, depth);
        if partitions.len() >= min_partitions || partitions.is_empty() {
            break;
        }
    }

    let n = partitions.len();
    if n < min_partitions {
        // Fall back to single-threaded
        eprintln!("Only {} partitions, running single-threaded.", n);
        let (status, bp) = mcts_search(initial, heuristic_weight, max_iterations, tree_size, Some(Arc::clone(&stop)));
        return search_status_to_result(status, vec![], bp);
    }

    // Distribute node budget evenly across partitions.
    let rounds_per_core = (n + num_threads - 1) / num_threads;
    let nodes_per_partition = (max_iterations / rounds_per_core as u64).max(50_000);

    eprintln!(
        "Parallel MCTS: {} partitions | {} threads | {}/partition (~{} rounds/thread)",
        n, num_threads, nodes_per_partition, rounds_per_core
    );
    let result: Arc<Mutex<Option<SolveResult>>> = Arc::new(Mutex::new(None));
    let global_best_partial: Arc<Mutex<BestPartial>> = Arc::new(Mutex::new(BestPartial::default()));

    partitions.into_par_iter().for_each(|(prefix, state)| {
        if stop.load(Ordering::Relaxed) { return; }

        let (status, bp) = mcts_search(state, heuristic_weight, nodes_per_partition, tree_size, Some(Arc::clone(&stop)));

        // Always merge best partial from this worker
        {
            let mut gbp = global_best_partial.lock().unwrap();
            gbp.merge_from(&bp);
        }

        let res = search_status_to_result(status, prefix, bp);

        if res.status != "TIMEOUT" && res.status != "NO_SOLUTION" && res.status != "STOPPED" {
            stop.store(true, Ordering::Relaxed);
            let mut guard = result.lock().unwrap();
            if guard.is_none() {
                *guard = Some(res);
            }
        } else if res.status == "NO_SOLUTION" {
            // Only replace a TIMEOUT with NO_SOLUTION (more informative)
            let mut guard = result.lock().unwrap();
            if guard.as_ref().map_or(true, |r| r.status == "TIMEOUT") {
                *guard = Some(res);
            }
        }
    });

    let best_partial = global_best_partial.lock().unwrap().clone();
    let guard = result.lock().unwrap();
    guard.clone().unwrap_or(SolveResult {
        moves: vec![],
        status: "TIMEOUT",
        best_partial,
    })
}

fn search_status_to_result(status: SearchStatus, prefix: Vec<(usize, usize)>, bp: BestPartial) -> SolveResult {
    match status {
        SearchStatus::Solved(mut moves) => {
            let mut full = prefix;
            full.append(&mut moves);
            SolveResult { moves: full, status: "SOLVED", best_partial: bp }
        }
        SearchStatus::UnknownRevealed(mut moves) => {
            let mut full = prefix;
            full.append(&mut moves);
            SolveResult { moves: full, status: "UNKNOWN_REVEALED", best_partial: bp }
        }
        SearchStatus::BottleUnlocked(mut moves) => {
            let mut full = prefix;
            full.append(&mut moves);
            SolveResult { moves: full, status: "BOTTLE_UNLOCKED", best_partial: bp }
        }
        SearchStatus::NoSolution => SolveResult { moves: vec![], status: "NO_SOLUTION", best_partial: bp },
        SearchStatus::Timeout => SolveResult { moves: vec![], status: "TIMEOUT", best_partial: bp },
        SearchStatus::Stopped => SolveResult { moves: vec![], status: "STOPPED", best_partial: bp },
    }
}
