"""Markdown report for one counterfactual continuation document."""

from __future__ import annotations

from .boundaries import disorder_without_readiness, structurally_promising


def render_report(document: dict) -> str:
    if document.get("mode") == "profile":
        return _render_profile(document)
    lines = [
        "# Counterfactual continuations v0.106",
        "",
        "Deal 4925153. The autonomous 185 is the baseline. The human 172 is a structural reference at the same stock horizon. It is not an ancestor of the machine states and it is not a template.",
        "",
        document.get("spec_note", ""),
        "",
        "## Baseline validation",
        "",
        "| Route | Corrected MW | Explicit actions | Solved | Foundations | Stock | Deals |",
        "|---|---:|---:|---|---:|---:|---:|",
    ]
    for label, row in (
        ("Human canonical", document["reference"]),
        ("Autonomous 185", document["baseline"]),
    ):
        lines.append(
            f"| {label} | {row['mobilityware_moves']} | {row['actions']} | "
            f"{'yes' if row['solved'] else 'no'} | {row['foundations']} | {row['stock_remaining']} | {row['stock_deals']} |"
        )
    lines.extend(
        [
            "",
            f"Local ceiling: {document['local_ceiling']}. {document['ceiling_rule']}",
            "",
            "## Policies",
            "",
        ]
    )
    for policy in document.get("policies", []):
        lines.append(f"- **{policy['name']}** ({policy['kind']}). {policy['summary']}")
    search = document.get("search", {})
    lines.extend(
        [
            "",
            "## Search",
            "",
            f"Kernel: `{search.get('kernel', '')}`.",
            "",
            search.get("root_worker", ""),
            "",
            search.get("candidate_screen", ""),
            "",
            search.get("stock_empty_worker_reason", ""),
            "",
            (
                f"Root worker limits: {search.get('time_limit_s')} s, "
                f"{search.get('max_unique')} unique states. "
                f"Candidate screen: width {search.get('candidate_width')}, "
                f"{search.get('candidate_time_s')} s, "
                f"{search.get('candidate_unique')} unique states. "
                f"Experiment B widen passes: {search.get('widen_passes_experiment_b')}."
            ),
            "",
            search.get("candidate_rank", ""),
            "",
            search.get("population", ""),
            "",
            "## Roots and results",
            "",
        ]
    )
    for experiment in document["experiments"]:
        lines.extend(_experiment_section(experiment))
    total, counts = _tally(document)
    count_text = ", ".join(f"{counts[name]} {name}" for name in sorted(counts))
    lines.extend(
        [
            "## Interpretation",
            "",
            f"Recorded searches: {total}. Status counts: {count_text}.",
            "",
        ]
    )
    for sentence in document.get("interpretation", []):
        lines.append(sentence)
        lines.append("")
    lines.extend(["## Limitations", ""])
    for item in document.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    return text


def _tally(document: dict) -> tuple:
    counts: dict = {}
    total = 0
    for experiment in document.get("experiments", []):
        for search in experiment.get("searches", []):
            total += 1
            status = search["status"]
            counts[status] = counts.get(status, 0) + 1
        for screen in experiment.get("candidate_screens", []):
            for batch in screen.get("batches", []):
                for row in batch.get("results", []):
                    total += 1
                    status = row["search"]["status"]
                    counts[status] = counts.get(status, 0) + 1
        for row in experiment.get("deep_searches") or []:
            if "search" not in row:
                continue
            total += 1
            status = row["search"]["status"]
            counts[status] = counts.get(status, 0) + 1
    return total, counts


