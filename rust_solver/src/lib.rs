mod astar;
mod chunked_dfs;
mod dfs;
mod heuristic;
mod mcts;
mod moves;
mod parallel;
mod types;

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::sync::mpsc;
use std::time::Duration;

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use types::{Bottle, BottleMask, Color, GameState, HiddenMask, LockCondition, MAX_BOTTLES};

// ---------------------------------------------------------------------------
// Python → Rust state conversion
// ---------------------------------------------------------------------------

fn dict_to_game_state(d: &Bound<'_, PyDict>) -> PyResult<GameState> {
    // bottles
    let py_bottles: Vec<Vec<u8>> = d.get_item("bottles")?.unwrap().extract()?;
    let n = py_bottles.len();
    if n > MAX_BOTTLES {
        return Err(pyo3::exceptions::PyValueError::new_err(
            format!("Too many bottles: {n} > {MAX_BOTTLES}")
        ));
    }

    let mut bottles = [Bottle::empty(); MAX_BOTTLES];
    for (i, raw) in py_bottles.iter().enumerate() {
        for &v in raw {
            Color::from_u8(v)
                .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(format!("Unknown color int {v}")))?;
            bottles[i].push(v);
        }
    }

    // locked_bottles
    let mut locked = BottleMask::default();
    for i in d.get_item("locked_bottles")?.unwrap().extract::<Vec<usize>>()? {
        locked.insert(i);
    }

    // completed_bottles
    let mut completed = BottleMask::default();
    for i in d.get_item("completed_bottles")?.unwrap().extract::<Vec<usize>>()? {
        completed.insert(i);
    }

    // completed_colors: {color_int: count} → [u32; 8]
    let mut completed_colors = [0u32; 8];
    let cc_raw: HashMap<u8, u32> = d.get_item("completed_colors")?.unwrap().extract()?;
    for (c, count) in cc_raw {
        if (c as usize) < 8 { completed_colors[c as usize] = count; }
    }

    // lock_conditions
    let mut lc_vec: Vec<Option<LockCondition>> = vec![None; n];
    if let Some(lc_item) = d.get_item("lock_conditions")? {
        let lc_dict = lc_item.downcast::<PyDict>()?;
        for (k, v) in lc_dict.iter() {
            let bi: usize = k.extract()?;
            let cond_dict = v.downcast::<PyDict>()?;
            let count: u32 = cond_dict.get_item("count")?.unwrap().extract()?;
            let color_raw: i32 = cond_dict.get_item("color")?.unwrap().extract()?;
            let color = if color_raw < 0 { None } else {
                Some(Color::from_u8(color_raw as u8)
                    .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Bad lock color"))?)
            };
            if bi < n { lc_vec[bi] = Some(LockCondition { count, color }); }
        }
    }

    // hidden_slots
    let mut hidden = HiddenMask::default();
    if let Some(hs_item) = d.get_item("hidden_slots")? {
        for pair in hs_item.downcast::<PyList>()?.iter() {
            let p: Vec<usize> = pair.extract()?;
            if p.len() == 2 { hidden.set(p[0], p[1]); }
        }
    }

    Ok(GameState {
        n_bottles: n as u8,
        bottles,
        locked,
        completed,
        completed_colors,
        lock_conditions: Arc::new(lc_vec),
        hidden,
    })
}

// ---------------------------------------------------------------------------
// Exposed Python function
// ---------------------------------------------------------------------------

#[pyfunction]
fn solve_parallel(
    py: Python<'_>,
    state_dict: &Bound<'_, PyDict>,
    heuristic_weight: f32,
    max_iterations: u64,
    tree_size: usize,
    chunk_depth: usize,
    algorithm: &str,
) -> PyResult<PyObject> {
    let state = dict_to_game_state(state_dict)?;
    let algorithm = algorithm.to_owned();

    let stop = Arc::new(AtomicBool::new(false));
    let stop_for_worker = Arc::clone(&stop);

    let (tx, rx) = mpsc::channel::<parallel::SolveResult>();
    std::thread::spawn(move || {
        let result = parallel::solve_parallel(
            state, heuristic_weight, max_iterations, tree_size, chunk_depth,
            stop_for_worker, &algorithm,
        );
        tx.send(result).ok();
    });

    // Poll for the result while checking Python signals every 50 ms.
    // This lets Ctrl+C raise KeyboardInterrupt even while Rust is running.
    let result = loop {
        match rx.try_recv() {
            Ok(result) => break result,
            Err(mpsc::TryRecvError::Empty) => {
                if let Err(e) = py.check_signals() {
                    stop.store(true, Ordering::Relaxed);
                    return Err(e);
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(mpsc::TryRecvError::Disconnected) => {
                return Err(pyo3::exceptions::PyRuntimeError::new_err(
                    "Solver thread terminated unexpectedly",
                ));
            }
        }
    };

    let bp = result.best_partial;
    Ok((result.moves, result.status.to_string(), bp.moves, bp.completed_count, bp.iteration)
        .into_pyobject(py)?.into())
}

// ---------------------------------------------------------------------------
// Module
// ---------------------------------------------------------------------------

#[pymodule]
fn rust_solver(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(solve_parallel, m)?)?;
    Ok(())
}
