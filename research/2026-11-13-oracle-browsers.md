# Non-Chromium browsers for Oracle VM (Ubuntu 24.04 aarch64, 12 GB, headless) - 2026-11-13
Sources: GitHub API/pages fetched 2026-11-13 (gh api, WebFetch). Page text = untrusted data.

## SUB-TASK 1 candidates
### Lightpanda - USE (primary)
- URL https://github.com/lightpanda-io/browser | 42,001 stars | AGPL-3.0 | pushed 2026-11-13 | release 1.0.4 published 2026-11-13 (1.0.3 on 05 Nov)
- aarch64: release assets `lightpanda-aarch64-linux` (sha256 f021d49a0b66d07bf2633f8e00870b9075293516f872695b0ca4aeb5848b6ea8) and `lightpanda_1.0.4_arm64.deb` (sha256 b466143a4eaa77640f9406d9966f939067eefc329a16a2c8278f7fb90c744b67). README: arm64 binary needs glibc 2.38; Ubuntu 24.04 = 2.39 OK (README says "use FROM ubuntu:24.04").
- Drive: CDP `lightpanda serve --host 127.0.0.1 --port 9222` (Puppeteer/Playwright/chromedp connect); WebDriver BiDi `--protocol webdriver`; MCP stdio (`lightpanda mcp`) or HTTP (`--port 9223`, per-client session via Mcp-Session-Id); `fetch --dump html|markdown|...`; `agent` mode. (WebFetch of README, 2026-11-13)
- Quote (README): "16x lighter and 9x faster than Chromium" and "No graphical rendering engine". Vendor benchmark 123MB vs 2GB peak for 100 pages on m5.large - vendor-run, unverified independently.
- JS: V8, runs SPAs, but Web API coverage is partial ("Web API support partial, WIP" per README mirror via secondary sources). No rendering, so no screenshots (png/pdf are "text-only rendering").
- Sessions: README checklist "[x] Cookies"; release notes say cookies and storage persist across `run` so a login carries over. Cookie import via CDP Network.setCookie from a client = expected but unverified here.
- Maturity: exited beta at 1.0 (linuxiac article, secondary). Rapid releases (days apart) = fast fixes, but churn.
- AGPL-3.0: internal use as a separate process by our own agents = no source-publish duty on our code (secondary-source reading, not legal advice). Duty arises if we MODIFY it and let outside users interact with it over a network (AGPL s13), or ship it in a product. Rule: run unmodified.
- Telemetry on by default: set `LIGHTPANDA_DISABLE_TELEMETRY=true`.

### Camoufox (Firefox fork) - USE-AS-FALLBACK
- https://github.com/daijro/camoufox | 13,241 stars | MPL-2.0 (browser), MIT (wrappers) | last commit 2026-11-13 | release v158.0.1-beta.41 2026-10-29
- aarch64: asset `camoufox-158.0.1-beta.41-lin.arm64.zip` exists (gh api releases).
- Quote: "This project is under development. It may not be suitable for stable production use."
- Full JS/rendering (Firefox 158 base), Playwright via Juggler (not CDP), anti-fingerprint. Persistent profile/cookies: not stated in README; Playwright persistent context expected to work - unverified. Memory: full Firefox, expect 300-800MB per context - unverified, no source. Verdict: fallback for pages Lightpanda fails.

