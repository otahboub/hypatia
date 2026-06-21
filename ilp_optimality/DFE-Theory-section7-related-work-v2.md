# §7  Related Work
*(Draft v2 — rebuilt around the CRP-as-solver-framework framing and the tripartite taxonomy.
Positions DFE against the five contemporary planner families. ⚠ = cite to verify.)*

Flow-aware time-sensitive networking poses a joint routing-and-rate-assignment problem: choose, for
each deadline-bearing flow, a path and a committed rate that meet timeliness while conserving the
transit reservoir. The contemporary literature attacks this with five method families. We position
DFE not as a sixth competitor but as an instance of a *unifying solver framework* — CRP — and state
precisely how that framework relates to each family.

## 7.1  CRP as a constructive solver framework

CRP (Constraint Resource Planning), in the lineage of Yun and colleagues, is a constructive,
staged, constraint-propagation solver: it builds a schedule incrementally, committing one flow at a
time across four stages — task selection (H1), candidate-route exploration (F1), route choice (H2),
and rate commitment with constraint propagation (F2) — each commit narrowing the residual feasibility
for the flows that follow. Crucially, CRP is not a single algorithm but a *parameterized family* of
solvers: each configuration of the four stages instantiates a distinct, complete planner. This is the
organizing observation of our evaluation and of this section — the contemporary heuristic planners are
recovered as particular CRP configurations, and DFE is the configuration whose rate stage yields the
reservoir bound kₗ ≤ 1 by construction.

CRP is thus a solver in the full sense — it maps a problem instance (topology, flows, deadlines) to a
feasible schedule. Its only boundary against the exact line is architectural, not a deficiency: CRP is
*not a monolithic global optimizer* that solves one simultaneous optimization over all flows at once;
it constructs a solution by forward constraint propagation, flow by flow. That constructive/staged
character — as opposed to monolithic/simultaneous — is precisely the source of its scalability, and our
optimality claim (M, below) is that this constructive procedure nonetheless *reaches* the optimum a
monolithic optimizer would compute, on the instances we verify.

We make three precise claims about CRP's relationship to the literature, which we label E/M/C:
CRP **instantiates** the staged-heuristic family as configurations (E); it **attains the optimum**
that monolithic exact solvers compute, at scales where those solvers do not terminate (M); and it
**certifies guarantees** that metaheuristic and learned planners structurally cannot (C).

## 7.2  Exact solvers — ILP/MILP and SMT  (relationship: M)

The exact line formulates routing and scheduling as a constraint system handed to a general solver.
ILP/MILP approaches [Atallah, Hamad, and Mohamed, 2020 ⚠; large-scale periodic scheduling 2022 ⚠]
and SMT-based schedule synthesis for 802.1Qbv [Craciunas and Oliver et al. ⚠] obtain globally optimal
configurations but are repeatedly reported to scale poorly; the runtime of the general solver becomes
prohibitive as flow and link counts grow, which is the stated motivation for much of the heuristic and
learning literature. We do not claim CRP emulates these solvers — it does not execute their
simultaneous global optimization. We claim the stronger and verifiable property that CRP-DFE's
constructive procedure *attains the optimum they would compute*: against a multi-commodity LP whose
relaxation is a rigorous lower bound on the minimum reservoir, DFE matches the bound at constellation
scale (§6/§ILP), where the exact solver does not terminate. Because the LP bound is solver-agnostic,
matching it matches what any exact method — ILP, MILP, or SMT — could achieve. One optimality witness
covers the family.

## 7.3  Constraint programming  (relationship: M, and kindred)

CP formulations using disjunctive or optional-interval models, often with logic-based Benders
decomposition [dos Santos, Schneider, and Tang, 2021 ⚠; Reusch, Pop, and Craciunas, 2020 ⚠], improve
on SMT/ILP for some instances but remain solver-bound. CP is the one family with which CRP shares an
intellectual lineage: both rest on constraint propagation. We frame the relationship as both shared
provenance and matched optimum — CRP belongs to the same constraint-resource tradition (a strength,
not a dilution), and CRP-DFE attains the CP optimum — while differing in architecture: CRP is a
domain-tailored four-stage constructive engine, not a general disjunctive solver invoked as a black box.

## 7.4  Heuristics — list scheduling, shortest-path routing, EDF/ASAP, load balancing  (relationship: E)

