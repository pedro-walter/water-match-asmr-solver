// Shared search result types used by mcts.rs and parallel.rs.

// ---------------------------------------------------------------------------
// Best partial result
// ---------------------------------------------------------------------------

#[derive(Clone, Default)]
pub struct BestPartial {
    pub moves: Vec<(usize, usize)>,
    pub completed_count: u32,
    pub iteration: u64,
}

impl BestPartial {
    pub fn update(&mut self, moves: Vec<(usize, usize)>, completed: u32, iter: u64) {
        if completed > self.completed_count
            || (completed == self.completed_count && self.completed_count > 0 && iter < self.iteration)
        {
            self.moves = moves;
            self.completed_count = completed;
            self.iteration = iter;
        }
    }

    pub fn merge_from(&mut self, other: &BestPartial) {
        self.update(other.moves.clone(), other.completed_count, other.iteration);
    }
}

// ---------------------------------------------------------------------------
// Public search status (returned to Python via parallel.rs)
// ---------------------------------------------------------------------------

pub enum SearchStatus {
    Solved(Vec<(usize, usize)>),
    UnknownRevealed(Vec<(usize, usize)>),
    BottleUnlocked(Vec<(usize, usize)>),
    NoSolution,
    Timeout,
    Stopped,
}
