"""Seed script generating a realistic scholarly PDF (with equations and vector subproblem DAG)
and populating a rich Scholia demo vault for testing and visual evaluation."""

from __future__ import annotations

import argparse
import math
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from scholia.config import StageRoute, load_config, save_config
from scholia.db import VaultDB
from scholia.services.ingestion import IngestionService
from scholia.services.vault import VaultFS


def _draw_header_footer(page: fitz.Page, running_head: str, page_num: int) -> None:
    rect = page.rect
    ink_muted = (0.38, 0.36, 0.33)
    rule_col = (0.82, 0.80, 0.75)
    page.insert_text((54, 42), running_head.upper(), fontsize=8.2, fontname="helv", color=ink_muted)
    page.draw_line((54, 48), (rect.width - 54, 48), color=rule_col, width=0.6)
    page.draw_line((54, rect.height - 48), (rect.width - 54, rect.height - 48), color=rule_col, width=0.6)
    page.insert_text((rect.width - 80, rect.height - 34), f"p. {page_num}", fontsize=8.5, fontname="cour", color=ink_muted)


def generate_algorithms_sample_pdf() -> bytes:
    """Build a crisp 10-page monograph PDF with embedded TOC, equations, pricing table, and vector DAG figure."""
    doc = fitz.open()
    bg_paper = (0.99, 0.985, 0.97)
    ink = (0.11, 0.10, 0.09)
    prussian = (0.114, 0.306, 0.408)
    forest = (0.169, 0.416, 0.302)
    ochre = (0.604, 0.357, 0.075)
    panel = (0.945, 0.935, 0.91)
    border = (0.78, 0.75, 0.69)

    def new_page(running_head: str, pno: int) -> fitz.Page:
        p = doc.new_page(width=612, height=792)
        p.draw_rect(p.rect, fill=bg_paper, color=None)
        if pno > 1:
            _draw_header_footer(p, running_head, pno)
        return p

    # Page 1: Title & Overview (Chapter 1 starts p. 1, Chapter 2 starts p. 4, Chapter 3 starts p. 8)
    p1 = new_page("", 1)
    p1.insert_text((54, 130), "MONOGRAPH IN ALGORITHMIC DESIGN", fontsize=9.5, fontname="helv", color=prussian)
    p1.insert_text((54, 172), "Decomposition, Recurrence,", fontsize=26, fontname="tiro", color=ink)
    p1.insert_text((54, 204), "and Optimal Substructure", fontsize=26, fontname="tiro", color=ink)
    p1.insert_text((54, 236), "Selected Chapters on Divide-and-Conquer, Dynamic Programming, and Greedy Matroids", fontsize=11.5, fontname="tiit", color=(0.35, 0.33, 0.30))
    p1.draw_line((54, 256), (260, 256), color=prussian, width=1.4)
    p1.insert_text((54, 290), "Chapter 1   Divide-and-Conquer and Recurrence Trees ......................... p. 1", fontsize=10.5, fontname="tiro", color=ink)
    p1.insert_text((54, 312), "Chapter 2   Dynamic Programming and Subproblem DAGs ................... p. 4", fontsize=10.5, fontname="tiro", color=ink)
    p1.insert_text((54, 334), "Chapter 3   Greedy Choice Property and Exchange Arguments ............. p. 8", fontsize=10.5, fontname="tiro", color=ink)
    p1.insert_textbox(
        fitz.Rect(54, 385, 558, 650),
        (
            "Chapter 1. Divide-and-Conquer and Recurrence Trees\n\n"
            "Divide-and-conquer partitions an instance of size n into disjoint subproblems, solves each subproblem recursively, "
            "and combines the resulting solutions in time f(n). When the subproblems are strictly independent, recursion trees "
            "capture total work cleanly through the Master Theorem:\n\n"
            "    T(n) = a T(n / b) + f(n),   with a >= 1 and b > 1.\n\n"
            "The critical exponent c_crit = log_b(a) determines whether total cost concentrates at the leaves, balances evenly across "
            "all log_b(n) levels, or concentrates at the root merge step. Crucially, independence implies that no two branches share "
            "identical subproblem instances; once subproblems overlap, naive recursion repeats identical work exponentially."
        ),
        fontsize=11,
        fontname="tiro",
        color=ink,
        lineheight=1.45,
    )

    # Pages 2-3: Chapter 1 continuation
    for idx, heading in enumerate(["1.2 Recurrence Tree Accounting", "1.3 When Disjoint Decomposition Breaks"], start=2):
        p = new_page("Chapter 1 · Divide-and-Conquer", idx)
        p.insert_text((54, 82), heading, fontsize=15, fontname="tibo", color=ink)
        p.insert_textbox(
            fitz.Rect(54, 104, 558, 690),
            (
                "Each internal node at depth k represents a subproblem of size n / b^k with local combine cost f(n / b^k). "
                "Summing across all a^k nodes at depth k yields the level work L(k) = a^k f(n / b^k). "
                "When merge work grows linearly as in merge sort (a = 2, b = 2, f(n) = Theta(n)), every level contributes Theta(n) work "
                "across log_2(n) levels for a total bound of Theta(n log n).\n\n"
                "However, recursive definitions whose subproblems overlap—such as the rod-cutting revenue recurrence or shortest paths "
                "in layered graphs—violate the disjointness premise. Their recursion trees contain exponentially many copies of only "
                "polynomially many distinct subproblem states. Chapter 2 replaces the tree with a directed acyclic graph (DAG) of unique states."
            ),
            fontsize=11,
            fontname="tiro",
            color=ink,
            lineheight=1.5,
        )

    # Page 4: Chapter 2 start — Dynamic Programming & Rod Cutting + Equation Box + Pricing Table
    p4 = new_page("Chapter 2 · Dynamic Programming", 4)
    p4.insert_text((54, 78), "CHAPTER 2", fontsize=9.5, fontname="helv", color=prussian)
    p4.insert_text((54, 106), "Dynamic Programming and Subproblem DAGs", fontsize=19, fontname="tibo", color=ink)
    p4.insert_textbox(
        fitz.Rect(54, 126, 558, 250),
        (
            "Dynamic programming applies when an optimization problem exhibits two structural properties simultaneously: "
            "optimal substructure and overlapping subproblems. Optimal substructure means an optimal global solution contains "
            "within it optimal solutions to its component subproblems, verifiable by a cut-and-paste contradiction. "
            "Overlapping subproblems mean a recursive decomposition revisits the same small set of states repeatedly rather than generating fresh subproblems."
        ),
        fontsize=10.8,
        fontname="tiro",
        color=ink,
        lineheight=1.45,
    )

    # Equation callout box
    eq_rect = fitz.Rect(54, 246, 558, 326)
    p4.draw_rect(eq_rect, fill=panel, color=border, width=0.8)
    p4.draw_line((54, 246), (54, 326), color=prussian, width=2.8)
    p4.insert_text((68, 266), "EQUATION 2.1 — ROD-CUTTING BELLMAN RECURRENCE", fontsize=8.2, fontname="helv", color=prussian)
    p4.insert_text((68, 292), "r_n  =  max_{1 <= i <= n} ( p_i  +  r_{n - i} ),     with base case  r_0 = 0", fontsize=12.5, fontname="cour", color=ink)
    p4.insert_text((68, 314), "First cut of length i is fixed without further cutting; remainder n - i resolves optimally.", fontsize=9.5, fontname="tiit", color=(0.35, 0.33, 0.30))

    # Rod-cutting pricing table
    p4.insert_text((54, 356), "Table 2.1 — Standard Rod-Cutting Price Schedule and Optimal Revenue r_n", fontsize=10.2, fontname="tibo", color=ink)
    table_top = 368
    col_w = 54
    headers = ["length i", "1", "2", "3", "4", "5", "6", "7", "8"]
    prices = ["price p_i", "1", "5", "8", "9", "10", "17", "17", "20"]
    revs = ["opt r_i", "1", "5", "8", "10", "13", "17", "18", "22"]
    cuts = ["first cut", "1", "2", "3", "2", "2", "6", "1", "2"]
    rows = [headers, prices, revs, cuts]
    for r_idx, row_vals in enumerate(rows):
        y0 = table_top + r_idx * 24
        y1 = y0 + 24
        if r_idx == 0:
            p4.draw_rect(fitz.Rect(54, y0, 54 + 9 * col_w, y1), fill=panel, color=border, width=0.6)
        else:
            p4.draw_line((54, y1), (54 + 9 * col_w, y1), color=border, width=0.5)
        for c_idx, val in enumerate(row_vals):
            x = 60 + c_idx * col_w
            font = "helv" if r_idx == 0 or c_idx == 0 else "cour"
            col = prussian if r_idx == 2 and c_idx > 0 else ink
            p4.insert_text((x, y0 + 16), val, fontsize=9.5, fontname=font, color=col)

    p4.insert_textbox(
        fitz.Rect(54, 482, 558, 710),
        (
            "Observe length n = 4 in Table 2.1. A greedy density rule picks length 3 (unit value 2.67, price 8) plus remainder 1 "
            "(price 1) for revenue 9. Dynamic programming evaluates all first cuts i in {1, 2, 3, 4} and finds i = 2 yields "
            "p_2 + r_2 = 5 + 5 = 10. Naive top-down recursion without caching evaluates 2^{n-1} cut combinations because r_2 "
            "and r_1 are recomputed along every branch. Memoizing each distinct state r_0, ..., r_n collapses runtime from "
            "Theta(2^n) to Theta(n^2): there are n + 1 distinct subproblems and each performs O(n) transition work."
        ),
        fontsize=10.8,
        fontname="tiro",
        color=ink,
        lineheight=1.5,
    )

    # Page 5: Vector Figure 2.1 — Exponential Recursion Tree vs. Collapsed Subproblem DAG
    p5 = new_page("Chapter 2 · Dynamic Programming", 5)
    p5.insert_text((54, 78), "2.2 Subproblem Graphs and Topological Evaluation Order", fontsize=14.5, fontname="tibo", color=ink)
    p5.insert_textbox(
        fitz.Rect(54, 98, 558, 170),
        (
            "The runtime of any dynamic program equals the number of vertices |V| in the subproblem DAG plus the sum of "
            "out-degrees |E|, multiplied by constant work per edge. Figure 2.1 contrasts the raw recursion tree for r_4 against "
            "its collapsed subproblem DAG where every distinct subproblem appears exactly once."
        ),
        fontsize=10.8,
        fontname="tiro",
        color=ink,
        lineheight=1.45,
    )

    fig_box = fitz.Rect(54, 178, 558, 466)
    p5.draw_rect(fig_box, fill=(0.985, 0.98, 0.965), color=border, width=0.8)
    p5.insert_text((70, 200), "FIGURE 2.1 — COLLAPSING THE RECURSION TREE INTO A SUBPROBLEM DAG (n = 4)", fontsize=8.5, fontname="helv", color=prussian)

    # Left side: Recursion tree (showing repeated r2, r1, r0 nodes)
    p5.insert_text((74, 224), "A. Naive Recursion Tree (8 leaves, repeated states)", fontsize=9.2, fontname="tiit", color=(0.35, 0.33, 0.30))
    tree_nodes = {
        "r4": (175, 254),
        "r3": (118, 306),
        "r2a": (178, 306),
        "r1a": (232, 306),
        "r2b": (90, 362),
        "r1b": (140, 362),
        "r1c": (184, 362),
        "r0a": (232, 362),
        "r1d": (74, 418),
        "r0b": (114, 418),
    }
    tree_edges = [
        ("r4", "r3"), ("r4", "r2a"), ("r4", "r1a"),
        ("r3", "r2b"), ("r3", "r1b"),
        ("r2a", "r1c"), ("r2a", "r0a"),
        ("r2b", "r1d"), ("r2b", "r0b"),
    ]
    for u, v in tree_edges:
        p5.draw_line(tree_nodes[u], tree_nodes[v], color=(0.62, 0.59, 0.54), width=1.0)
    labels_tree = {
        "r4": "r4", "r3": "r3", "r2a": "r2", "r1a": "r1",
        "r2b": "r2", "r1b": "r1", "r1c": "r1", "r0a": "r0", "r1d": "r1", "r0b": "r0",
    }
    repeated_keys = {"r2a", "r2b", "r1a", "r1b", "r1c", "r1d"}
    for key, (cx, cy) in tree_nodes.items():
        fill_c = (0.98, 0.92, 0.84) if key in repeated_keys else bg_paper
        stroke_c = ochre if key in repeated_keys else ink
        p5.draw_circle((cx, cy), 14, color=stroke_c, fill=fill_c, width=1.1)
        p5.insert_text((cx - 7, cy + 3.5), labels_tree[key], fontsize=9, fontname="cour", color=ink)

    # Divider line
    p5.draw_line((290, 218), (290, 448), color=border, width=0.8, dashes="[3 3]")

    # Right side: Collapsed Subproblem DAG
    p5.insert_text((310, 224), "B. Collapsed Subproblem DAG (|V|=5, |E|=10)", fontsize=9.2, fontname="tiit", color=forest)
    dag_nodes = [
        ("r4", (425, 256)),
        ("r3", (425, 302)),
        ("r2", (425, 348)),
        ("r1", (425, 394)),
        ("r0", (425, 438)),
    ]
    # Draw curved arcs on left and right for multi-step transitions
    for i in range(len(dag_nodes)):
        for j in range(i + 1, len(dag_nodes)):
            x1, y1 = dag_nodes[i][1]
            x2, y2 = dag_nodes[j][1]
            diff = j - i
            if diff == 1:
                p5.draw_line((x1, y1 + 14), (x2, y2 - 14), color=prussian, width=1.2)
            else:
                side = -1 if diff % 2 == 0 else 1
                ctrl_x = x1 + side * (28 + diff * 18)
                ctrl_y = (y1 + y2) / 2
                p5.draw_bezier((x1 + side * 12, y1 + 6), (ctrl_x, ctrl_y), (ctrl_x, ctrl_y), (x2 + side * 12, y2 - 6), color=forest, width=0.9)
    for lbl, (cx, cy) in dag_nodes:
        p5.draw_circle((cx, cy), 14, color=prussian, fill=(0.91, 0.95, 0.97), width=1.3)
        p5.insert_text((cx - 7, cy + 3.5), lbl, fontsize=9.2, fontname="cour", color=prussian)

    p5.insert_textbox(
        fitz.Rect(54, 484, 558, 705),
        (
            "Topological order defines bottom-up tabulation: evaluate vertices in reverse topological order of the dependency DAG "
            "(r_0, r_1, r_2, r_3, r_4) so that every out-neighbor is already computed before a state executes. "
            "Top-down memoization performs depth-first search on the same DAG, visiting only reachable vertices from the target state.\n\n"
            "Subtlety (Negative-Weight Cycles and Acyclicity): Dynamic programming requires the subproblem graph to be acyclic. "
            "In shortest-path problems on general graphs with cycles, relaxing acyclicity requires adding an explicit edge-count "
            "dimension k (Bellman-Ford layers d[k, v]) to unfold the cyclic graph into a layered DAG of depth |V| - 1."
        ),
        fontsize=10.8,
        fontname="tiro",
        color=ink,
        lineheight=1.5,
    )

    # Page 6: Top-Down vs Bottom-Up & Space Compression
    p6 = new_page("Chapter 2 · Dynamic Programming", 6)
    p6.insert_text((54, 78), "2.3 Top-Down Memoization Versus Bottom-Up Tabulation", fontsize=14.5, fontname="tibo", color=ink)
    p6.insert_textbox(
        fitz.Rect(54, 102, 558, 690),
        (
            "Both top-down memoization and bottom-up tabulation achieve the same asymptotic worst-case bound when all subproblems "
            "are reachable, yet their engineering tradeoffs diverge sharply in practice.\n\n"
            "1. Sparse Reachability: When fewer than 10% of the theoretical state space is reachable from the initial query, "
            "top-down memoization avoids computing unreachable table entries altogether.\n"
            "2. Cache Locality and Constant Factors: Bottom-up tabulation iterates over contiguous arrays without recursion stack "
            "frames or hash-table probes, delivering 3x to 8x lower constant overhead on dense grids such as edit distance or matrix-chain multiplication.\n"
            "3. Space Compression: When state transitions depend only on the previous layer k - 1, bottom-up tabulation retains only "
            "two rolling rows, reducing memory from O(n^2) to O(n). Full path reconstruction under O(n) memory requires Hirschberg's "
            "divide-and-conquer midpoint technique.\n\n"
            "Matrix-Chain Multiplication Recurrence:\n"
            "    m[i, j] = min_{i <= k < j} ( m[i, k] + m[k + 1, j] + p_{i-1} p_k p_j )\n\n"
            "Here each interval [i, j] depends strictly on shorter sub-intervals [i, k] and [k+1, j], giving O(n^2) distinct states "
            "with O(n) split choices per state for total time Theta(n^3) and space Theta(n^2)."
        ),
        fontsize=10.8,
        fontname="tiro",
        color=ink,
        lineheight=1.5,
    )

    # Page 7: When Optimal Substructure Fails (Longest Simple Path)
    p7 = new_page("Chapter 2 · Dynamic Programming", 7)
    p7.insert_text((54, 78), "2.4 Failure of Subproblem Independence: Unweighted Longest Simple Path", fontsize=14.5, fontname="tibo", color=ink)
    p7.insert_textbox(
        fitz.Rect(54, 102, 558, 690),
        (
            "Optimal substructure requires not only that optimal solutions decompose into optimal subproblem solutions, but also "
            "that subproblems remain independent—solving one subproblem must not consume resources needed by another.\n\n"
            "Contrast unweighted shortest path with unweighted longest simple path on a four-vertex directed graph with edges "
            "q -> r, r -> t, t -> q, q -> s, s -> t, t -> s. The longest simple path from q to t passes through r (q -> r -> t), "
            "yet combining the longest simple path from q to r (q -> s -> t -> r) with the longest simple path from r to t "
            "(r -> q -> s -> t) reuses vertices s and t, producing an invalid non-simple walk.\n\n"
            "Restoring independence forces encoding the entire visited vertex bitmask S into the state (Held-Karp state dp[S, v]), "
            "expanding the vertex count of the subproblem DAG to |V| * 2^{|V|}."
        ),
        fontsize=10.8,
        fontname="tiro",
        color=ink,
        lineheight=1.5,
    )

    # Pages 8-10: Chapter 3 — Greedy Choice Property and Exchange Arguments
    for idx, sub in enumerate(
        [
            "Chapter 3. Greedy Choice Property and Exchange Arguments",
            "3.2 Huffman Prefix Codes and Optimal Merge Trees",
            "3.3 Matroids and Exact Boundaries Between Greedy and DP",
        ],
        start=8,
    ):
        p = new_page("Chapter 3 · Greedy Choice Property", idx)
        p.insert_text((54, 82), sub, fontsize=14.5, fontname="tibo", color=ink)
        p.insert_textbox(
            fitz.Rect(54, 106, 558, 690),
            (
                "A greedy algorithm avoids evaluating all choices in a recurrence by committing to a single locally optimal decision "
                "before solving the remaining subproblem. Correctness requires proving the greedy choice property via an exchange "
                "argument: take any optimal solution O, swap its first differing choice with the greedy choice g, and prove that "
                "feasibility is preserved without degrading the objective value.\n\n"
                "In activity selection, selecting the compatible activity with earliest finish time maximizes remaining schedule "
                "capacity; swapping any optimal solution's first activity for the earliest-finishing activity never introduces an "
                "overlap. By contrast, 0-1 knapsack lacks the greedy choice property because indivisible item weights create leftover "
                "capacity that interacts globally across remaining items, forcing dynamic programming over capacity states."
            ),
            fontsize=10.8,
            fontname="tiro",
            color=ink,
            lineheight=1.5,
        )

    doc.set_toc(
        [
            [1, "Chapter 1: Divide-and-Conquer and Recurrence Trees", 1],
            [1, "Chapter 2: Dynamic Programming and Subproblem DAGs", 4],
            [1, "Chapter 3: Greedy Choice Property and Exchange Arguments", 8],
        ]
    )
    doc.set_metadata(
        {
            "title": "Decomposition, Recurrence, and Optimal Substructure",
            "author": "Cormen, Leiserson, Rivest & Stein (Study Edition)",
        }
    )
    raw_bytes = doc.tobytes()
    doc.close()
    return raw_bytes


