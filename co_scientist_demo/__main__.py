import argparse
import json
from pathlib import Path

from .models import DemoCase, LiveScenario
from .pipeline import run_case


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or replay a synthetic research meeting.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--case", type=Path, help="Replay a reviewed synthetic case.")
    source.add_argument("--live-scenario", type=Path, help="Ask a configured model to draft role outputs.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.live_scenario:
        from .agents import OpenAIBackend, generate_case

        scenario = LiveScenario.model_validate_json(args.live_scenario.read_text(encoding="utf-8"))
        case = generate_case(scenario, OpenAIBackend())
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(case.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Draft saved to {args.out}. Review sources and choose a candidate before replay.")
        return
    case = DemoCase.model_validate_json(args.case.read_text(encoding="utf-8"))
    status = run_case(case, args.out)
    print(f"{status.case_id}: {status.handoff_status} (blockers: {', '.join(status.blocker_codes) or 'none'})")


if __name__ == "__main__":
    main()
