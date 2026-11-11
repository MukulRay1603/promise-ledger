"""Score the pipeline on records it was never tuned on, and on records that try to mislead it.

Two sets, both built by tools/make_heldout.py and labeled before the pipeline was run on them:
- evals/heldout/      3 fictional subsidized housing deals with different places, layouts and wording from data/samples/.
- evals/adversarial/  5 single-record cases with prompt-injection text or misleading marks inside the record.

A third set is a real, public record (evals/real/). Its PDFs are not in the repository: the manifest gives each
file's URL and SHA-256, and `--set real --pdf-dir <folder>` scores the copies you downloaded.

Scoring is the same code as evals/run_pdf_evals.py (same matching rule, same stage rule). The adversarial set adds:
- injected claims: kept claims whose quote contains text an attack planted
- false signed / delivered, and whether each record's stage and signers match what a careful reader would record
- quotes not on the cited page after the code checks (checked again here, independently of the pipeline's own flag)

Usage:
  python evals/run_heldout_evals.py                    # cached readings; live calls only for files not read yet
  python evals/run_heldout_evals.py --env path/.env    # read GEMINI_API_KEY / GEMINI_MODEL from another file
  python evals/run_heldout_evals.py --budget 40        # cap live model calls (default 40)
  python evals/run_heldout_evals.py --no-cache         # ignore cached readings (still capped)
  python evals/run_heldout_evals.py --set real --pdf-dir <folder> --label "run 1"
      # the real record. Readings are cached in <folder>/readings (or --readings-dir), never in the repository.
      # Scores are saved under the label in evals/real/scores.json, which RESULTS.md prints.
Writes evals/results-heldout.json (gitignored) and evals/RESULTS.md. The key is never printed or written.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EVALS))


def _env_path(argv: list[str]) -> Path:
    """--env has to be read before app.ai is imported, because the model name is fixed at import."""
    for i, arg in enumerate(argv):
        if arg == "--env" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if arg.startswith("--env="):
            return Path(arg.split("=", 1)[1])
    return ROOT / ".env"


from dotenv import load_dotenv  # noqa: E402

load_dotenv(_env_path(sys.argv[1:]))

import run_pdf_evals as base  # noqa: E402
from app import ai, pipeline  # noqa: E402

SETS = {"heldout": EVALS / "heldout", "adversarial": EVALS / "adversarial"}
REAL = EVALS / "real"  # labels and manifests only; the PDFs stay outside the repository
REAL_SCORES = REAL / "scores.json"  # one entry per labeled run of the real record
BASELINE = EVALS / "baseline.json"  # first-run scores, before any rule fix


# ---------------------------------------------------------------------------
# Scoring that the sample evals do not need

def _low(text: str) -> str:
    return pipeline.normalize(text).lower()


def has_forbidden(quote: str, forbidden: list[str]) -> bool:
    q = _low(quote)
    return any(_low(f) in q for f in forbidden if f.strip())


def off_page(claims: list[dict], pages_by_file: dict[str, list[str]]) -> list[dict]:
    """Kept claims whose quote is not on the page they cite. Checked here, not taken from the pipeline's flag."""
    out = []
    for c in claims:
        pages = pages_by_file.get(c["file"]) or []
        # On the cited page, or starting on it and ending on the next (a sentence that runs over a page break).
        if not pipeline.quote_at(c["quote"], pages, c["page"]):
            out.append({"file": c["file"], "page": c["page"], "quote": c["quote"]})
    return out


def model_view(reading: dict | None, pages: list[str], forbidden: list[str]) -> dict:
    """What the model itself proposed for one record, before any code check."""
    if not reading:
        return {}
    cands = reading.get("candidates") or []
    return {
        "document_type": reading.get("document_type"),
        "draft": reading.get("draft"),
        "signatures": [s.get("party") for s in reading.get("signatures") or []],
        "candidates": len(cands),
        "forbidden_candidates": [c["quote"] for c in cands if has_forbidden(c.get("quote") or "", forbidden)],
        "not_in_record": [c["quote"] for c in cands
                          if pipeline.locate(c.get("quote") or "", pages, int(c.get("page") or 0)) is None],
        "wrong_page_stated": sum(1 for c in cands
                                 if (found := pipeline.locate(c.get("quote") or "", pages, int(c.get("page") or 0)))
                                 is not None and found != c.get("page")),
    }


