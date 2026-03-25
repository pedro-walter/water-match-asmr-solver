use crate::types::{GameState, Color, BOTTLE_CAP};

pub fn heuristic(state: &GameState) -> f32 {
    let n = state.n();
    let accessible_unknowns: usize = (0..n)
        .filter(|&i| !state.locked.contains(i))
        .map(|i| {
            let b = &state.bottles[i];
            (0..b.len as usize).filter(|&k| b.slots[k] == Color::Unknown.to_u8()).count()
        })
        .sum();

    if accessible_unknowns > 0 {
        return unknown_bonus(state);
    }
    color_fragmentation_heuristic(state)
}

fn unknown_bonus(state: &GameState) -> f32 {
    let n = state.n();
    let total: usize = (0..n)
        .map(|i| {
            let b = &state.bottles[i];
            (0..b.len as usize).filter(|&k| b.slots[k] == Color::Unknown.to_u8()).count()
        })
        .sum();
    -0.5 * total as f32
}

pub fn color_fragmentation_heuristic(state: &GameState) -> f32 {
    // color_index (0..=7) → number of distinct non-completed bottles it appears in
    let mut color_bottles = [0u32; 8];
    let mut disruption: u32 = 0;
    let n = state.n();

    for i in 0..n {
        if state.completed.contains(i) { continue; }
        let b = &state.bottles[i];
        if b.is_empty() { continue; }

        let mut seen = [false; 8];
        for k in 0..b.len as usize {
            let c = b.slots[k];
            if c < 8 { seen[c as usize] = true; }
        }
        for c in 0..8usize {
            if seen[c] { color_bottles[c] += 1; }
        }

        if !state.locked.contains(i) {
            for j in 1..b.len as usize {
                if b.slots[j] != b.slots[j - 1] { disruption += 1; }
            }
        }
    }

    let fragmentation: u32 = color_bottles.iter().map(|&v| v.saturating_sub(1)).sum();
    let base = fragmentation.max(disruption) as f32;

    let mut lock_penalty: u32 = 0;
    for (bi, lc_opt) in state.lock_conditions.iter().enumerate() {
        if let Some(lc) = lc_opt {
            if !state.locked.contains(bi) { continue; }
            if let Some(color) = lc.color {
                let ci = color.to_u8() as usize;
                let have = if ci < 8 { state.completed_colors[ci] } else { 0 };
                let need = lc.count.saturating_sub(have);
                if need > 0 {
                    let bottles_with_prereq = if ci < 8 { color_bottles[ci] } else { 0 };
                    let prereq_frag = bottles_with_prereq.saturating_sub(need);
                    lock_penalty += need * BOTTLE_CAP as u32 + prereq_frag;
                }
            }
        }
    }

    base + lock_penalty as f32
}
