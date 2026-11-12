import sys

from .cli import main

try:
    main()
except RuntimeError as e:
    if "no NIM keys" in str(e):
        sys.exit(f"{e}\nrun: ~/.claude/scripts/with-env NIM_1 NIM_2 NIM_3 -- python3 -m backbone ...")
    raise