DP_STUDY_NOTES_MD = r"""# Chapter 2: Dynamic Programming and Subproblem DAGs

## TL;DR

Dynamic programming replaces exponential recursive branching with polynomial-time evaluation over a directed acyclic graph (DAG) of unique subproblem states [p. 5]. Correctness rests on optimal substructure with independent subproblems, while efficiency rests on overlapping subproblems whose total runtime equals the number of reachable states multiplied by the transition work per state [p. 4].

## Why This Matters

Mistaking overlapping subproblems for independent divide-and-conquer branches produces silent exponential blowups on inputs larger than 30 elements. Conversely, assuming optimal substructure without checking subproblem independence leads to invalid recurrences on constrained graph problems such as longest simple path [p. 7].

## Key Ideas

### 1. Optimal Substructure and Cut-and-Paste Verification

An optimization problem exhibits optimal substructure when an optimal solution to the full instance contains optimal solutions to its component subproblems [p. 4]. Verification follows a cut-and-paste contradiction: suppose an optimal global solution contained a suboptimal solution to some subproblem, replace that component with the strictly better subproblem solution, and verify that the spliced result remains feasible with a strictly improved objective.

For rod cutting of length $n$ with price vector $p_1, \dots, p_n$, fixing an indivisible first piece of length $i$ yields the Bellman optimality recurrence [p. 4]:

$$r_n = \max_{1 \le i \le n} \left( p_i + r_{n-i} \right), \quad r_0 = 0$$

**Worked Example:** For $n = 4$ and $p = [1, 5, 8, 9]$, a greedy density heuristic selects length 3 (revenue 8) plus remainder 1 (revenue 1) for a total of 9. Evaluating all four first cuts yields $p_2 + r_2 = 5 + 5 = 10$ [p. 4].

**Failure Boundary:** Unweighted longest simple path fails subproblem independence because choosing vertices on the first half of a path forbids reusing those same vertices on the second half [p. 7]. Restoring independence requires expanding the state to track the visited vertex set $S$, multiplying state count to $|V| \cdot 2^{|V|}$.

### 2. Overlapping Subproblems and the Subproblem DAG

When a recursive algorithm revisits the same small set of subproblem states along multiple branches, collapsing identical vertices turns an exponential recursion tree into a compact subproblem DAG $G = (V, E)$ [p. 5].

Total running time follows directly from graph geometry:

$$T(n) = \Theta\!\left(|V| + \sum_{v \in V} \deg^{+}(v)\right)$$

For rod cutting, $|V| = n + 1$ vertices and $\sum \deg^{+}(v) = \binom{n+1}{2}$, reducing runtime from $\Theta(2^n)$ to $\Theta(n^2)$ [p. 4]. For matrix-chain multiplication over interval states $m[i, j]$:

$$m[i, j] = \min_{i \le k < j} \left( m[i, k] + m[k+1, j] + p_{i-1} p_k p_j \right)$$

There are $\Theta(n^2)$ interval subproblems with $O(n)$ split candidates per state, producing $\Theta(n^3)$ total time and $\Theta(n^2)$ table space [p. 6].

### 3. Top-Down Memoization Versus Bottom-Up Tabulation

Both implementations evaluate the same subproblem DAG, yet their operational profiles diverge under sparsity and memory constraints [p. 6]:

1. **Sparse state spaces:** Top-down memoization visits only vertices reachable from the initial query, avoiding work on unreachable states when reachability falls below 10% of the table.
2. **Dense state spaces:** Bottom-up tabulation traverses vertices in reverse topological order over contiguous memory without recursion frames or hash probes, lowering constant factors by 3x to 8x.
3. **Rolling-frontier compression:** When transitions depend strictly on the previous layer $k - 1$, bottom-up evaluation drops space from $O(n^2)$ to $O(n)$ unless full solution reconstruction is required without Hirschberg's midpoint pass [p. 6].

## Argument Structure

1. **Claim:** Polynomial dynamic programming holds if and only if the problem decomposes into an acyclic graph of polynomially many independent subproblems [p. 5].
2. **Evidence:** Rod cutting collapses $2^{n-1}$ branches into $n + 1$ states [p. 4], while matrix-chain intervals form a triangular DAG of $\Theta(n^2)$ states [p. 6].
3. **Counterexample Boundary:** Unweighted longest simple path breaks subproblem independence when vertex usage couples subproblems [p. 7].
4. **Conclusion:** State design—not code template—governs both correctness and asymptotic scaling.

## Open Questions and Confusions

- When does a cyclic shortest-path graph allow unfolding into a layered DAG (Bellman-Ford $d[k, v]$) versus requiring Dijkstra's priority-queue ordering?
- Under what memory bandwidth regimes does cache-oblivious blocking beat standard row-major bottom-up loops?

## Self-Quiz Prompts

1. Why does cut-and-paste fail on unweighted longest simple path even though shortest path on the exact same graph succeeds [p. 7]?
2. Given a recurrence whose subproblem graph contains a cycle of zero-weight transitions, what breaks in bottom-up tabulation [p. 5]?
3. When only 2,000 states are reachable inside a 10 million-cell table, which execution strategy wins and why [p. 6]?
"""


