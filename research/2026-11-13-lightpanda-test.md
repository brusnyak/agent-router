# Lightpanda headless browser test (1.0.4, aarch64-macos)

sha256: 83b0ba5ae31086b675fb3ba50644bda075a13bebabe46dc5f7543952bc41ae46

Binary: /Users/yegor/.agent-router/tools/lightpanda-1.0.4/lightpanda-aarch64-macos

## Subcommands (from --help)

agent, completion, fetch, help, mcp, run, serve, version

## Fetch results

Each page fetched with `--dump markdown`, 60s timeout, run under `/usr/bin/time -l` from /tmp.
Peak MB = maximum resident set size from `time -l`, bytes / 1048576.

| page | exit | seconds | bytes | peak MB | JS content present |
|---|---|---|---|---|---|
| https://example.com | 0 | 0.35 | 1344 | 27.6 | n/a |
| https://news.ycombinator.com | 0 | 1.06 | 19438 | 28.5 | n/a |
| https://quotes.toscrape.com/js/ | 0 | 1.26 | 1728 | 33.6 | yes (5 quotes rendered, e.g. Einstein, Rowling, Austen) |

## Persistent login session

Yes. `fetch --help` documents `--cookie <PATH>` (load cookies, CDP/Puppeteer JSON or Netscape cookies.txt, read-only) and `--cookie-jar <PATH>` (save cookies on exit, write-only), so cookie-based persistent sessions appear supported.
