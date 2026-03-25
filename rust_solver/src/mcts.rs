use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use crate::astar::{BestPartial, SearchStatus};
use crate::heuristic::heuristic;
use crate::moves::{generate_valid_moves, is_revealing_unknown, is_unlocking_unknown_bottle};
use crate::types::GameState;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// UCB1 exploration constant (√2).
const C: f64 = std::f64::consts::SQRT_2;

/// Max moves per rollout simulation.
const ROLLOUT_DEPTH: usize = 300;

/// How often (in MCTS iterations) to check RAM and tree size.
const CHECK_INTERVAL: u64 = 5_000;

/// Free RAM threshold in KB below which we compact (1 GB).
const RAM_THRESHOLD_KB: u64 = 1_024 * 1_024;

/// Hard cap on tree nodes per thread.  When reached, compact immediately.
/// 100K nodes × ~280 bytes × 8 threads ≈ 224 MB peak — well within budget.
const TREE_SIZE_THRESHOLD: usize = 100_000;

// ---------------------------------------------------------------------------
// Terminal kind
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq)]
enum Terminal {
    Solved,
    Stuck,
    UnknownRevealed,
    BottleUnlocked,
}

// ---------------------------------------------------------------------------
// Tree node
// ---------------------------------------------------------------------------

#[derive(Clone)]
struct Node {
    state:      GameState,
    parent:     Option<u32>,
    move_here:  Option<(u8, u8)>,  // move that produced this node from its parent
    children:   Vec<u32>,           // indices into the arena Vec
    untried:    Vec<(u8, u8)>,      // valid moves not yet expanded
    visits:     u32,
    reward_sum: f64,
    terminal:   Option<Terminal>,
}

impl Node {
    fn new(state: GameState, parent: Option<u32>, move_here: Option<(u8, u8)>) -> Self {
        let moves = generate_valid_moves(&state);
        let (terminal, untried) = if state.is_goal() {
            (Some(Terminal::Solved), vec![])
        } else if moves.is_empty() {
            (Some(Terminal::Stuck), vec![])
        } else {
            (None, moves.iter().map(|&(f, t)| (f as u8, t as u8)).collect())
        };
        Node {
            state,
            parent,
            move_here,
            children: vec![],
            untried,
            visits: 0,
            reward_sum: 0.0,
            terminal,
        }
    }

    fn avg_reward(&self) -> f64 {
        if self.visits == 0 { 0.0 } else { self.reward_sum / self.visits as f64 }
    }

    fn completed_count(&self) -> u32 {
        self.state.completed.0.count_ones() as u32
    }
}

// ---------------------------------------------------------------------------
// UCB1
// ---------------------------------------------------------------------------

fn ucb1(node: &Node, log_parent_visits: f64) -> f64 {
    if node.visits == 0 {
        return f64::INFINITY;
    }
    node.reward_sum / node.visits as f64
        + C * (log_parent_visits / node.visits as f64).sqrt()
}

// ---------------------------------------------------------------------------
// Selection — walk tree by UCB1 until a node with untried moves or terminal
// ---------------------------------------------------------------------------

fn select(nodes: &[Node]) -> u32 {
    let mut idx: u32 = 0;
    loop {
        let n = &nodes[idx as usize];
        if n.terminal.is_some() || !n.untried.is_empty() || n.children.is_empty() {
            return idx;
        }
        let log_pv = (n.visits as f64).ln();
        idx = *n.children.iter().max_by(|&&a, &&b| {
            ucb1(&nodes[a as usize], log_pv)
                .partial_cmp(&ucb1(&nodes[b as usize], log_pv))
                .unwrap_or(std::cmp::Ordering::Equal)
        }).unwrap();
    }
}

// ---------------------------------------------------------------------------
// Expansion — pop one untried move, create a child node
// Returns (child_index, terminal_kind_if_any)
// ---------------------------------------------------------------------------

