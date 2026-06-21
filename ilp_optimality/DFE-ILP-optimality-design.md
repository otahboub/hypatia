# ILP optimality-gap experiment — design (Kuiper-630, proves LWEEF/EAP ≈ global optimum)

## CLAIM TO ESTABLISH
At constellation scale, CRP-DFE (LWEEF/EAP/êₕ) attains the ILP-optimal reservoir within gap ε while
meeting all deadlines — i.e. it matches the GLOBAL OPTIMUM a general solver computes, at heuristic
speed. (Scale-tier analog of the OARNet exhaustive global-maximum proof.)

## THE TWO OBJECTIVES (must match the theory)
1. Timeliness: every admitted flow completes by its deadline (hard constraint).
2. Reservoir conservation: minimize total/peak oversubscription -> minimize the reservoir surplus
   Σ_links max(0, load_ℓ − C_ℓ)·window, equivalently keep kℓ ≤ 1 everywhere if feasible.

## ILP / LP FORMULATION (per time-snapshot, then composed over the horizon)
Decision variables (multi-commodity flow on the time-expanded / per-snapshot residual graph):
  x[f, (a,b)] ∈ {0,1}  (path-selection) OR  r[f,(a,b)] ≥ 0  (rate on link, LP relaxation)
For each flow f with demand d_f, deadline dl_f, source s_f, dest t_f:
  - Flow conservation: at each node, inflow = outflow (except ±d_f at s_f / t_f).
  - Deadline feasibility: chosen path's (Σ wait + Σ propagation + d_f / rate) ≤ dl_f.
  - Link capacity / oversubscription: Σ_f r[f,(a,b)] relates to C(a,b,t); define
      over_ℓ = max(0, Σ_f rate_f·1[f uses ℓ] − C_ℓ).
Objective (lexicographic or weighted):
  PRIMARY  : maximize #flows meeting deadline (timeliness)   — should be ALL on loose deadlines
  SECONDARY: minimize Σ_ℓ over_ℓ (reservoir surplus)         — the conservation objective
  => lexicographic: first satisfy all deadlines, then minimize oversubscription. Matches Theorem 1
     (the two objectives in tension) + Prop 1 (êₕ is the Pareto point).

## WHAT WE COMPARE
- Solve the ILP/LP -> OPT(reservoir), OPT(deadline-met).
- Run CRP-DFE (the emit harness) -> DFE(reservoir), DFE(deadline-met).
- GAP = (DFE − OPT)/OPT. Claim strength: gap ≈ 0 -> LWEEF/EAP/êₕ attains global optimum.
- Also report faircap/linerate gaps (they should be FAR from OPT on reservoir) to show the F2 spread
  against the true optimum, not just against each other.

## TRACTABILITY (why this runs where enumeration cannot)
- Multi-commodity flow LP is polynomial; ILP (integral paths) is NP-hard but solvable for 306 flows /
  60 pairs / per-snapshot with a good solver (CBC/HiGHS/Gurobi) using column generation or the LP
  relaxation + rounding. Start with LP relaxation (gives a valid LOWER BOUND on reservoir = still a
  rigorous optimality witness: if DFE matches the LP lower bound, it is provably optimal).
- Per-snapshot decomposition keeps each ILP small; compose over the 200s/1000ms horizon.

## SOLVER CHOICE
- Open-source first: HiGHS (fast LP/MILP, pip installable) or CBC via PuLP. Gurobi if a license is
  available (much faster, academic license likely). Script supports HiGHS/CBC by default.

## DELIVERABLES TO BUILD
1. ilp_optimality.py — builds the multi-commodity flow model from the SAME DynamicState the harness
   uses (reuse satgenpy snapshots), solves per-snapshot, emits OPT(reservoir, deadline) per snapshot
   + aggregate, and the DFE/faircap/linerate gaps.
2. Dockerfile — reproducible image (python + highs/pulp + satgenpy deps) for AWS.
3. run_ilp.sh — entrypoint: build state, solve, dump optimality_gap.csv.
4. README-ILP.md — how to run locally + on AWS via Claude Code.

## ⚠ DESIGN CHECKS before trusting numbers
- Confirm the ILP objective EXACTLY encodes the paper's two objectives (lexicographic timeliness ≻
  reservoir). If the paper's primary is reservoir-min subject to deadlines, lexicographic is right.
- Confirm the reservoir definition in the ILP == Lemma 1's surplus (kℓ−1)·Cℓ·|W|.
- LP relaxation gives a LOWER BOUND on min-reservoir -> matching it is a SOUND optimality proof.
  Integral ILP gives the exact optimum -> use if tractable, else LP bound suffices for the claim.
- Per-flow rate model must match the harness (constant-rate, rate-matched to bottleneck).
