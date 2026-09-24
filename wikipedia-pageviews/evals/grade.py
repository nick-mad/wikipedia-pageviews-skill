#!/usr/bin/env python3
"""Programmatic grader for eval runs. Writes grading.json into each run dir.

    uv run --project <skill> python evals/grade.py <ws>/iteration-N

Checks are deterministic (regexes over the transcript and the final answer,
plus the report module's number verifier), so iterations are comparable.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from wpv import report

SKILL_DIR = Path(__file__).resolve().parent.parent
API_HOSTS = re.compile(r"wikimedia\.org|wikipedia\.org/w/api|wikidata\.org|rest_v1")


def commands(run_dir: Path) -> tuple[list[str], list[str], Counter]:
    bash, written, tools = [], [], Counter()
    for line in (run_dir / "transcript.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e.get("type") != "assistant":
            continue
        for b in e["message"].get("content", []):
            if b.get("type") != "tool_use":
                continue
            tools[b["name"]] += 1
            if b["name"] == "Bash":
                bash.append(b["input"].get("command", ""))
            elif b["name"] in ("Write", "Edit"):
                written.append(b["input"].get("content", "") + b["input"].get("new_string", ""))
            elif b["name"] == "WebFetch":
                bash.append("WebFetch " + b["input"].get("url", ""))
    return bash, written, tools


def analyses(out: Path) -> list[dict]:
    files = sorted(out.glob("*analysis.json"), key=lambda p: p.stat().st_mtime)
    return [json.loads(f.read_text()) for f in files]


def pdf_pages(path: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", path.read_bytes()))


def lang_ok(text: str, lang: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    cyr = sum("а" <= c.lower() <= "я" or c in "іїєґІЇЄҐ" for c in letters) / len(letters)
    if lang == "uk":
        return cyr > 0.5 and bool(re.search(r"[іїєґ]", text.lower()))
    return cyr < 0.1


def grade(run_dir: Path, ev: dict) -> dict:
    out = run_dir / "outputs"
    answer = (out / "final_answer.txt").read_text()
    all_answers = (out / "answer.md").read_text()
    bash, written, tools = commands(run_dir)
    ans = analyses(out)
    low = all_answers.lower()

    def check(aid: str):
        if aid == "used_cli":
            hits = [c for c in bash if re.search(r"wpv\S*\s+analyze", c)]
            return bool(hits), (hits[0][:160] if hits else "no `wpv analyze` call")
        if aid == "no_own_api_code":
            hits = [c for c in bash + written if API_HOSTS.search(c)]
            return not hits, (f"{len(hits)} direct API call(s)/scripts, e.g. {hits[0][:140]}"
                              if hits else "no direct Wikimedia API calls")
        if aid == "numbers_grounded":
            if not ans:
                return False, "no analysis.json produced; numbers cannot be traced to data"
            known = set().union(*(report.known_numbers(a) for a in ans))
            bad = report.unverified(answer, known)
            return not bad, ("all numbers traceable" if not bad
                             else f"untraceable: {', '.join(bad[:10])}")
        if aid == "states_confidence":
            m = re.search(r"confidence|trust|reliab|довір|надійн|впевнен", low)
            return bool(m), m.group(0) if m else "no confidence statement"
        if aid == "mentions_normalisation":
            m = re.search(r"share of|normali|per million|overall (wikipedia )?traffic|"
                          r"частк|нормаліз|на мільйон|загальн\w* трафік|трафік\w* (всієї|усієї)",
                          low)
            return bool(m), m.group(0) if m else "no mention of normalisation / overall traffic"
        if aid == "answers_in_user_language":
            ok = lang_ok(answer, ev["answer_language"])
            return ok, f"expected {ev['answer_language']}: {'ok' if ok else 'wrong language'}"
        if aid == "flags_missing_polish_article":
            m = re.search(r"(польськ|polish|\bpl\b)[^.\n]{0,120}(немає|відсутн|не має|нема|"
                          r"не існує|no (dedicated )?article|missing)|(немає|відсутн)[^.\n]{0,80}"
                          r"(польськ|\bpl\b)", low)
            return bool(m), m.group(0)[:120] if m else "does not say the pl article is missing"
        if aid == "mentions_statistical_test":
            m = re.search(r"p\s*[=<]\s*0|p-value|значущ|significan|mann|манна", low)
            return bool(m), m.group(0) if m else "no statistical backing"
        if aid == "pdf_one_page":
            pdfs = list(out.glob("*.pdf"))
            if not pdfs:
                return False, "no PDF produced"
            pages = {p.name: pdf_pages(p) for p in pdfs}
            return any(v == 1 for v in pages.values()), json.dumps(pages)
        if aid == "all_languages_covered":
            if not ans:
                return False, "no analysis.json"
            langs = set(ans[-1]["params"]["langs"])
            need = set(ev["required_langs"])
            return need <= langs, f"final analysis langs: {sorted(langs)}"
        if aid == "custom_weights":
            for c in bash:
                m = re.search(r"--weights[= ]\"?'?([\w=.,]+)", c)
                if m:
                    w = dict(x.split("=") for x in m.group(1).split(",") if "=" in x)
                    ok = float(w.get("volume", 0.3)) > float(w.get("growth", 0.5))
                    return ok, f"--weights {m.group(1)}"
            return False, "no --weights used"
        if aid == "gives_ranking":
            m = re.search(r"(^|\n)\s*(1\.|1\)|#1|\*\*1)|перш\w* (за )?черг|пріоритет|first|рейтинг|ранг",
                          low)
            return bool(m), m.group(0).strip() if m else "no ordered recommendation"
        if aid == "caveat_not_purchase_intent":
            m = re.search(r"willingness to pay|purchase|pay for|paying|revenue|monetiz|"
                          r"платити|купівел|платоспроможн", low)
            return bool(m), m.group(0) if m else "no views-vs-payment caveat"
        raise KeyError(aid)

    exps = []
    for a in ev["assertions"]:
        passed, evidence = check(a["id"])
        exps.append({"text": a["text"], "passed": bool(passed), "evidence": evidence})
    n_pass = sum(e["passed"] for e in exps)
    return {
        "expectations": exps,
        "summary": {"passed": n_pass, "failed": len(exps) - n_pass, "total": len(exps),
                    "pass_rate": round(n_pass / len(exps), 3)},
        "execution_metrics": {"tool_calls": dict(tools),
                              "total_tool_calls": sum(tools.values()),
                              "output_chars": len(all_answers)},
        # timing/tokens are read by aggregate_benchmark from the sibling timing.json
    }


def main() -> None:
    it_dir = Path(sys.argv[1])
    evals = {e["id"]: e for e in
             json.loads((SKILL_DIR / "evals" / "evals.json").read_text())["evals"]}
    for eval_dir in sorted(it_dir.glob("eval-*")):
        ev = evals[int(eval_dir.name.split("-")[1])]
        for run_dir in sorted(eval_dir.glob("*/run-*")):
            g = grade(run_dir, ev)
            (run_dir / "grading.json").write_text(json.dumps(g, ensure_ascii=False, indent=2))
            s = g["summary"]
            print(f"{eval_dir.name:32} {run_dir.parent.name:14} {s['passed']}/{s['total']}  "
                  + " ".join("✓" if e["passed"] else "✗" for e in g["expectations"]))


if __name__ == "__main__":
    main()
