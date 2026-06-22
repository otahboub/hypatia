#!/usr/bin/env python3
"""
grid_sweep.py — run the full H1×H2×F2 policy grid over the rich precomputed paths, collecting
each configuration's per-flow reservoir (peak kₗ) and deadline outcome. When the ILP optimum is
available, each config's gap-to-optimum is just (reservoir(config) − OPT)/OPT.

This produces the PAPER'S CENTERPIECE TABLE: literature methods as rows, gap-to-optimum as the
column, DFE at ≈0, the others trailing — every method an instance of the CRP grid, every gap
measured against the same ILP yardstick.

Reuses eval_rich_eap's machinery (rich path set, src_load/per-link accounting) but sweeps the
policy knobs instead of evaluating one config.

The named configs (each a literature method = a CRP instance):
  Classic IP    = H1 fifo  + H2 shortest + F2 linerate
  EDF-shortest  = H1 edf   + H2 shortest + F2 ehat
  Load-balanced = H1 lweef + H2 loadbal  + F2 ehat
  Fair-share    = H1 lweef + H2 eap      + F2 faircap
  DFE           = H1 lweef + H2 eap      + F2 ehat
  Widest-ehat   = H1 lweef + H2 widest   + F2 ehat   (optional)
"""
import os, sys, json, csv, math
from collections import defaultdict
INF = float("inf")

PATHS_DIR = os.environ.get("PATHS_OUT", "precomputed_paths")

# Named literature configs (H1 task-order, H2 route-rule, F2 rate-rule)
GRID = {
    "ClassicIP":    dict(h1="fifo",  h2="shortest", f2="linerate"),
    "EDF-shortest": dict(h1="edf",   h2="shortest", f2="ehat"),
    "LoadBalanced": dict(h1="lweef", h2="loadbal",  f2="ehat"),
    "FairShare":    dict(h1="lweef", h2="eap",      f2="faircap"),
    "DFE":          dict(h1="lweef", h2="eap",      f2="ehat"),
    "Widest-ehat":  dict(h1="lweef", h2="widest",   f2="ehat"),
}


def load_paths(src, dst):
    fn = os.path.join(PATHS_DIR, f"{src}_{dst}.json")
    if not os.path.exists(fn): return []
    return json.load(open(fn)).get("paths", [])


def _delay(state, a, b, t):
    try: return state.delay_s(a, b, t)
    except TypeError: return state.delay_s(a, b)


def _walk(state, path, w, load, src_load, t0, util):
    """Return (completion, ehat, first_share, line_rate, per_hop[(a,b,n,cap,share)])."""
    t = t0; ehat = INF; first_share = INF; line_rate = INF; hops = []
    for i, (a, b) in enumerate(zip(path[:-1], path[1:])):
        t = max(t, state.next_available(a, b, t)); t += _delay(state, a, b, t)
        n = max((src_load.get(a, 0) if i == 0 else load.get((a, b), 0)) + 1, 1)
        cap = state.capacity_bps(a, b, t)
        share = util * cap / n
        ehat = min(ehat, share)
        if i == 0: first_share = share; line_rate = cap
        hops.append((a, b, n, cap, share))
    if ehat <= 0: return INF, 0.0, first_share, line_rate, hops
    tx = (w["size_bytes"] * 8.0) / ehat
    return t + tx, ehat, first_share, line_rate, hops


def _rate_for(f2, ehat, first_share, line_rate):
    return {"ehat": ehat, "faircap": first_share, "linerate": line_rate}[f2]


