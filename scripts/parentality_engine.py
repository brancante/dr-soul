#!/usr/bin/env python3
"""Parentality preview engine for Dr. Frankenstein.

Purpose:
- Only run instincts when a child exists.
- Evaluate child scores against thresholds.
- Emit suggested parent actions (complementary).
- Re-check scores and close instinct context when improved.

This script is intentionally OpenClaw-core agnostic: it only outputs JSON plans.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


ScoreMap = Dict[str, int]


@dataclass
class ThresholdBand:
    name: str
    min: int
    max: int


BANDS = [
    ThresholdBand("monitor", 0, 39),
    ThresholdBand("soft", 40, 69),
    ThresholdBand("active", 70, 84),
    ThresholdBand("urgent", 85, 100),
]


PARENT_ACTIONS = {
    "parentA": {
        "fear": "Talk calmly, validate emotion, guide one grounding breath cycle.",
        "anger": "De-escalate tone, acknowledge frustration, suggest a pause.",
        "bonding": "Initiate warm check-in and reaffirm relationship safety.",
        "protection": "Provide emotional safety and reassure child it is not alone.",
    },
    "parentB": {
        "learning": "Break problem into 1 small lesson + 1 practice step.",
        "hunger": "Give one concrete task with clear reward and completion signal.",
        "protection": "Apply practical safeguards, boundaries, and contingency plan.",
    },
}


def clamp_score(v: int) -> int:
    return max(0, min(100, int(v)))


def band_for_score(score: int) -> str:
    for band in BANDS:
        if band.min <= score <= band.max:
            return band.name
    return "monitor"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def evaluate_child(state: dict) -> dict:
    child = state.get("child")
    if not child:
        return {
            "hasChild": False,
            "status": "no-child",
            "message": "No child generated yet. Parenting instincts stay inactive.",
            "events": [],
        }

    scores: ScoreMap = {k: clamp_score(v) for k, v in (child.get("scores") or {}).items()}
    events = []
    for metric, score in scores.items():
        level = band_for_score(score)
        if level == "monitor":
            continue
        events.append({"metric": metric, "score": score, "level": level})

    return {
        "hasChild": True,
        "status": "ok",
        "childId": child.get("id"),
        "stage": child.get("stage"),
        "scores": scores,
        "events": sorted(events, key=lambda e: e["score"], reverse=True),
    }


def build_instinct_plan(eval_result: dict) -> dict:
    if not eval_result.get("hasChild"):
        return {
            "enabled": False,
            "reason": "no-child",
            "crons": [],
            "suggestions": [],
        }

    events = eval_result.get("events", [])
    if not events:
        return {
            "enabled": True,
            "reason": "stable",
            "crons": [],
            "suggestions": [],
        }

    suggestions: List[dict] = []
    for ev in events:
        metric = ev["metric"]
        level = ev["level"]
        if metric in PARENT_ACTIONS["parentA"]:
            suggestions.append(
                {
                    "parent": "parentA",
                    "metric": metric,
                    "level": level,
                    "action": PARENT_ACTIONS["parentA"][metric],
                }
            )
        if metric in PARENT_ACTIONS["parentB"]:
            suggestions.append(
                {
                    "parent": "parentB",
                    "metric": metric,
                    "level": level,
                    "action": PARENT_ACTIONS["parentB"][metric],
                }
            )

    now = datetime.now(timezone.utc).isoformat()
    crons = [
        {
            "name": "parentality-keepalive-check",
            "kind": "every",
            "everyMinutes": 20,
            "purpose": "Recompute child scores and detect threshold crossings.",
        },
        {
            "name": "parentality-instinct-intervention",
            "kind": "event-or-poll",
            "everyMinutes": 10,
            "purpose": "Trigger parent-specific complementary intervention suggestions.",
            "enabledWhen": "child exists AND any score >= soft threshold",
        },
        {
            "name": "parentality-recovery-check",
            "kind": "every",
            "everyMinutes": 20,
            "purpose": "Compare post-action score against previous and close instinct context when improved.",
            "startedAt": now,
        },
    ]

    return {
        "enabled": True,
        "reason": "threshold-crossed",
        "crons": crons,
        "suggestions": suggestions,
    }


def close_context_if_improved(previous: dict, current: dict, min_improvement: int = 8) -> dict:
    prev_scores: ScoreMap = previous.get("scores", {})
    cur_scores: ScoreMap = current.get("scores", {})
    improvements = {}
    unresolved = []

    for metric, prev in prev_scores.items():
        cur = cur_scores.get(metric, prev)
        delta = prev - cur
        improvements[metric] = delta
        if band_for_score(prev) != "monitor" and delta < min_improvement and band_for_score(cur) != "monitor":
            unresolved.append(metric)

    return {
        "improvements": improvements,
        "resolved": len(unresolved) == 0,
        "unresolved": unresolved,
        "nextAction": "exit-instinct-context" if len(unresolved) == 0 else "continue-or-escalate",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Dr. Frankenstein parentality preview engine")
    parser.add_argument("--state", required=True, help="Path to parentality-preview state JSON")
    parser.add_argument("--previous", help="Optional previous evaluation JSON for recovery checks")
    parser.add_argument("--out", help="Output path for generated plan JSON")
    args = parser.parse_args()

    state_path = Path(args.state)
    state = load_json(state_path)

    eval_result = evaluate_child(state)
    plan = build_instinct_plan(eval_result)
    output = {
        "evaluatedAt": datetime.now(timezone.utc).isoformat(),
        "evaluation": eval_result,
        "plan": plan,
    }

    if args.previous:
        prev = load_json(Path(args.previous))
        output["recovery"] = close_context_if_improved(prev.get("evaluation", {}), eval_result)

    if args.out:
        save_json(Path(args.out), output)
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