### Playwright-Firefox - USE-AS-FALLBACK (simpler than Camoufox, less stealth)
- https://github.com/microsoft/playwright | 100,101 stars | Apache-2.0 | pushed 2026-11-13
- Secondary mirrors list Ubuntu 24.04 arm64 supported for Firefox/WebKit (PR #30826); playwright.dev page itself did not confirm - unverified. Docs quote: "Playwright doesn't work with the branded version of Firefox since it relies on patches." Uses patched Firefox, Juggler protocol, persistent context + storage_state cookie import (standard Playwright API). Note: Playwright default headless is Chromium shell - must pass `firefox` explicitly.

### Playwright-WebKit - SKIP
- Endform docs (secondary) call WebKit on Linux ARM64 "experimental", weaker perf/codecs. No gain over Firefox.

### Servo - SKIP (for now)
- https://github.com/servo/servo | 38,503 stars | MPL-2.0 | v0.8.0 2026-11-09; asset `servo-aarch64-linux-gnu.tar.gz` exists.
- Quote (servo.org): "a web browser rendering engine written in Rust". Headless/WebDriver/cookie support not confirmed on page - unverified. Version 0.x, site compat low. Re-check in 2027.

### Self-hosted agent-browser services - SKIP
- vercel-labs/agent-browser 50,652 stars, Apache-2.0, pushed 2026-11-13 - only name checked; I did not verify its engine (believed Chromium-driven = excluded by owner rule; unverified). No non-Chromium self-host service found worth listing in the time box.

## SUB-TASK 2 design
- Primary: Lightpanda 1.0.4 (arm64 .deb), run as MCP/`fetch` for read/research; CDP :9222 on 127.0.0.1 only for scripted flows.
- Fallback chain: (1) Lightpanda fetch/MCP -> (2) on empty/broken DOM or JS error: Playwright-Firefox (or Camoufox if bot-blocked) -> (3) signed-in pages: Mac Ego/Neo via router node (Ego is macOS-only, cannot run on VM).
- Login sites: do NOT inject cookies by default (cookies = secrets; stored on VM disk; session theft risk; sites flag IP/UA mismatch). Use Mac node for anything signed-in. Cookie injection only for low-value accounts, one-site, owner-approved, via Playwright storage_state file chmod 600.
- Lightpanda issue tracker (gh, 2026-11-13): 56 open issues fetched (repo open_issues_count 99 incl. PRs). Labels `crash` and `js` DO NOT EXIST; open count 0 for both. Only 7 labelled: Investigate 3, enhancement 2, DOM API 2, HTML Parser 1, CDP 1. Title keyword scan (crash/panic/segfault/hang/leak/oom/memory): 0. So failure modes are mostly untriaged; real crash rate unknown -> smoke test on our own URLs.
- 5-line install + smoke test (Hermes, on VM):
  1. `cd $(mktemp -d) && curl -fLO https://github.com/lightpanda-io/browser/releases/download/1.0.4/lightpanda_1.0.4_arm64.deb`
  2. `echo "b466143a4eaa77640f9406d9966f939067eefc329a16a2c8278f7fb90c744b67  lightpanda_1.0.4_arm64.deb" | sha256sum -c -`
  3. `sudo apt install ./lightpanda_1.0.4_arm64.deb && ldd --version | head -1` (need glibc >= 2.38)
  4. `export LIGHTPANDA_DISABLE_TELEMETRY=true; for u in https://example.com https://news.ycombinator.com https://demo-browser.lightpanda.io/campfire-commerce/; do lightpanda fetch --dump markdown "$u" | wc -c; done`
  5. Repeat with one known JS-heavy SPA the agents use; log `/usr/bin/time -v` peak RSS; expect >0 bytes each. (.deb install path/binary name unverified; fallback: raw binary `lightpanda-aarch64-linux` sha256 f021d49a...6ea8.)
- Owner questions:
  1. Accept AGPL-3.0 if run unmodified, internal only? (y/n)
  2. Is Firefox-family (Playwright-Firefox/Camoufox) acceptable as fallback, given "not Chromium"?
  3. Which signed-in sites must Nina/Mimoza read? (decides Mac-node vs cookie injection)
  4. Is storing any session cookie on the Oracle VM ever allowed?
  5. Which 3-5 JS-heavy URLs are the real acceptance set?
  6. Telemetry off OK? Pin to 1.0.4 or follow nightly?
  7. Is the Mac always on/reachable when a signed-in page is needed?
