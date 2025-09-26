from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Any, List

from .model_caps import MODEL_CAPS, probe_feature

PERSIST = Path('data') / 'model_caps.json'
PERSIST.parent.mkdir(parents=True, exist_ok=True)


def load_persisted() -> Dict[str, Any] | None:
    if not PERSIST.exists():
        return None
    try:
        return json.loads(PERSIST.read_text(encoding='utf-8'))
    except Exception:
        return None


def save_persisted(data: Dict[str, Any]) -> None:
    PERSIST.write_text(json.dumps(data, indent=2), encoding='utf-8')


def _list_openai_models(client) -> List[str]:
    try:
        models = client.models.list()
        out = []
        data = getattr(models, 'data', None) or (models.get('data') if isinstance(models, dict) else None)
        if data is not None:
            for m in data:
                mid = getattr(m, 'id', None) or (m.get('id') if isinstance(m, dict) else None)
                if mid:
                    out.append(mid)
        else:
            try:
                for m in models:
                    out.append(getattr(m, 'id', str(m)))
            except Exception:
                pass
        return out
    except Exception:
        return []


def probe_all_models() -> Dict[str, Any]:
    """Probe available models for supported features and persist results.

    Returns the probe result dictionary.
    """
    result: Dict[str, Any] = {
        'probed_at': int(time.time()),
        'models': {},
    }
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        # No key: persist default MODEL_CAPS for known models
        for m, caps in MODEL_CAPS.items():
            result['models'][m] = {**caps, 'probed': False}
        save_persisted(result)
        return result

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except Exception:
        # can't import client; persist defaults
        for m, caps in MODEL_CAPS.items():
            result['models'][m] = {**caps, 'probed': False}
        save_persisted(result)
        return result

    model_ids = _list_openai_models(client)
    # prefer known caps first
    seen = set()
    ordered = []
    for k in MODEL_CAPS.keys():
        if k in model_ids:
            ordered.append(k); seen.add(k)
    for mid in model_ids:
        if mid not in seen:
            ordered.append(mid); seen.add(mid)

    for mid in ordered:
        entry: Dict[str, Any] = MODEL_CAPS.get(mid, {'endpoint': 'responses', 'token_param': 'max_output_tokens'})
        # probe features we care about
        features = {}
        features['supports_json_mode'] = probe_feature(client, mid, 'json_mode')
        features['supports_tools'] = probe_feature(client, mid, 'tools')
        entry = {**entry, **features, 'probed': True}
        result['models'][mid] = entry

    save_persisted(result)
    return result


def schedule_probe_background() -> threading.Thread:
    t = threading.Thread(target=probe_all_models, daemon=True)
    t.start()
    return t