fn expand(nodes: &mut Vec<Node>, idx: u32) -> Option<(u32, Option<Terminal>)> {
    let mv = nodes[idx as usize].untried.pop()?;
    let (from, to) = (mv.0 as usize, mv.1 as usize);

    // Clone parent state now so we can mutate `nodes` freely afterward.
    let parent_state = nodes[idx as usize].state.clone();

    // Unknown-revealing moves must pause the search — create terminal child
    // carrying the move so the full path is intact when we return.
    if is_revealing_unknown(&parent_state, from) {
        let child = Node {
            state:      parent_state,
            parent:     Some(idx),
            move_here:  Some((from as u8, to as u8)),
            children:   vec![],
            untried:    vec![],
            visits:     0,
            reward_sum: 0.0,
            terminal:   Some(Terminal::UnknownRevealed),
        };
        let cidx = nodes.len() as u32;
        nodes.push(child);
        nodes[idx as usize].children.push(cidx);
        return Some((cidx, Some(Terminal::UnknownRevealed)));
    }

    let new_state = parent_state.apply_move(from, to)?;

    let forced_terminal = if is_unlocking_unknown_bottle(&parent_state, &new_state) {
        Some(Terminal::BottleUnlocked)
    } else {
        None
    };

    let mut child = Node::new(new_state, Some(idx), Some((from as u8, to as u8)));
    if let Some(t) = forced_terminal {
        child.terminal = Some(t);
        child.untried.clear();
    }

    let terminal = child.terminal;
    let cidx = nodes.len() as u32;
    nodes.push(child);
    nodes[idx as usize].children.push(cidx);
    Some((cidx, terminal))
}

// ---------------------------------------------------------------------------
// Rollout — greedy simulation
// ---------------------------------------------------------------------------

fn rollout(initial: &GameState, heuristic_weight: f32) -> f64 {
    let mut state = initial.clone();

    for _ in 0..ROLLOUT_DEPTH {
        if state.is_goal() {
            return 1.0;
        }
        let moves = generate_valid_moves(&state);
        if moves.is_empty() {
            break;
        }
        if moves.iter().any(|&(f, _)| is_revealing_unknown(&state, f)) {
            return 0.6;
        }
        let mut best_h = f32::INFINITY;
        let mut best_next: Option<GameState> = None;
        for (from, to) in moves {
            if let Some(next) = state.apply_move(from, to) {
                if is_unlocking_unknown_bottle(&state, &next) {
                    return 0.6;
                }
                let h = heuristic(&next) * heuristic_weight;
                if h < best_h {
                    best_h = h;
                    best_next = Some(next);
                }
            }
        }
        match best_next {
            Some(s) => state = s,
            None    => break,
        }
    }

    let completed = state.completed.0.count_ones() as f64;
    let total     = state.n_bottles as f64;
    let h         = heuristic(&state) as f64;
    let progress  = completed / total;
    let closeness = 1.0 / (1.0 + h * 0.05);
    (progress + closeness) * 0.5
}

// ---------------------------------------------------------------------------
// Backpropagation
// ---------------------------------------------------------------------------

fn backpropagate(nodes: &mut Vec<Node>, mut idx: u32, reward: f64) {
    loop {
        nodes[idx as usize].visits     += 1;
        nodes[idx as usize].reward_sum += reward;
        match nodes[idx as usize].parent {
            Some(p) => idx = p,
            None    => break,
        }
    }
}

// ---------------------------------------------------------------------------
// Path extraction — walk parent pointers from a node back to the root
// ---------------------------------------------------------------------------

fn extract_path(nodes: &[Node], mut idx: u32) -> Vec<(usize, usize)> {
    let mut path = Vec::new();
    loop {
        if let Some(mv) = nodes[idx as usize].move_here {
            path.push((mv.0 as usize, mv.1 as usize));
        }
        match nodes[idx as usize].parent {
            Some(p) => idx = p,
            None    => break,
        }
    }
    path.reverse();
    path
}

// ---------------------------------------------------------------------------
// Available RAM (Linux only — returns u64::MAX on other platforms)
// ---------------------------------------------------------------------------

