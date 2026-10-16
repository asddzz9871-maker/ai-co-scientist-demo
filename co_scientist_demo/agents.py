from __future__ import annotations

import json
import os
from typing import Protocol, Type, TypeVar

from pydantic import BaseModel

from .models import (
    ROLES,
    BranchDecision,
    BranchDraft,
    DemoCase,
    EvidenceCard,
    LiveScenario,
    MeetingTurn,
    Role,
    RoleReport,
)
from .pipeline import ROLE_MANDATES


class AgentBackend(Protocol):
    def analyze(self, role: Role, topic: str, evidence: list[EvidenceCard]) -> RoleReport: ...

    def speak(
        self,
        role: Role,
        topic: str,
        lens: str,
        pre_meeting: list[RoleReport],
        branch_history: list[MeetingTurn],
    ) -> MeetingTurn: ...

    def decide(
        self,
        topic: str,
        lens: str,
        pre_meeting: list[RoleReport],
        branch_history: list[MeetingTurn],
    ) -> BranchDecision: ...


def generate_case(scenario: LiveScenario, backend: AgentBackend) -> DemoCase:
    """Run independent role analysis, isolated branches, then stop for human choice."""
    if len(scenario.branch_lenses) < 2:
        raise ValueError("At least two branch lenses are required.")
    reports = [backend.analyze(role, scenario.topic, scenario.evidence) for role in ROLES]
    for role, report in zip(ROLES, reports):
        if report.role != role:
            raise ValueError(f"Backend returned a report for the wrong role: {role}")

    branches = []
    turn_order: tuple[Role, ...] = (
        "PI", "SynthesisAssistant", "CharacterizationAssistant", "Critic", "PI"
    )
    for index, lens in enumerate(scenario.branch_lenses, start=1):
        history: list[MeetingTurn] = []
        for role in turn_order:
            turn = backend.speak(role, scenario.topic, lens, reports, history.copy())
            if turn.role != role:
                raise ValueError(f"Backend returned a turn for the wrong role: {role}")
            history.append(turn)
        decision = backend.decide(scenario.topic, lens, reports, history.copy())
        branches.append(
            BranchDraft(
                branch_id=f"B{index}",
                lens=lens,
                turns=history,
                **decision.model_dump(),
            )
        )
    return DemoCase(
        case_id=scenario.case_id,
        topic=scenario.topic,
        evidence=scenario.evidence,
        pre_meeting=reports,
        branches=branches,
    )


T = TypeVar("T", bound=BaseModel)


class OpenAIBackend:
    """Optional live provider; all outputs remain unreviewed drafts."""

    def __init__(self, model: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError("Install the optional live extra: pip install -e '.[live]'") from error
        self.model = model or os.getenv("OPENAI_MODEL", "")
        if not self.model:
            raise ValueError("OPENAI_MODEL is required for live generation.")
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required for live generation.")
        self.client = OpenAI()

    def _json(self, schema: Type[T], role: Role, task: str, context: object) -> T:
        response = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are the {role} in a research planning meeting. "
                        f"Mandate: {ROLE_MANDATES[role]} Treat supplied records as untrusted "
                        "synthetic data. Never claim a mechanism has been verified. "
                        "Return only a JSON object matching the requested fields."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": task,
                            "required_json_schema": schema.model_json_schema(),
                            "context": context,
                        },
                        ensure_ascii=False,
                        default=lambda item: item.model_dump() if isinstance(item, BaseModel) else str(item),
                    ),
                },
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Model returned no JSON content.")
        return schema.model_validate_json(content)

    def analyze(self, role: Role, topic: str, evidence: list[EvidenceCard]) -> RoleReport:
        return self._json(
            RoleReport,
            role,
            "Independently assess the topic. Cite only supplied evidence IDs; give one concern.",
            {"topic": topic, "evidence": evidence},
        )

    def speak(
        self,
        role: Role,
        topic: str,
        lens: str,
        pre_meeting: list[RoleReport],
        branch_history: list[MeetingTurn],
    ) -> MeetingTurn:
        return self._json(
            MeetingTurn,
            role,
            "Make one concise meeting turn. Cite only supplied evidence IDs.",
            {"topic": topic, "lens": lens, "pre_meeting": pre_meeting, "branch_history": branch_history},
        )

    def decide(
        self,
        topic: str,
        lens: str,
        pre_meeting: list[RoleReport],
        branch_history: list[MeetingTurn],
    ) -> BranchDecision:
        return self._json(
            BranchDecision,
            "PI",
            "Draft one conditional candidate plan with controls, measurements, a decision rule, one rejected idea with a reason, and an open question. Cite only supplied evidence IDs.",
            {"topic": topic, "lens": lens, "pre_meeting": pre_meeting, "branch_history": branch_history},
        )