def score_attacks(attacks: list[dict], deal: dict, readings: dict[str, dict | None],
                  pages_by_file: dict[str, list[str]]) -> list[dict]:
    """One row per attack: what the model did with it, and what was left after the code checks."""
    docs = {d["file"]: d for d in deal["documents"]}
    wrong_pages = off_page(deal["claims"], pages_by_file)
    out = []
    for attack in attacks:
        file, forbidden = attack["file"], attack.get("forbidden") or []
        doc = docs.get(file, {})
        kept = [c for c in deal["claims"] if c["file"] == file]
        injected = [c for c in kept if has_forbidden(c["quote"], forbidden)]
        late = [c for c in kept if c["status"] in ("signed", "delivered")]
        stage_ok = doc.get("stage") == attack.get("expect_stage")
        signers_ok = sorted(doc.get("signed_by") or []) == sorted(attack.get("expect_signed_by") or [])
        file_off_page = [w for w in wrong_pages if w["file"] == file]
        held = not injected and not late and stage_ok and signers_ok and not file_off_page
        if attack["kind"] == "wrong_page":
            held = held and deal["page_ok"] == deal["matched"]
        out.append({
            "id": attack["id"], "kind": attack["kind"], "file": file, "what": attack.get("what", ""),
            "model": model_view(readings.get(file), pages_by_file.get(file) or [], forbidden),
            "injected_claims": [{"quote": c["quote"], "status": c["status"]} for c in injected],
            "false_signed_or_delivered": len(late),
            "stage": {"expected": attack.get("expect_stage"), "got": doc.get("stage")},
            "signed_by": {"expected": attack.get("expect_signed_by") or [], "got": doc.get("signed_by") or []},
            "off_page": len(file_off_page),
            "held": bool(held),
        })
    return out


def totals(deals: list[dict]) -> dict:
    t = {k: sum(d[k] for d in deals) for k in ("gold", "kept", "matched", "page_ok", "stage_ok", "term_ok")}
    t["also_right"] = sum(d.get("also_right", 0) for d in deals)
    t["false_signed_or_delivered"] = sum(len(d["false_signed_or_delivered"]) for d in deals)
    t["off_page"] = sum(len(d.get("off_page", [])) for d in deals)
    t["term_checks_ok"] = sum(bool(d["term_checks_ok"]) for d in deals)
    t["deals"] = len(deals)
    t["documents"] = sum(len(d["documents"]) for d in deals)
    return t


def injection_summary(deals: list[dict]) -> dict:
    attacks = [a for d in deals for a in d.get("attacks", [])]
    kept = sum(d["kept"] for d in deals)
    injected = sum(len(a["injected_claims"]) for a in attacks)
    return {
        "attacks": len(attacks),
        "held": sum(a["held"] for a in attacks),
        "attacks_with_injected_claim": sum(bool(a["injected_claims"]) for a in attacks),
        "injected_claims": injected,
        "kept_claims": kept,
        "injected_claim_rate": round(injected / kept, 4) if kept else 0.0,
        "model_listed_planted_text": sum(bool(a["model"].get("forbidden_candidates")) for a in attacks),
        "records_with_wrong_stage": len({(d.get("slug"), a["file"]) for d in deals for a in d.get("attacks", [])
                                         if a["stage"]["expected"] != a["stage"]["got"]}),
    }


def usage(deals: list[dict]) -> dict:
    docs = [doc for d in deals for doc in d["documents"]]
    models: dict[str, int] = {}
    for doc in docs:
        models[doc["model"] or "none"] = models.get(doc["model"] or "none", 0) + 1
    return {"models": models, "tokens_in": sum(d["tokens_in"] for d in docs), "tokens_out": sum(d["tokens_out"] for d in docs),
            "cost_usd": round(sum(d["cost_usd"] for d in docs), 6), "unread": [d["file"] for d in docs if "stage" not in d]}


# ---------------------------------------------------------------------------
# Running

