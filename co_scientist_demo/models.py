from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


Role = Literal["PI", "Critic", "SynthesisAssistant", "CharacterizationAssistant"]
ROLES: tuple[Role, ...] = (
    "PI", "Critic", "SynthesisAssistant", "CharacterizationAssistant"
)


class EvidenceCard(BaseModel):
    id: str
    source_ref: str
    claim: str
    evidence_class: Literal["SYNTHETIC"] = "SYNTHETIC"


class RoleReport(BaseModel):
    role: Role
    assessment: str
    concern: str
    evidence_ids: list[str]


class MeetingTurn(BaseModel):
    role: Role
    statement: str
    evidence_ids: list[str] = Field(default_factory=list)


class RejectedIdea(BaseModel):
    idea: str
    reason: str


class CandidatePlan(BaseModel):
    id: str
    route_label: str
    controls: list[str]
    measurements: list[str]
    decision_rule: str


class BranchDraft(BaseModel):
    branch_id: str
    lens: str
    turns: list[MeetingTurn]
    accepted_decisions: list[str]
    rejected_ideas: list[RejectedIdea]
    open_questions: list[str]
    cited_evidence_ids: list[str]
    candidate: CandidatePlan
    fallback_used: bool = False


class BranchDecision(BaseModel):
    accepted_decisions: list[str]
    rejected_ideas: list[RejectedIdea]
    open_questions: list[str]
    cited_evidence_ids: list[str]
    candidate: CandidatePlan


class LiveScenario(BaseModel):
    case_id: str
    topic: str
    evidence: list[EvidenceCard]
    branch_lenses: list[str]


class ExperimentalResult(BaseModel):
    experiment_id: str
    observation: str
    recorded_by: str
    source_ref: str


class DemoCase(BaseModel):
    case_id: str
    topic: str
    evidence: list[EvidenceCard]
    pre_meeting: list[RoleReport]
    branches: list[BranchDraft]
    researcher_selected_candidate_id: Optional[str] = None
    experimental_result: Optional[ExperimentalResult] = None


class QAFinding(BaseModel):
    code: str
    target: str
    reason: str


class MeetingQA(BaseModel):
    approved: bool
    findings: list[QAFinding]
    reviewed_branch_ids: list[str]


class ExperimentDesignReview(BaseModel):
    approved: bool
    findings: list[QAFinding]
    candidate_id: str


class MeetingSynthesis(BaseModel):
    consensus: list[str]
    disputes: list[str]
    rejected_ideas: list[RejectedIdea]
    open_questions: list[str]
    candidate_ids: list[str]
    status: Literal["PASS", "BLOCKED"]


class ExperimentMatrix(BaseModel):
    experiment_id: str
    candidate_id: str
    controls: list[str]
    measurements: list[str]
    decision_rule: str
    evidence_ids: list[str]


class NextRoundAdvice(BaseModel):
    action: str
    basis: list[str]
    evidence_ids: list[str]
    unresolved_questions: list[str]


class ResultFeedback(BaseModel):
    experiment_id: str
    observation: str
    source_ref: str
    status: Literal["REQUIRES_RESEARCHER_REVIEW"] = "REQUIRES_RESEARCHER_REVIEW"


class RunStatus(BaseModel):
    case_id: str
    meeting_qa_passed: bool
    final_gate_passed: bool
    handoff_status: Literal["BLOCKED", "AWAITING_SELECTION", "COMPILED"]
    blocker_codes: list[str]


class DecisionTrace(BaseModel):
    source_evidence_ids: list[str]
    meeting_draft_ids: list[str]
    selected_candidate_id: Optional[str]
    reviewer_approved_experiment_id: Optional[str]
    notes: list[str]
