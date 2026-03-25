use std::sync::Arc;

// ---------------------------------------------------------------------------
// Color
// ---------------------------------------------------------------------------

/// Matches Python Color enum values exactly.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
#[repr(u8)]
pub enum Color {
    Red = 0,
    Purple = 1,
    Grey = 2,
    Green = 3,
    Yellow = 4,
    Orange = 5,
    Blue = 6,
    Cyan = 7,
    Unknown = 99,
}

impl Color {
    pub fn from_u8(v: u8) -> Option<Self> {
        match v {
            0 => Some(Color::Red),
            1 => Some(Color::Purple),
            2 => Some(Color::Grey),
            3 => Some(Color::Green),
            4 => Some(Color::Yellow),
            5 => Some(Color::Orange),
            6 => Some(Color::Blue),
            7 => Some(Color::Cyan),
            99 => Some(Color::Unknown),
            _ => None,
        }
    }

    pub fn to_u8(self) -> u8 { self as u8 }
}

// ---------------------------------------------------------------------------
// LockCondition
// ---------------------------------------------------------------------------

/// Mirrors Python LockCondition: count + optional color (None = ANY).
#[derive(Clone, Debug)]
pub struct LockCondition {
    pub count: u32,
    pub color: Option<Color>, // None means ANY
}

impl LockCondition {
    /// completed_colors is indexed by color value (0..=7).
    pub fn is_unlocked(&self, completed_count: u32, completed_colors: &[u32; 8]) -> bool {
        match self.color {
            None => completed_count >= self.count,
            Some(c) => completed_colors[c.to_u8() as usize] >= self.count,
        }
    }
}

// ---------------------------------------------------------------------------
// Structural constants
// ---------------------------------------------------------------------------

/// Max bottles we support.
pub const MAX_BOTTLES: usize = 32;
/// Fixed bottle capacity.
pub const BOTTLE_CAP: usize = 4;

// ---------------------------------------------------------------------------
// Bottle  (stack-allocated, 5 bytes)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub struct Bottle {
    pub slots: [u8; BOTTLE_CAP], // color values; 255 = empty slot
    pub len: u8,
}

impl Bottle {
    pub fn empty() -> Self { Bottle { slots: [255; BOTTLE_CAP], len: 0 } }

    pub fn push(&mut self, color: u8) {
        debug_assert!((self.len as usize) < BOTTLE_CAP);
        self.slots[self.len as usize] = color;
        self.len += 1;
    }

    pub fn pop(&mut self) -> u8 {
        debug_assert!(self.len > 0);
        self.len -= 1;
        self.slots[self.len as usize]
    }

    pub fn is_empty(&self) -> bool { self.len == 0 }
    pub fn is_full(&self) -> bool { self.len as usize == BOTTLE_CAP }
}

// ---------------------------------------------------------------------------
// HiddenMask  (16 bytes, stack)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, Default)]
pub struct HiddenMask(pub u128);

impl HiddenMask {
    pub fn is_hidden(&self, bottle_idx: usize, slot_idx: usize) -> bool {
        let bit = bottle_idx * BOTTLE_CAP + slot_idx;
        (self.0 >> bit) & 1 == 1
    }
    pub fn set(&mut self, bottle_idx: usize, slot_idx: usize) {
        self.0 |= 1u128 << (bottle_idx * BOTTLE_CAP + slot_idx);
    }
    pub fn clear(&mut self, bottle_idx: usize, slot_idx: usize) {
        self.0 &= !(1u128 << (bottle_idx * BOTTLE_CAP + slot_idx));
    }
    pub fn iter(&self) -> impl Iterator<Item = (usize, usize)> {
        let mask = self.0;
        (0..128usize)
            .filter(move |&b| (mask >> b) & 1 == 1)
            .map(|b| (b / BOTTLE_CAP, b % BOTTLE_CAP))
    }
}

// ---------------------------------------------------------------------------
// BottleMask  (8 bytes, stack)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, Default)]
pub struct BottleMask(pub u64);

impl BottleMask {
    pub fn contains(&self, idx: usize) -> bool { (self.0 >> idx) & 1 == 1 }
    pub fn insert(&mut self, idx: usize) { self.0 |= 1u64 << idx; }
    pub fn minus(&self, other: BottleMask) -> BottleMask { BottleMask(self.0 & !other.0) }
    pub fn iter(&self) -> impl Iterator<Item = usize> {
        let mask = self.0;
        (0..64usize).filter(move |&i| (mask >> i) & 1 == 1)
    }
}

// ---------------------------------------------------------------------------
// GameState  — fully stack-allocated except the Arc for lock_conditions
//
// Memory per state (32-bottle budget):
//   bottles:           32 × 5  = 160 bytes
//   n_bottles:                    1 byte
//   locked/completed:             8 + 8 = 16 bytes
//   completed_colors: [u32;8]  = 32 bytes
//   hidden:            u128    = 16 bytes
//   lock_conditions:   Arc ptr =  8 bytes  (shared, clone is O(1))
//   ─────────────────────────────────────
//   Total:                      ~233 bytes  (no heap allocation per clone)
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct GameState {
    pub n_bottles: u8,
    pub bottles: [Bottle; MAX_BOTTLES],  // first n_bottles entries are valid
    pub locked: BottleMask,
    pub completed: BottleMask,
    /// Indexed by color value 0..=7.  No heap allocation — fixed array.
    pub completed_colors: [u32; 8],
    /// Shared across all states derived from the same puzzle — Arc clone is O(1).
    pub lock_conditions: Arc<Vec<Option<LockCondition>>>,
    pub hidden: HiddenMask,
}

