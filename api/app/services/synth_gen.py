from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from random import Random
from typing import List, Tuple


MERCHANTS = [
    "Uber",
    "Lyft",
    "United",
    "Delta",
    "Marriott",
    "Hilton",
    "Starbucks",
    "Amazon",
    "Local Taxi",
    "Airbnb",
]
CATEGORIES = ["Travel", "Meals", "Lodging", "Supplies", "Entertainment"]
CITIES = ["NYC", "SFO", "LON", "BOS", "SEA", "ATL"]
CHANNELS = ["card", "reimbursement", "cash"]


def _rand_ts(rng: Random) -> int:
    # Between ~2023-11 and ~2025-06 in epoch seconds
    return rng.randint(1_700_000_000, 1_750_000_000)


def _gen_amount(rng: Random) -> float:
    # Rough normal-like via Irwin-Hall central limit trick
    s = sum(rng.uniform(-1, 1) for _ in range(6)) / 6.0
    base = 80 + s * 40
    if rng.random() < 0.02:
        base *= rng.uniform(3, 10)
    base = abs(base)
    base = max(1.0, min(5000.0, base))
    return round(base, 2)


def _default_data_dir() -> str:
    # Prefer explicit DATA_DIR; else use project-local data/synth folder
    env = os.environ.get("DATA_DIR")
    if env:
        return env
    try:
        base = Path.cwd() / "data" / "synth"
        base.mkdir(parents=True, exist_ok=True)
        return str(base)
    except Exception:
        return tempfile.gettempdir()


def generate_synth(rows: int, seed: int | None = None) -> Tuple[str, List[dict]]:
    rng = Random(seed)
    tmpdir = _default_data_dir()
    os.makedirs(tmpdir, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="synth_txns_", suffix=".csv", dir=tmpdir)
    os.close(fd)
    headers = [
        "txn_id",
        "employee_id",
        "merchant",
        "city",
        "category",
        "amount",
        "timestamp",
        "channel",
        "card_id",
    ]
    preview: List[dict] = []
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for i in range(rows):
            txn_id = f"T{i:012d}"
            employee_id = f"E{rng.randint(1, 4999):06d}"
            merchant = rng.choice(MERCHANTS)
            city = rng.choice(CITIES)
            category = rng.choice(CATEGORIES)
            amount = _gen_amount(rng)
            ts = _rand_ts(rng)
            # Keep ISO-8601 for readability
            iso_ts = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            channel = rng.choice(CHANNELS)
            card_id = f"C{rng.randint(1, 99999):08d}"
            row = [
                txn_id,
                employee_id,
                merchant,
                city,
                category,
                f"{amount:.2f}",
                iso_ts,
                channel,
                card_id,
            ]
            w.writerow(row)
            if i < 10:
                preview.append(
                    {
                        "txn_id": txn_id,
                        "employee_id": employee_id,
                        "merchant": merchant,
                        "city": city,
                        "category": category,
                        "amount": float(f"{amount:.2f}"),
                        "timestamp": iso_ts,
                        "channel": channel,
                        "card_id": card_id,
                    }
                )
    try:
        from .trainer import set_last_dataset_path

        set_last_dataset_path(path)
    except Exception:
        pass
    return path, preview
