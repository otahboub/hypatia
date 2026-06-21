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
    """Run one H1/H2/F2 config; return per-flow rows with peak kₗ for the F2 rate rule."""
    load = defaultdict(int); src_load = defaultdict(int)
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
        # F2 rate + peak kₗ for THIS config's rate rule
        rate = _rate_for(f2, ehat, fs, lr)
        peak_kl = 0.0
        for (a, b, n, cap, share) in hops:
            if share > 0:
                peak_kl = max(peak_kl, rate / share)
        rows.append(dict(flow_id=w["id"], config=None, hops=len(path) - 1,
                         rate_bps=round(rate, 2), peak_kl=round(peak_kl, 4),
                         met=(1 if comp <= w["deadline_s"] else 0),
                         oversub=(1 if peak_kl > 1.0 else 0)))
    return rows


def main(state, flows, out_dir=".", t0=0.0, util=0.9, opt_reservoir=None):
    import statistics as st
    summary = []
    for name, cfg in GRID.items():
        rows = run_config(state, flows, cfg, t0, util)
        for r in rows: r["config"] = name
        n = len(rows)
        if not n: continue
        kls = [r["peak_kl"] for r in rows]
        reservoir = sum(max(0.0, r["peak_kl"] - 1.0) for r in rows)  # proxy surplus
        summ = dict(config=name, h1=cfg["h1"], h2=cfg["h2"], f2=cfg["f2"],
                    flows=n, wce=round(sum(r["met"] for r in rows)/n, 4),
                    median_kl=round(st.median(kls), 3), max_kl=round(max(kls), 3),
                    oversub=sum(r["oversub"] for r in rows),
                    reservoir_proxy=round(reservoir, 3))
        if opt_reservoir not in (None, 0):
            summ["gap_to_opt"] = round((reservoir - opt_reservoir)/opt_reservoir, 4)
        summary.append(summ)
        # per-config detail
        with open(os.path.join(out_dir, f"grid_{name}.csv"), "w", newline="") as f:
            wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys())); wtr.writeheader(); wtr.writerows(rows)
    # centerpiece summary
    if summary:
        with open(os.path.join(out_dir, "grid_summary.csv"), "w", newline="") as f:
            wtr = csv.DictWriter(f, fieldnames=list(summary[0].keys())); wtr.writeheader(); wtr.writerows(summary)
        print("\n=== GRID SUMMARY (centerpiece) ===")
        for s in summary:
            print(f"  {s['config']:13s} H1={s['h1']:6s} H2={s['h2']:9s} F2={s['f2']:9s} "
                  f"| WCE {s['wce']:.3f} medKl {s['median_kl']:6.2f} maxKl {s['max_kl']:7.2f} "
                  f"oversub {s['oversub']:4d}"
                  + (f" gap {s.get('gap_to_opt')}" if 'gap_to_opt' in s else ""))
    return summary


if __name__ == "__main__":
    print("Import main(state, flows, ...) from the harness driver. See run_grid_mac.py.")
