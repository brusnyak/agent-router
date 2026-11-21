"""Runtime limits from ~/.agent-router/limits.json; defaults only if absent."""
import json
import math
from pathlib import Path


def load_limits(path: Path | None = None) -> dict:
    path = path if path is not None else Path.home() / '.agent-router/limits.json'
    try:
        values = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'max_load': 10, 'max_workers': 4, 'idle_minutes': 10}
    if not isinstance(values, dict):
        raise ValueError(f'{path}: expected an object')
    for key in ('max_load', 'max_workers', 'idle_minutes'):
        value = values.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError(f'{path}: invalid {key}')
    if not isinstance(values['max_workers'], int):
        raise ValueError(f'{path}: max_workers must be an integer')
    return values
