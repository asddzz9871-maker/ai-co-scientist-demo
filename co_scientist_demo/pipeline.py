from __future__ import annotations

import json
from pathlib import Path

from .models import (
    ROLES,
    BranchDraft,
    DecisionTrace,
    DemoCase,
    ExperimentDesignReview,
    ExperimentMatrix,
    MeetingQA,
    MeetingSynthesis,
    NextRoundAdvice,
    QAFinding,
    ResultFeedback,
    RunStatus,
)


ROLE_MANDATES = {
    "PI": "Frame the question, weigh competing proposals, and state a bounded decision.",
    "Critic": "Find missing controls, weak provenance, and claims that exceed the evidence.",
    "SynthesisAssistant": "Assess route feasibility and identify parameters requiring human review.",
    "CharacterizationAssistant": "Specify measurements that could discriminate between alternatives.",
}


def review_meeting(case: DemoCase) -> MeetingQA:
    findings: list[QAFinding] = []

    def flag(code: str, target: str, reason: str) -> None:
        findings.append(QAFinding(code=code, target=target, reason=reason))

    evidence_ids = [card.id for card in case.evidence]
    known_evidence = set(evidence_ids)
    if not evidence_ids or len(evidence_ids) != len(known_evidence):
        flag("EVIDENCE_IDS", "evidence", "Evidence IDs must be present and unique.")
    for card in case.evidence:
        if not card.source_ref.startswith("demo://") or not card.claim.strip():
            flag("SOURCE", card.id, "Demo evidence needs a synthetic source locator and claim.")

    report_roles = [report.role for report in case.pre_meeting]
    if sorted(report_roles) != sorted(ROLES):
        flag("ROLE_COVERAGE", "pre_meeting", "Each role needs one independent report.")
    for report in case.pre_meeting:
        if not report.assessment.strip() or not report.concern.strip():
            flag("ROLE_CONTENT", report.role, "Assessment and concern are both required.")
        if not report.evidence_ids or not set(report.evidence_ids) <= known_evidence:
            flag("ROLE_EVIDENCE", report.role, "Report must cite known EvidenceCard IDs.")

    branch_ids = [branch.branch_id for branch in case.branches]
    if len(branch_ids) < 2 or len(branch_ids) != len(set(branch_ids)):
        flag("BRANCH_COVERAGE", "branches", "At least two distinct branches are required.")
    for branch in case.branches:
        _review_branch(branch, known_evidence, flag)

    return MeetingQA(
        approved=not findings,
        findings=findings,
        reviewed_branch_ids=branch_ids,
    )


def _review_branch(branch: BranchDraft, known_evidence: set[str], flag) -> None:
    roles = [turn.role for turn in branch.turns]
    speakers = {"SynthesisAssistant", "CharacterizationAssistant", "Critic"}
    if len(roles) != 5 or roles[0] != "PI" or roles[-1] != "PI" or set(roles[1:4]) != speakers:
        flag("BRANCH_ROLES", branch.branch_id, "Branch needs PI opening/decision and one turn from each other role.")
    for turn in branch.turns:
        if not turn.statement.strip() or not set(turn.evidence_ids) <= known_evidence:
            flag("TURN_EVIDENCE", branch.branch_id, "Turn is empty or cites an unknown source.")
    if branch.fallback_used:
        flag("FALLBACK", branch.branch_id, "A fallback branch cannot pass QA.")
    if not branch.accepted_decisions:
        flag("DECISION", branch.branch_id, "No accepted decision was recorded.")
    if not branch.rejected_ideas or any(
        not item.idea.strip() or not item.reason.strip() for item in branch.rejected_ideas
    ):
        flag("REJECTION", branch.branch_id, "Record an idea rejected with a reason.")
    if not branch.open_questions:
        flag("OPEN_QUESTION", branch.branch_id, "Record an unresolved question.")
    if not branch.cited_evidence_ids or not set(branch.cited_evidence_ids) <= known_evidence:
        flag("BRANCH_EVIDENCE", branch.branch_id, "Branch must cite known EvidenceCard IDs.")


def review_design(branch: BranchDraft) -> ExperimentDesignReview:
    candidate = branch.candidate
    findings: list[QAFinding] = []
    if not candidate.controls:
        findings.append(QAFinding(code="DESIGN_CONTROLS", target=candidate.id, reason="A comparison needs controls."))
    if not candidate.measurements:
        findings.append(QAFinding(code="DESIGN_READOUTS", target=candidate.id, reason="A comparison needs measurements."))
    if not candidate.decision_rule.strip():
        findings.append(QAFinding(code="DESIGN_RULE", target=candidate.id, reason="A comparison needs a decision rule."))
    if not branch.cited_evidence_ids:
        findings.append(QAFinding(code="DESIGN_BASIS", target=candidate.id, reason="The plan needs source evidence IDs."))
    return ExperimentDesignReview(approved=not findings, findings=findings, candidate_id=candidate.id)