The deployable mainstream is a family of fast, greedy, per-flow rules: list scheduling [Pahlevan,
Tabassam, and Obermaisser, 2019 ⚠], routing for 802.1Qbv and incremental TS-SDN scheduling [Nayak,
Dürr, and Rothermel, 2018 ⚠], and load-balanced transmission [Ojewale and Yomsi, 2020 ⚠], over the
standard shortest-path routing default. This is exactly the family CRP instantiates. Task-ordering
rules (FCFS, EDF, least-earliness) are H1 settings; routing rules (shortest-path, earliest-arrival,
least-loaded, widest) are H2 settings; rate rules (line rate, first-hop fair share, route-bottleneck
êₕ) are F2 settings. Classic IP forwarding is the configuration (FCFS, shortest-path, line rate);
EDF-shortest is (EDF, shortest-path, êₕ); load-balanced routing is (least-earliness, least-loaded,
êₕ); and DFE is (least-earliness, earliest-arrival, êₕ). Each literature heuristic is therefore not
approximated but *recovered exactly* as a cell of the CRP grid, and our evaluation scores the whole
grid against the same optimality yardstick (§6): every method a row, its distance from the optimum a
column. This is what licenses the framework claim — the heuristics are instances, and DFE is the
instance that attains the reservoir optimum.

## 7.5  Metaheuristics and learning-based planners  (relationship: C)

Evolutionary and differential-evolution methods [Wang et al., 2025 ⚠] search the routing-and-schedule
space stochastically; learning-based methods using graph convolutional networks with deep
reinforcement learning [Yang, Wei, Yu, and Han, 2022 ⚠; and subsequent GCN-DRL work ⚠] learn a policy
from interaction. Both adapt well but offer no hard guarantee — metaheuristics approximate the optimum
without certifying it; learned policies cannot certify the reservoir bound. CRP-DFE is the verifiable
counterpart: êₕ gives kₗ ≤ 1 by construction, and the optimality experiment establishes that the
constructive schedule reaches the global optimum a stochastic or learned search could only approach.
Against this family CRP-DFE serves as the certified baseline any heuristic or learned planner would
have to beat — and, being optimal where checkable, cannot be beaten on the reservoir objective.

## 7.6  A structural connection: broadcast interconnects and path enumeration (OTIS-EDN)

The enumeration of a complete candidate-path set per source–destination pair — the mechanism behind
the small-network global-optimality result that motivates DFE's heuristics — is naturally realized by
flooding over a broadcast interconnection substrate. OTIS-EDN [Mahafzah, Tahboub, and Tahboub, 2008 ⚠
exact venue], an OTIS-class broadcast/interconnection network, is one such substrate, and the
path-enumeration view connects DFE's route-exploration stage (F1) to that interconnect literature. We
import this only as structural lineage and as the enumeration method behind the optimality tier, not
as a transfer of OTIS's regular topology to the constellation setting.

## 7.7  Summary: the tripartite position

DFE is the rate-stage instance of a unifying constructive solver framework. The exact and CP families
(M) give the optimum but do not scale; CRP-DFE attains their optimum where they cannot run. The
heuristic family (E) scales but offers no guarantee; CRP-DFE *contains* it as configurations and
identifies the optimal one. The metaheuristic and learned families (C) adapt but cannot certify;
CRP-DFE provides the construction-guaranteed, optimality-checked baseline. The contribution is thus
not a better point in the design space but a characterization of the space and the location of its
optimum within it.

---
## ⚠ CITES TO VERIFY (full list in DFE-contemporary-planners-CRP-coverage.md)
Atallah/Hamad/Mohamed TII 2020; periodic-scheduling Comp&OR 2022; Craciunas & Oliver SMT;
dos Santos/Schneider/Tang Comp&IndEng 2021; Reusch/Pop/Craciunas RTSS 2020; Pahlevan et al. SIGBED
2019; Nayak/Dürr/Rothermel SIGBED 2018 + TII 2018; Ojewale/Yomsi SIGBED 2020; Wang et al.
Biomimetics 2025; Yang/Wei/Yu/Han IoT-J 2022; Stüber et al. IEEE Access 2023 (survey);
Mahafzah/Tahboub/Tahboub 2008 (OTIS-EDN, exact venue/pages).
