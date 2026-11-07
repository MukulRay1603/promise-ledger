"""Run the extraction cases against the live model and print a scorecard.

Each line of cases.jsonl:
  {"id": "...", "text": "...", "must_find": ["topic"], "must_not_quote": ["..."]}
Every quote returned must also be word for word in the text.

Usage: python evals/run_evals.py
Needs GEMINI_API_KEY. Without one it stops, since saved output would prove nothing.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import ai  # noqa: E402


def check(case: dict, result: ai.ExtractResult) -> list[str]:
    failures = []
    if result.mode != "live":
        failures.append(f"fell back to saved output: {result.notice}")
    topics = {c.topic for c in result.candidates}
    for topic in case.get("must_find", []):
        if topic not in topics:
            failures.append(f"missing topic {topic}")
    for candidate in result.candidates:
        if candidate.quote not in case["text"]:
            failures.append(f"quote not in text: {candidate.quote!r}")
        for phrase in case.get("must_not_quote", []):
            if phrase.lower() in candidate.quote.lower():
                failures.append(f"quoted blocked phrase {phrase!r}")
    return failures


def main() -> int:
    if not os.getenv("GEMINI_API_KEY"):
        print("Skipped: set GEMINI_API_KEY to run these cases.")
        return 0
    path = Path(__file__).parent / "cases.jsonl"
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    passed = 0
    for case in cases:
        failures = check(case, ai.extract(case["text"]))
        passed += not failures
        print(f"{'PASS' if not failures else 'FAIL'}  {case['id']}" + "".join(f"\n      - {f}" for f in failures))
    print(f"\n{passed}/{len(cases)} passed (model: {ai.MODEL})")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
