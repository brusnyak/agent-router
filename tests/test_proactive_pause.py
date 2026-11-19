import sys
import threading
from pathlib import Path
import pytest
from backbone import guard
from backbone.workspace import run_group


def test_pause_terminates_running_worker(tmp_path):
    flag = tmp_path / 'PAUSE'
    timer = threading.Timer(.15, lambda: flag.write_text('stop'))
    timer.start()
    try:
        with pytest.raises(guard.Blocked, match='paused during worker'):
            run_group([sys.executable, '-c', 'import time;time.sleep(20)'], str(tmp_path), 10,
                      env={'BACKBONE_WATCH_PAUSE':'1','BACKBONE_PAUSE_FILES':str(flag)})
    finally:
        timer.join()


def test_idle_loss_terminates_worker(tmp_path, monkeypatch):
    from backbone import idle_policy
    snapshots=iter([idle_policy.Snapshot(700,True,0,False),idle_policy.Snapshot(0,True,0,False)])
    monkeypatch.setattr(idle_policy,'current_snapshot',lambda: next(snapshots))
    with pytest.raises(guard.Blocked, match='idle eligibility lost'):
        run_group([sys.executable,'-c','import time;time.sleep(20)'],str(tmp_path),10,
                  env={'BACKBONE_WATCH_PAUSE':'1','BACKBONE_PAUSE_FILES':'','BACKBONE_WATCH_IDLE':'1'})