impl GameState {
    #[inline]
    pub fn n(&self) -> usize { self.n_bottles as usize }

    pub fn is_goal(&self) -> bool {
        for i in 0..self.n() {
            let b = &self.bottles[i];
            if b.is_empty() { continue; }
            if b.len != BOTTLE_CAP as u8 { return false; }
            let c0 = b.slots[0];
            if c0 == Color::Unknown.to_u8() { return false; }
            if !b.slots[..BOTTLE_CAP].iter().all(|&c| c == c0) { return false; }
            for j in 0..BOTTLE_CAP {
                if self.hidden.is_hidden(i, j) { return false; }
            }
        }
        true
    }

    /// Compact bytes key — same format as Python's to_key().
    pub fn to_key(&self) -> Vec<u8> {
        let n = self.n();
        let mut arr = Vec::with_capacity(n * 2 + 4);
        for i in 0..n {
            let b = &self.bottles[i];
            let slots = [
                if b.len > 0 { b.slots[0] } else { 255 },
                if b.len > 1 { b.slots[1] } else { 255 },
                if b.len > 2 { b.slots[2] } else { 255 },
                if b.len > 3 { b.slots[3] } else { 255 },
            ];
            for k in (0..4).step_by(2) {
                arr.push((encode_nibble(slots[k]) << 4) | encode_nibble(slots[k + 1]));
            }
        }
        for (bi, si) in self.hidden.iter() {
            arr.push(bi as u8);
            arr.push(si as u8);
        }
        arr
    }

    pub fn apply_move(&self, from_idx: usize, to_idx: usize) -> Option<GameState> {
        let from = &self.bottles[from_idx];
        let to = &self.bottles[to_idx];

        if from.is_empty() || to.is_full() { return None; }

        let top_slot = from.len as usize - 1;
        if self.hidden.is_hidden(from_idx, top_slot) { return None; }

        let from_color = from.slots[top_slot];
        if !to.is_empty() && to.slots[to.len as usize - 1] != from_color { return None; }

        let mut count = 1usize;
        for i in (0..top_slot).rev() {
            if self.hidden.is_hidden(from_idx, i) { break; }
            if from.slots[i] == from_color { count += 1; } else { break; }
        }

        let space = BOTTLE_CAP - to.len as usize;
        if space < count { return None; }

        // Clone bottles array (stack copy — no heap allocation)
        let mut new_bottles = self.bottles;
        for _ in 0..count {
            let c = new_bottles[from_idx].pop();
            new_bottles[to_idx].push(c);
        }

        // Auto-reveal hidden slot at top of from_bottle
        let mut new_hidden = self.hidden;
        let new_from = &new_bottles[from_idx];
        if !new_from.is_empty() {
            let new_top = new_from.len as usize - 1;
            if new_hidden.is_hidden(from_idx, new_top) {
                let revealed_color = new_from.slots[new_top];
                new_hidden.clear(from_idx, new_top);
                for j in (0..new_top).rev() {
                    if new_hidden.is_hidden(from_idx, j) && new_from.slots[j] == revealed_color {
                        new_hidden.clear(from_idx, j);
                    } else {
                        break;
                    }
                }
            }
        }

        // Recompute completed
        let mut new_completed = BottleMask::default();
        let mut new_completed_colors = [0u32; 8];
        for i in 0..self.n() {
            let b = &new_bottles[i];
            if b.len as usize == BOTTLE_CAP
                && b.slots[0] != Color::Unknown.to_u8()
                && b.slots[..BOTTLE_CAP].iter().all(|&c| c == b.slots[0])
                && (0..BOTTLE_CAP).all(|j| !new_hidden.is_hidden(i, j))
            {
                new_completed.insert(i);
                let ci = b.slots[0] as usize;
                if ci < 8 { new_completed_colors[ci] += 1; }
            }
        }

        // Recompute locked
        let mut new_locked = BottleMask::default();
        let total_completed = new_completed.0.count_ones() as u32;
        for (bi, lc_opt) in self.lock_conditions.iter().enumerate() {
            if let Some(lc) = lc_opt {
                if !lc.is_unlocked(total_completed, &new_completed_colors) {
                    new_locked.insert(bi);
                }
            }
        }

        Some(GameState {
            n_bottles: self.n_bottles,
            bottles: new_bottles,
            locked: new_locked,
            completed: new_completed,
            completed_colors: new_completed_colors,
            lock_conditions: Arc::clone(&self.lock_conditions), // O(1)
            hidden: new_hidden,
        })
    }
}

fn encode_nibble(raw: u8) -> u8 {
    if raw == 255 { 15 } else if raw == 99 { 14 } else { raw }
}
