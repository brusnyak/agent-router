"""Read-only leadgen child: exit if parent dies, PAUSE appears or night ends.

Executed under sandbox-exec by night.py with no credential environment.
Only stdlib imports; never starts another process or worker.
"""
import datetime as dt
import os
from pathlib import Path
import runpy
import sys
import threading
import time
from zoneinfo import ZoneInfo


def should_stop(parent, paths, hour, now, deadline):
    return (os.getppid() != parent or any(Path(p).exists() for p in paths)
            or not (hour >= 23 or hour < 7) or now >= deadline)


def main():
    parent = int(sys.argv[1])
    script = Path(sys.argv[2]).resolve()
    paths = os.environ['BACKBONE_PAUSE_FILES'].split(':')
    deadline = time.monotonic() + 600
    tz = ZoneInfo('Europe/Bratislava')

    def watch():
        while True:
            if should_stop(parent, paths, dt.datetime.now(tz).hour, time.monotonic(), deadline):
                os._exit(124)  # kill request threads too; no teardown can send or write elsewhere
            time.sleep(0.1)

    threading.Thread(target=watch, daemon=True).start()
    sys.argv = sys.argv[2:]
    sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name='__main__')


if __name__ == '__main__':
    main()
