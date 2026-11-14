import os
import sys

from .cli import main

if os.environ.pop("BACKBONE_SCRUB_PP", None):  # remote.py sets PYTHONPATH only for this process; children must not inherit it (broke hermes: pydantic_core)
    os.environ.pop("PYTHONPATH", None)

try:
    main()
except RuntimeError as e:
    if "no NIM keys" in str(e):
        sys.exit(f"{e}\nrun: ~/.claude/scripts/with-env NIM_1 NIM_2 NIM_3 -- python3 -m backbone ...")
    raise