fn free_ram_kb() -> u64 {
    #[cfg(target_os = "linux")]
    {
        if let Ok(content) = std::fs::read_to_string("/proc/meminfo") {
            for line in content.lines() {
                if line.starts_with("MemAvailable:") {
                    if let Some(kb_str) = line.split_whitespace().nth(1) {
                        if let Ok(kb) = kb_str.parse::<u64>() {
                            return kb;
                        }
                    }
                }
            }
        }
    }
    u64::MAX
}

// ---------------------------------------------------------------------------
// Tree compaction — advance the root to its most-visited child, discarding
// all sibling subtrees.  Rebuilds the arena with compact indices so that
// the new root is always at index 0.
//
// The committed move is appended to `committed_prefix`.
// Returns false if there are no children or not enough visits yet.
// The `forced` flag bypasses the minimum-visits guard (used when RAM is low).
// ---------------------------------------------------------------------------

fn compact_to_best_child(
    nodes: &mut Vec<Node>,
    committed_prefix: &mut Vec<(usize, usize)>,
) -> bool {
    if nodes[0].children.is_empty() {
        return false;
    }

    let best_child = *nodes[0].children.iter()
        .max_by_key(|&&c| nodes[c as usize].visits)
        .unwrap();

    // Don't commit to game-pause terminals — the main loop returns those
    // immediately, so this should never trigger in practice.
    if let Some(t) = nodes[best_child as usize].terminal {
        if t != Terminal::Stuck {
            return false;
        }
    }

    // Record committed move
    if let Some(mv) = nodes[best_child as usize].move_here {
        committed_prefix.push((mv.0 as usize, mv.1 as usize));
    }

    // BFS traversal of the kept subtree to assign new contiguous indices.
    let mut old_to_new: Vec<u32> = vec![u32::MAX; nodes.len()];
    let mut bfs: VecDeque<u32> = VecDeque::new();
    let mut order: Vec<u32> = Vec::new();

    bfs.push_back(best_child);
    while let Some(old_idx) = bfs.pop_front() {
        old_to_new[old_idx as usize] = order.len() as u32;
        order.push(old_idx);
        for &c in &nodes[old_idx as usize].children {
            bfs.push_back(c);
        }
    }

    // Rebuild the arena with remapped indices.
    let mut new_nodes: Vec<Node> = Vec::with_capacity(order.len());
    for &old_idx in &order {
        let old      = &nodes[old_idx as usize];
        let new_par  = if old_idx == best_child {
            None
        } else {
            old.parent.map(|p| old_to_new[p as usize])
        };
        let new_children: Vec<u32> = old.children.iter()
            .map(|&c| old_to_new[c as usize])
            .collect();
        new_nodes.push(Node {
            state:      old.state.clone(),
            parent:     new_par,
            move_here:  old.move_here,
            children:   new_children,
            untried:    old.untried.clone(),
            visits:     old.visits,
            reward_sum: old.reward_sum,
            terminal:   old.terminal,
        });
    }

    let freed = nodes.len() - new_nodes.len();
    *nodes = new_nodes;
    eprintln!("  [MCTS] Pruned tree: committed 1 move, freed {} nodes ({} remain)",
              freed, nodes.len());
    true
}

// ---------------------------------------------------------------------------
// Main MCTS search
// ---------------------------------------------------------------------------