def run_config(state, flows, cfg, t0=0.0, util=0.9):
    """Run one H1/H2/F2 config; return (per-flow rows, link_load_bps dict).
    link_load_bps[(a,b)] = Σ committed rate (bps) of flows using that link, where the rate is the
    config's F2 rate rule. This makes the reservoir computable in the SAME bps units as the LP OPT:
        R_policy = Σ_links max(0, load_bps − cap_bps).
    """
    load = defaultdict(int); src_load = defaultdict(int)
    link_load_bps = defaultdict(float)        # (a,b) -> sum of COMMIT-TIME flow rates in bps (greedy)
    link_cap_bps = {}                          # (a,b) -> capacity bps (for the reservoir formula)
    committed = []                             # (path, [(a,b,cap)]) per flow, for the RE-RATED pass
    h1, h2, f2 = cfg["h1"], cfg["h2"], cfg["f2"]

    # H1: order flows
    def first_path_comp(w):
        ps = load_paths(w["src"], w["dst"])
        if not ps: return INF
        c, *_ = _walk(state, ps[0], w, load, src_load, t0, util)
        return c
    if h1 == "fifo":
        order = sorted(flows, key=lambda w: (w.get("release_s", 0), w["id"]))
    elif h1 == "edf":
        order = sorted(flows, key=lambda w: w["deadline_s"])
    else:  # lweef: least earliness (deadline - completion) first
        order = sorted(flows, key=lambda w: w["deadline_s"] - first_path_comp(w))

    rows = []
    for w in order:
        ps = load_paths(w["src"], w["dst"])
        if not ps: continue
        # evaluate candidates
        cand = []
        for p in ps:
            comp, ehat, fs, lr, hops = _walk(state, p, w, load, src_load, t0, util)
            if ehat <= 0 or comp == INF: continue
            cand.append((p, comp, ehat, fs, lr, hops))
        if not cand: continue
        # feasibility filter (deadline)
        feas = [c for c in cand if c[1] <= w["deadline_s"]] or cand
        # H2: select route
        if h2 == "eap":
            best = min(feas, key=lambda c: c[1])
        elif h2 == "shortest":
            best = min(feas, key=lambda c: (len(c[0]) - 1, c[1]))
        elif h2 == "loadbal":
            best = min(feas, key=lambda c: max((load.get((a, b), 0) + 1
                        for a, b in zip(c[0][:-1], c[0][1:])), default=0))
        elif h2 == "widest":
            best = max(feas, key=lambda c: c[2])   # max ehat = widest bottleneck
        else:
            best = min(feas, key=lambda c: c[1])
        path, comp, ehat, fs, lr, hops = best
        # commit
        for a, b in zip(path[:-1], path[1:]): load[(a, b)] += 1
        src_load[path[0]] += 1
        committed.append((path, [(a, b, cap) for (a, b, n, cap, share) in hops]))
        # F2 rate + peak kₗ for THIS config's rate rule
        rate = _rate_for(f2, ehat, fs, lr)
        # accumulate per-link bps load (this flow's committed rate flows on every hop of its path)
        for (a, b, n, cap, share) in hops:
            link_load_bps[(a, b)] += rate
            link_cap_bps[(a, b)] = cap
        peak_kl = 0.0
        for (a, b, n, cap, share) in hops:
            if share > 0:
                peak_kl = max(peak_kl, rate / share)
        rows.append(dict(flow_id=w["id"], config=None, hops=len(path) - 1,
                         rate_bps=round(rate, 2), peak_kl=round(peak_kl, 4),
                         met=(1 if comp <= w["deadline_s"] else 0),
                         oversub=(1 if peak_kl > 1.0 else 0)))

    # --- RE-RATED pass (the DFE model): re-rate each flow to FINAL per-link load, then
    #     reservoir = Σ_links max(0, load_bps − cap). êₕ uses the windowed bottleneck effective
    #     bandwidth = min_path util·cap/n_final; faircap = first-hop final share; linerate = line rate.
    #     HARD CHECK: any êₕ config MUST give 0 congested links here (Σ êₕ ≤ util·cap < cap per link).
    # Count flows per PHYSICAL link (final). The reservoir is per-link, so the fair
    # share must use the per-link flow count n_link[ℓ] for EVERY hop — including the
    # first. (Using the GS-transmitter count src_load[a] for first hops over-allocates
    # when a GS link also appears as a transit hop in some candidate path, breaking
    # Σ êₕ ≤ util·cap. Per-link counts make the invariant hold by construction.)
    n_link = defaultdict(int)
    for (path, hopcaps) in committed:
        for (a, b, cap) in hopcaps:
            n_link[(a, b)] += 1
    link_load_rerated = defaultdict(float)
    for (path, hopcaps) in committed:
        shares = []
        for (a, b, cap) in hopcaps:
            nf = max(n_link[(a, b)], 1)
            shares.append((a, b, cap, util * cap / nf))
        if f2 == "ehat":
            rr = min(s for *_, s in shares)
        elif f2 == "faircap":
            rr = shares[0][3]            # first-hop final per-link fair share
        else:                            # linerate (load-independent line rate)
            rr = shares[0][2]
        for (a, b, cap, s) in shares:
            link_load_rerated[(a, b)] += rr
            link_cap_bps[(a, b)] = cap
    return rows, link_load_bps, link_cap_bps, link_load_rerated