def seed_demo_vault(vault_dir: Path, reset: bool = True) -> dict:
    """Populate a complete realistic demo vault for Scholia."""
    vault_dir = vault_dir.resolve()
    if reset and vault_dir.exists():
        shutil.rmtree(vault_dir)
    vault_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(vault_dir)
    # Use deterministic demo engine by default in the seeded demo vault so interactive clicks work offline too,
    # while showing real detected claude/codex CLI status in Settings.
    cfg.routing = {
        "extraction_planning": StageRoute(provider="agy", model="gemini-4-neon", effort="high"),
        "socratic_dialogue": StageRoute(provider="agy", model="gemini-4-neon", effort="low"),
        "oral_exam_grading": StageRoute(provider="claude", model="opus", effort="high"),
        "note_enrichment": StageRoute(provider="claude", model="sonnet", effort="medium"),
    }
    save_config(cfg, vault_dir)

    db = VaultDB(vault_dir)
    fs = VaultFS(vault_dir)
    ingestion = IngestionService(db, fs)

    # 1. Ingest real generated Algorithms PDF
    algo_pdf_bytes = generate_algorithms_sample_pdf()
    algo_book = ingestion.ingest_upload(
        filename="algorithms_decomposition_monograph.pdf",
        content=algo_pdf_bytes,
        title_override="Decomposition, Recurrence, and Optimal Substructure",
        authors_override="T. H. Cormen, C. E. Leiserson, R. L. Rivest, C. Stein",
        topic_areas=["Algorithms", "Discrete Optimization"],
    )
    ch1, ch2, ch3 = algo_book["chapters"][0], algo_book["chapters"][1], algo_book["chapters"][2]

    # Mark Ch 1 mastered, Ch 2 in_progress (our flagship study chapter), Ch 3 ready
    db.update_chapter_status(ch1["id"], "mastered", "Extraction complete")
    db.update_chapter_status(ch2["id"], "in_progress", "Extraction complete")
    db.update_chapter_status(ch3["id"], "ready", "Extraction complete")

    # Write rich study notes + lesson plan for Ch 2
    fs.write_chapter_notes(algo_book["slug"], ch2["slug"], DP_STUDY_NOTES_MD)
    ch2_plan = {
        "chapter_title": ch2["title"],
        "topic_areas": ["Algorithms", "Discrete Optimization"],
        "estimated_minutes": 35,
        "calibration_questions": [
            "Have you previously proven optimal substructure with a cut-and-paste argument or mainly coded standard tabulation loops?",
            "Do you want to inspect sparse memoization memory tradeoffs alongside the formal recurrences?",
        ],
        "prerequisite_links": ["Recursion", "Trees", "Divide-and-Conquer"],
        "concepts": [
            {
                "name": "Optimal Substructure",
                "summary": "Optimal global solutions contain optimal solutions to independent subproblems, verified via cut-and-paste contradiction.",
                "prerequisites": ["Recursion", "Trees"],
                "page_refs": [4, 7],
                "common_misconceptions": ["Assuming optimal substructure holds whenever a problem can be written recursively, ignoring subproblem independence."],
                "socratic_probe": "Why does a cut-and-paste proof succeed for rod cutting yet fail for unweighted longest simple path [p. 7]?",
                "worked_example_hook": "Rod of length 4 with prices [1, 5, 8, 9] vs. four-vertex directed graph.",
            },
            {
                "name": "Dynamic Programming",
                "summary": "Collapsing overlapping recursive subproblems into a directed acyclic graph of unique states evaluated once in topological order.",
                "prerequisites": ["Recursion", "Trees", "Optimal Substructure"],
                "page_refs": [4, 5],
                "common_misconceptions": ["Equating dynamic programming with filling a 2D array rather than exploiting an acyclic overlapping subproblem DAG."],
                "socratic_probe": "How do the vertex count and out-degrees of the subproblem DAG determine asymptotic runtime [p. 5]?",
                "worked_example_hook": "Figure 2.1 collapsing the 8-leaf recursion tree for r_4 into 5 DAG states.",
            },
            {
                "name": "Memoization vs. Tabulation",
                "summary": "Choosing top-down reachability-driven caching versus bottom-up cache-local topological iteration and rolling-row compression.",
                "prerequisites": ["Dynamic Programming"],
                "page_refs": [6],
                "common_misconceptions": ["Assuming bottom-up tabulation is always faster even when fewer than 10% of states are reachable."],
                "socratic_probe": "When fewer than 10% of table states are reachable from the query, how do memoization and tabulation compare [p. 6]?",
                "worked_example_hook": "Matrix-chain interval table vs. sparse state-space DFS.",
            },
        ],
    }
    fs.write_lesson_plan(algo_book["slug"], ch2["slug"], ch2_plan)

    # Also write concise study notes for Ch 1 and Ch 3 so switching chapters works smoothly
    fs.write_chapter_notes(
        algo_book["slug"],
        ch1["slug"],
        "# Chapter 1: Divide-and-Conquer and Recurrence Trees\n\n## TL;DR\n\nDivide-and-conquer solves disjoint recursive subproblems and recombines them in time $f(n)$, governed by the Master Theorem recurrence $T(n) = aT(n/b) + f(n)$ [p. 1]. Once branches share identical subproblems, the recursion tree repeats identical work exponentially and must collapse into a subproblem DAG [p. 3].\n",
    )
    fs.write_chapter_notes(
        algo_book["slug"],
        ch3["slug"],
        "# Chapter 3: Greedy Choice Property and Exchange Arguments\n\n## TL;DR\n\nGreedy algorithms commit to a single locally optimal step before recursing, eliminating branching across alternatives [p. 8]. Validity requires an exchange argument proving that swapping the first differing choice in any optimal solution preserves feasibility without degrading objective value [p. 8].\n",
    )

    # 2. Ingest a second book (Markdown: Distributed Systems) for rich cross-topic Library, Review Queue, and Topic Graph
    ds_md = """# Chapter 1: Replication Logs and Linearizability

Single-leader replication orders writes through a sequential log, yet asynchronous followers can serve stale reads that violate linearizability. Achieving linearizable reads requires quorum intersection or leader lease verification so that once a write completes, every subsequent read observes at least that version.

# Chapter 2: Consensus, Raft Elections, and Split-Brain Prevention

Consensus protocols guarantee that a majority quorum agrees on a single append-only log sequence despite message delays and crash-recovery faults. Raft enforces log completeness during leader election so that no candidate missing a committed entry can collect a majority vote.

# Chapter 3: Distributed Transactions and Two-Phase Commit

Two-phase commit coordinates atomic updates across disjoint shards through a prepare vote phase followed by a commit phase. Its blocking window occurs when the coordinator crashes after participants record prepared locks, motivating consensus-backed coordinators.
"""
    ds_book = ingestion.ingest_upload(
        filename="designing_data_intensive_systems.md",
        content=ds_md.encode("utf-8"),
        title_override="Designing Data-Intensive Distributed Systems",
        authors_override="M. Kleppmann (Annotated Study Edition)",
        topic_areas=["Distributed Systems", "Storage Engines"],
    )
    ds_ch1, ds_ch2, ds_ch3 = ds_book["chapters"][0], ds_book["chapters"][1], ds_book["chapters"][2]
    db.update_chapter_status(ds_ch1["id"], "mastered", "Extraction complete")
    db.update_chapter_status(ds_ch2["id"], "mastered", "Extraction complete")
    db.update_chapter_status(ds_ch3["id"], "ready", "Extraction complete")
    fs.write_chapter_notes(
        ds_book["slug"],
        ds_ch1["slug"],
        "# Chapter 1: Replication Logs and Linearizability\n\n## TL;DR\n\nLinearizability provides the illusion of a single up-to-date copy of data by enforcing a recency guarantee across concurrent reads and writes. Asynchronous replication breaks linearizability whenever a follower serves a read prior to applying the leader's latest log entry.\n",
    )
    fs.write_chapter_notes(
        ds_book["slug"],
        ds_ch2["slug"],
        "# Chapter 2: Consensus, Raft Elections, and Split-Brain Prevention\n\n## TL;DR\n\nConsensus guarantees agreement, validity, and termination across a fault-tolerant quorum despite network partitions. Raft couples leader election with an up-to-date log check so that every committed log prefix survives leadership changes.\n",
    )

    # 3. Seed Multi-Parent Concept DAG & FSRS States
    now = datetime.now(timezone.utc)
    past_due_3d = (now - timedelta(days=3)).isoformat()
    past_due_1d = (now - timedelta(days=1)).isoformat()
    past_due_5h = (now - timedelta(hours=5)).isoformat()
    last_rev_10d = (now - timedelta(days=10)).isoformat()
    last_rev_6d = (now - timedelta(days=6)).isoformat()
    future_due = (now + timedelta(days=9)).isoformat()

    # Foundational & Algorithms DAG (Explicit Multi-Parent: Recursion + Trees -> Dynamic Programming; DP + Graphs -> Shortest Paths)
    c_rec = db.upsert_concept(
        name="Recursion",
        summary="Inductive problem reduction over self-similar base cases and recursive transitions.",
        book_id=algo_book["id"],
        chapter_id=ch1["id"],
        topic_areas=["Algorithms"],
        page_refs=[1],
        mastery_state="mastered",
        core_passed=True,
    )
    db.update_concept_mastery_and_fsrs(c_rec["id"], "mastered", True, 18.4, 3.8, 4, 0, future_due, last_rev_6d)

    c_trees = db.upsert_concept(
        name="Trees",
        summary="Acyclic hierarchical structures modeling recursion call graphs, intervals, and branching decisions.",
        book_id=algo_book["id"],
        chapter_id=ch1["id"],
        topic_areas=["Algorithms"],
        page_refs=[2],
        mastery_state="mastered",
        core_passed=True,
    )
    db.update_concept_mastery_and_fsrs(c_trees["id"], "mastered", True, 14.2, 4.1, 3, 0, future_due, last_rev_6d)

    c_graphs = db.upsert_concept(
        name="Directed Acyclic Graphs",
        summary="Directed graphs with zero cycles admitting a linear topological ordering of all dependencies.",
        book_id=algo_book["id"],
        chapter_id=ch1["id"],
        topic_areas=["Algorithms"],
        page_refs=[3],
        mastery_state="mastered",
        core_passed=True,
    )
    db.update_concept_mastery_and_fsrs(
        c_graphs["id"],
        "mastered",
        True,
        7.5,
        4.6,
        3,
        0,
        past_due_1d,
        last_rev_10d,
        append_frontier="Detecting cycles incrementally under online edge insertions requires dynamic topological maintenance.",
    )

    c_opt = db.upsert_concept(
        name="Optimal Substructure",
        summary="Optimal global solutions decompose into optimal solutions of independent subproblems, verified via cut-and-paste contradiction.",
        book_id=algo_book["id"],
        chapter_id=ch2["id"],
        topic_areas=["Algorithms", "Discrete Optimization"],
        page_refs=[4, 7],
        misconceptions=["Assuming recursive phrasing guarantees subproblem independence on simple-path constraints."],
        frontiers=["Restoring independence on longest simple path expands the state to visited bitmasks of size |V| 2^|V|."],
        mastery_state="mastered",
        core_passed=True,
    )
    db.update_concept_mastery_and_fsrs(c_opt["id"], "mastered", True, 6.2, 5.1, 2, 0, past_due_3d, last_rev_10d)

    c_dp = db.upsert_concept(
        name="Dynamic Programming",
        summary="Evaluating overlapping subproblems once over a collapsed subproblem DAG in topological order.",
        book_id=algo_book["id"],
        chapter_id=ch2["id"],
        topic_areas=["Algorithms", "Discrete Optimization"],
        page_refs=[4, 5],
        misconceptions=["Confusing DP with bottom-up array boilerplate rather than subproblem DAG collapse."],
        frontiers=["Unfolding cyclic negative-weight shortest paths into a layered Bellman-Ford DAG of depth |V|-1."],
        mastery_state="core_passed",
        core_passed=True,
    )
    db.update_concept_mastery_and_fsrs(c_dp["id"], "core_passed", True, 4.8, 5.4, 2, 0, past_due_5h, last_rev_6d)

    c_mem = db.upsert_concept(
        name="Memoization vs. Tabulation",
        summary="Tradeoff between sparse reachability in top-down caching and cache locality plus rolling-row compression in bottom-up iteration.",
        book_id=algo_book["id"],
        chapter_id=ch2["id"],
        topic_areas=["Algorithms", "Discrete Optimization"],
        page_refs=[6],
        misconceptions=["Assuming bottom-up loops dominate when fewer than 10% of states are reachable."],
        mastery_state="learning",
        core_passed=False,
    )

    c_greedy = db.upsert_concept(
        name="Greedy Exchange Arguments",
        summary="Proving a single locally optimal choice can safely replace the first differing choice in any optimal solution.",
        book_id=algo_book["id"],
        chapter_id=ch3["id"],
        topic_areas=["Algorithms", "Discrete Optimization"],
        page_refs=[8],
        mastery_state="unseen",
        core_passed=False,
    )

    c_sp = db.upsert_concept(
        name="Shortest Paths in Weighted Graphs",
        summary="Layered DAG relaxation (Bellman-Ford) versus greedy priority-queue expansion (Dijkstra) depending on edge-weight signs.",
        book_id=algo_book["id"],
        chapter_id=ch3["id"],
        topic_areas=["Algorithms"],
        page_refs=[5, 9],
        mastery_state="needs_review",
        core_passed=True,
    )
    db.update_concept_mastery_and_fsrs(
        c_sp["id"],
        "needs_review",
        True,
        3.9,
        6.1,
        2,
        1,
        past_due_3d,
        last_rev_10d,
        append_frontier="Negative-weight edges invalidate Dijkstra's finalized-distance invariant even without negative cycles.",
    )

    # Distributed Systems DAG (Multi-Parent: Replication Logs + Consensus Quorums -> Linearizability)
    c_repl = db.upsert_concept(
        name="Replication Logs",
        summary="Ordered append-only write-ahead streams propagating state mutations from leader to followers.",
        book_id=ds_book["id"],
        chapter_id=ds_ch1["id"],
        topic_areas=["Distributed Systems"],
        page_refs=[1],
        mastery_state="mastered",
        core_passed=True,
    )
    db.update_concept_mastery_and_fsrs(c_repl["id"], "mastered", True, 11.4, 4.3, 3, 0, future_due, last_rev_6d)

    c_cons = db.upsert_concept(
        name="Consensus Quorums",
        summary="Intersecting majorities guaranteeing a single committed log sequence across crash-recovery faults.",
        book_id=ds_book["id"],
        chapter_id=ds_ch2["id"],
        topic_areas=["Distributed Systems"],
        page_refs=[2],
        mastery_state="mastered",
        core_passed=True,
    )
    db.update_concept_mastery_and_fsrs(
        c_cons["id"],
        "mastered",
        True,
        5.5,
        5.8,
        2,
        0,
        past_due_1d,
        last_rev_10d,
        append_frontier="Distinguishing leader lease clock-drift bounds from ReadIndex quorum round-trips under pause faults.",
    )

    c_lin = db.upsert_concept(
        name="Linearizability",
        summary="Real-time recency guarantee ensuring every read after a completed write observes that write or a newer state.",
        book_id=ds_book["id"],
        chapter_id=ds_ch1["id"],
        topic_areas=["Distributed Systems"],
        page_refs=[1],
        mastery_state="mastered",
        core_passed=True,
    )
    db.update_concept_mastery_and_fsrs(
        c_lin["id"],
        "mastered",
        True,
        4.4,
        6.0,
        2,
        0,
        past_due_3d,
        last_rev_10d,
        append_frontier="Separating single-object linearizability from multi-object serializability (strict serializability).",
    )

    c_2pc = db.upsert_concept(
        name="Two-Phase Commit",
        summary="Atomic commit protocol across independent shards using a blocking prepare-and-commit coordinator.",
        book_id=ds_book["id"],
        chapter_id=ds_ch3["id"],
        topic_areas=["Distributed Systems"],
        page_refs=[3],
        mastery_state="learning",
        core_passed=False,
    )

    # Multi-parent prerequisite edges!
    edges = [
        (c_rec["id"], c_dp["id"]),
        (c_trees["id"], c_dp["id"]),
        (c_opt["id"], c_dp["id"]),
        (c_graphs["id"], c_dp["id"]),
        (c_rec["id"], c_opt["id"]),
        (c_dp["id"], c_mem["id"]),
        (c_dp["id"], c_sp["id"]),
        (c_graphs["id"], c_sp["id"]),
        (c_opt["id"], c_greedy["id"]),
        (c_repl["id"], c_lin["id"]),
        (c_cons["id"], c_lin["id"]),
        (c_cons["id"], c_2pc["id"]),
        (c_lin["id"], c_2pc["id"]),
    ]
    for p_id, ch_id in edges:
        db.add_concept_edge(p_id, ch_id, relation="prerequisite")

    # 4. Seed Learner Notes for Ch 2
    db.add_learner_note(
        "confusion",
        "Initially treated subproblem independence as automatic whenever a recursive formula existed, missing the vertex-reuse conflict in longest simple path.",
        chapter_id=ch2["id"],
        concept_id=c_opt["id"],
        resolved=True,
    )
    db.add_learner_note(
        "breakthrough",
        "Seeing Figure 2.1 collapse the 8-leaf recursion tree into a 5-vertex subproblem DAG made the Theta(|V| + |E|) runtime bound immediate.",
        chapter_id=ch2["id"],
        concept_id=c_dp["id"],
        resolved=True,
    )
    db.add_learner_note(
        "frontier",
        "Unfolding cyclic negative-weight shortest paths into a layered Bellman-Ford DAG of depth |V|-1 vs. arbitrary cycle detection.",
        chapter_id=ch2["id"],
        concept_id=c_dp["id"],
        resolved=False,
    )

    # 5. Seed Rich Active Session on Chapter 2 with BOTH a crisp Socratic transcript AND an active Oral Exam at Q3/5 (Core Bar Passed + Frontier Probe #2)
    # Create Session A (Socratic dialogue transcript — active on Ch 2 for Socratic view)
    socratic_sess = db.create_session(
        book_id=algo_book["id"],
        chapter_id=ch2["id"],
        stage="socratic",
        active_concept_id=c_mem["id"],
        session_id="sess_dp_socratic",
    )
    db.update_session(
        socratic_sess["id"],
        covered_concept_ids=[c_opt["id"], c_dp["id"]],
        active_concept_id=c_mem["id"],
    )
    db.append_message(
        socratic_sess["id"],
        speaker="TUTOR",
        stage="plan",
        content=(
            "This chapter covers 3 core concepts across pages 4 through 7. Prerequisite links in your concept graph: Recursion, Trees, Directed Acyclic Graphs.\n\n"
            "- **Optimal Substructure** — Cut-and-paste verification and subproblem independence [p. 4]\n"
            "- **Dynamic Programming** — Collapsing overlapping recursion trees into a subproblem DAG [p. 5]\n"
            "- **Memoization vs. Tabulation** — Reachability sparsity, cache locality, and rolling-row compression [p. 6]\n\n"
            "State which mechanisms you already know well and whether you want to emphasize sparse-state tradeoffs."
        ),
        citations=[{"page": 4, "label": "p. 4"}, {"page": 5, "label": "p. 5"}, {"page": 6, "label": "p. 6"}],
    )
    db.append_message(
        socratic_sess["id"],
        speaker="YOU",
        stage="plan",
        content="I have coded standard tabulation loops before, but I want to sharpen my intuition on subproblem independence failures and when memoization beats tabulation.",
    )
    db.append_message(
        socratic_sess["id"],
        speaker="TUTOR",
        stage="socratic",
        content=(
            "Optimal substructure requires that replacing a suboptimal subproblem solution strictly improves the global objective without breaking feasibility [p. 4]. "
            "On a four-vertex directed graph, unweighted shortest path satisfies this condition, whereas unweighted longest simple path breaks it [p. 7]. "
            "What shared resource couples the two halves of a longest simple path so that solving each half independently yields an invalid walk?"
        ),
        citations=[{"page": 4, "label": "p. 4"}, {"page": 7, "label": "p. 7"}],
        metadata={"concept_id": c_opt["id"], "concept_name": "Optimal Substructure"},
    )
    db.append_message(
        socratic_sess["id"],
        speaker="YOU",
        stage="socratic",
        content="Both subpaths compete for the same set of intermediate vertices. Because a simple path forbids repeating any vertex, choosing the optimal first subpath consumes vertices that the second subpath also wants to use.",
    )
    db.append_message(
        socratic_sess["id"],
        speaker="TUTOR",
        stage="socratic",
        content=(
            "Vertex exclusivity couples the two subproblems, forcing any valid recurrence to carry the visited bitmask $S$ inside the state [p. 7]. "
            "Now shift to **Memoization vs. Tabulation** on a $1000 \\times 1000$ grid recurrence where input constraints make fewer than 4% of states reachable from the initial query [p. 6]. "
            "How do cache locality, recursion overhead, and unreachable-state computation trade off between top-down memoization and bottom-up tabulation here?"
        ),
        citations=[{"page": 7, "label": "p. 7"}, {"page": 6, "label": "p. 6"}],
        metadata={"concept_id": c_mem["id"], "concept_name": "Memoization vs. Tabulation"},
    )
    fs.write_session_snapshot(algo_book["slug"], ch2["slug"], db.get_session(socratic_sess["id"]))  # type: ignore[arg-type]

    # Create Session B (Active Oral Exam session on Ch 2 at Q3/5 Analysis, Core Bar Cleared + Frontier Probe #2)
    exam_questions = [
        {
            "index": 1,
            "cognitive_level": "explanation",
            "concept_id": c_opt["id"],
            "concept_name": "Optimal Substructure",
            "max_points": 4,
            "prompt": "Explain why optimal substructure requires subproblem independence, contrasting unweighted shortest path against unweighted longest simple path [p. 7].",
            "core_criteria": ["States cut-and-paste contradiction", "Explains vertex-reuse coupling in longest simple path"],
            "core_bar_passed": True,
            "score": 4.0,
            "phase": "completed",
            "frontier_depth": 1,
            "frontier_notes": ["Held-Karp bitmask state expansion restores independence at exponential |V| 2^|V| cost."],
            "attempts_on_core": 1,
            "is_retake": False,
        },
        {
            "index": 2,
            "cognitive_level": "application",
            "concept_id": c_mem["id"],
            "concept_name": "Memoization vs. Tabulation",
            "max_points": 4,
            "prompt": "Given a state table of 10 million cells where fewer than 2,000 states are reachable from the initial input, select top-down memoization or bottom-up tabulation and justify the memory layout [p. 6].",
            "core_criteria": ["Selects top-down memoization for sparse reachability", "Notes hash-map overhead versus dense array traversal"],
            "core_bar_passed": True,
            "score": 4.0,
            "phase": "completed",
            "frontier_depth": 1,
            "frontier_notes": ["Hybrid sparse BFS frontier avoids stack overflow while preserving reachability pruning."],
            "attempts_on_core": 1,
            "is_retake": False,
        },
        {
            "index": 3,
            "cognitive_level": "analysis",
            "concept_id": c_dp["id"],
            "concept_name": "Dynamic Programming",
            "max_points": 4,
            "prompt": "Analyze how the vertex count |V| and edge count |E| of the subproblem DAG determine total runtime for rod cutting and matrix-chain multiplication [p. 5].",
            "core_criteria": ["Relates |V| to unique states and out-degree to transition choices", "Derives Theta(n^2) for rod cutting and Theta(n^3) for matrix-chain"],
            "core_bar_passed": True,
            "score": 4.0,
            "phase": "frontier_probing",
            "frontier_depth": 2,
            "frontier_notes": [],
            "attempts_on_core": 1,
            "is_retake": False,
        },
        {
            "index": 4,
            "cognitive_level": "evaluation",
            "concept_id": c_mem["id"],
            "concept_name": "Memoization vs. Tabulation",
            "max_points": 4,
            "prompt": "Evaluate rolling-row space compression when the caller also requires reconstructing the exact optimal edit sequence [p. 6].",
            "core_criteria": ["Identifies loss of backpointers under O(n) space", "Describes Hirschberg divide-and-conquer midpoint recovery"],
            "core_bar_passed": False,
            "score": 0.0,
            "phase": "pending",
            "frontier_depth": 0,
            "frontier_notes": [],
            "attempts_on_core": 0,
            "is_retake": False,
        },
        {
            "index": 5,
            "cognitive_level": "synthesis",
            "concept_id": c_dp["id"],
            "concept_name": "Dynamic Programming",
            "max_points": 4,
            "prompt": "Work through rod cutting for length n = 4 with p = [1, 5, 8, 9], tracing r_1 through r_4 in topological order and reconstructing the optimal cuts [p. 4].",
            "core_criteria": ["Evaluates r_1=1, r_2=5, r_3=8, r_4=10", "Reconstructs two cuts of length 2"],
            "core_bar_passed": False,
            "score": 0.0,
            "phase": "pending",
            "frontier_depth": 0,
            "frontier_notes": [],
            "attempts_on_core": 0,
            "is_retake": False,
        },
    ]
    exam_state = {
        "exam_type": "chapter",
        "chapter_ids": [ch2["id"]],
        "current_question_index": 2,  # Q3/5
        "total_points_possible": 20,
        "points_earned": 12.0,
        "passed": None,
        "failed_concept_ids": [],
        "questions": exam_questions,
        "attempt_number": 1,
    }
    exam_sess = db.create_session(
        book_id=algo_book["id"],
        chapter_id=ch2["id"],
        stage="exam",
        active_concept_id=c_dp["id"],
        exam_state=exam_state,
        session_id="sess_dp_exam",
    )
    db.append_message(
        exam_sess["id"],
        speaker="EXAMINER",
        stage="exam",
        content=(
            "**Question 3/5 (ANALYSIS · 4 pts) — Dynamic Programming**\n\n"
            "Analyze how the vertex count $|V|$ and edge count $|E|$ of the subproblem DAG determine total runtime for rod cutting and matrix-chain multiplication [p. 5]."
        ),
        citations=[{"page": 5, "label": "p. 5"}],
        metadata={"question_index": 3, "cognitive_level": "analysis", "phase": "core_bar", "core_bar_passed": False, "frontier_depth": 0},
    )
    db.append_message(
        exam_sess["id"],
        speaker="YOU",
        stage="exam",
        content="Each distinct subproblem is evaluated once, so total work sums the transition fan-out across every vertex: Theta(|V| + |E|). Rod cutting has n + 1 states with up to i choices per state for Theta(n^2) time, whereas matrix-chain has Theta(n^2) interval states with O(n) split indices each for Theta(n^3) time.",
    )
    db.append_message(
        exam_sess["id"],
        speaker="EXAMINER",
        stage="exam",
        content=(
            "**Core Bar Cleared (4.0/4 pts).** Your accounting separates state cardinality from transition fan-out cleanly across both recurrences [p. 5].\n\n"
            "**Frontier Probe #1 (No Penalty):** Relax acyclicity: if a shortest-path recurrence operates on a graph containing cycles without negative cycles, why does single-pass topological tabulation fail and how does adding an edge-count layer $k$ restore a DAG [p. 5]?"
        ),
        citations=[{"page": 5, "label": "p. 5"}],
        metadata={"question_index": 3, "cognitive_level": "analysis", "phase": "frontier_probing", "core_bar_passed": True, "frontier_depth": 1},
    )
    db.append_message(
        exam_sess["id"],
        speaker="YOU",
        stage="exam",
        content="Cycles prevent any topological ordering over raw vertices. Indexing states by (k, v) for paths of at most k edges forces every transition from layer k-1 to layer k, unfolding the cyclic graph into a layered DAG of depth |V|-1 as in Bellman-Ford.",
    )
    db.append_message(
        exam_sess["id"],
        speaker="EXAMINER",
        stage="exam",
        content=(
            "**Frontier Probe #1 Cleared.** Unfolding cyclic dependencies into $|V| - 1$ monotonic layers recovers acyclicity at the cost of multiplying vertex count by $|V|$ [p. 5].\n\n"
            "**Frontier Probe #2 (No Penalty):** Now push one step further: when edge weights are strictly non-negative, Dijkstra computes shortest paths in $O((|V| + |E|) \\log |V|)$ without creating $|V|$ explicit layers. Which exact monotonicity property lets a priority queue discover a valid topological evaluation order on the fly, and why does a single negative edge break it?"
        ),
        citations=[{"page": 5, "label": "p. 5"}],
        metadata={"question_index": 3, "cognitive_level": "analysis", "phase": "frontier_probing", "core_bar_passed": True, "frontier_depth": 2},
    )
    # Make socratic_sess the latest updated by 1 second or keep exam_sess accessible; let's keep socratic_sess as latest so opening Chapter 2 shows Notes + Socratic first,
    # and make exam_sess easily selectable via session switcher or tab! Wait: let's check both screenshots!
    # In our UI, the Right Pane has stage tabs (`1. Plan`, `2. Socratic`, `3. Oral Exam`, `4. Enriched`) AND a session switcher so switching between Socratic and active Oral Exam is 1 click!
    with db.connect() as conn:
        t_exam = (now - timedelta(minutes=2)).isoformat()
        t_soc = now.isoformat()
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (t_exam, exam_sess["id"]))
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (t_soc, socratic_sess["id"]))

    fs.write_session_snapshot(algo_book["slug"], ch2["slug"], db.get_session(exam_sess["id"]))  # type: ignore[arg-type]

    # Pre-render page 4 and page 5 PNGs so they're warm too
    ingestion.render_chapter_page_png(algo_book["slug"], ch2["slug"], 1)
    ingestion.render_chapter_page_png(algo_book["slug"], ch2["slug"], 2)

    return {
        "vault_dir": str(vault_dir),
        "algo_book_id": algo_book["id"],
        "dp_chapter_id": ch2["id"],
        "socratic_session_id": socratic_sess["id"],
        "exam_session_id": exam_sess["id"],
        "ds_book_id": ds_book["id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a realistic Scholia demo vault.")
    parser.add_argument("--vault", type=str, required=True, help="Target vault directory.")
    parser.add_argument("--no-reset", action="store_true", help="Do not wipe existing target vault.")
    args = parser.parse_args()
    summary = seed_demo_vault(Path(args.vault), reset=not args.no_reset)
    print(f"Seeded Scholia demo vault: {summary}")


if __name__ == "__main__":
    main()
