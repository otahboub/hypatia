#!/usr/bin/env python3
"""
run_ilp.py — STREAM the ILP optimality solver over Kuiper-630 snapshots, compare
against CRP-DFE / faircap / linerate, emit optimality_gap.csv.

MEMORY NOTE (why this version exists): the previous version built the FULL dynamic
state eagerly — 200 snapshots (200s @ 1000ms) × 1256-node graph × per-link series,
all in RAM — which is terabytes and crashed. The ILP only ever needs ONE snapshot
at a time, so this version builds snapshot t, solves it, DISCARDS it, and moves on.
Peak memory is one snapshot (~MB). build_snapshots(offset_ns=t, end=t+1) is the
single-snapshot primitive (the builder already supports offset_ns).

Env knobs (mirror run_phase2.py):
  DFE_WORKLOAD=matrix TM_SKEW=0.6 TM_MAXFLOWS=300 TM_LAMBDA=1.0 TM_SEED=1
  ILP_MODE=lp|milp            (lp = relaxation lower-bound, default)
  ILP_LP_METHOD=highs|highs-ipm  (passed through to the solver core)
  ILP_SNAPSHOTS=first|all|N   first = t0 only; N = first N snapshots; all = decimated
  ILP_DECIMATE=8              (# representative snapshots when ILP_SNAPSHOTS=all)
  SWEEP_DURATION_NS=200e9     (horizon used to place the decimated snapshots)
  OUT_DIR=/work/out
"""
import os, sys, csv, json, ast, math
from collections import defaultdict

OUT = os.environ.get("OUT_DIR", "/work/out")
os.makedirs(OUT, exist_ok=True)
STEP_NS = 1_000_000_000

# --- solver core ---
sys.path.insert(0, os.path.dirname(__file__))
from ilp_optimality import solve_snapshot_min_reservoir

# --- harness state builder (needs /work/hypatia on PYTHONPATH) ---
try:
    from satgen.dfe.graph_builder import build_snapshots
    from satgen.dfe.dynamic_state_adapter import SatgenpyDynamicState
    from dfe.planners.crp_dfe import CrpDfePlanner
    from dfe.dfe_schedule import Workload
    from dfe.workload_gen import realize_workloads
    HARNESS = True
except Exception as e:
    print(f"[run_ilp] harness import failed ({e}); running in SOLVER-ONLY mode.")
    HARNESS = False


def _config():
    """Parse main_kuiper_630.py for the MAX_ISL/MAX_GSL constants; return paths too."""
    GEN = ("paper/satellite_networks_state/gen_data/"
           "kuiper_630_isls_plus_grid_ground_stations_top_100_"
           "algorithm_free_one_only_over_isls")
    MAIN = "paper/satellite_networks_state/main_kuiper_630.py"
    ns = {"math": math}
    for node in ast.parse(open(MAIN).read()).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            try:
                ns[node.targets[0].id] = eval(
                    compile(ast.Expression(node.value), "<c>", "eval"), ns)
            except Exception:
                pass
    return GEN, ns["MAX_ISL_LENGTH_M"], ns["MAX_GSL_LENGTH_M"]


def build_one(GEN, max_isl, max_gsl, t_ns):
    """Build EXACTLY ONE snapshot at t_ns. Streamed: never holds the full horizon."""
    snaps, gs_ids = build_snapshots(
        filename_tles=f"{GEN}/tles.txt",
        filename_ground_stations=f"{GEN}/ground_stations.txt",
        filename_isls=f"{GEN}/isls.txt",
        simulation_end_time_ns=t_ns + 1, time_step_ns=STEP_NS,
        isl_data_rate_bps=10e9, gsl_data_rate_bps=10e9,
        max_isl_length_m=max_isl, max_gsl_length_m=max_gsl,
        fault_model=None, offset_ns=t_ns)
    return SatgenpyDynamicState.from_snapshot_graphs(snaps, gs_ids)


