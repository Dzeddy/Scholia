"""Free Spaced Repetition Scheduler (FSRS v4.5) implementation for Scholia."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

# Standard FSRS-4.5 default parameters (17 weights)
FSRS_WEIGHTS = (
    0.4072,
    1.1829,
    3.1262,
    15.4722,
    7.2102,
    0.5316,
    1.0651,
    0.0234,
    1.616,
    0.1544,
    1.0824,
    1.9813,
    0.0953,
    0.2975,
    2.2042,
    0.2407,
    2.9466,
)

DECAY = -0.5
FACTOR = 19.0 / 81.0
REQUEST_RETENTION = 0.90


@dataclass
class FSRSState:
    stability: float
    difficulty: float
    reps: int
    lapses: int
    scheduled_days: int
    due_at: str
    last_review_at: str


def _clamp_difficulty(d: float) -> float:
    return max(1.0, min(10.0, d))


def retrievability(elapsed_days: float, stability: float) -> float:
    if stability <= 0.0:
        return 0.0
    if elapsed_days <= 0.0:
        return 1.0
    return (1.0 + FACTOR * elapsed_days / stability) ** DECAY


def next_interval_days(stability: float, target_retention: float = REQUEST_RETENTION) -> int:
    if stability <= 0.0:
        return 1
    raw = (stability / FACTOR) * (target_retention ** (1.0 / DECAY) - 1.0)
    return max(1, min(3650, int(round(raw))))


def rating_label(rating: int) -> str:
    return {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}.get(rating, "Good")


def schedule_fsrs(
    stability: float,
    difficulty: float,
    reps: int,
    lapses: int,
    last_review_at: Optional[str],
    rating: int,
    now: Optional[datetime] = None,
) -> FSRSState:
    """Compute updated FSRS stability, difficulty, and next review timestamp.

    rating: 1 = Again, 2 = Hard, 3 = Good, 4 = Easy.
    """
    rating = max(1, min(4, int(rating)))
    w = FSRS_WEIGHTS
    current = now or datetime.now(timezone.utc)

    if reps <= 0 or stability <= 0.0:
        # Initial review
        new_stability = max(0.2, w[rating - 1])
        new_difficulty = _clamp_difficulty(w[4] - math.exp(w[5] * (rating - 1)) + 1.0)
        new_reps = 1
        new_lapses = lapses + (1 if rating == 1 else 0)
        sched_days = 1 if rating == 1 else next_interval_days(new_stability)
    else:
        elapsed = 1.0
        if last_review_at:
            try:
                prev_dt = datetime.fromisoformat(last_review_at.replace("Z", "+00:00"))
                elapsed = max(0.0, (current - prev_dt).total_seconds() / 86400.0)
            except ValueError:
                elapsed = 1.0

        r = retrievability(elapsed, stability)
        d0_good = _clamp_difficulty(w[4] - math.exp(w[5] * 2.0) + 1.0)
        raw_d = difficulty - w[6] * (rating - 3)
        new_difficulty = _clamp_difficulty(w[7] * d0_good + (1.0 - w[7]) * raw_d)

        if rating == 1:
            # Lapse
            new_lapses = lapses + 1
            new_reps = reps + 1
            s_fail = (
                w[11]
                * (new_difficulty ** (-w[12]))
                * ((stability + 1.0) ** w[13] - 1.0)
                * math.exp(w[14] * (1.0 - r))
            )
            new_stability = max(0.2, min(stability, s_fail))
            sched_days = 1
        else:
            new_lapses = lapses
            new_reps = reps + 1
            hard_penalty = w[15] if rating == 2 else 1.0
            easy_bonus = w[16] if rating == 4 else 1.0
            s_inc = (
                math.exp(w[8])
                * (11.0 - new_difficulty)
                * (stability ** (-w[9]))
                * (math.exp(w[10] * (1.0 - r)) - 1.0)
                * hard_penalty
                * easy_bonus
            )
            new_stability = max(0.5, stability * (1.0 + s_inc))
            sched_days = next_interval_days(new_stability)

    due_dt = current + timedelta(days=sched_days)
    return FSRSState(
        stability=round(new_stability, 3),
        difficulty=round(new_difficulty, 3),
        reps=new_reps,
        lapses=new_lapses,
        scheduled_days=sched_days,
        due_at=due_dt.isoformat(),
        last_review_at=current.isoformat(),
    )