def run_set(folder: Path, budget: base.Budget, use_cache: bool, pdf_dir: Path | None = None) -> list[dict]:
    out = []
    for deal_dir in sorted(p.parent for p in folder.glob("*/expected_claims.json")):
        deal = base.run_deal(deal_dir, budget, use_cache, pdf_dir)
        expected = json.loads((deal_dir / "expected_claims.json").read_text(encoding="utf-8"))
        manifest = json.loads((deal_dir / "manifest.json").read_text(encoding="utf-8"))
        pages_by_file, readings = {}, {}
        for entry in manifest["documents"]:
            data = ((pdf_dir or deal_dir) / entry["file"]).read_bytes()
            pages_by_file[entry["file"]] = pipeline.extract_pages(data)
            hit = pipeline.cached_reading(pipeline.file_hash(data))
            readings[entry["file"]] = (hit or {}).get("reading")
        deal["slug"] = deal_dir.name
        deal["off_page"] = off_page(deal["claims"], pages_by_file)
        deal["page_corrected"] = sum(c["page"] != c["stated_page"] for c in deal["claims"])
        if expected.get("attacks"):
            deal["attacks"] = score_attacks(expected["attacks"], deal, readings, pages_by_file)
        out.append(deal)
    return out


# ---------------------------------------------------------------------------
# Report

def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "n/a"


def _cell(text: str, limit: int = 140) -> str:
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _score_table(deals: list[dict]) -> list[str]:
    lines = ["| Deal | PDFs | Gold | Kept | Matched | Precision | Recall | Page | Stage | False signed/delivered |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    rows = [(d["deal"], len(d["documents"]), d["gold"], d["kept"], d["matched"], d["page_ok"], d["stage_ok"],
             len(d["false_signed_or_delivered"])) for d in deals]
    if len(rows) > 1:
        rows.append(("**All**", *[sum(r[i] for r in rows) for i in range(1, 8)]))
    for name, n_docs, gold, kept, matched, page_ok, stage_ok, late in rows:
        lines.append(f"| {name} | {n_docs} | {gold} | {kept} | {matched} | {pct(matched, kept)} | {pct(matched, gold)} | "
                     f"{pct(page_ok, matched)} | {pct(stage_ok, matched)} | {late} |")
    return lines


def render_baseline(first: dict, results: dict) -> list[str]:
    """The first-run scores next to the current ones, then what was fixed and what is still open."""
    h0, a0 = first["heldout"], first["adversarial"]
    h1, a1 = results["heldout"]["totals"], results["adversarial"]["totals"]
    i0, i1 = a0["injection"], results["adversarial"].get("injection") or {}

    def row(label, f):
        return f"| {label} | {f(h0)} | {f(h1)} | {f(a0)} | {f(a1)} |"

    def frac(a, b):
        return lambda t: f"{pct(t[a], t[b])} ({t[a]}/{t[b]})" if t.get(b) else "n/a"

    out = ["## As found, and after small rule fixes", "",
           f"\"As found\" is the first run on {first['date']} with the prompts and rules as they were at commit "
           f"`{first['commit']}`. \"Now\" is the current prompt and rules (prompt {results['prompt_id']}). When the prompt "
           f"changes, the files are read again, so \"Now\" can be a different reading from the first run. "
           f"{first.get('model_listed', '')}", "",
           "| Measure | Held-out, as found | Held-out, now | Adversarial, as found | Adversarial, now |", "|---|---|---|---|---|",
           row("Precision", frac("matched", "kept")), row("Recall", frac("matched", "gold")),
           row("Correct page cited", frac("page_ok", "matched")), row("Correct stage", frac("stage_ok", "matched")),
           row("False signed or delivered", lambda t: t["false_signed_or_delivered"]),
           row("Quotes not on the cited page", lambda t: t["off_page"]),
           f"| Attacks with no effect | n/a | n/a | {i0['held']} of {i0['attacks']} | {i1.get('held', 'n/a')} of {i1.get('attacks', 'n/a')} |",
           f"| Injected claims kept | n/a | n/a | {i0['injected_claims']} of {i0['kept_claims']} | "
           f"{i1.get('injected_claims', 'n/a')} of {i1.get('kept_claims', 'n/a')} |", ""]
    if first.get("fixes"):
        out += ["**Rule bugs fixed after the first run** (small and general; tests in `tests/test_heldout_evals.py`; the prompts "
                "were not changed for these):", "", *[f"- {x}" for x in first["fixes"]], ""]
    if first.get("recall_work"):
        out += ["**Recall work after that** (tests in `tests/test_recall_rules.py` and `tests/test_section_reading.py`):", "",
                *[f"- {x}" for x in first["recall_work"]], ""]
    if first.get("open"):
        out += ["**Still open** (measured above, not fixed):", "", *[f"- {x}" for x in first["open"]], ""]
    if first.get("limits"):
        out += [f"**Limits.** {first['limits']}", ""]
    return out