def main(state, flows, out_dir=".", t0=0.0, util=0.9, opt_reservoir=None):
    import statistics as st
    summary = []
    for name, cfg in GRID.items():
        rows, link_load_commit, link_cap_bps, link_load_rerated = run_config(state, flows, cfg, t0, util)
        for r in rows: r["config"] = name
        n = len(rows)
        if not n: continue
        kls = [r["peak_kl"] for r in rows]
        def _resv(load_map):
            r = sum(max(0.0, load_map[e] - link_cap_bps.get(e, 0.0)) for e in load_map)
            c = sum(1 for e in load_map if load_map[e] > link_cap_bps.get(e, 0.0) + 1e-6)
            return r, c
        # RE-RATED = DFE's actual reservoir (final-load êₕ); COMMIT = greedy ablation (see §5.5)
        reservoir_rerated, congested_rerated = _resv(link_load_rerated)
        reservoir_commit,  congested_commit  = _resv(link_load_commit)
        reservoir_proxy = sum(max(0.0, r["peak_kl"] - 1.0) for r in rows)  # commit-time kₗ surplus
        # HARD CHECK: any êₕ config MUST attain 0 congested links under re-rating.
        if cfg["f2"] == "ehat" and congested_rerated > 0:
            print(f"  [HARD-CHECK FAIL] {name}: êₕ config shows {congested_rerated} congested links "
                  f"under re-rating (expected 0) — n_final bookkeeping inconsistent.")
        summ = dict(config=name, h1=cfg["h1"], h2=cfg["h2"], f2=cfg["f2"],
                    flows=n, wce=round(sum(r["met"] for r in rows)/n, 4),
                    median_kl=round(st.median(kls), 3), max_kl=round(max(kls), 3),
                    oversub=sum(r["oversub"] for r in rows),
                    reservoir_bps_rerated=round(reservoir_rerated, 1),
                    congested_rerated=congested_rerated,
                    reservoir_bps_commit=round(reservoir_commit, 1),
                    congested_commit=congested_commit,
                    reservoir_proxy=round(reservoir_proxy, 3))
        # gap vs OPT on the RE-RATED reservoir (DFE's model), same bps units as the LP OPT.
        if opt_reservoir is not None:
            if opt_reservoir > 0:
                summ["gap_to_opt"] = round((reservoir_rerated - opt_reservoir) / opt_reservoir, 4)
            else:
                summ["gap_to_opt"] = ("attains" if reservoir_rerated <= 1e-6
                                      else f"+{reservoir_rerated:.3e}bps_above_zero_OPT")
        summary.append(summ)
        with open(os.path.join(out_dir, f"grid_{name}.csv"), "w", newline="") as f:
            wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys())); wtr.writeheader(); wtr.writerows(rows)
    if summary:
        with open(os.path.join(out_dir, "grid_summary.csv"), "w", newline="") as f:
            wtr = csv.DictWriter(f, fieldnames=list(summary[0].keys())); wtr.writeheader(); wtr.writerows(summary)
        print("\n=== GRID SUMMARY (centerpiece) ===")
        for s in summary:
            line = (f"  {s['config']:13s} H1={s['h1']:6s} H2={s['h2']:9s} F2={s['f2']:9s} "
                    f"| WCE {s['wce']:.3f} maxKl {s['max_kl']:7.2f} "
                    f"| RERATED {s['reservoir_bps_rerated']:.3e}bps cong {s['congested_rerated']:4d} "
                    f"| commit_ablation {s['reservoir_bps_commit']:.3e}bps cong {s['congested_commit']:4d}")
            if 'gap_to_opt' in s: line += f" | gap_rerated {s['gap_to_opt']}"
            print(line)
    return summary


if __name__ == "__main__":
    print("Import main(state, flows, ...) from the harness driver. See run_grid_mac.py.")