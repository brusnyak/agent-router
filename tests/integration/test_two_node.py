"""Run the same hermetic dispatch harness on this node and an opt-in SSH node."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from backbone import contract


pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not os.environ.get("BACKBONE_IT_HOST"),
                                 reason="BACKBONE_IT_HOST is not set")]


HARNESS = '''
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    os.environ['AGENT_ROUTER_HOME'] = str(root)
    module = root / 'contract.py'
    module.write_text(SOURCE)
    spec = importlib.util.spec_from_file_location('dispatch_contract', module)
    c = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = c
    spec.loader.exec_module(c)
    stub = root / 'worker.py'
    stub.write_text('import sys; sys.exit(int(sys.argv[1]))\\n')
    for code, expected in ((0, 'PASS'), (1, 'CRASH'), (124, 'TIMEOUT')):
        calls = [0]
        def runner(*args, **kwargs):
            calls[0] += 1
            proc = subprocess.run([sys.executable, str(stub), str(code)],
                                  capture_output=True, text=True, timeout=5)
            return {'ok': proc.returncode == 0,
                    'error': 'timeout' if proc.returncode == 124 else 'worker exited 1'}
        task = c.TaskContract('stub run', 'stub', idempotency_key=str(code), retry_backoff_s=0)
        first = c.run_contract(task, runner)
        assert first['outcome'] == expected, first
        assert calls[0] == (1 if code == 0 else 3), calls
        second = c.run_contract(task, runner)
        assert second['outcome'] == ('RACE_LOST' if code == 0 else expected), second
        rows = [json.loads(line) for line in (root / 'data/outcomes.jsonl').read_text().splitlines()]
        matching = [row for row in rows if row['idempotency_key'] == str(code)]
        assert len(matching) == 1, matching
    print(json.dumps({'outcomes': len(rows), 'codes': [0, 1, 124]}))
'''


def test_two_node():
    host = os.environ["BACKBONE_IT_HOST"]
    assert re.fullmatch(r"[\w][\w.@:-]*", host), "invalid SSH host"
    source = "SOURCE = " + repr(Path(contract.__file__).read_text()) + "\n" + HARNESS
    for command in ([sys.executable, "-"],
                    ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "python3", "-"]):
        result = subprocess.run(command, input=source, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout) == {"outcomes": 3, "codes": [0, 1, 124]}