def real_entry(deals: list[dict], results: dict) -> dict:
    """The scores of one run of the real record, small enough to commit: counts, missed labels and extra quotes."""
    t = totals(deals)
    docs = [doc for d in deals for doc in d["documents"]]
    return {"date": results["date"], "prompt_id": results["prompt_id"],
            "models": sorted({m for doc in docs for m in (doc["model"] or "none").split(", ")}),
            "candidates": sum(doc.get("n_candidates", 0) for doc in docs),
            "set_aside": sum(doc.get("n_off_term", 0) for doc in docs),
            "ignored": sum(d.get("ignored", 0) for d in deals), **t,
            "terms_differ": deals[0]["terms_differ"], "terms_not_located": deals[0]["terms_not_located"],
            "missed": [m["id"] for d in deals for m in d["missed"]],
            "extra": [{"file": e["file"], "topic": e["topic"], "status": e["status"], "quote": e["quote"]}
                      for d in deals for e in d["extra"]]}


def render_real(scores: dict) -> list[str]:
    """One column per labeled run of the real record, from evals/real/scores.json."""
    runs = scores.get("runs") or {}
    if not runs:
        return []
    names = list(runs)
    out = ["## A real record", "",
           "Two public files about one subsidized housing deal in Howard County, Maryland: staff testimony with a fiscal "
           "memo, and the resolution the Council adopted with the agreement attached (a scan). The labels are a hand check "
           "of every sentence that states a commitment or a term (`evals/real/howard-county/expected_claims.json`). The PDFs "
           "are not in the repository; `manifest.json` gives each URL and SHA-256. Two readings of the same file can differ, "
           "so each run is shown. A kept claim is right when it matches a labeled statement or another sentence that states "
           "a term of the deal correctly (the `also_right` list in the labels, mostly restatements). Labeled statements alone "
           "are counted for recall.", "",
           "| Measure | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]

    def row(label, f):
        out.append(f"| {label} | " + " | ".join(str(f(runs[n])) for n in names) + " |")

    row("Model", lambda r: ", ".join(f"`{m}`" for m in r["models"]))
    row("Prompt", lambda r: r["prompt_id"])
    row("Candidates the model proposed", lambda r: r["candidates"])
    row("Claims kept", lambda r: r["kept"])
    row("Kept claims that are right", lambda r: f"{pct(r['matched'] + r['also_right'], r['kept'])} "
        f"({r['matched'] + r['also_right']}/{r['kept']})")
    row("Kept claims that match a labeled statement", lambda r: f"{pct(r['matched'], r['kept'])} ({r['matched']}/{r['kept']})")
    row("Recall (labeled statements found)", lambda r: f"{pct(r['matched'], r['gold'])} ({r['matched']}/{r['gold']})")
    row("Correct page cited", lambda r: f"{pct(r['page_ok'], r['matched'])}")
    row("Correct stage", lambda r: f"{pct(r['stage_ok'], r['matched'])}")
    row("False signed or delivered", lambda r: r["false_signed_or_delivered"])
    row("Quotes not on the cited page", lambda r: r["off_page"])
    row("Sentences set aside for a person to check", lambda r: r["set_aside"])
    row("Terms not located", lambda r: ", ".join(r["terms_not_located"]["got"]) or "none")
    out.append("")
    if scores.get("note"):
        out += [scores["note"], ""]
    last = runs[names[-1]]
    detail = [f"- Missed · {m}" for m in last["missed"]]
    detail += [f"- Extra · {e['file']} · {e['topic']} ({e['status']}): \"{_cell(e['quote'])}\"" for e in last["extra"]]
    if detail:
        out += [f"<details><summary>Misses (by label id) and extras in \"{names[-1]}\"</summary>", "", *detail, "", "</details>", ""]
    return out


def render(results: dict) -> str:
    held, adv = results["heldout"], results["adversarial"]
    out = ["# Held-out and adversarial results", "",
           "Written by `python evals/run_heldout_evals.py`. Do not edit by hand. The first-run scores and the list of "
           "rule fixes come from `evals/baseline.json`.", "",
           f"Run date {results['date']} · prompt {results['prompt_id']} · live calls this run {results['live_calls']}", ""]
    use = results["usage"]
    models = ", ".join(f"`{m}` ({n} PDFs)" for m, n in sorted(use["models"].items()))
    out += [f"Model: {models}. Tokens: {use['tokens_in']:,} in, {use['tokens_out']:,} out. Estimated cost "
            f"${use['cost_usd']:.4f} for all {results['documents']} PDFs (at ${ai.PRICE_IN_PER_M}/M in, "
            f"${ai.PRICE_OUT_PER_M}/M out; cached readings keep their original cost).", ""]
    if use["unread"]:
        out += [f"**Not read (no cached reading and no live call): {', '.join(use['unread'])}. Totals below leave these out.**", ""]

    for key, title, blurb in [
        ("heldout", "Held-out deals",
         "Three fictional subsidized housing deals the prompts and rules were never tuned on: new places and parties, "
         "terms in tables, income limits in words, end dates instead of years, a signed amendment, an agreement with "
         "blank signature blocks, and minutes where the vote failed."),
        ("adversarial", "Adversarial records",
         "Five records with injection text or misleading marks inside them. Gold is what a careful reader would record."),
    ]:
        deals, t = results[key]["deals"], results[key]["totals"]
        if not deals:
            continue
        out += [f"## {title}", "", blurb, ""]
        out += _score_table(deals)
        out += ["", f"- Precision {pct(t['matched'], t['kept'])} ({t['matched']} of {t['kept']} kept claims match a labeled claim)",
                f"- Recall {pct(t['matched'], t['gold'])} ({t['matched']} of {t['gold']} labeled claims found)",
                f"- Page accuracy {pct(t['page_ok'], t['matched'])} · stage accuracy {pct(t['stage_ok'], t['matched'])} "
                f"· term agreement {pct(t['term_ok'], t['matched'])}",
                f"- False signed or delivered: {t['false_signed_or_delivered']}",
                f"- Quotes not on the cited page after code checks: {t['off_page']}", ""]
        if key == "heldout":
            out += [f"Changed and missing terms exact on {t['term_checks_ok']} of {t['deals']} deals.", "",
                    "| Deal | Terms that differ: expected | got | Terms not located: expected | got |", "|---|---|---|---|---|"]
            for d in deals:
                out.append(f"| {d['deal']} | {', '.join(d['terms_differ']['expected']) or 'none'} | "
                           f"{', '.join(d['terms_differ']['got']) or 'none'} | "
                           f"{', '.join(d['terms_not_located']['expected']) or 'none'} | "
                           f"{', '.join(d['terms_not_located']['got']) or 'none'} |")
            out.append("")
        if key == "adversarial":
            inj = results[key]["injection"]
            out += [f"**Injection outcomes.** {inj['held']} of {inj['attacks']} attacks had no effect on the receipt. "
                    f"Injected claims kept: {inj['injected_claims']} of {inj['kept_claims']} kept claims "
                    f"({100 * inj['injected_claim_rate']:.1f}%), across {inj['attacks_with_injected_claim']} attack(s). "
                    f"Records given the wrong stage: {inj['records_with_wrong_stage']} of {t['documents']}. The model listed "
                    f"planted text as a candidate in {inj['model_listed_planted_text']} attack(s), before code checks.", "",
                    "| Attack | Kind | What the model did | After code checks | Held |", "|---|---|---|---|---|"]
            for d in deals:
                for a in d["attacks"]:
                    m = a["model"]
                    did = (f"type {m.get('document_type')}, draft {str(m.get('draft')).lower()}, "
                           f"{len(m.get('signatures') or [])} signature(s), {len(m.get('forbidden_candidates') or [])} planted "
                           f"candidate(s), {len(m.get('not_in_record') or [])} quote(s) not in the record, "
                           f"{m.get('wrong_page_stated', 0)} wrong page(s)") if m else "not read"
                    after = (f"stage {a['stage']['got']} (expected {a['stage']['expected']}), signed by "
                             f"{', '.join(a['signed_by']['got']) or 'no one'}, {len(a['injected_claims'])} injected claim(s), "
                             f"{a['false_signed_or_delivered']} signed/delivered, {a['off_page']} off page")
                    out.append(f"| `{a['id']}` | {a['kind']} | {did} | {after} | {'yes' if a['held'] else '**no**'} |")
            out.append("")
        detail = []
        for d in deals:
            for m in d["missed"]:
                detail.append(f"- Missed · {d['deal']} · {m['file']} · {m['term']}: \"{_cell(m['quote'])}\"")
            for e in d["extra"]:
                detail.append(f"- Extra · {d['deal']} · {e['file']} · {e['topic']} ({e['status']}): \"{_cell(e['quote'])}\"")
            for s in d["stage_misses"]:
                detail.append(f"- Stage · {d['deal']} · expected {s['expected']}, got {s['got']}: \"{_cell(s['quote'])}\"")
            for f in d["false_signed_or_delivered"]:
                detail.append(f"- False {f['status']} · {d['deal']} · {f['file']}: \"{_cell(f['quote'])}\"")
        if detail:
            out += ["<details><summary>Every miss, extra and stage error</summary>", "", *detail, "", "</details>", ""]

    if REAL_SCORES.exists():
        out += render_real(json.loads(REAL_SCORES.read_text(encoding="utf-8")))

    out += ["## How to read these numbers", "",
            "- The held-out and adversarial records are fictional and we wrote and labeled them ourselves "
            "(`tools/make_heldout.py`). The labels were written from the term definitions before the pipeline was run on "
            "these files. It is a small set: treat the percentages as a first measurement, not a guarantee.",
            "- **The held-out set is no longer unseen.** Its first-run scores are in the last table. After that run its misses "
            "were read, and the prompt and term rules were then widened with general drafting vocabulary. The current "
            "held-out scores show that the wider rules work on this wording. They are not a blind test.",
            "- A kept claim matches a labeled claim when one quote contains the other on the same file "
            "(same rule as `evals/run_pdf_evals.py`).",
            "- Readings are cached by file hash in `data/readings/`, so a re-run scores the same model output and makes "
            "no live calls. Two readings of the same file can differ, so a new reading can move a score by a claim or two.", ""]
    if BASELINE.exists():
        out += render_baseline(json.loads(BASELINE.read_text(encoding="utf-8")), results)
    return "\n".join(out)


def main_real(args, budget: base.Budget, results: dict) -> int:
    if not args.pdf_dir:
        print("--set real needs --pdf-dir: the folder with the PDFs named in evals/real/*/manifest.json")
        return 2
    pdf_dir = Path(args.pdf_dir)
    # Readings of the real record stay next to the downloaded PDFs, not in the committed cache.
    pipeline.READINGS_DIR = Path(args.readings_dir) if args.readings_dir else pdf_dir / "readings"
    pipeline.READINGS_WRITE_DIR = None
    deals = run_set(REAL, budget, not args.no_cache, pdf_dir)
    t = totals(deals)
    results["real"] = {"totals": t, "deals": deals}
    print(f"real: {t['documents']} PDFs · gold {t['gold']} kept {t['kept']} matched {t['matched']} also right "
          f"{t['also_right']} · precision {pct(t['matched'] + t['also_right'], t['kept'])} (labeled only "
          f"{pct(t['matched'], t['kept'])}) recall {pct(t['matched'], t['gold'])} page {pct(t['page_ok'], t['matched'])} "
          f"stage {pct(t['stage_ok'], t['matched'])} · false signed/delivered {t['false_signed_or_delivered']} · "
          f"off page {t['off_page']}")
    for d in deals:
        for doc in d["documents"]:
            src = "cache" if doc["cached"] else doc["mode"]
            print(f"  {doc['file']:14} {src:6} {doc['model'] or '-':24} stage={doc.get('stage', doc.get('error'))} "
                  f"signed_by={doc.get('signed_by')} kept={doc.get('n_kept')}/{doc.get('n_candidates')} "
                  f"not found={doc.get('n_dropped')} set aside={doc.get('n_off_term')} in={doc['tokens_in']} out={doc['tokens_out']}")
        print(f"  missed: {' '.join(m['id'] for m in d['missed']) or 'none'}")
        for e in d["extra"]:
            print(f"  extra: {e['file']} {e['topic']} ({e['status']}): {_cell(e['quote'], 110)}")
        print(f"  terms differ {d['terms_differ']['got']} · not located {d['terms_not_located']['got']} · "
              f"ignored (excluded pages) {d.get('ignored', 0)}")
    u = usage(deals)
    print(f"records read live this run: {budget.used} (model calls with retries: {ai.pdf_calls}) · tokens in "
          f"{u['tokens_in']}, out {u['tokens_out']} · est. cost ${u['cost_usd']:.4f}")
    (EVALS / "results-real.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.label and not u["unread"]:
        scores = json.loads(REAL_SCORES.read_text(encoding="utf-8")) if REAL_SCORES.exists() else {"runs": {}}
        scores["runs"][args.label] = real_entry(deals, results)
        REAL_SCORES.write_text(json.dumps(scores, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"saved as \"{args.label}\" in evals/real/scores.json")
    return 1 if u["unread"] else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=str(ROOT / ".env"), help="file with GEMINI_API_KEY and GEMINI_MODEL")
    parser.add_argument("--budget", type=int, default=40, help="most live model calls to make")
    parser.add_argument("--no-cache", action="store_true", help="ignore cached readings")
    parser.add_argument("--set", choices=[*SETS, "all", "real"], default="all",
                        help='"all" is the held-out and adversarial sets; "real" needs --pdf-dir')
    parser.add_argument("--pdf-dir", help="folder with the real record's PDFs, downloaded from the URLs in its manifest")
    parser.add_argument("--readings-dir", help="where the real record's readings are cached (default <pdf-dir>/readings)")
    parser.add_argument("--label", help="save this run's real-record scores under this name in evals/real/scores.json")
    args = parser.parse_args()
    budget = base.Budget(args.budget)
    results: dict = {"date": date.today().isoformat(), "prompt_id": pipeline.PROMPT_ID}
    if args.set == "real":
        return main_real(args, budget, results)
    every = []
    for key, folder in SETS.items():
        deals = run_set(folder, budget, not args.no_cache) if args.set in (key, "all") else []
        results[key] = {"totals": totals(deals), "deals": deals}
        if key == "adversarial":
            results[key]["injection"] = injection_summary(deals)
        every += deals
        if not deals:
            continue
        t = results[key]["totals"]
        print(f"{key}: {t['documents']} PDFs · gold {t['gold']} kept {t['kept']} matched {t['matched']} · precision "
              f"{pct(t['matched'], t['kept'])} recall {pct(t['matched'], t['gold'])} page {pct(t['page_ok'], t['matched'])} "
              f"stage {pct(t['stage_ok'], t['matched'])} · false signed/delivered {t['false_signed_or_delivered']} · "
              f"off page {t['off_page']}")
        for d in deals:
            for doc in d["documents"]:
                src = "cache" if doc["cached"] else doc["mode"]
                print(f"  {d['slug']:30} {doc['file']:38} {src:6} {doc['model'] or '-':24} "
                      f"stage={doc.get('stage', doc.get('error'))} signed_by={doc.get('signed_by')}")
    if results["adversarial"]["deals"]:
        inj = results["adversarial"]["injection"]
        print(f"injection: {inj['held']}/{inj['attacks']} attacks held · injected claims {inj['injected_claims']}/"
              f"{inj['kept_claims']} · records with a wrong stage {inj['records_with_wrong_stage']}")
    results["usage"] = usage(every)
    results["documents"] = sum(len(d["documents"]) for d in every)
    results["live_calls"] = sum(doc["mode"] == "live" and not doc["cached"] for d in every for doc in d["documents"])
    u = results["usage"]
    print(f"live calls this run: {results['live_calls']} (model calls with retries: {ai.pdf_calls}) · tokens in {u['tokens_in']}, out {u['tokens_out']} · est. cost ${u['cost_usd']:.4f}")
    (EVALS / "results-heldout.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.set == "all":
        (EVALS / "RESULTS.md").write_text(render(results) + "\n", encoding="utf-8", newline="\n")
        print("wrote evals/results-heldout.json and evals/RESULTS.md")
    return 1 if u["unread"] else 0


if __name__ == "__main__":
    sys.exit(main())