pub fn mcts_search(
    initial: GameState,
    heuristic_weight: f32,
    max_nodes: u64,
    tree_size: usize,
    stop: Option<Arc<AtomicBool>>,
) -> (SearchStatus, BestPartial) {
    let mut nodes: Vec<Node> = Vec::with_capacity(tree_size);
    let mut best_partial = BestPartial::default();
    // Moves committed during tree compactions — prepended to any returned path.
    let mut committed_prefix: Vec<(usize, usize)> = Vec::new();
    let mut iterations: u64 = 0;

    let root = Node::new(initial, None, None);
    if root.terminal == Some(Terminal::Solved) {
        return (SearchStatus::Solved(vec![]), best_partial);
    }
    nodes.push(root);

    // Helper: build the full path by prepending committed_prefix.
    // (Defined as a closure to avoid repeating the extend pattern.)
    macro_rules! full_path {
        ($node_idx:expr) => {{
            let mut p = committed_prefix.clone();
            p.extend(extract_path(&nodes, $node_idx));
            p
        }};
    }

    while iterations < max_nodes {
        iterations += 1;

        // ── Stop signal ───────────────────────────────────────────────────────
        if iterations % 2000 == 0 {
            if let Some(ref flag) = stop {
                if flag.load(Ordering::Relaxed) {
                    return (SearchStatus::Stopped, best_partial);
                }
            }
        }

        // ── Compact when tree hits the size cap OR RAM is running low ─────────
        if iterations % CHECK_INTERVAL == 0 {
            let free_kb = free_ram_kb();
            let need_compact = nodes.len() >= tree_size
                || free_kb < RAM_THRESHOLD_KB;

            if need_compact {
                if free_kb < RAM_THRESHOLD_KB {
                    eprintln!("  [MCTS] Low RAM ({} MB free), compacting...",
                              free_kb / 1024);
                }
                compact_to_best_child(&mut nodes, &mut committed_prefix);

                // Check if the new root is itself a game-pause terminal.
                if let Some(t) = nodes[0].terminal {
                    match t {
                        Terminal::Solved => {
                            return (SearchStatus::Solved(committed_prefix), best_partial);
                        }
                        Terminal::UnknownRevealed => {
                            let path = full_path!(0);
                            return (SearchStatus::UnknownRevealed(path), best_partial);
                        }
                        Terminal::BottleUnlocked => {
                            let path = full_path!(0);
                            return (SearchStatus::BottleUnlocked(path), best_partial);
                        }
                        Terminal::Stuck => {
                            return (SearchStatus::Timeout, best_partial);
                        }
                    }
                }
            }
        }

        // ── 1. Select ─────────────────────────────────────────────────────────
        let sel = select(&nodes);

        // ── 2. Terminal node — backprop and handle ────────────────────────────
        if let Some(t) = nodes[sel as usize].terminal {
            match t {
                Terminal::Solved => {
                    return (SearchStatus::Solved(full_path!(sel)), best_partial);
                }
                Terminal::UnknownRevealed => {
                    return (SearchStatus::UnknownRevealed(full_path!(sel)), best_partial);
                }
                Terminal::BottleUnlocked => {
                    return (SearchStatus::BottleUnlocked(full_path!(sel)), best_partial);
                }
                Terminal::Stuck => {
                    let completed = nodes[sel as usize].completed_count() as f64;
                    let total     = nodes[sel as usize].state.n_bottles as f64;
                    backpropagate(&mut nodes, sel, completed / total);
                    continue;
                }
            }
        }

        // ── 3. Expand ─────────────────────────────────────────────────────────
        let (cidx, special) = match expand(&mut nodes, sel) {
            Some(r) => r,
            None => {
                let r = nodes[sel as usize].avg_reward();
                backpropagate(&mut nodes, sel, r);
                continue;
            }
        };

        // Update best_partial whenever we reach a new node with progress.
        let completed = nodes[cidx as usize].completed_count();
        if completed > best_partial.completed_count {
            best_partial.update(full_path!(cidx), completed, iterations);
        }

        // ── 4. Game-pause terminals return immediately ────────────────────────
        match special {
            Some(Terminal::Solved) => {
                return (SearchStatus::Solved(full_path!(cidx)), best_partial);
            }
            Some(Terminal::UnknownRevealed) => {
                return (SearchStatus::UnknownRevealed(full_path!(cidx)), best_partial);
            }
            Some(Terminal::BottleUnlocked) => {
                return (SearchStatus::BottleUnlocked(full_path!(cidx)), best_partial);
            }
            Some(Terminal::Stuck) => {
                let completed = nodes[cidx as usize].completed_count() as f64;
                let total     = nodes[cidx as usize].state.n_bottles as f64;
                backpropagate(&mut nodes, cidx, completed / total);
                continue;
            }
            None => {}
        }

        // ── 5. Rollout ────────────────────────────────────────────────────────
        let reward = rollout(&nodes[cidx as usize].state, heuristic_weight);

        // ── 6. Backpropagate ──────────────────────────────────────────────────
        backpropagate(&mut nodes, cidx, reward);
    }

    (SearchStatus::Timeout, best_partial)
}