def _experiment_section(experiment: dict) -> list:
    root = experiment["root"]
    lines = [
        f"### Experiment {experiment['name']} — {root['title']}",
        "",
        f"Priority: {experiment['priority']}. Phase: {root['phase']}. {root['saved_when']}.",
        "",
        (
            f"Action index {root['action_index']} (1-based). "
            f"Cumulative corrected MW {root['cumulative_g']}. "
            f"State `{root['state_hash']}`. "
            f"Stock rows {root['snapshot']['stock_rows_remaining']}. "
            f"Foundations {root['snapshot']['foundations']}. "
            f"Face-down {root['snapshot']['face_down']}. "
            f"Column {root['focus_column']} disorder {root['focus_disorder']} "
            f"(suit boundaries {root['focus_suit_boundaries']}, "
            f"rank breaks {root['focus_rank_discontinuities']}). "
            f"Column {root['focus_column']} experimental debt {root['focus_experimental_debt']}."
        ),
        "",
        (
            f"Original suffix: {root['suffix_count']} actions, "
            f"remaining corrected MW {root['suffix_remaining_mw']}. "
            f"Head: {', '.join(root.get('suffix_head', []))}."
        ),
        "",
    ]
    if root.get("g_before_this_deal") is not None:
        lines.append(
            f"Corrected MW before this deal: {root['g_before_this_deal']}. "
            f"Deal cost: {root['this_deal_cost']}. "
            f"Corrected MW after this deal: {root['cumulative_g']}."
        )
        lines.append("")
    horizon = experiment.get("stock_horizon")
    if horizon:
        lines.append(
            f"At this stock horizon the machine's corrected MW is {horizon['machine_g_after_deal']} "
            f"and the reference route's corrected MW is {horizon['reference_g_after_deal']}. "
            f"The machine is {horizon['machine_ahead_by']} corrected MW moves ahead. "
            f"Reference g before its own third deal is {horizon['reference_g_before_deal']}. "
            f"{horizon['note']}"
        )
        lines.append("")
    effect = root.get("original_action_effect")
    if effect:
        lines.append(
            f"Original next action `{effect['canonical']}` costs {effect['cost']}. "
            f"Column focus suit boundaries {effect['suit_boundaries_before']} to {effect['suit_boundaries_after']}. "
            f"Disorder {effect['disorder_before']} to {effect['disorder_after']}. "
            f"Same-suit bond change {effect['bonds_delta']}. "
            f"Face-down change {effect['face_down_delta']}."
        )
        lines.append("")
    lines.append(
        "Debt vector (experimental, diagnostic): "
        + ", ".join(str(score) for score in root["snapshot"]["experimental_debt_vector"])
        + f". Sum {root['snapshot']['experimental_debt_sum']}. "
        + f"Readiness n_ready {root['snapshot']['readiness_n_ready']}."
    )
    lines.append("")
    lines.append("Column layout, face-down then face-up, deal-order labels:")
    lines.append("")
    for column in root["snapshot"]["layout"]:
        down = " ".join(column["face_down"]) or "-"
        up = " ".join(column["face_up"]) or "-"
        lines.append(f"- Column {column['column']}: down [{down}] up [{up}]")
    lines.append("")
    lines.append(root["hypothesis"])
    lines.append("")
    lines.append("Root worker:")
    lines.append("")
    lines.append("| Policy | Status | Stop | Expanded | Unique | Seconds | Terminal g | Foundations seen |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for search in experiment["searches"]:
        probe = search["probe"]
        terminal = "" if search["terminal_g"] is None else str(search["terminal_g"])
        lines.append(
            f"| {search['policy']} | {search['status']} | {search['stop_reason']} | "
            f"{search['expanded']} | {search['unique']} | {search['elapsed_s']} | {terminal} | "
            f"{probe['max_foundations']} |"
        )
    lines.append("")
    for policy_name, ply in experiment["one_ply"].items():
        lines.append(
            f"One-ply {policy_name}: engine legal {ply['engine_legal']}, "
            f"policy allowed {ply['policy_allowed']}, hidden {ply['hidden_count']}. "
            f"Original action allowed: {ply['original_allowed']}. "
            f"Original rank: {ply['original_rank']}."
        )
        if ply["hidden_sample"]:
            lines.append("Hidden sample: " + ", ".join(ply["hidden_sample"]) + ".")
        lines.append("")
    for screen in experiment.get("candidate_screens", []):
        lines.append(
            f"Candidate screen {screen['policy']} via `{screen['rank_mode']}`: "
            f"enumerated tableau {screen['enumerated_tableau']}, "
            f"unique children {screen['unique_children']}, retained {screen['retained']}. "
            f"{screen['note']}"
        )
        lines.append("")
        lines.append("| Rank | First action | Cost | Boundary delta | Bonds delta | Face-down delta | Status | Stop |")
        lines.append("|---:|---|---:|---:|---:|---:|---|---|")
        for batch in screen["batches"]:
            for row in batch["results"]:
                search = row["search"]
                lines.append(
                    f"| {row['screen_rank']} | `{row['canonical']}` | {row['cost']} | "
                    f"{row['suit_boundary_delta']} | {row['bonds_delta']} | {row['face_down_delta']} | "
                    f"{search['status']} | {search['stop_reason']} |"
                )
        lines.append("")
    return lines


def build_answers(document: dict) -> dict:
    """Answer the v0.106 report questions from recorded results."""

    experiments = list(document.get("experiments") or [])
    by_name = {item.get("name"): item for item in experiments}
    outcome = _outcome(experiments)
    solved = [item for item in _every_search(experiments) if item.get("improves_on_baseline")]
    questions = [
        _q1(by_name.get("A")),
        _q2(experiments),
        _q3(experiments),
        _q4(experiments),
        _q5(by_name.get("B")),
        _q6(by_name.get("B"), solved),
        _q7(experiments, solved),
        _q8(solved),
        _q9(experiments),
        _q10(outcome, experiments, solved),
    ]
    return {
        "outcome": outcome,
        "questions": questions,
        "preserve": _preserve(document, experiments),
        "discourage": _discourage(solved, experiments),
        "unknown": _unknown(outcome, experiments),
        "causal": _causal(experiments, solved),
        "misleading": _misleading(experiments),
    }


def _render_profile(document: dict) -> str:
    # Recompute from the recorded boundaries. A stored answers block can be stale.
    answers = build_answers(document)
    git = document.get("git") or {}
    profile = document.get("profile") or {}
    resources = document.get("resource_settings") or {}
    lines = [
        "# Counterfactual continuations v0.106",
        "",
        "Deal 4925153. The autonomous 185 is the baseline. The human 172 is examined after ranking and is not used to choose candidates.",
        "",
        document.get("spec_note", ""),
        "",
        f"Branch `{git.get('branch', '')}`. HEAD `{git.get('head', '')}`.",
        "",
        "## Baseline validation",
        "",
        "| Route | Corrected MW | Explicit actions | SHA-256 |",
        "|---|---:|---:|---|",
    ]
    for label, row in (("Human canonical 172", document["reference"]), ("Autonomous 185", document["baseline"])):
        lines.append(
            f"| {label} | {row['mobilityware_moves']} | {row['actions']} | `{row.get('moves_sha256', '')}` |"
        )
    lines.extend(
        [
            "",
            f"Local ceiling: {document['local_ceiling']}. {document['ceiling_rule']}",
            "",
            "## Resources",
            "",
            (
                f"Profile `{profile.get('name', '')}`. Workers requested {resources.get('workers_requested', profile.get('workers_requested'))}, "
                f"workers used {resources.get('workers_used', 1)}. "
                f"Search width used {resources.get('search_width_used', 1)}. "
                f"Total seconds recorded {resources.get('elapsed_s')}. "
                f"Peak RSS MB {resources.get('peak_rss_mb')}."
            ),
            "",
            resources.get("workers_note", ""),
            "",
            resources.get("search_width_note", ""),
            "",
            "| Limit | Value |",
            "|---|---:|",
            f"| total_time_s per root | {profile.get('total_time_s')} |",
            f"| root_time_s | {profile.get('root_time_s')} |",
            f"| root_unique | {profile.get('root_unique')} |",
            f"| screen_time_s | {profile.get('screen_time_s')} |",
            f"| screen_unique | {profile.get('screen_unique')} |",
            f"| candidate_width | {profile.get('candidate_width')} |",
            f"| deep_survivors per policy | {profile.get('deep_survivors')} |",
            f"| deep_time_s | {profile.get('deep_time_s')} |",
            f"| deep_unique | {profile.get('deep_unique')} |",
            f"| max_depth | {profile.get('max_depth')} |",
            f"| rss_abort_mb | {profile.get('rss_abort_mb')} |",
            "",
            "## Policies",
            "",
        ]
    )
    for policy in document.get("policies") or []:
        lines.append(f"- **{policy['name']}** ({policy['kind']}). {policy['summary']}")
    lines.extend(["", f"Outcome: **{answers['outcome']}**.", ""])
    for experiment in document.get("experiments") or []:
        lines.extend(_profile_experiment(experiment))
    lines.extend(["## Answers", ""])
    for item in answers["questions"]:
        lines.append(f"### {item['number']}. {item['question']}")
        lines.append("")
        lines.append(item["answer"])
        lines.append("")
    lines.extend(["## Machine behaviour to preserve", ""])
    for item in answers["preserve"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Machine behaviour to discourage", ""])
    for item in answers["discourage"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Still unknown", ""])
    for item in answers["unknown"]:
        lines.append(f"- {item}")
    causal = answers.get("causal") or {}
    lines.extend(["", "## Causal labels", ""])
    for label in ("observed", "controlled", "inferred", "unresolved_hypothesis"):
        lines.append(f"### {label.replace('_', ' ')}")
        lines.append("")
        for item in causal.get(label) or []:
            lines.append(f"- {item}")
        if not causal.get(label):
            lines.append("- None recorded.")
        lines.append("")
    lines.extend(["## Where structural metrics misled", ""])
    for item in answers.get("misleading") or []:
        lines.append(f"- {item}")
    if not answers.get("misleading"):
        lines.append("- None recorded.")
    lines.extend(["", "## Endgame", ""])
    endgames = [item for item in _every_search(document.get("experiments") or []) if item.get("status") == "SOLVED_VALID"]
    if not endgames:
        lines.append("No fully solved alternative was generated.")
        lines.append("")
    for search in endgames:
        replay = search.get("replay") or {}
        lines.append(
            f"- Policy {search.get('policy')} role {search.get('role')}: "
            f"final corrected MW {replay.get('total_mw', search.get('terminal_g'))}, "
            f"explicit actions {replay.get('explicit_actions', 'recorded on the replay')}, "
            f"foundations {replay.get('foundations')}, "
            f"valid {replay.get('ok')}, "
            f"deviation from 185 {search.get('improvement_vs_baseline')}, "
            f"accepted by {search.get('accepted_by')}."
        )
    lines.extend(["", "## Interpretation", ""])
    total, counts = _tally(document)
    count_text = ", ".join(f"{counts[name]} {name}" for name in sorted(counts))
    lines.append(f"Recorded searches: {total}. Status counts: {count_text}.")
    lines.append("")
    for sentence in document.get("interpretation") or []:
        lines.append(sentence)
        lines.append("")
    lines.extend(["## Limitations", ""])
    for item in document.get("limitations") or []:
        lines.append(f"- {item}")
    lines.append("")
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    return text


def _profile_experiment(experiment: dict) -> list:
    root = experiment["root"]
    lines = [
        f"## Experiment {experiment['name']} — {root['title']}",
        "",
        (
            f"Root `{experiment.get('root_key', '')}`. Phase {root['phase']}. "
            f"Action index {root['action_index']}. Cumulative corrected MW {root['cumulative_g']}. "
            f"State `{root['state_hash']}`. "
            f"Column {root['focus_column']} disorder {root['focus_disorder']}. "
            f"Elapsed {experiment.get('elapsed_s')} s of a {experiment.get('budget_s')} s budget."
        ),
        "",
    ]
    horizon = experiment.get("stock_horizon")
    if horizon:
        lines.append(
            f"After this route's own third deal the corrected MW is {horizon['machine_g_after_deal']} "
            f"(before the deal {horizon['machine_g_before_deal']}). "
            f"The reference route at its own third deal is {horizon['reference_g_after_deal']} "
            f"(before the deal {horizon['reference_g_before_deal']}). "
            f"The machine is ahead by {horizon['machine_ahead_by']}. {horizon['note']}"
        )
        lines.append("")
    lines.extend(
        [
            "### Policy comparison at this root",
            "",
            "| Policy | Stage | Status | Stop | Expanded | Unique | Seconds | Terminal g | Foundations seen | Immediate deal |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in experiment.get("comparisons") or []:
        if row.get("stage") not in ("root", "known-line", "deep"):
            continue
        effort = row.get("effort") or {}
        probe = row.get("probe") or {}
        lines.append(
            f"| {row.get('policy')} | {row.get('stage')} | {row.get('status')} | {row.get('stop_reason', '')} | "
            f"{effort.get('expanded', '')} | {effort.get('unique', '')} | {effort.get('elapsed_s', '')} | "
            f"{'' if row.get('terminal_g') is None else row.get('terminal_g')} | "
            f"{probe.get('max_foundations', '')} | {row.get('immediate_deal')} |"
        )
    lines.extend(
        [
            "",
            "### Next stock boundary",
            "",
            "Deal-now is a legal boundary and is not a prepared tableau. A lower g on an immediate deal is the cost of dealing, not a better solution.",
            "",
            "| Policy | Stage | Kind | g | g since root | Face-down | Foundations | Bonds | Empty | Disorder | Rehandles | Deal legal | Debt moved to 7 or 8 |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in experiment.get("comparisons") or []:
        boundary = row.get("boundary") or {}
        if row.get("policy") == "REFERENCE_SUFFIX" or row.get("stage") in ("root", "deep"):
            lines.append(_boundary_line(row.get("policy"), row.get("stage"), boundary, row))
    lines.extend(["", "### Screen and deep effort", ""])
    lines.append("| Policy | Stage | First action | Status | Stop | Expanded | Unique | Seconds | Planned unique |")
    lines.append("|---|---|---|---|---|---:|---:|---:|---:|")
    for screen in experiment.get("candidate_screens") or []:
        for batch in screen.get("batches") or []:
            for row in batch.get("results") or []:
                search = row["search"]
                effort = search.get("effort") or {}
                planned = search.get("planned") or {}
                lines.append(
                    f"| {screen['policy']} | screen | `{row['canonical']}` | {search.get('status')} | "
                    f"{search.get('stop_reason')} | {effort.get('expanded', '')} | {effort.get('unique', '')} | "
                    f"{effort.get('elapsed_s', '')} | {planned.get('max_unique', '')} |"
                )
    for row in experiment.get("deep_searches") or []:
        search = row["search"]
        effort = search.get("effort") or {}
        planned = search.get("planned") or {}
        lines.append(
            f"| {row['policy']} | deep | `{row['canonical']}` | {search.get('status')} | "
            f"{search.get('stop_reason')} | {effort.get('expanded', '')} | {effort.get('unique', '')} | "
            f"{effort.get('elapsed_s', '')} | {planned.get('max_unique', '')} |"
        )
    lines.append("")
    promising = [
        row
        for row in experiment.get("comparisons") or []
        if structurally_promising(row.get("boundary"), experiment.get("original_boundary"))
    ]
    if promising:
        lines.append("**Structurally promising, terminal value unresolved.**")
        lines.append("")
        for row in promising:
            lines.append(f"- {row.get('name')}: {row.get('structural_label')}")
        lines.append("")
    moved = [row for row in experiment.get("comparisons") or [] if row.get("debt_moved_to_column_7_or_8")]
    if moved:
        lines.append("Observed focus-debt drop with a rise in column 7 or 8:")
        lines.append("")
        for row in moved:
            lines.append(f"- {row.get('name')}. This is a vector change, not a terminal-cost result.")
        lines.append("")
    return lines


def _boundary_line(policy, stage, boundary: dict, row: dict) -> str:
    if not boundary or boundary.get("kind") == "original_suffix_never_dealt":
        return f"| {policy} | {stage} | none |  |  |  |  |  |  |  |  |  | {row.get('debt_moved_to_column_7_or_8')} |"
    return (
        f"| {policy} | {stage} | {boundary.get('label') or boundary.get('kind')} | "
        f"{boundary.get('cumulative_g', '')} | {boundary.get('g_since_root', '')} | "
        f"{boundary.get('face_down', '')} | {boundary.get('foundations', '')} | "
        f"{boundary.get('same_suit_bonds', '')} | {boundary.get('empty_columns', '')} | "
        f"{boundary.get('focus_disorder', '')} | {boundary.get('rehandle_card_events', '')} | "
        f"{boundary.get('deal_legal', '')} | {row.get('debt_moved_to_column_7_or_8')} |"
    )


def _n(value, singular: str, plural: str | None = None) -> str:
    count = int(value or 0)
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


def _outcome(experiments: list) -> str:
    if any(item.get("improves_on_baseline") for item in _every_search(experiments)):
        return "Positive"
    promising = any(
        structurally_promising(row.get("boundary"), experiment.get("original_boundary"))
        for experiment in experiments
        for row in experiment.get("comparisons") or []
        if row.get("policy") != "REFERENCE_SUFFIX"
    )
    if promising:
        return "Mixed"
    exhausted = any(
        search.get("policy") == "C0" and search.get("status") == "EXHAUSTED"
        for experiment in experiments
        for search in experiment.get("searches") or []
    )
    if exhausted:
        return "Negative"
    return "Inconclusive"


def _q1(experiment) -> dict:
    question = "Could the column-4 intervention at action 25 preserve the economical opening?"
    if experiment is None:
        return {"number": 1, "question": question, "answer": "Experiment A was not part of this run."}
    root = experiment["root"]
    effect = root.get("original_action_effect") or {}
    hidden = []
    for name in ("C1", "A-suppress"):
        ply = (experiment.get("one_ply") or {}).get(name) or {}
        if ply:
            hidden.append(
                f"{name} hid {_n(ply.get('hidden_count'), 'action')} and left "
                f"{_n(ply.get('policy_allowed'), 'legal action', 'legal actions')}"
            )
    free = []
    for search in _experiment_searches(experiment):
        continuation = search.get("continuation") or []
        if search.get("status") == "SOLVED_VALID" and all(
            move in continuation for move in ("move 8 3 1", "move 9 8 4", "move 6 9 6")
        ):
            free.append(search.get("policy"))
    boundary = experiment.get("original_boundary") or {}
    if free:
        answer = (
            f"A verified continuation from before action 25 still contained the three zero-cost "
            f"whole-column moves under {', '.join(free)}. "
            f"The recorded action `{effect.get('canonical')}` costs {effect.get('cost')} and changes "
            f"column-4 suit boundaries from {effect.get('suit_boundaries_before')} to {effect.get('suit_boundaries_after')}."
        )
    else:
        answer = (
            f"The recorded action `{effect.get('canonical')}` costs {effect.get('cost')} and changes "
            f"column-4 suit boundaries from {effect.get('suit_boundaries_before')} to {effect.get('suit_boundaries_after')}. "
            f"On the verified 185 the next stock boundary after this root is at corrected MW {boundary.get('cumulative_g')} "
            f"({boundary.get('g_since_root')} since the root, {boundary.get('action_count')} actions). "
            + ("; ".join(hidden) + ". " if hidden else "")
            + "No verified continuation showed those three zero-cost moves surviving an intervention. "
            "The restrictions left other legal moves in place, so they did not by themselves discard the opening. "
            "Preservation is unresolved."
        )
    return {"number": 1, "question": question, "answer": answer}


def _q2(experiments: list) -> dict:
    question = "Did the intervention avoid debt or merely move it?"
    moved = []
    prepared = []
    for experiment in experiments:
        for row in experiment.get("comparisons") or []:
            if row.get("policy") == "REFERENCE_SUFFIX":
                continue
            boundary = row.get("boundary") or {}
            if row.get("debt_moved_to_column_7_or_8") and not boundary.get("immediate_deal"):
                moved.append(f"{experiment.get('name')} {row.get('name')}")
            if boundary and not boundary.get("immediate_deal") and row.get("stage") != "known-line":
                prepared.append(row.get("name"))
    if moved:
        answer = (
            "Observed: focus debt fell while column 7 or 8 rose on "
            + ", ".join(moved)
            + ". That is a transfer of the diagnostic vector. It is not a terminal-cost result."
        )
    elif not prepared:
        answer = (
            "The bounded searches' stock boundaries were immediate deals, or no non-deal boundary was retained. "
            "An immediate deal does not show whether column-4 debt was avoided or relocated. "
            "The question is unresolved."
        )
    else:
        answer = (
            "Prepared boundaries were retained and none of them combined a focus-debt drop with a rise in column 7 or 8. "
            "That does not show the debt was eliminated. No verified cheaper ending identifies where the cost went."
        )
    return {"number": 2, "question": question, "answer": answer}


def _q3(experiments: list) -> dict:
    question = "Did the restriction sacrifice valuable reveals, compression, or workspace?"
    notes = []
    for experiment in experiments:
        c0 = (experiment.get("one_ply") or {}).get("C0") or {}
        c1 = (experiment.get("one_ply") or {}).get("C1") or {}
        if not c1:
            continue
        notes.append(
            f"Experiment {experiment.get('name')}: C0 allowed {c0.get('policy_allowed')} and C1 allowed {c1.get('policy_allowed')} "
            f"of {c1.get('engine_legal')} engine-legal actions. Hidden: {', '.join(c1.get('hidden_sample') or []) or 'none'}."
        )
    answer = " ".join(notes) + (
        " The hidden actions stay legal in the engine. Deal stays available. "
        "No pair of finished solutions separates a sacrificed reveal from an unused one. "
        "A terminal sacrifice is unresolved."
    )
    return {"number": 3, "question": question, "answer": answer.strip()}


def _q4(experiments: list) -> dict:
    question = "How did hard restriction compare with soft preference?"
    parts = []
    for experiment in experiments:
        rows = {}
        for search in experiment.get("searches") or []:
            if search.get("policy") in ("C0", "C1", "C2"):
                effort = search.get("effort") or {}
                probe = search.get("probe") or {}
                rows[search["policy"]] = (
                    f"{search.get('status')} in {effort.get('elapsed_s')} s, "
                    f"expanded {effort.get('expanded')}, unique {effort.get('unique')}, "
                    f"foundations seen {probe.get('max_foundations')}, "
                    f"minimum focus boundaries seen {probe.get('min_focus_suit_boundaries_seen')}"
                )
        if rows:
            rendered = "; ".join(f"{name}: {rows[name]}" for name in ("C0", "C1", "C2") if name in rows)
            parts.append(f"Experiment {experiment.get('name')} root workers, same planned stage budget. {rendered}.")
    if not parts:
        answer = "Hard and soft policies were not both run at a shared root."
    else:
        answer = " ".join(parts) + " Equal corrected MW remains the primary key. The soft key does not remove moves."
    return {"number": 4, "question": question, "answer": answer}


def _q5(experiment) -> dict:
    question = "Could the post-SD3 state produce a cheaper continuation?"
    if experiment is None:
        return {"number": 5, "question": question, "answer": "Experiment B was not part of this run."}
    solved = [item for item in _experiment_searches(experiment) if item.get("improves_on_baseline")]
    if solved:
        bits = ", ".join(
            f"{item.get('policy')} replayed to {item.get('terminal_g')}" for item in solved
        )
        answer = f"Yes. {bits}. The replay is from the untouched deal."
    else:
        root_c0 = next((item for item in experiment.get("searches") or [] if item.get("policy") == "C0"), None)
        if root_c0 and root_c0.get("status") == "EXHAUSTED":
            answer = (
                "The unmodified root worker exhausted its tree under the ceiling. "
                "No cheaper continuation exists from this post-SD3 state under that contract."
            )
        else:
            answer = (
                "No replay-verified continuation below 185 was produced from the post-SD3 state. "
                "The searches that stopped on a budget remain unresolved rather than disproven."
            )
    return {"number": 5, "question": question, "answer": answer}


def _q6(experiment, solved: list) -> dict:
    question = "Did the original 27-move lead contain recoverable value?"
    if experiment is None:
        return {"number": 6, "question": question, "answer": "The post-SD3 root was not run, so the lead was not tested."}
    horizon = experiment.get("stock_horizon") or {}
    ahead = horizon.get("machine_ahead_by")
    if any(item.get("improves_on_baseline") for item in _experiment_searches(experiment)):
        answer = (
            f"The verified routes differ by {ahead} corrected MW at this stock horizon. "
            "A complete continuation from that state finished below 185, so some of the lead was recovered in a replayed line."
        )
    else:
        answer = (
            f"At this stock horizon the machine's corrected MW is {horizon.get('machine_g_after_deal')} and the reference is "
            f"{horizon.get('reference_g_after_deal')}, a lead of {ahead}. "
            "The lead is a measurement on the verified routes. This run did not convert it into a finished total below 185. "
            "Whether it is recoverable remains unresolved."
        )
    return {"number": 6, "question": question, "answer": answer}


def _q7(experiments: list, solved: list) -> dict:
    question = "Which intermediate structural measurements predicted eventual success or failure?"
    if not solved:
        mismatch = _misleading(experiments)
        extra = ""
        if mismatch:
            extra = " " + mismatch[0]
        answer = (
            "No verified solution below 185 was available to test a predictor. "
            "Column-4 disorder, same-suit bonds, face-down count, and the diagnostic debt vector were recorded. "
            "None is confirmed here as an early-warning signal of eventual cost. "
            "A lower focus-boundary count inside a budget is a search observation, not a prediction."
            + extra
        )
    else:
        answer = (
            "A verified cheaper line exists. Its terminal corrected MW is the result that matters. "
            "Intermediate disorder on that line is a description of the route, not proof that tidiness caused the saving."
        )
    return {"number": 7, "question": question, "answer": answer}


def _q8(solved: list) -> dict:
    question = "Did any intervention produce a valid solution below 185?"
    if not solved:
        answer = "No intervention produced a replay-verified solution at corrected MW 184 or below."
    else:
        bits = []
        for item in solved:
            replay = item.get("replay") or {}
            bits.append(
                f"{item.get('policy')} ({item.get('accepted_by') or item.get('role')}) "
                f"replayed to {replay.get('total_mw', item.get('terminal_g'))} with replay ok {replay.get('ok')}"
            )
        answer = "Yes. " + "; ".join(bits) + "."
    return {"number": 8, "question": question, "answer": answer}


def _q9(experiments: list) -> dict:
    question = "Which candidates remain unresolved rather than disproven?"
    counts = {}
    for search in _every_search(experiments):
        status = search.get("status") or "ERROR"
        counts[status] = counts.get(status, 0) + 1
    unresolved = {name: counts.get(name, 0) for name in ("TIME_LIMIT", "NODE_LIMIT", "MEMORY_LIMIT")}
    exhausted = counts.get("EXHAUSTED", 0)
    rendered = ", ".join(f"{name} {unresolved[name]}" for name in sorted(unresolved))
    answer = (
        f"Unresolved budgets: {rendered}. "
        f"EXHAUSTED {exhausted}. EXHAUSTED is disproven only inside the stated contract, and a C1 exhaustion does not show that a hidden move was required. "
        "TIME_LIMIT is not EXHAUSTED. A low heuristic rank is not a hopeless label."
    )
    return {"number": 9, "question": question, "answer": answer}


def _q10(outcome: str, experiments: list, solved: list) -> dict:
    question = "What, specifically, should the next solver learn from the evidence?"
    if outcome == "Positive":
        answer = (
            "A replayed line below 185 exists. Learn that route's moves, then test whether the saving survives a fresh search. "
            "Do not turn the result into a rule that every column should stay tidy."
        )
    elif outcome == "Negative":
        answer = (
            "Under the stated ceiling the unmodified tree from a tested root contained no cheaper solution. "
            "That is evidence about those roots and that contract. It is not a reason to punish temporary disorder in general."
        )
    elif outcome == "Mixed":
        answer = (
            "At least one unfinished branch looked structurally better on a recorded signal and still had no verified cheaper ending. "
            "Do not optimise the experimental debt score. Terminal corrected MW remains the objective."
        )
    else:
        answer = (
            "Best-g search meets an immediate legal deal before it can imitate the 185's longer preparation for the next deal. "
            "A useful next test has to spend tableau moves before dealing, or it has to notice an exact later state of a verified route. "
            "Column-4 disorder was not shown to be an early-warning signal of terminal cost, and it was not shown to be irrelevant. "
            "Do not add a heuristic whose job is to keep every column tidy."
        )
    return {"number": 10, "question": question, "answer": answer}


def _preserve(document: dict, experiments: list) -> list:
    items = [
        "Corrected MobilityWare accounting, including a zero cost for relocating an entire column onto an empty column.",
        "Unrestricted Deal. Every policy in this experiment leaves Deal available, including when a column is empty.",
    ]
    baseline = document.get("baseline") or {}
    if baseline.get("mobilityware_moves") == 185:
        items.append(
            "The verified 185's opening economy and its three zero-cost whole-column moves. "
            "This run did not produce a finished line that shows those moves are harmful."
        )
    return items


def _discourage(solved: list, experiments: list) -> list:
    if solved:
        return [
            "No general tidy-column rule. The cheaper verified line is evidence about cost, not about making every column neat."
        ]
    return [
        "None. The bounded searches did not show an expensive structural pattern that a verified alternative avoided."
    ]


def _misleading(experiments: list) -> list:
    items = []
    for experiment in experiments:
        original = experiment.get("original_boundary") or {}
        rows = [
            row
            for row in experiment.get("comparisons") or []
            if row.get("policy") != "REFERENCE_SUFFIX"
            and disorder_without_readiness(row.get("boundary"), original)
        ]
        if not rows:
            continue
        disorders = [int(row["boundary"]["focus_disorder"]) for row in rows]
        bonds = [int(row["boundary"]["same_suit_bonds"]) for row in rows]
        face_down = [int(row["boundary"].get("face_down") or 0) for row in rows]
        spent = [int(row["boundary"].get("g_since_root") or 0) for row in rows]
        items.append(
            f"Experiment {experiment.get('name')}: {len(rows)} retained boundaries had column-4 disorder "
            f"{min(disorders)}–{max(disorders)} against the 185 suffix boundary's {original.get('focus_disorder')}, "
            f"but same-suit bonds were {min(bonds)}–{max(bonds)} against {original.get('same_suit_bonds')} "
            f"and face-down cards were {min(face_down)}–{max(face_down)} against {original.get('face_down')}. "
            f"Those searches spent {min(spent)}–{max(spent)} corrected MW to the deal; "
            f"the 185 suffix spends {original.get('g_since_root')}. "
            "Lower disorder here is not structural readiness."
        )
    return items


def _unknown(outcome: str, experiments: list) -> list:
    items = []
    if outcome != "Positive":
        items.append("Whether any complete continuation from these roots costs less than 185 corrected MW.")
    items.append("Whether column-4 disorder is an early-warning signal of eventual cost or a correlate of other structure.")
    items.append("Whether the action-25 placement avoids later cost, creates it, or only moves the diagnostic vector.")
    items.append("Whether the post-SD3 lead of 27 corrected MW can be converted into a lower finished total.")
    if any(search.get("status") in {"TIME_LIMIT", "NODE_LIMIT", "MEMORY_LIMIT"} for search in _every_search(experiments)):
        items.append("The terminal value of every candidate that stopped on time, nodes, or memory.")
    return items


def _causal(experiments: list, solved: list) -> dict:
    observed = []
    controlled = []
    for experiment in experiments:
        root = experiment.get("root") or {}
        effect = root.get("original_action_effect")
        if effect:
            observed.append(
                f"Experiment {experiment.get('name')}: `{effect.get('canonical')}` changed column-4 suit boundaries "
                f"from {effect.get('suit_boundaries_before')} to {effect.get('suit_boundaries_after')} at cost {effect.get('cost')}."
            )
        for row in experiment.get("comparisons") or []:
            if row.get("immediate_deal") and row.get("stage") == "root":
                observed.append(
                    f"Experiment {experiment.get('name')} {row.get('policy')} root search recorded an immediate deal as a stock boundary."
                )
        names = []
        for search in experiment.get("searches") or []:
            effort = search.get("effort") or {}
            names.append(f"{search.get('policy')} {search.get('status')} unique {effort.get('unique')}")
        if names:
            controlled.append(
                f"Experiment {experiment.get('name')} compared policies from one packed state under one stage budget: "
                + "; ".join(names)
                + "."
            )
    unresolved = [
        "A definite terminal-cost saving cannot be attributed to an intervention without a verified complete alternative."
    ]
    if not solved:
        unresolved.append("No such alternative was verified in this run.")
    inferred = []
    if not solved:
        inferred.append(
            "No inferred causal claim about the 13-move gap is made from an unfinished branch."
        )
    return {
        "observed": observed,
        "controlled": controlled,
        "inferred": inferred,
        "unresolved_hypothesis": unresolved,
    }


def _every_search(experiments: list):
    for experiment in experiments:
        yield from _experiment_searches(experiment)


def _experiment_searches(experiment: dict):
    for search in experiment.get("searches") or []:
        yield search
    for screen in experiment.get("candidate_screens") or []:
        for batch in screen.get("batches") or []:
            for row in batch.get("results") or []:
                yield row["search"]
    for row in experiment.get("deep_searches") or []:
        if "search" in row:
            yield row["search"]

