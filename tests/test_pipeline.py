import json
import tempfile
import unittest
from pathlib import Path

from co_scientist_demo.agents import generate_case
from co_scientist_demo.models import (
    BranchDecision,
    CandidatePlan,
    DemoCase,
    LiveScenario,
    MeetingTurn,
    RejectedIdea,
    RoleReport,
)
from co_scientist_demo.pipeline import run_case


ROOT = Path(__file__).resolve().parents[1]


def load_case(name: str = "pass") -> DemoCase:
    return DemoCase.model_validate_json((ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8"))


class GatedWorkflowTests(unittest.TestCase):
    def test_agent_orchestration_is_role_specific_and_branch_isolated(self):
        scenario = LiveScenario.model_validate_json(
            (ROOT / "examples" / "live_scenario.json").read_text(encoding="utf-8")
        )

        class FakeBackend:
            def __init__(self):
                self.analysis_roles = []
                self.history_lengths = {}

            def analyze(self, role, topic, evidence):
                self.analysis_roles.append(role)
                return RoleReport(role=role, assessment=f"{role} view", concern="Needs verification", evidence_ids=["E1"])

            def speak(self, role, topic, lens, pre_meeting, branch_history):
                self.history_lengths.setdefault(lens, []).append(len(branch_history))
                return MeetingTurn(role=role, statement=f"{role} turn", evidence_ids=["E1"])

            def decide(self, topic, lens, pre_meeting, branch_history):
                return BranchDecision(
                    accepted_decisions=["Keep a matched baseline."],
                    rejected_ideas=[RejectedIdea(idea="Skip control", reason="Uninterpretable")],
                    open_questions=["Can the route be repeated?"],
                    cited_evidence_ids=["E1"],
                    candidate=CandidatePlan(
                        id=f"candidate-{lens.split()[0]}",
                        route_label=lens,
                        controls=["Matched baseline"],
                        measurements=["Independent readout"],
                        decision_rule="Proceed only if baseline checks pass.",
                    ),
                )

        backend = FakeBackend()
        case = generate_case(scenario, backend)
        self.assertEqual(backend.analysis_roles, ["PI", "Critic", "SynthesisAssistant", "CharacterizationAssistant"])
        self.assertEqual(backend.history_lengths["route feasibility"], [0, 1, 2, 3, 4])
        self.assertEqual(backend.history_lengths["verification and falsification"], [0, 1, 2, 3, 4])
        self.assertIsNone(case.researcher_selected_candidate_id)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run_case(case, Path(tmp)).handoff_status, "AWAITING_SELECTION")

    def test_pass_case_has_traceable_handoff_and_pending_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            status = run_case(load_case(), output)
            self.assertEqual(status.handoff_status, "COMPILED")
            self.assertTrue(status.final_gate_passed)
            design = json.loads((output / "ExperimentDesignReview.json").read_text(encoding="utf-8"))
            self.assertTrue(design["approved"])
            matrix = json.loads((output / "ExperimentMatrix.json").read_text(encoding="utf-8"))
            self.assertEqual(matrix["candidate_id"], "route-a")
            self.assertEqual(matrix["evidence_ids"], ["E1", "E2"])
            trace = json.loads((output / "DecisionTrace.json").read_text(encoding="utf-8"))
            self.assertEqual(trace["source_evidence_ids"], ["E1", "E2"])
            self.assertEqual(len(json.loads((output / "EvidenceCards.json").read_text(encoding="utf-8"))), 2)
            feedback = json.loads((output / "ResultFeedback.json").read_text(encoding="utf-8"))
            self.assertEqual(feedback["status"], "REQUIRES_RESEARCHER_REVIEW")

    def test_fallback_branch_blocks_downstream_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            status = run_case(load_case("blocked"), output)
            self.assertEqual(status.handoff_status, "BLOCKED")
            self.assertIn("FALLBACK", status.blocker_codes)
            self.assertFalse((output / "ExperimentMatrix.json").exists())
            self.assertFalse((output / "NextRoundAdvice.json").exists())

    def test_design_review_blocks_missing_control(self):
        case = load_case()
        case.branches[0].candidate.controls = []
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            status = run_case(case, output)
            self.assertTrue(status.meeting_qa_passed)
            self.assertTrue(status.final_gate_passed)
            self.assertEqual(status.handoff_status, "BLOCKED")
            self.assertIn("DESIGN_CONTROLS", status.blocker_codes)
            self.assertFalse((output / "ExperimentMatrix.json").exists())

    def test_unknown_source_reference_blocks_meeting(self):
        case = load_case()
        case.branches[0].turns[1].evidence_ids = ["UNKNOWN"]
        with tempfile.TemporaryDirectory() as tmp:
            status = run_case(case, Path(tmp))
            self.assertIn("TURN_EVIDENCE", status.blocker_codes)
            self.assertEqual(status.handoff_status, "BLOCKED")

    def test_human_selection_is_required_for_compilation(self):
        case = load_case()
        case.researcher_selected_candidate_id = None
        case.experimental_result = None
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            status = run_case(case, output)
            self.assertEqual(status.handoff_status, "AWAITING_SELECTION")
            self.assertFalse((output / "ExperimentMatrix.json").exists())

    def test_result_must_match_selected_experiment_before_writing(self):
        case = load_case()
        case.experimental_result.experiment_id = "experiment-other"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with self.assertRaises(ValueError):
                run_case(case, output)
            self.assertEqual(list(output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