def synthesize(case: DemoCase, meeting_qa: MeetingQA) -> MeetingSynthesis:
    decision_sets = [set(branch.accepted_decisions) for branch in case.branches]
    consensus = set.intersection(*decision_sets) if decision_sets else set()
    all_decisions = set.union(*decision_sets) if decision_sets else set()
    rejected = {
        (item.idea, item.reason): item
        for branch in case.branches
        for item in branch.rejected_ideas
    }
    return MeetingSynthesis(
        consensus=sorted(consensus),
        disputes=sorted(all_decisions - consensus),
        rejected_ideas=list(rejected.values()),
        open_questions=sorted({q for branch in case.branches for q in branch.open_questions}),
        candidate_ids=[branch.candidate.id for branch in case.branches],
        status="PASS" if meeting_qa.approved else "BLOCKED",
    )


def run_case(case: DemoCase, output_dir: Path) -> RunStatus:
    """Replay typed role outputs and enforce the same stage order on every run."""
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_dir}")
    if case.experimental_result is not None:
        expected_id = f"experiment-{case.researcher_selected_candidate_id}"
        if case.experimental_result.experiment_id != expected_id:
            raise ValueError("ExperimentalResult must refer to the selected experiment.")
        if not case.experimental_result.source_ref.startswith("demo://"):
            raise ValueError("Demo ExperimentalResult needs a synthetic source locator.")
    output_dir.mkdir(parents=True, exist_ok=True)
    _write(output_dir / "EvidenceCards.json", [card.model_dump() for card in case.evidence])
    _write(output_dir / "Role_Briefs.json", ROLE_MANDATES)
    _write(output_dir / "PreMeetingReports.json", [report.model_dump() for report in case.pre_meeting])
    _write(output_dir / "BranchArtifacts.json", [branch.model_dump() for branch in case.branches])

    meeting_qa = review_meeting(case)
    synthesis = synthesize(case, meeting_qa)
    _write(output_dir / "Meeting_QA.json", meeting_qa.model_dump())
    _write(output_dir / "MeetingSynthesis.json", synthesis.model_dump())

    blocker_codes = [finding.code for finding in meeting_qa.findings]
    candidate_by_id = {branch.candidate.id: branch for branch in case.branches}
    if len(candidate_by_id) != len(case.branches):
        blocker_codes.append("CANDIDATE_IDS")
    selected = case.researcher_selected_candidate_id
    if selected is not None and selected not in candidate_by_id:
        blocker_codes.append("SELECTION")

    final_gate_passed = meeting_qa.approved and not blocker_codes
    if final_gate_passed and selected is not None:
        design_review = review_design(candidate_by_id[selected])
        _write(output_dir / "ExperimentDesignReview.json", design_review.model_dump())
        blocker_codes.extend(finding.code for finding in design_review.findings)

    if blocker_codes:
        handoff_status = "BLOCKED"
    elif selected is None:
        handoff_status = "AWAITING_SELECTION"
    else:
        handoff_status = "COMPILED"

    status = RunStatus(
        case_id=case.case_id,
        meeting_qa_passed=meeting_qa.approved,
        final_gate_passed=final_gate_passed,
        handoff_status=handoff_status,
        blocker_codes=sorted(set(blocker_codes)),
    )
    _write(output_dir / "RunStatus.json", status.model_dump())

    experiment: ExperimentMatrix | None = None
    if handoff_status == "COMPILED":
        selected_branch = candidate_by_id[selected]
        candidate = selected_branch.candidate
        experiment = ExperimentMatrix(
            experiment_id=f"experiment-{candidate.id}",
            candidate_id=candidate.id,
            controls=candidate.controls,
            measurements=candidate.measurements,
            decision_rule=candidate.decision_rule,
            evidence_ids=selected_branch.cited_evidence_ids,
        )
        advice = NextRoundAdvice(
            action=f"Researcher review and, if appropriate, execute {experiment.experiment_id}.",
            basis=[candidate.route_label, candidate.decision_rule],
            evidence_ids=experiment.evidence_ids,
            unresolved_questions=synthesis.open_questions,
        )
        _write(output_dir / "ExperimentMatrix.json", experiment.model_dump())
        _write(output_dir / "NextRoundAdvice.json", advice.model_dump())

    if case.experimental_result is not None and experiment is not None:
        feedback = ResultFeedback(
            experiment_id=experiment.experiment_id,
            observation=case.experimental_result.observation,
            source_ref=case.experimental_result.source_ref,
        )
        _write(output_dir / "ResultFeedback.json", feedback.model_dump())

    trace = DecisionTrace(
        source_evidence_ids=[card.id for card in case.evidence],
        meeting_draft_ids=[branch.branch_id for branch in case.branches],
        selected_candidate_id=selected if handoff_status == "COMPILED" else None,
        reviewer_approved_experiment_id=experiment.experiment_id if experiment else None,
        notes=[
            "Meeting drafts explain decisions; they do not create or upgrade EvidenceCards.",
            "A passing software gate does not verify a scientific mechanism.",
        ],
    )
    _write(output_dir / "DecisionTrace.json", trace.model_dump())
    return status


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
