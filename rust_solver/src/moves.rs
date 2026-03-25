use crate::types::{GameState, Color, BOTTLE_CAP};

/// Count consecutive visible same-color slots from top, stopping at hidden boundary.
pub fn count_consecutive_top(state: &GameState, bottle_idx: usize) -> usize {
    let b = &state.bottles[bottle_idx];
    if b.is_empty() { return 0; }
    let top = b.len as usize - 1;
    if state.hidden.is_hidden(bottle_idx, top) { return 0; }
    let top_color = b.slots[top];
    let mut count = 1;
    for i in (0..top).rev() {
        if state.hidden.is_hidden(bottle_idx, i) { break; }
        if b.slots[i] == top_color { count += 1; } else { break; }
    }
    count
}

/// Number of visible slots (not hidden) in a bottle.
fn visible_count(state: &GameState, bottle_idx: usize) -> usize {
    let b = &state.bottles[bottle_idx];
    (0..b.len as usize).filter(|&k| !state.hidden.is_hidden(bottle_idx, k)).count()
}

/// Generate all valid moves from the current state.
/// Mirrors Python _generate_valid_moves() exactly, including the
/// "only move to first empty bottle, and only if not uniform" rule.
pub fn generate_valid_moves(state: &GameState) -> Vec<(usize, usize)> {
    let mut moves = Vec::new();

    // Find the index of the first usable empty bottle
    let first_empty = (0..state.n())
        .find(|&j| state.bottles[j].is_empty() && !state.locked.contains(j) && !state.completed.contains(j));

    for i in 0..state.n() {
        if state.locked.contains(i) || state.completed.contains(i) { continue; }
        let from = &state.bottles[i];
        if from.is_empty() { continue; }

        let top_slot = from.len as usize - 1;
        if state.hidden.is_hidden(i, top_slot) { continue; }

        let from_color = from.slots[top_slot];
        let from_consec = count_consecutive_top(state, i);
        let vis_count = visible_count(state, i);
        let is_uniform = from_consec == vis_count && from_color != Color::Unknown.to_u8();

        for j in 0..state.n() {
            if i == j { continue; }
            if state.locked.contains(j) || state.completed.contains(j) { continue; }
            let to = &state.bottles[j];
            if to.len as usize == BOTTLE_CAP { continue; }

            if to.is_empty() {
                if Some(j) != first_empty { continue; }
                if is_uniform { continue; }
                moves.push((i, j));
                continue;
            }

            let to_color = to.slots[to.len as usize - 1];
            if from_color == to_color {
                let space = BOTTLE_CAP - to.len as usize;
                if space >= from_consec {
                    moves.push((i, j));
                }
            }
        }
    }

    moves
}

/// True if executing this move would reveal an UNKNOWN color.
pub fn is_revealing_unknown(state: &GameState, from_idx: usize) -> bool {
    let b = &state.bottles[from_idx];
    if b.is_empty() { return false; }
    let top = b.len as usize - 1;
    if b.slots[top] == Color::Unknown.to_u8() { return true; }
    let count = count_consecutive_top(state, from_idx);
    if count < b.len as usize {
        let revealed = b.len as usize - count - 1;
        if b.slots[revealed] == Color::Unknown.to_u8() { return true; }
    }
    false
}

/// True if the move unlocks a bottle whose contents are empty or all-unknown.
pub fn is_unlocking_unknown_bottle(state: &GameState, new_state: &GameState) -> bool {
    let newly_unlocked = state.locked.minus(new_state.locked);
    for idx in newly_unlocked.iter() {
        let b = &new_state.bottles[idx];
        if b.is_empty() || (0..b.len as usize).all(|k| b.slots[k] == Color::Unknown.to_u8()) {
            return true;
        }
    }
    false
}
