#!/usr/bin/env python3
"""
run_ilp.py — drive the ILP optimality solver over the REAL Kuiper-630 snapshots,
compare against CRP-DFE / faircap / linerate, emit optimality_gap.csv.

Runs inside the Docker image with the hypatia harness mounted at /work/hypatia.
It reuses the harness's DynamicState builder so the ILP sees exactly the same
network the planner does (apples-to-apples).

Env knobs (mirror run_phase2.py):
  DFE_WORKLOAD=matrix TM_SKEW=0.6 TM_MAXFLOWS=300
  ILP_MODE=lp|milp           (lp = relaxation lower-bound, default; milp = exact integral)
  ILP_SNAPSHOTS=all|first|N   (how many snapshots to solve; 'first' = t0 only, fast)
  OUT_DIR=/work/out
"""
import os, sys, csv, json
from collections import defaultdict

OUT = os.environ.get("OUT_DIR", "/work/out")
os.makedirs(OUT, exist_ok=True)

# --- import the solver core ---
sys.path.insert(0, os.path.dirname(__file__))
from ilp_optimality import solve_snapshot_min_reservoir

# --- import the harness state builder (same as run_phase2.py) ---
# These imports require /work/hypatia on PYTHONPATH (set in Dockerfile).
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


def build_state_and_workload():
    """Mirror run_phase2.py's state + matrix workload construction."""
    import ast, math
    GEN = ("paper/satellite_networks_state/gen_data/"
           "kuiper_630_isls_plus_grid_ground_stations_top_100_"
           "algorithm_free_one_only_over_isls")
    MAIN = "paper/satellite_networks_state/main_kuiper_630.py"
    ns = {"math": math}
    for node in ast.parse(open(MAIN).read()).body:
        if (isinstance(node, ast.Assign) and len(node.targets)==1
                and isinstance(node.targets[0], ast.Name)):
            try: ns[node.targets[0].id] = eval(compile(__import__("ast").Expression(node.value),"<c>","eval"), ns)
            except Exception: pass
    max_isl = ns["MAX_ISL_LENGTH_M"]; max_gsl = ns["MAX_GSL_LENGTH_M"]
    dur = int(os.environ.get("SWEEP_DURATION_NS","200000000000"))
    step = 1_000_000_000
    snaps, gs_ids = build_snapshots(
        filename_tles=f"{GEN}/tles.txt",
        filename_ground_stations=f"{GEN}/ground_stations.txt",
        filename_isls=f"{GEN}/isls.txt",
        simulation_end_time_ns=dur, time_step_ns=step,
        isl_data_rate_bps=10e9, gsl_data_rate_bps=10e9,
        max_isl_length_m=max_isl, max_gsl_length_m=max_gsl, fault_model=None)
    state = SatgenpyDynamicState.from_snapshot_graphs(snaps, gs_ids)
    gs = list(state.ground_stations())
    wls = realize_workloads(gs,
        skew=float(os.environ.get("TM_SKEW","0.6")),
        load_lambda=float(os.environ.get("TM_LAMBDA","1.0")),
        hetero=os.environ.get("TM_HETERO","uniform"),
        seed=int(os.environ.get("TM_SEED","1")),
        max_flows=int(os.environ.get("TM_MAXFLOWS","300")))
    return state, gs, wls


def snapshot_view(state, t):
    """Extract nodes, directed edges, capacity, delay at time t from the harness state."""
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


def main():
    if not HARNESS:
        print("[run_ilp] No harness; run ilp_optimality.py --selftest to validate the solver.")
        return
    state, gs, wls = build_state_and_workload()
    print(f"[run_ilp] state built: {len(list(state.nodes()))} nodes, {len(wls)} flows")

    t = 0.0  # ILP_SNAPSHOTS=first -> just t0; extend to loop over the horizon as needed
    nodes, edges, cap, delay = snapshot_view(state, t)
    print(f"[run_ilp] snapshot t={t}: {len(edges)} up-links")

    flows = [{"id": w.id, "src": w.src, "dst": w.dst,
              "demand_bps": (w.size_bytes*8.0)/max(w.deadline_s,1e-9),
              "deadline_s": w.deadline_s} for w in wls]

    opt = solve_snapshot_min_reservoir(nodes, edges, cap, flows, delay)
    print(f"[run_ilp] ILP optimum: {opt}")

    # CRP-DFE actual reservoir (from emit) for the same snapshot would be compared here.
    # Write the gap row.
    with open(os.path.join(OUT, "optimality_gap.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["snapshot_t","opt_reservoir_bps","feasible","status"])
        w.writerow([t, opt.get("opt_reservoir_bps"), opt.get("feasible"), opt.get("status")])
    print(f"[run_ilp] wrote {OUT}/optimality_gap.csv")


if __name__ == "__main__":
    main()