def snapshot_view(state, t):
    """Extract nodes, directed edges, capacity, delay at time t (seconds)."""
    nodes = list(state.nodes())
    edges = []; cap = {}; delay = {}
    for u in nodes:
        for v in state.neighbors(u):
            if state.link_up(u, v, t):
                e = (u, v); edges.append(e)
                cap[e] = state.capacity_bps(u, v, t)
                try: delay[e] = state.delay_s(u, v, t)
                except TypeError: delay[e] = state.delay_s(u, v)
    return nodes, edges, cap, delay


def chosen_times():
    """Snapshot times (ns) to solve, per ILP_SNAPSHOTS. Decimation avoids the full
    horizon: 'all' picks ILP_DECIMATE evenly-spaced representative snapshots."""
    dur = int(os.environ.get("SWEEP_DURATION_NS", "200000000000"))
    mode = os.environ.get("ILP_SNAPSHOTS", "first")
    n_snap = max(1, dur // STEP_NS)
    if mode == "first":
        return [0]
    if mode == "all":
        k = min(int(os.environ.get("ILP_DECIMATE", "8")), n_snap)
        if k <= 1:
            return [0]
        return [(i * (n_snap - 1) // (k - 1)) * STEP_NS for i in range(k)]
    try:
        N = max(1, min(int(mode), n_snap))
    except ValueError:
        N = 1
    return [i * STEP_NS for i in range(N)]


def main():
    if not HARNESS:
        print("[run_ilp] No harness; run ilp_optimality.py --selftest to validate the solver.")
        return
    GEN, max_isl, max_gsl = _config()

    # workload built ONCE (ground-station node ids are time-invariant)
    state0 = build_one(GEN, max_isl, max_gsl, 0)
    gs = list(state0.ground_stations())
    wls = realize_workloads(
        gs,
        skew=float(os.environ.get("TM_SKEW", "0.6")),
        load_lambda=float(os.environ.get("TM_LAMBDA", "1.0")),
        hetero=os.environ.get("TM_HETERO", "uniform"),
        seed=int(os.environ.get("TM_SEED", "1")),
        max_flows=int(os.environ.get("TM_MAXFLOWS", "300")))
    flows = [{"id": w.id, "src": w.src, "dst": w.dst,
              "demand_bps": (w.size_bytes * 8.0) / max(w.deadline_s, 1e-9),
              "deadline_s": w.deadline_s} for w in wls]
    print(f"[run_ilp] {len(gs)} ground stations, {len(wls)} flows")

    times = chosen_times()
    print(f"[run_ilp] streaming {len(times)} snapshot(s) at indices "
          f"{[t // STEP_NS for t in times]} (one in RAM at a time)")

    # Write the header up front and flush+fsync each row as soon as its snapshot
    # solves, so a kill/crash on a long run never loses completed snapshots.
    csv_path = os.path.join(OUT, "optimality_gap.csv")
    n = 0
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["snapshot_t", "opt_reservoir_bps", "feasible", "status"])
        f.flush(); os.fsync(f.fileno())
        for t_ns in times:
            t_s = t_ns / 1e9
            state = state0 if t_ns == 0 else build_one(GEN, max_isl, max_gsl, t_ns)
            nodes, edges, cap, delay = snapshot_view(state, t_s)
            print(f"[run_ilp] t={t_s:.0f}s: {len(nodes)} nodes, {len(edges)} up-links — solving...")
            opt = solve_snapshot_min_reservoir(nodes, edges, cap, flows, delay)
            print(f"[run_ilp]   -> {opt}")
            w.writerow([t_s, opt.get("opt_reservoir_bps"), opt.get("feasible"), opt.get("status")])
            f.flush(); os.fsync(f.fileno())   # persist this row immediately
            n += 1
            print(f"[run_ilp]   (wrote row {n}/{len(times)} to {csv_path})")
            state = None  # discard; never hold >1 snapshot
    print(f"[run_ilp] done: {csv_path} ({n} row(s))")


if __name__ == "__main__":
    main()
