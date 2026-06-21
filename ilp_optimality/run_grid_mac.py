#!/usr/bin/env python3
"""
run_grid_mac.py — run the full policy grid on the REAL Kuiper-630 state + precomputed paths.
Produces grid_summary.csv = the paper's centerpiece (each literature method = a CRP config,
scored on WCE / median kₗ / max kₗ / oversub, and gap-to-optimum once the ILP OPT is supplied).

RUN FROM hypatia ROOT (after precompute finished):
    cd /Users/omartahboub/Desktop/simulations/hypatia
    export PYTHONPATH=$PWD:$PWD/satgenpy
    DFE_WORKLOAD=matrix TM_SKEW=0.6 TM_MAXFLOWS=300 \
    PATHS_OUT=precomputed_paths PATHS_SNAPSHOT_T=0 \
    OPT_RESERVOIR=  python3 run_grid_mac.py
    # (leave OPT_RESERVOIR empty until the ILP gives the optimum; then set it to fill gap_to_opt)
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grid_sweep

SNAP_T = float(os.environ.get("PATHS_SNAPSHOT_T", "0"))
OPT = os.environ.get("OPT_RESERVOIR", "")
OPT = float(OPT) if OPT.strip() else None


def build_state_and_workload():
    import ast
    from satgen.dfe.graph_builder import build_snapshots
    from satgen.dfe.dynamic_state_adapter import SatgenpyDynamicState
    from dfe.workload_gen import realize_workloads
    GEN = ("paper/satellite_networks_state/gen_data/"
           "kuiper_630_isls_plus_grid_ground_stations_top_100_"
           "algorithm_free_one_only_over_isls")
    MAIN = "paper/satellite_networks_state/main_kuiper_630.py"
    ns = {"math": math}
    for node in ast.parse(open(MAIN).read()).body:
        if (isinstance(node, ast.Assign) and len(node.targets)==1
                and isinstance(node.targets[0], ast.Name)):
            try: ns[node.targets[0].id]=eval(compile(ast.Expression(node.value),"<c>","eval"),ns)
            except Exception: pass
    snaps, gs_ids = build_snapshots(
        filename_tles=f"{GEN}/tles.txt",
        filename_ground_stations=f"{GEN}/ground_stations.txt",
        filename_isls=f"{GEN}/isls.txt",
        simulation_end_time_ns=int(os.environ.get("SWEEP_DURATION_NS","200000000000")),
        time_step_ns=1_000_000_000,
        isl_data_rate_bps=10e9, gsl_data_rate_bps=10e9,
        max_isl_length_m=ns["MAX_ISL_LENGTH_M"], max_gsl_length_m=ns["MAX_GSL_LENGTH_M"],
        fault_model=None)
    state = SatgenpyDynamicState.from_snapshot_graphs(snaps, gs_ids)
    gs = list(state.ground_stations())
    wls = realize_workloads(gs,
        skew=float(os.environ.get("TM_SKEW","0.6")),
        load_lambda=float(os.environ.get("TM_LAMBDA","1.0")),
        hetero=os.environ.get("TM_HETERO","uniform"),
        seed=int(os.environ.get("TM_SEED","1")),
        max_flows=int(os.environ.get("TM_MAXFLOWS","300")))
    return state, wls


def main():
    state, wls = build_state_and_workload()
    flows = [{"id": w.id, "src": w.src, "dst": w.dst, "size_bytes": w.size_bytes,
              "deadline_s": w.deadline_s, "release_s": getattr(w, "release_s", 0.0)} for w in wls]
    print(f"[grid] {len(flows)} flows; OPT_RESERVOIR={OPT}")
    grid_sweep.main(state, flows, out_dir=".", t0=SNAP_T,
                    util=float(os.environ.get("DFE_UTILIZATION","0.90")),
                    opt_reservoir=OPT)
    print("[grid] wrote grid_summary.csv + per-config grid_*.csv")


if __name__ == "__main__":
    main()
