# CRP framework grid — literature methods as configurations, scored vs the ILP optimum

CRP is a **constructive constraint-propagation solver framework**: each H1×H2×F2
configuration of its stages instantiates a distinct, complete planner. The contemporary
heuristics are recovered as configurations, and DFE is the êₕ-rate instance.

## Files
- `grid_sweep.py`   — sweeps the named configs over the rich precomputed paths; emits per-flow
  peak kₗ, WCE, oversub, and a reservoir proxy per config -> `grid_summary.csv`.
- `run_grid_mac.py` — driver: builds the real Kuiper-630 state + workload, calls grid_sweep.
- `h2_route_select.py` — the H2 route-selection knob (eap/shortest/loadbal/widest) as a tested
  standalone module, for slotting into `crp_dfe._eap()`.

Named configs (each a literature method = a CRP instance):
  ClassicIP=(fifo,shortest,linerate) · EDF-shortest=(edf,shortest,ehat) ·
  LoadBalanced=(lweef,loadbal,ehat) · FairShare=(lweef,eap,faircap) ·
  DFE=(lweef,eap,ehat) · Widest-ehat=(lweef,widest,ehat)

## Run (from hypatia root, with the harness deps available)
    export PYTHONPATH=$PWD:$PWD/satgenpy
    # 1. precompute candidate paths for the workload's pairs (once per skew/maxflows):
    DFE_WORKLOAD=matrix TM_SKEW=0.3 TM_MAXFLOWS=400 PATHS_KMAX=200 \
      PATHS_OUT=precomputed_paths_s0.3 SWEEP_DURATION_NS=2000000000 \
      python3 run_precompute_mac.py
    # 2. score the grid on that path set:
    DFE_WORKLOAD=matrix TM_SKEW=0.3 TM_MAXFLOWS=400 \
      PATHS_OUT=precomputed_paths_s0.3 PATHS_SNAPSHOT_T=0 SWEEP_DURATION_NS=2000000000 \
      python3 ilp_optimality/run_grid_mac.py
⚠ Always cap SWEEP_DURATION_NS (e.g. 2e9) — the default 200e9 eagerly builds 200 snapshots.

## Key findings (see ilp_optimality/ results)
1. **F2 (rate rule) is the decisive stage.** êₕ attains the reservoir bound kₗ≤1 and matches
   the LP optimum (gap 0); faircap and linerate do not.
2. **The separation only appears in a dispersed (low-skew) regime.** At skew≈0.6 the bottleneck
   is the source GSL (first hop), so faircap ≡ êₕ and is hidden. At skew≈0.3, traffic converges
   on shared ISLs (downstream), faircap over-commits (kₗ→5.5 on 68 flows) and separates;
   linerate is catastrophic (kₗ→57.8 on all flows). DFE/êₕ stays at kₗ=1, gap 0.
3. **Load (λ) and utilization do not separate the reservoir** — kₗ ratios cancel them; λ only
   lowers deadline satisfaction (WCE), equally for every config.
4. **Honest scope:** DFE is tied within the êₕ group (LoadBalanced/Widest also reach kₗ=1);
   H1/H2 give only a marginal WCE edge. The defensible claim is rate-rule-centric:
   "êₕ is the unique rate rule attaining kₗ≤1; DFE is its principled instance."
