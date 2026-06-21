#!/usr/bin/env python3
"""
h2_route_select.py — the DFE_H2 route-selection knob, as a standalone tested module.

This generalizes crp_dfe._eap() into a mode-switched route selector so every taxonomy E-cell
becomes a runnable configuration:
  DFE_H2=eap        earliest-arrival path        (current DFE/EDF behavior)
  DFE_H2=shortest   fewest-hops then least-delay  (Classic IP routing)
  DFE_H2=loadbal    minimize peak per-link load   (load-balanced routing, Ojewale & Yomsi)
  DFE_H2=widest     maximize bottleneck share     (widest-path)

All modes select over the SAME F1 candidate set and apply the SAME deadline-feasibility filter,
so the comparison across H2 modes is clean. Default = eap (no regression).

Designed to slot into crp_dfe.py: replace the body of _eap() with a call to select_route(...),
or paste select_route as a method. Pure functions here for testability.
"""
import os
INF = float("inf")


def _path_delay(state, path, t0):
    t = t0
    for a, b in zip(path[:-1], path[1:]):
        try: d = state.delay_s(a, b, t)
        except TypeError: d = state.delay_s(a, b)
        t = state.next_available(a, b, t) + d
    return t - t0


def _peak_link_load(path, load):
    """Max over hops of the per-link flow count (after this flow would be added)."""
    return max((load.get((a, b), 0) + 1 for a, b in zip(path[:-1], path[1:])), default=0)


def _bottleneck_share(state, path, load, t0, util=0.9):
    """Min over hops of util*cap/n — the route bottleneck fair-share (higher is wider)."""
    t = t0; bn = INF
    for a, b in zip(path[:-1], path[1:]):
        try: d = state.delay_s(a, b, t)
        except TypeError: d = state.delay_s(a, b)
        t = state.next_available(a, b, t) + d
        n = max(load.get((a, b), 0) + 1, 1)
        bn = min(bn, util * state.capacity_bps(a, b, t) / n)
    return bn


def select_route(routes, state, load, deadline_s, completion_fn, t0=0.0,
                 mode=None, util=0.9):
    """
    routes        : list of (path, ehat) candidates from F1
    completion_fn : fn(path, ehat) -> completion_s  (the planner's _completion)
    Returns (path, completion_s, ehat) for the chosen feasible route, or None.

    The deadline-feasibility filter is applied IDENTICALLY across modes; only the
    selection KEY differs. This keeps the H2 ablation clean.
    """
    if mode is None:
        mode = os.environ.get("DFE_H2", "eap").lower()

    # feasible = routes whose completion meets the deadline
    feas = []
    for path, ehat in routes:
        comp = completion_fn(path, ehat)
        if comp <= deadline_s:
            feas.append((path, comp, ehat))
    if not feas:
        return None

    if mode == "eap":
        key = lambda r: r[1]                                   # earliest completion
    elif mode == "shortest":
        key = lambda r: (len(r[0]) - 1, _path_delay(state, r[0], t0))  # fewest hops, then delay
    elif mode == "loadbal":
        key = lambda r: _peak_link_load(r[0], load)           # least peak load
    elif mode == "widest":
        key = lambda r: -_bottleneck_share(state, r[0], load, t0, util)  # max bottleneck share
    else:
        key = lambda r: r[1]                                  # default eap

    best = min(feas, key=key)
    return best  # (path, completion_s, ehat)


# ---------------------------------------------------------------------------
def _selftest():
    # diamond: 0->3 via 1 (2 hops, tight 40Mb/s on 1->3) or via 2 (2 hops, 100Mb/s),
    # or long way 0->1->... make a 3-hop wide alternative to test 'shortest' vs 'widest'
    class S:
        adj={0:[1,2],1:[3],2:[3,4],4:[3]}
        def neighbors(self,u): return self.adj.get(u,[])
        def next_available(self,u,v,t): return t
        def delay_s(self,u,v,t=0): return 0.01
        def capacity_bps(self,u,v,t):
            return {(1,3):40e6,(0,1):100e6,(0,2):100e6,(2,3):100e6,(2,4):100e6,(4,3):100e6}.get((u,v),100e6)
    st=S()
    # candidate paths (path, ehat-ish placeholder; completion_fn recomputes)
    routes=[([0,1,3],0),([0,2,3],0),([0,2,4,3],0)]
    load={}
    # completion_fn: longer/tighter paths complete later; approximate by delay + size/bottleneck
    def comp(path,ehat):
        d=_path_delay(st,path,0.0); bn=_bottleneck_share(st,path,load,0.0)
        return d + (10e6*8.0)/bn   # 10 Mb flow
    for m in ["eap","shortest","loadbal","widest"]:
        r=select_route(routes, st, load, deadline_s=10.0, completion_fn=comp, mode=m)
        print(f"  DFE_H2={m:9s} -> path {r[0]}  (hops={len(r[0])-1}, comp={r[1]:.3f}s)")
    print("expected: shortest picks a 2-hop; widest avoids the 40Mb/s (1,3) link; loadbal balanced")


if __name__ == "__main__":
    _selftest()
