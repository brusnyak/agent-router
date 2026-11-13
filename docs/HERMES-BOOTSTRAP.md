# Brief for Hermes: install and run agent-router yourself

Written 2026-11-13 by Claude for the owner. You (Hermes) do the install and decide the details. Nobody else installs it on this VM from now on. Everything below was verified on 2026-11-13 unless marked UNKNOWN.

## What exists already (read first)
| Item | State |
|---|---|
| Repo | private `brusnyak/agent-router`, branch `dev/backbone` |
| Your git access | ssh deploy key, **read-write, this repo only**, host alias `github-agent-router` in `~/.ssh/config`. Clone URL: `git@github-agent-router:brusnyak/agent-router.git` |
| Your `gh` login | account `brusnyak` (fine-grained token). It has admin on `memory-vault` (vault pushes work). It cannot see `agent-router`. For `gh pr create` the owner must add that repo to the token (Contents and Pull requests read/write). Until then push a branch and tell the owner. |
| A copy Claude made before this brief | `~/agent-router-dev`: a clone at commit `a3e02bd` with a venv and the 134 packages from `requirements.txt` installed. No service, no config. Decide yourself: `git pull` and reuse it, or delete it and clone fresh. Check `git status` first. |
| The running service | `agent-router.service` (`backbone daemon --poll 5 --parallel 2`) runs OLD code from `~/agent-router`, env from `~/.config/agent-router/env`. Backups: `~/backups/agent-router-pre-github-*.tgz` and a copy of the unit file. |
| Keys | The router env has `NIM_1`, `NIM_2`, `NIM_3`. **`NIM_2` is yours** (same value as your `NVIDIA_API_KEY`). The router's agents use **`NIM_1` and `NIM_3` only**. Never print key values. |

## Do, in this order (stop at the first failed check and report the command and its output)
1. `cd ~/agent-router-dev && git status && git pull` (or re-clone). Check: `git log -1` shows the latest commit of `dev/backbone`.
2. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` if not already done. Check: `.venv/bin/python -m backbone --help` lists `run fanout swarm doctor librarian router-report`.
3. Run the test suite **in the background** (about 2 minutes), never in the foreground: `nohup .venv/bin/python -m pytest tests -q -p no:cacheprovider > ~/pytest.log 2>&1 &`. Check: the log ends with `passed` and no `failed`. Two tests used to call the real NVIDIA API; they are now offline.
4. Write `~/.agent-router/backbone.yaml` (the router reads it before the repo default). Copy `config/backbone.yaml` and set `nim.keys: [NIM_1, NIM_3]`. Keep `rpm_limit: 40`: the router counts requests per key per minute, waits briefly when a key is full, and fails over to the other key. There is no 2-call cap and no fixed cooldown. Check: `.venv/bin/python -m backbone keys` shows only those two.
5. `.venv/bin/python -m backbone doctor` and read which workers are usable on this VM (probably none of claude/codex/kilo; the NIM `pi` and `fanout`/`swarm` paths are what matter here).
6. Try one cheap multi-agent run through the router: `.venv/bin/python -m backbone fanout "<harmless prompt A>" "<harmless prompt B>"`. In `swarm` the planner chooses how many sub-agents (1 to 8); workers never start workers. Report the output and which keys were used.
7. Decide whether to move `agent-router.service` to the new clone. If yes: back up the unit file again, change `WorkingDirectory` and `ExecStart`, `systemctl --user daemon-reload && systemctl --user restart agent-router`, check `is-active`, keep the rollback line (restore the unit copy and restart). If unsure, leave the old service running and say so.

## Your skill
Design and install your own `agent-router` skill for the agents you choose (Nina, Mimoza or both). A draft Claude wrote is at `docs/hermes-skills/agent-router/SKILL.md`; it is input, not an order. Keep your skill format and conventions.

## Browser
- Ego (the owner's signed-in browser) is **macOS-only today**; Linux is on its roadmap. It cannot run on this aarch64 VM. Do not install Chromium or Playwright: the owner does not want that.
- Path A (owner approved): run the router hub on this VM, loopback only (`backbone serve --port 8799`, needs `BACKBONE_TOKEN`: create it, keep it only in `~/.config/agent-router/env`, never print it). The Mac connects outbound with `backbone node --hub http://127.0.0.1:8799 --name mac` over an `ssh -L 8799:127.0.0.1:8799 oracle-vm` tunnel. Then `@node:mac @browser Read <url>` runs in Ego on the Mac. It works only while the Mac is on and the node is running. Prefer your own tools when they are enough.
- **Path B (owner: "just use this one"): Lightpanda, installed by you.** https://github.com/lightpanda-io/browser , release 1.0.4 (2026-11-13), AGPL-3.0, not Chromium, V8 JavaScript, no rendering (no screenshots). Tested by Claude on the Mac: official macOS binary sha256 equals the release digest; `fetch --dump markdown` returned a JavaScript-rendered page (quotes.toscrape.com/js, 5 quotes) in 1.3 s at about 34 MB peak. Not yet tested on this VM. Install plan for you: download the `lightpanda-aarch64-linux` asset (or `lightpanda_1.0.4_arm64.deb`) from the release into a NEW directory under `~/tools`, verify its sha256 against the digest shown by `gh release view 1.0.4 -R lightpanda-io/browser --json assets`, `chmod +x`, then smoke-test from another directory: `lightpanda fetch --dump markdown https://example.com`, the same on `https://news.ycombinator.com` and `https://quotes.toscrape.com/js/` (check that at least 3 quotes appear). The VM has glibc 2.39; the build needs 2.38. Subcommands: `fetch`, `serve` (CDP), `mcp`, `agent`, `run`. `fetch` has `--cookie <file>` (load) and `--cookie-jar <file>` (save), so cookie sessions are possible. Run it unmodified and internal-only (AGPL: no changes, no public network service). Report the smoke-test numbers.
- **Fallback chain** (research, not yet tested): Lightpanda first; for pages it fails on, a non-Chromium full browser (Playwright-Firefox, Ubuntu 24.04 arm64 support unverified; Camoufox for bot-blocking sites, its README warns it may not suit stable production); for signed-in pages, the Mac Ego node (Path A). Details and sources: `research/2026-11-13-oracle-browsers.md`. Lightpanda's issue tracker has no `crash` or `js` labels, so its real failure rate is unknown: your smoke test is the evidence.

## Git rules
- Push to branches named `hermes/<topic>`. Never force-push. Do not push to `main`. The owner merges.
- Vault updates keep using your existing flow (`vault-sync`).
- Do not commit secrets, `.env`, `data/`, `logs/` or `eval/heldout*` (private; already gitignored).

## Stop and ask the owner before
Spending money, sending anything to a third party, deleting files you did not create, changing auth, DNS or mail, switching the Telegram channel off, touching `nginx`, and any change to `hermes-ui` (that has its own process: the `hermes-change` skill).

## Report
Result first, at most 8 lines: what ran, the check output, what is next. Put long output in a vault page and name its path. Unknowns go in an UNKNOWN list.

## UNKNOWN
- Whether `nim.keys` in the user config needs the full block or only the key list (read `backbone/core.py`, `load_config`).
- Whether the hub and node need `BACKBONE_TOKEN` in both env files (read `backbone/serve.py` and `backbone/node.py`).
- Which of the two webchat relays should talk to the router (see the owner's separate chat-UI task).
