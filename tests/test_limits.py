"""Limits contract, consumer integration, and source-of-truth regression gate."""
import json
from pathlib import Path
import re

import pytest

from backbone import bracket, idle_policy, limits, monitor


# Match policy thresholds, not availability checks such as load < 0 or indices.
NUMBER = r'[1-9]\d*(?:\.\d+)?'
LOAD = r'(?:\bload(?:1)?\b|\b(?:snapshot|snap)\s*(?:\.load|\[[\x27\"]load1?[\x27\"]\])|\bos\.getloadavg\(\)\[0\])'
PATTERNS = [
    re.compile(LOAD + r'\s*(?:[<>]=?|==|under|over|below|above)\s*' + NUMBER, re.I),
    re.compile(r'\bmax_load\s*(?::\s*(?:float|int)(?:\s*\|\s*None)?)?\s*=\s*' + NUMBER, re.I),
    re.compile(r'[\x27\"]max_load[\x27\"]\s*:\s*' + NUMBER, re.I),
]


def hardcoded_loads(paths):
    return [f'{path}:{lineno}: {line.strip()}'
            for path in paths if path.name != 'limits.py'
            for lineno, line in enumerate(path.read_text().splitlines(), 1)
            if any(pattern.search(line) for pattern in PATTERNS)]


def test_no_hardcoded_load_limits():
    root = Path(__file__).resolve().parents[1]
    rules = Path.home() / 'ai-context/rules'
    # The standalone product has no owner rules directory; scan it only where it exists.
    rule_files = sorted(rules.glob('*.md')) if rules.is_dir() else []
    paths = [*sorted((root / 'backbone').glob('*.py')), *rule_files]
    found = hardcoded_loads(paths)
    assert not found, 'Use see ~/.agent-router/limits.json:\n' + '\n'.join(found)


@pytest.mark.parametrize('text', [
    'load < 6', 'load > 10', 'load >= 10', 'load under 6',
    'max_load=10', 'max_load: float = 6', '"max_load": 10',
    'snapshot.load >= 10', 'snap["load1"] >= 10', 'os.getloadavg()[0] < 6.0',
])
def test_scanner_catches_literals(tmp_path, text):
    source = tmp_path / 'consumer.py'
    source.write_text(text)
    assert hardcoded_loads([source])


def test_scanner_allows_validation_and_config_reference(tmp_path):
    source = tmp_path / 'consumer.py'
    source.write_text('load < 0\nmax_load <= 0\nsee ~/.agent-router/limits.json\n')
    assert hardcoded_loads([source]) == []
    source = tmp_path / 'limits.py'
    source.write_text('max_load=10')
    assert hardcoded_loads([source]) == []


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    path = tmp_path / '.agent-router/limits.json'
    path.parent.mkdir()
    return path


def write_config(path, **changes):
    values = {'max_load': 3, 'max_workers': 2, 'idle_minutes': 2}
    values.update(changes)
    path.write_text(json.dumps(values))
    return values


def test_missing_file_only_uses_defaults(config):
    assert limits.load_limits() == {'max_load': 10, 'max_workers': 4, 'idle_minutes': 10}
    assert not config.exists()  # Reading never initializes or overwrites config.


def test_config_is_reread(config):
    assert write_config(config) == limits.load_limits()
    assert write_config(config, max_load=7) == limits.load_limits()


@pytest.mark.parametrize('text', ['{', '[]', '{}', 'null'])
def test_invalid_file_does_not_fall_back(config, text):
    config.write_text(text)
    with pytest.raises(ValueError):
        limits.load_limits()


@pytest.mark.parametrize('key,value', [
    ('max_load', 0), ('max_load', -1), ('max_load', True), ('max_load', '10'),
    ('max_load', float('nan')), ('max_load', float('inf')),
    ('max_workers', 1.5), ('max_workers', False), ('idle_minutes', 0),
])
def test_invalid_values(config, key, value):
    write_config(config, **{key: value})
    with pytest.raises(ValueError):
        limits.load_limits()


def test_permission_error_does_not_fall_back(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError('fixture')
    monkeypatch.setattr(Path, 'read_text', denied)
    with pytest.raises(PermissionError):
        limits.load_limits()


def test_policy_uses_current_config(config):
    write_config(config)
    snapshot = idle_policy.Snapshot(120, True, 2.99, False)
    assert idle_policy.decision(snapshot) == 'ready'
    assert idle_policy.decision(idle_policy.Snapshot(120, True, 3, False)) == 'load-high'
    assert idle_policy.decision(idle_policy.Snapshot(119, True, 2, False)) == 'active'
    write_config(config, idle_minutes=3)
    assert idle_policy.decision(snapshot) == 'active'
    assert idle_policy.decision(snapshot, min_idle=1, max_load=4) == 'ready'


def test_bracket_uses_current_config(config, monkeypatch):
    write_config(config)
    monkeypatch.setattr(bracket.os, 'getloadavg', lambda: (3, 0, 0))
    assert bracket.load_ok() is False
    write_config(config, max_load=4)
    assert bracket.load_ok() is True
    monkeypatch.setattr(bracket, 'paused', lambda: False)
    monkeypatch.setattr(bracket, 'ac_power', lambda: True)
    monkeypatch.setattr(bracket, 'interactive_claude', lambda: False)
    monkeypatch.setattr(bracket, 'idle_seconds', lambda: 119)
    monkeypatch.setattr(bracket, 'log', lambda event: None)
    assert bracket.tick()['state'] == 'idle-119s'
    write_config(config, max_load=4, idle_minutes=1)
    monkeypatch.setattr(bracket, 'load_queue', lambda path: [])
    monkeypatch.setattr(bracket, 'load_state', lambda: {'tasks': {}})
    assert bracket.tick()['state'] == 'complete'


def test_monitor_uses_current_config(config):
    write_config(config)
    assert 'warning' in monitor.ok_to_dispatch({'load1': 3, 'mem_avail_mb': 1000})[1]
    write_config(config, max_load=4)
    assert monitor.ok_to_dispatch({'load1': 3, 'mem_avail_mb': 1000}) == (True, 'resources available')
