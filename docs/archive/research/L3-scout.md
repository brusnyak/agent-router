# L3 scout: project #3 candidates (checked 2026-11-12 ~09:56 UTC)

Method: gh API issue/repo counts (live), Upwork find_jobs search (live, 2026-11-12), vault sweeps (2026-10-22 Upwork, 2026-11-05 postings). Mid-level SK/CZ search returned only 3 explicit mid-level roles. Reddit/HN search returned nothing usable.

## Candidates

1. **Postgres trigger support for Drizzle (`drizzle-triggers`-style plugin).** Define `BEFORE UPDATE` triggers next to table defs, generate migration SQL, test on real Postgres.
   - Demand: drizzle-team/drizzle-orm#843 "CREATE TRIGGER functions": 503 thumbs-up, 24 comments, open, labels `drizzle/kit`, `db/postgres` (gh api, 2026-11-12).
   - Existing: RagedPanda/drizzle-triggers, 2 stars, pushed 2026-11-08 (gh search). Niche open, competitor tiny.
   - Who pays / users: Drizzle users (drizzle-orm 36,283 stars). First 5 users = commenters on #843 and the RagedPanda repo, reached by a genuine comment with a working demo.
   - 2-week plan: d1-2 spec the trigger DSL; d3-6 SQL generator + drizzle-kit migration hook; d7-9 integration tests on Postgres via docker; d10-12 README, npm publish; d13-14 post on #843 with demo.
   - Skill proof: SQL/Postgres DDL, ORM internals, migrations, integration tests in Docker. Gap per earlier picker (Postgres/SQL missing from bp+router).
   - Kill rule: no outside install or reply on #843 within 14 days, or drizzle ships native trigger support first.
   - Objection: drizzle team can ship it natively; a 2-star competitor shows the bar is low, so there is no moat.

2. **Webhook debugger for dev (signature verify, replay, local forward).** Self-hosted; Stripe/GHL/Shopify-style payloads.
   - Demand: Upwork `find_jobs` title="webhook", verified payment, 2026-11-12: 10 rows, 9 at 20+ proposal tier, budgets $200-$300 fixed (e.g. CallHippo webhook $300, Stripe webhook fix row). Pain is real, but it is paid service work.
   - Who pays: freelance-market clients (services, not product). Free reach: unverified.
   - Objection: ngrok, Hookdeck, webhook.site already cover forwarding; big funded vendors (unverified: market share).
   - Kill rule: 3 non-owner installs in 7 days.

3. **Self-hosted SMTP/DNS deliverability checker (SPF/DKIM/DMARC + SES setup check).**
   - Demand: Upwork `title`="self-hosted": Mautic-to-SES job, 100 invites / 52 interviews (fixed $100, 50+ tier); self-hosted SMTP-IPv4 job at 15-20 tier. Paid-service signal only.
   - Objection: MXToolbox-type checkers exist (unverified: not checked this session). Low OSS reach.
   - Kill rule: no stranger run in 7 days.

4. **golangci-lint-action: lint results as PR review comments (contribute or standalone).**
   - Demand: golangci/golangci-lint-action#5 "Support comments instead of annotations": 406 thumbs-up, 17 comments, open. Repo 1,453 stars, pushed 2026-11-12.
   - Objection: overlaps owner-rejected "CI triage" family; reviewdog covers this space (unverified: not checked). Scores high on demand but low on fit.

5. **Per-job soft-fail for GitHub Actions (actions/runner#2347 "allow-failure").**
   - Demand: 1,468 thumbs-up, 188 comments, open.
   - Objection: GitHub-owned runner (big player); third-party action has no reach. Reject. Unverified: whether job-level `continue-on-error` already covers it.

6. **Python `uv upgrade` for pyproject (astral-sh/uv#6794).** 537 thumbs-up, 88 comments, open.
   - Objection: uv is Astral, 91,935 stars; head-on with big well-funded tool. Reject.

## Score (0-5 each; risk: 5 = high big-player risk; total = demand + reach + feasibility + CV-fit - risk; max 20)

| # | Candidate | Demand | Reach | 2-wk feas. | CV-fit | Big-player risk | Total |
|---|---|---|---|---|---|---|---|
| 1 | Drizzle Postgres triggers | 4 | 3 | 4 | 5 | 2 | 14 |
| 2 | Webhook debugger | 3 | 2 | 4 | 4 | 4 | 9 |
| 3 | SMTP/DNS checker | 2 | 2 | 4 | 3 | 3 | 8 |
| 4 | golangci PR comments | 4 | 3 | 4 | 2 | 2 | 11 |
| 5 | Actions allow-failure | 5 | 1 | 2 | 3 | 5 | 6 |
| 6 | uv upgrade | 4 | 4 | 2 | 2 | 5 | 7 |

## Pick: #1 Drizzle Postgres triggers

Verified: 503 thumbs-up on #843, open, Postgres label; tiny competitor exists. Unverified: whether drizzle-kit already supports triggers in its latest release; drizzle team roadmap.

Next check (5 min): read drizzle-kit release notes for "trigger" before any build. If shipped, drop to runner-up.

## Runner-up: #2 Webhook debugger

Score 9, lower than #4 (11) but #4 sits in the owner-rejected CI family, so #2 is the runner-up.

## Could not verify

- Reddit/HN demand for any candidate (search returned nothing).
- SK/CZ mid-level posting counts for each stack (only 3 explicit mid-level hits).
- Reviewdog overlap, MXToolbox overlap, drizzle-kit trigger status, job-level `continue-on-error` coverage.
- Tester pool size for any pick.
- Upwork demand is a freelance-services signal, not product demand.

Mentor: #843 is strong demand for a 36k-star tool, but "503 thumbs" means many people want it, not that they will install a plugin. Test the install, not the vote.
