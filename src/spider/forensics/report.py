"""Deterministic Markdown report. No timestamps."""

from __future__ import annotations

from typing import Sequence


def _cell(value) -> str:
    if value is None:
        return ""
    return str(value)


def _table(headers: Sequence[str], rows: Sequence[Sequence]) -> str:
    head = "| " + " | ".join(headers) + " |"
    rule = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


def _bullets(items: Sequence[str]) -> str:
    if not items:
        return "_None recorded._"
    return "\n".join(f"- {item}" for item in items)


def render_report(document: dict) -> str:
    findings = document["findings"]
    validation = document["validation"]
    label_a = findings["label_a"]
    label_b = findings["label_b"]
    role_a = findings["role_a"]
    role_b = findings["role_b"]
    focus = findings.get("focus_column")
    lines = [
        f"# Solution forensics: {label_a} vs {label_b}",
        "",
        f"Schema `{document['schema']}`. Route A is the {role_a} (`{label_a}`). "
        f"Route B is the {role_b} (`{label_b}`). "
        "Corrected MobilityWare cost is the engine total. "
        "This report compares structural condition at stock boundaries. "
        "It does not align move text and it does not treat either route as optimal.",
        "",
        "## 1. Executive summary",
        "",
        (
            f"{label_b} finishes at corrected MW {findings['g_b']}. "
            f"{label_a} finishes at {findings['g_a']}. "
            f"The gap (B minus A) is {findings['g_gap_b_minus_a']}. "
            f"Segment accounting {'matches' if findings['phase_gap_matches_total'] else 'does not match'} that gap "
            f"(accounted {findings['phase_gap_accounted']})."
        ),
        "",
        findings["hypothesis_better_opening_worse_continuation"]["reason"],
        "",
        findings["gap_character"]["reason"],
        "",
        findings["divergence"]["ancestry_reason"],
        "",
        "What each route makes expensive later is in sections 11 and 12. "
        "Those statements carry confidence grades. A grade is not a count of caused moves.",
        "",
        "## 2. Validation",
        "",
        _table(
            ["route", "file", "moves sha256", "actions", "solved", "foundations", "stock", "corrected MW", "legacy MW", "deals", "tableau moves"],
            [
                [
                    label_a,
                    validation["a"]["moves_path"],
                    validation["a"]["moves_sha256"],
                    validation["a"]["actions"],
                    validation["a"]["solved"],
                    validation["a"]["foundations"],
                    validation["a"]["stock_remaining"],
                    validation["a"]["mobilityware_moves"],
                    validation["a"]["legacy_mw"],
                    validation["a"]["stock_deals"],
                    validation["a"]["tableau_moves"],
                ],
                [
                    label_b,
                    validation["b"]["moves_path"],
                    validation["b"]["moves_sha256"],
                    validation["b"]["actions"],
                    validation["b"]["solved"],
                    validation["b"]["foundations"],
                    validation["b"]["stock_remaining"],
                    validation["b"]["mobilityware_moves"],
                    validation["b"]["legacy_mw"],
                    validation["b"]["stock_deals"],
                    validation["b"]["tableau_moves"],
                ],
            ],
        ),
        "",
        f"Deal file `{validation['a']['deal_path']}` sha256 `{validation['a']['deal_sha256']}`.",
        "Both totals were produced by `replay_actions_detailed` under `MW_RULES` from the untouched deal.",
        "",
        "## 3. Opening comparison",
        "",
        _opening_section(findings["opening"]),
        "",
        "## 4. Stock-boundary comparison",
        "",
        _horizon_table(document),
        "",
        "Gap contribution is extra corrected MW spent by B in that segment. "
        "Deal segments contain only the deal action, so they are 0 when both routes pay 1.",
        "",
        _table(
            ["segment", "A spent", "B spent", "B minus A", "debt sum A", "debt sum B", "face-down A", "face-down B", "bonds A", "bonds B", "rehandles A", "rehandles B"],
            [
                [
                    row["segment"],
                    row["g_spent_a"],
                    row["g_spent_b"],
                    row["gap_contribution_b_minus_a"],
                    row["debt_sum_end_a"],
                    row["debt_sum_end_b"],
                    row["face_down_end_a"],
                    row["face_down_end_b"],
                    row["bonds_end_a"],
                    row["bonds_end_b"],
                    row["rehandles_end_a"],
                    row["rehandles_end_b"],
                ]
                for row in findings["phase_gaps"]
            ],
        ),
        "",
        "## 5. Strong machine behaviours",
        "",
        "### MACHINE BEHAVIOUR TO PRESERVE",
        "",
        _claim_list(findings["machine_behaviour_to_preserve"]),
        "",
        "### MACHINE BEHAVIOUR TO SUPPRESS / IMPROVE",
        "",
        _claim_list(findings["machine_behaviour_to_suppress"]),
        "",
        "## 6. Major structural liabilities",
        "",
        _bullets(item["statement"] + f" Confidence {item['confidence']}." for item in findings["what_b_makes_expensive_later"]),
        "",
        "Exclusive cost-class accounting partitions the MW totals. It is not a causal partition. "
        "A reveal that also parks is counted as REVEAL because reveal has priority.",
        "",
        _table(
            ["class", "A", "B", "B minus A"],
            [[row["class"], row["cost_a"], row["cost_b"], row["gap_b_minus_a"]] for row in findings["exclusive_cost_class_gap"]],
        ),
        "",
        "## 7. Column focus forensic timeline",
        "",
        _focus_section(focus),
        "",
        "## 8. Card-rehandling comparison",
        "",
        _rehandle_section(document),
        "",
        "## 9. Park lifecycle comparison",
        "",
        _park_section(document),
        "",
        "## 10. Workspace lifecycle comparison",
        "",
        _workspace_section(document),
        "",
        "## 11. Forward attribution findings",
        "",
        (
            "Forward question: at what point does one trajectory begin accumulating extra later cost? "
            "The evidence available from two finished routes is the segment in which B's MW spend pulls ahead, "
            "together with the structural measures at that boundary. That is a location, not a proof of avoidability."
        ),
        "",
        _bullets(_forward_lines(findings)),
        "",
        "## 12. Backward attribution findings",
        "",
        (
            "Backward question: which earlier decision made a later repair necessary? "
            "HIGH requires the repaired physical card to be the anchor of a HIGH-confidence park on the repaired column. "
            "MEDIUM is an overlapping placement or a stock landing whose column was arranged earlier. "
            "LOW is column correlation without that card link. None of these grades assign an exact future-move total."
        ),
        "",
        _attribution_section(findings["backward_high"], "HIGH"),
        "",
        _attribution_section(findings["backward_medium"], "MEDIUM"),
        "",
        f"Counterfactual seeds recorded: {findings['counterfactual_seed_count']}. They are one ply of immediate metrics.",
        "",
        _seed_section(document["comparison"]["counterfactual_seeds"]),
        "",
        "## 13. Earliest important divergences",
        "",
        findings["divergence"]["ancestry_reason"],
        "",
        (
            f"Common prefix actions: {findings['divergence']['common_prefix_actions']}. "
            f"First differing action on A: `{findings['divergence']['first_action_a']}`. "
            f"First differing action on B: `{findings['divergence']['first_action_b']}`. "
            f"Shared exact states: {findings['divergence']['shared_exact_state_count']}. "
            f"Strategic reconvergences after the prefix, excluding any solved terminal: {findings['divergence']['reconvergence_count']}. "
            f"Shared solved terminals: {findings['divergence']['shared_terminal_solved_count']}. "
            f"Post-stock symmetry-only pairs: {findings['divergence']['post_stock_symmetry_only_pairs']}."
        ),
        "",
        document["comparison"]["divergence"]["symmetry_rule"],
        "",
        "## 14. What B teaches that A does not",
        "",
        _claim_list(findings["what_b_teaches"]),
        "",
        "## 15. What A does materially better",
        "",
        _bullets(findings["what_a_does_materially_better"]),
        "",
        "## 16. Implications for future principal-line search",
        "",
        _bullets(_search_implications(findings)),
        "",
        "## 17. Metrics that proved useful",
        "",
        _metric_list(findings["metrics_useful"]),
        "",
        "## 18. Metrics that were noisy or misleading",
        "",
        _metric_list(findings["metrics_noisy"]),
        "",
        "## 19. Explicit unknowns",
        "",
        _bullets(_unknowns(findings)),
        "",
        "## 20. Recommended next development step",
        "",
        findings["next_experiment"]["recommendation"],
        "",
        "## Definitions",
        "",
        _bullets(
            f"**{key}.** {document['schema_notes'][key]}"
            for key in sorted(document["schema_notes"])
        ),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _opening_section(opening: dict) -> str:
    if not opening.get("available"):
        return opening.get("reason", "Opening horizon unavailable.")
    rows = _table(
        ["measure", opening["label_a"], opening["label_b"]],
        [
            ["corrected MW at pre-SD1", opening["g_a"], opening["g_b"]],
            ["action index at pre-SD1", opening["action_index_a"], opening["action_index_b"]],
            ["positive-cost moves", opening["stats_a"]["positive_cost_moves"], opening["stats_b"]["positive_cost_moves"]],
            ["zero-cost whole-column moves", opening["stats_a"]["zero_cost_whole_column_moves"], opening["stats_b"]["zero_cost_whole_column_moves"]],
            ["cards revealed", opening["stats_a"]["reveals"], opening["stats_b"]["reveals"]],
            ["face-down remaining", opening["face_down_a"], opening["face_down_b"]],
            ["same-suit bonds", opening["bonds_a"], opening["bonds_b"]],
            ["run compression", opening["compression_a"], opening["compression_b"]],
            ["empty columns", opening["empty_a"], opening["empty_b"]],
            ["experimental debt sum", opening["debt_sum_a"], opening["debt_sum_b"]],
            ["positive-cost rehandle card-events", opening["rehandles_a"], opening["rehandles_b"]],
            ["foundations", opening["foundations_a"], opening["foundations_b"]],
        ],
    )
    details = opening["stats_b"]["zero_cost_details"]
    extra = "Zero-cost whole-column moves on B before SD1:"
    if not details:
        extra += " none."
    else:
        rendered = "; ".join(
            f"action {item['action_index']} `{item['canonical']}` relocates "
            f"{' '.join(item['run_labels']) or 'the whole column'}"
            f"{', source becomes empty' if item['source_became_empty'] else ''}, "
            f"revealed {len(item['revealed'])}, bonds {item['bonds_delta']:+d}, "
            f"face-down {item['face_down_delta']:+d}"
            for item in details
        )
        extra += " " + rendered + "."
        if details and all(len(item["revealed"]) == 0 for item in details):
            extra += " These transfers reveal nothing. They rearrange already-built runs and manage an empty column before the deal."
    cheaper = (
        "B's opening is cheaper on corrected MW."
        if opening["b_opening_cheaper"]
        else "B's opening is not cheaper on corrected MW."
    )
    return rows + "\n\n" + cheaper + " " + extra


def _horizon_table(document: dict) -> str:
    horizons_a = {row["role"]: row for row in document["trajectories"]["a"]["horizons"]}
    horizons_b = {row["role"]: row for row in document["trajectories"]["b"]["horizons"]}
    roles = []
    for role in (
        "opening",
        "pre-SD1",
        "post-SD1",
        "pre-SD2",
        "post-SD2",
        "pre-SD3",
        "post-SD3",
        "pre-SD4",
        "post-SD4",
        "pre-SD5",
        "post-SD5",
        "stock-empty-endgame",
        "solved",
    ):
        if role in horizons_a or role in horizons_b:
            roles.append(role)
    rows = []
    for role in roles:
        left = horizons_a.get(role, {})
        right = horizons_b.get(role, {})
        rows.append(
            [
                role,
                left.get("cumulative_g", ""),
                right.get("cumulative_g", ""),
                left.get("foundations_completed", ""),
                right.get("foundations_completed", ""),
                left.get("face_down_remaining", ""),
                right.get("face_down_remaining", ""),
                left.get("empty_columns", ""),
                right.get("empty_columns", ""),
                left.get("same_suit_bonds", ""),
                right.get("same_suit_bonds", ""),
                left.get("legal_reveal_columns", ""),
                right.get("legal_reveal_columns", ""),
                left.get("cards_moved_2plus_to_date", ""),
                right.get("cards_moved_2plus_to_date", ""),
                left.get("experimental_debt_sum", ""),
                right.get("experimental_debt_sum", ""),
            ]
        )
    return _table(
        [
            "horizon",
            "g A",
            "g B",
            "found A",
            "found B",
            "fd A",
            "fd B",
            "empty A",
            "empty B",
            "bonds A",
            "bonds B",
            "reveal cols A",
            "reveal cols B",
            "cards 2+ A",
            "cards 2+ B",
            "debt sum A",
            "debt sum B",
        ],
        rows,
    )


def _claim_list(claims: Sequence[dict]) -> str:
    if not claims:
        return "_None recorded._"
    return "\n".join(
        f"- **{claim['claim']}** ({claim['confidence']}). {claim['evidence']}" for claim in claims
    )


def _focus_section(focus) -> str:
    if not focus:
        return "No focus column was requested."
    verdict = focus["reference_also_carries_this_column"]
    lines = [
        f"Focus column is {focus['column']} (MobilityWare column number, 1-based).",
        "",
        verdict["reason"],
        "",
        f"Horizons where B is more disordered: {', '.join(verdict['horizons_b_more_disordered']) or 'none'}.",
        f"Horizons where A is more disordered: {', '.join(verdict['horizons_a_more_disordered']) or 'none'}.",
        "",
        _table(
            ["horizon", "disorder A", "disorder B", "debt A", "debt B", "suit br A", "suit br B", "rank br A", "rank br B", "buried up A", "buried up B", "argmax A", "argmax B"],
            [
                [
                    row["role"],
                    row["disorder_a"],
                    row["disorder_b"],
                    row["debt_a"],
                    row["debt_b"],
                    row["suit_boundaries_a"],
                    row["suit_boundaries_b"],
                    row["rank_discontinuities_a"],
                    row["rank_discontinuities_b"],
                    row["buried_face_up_a"],
                    row["buried_face_up_b"],
                    row["argmax_a"],
                    row["argmax_b"],
                ]
                for row in focus["horizons"]
            ],
        ),
        "",
    ]
    first = focus["timeline_b"]["first_increase"]
    if first:
        lines.append(
            f"First B action that raises column {focus['column']} disorder, or raises its experimental score by 2 or more: "
            f"action {first['action_index']} `{first['canonical']}` at g={first['cumulative_g']} "
            f"({first['phase']}, class {first['exclusive_class']}). "
            f"Disorder {first['disorder_before']} -> {first['disorder_after']}, "
            f"experimental score {first['debt_before']} -> {first['debt_after']}. "
            f"Bonds delta {first['bonds_delta']:+d}, face-down delta {first['face_down_delta']:+d}, "
            f"revealed {first['revealed'] or 'nothing'}."
        )
    else:
        lines.append(f"Column {focus['column']} on B has no recorded disorder or experimental-score increase.")
    increases = focus["timeline_b"]["increases"]
    lines.append("")
    lines.append(f"B actions that increase this column's disorder or experimental score by 2 or more: {len(increases)}.")
    shown = increases[:25]
    if shown:
        lines.append("")
        lines.append(
            _table(
                ["action", "g", "canonical", "class", "disorder", "score", "revealed", "bonds", "face-down"],
                [
                    [
                        row["action_index"],
                        row["cumulative_g"],
                        f"`{row['canonical']}`",
                        row["exclusive_class"],
                        f"{row['disorder_before']}->{row['disorder_after']}",
                        f"{row['debt_before']}->{row['debt_after']}",
                        ",".join(row["revealed"]) if row["revealed"] else "",
                        f"{row['bonds_delta']:+d}",
                        f"{row['face_down_delta']:+d}",
                    ]
                    for row in shown
                ],
            )
        )
        if len(increases) > len(shown):
            lines.append("")
            lines.append(f"{len(increases) - len(shown)} further increases are in the JSON timeline.")
    repairs = focus["repair_attributions"]
    lines.append("")
    if repairs:
        lines.append(
            f"MEDIUM or HIGH backward attributions that repair column {focus['column']}: "
            + ", ".join(f"{item['id']} ({item['confidence']}, cost {item['repair_cost']})" for item in repairs[:12])
            + "."
        )
    else:
        lines.append(
            f"No MEDIUM or HIGH backward attribution names column {focus['column']} as the repaired column. "
            "That does not clear the column. It means the card-level rule did not tie a repair group to it."
        )
    worse = focus.get("first_materially_worse_horizon")
    if worse:
        lines.append("")
        lines.append(
            f"Column {focus['column']} is first materially worse than the reference at {worse['role']}: "
            f"disorder {worse['disorder_b']} versus {worse['disorder_a']}, "
            f"experimental debt {worse['debt_b']} versus {worse['debt_a']}."
        )
    shown_roles = {"pre-SD1", "pre-SD4", "post-SD5"}
    for share in focus.get("debt_concentration_b") or []:
        if share["role"] not in shown_roles or not share["debt_sum"]:
            continue
        lines.append("")
        lines.append(
            f"At {share['role']}, column {focus['column']} holds experimental debt {share['focus_debt']} "
            f"of the tableau sum {share['debt_sum']} (share of the experimental score {share['share_of_experimental_score']}). "
            f"Argmax column is {share['argmax_column']}. Vector: {share['vector']}. "
            "That share is not a share of the finished MW gap."
        )
    lines.append("")
    lines.append(focus.get("not_the_sole_cause") or (
        "The focus column is a liability to test. It is not, by this comparison alone, the sole cause of the finished gap."
    ))
    return "\n".join(lines)


def _rehandle_section(document: dict) -> str:
    rows = []
    for key, title in (("a", "A"), ("b", "B")):
        agg = document["trajectories"][key]["card_aggregates"]
        rows.append(
            [
                title,
                document["trajectories"][key]["label"],
                agg["total_card_handling_events"],
                agg["unique_cards_explicitly_handled"],
                agg["cards_moved_2plus"],
                agg["cards_moved_3plus"],
                agg["cards_moved_4plus"],
                agg["positive_cost_rehandle_card_events"],
                agg["zero_cost_card_moves"],
                agg["max_handles_on_one_card"],
            ]
        )
    most = []
    for key in ("a", "b"):
        label = document["trajectories"][key]["label"]
        for card in document["trajectories"][key]["card_aggregates"]["most_handled"][:5]:
            most.append([label, card["label"], card["handle_count"], card["positive_cost_rehandles"]])
    return (
        _table(
            ["route", "label", "handling events", "unique cards", "moved 2+", "moved 3+", "moved 4+", "positive rehandles", "zero-cost card moves", "max handles"],
            rows,
        )
        + "\n\nMost-handled cards, by deal-order identity:\n\n"
        + _table(["route", "card", "handles", "positive rehandles"], most)
        + "\n\n"
        + document["trajectories"]["a"]["card_aggregates"]["definition"]["counts_are_not_causes"] * ""
        + "These counts do not by themselves say which handling was necessary."
    )


def _park_section(document: dict) -> str:
    blocks = []
    for key in ("a", "b"):
        route = document["trajectories"][key]
        summary = route["park_summary"]
        blocks.append(
            f"**{route['label']}.** candidates {summary['candidates']}, "
            f"removed non-same-suit {summary['removed_non_same_suit']}, "
            f"HIGH {summary['high']}, MEDIUM {summary['medium']}, "
            f"LOW non-same-suit {summary['low_non_same_suit']}, "
            f"zero-cost whole-column relocations recorded {summary['zero_cost_whole_column_relocations']}."
        )
        interesting = [
            park
            for park in route["parks"]
            if park["confidence"] in ("HIGH", "MEDIUM") and park["contact"] != "same_suit" and park["removed_action"] is not None
        ][:12]
        if interesting:
            blocks.append("")
            blocks.append(
                _table(
                    ["id", "confidence", "contact", "cards", "from", "park", "created", "removed", "life", "deals", "create cost", "remove cost"],
                    [
                        [
                            park["id"],
                            park["confidence"],
                            park["contact"],
                            " ".join(park["cards"][:4]),
                            park["source_column"],
                            park["parking_column"],
                            park["created_action"],
                            park["removed_action"],
                            park["lifetime_actions"],
                            park["stock_deals_crossed"],
                            park["cost_to_create"],
                            park["removal_cost"],
                        ]
                        for park in interesting
                    ],
                )
            )
        blocks.append("")
    high_a = document["trajectories"]["a"]["park_summary"]["high"]
    high_b = document["trajectories"]["b"]["park_summary"]["high"]
    blocks.append(document["trajectories"]["a"]["park_summary"]["note"])
    if high_a >= 10 and high_b >= 10:
        blocks.append("")
        blocks.append(
            f"HIGH parks are common on both routes (A {high_a}, B {high_b}). "
            "A single HIGH park is a graded temporary placement, not a rare proof of a mistake."
        )
    return "\n".join(blocks)


def _workspace_section(document: dict) -> str:
    blocks = ["Components are listed separately. There is no workspace efficiency scalar.", ""]
    for key in ("a", "b"):
        route = document["trajectories"][key]
        summary = route["workspace_summary"]
        blocks.append(
            f"**{route['label']}.** episodes {summary['episodes']}, "
            f"acquired by play {summary['acquired_by_play']}, "
            f"sum of recorded acquisition costs {summary['acquisition_cost_sum']} "
            f"(a shared action that empties two columns is counted on each episode), "
            f"consumed {summary['consumed']}, consumed by a stock deal {summary['consumed_by_stock_deal']}, "
            f"consumed with a reveal {summary['consumed_with_reveal']}, "
            f"consumed with immediate benefit {summary['consumed_with_immediate_benefit']}, "
            f"recovered {summary['recovered']}, held until end {summary['held_until_end']}, "
            f"positive immediate unwind {summary['positive_unwind_episodes']}."
        )
        sample = [
            episode
            for episode in route["workspace_episodes"]
            if episode["filled_action"] is not None and episode["created_by"] != "opening"
        ][:8]
        if sample:
            blocks.append("")
            blocks.append(
                _table(
                    ["id", "column", "created", "acq cost", "held", "consumed by", "stock deal", "reveals", "benefit", "unwind", "recovered", "until recovery"],
                    [
                        [
                            episode["id"],
                            episode["column"],
                            episode["created_action"],
                            episode["acquisition_cost"],
                            episode["actions_held"],
                            episode["consumed_by"],
                            episode["consumed_by_stock_deal"],
                            len(episode["reveals_on_use"]),
                            episode["immediate_benefit"],
                            episode["immediate_unwind_cost"],
                            episode["recovered"],
                            episode["actions_until_recovery"],
                        ]
                        for episode in sample
                    ],
                )
            )
        blocks.append("")
    blocks.append(document["trajectories"]["a"]["workspace_summary"]["note"])
    return "\n".join(blocks)


def _forward_lines(findings: dict) -> list:
    lines = []
    opening = findings["opening"]
    if opening.get("available"):
        lines.append(
            f"Before SD1 the gap (B minus A) is {opening['g_gap_b_minus_a']} MW. "
            + (
                "B is ahead on cost at that boundary."
                if opening["g_gap_b_minus_a"] < 0
                else "B is not ahead on cost at that boundary."
            )
        )
    for row in findings["phase_gaps"]:
        if row["gap_contribution_b_minus_a"] == 0:
            continue
        direction = "more" if row["gap_contribution_b_minus_a"] > 0 else "fewer"
        lines.append(
            f"During {row['title']}, B spends {abs(row['gap_contribution_b_minus_a'])} MW {direction} than A. "
            f"At the end of the segment, experimental debt sums are {row['debt_sum_end_b']} (B) and {row['debt_sum_end_a']} (A); "
            f"positive-cost rehandle card-events to date are {row['rehandles_end_b']} and {row['rehandles_end_a']}."
        )
    lines.append(findings["gap_character"]["reason"])
    return lines


def _attribution_section(items: Sequence[dict], grade: str) -> str:
    if not items:
        return f"No {grade} backward attributions were retained in the report sample."
    blocks = [f"{grade} sample ({len(items)} shown):", ""]
    for item in items:
        blocks.append(
            f"- **{item['id']}** columns {item['columns']} cards {' '.join(item['cards'][:6])} "
            f"repair cost {item['repair_cost']} at actions {item['repair_actions'][:8]}. "
            f"Candidate cause: `{item['causal_canonical']}` ({item['causal_kind']}) "
            f"at action {item['causal_action']}. {item['reason']}"
        )
    return "\n".join(blocks)


def _seed_section(seeds: Sequence[dict]) -> str:
    if not seeds:
        return "No counterfactual seeds were recorded."
    blocks = []
    for seed in seeds[:6]:
        actual = seed["actual"]
        alternatives = ", ".join(
            f"`{row['canonical']}` (rank {row['immediate_rank']}, focus disorder {row['focus_disorder']}, debt sum {row['debt_sum']})"
            for row in seed["alternatives_better_on_immediate_sort"][:3]
        )
        blocks.append(
            f"- Action {seed['action_index']} `{actual['canonical']}` is immediate rank "
            f"{seed['actual_immediate_rank']} of {seed['n_legal']}. "
            f"Locally ordinary on the immediate sort: {seed['locally_ordinary_on_immediate_sort']}. "
            f"It bought class {seed['bought']['exclusive_class']}, cost {seed['bought']['cost']}, "
            f"reveals {seed['bought']['revealed'] or 'none'}, bonds {seed['bought']['bonds_delta']:+d}, "
            f"face-down {seed['bought']['face_down_delta']:+d}. "
            f"Why selected: {seed['why']}. Better immediate alternatives include {alternatives or 'none listed'}."
        )
    blocks.append("")
    blocks.append(seeds[0]["limit"])
    blocks.append(
        "A poor immediate rank is not evidence that the played move was a mistake. "
        "The sort is one ply. A reveal can rank worse because the newly exposed card raises column disorder, "
        "while an alternative that reveals nothing keeps the old top."
    )
    return "\n".join(blocks)


def _search_implications(findings: dict) -> list:
    opening = findings.get("opening") or {}
    zero = (opening.get("stats_b") or {}).get("zero_cost_details") or []
    if zero and all(not item["revealed"] for item in zero):
        zero_line = (
            "The opening zero-cost whole-column transfers on B reveal nothing. "
            "Preserve them as free rearrangement of already-built runs onto empty columns. "
            "Do not preserve them as free reveals."
        )
    else:
        zero_line = (
            "Keep zero-cost whole-column transfers that relocate a built run onto an empty column. "
            "They cost 0 under corrected MW."
        )
    lines = [
        zero_line,
        "Do not score a state by g alone once the stock is near empty. A route can be ahead on corrected MW while holding fewer same-suit bonds and a higher column-debt vector.",
        "Do not score a state by empty-column count or by the experimental debt sum alone. Both can disagree with the route that actually finishes cheaper.",
        "Add a column-disorder check before a stock deal: suit boundaries and rank discontinuities on the column that is about to receive a card, especially when the placement that raised them revealed nothing. The deal costs 1 either way; the top it lands on is the decision.",
        "Preserve physical-card identity inside diagnostics. Rank/suit notation collides on a two-deck deal and will mis-attribute rehandles.",
        "Backward repair links are evidence for which branch point to test. They are not yet a heuristic weight.",
        "Search changes wait on the bounded counterfactual in section 20. v0.105 does not change beam, DFS, UCS, A*, campaigns, or the principal-line policy.",
    ]
    ancestry = findings["divergence"]["ancestry"]
    if ancestry in (
        "different_early_ancestry",
        "shared_prefix_then_different_early_ancestry",
        "shared_prefix_then_diverged",
    ):
        lines.append(
            "The routes share only a short prefix, then different early ancestry. "
            "A solver that imitates the reference from the first action would discard the machine opening rather than repair its continuation. "
            "A shared solved terminal means both routes finished the deal. It does not mean the lines reconverged strategically."
        )
    return lines


def _metric_list(items: Sequence[dict]) -> str:
    return _bullets(f"**{item['metric']}.** {item['why']}" for item in items)


def _unknowns(findings: dict) -> list:
    focus = findings.get("focus_column")
    lines = [
        "Two complete routes cannot show that a different move at a seed would finish cheaper. That requires a bounded replay of the alternative.",
        "Park confidence is a documented heuristic. A HIGH park can still have been the cheapest way to expose a card. When both routes have many HIGH parks, the count is a weak discriminator.",
        "Exclusive cost classes hide mixed motives. A REVEAL bucket move may also have been the move that disordered a column.",
        "Post-stock column symmetry is an exact automorphism only after the stock is empty. It does not identify similar openings.",
        "The experimental debt score has not been calibrated against remaining MW. Agreement on this pair would still be one observation.",
    ]
    if focus:
        lines.append(
            f"Column {focus['column']} was the requested focus. "
            f"Verdict: {focus['reference_also_carries_this_column']['verdict']}. "
            "A hotter argmax column at a horizon is a competing hypothesis, not a refutation, until a counterfactual separates them."
        )
    hypothesis = findings["hypothesis_better_opening_worse_continuation"]
    if hypothesis.get("continuation") == "mixed":
        lines.append(
            "The better-opening / worse-continuation hypothesis is only partly supported. "
            "The opening cost is lower. The continuation contains both savings and extra cost. "
            "Two routes cannot show that the opening caused the later extra cost."
        )
    elif not hypothesis["supported"]:
        lines.append(
            "The better-opening / worse-continuation hypothesis is not supported strongly enough to treat it as architecture input without the numbers in section 3."
        )
    return lines
