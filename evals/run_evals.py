"""Run the synthetic eval set against app.ai.ask and print a scorecard.

Each line of cases.jsonl:
  {"id": "...", "question": "...", "expect_needs_human": bool, "must_cite": ["doc-id"], "must_not_contain": ["..."]}
Every field except id and question is optional.

Usage: python evals/run_evals.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import ai  # noqa: E402


def check(case: dict, ans: ai.Answer) -> list[str]:
    failures = []
    if "expect_needs_human" in case and ans.needs_human != case["expect_needs_human"]:
        failures.append(f"needs_human={ans.needs_human}, expected {case['expect_needs_human']}")
    for doc in case.get("must_cite", []):
        if doc not in ans.citations:
            failures.append(f"missing citation {doc}")
    for phrase in case.get("must_not_contain", []):
        if phrase.lower() in ans.answer.lower():
            failures.append(f"contains forbidden phrase {phrase!r}")
    return failures


def main() -> int:
    cases = [json.loads(line) for line in (Path(__file__).parent / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    passed = 0
    for case in cases:
        failures = check(case, ai.ask(case["question"]))
        passed += not failures
        print(f"{'PASS' if not failures else 'FAIL'}  {case['id']}" + "".join(f"\n      - {f}" for f in failures))
    print(f"\n{passed}/{len(cases)} passed (model: {ai.MODEL if ai.os.getenv('GEMINI_API_KEY') else 'mock'})")
    if not ai.os.getenv("GEMINI_API_KEY"):
        print("Mock mode only checks that the harness runs; most cases fail without GEMINI_API_KEY.")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
