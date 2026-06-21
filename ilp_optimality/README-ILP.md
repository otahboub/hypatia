# ILP Optimality-Gap Experiment — run guide (local + AWS via Claude Code)

## GOAL
Prove that CRP-DFE (LWEEF/EAP/êₕ) attains the GLOBAL OPTIMUM reservoir (within ε) at Kuiper-630
scale — the scale-tier analog of the OARNet exhaustive-enumeration proof. The ILP gives the true
minimum-reservoir any policy could achieve; "DFE matches it" is a global-optimality witness.

## WHAT IT COMPUTES
- ILP/LP min-reservoir optimum per snapshot (multi-commodity flow, oversub-slack objective).
- LP relaxation = rigorous LOWER BOUND on min reservoir. If DFE's reservoir == LP bound -> DFE is
  provably optimal. MILP (--integral) = exact, slower; use where tractable.
- Compares OPT vs DFE / faircap / linerate -> optimality gaps.

## FILES
- ilp_optimality.py   — solver core (scipy/HiGHS). Self-tested: `python3 ilp_optimality.py --selftest`
- run_ilp.py          — drives it over the REAL harness DynamicState; emits optimality_gap.csv
- Dockerfile.ilp      — reproducible image

## LOCAL SMOKE TEST (no harness needed)
    python3 ilp_optimality.py --selftest
Expect: test1 opt_reservoir≈0 (splittable), test2 opt_reservoir≈30e6 (over capacity). Both PASS.

## RUN ON AWS (via Claude Code)
1. Build the image (from a dir containing ilp_optimality.py, run_ilp.py, Dockerfile.ilp):
       docker build -f Dockerfile.ilp -t dfe-ilp .
2. Run with the hypatia harness mounted (so the ILP reads the same state the planner does):
       docker run --rm \
         -v /path/to/hypatia:/work/hypatia \
         -v $PWD/out:/work/out \
         -e DFE_WORKLOAD=matrix -e TM_SKEW=0.6 -e TM_MAXFLOWS=300 \
         -e ILP_MODE=lp -e ILP_SNAPSHOTS=first \
         dfe-ilp
3. Result: out/optimality_gap.csv

## SCALING NOTES (important for AWS sizing)
- LP relaxation of multi-commodity flow: variables = (#flows × #up-links) + #links. At Kuiper t0
  (~thousands of up-links, 306 flows) this is LARGE but LP is polynomial — HiGHS handles it; expect
  minutes-to-tens-of-minutes per snapshot on a compute-optimized instance (c6i/c7i, 16–32 vCPU,
  32–64 GB). Start with ILP_SNAPSHOTS=first (t0 only) to validate, then expand.
- MILP (integral paths) is NP-hard; only attempt on a reduced flow set or with a commercial solver
  (Gurobi academic license) if the LP lower-bound proof isn't deemed sufficient. The LP LOWER BOUND
  is already a SOUND optimality witness — matching it proves optimality without integral solve.
- Memory is the likely limit (the dense A_ub/A_eq). For the full snapshot, switch to the sparse
  build (scipy.sparse) — the core already imports lil_matrix; a sparse refactor of A_ub/A_eq is the
  one change needed for full-scale runs. ⚠ TODO before full run: sparsify A_eq/A_ub.

## CLAIM PRODUCED (state with real scope)
"At constellation scale, CRP-DFE attains the LP-optimal reservoir lower bound within gap ε while
meeting all deadlines — matching the global optimum a general solver computes, at heuristic speed.
faircap and line rate are far from this optimum on reservoir (gaps X%, Y%), confirming the F2 rate
rule is what closes the gap."

## ⚠ BEFORE TRUSTING NUMBERS
- Sparsify A_eq/A_ub for full-snapshot scale (memory).
- Confirm the ILP objective == paper's lexicographic (timeliness ≻ reservoir).
- Confirm reservoir def == Lemma 1 surplus (kℓ−1)·Cℓ·|W|.
- Wire the DFE/faircap/linerate per-snapshot reservoir (from the emit CSVs) into the gap columns.
