#!/usr/bin/env python3
"""Run eval prompts through headless Claude Code on a cheap model.

Each run gets its own empty sandbox directory. In the `with_skill` config the
sandbox has `.claude/skills/wikipedia-pageviews` symlinked to this skill; in
`without_skill` it has nothing, so the baseline must improvise.

    python evals/run_eval.py --workspace /tmp/ws --iteration 1
    python evals/run_eval.py --workspace /tmp/ws --iteration 2 --evals 3,4 --configs with_skill

Layout (compatible with skill-creator's aggregate_benchmark / eval viewer):
    <ws>/iteration-N/eval-<id>-<name>/eval_metadata.json
    <ws>/iteration-N/eval-<id>-<name>/<config>/run-1/{outputs/, transcript.jsonl,
                                                     transcript.md, timing.json}
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TOOLS = "Bash Read Write Edit Glob Grep Skill WebFetch WebSearch"


def claude(prompt: str, cwd: Path, model: str, resume: str | None) -> list[dict]:
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json",
           "--verbose", "--allowedTools", TOOLS, "--setting-sources", "project",
           "--strict-mcp-config"]
    if resume:
        cmd += ["--resume", resume]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=1800)
    events = []
    for line in proc.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    if not any(e.get("type") == "result" for e in events):
        events.append({"type": "result", "is_error": True, "result": proc.stderr[-2000:],
                       "duration_ms": 0, "usage": {}})
    return events


def to_markdown(turns: list[tuple[str, list[dict]]]) -> str:
    out = []
    for prompt, events in turns:
        out.append(f"## USER\n\n{prompt}\n")
        for e in events:
            if e.get("type") != "assistant":
                continue
            for block in e["message"].get("content", []):
                if block.get("type") == "text" and block["text"].strip():
                    out.append(f"**assistant:** {block['text']}\n")
                elif block.get("type") == "tool_use":
                    inp = block["input"]
                    shown = inp.get("command") or inp.get("file_path") or inp.get("skill") \
                        or json.dumps(inp, ensure_ascii=False)[:300]
                    out.append(f"`{block['name']}`: `{shown}`\n")
    return "\n".join(out)


def run_one(ws: Path, iteration: int, ev: dict, config: str, model: str, run: int = 1) -> str:
    eval_dir = ws / f"iteration-{iteration}" / f"eval-{ev['id']}-{ev['name']}"
    run_dir = eval_dir / config / f"run-{run}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    sandbox = run_dir / "sandbox"
    sandbox.mkdir(parents=True)
    (run_dir / "outputs").mkdir()
    eval_dir.joinpath("eval_metadata.json").write_text(json.dumps({
        "eval_id": ev["id"], "eval_name": ev["name"], "prompt": ev["prompt"],
        "followups": ev.get("followups", []),
        "assertions": [a["text"] for a in ev.get("assertions", [])],
    }, ensure_ascii=False, indent=2))
    if config == "with_skill":
        skills = sandbox / ".claude" / "skills"
        skills.mkdir(parents=True)
        (skills / "wikipedia-pageviews").symlink_to(SKILL_DIR)

    start = time.time()
    turns, session, tokens, cost = [], None, 0, 0.0
    for prompt in [ev["prompt"], *ev.get("followups", [])]:
        events = claude(prompt, sandbox, model, session)
        turns.append((prompt, events))
        res = next(e for e in events if e.get("type") == "result")
        session = res.get("session_id", session)
        u = res.get("usage", {})
        tokens += sum(u.get(k, 0) for k in ("input_tokens", "output_tokens",
                                             "cache_read_input_tokens",
                                             "cache_creation_input_tokens"))
        cost += res.get("total_cost_usd", 0) or 0
    elapsed = time.time() - start

    with open(run_dir / "transcript.jsonl", "w") as f:
        for i, (_, events) in enumerate(turns):
            for e in events:
                f.write(json.dumps({"turn": i, **e}, ensure_ascii=False) + "\n")
    (run_dir / "transcript.md").write_text(to_markdown(turns))
    answers = [next(e for e in ev_ if e.get("type") == "result").get("result", "")
               for _, ev_ in turns]
    (run_dir / "outputs" / "answer.md").write_text(
        "\n\n---\n\n".join(f"### Turn {i + 1}\n\n{a}" for i, a in enumerate(answers)))
    (run_dir / "outputs" / "final_answer.txt").write_text(answers[-1])
    for f in sandbox.rglob("*"):
        if f.is_file() and f.suffix in (".pdf", ".png", ".json", ".csv") and ".claude" not in f.parts:
            dest = run_dir / "outputs" / f.relative_to(sandbox).as_posix().replace("/", "__")
            shutil.copy2(f, dest)
    (run_dir / "timing.json").write_text(json.dumps({
        "total_tokens": tokens, "duration_ms": int(elapsed * 1000),
        "total_duration_seconds": round(elapsed, 1), "cost_usd": round(cost, 4),
        "model": model, "turns": len(turns)}, indent=2))
    return f"{eval_dir.name}/{config}/run-{run}: {elapsed:.0f}s, {tokens} tokens, ${cost:.3f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True, type=Path)
    ap.add_argument("--iteration", type=int, required=True)
    ap.add_argument("--evals", help="comma-separated ids (default: all)")
    ap.add_argument("--configs", default="with_skill,without_skill")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--runs", type=int, default=1, help="repetitions per eval x config")
    args = ap.parse_args()

    evals = json.loads((SKILL_DIR / "evals" / "evals.json").read_text())["evals"]
    if args.evals:
        wanted = {int(x) for x in args.evals.split(",")}
        evals = [e for e in evals if e["id"] in wanted]
    jobs = [(e, c, r) for e in evals for c in args.configs.split(",")
            for r in range(1, args.runs + 1)]
    with ThreadPoolExecutor(args.parallel) as pool:
        futures = [pool.submit(run_one, args.workspace, args.iteration, e, c, args.model, r)
                   for e, c, r in jobs]
        for f in as_completed(futures):
            print(f.result(), flush=True)


if __name__ == "__main__":
    main()
