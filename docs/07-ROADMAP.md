# LeadKhojo — Development Roadmap

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-30 |
| **Target** | v1.0 MVP in **15 working days**, one developer |
| **Depends on** | [02-PRD.md](02-PRD.md) |

---

## 1. Planning assumptions

| Assumption | Value |
|---|---|
| Team | **1 developer**, full-time |
| Duration | 15 working days (3 calendar weeks) |
| Productive hours | ~6 per day. A plan built on 8 is a plan that slips in week one. |
| Discovery provider decision | Made by **Day 3** — the only external blocker |
| Environment | Docker Desktop, Python 3.12, Node 20 already installed |

**The strategy in one line:** *the backend must be complete and usable from the command line by the end of Day 10.* If week three goes badly, there is still a working product — just without a browser UI. If the UI were built first, a slip would leave a beautiful shell with nothing behind it.

---

## 2. Phase overview

```
Week 1  ── THE SPINE ─────────────────────────────────────────
Day  1  Foundation: repo, Docker, database, config
Day  2  Job queue + scan orchestration skeleton
Day  3  Discovery (CSV import, then a real provider)
Day  4  Crawler part 1: fetch, robots, redirects, TLS
Day  5  Crawler part 2: DNS, page planning, Playwright fallback
        ✅ GATE: a real website produces a persisted SiteSnapshot

Week 2  ── THE INTELLIGENCE ──────────────────────────────────
Day  6  Contact extraction
Day  7  Technology detection
Day  8  Security analysis part 1: TLS + headers
Day  9  Security analysis part 2: DNS auth, cookies, content
Day 10  Opportunity Engine + Scoring + CSV export
        ✅ GATE: `make scan` produces a useful CSV of real businesses

Week 3  ── THE PRODUCT ───────────────────────────────────────
Day 11  Frontend: scaffold, scan form, live progress
Day 12  Frontend: results table, sorting, filtering
Day 13  Frontend: business detail with evidence
Day 14  PDF reports
Day 15  Hardening, docs, ship
        ✅ GATE: v1.0 release criteria met
```

---

## 3. Week 1 — The spine

### Day 1 — Foundation

- Repo scaffold per [Folder Structure](04-FOLDER-STRUCTURE.md)
- `docker-compose.yml`: Postgres + API; `Makefile` with `dev`, `test`, `lint`, `migrate`
- `core/config.py` (Pydantic Settings), `core/logging.py`, `core/errors.py`
- SQLAlchemy async setup, Alembic initialized
- All nine models + first migration
- FastAPI app factory, `/healthz`, `/readyz`
- CI: ruff, mypy, pytest on push

**Done when:** `make dev` brings up Postgres and the API on a clean machine, `/healthz` returns 200, and CI is green on an empty PR.

### Day 2 — Job queue and orchestration

- `core/jobs.py`: `JobQueue` protocol, `PostgresJobQueue`, the `FOR UPDATE SKIP LOCKED` claim query
- `workers/pool.py`: async worker pool started in the FastAPI lifespan
- Job handlers registry; stale-lock sweeper
- `scans` module: models, repository, service, `POST /scans`, `GET /scans/{id}/progress`
- Job types stubbed end to end with fake work

**Done when:** `POST /scans` returns 202, a worker picks the job up, progress advances through the stub, and killing the process mid-scan then restarting resumes it.

> This is the least visible day of the project and the one that makes every later day possible. Resist the urge to skip ahead to crawling.

### Day 3 — Discovery

- `DiscoveryProvider` protocol
- **`CsvImportProvider` first** — zero external dependencies, unblocks everything downstream
- `POST /imports/csv/validate` and `POST /imports/csv`
- Canonical-domain deduplication (public-suffix aware)
- Then the chosen real provider (`GooglePlacesProvider` or `OpenStreetMapProvider`)
- Provider failure → recorded on the scan, not fatal

**Done when:** a CSV of 20 domains creates a scan with 20 deduplicated businesses, and the configured live provider returns real results for "dental clinics, Austin".

> **Blocker resolves today.** If the paid provider decision (PRD Q1) is unresolved, ship OSM as the default and move on. Do not lose a day waiting.

### Day 4 — Crawler part 1

- `SiteSnapshot`, `PageCapture`, `TlsInfo`, `DnsInfo` dataclasses — **freeze these shapes carefully**
- `fetcher.py`: httpx, redirect chain, timeouts, retries, `429`/`503` handling
- `robots.py`: fetch, parse, enforce
- `tls_collector.py`: certificate capture from the live connection
- `rate_limiter.py`: per-host concurrency 1, ≥ 1 s delay
- `SnapshotStore` + Postgres implementation
- `scripts/capture_snapshot.py`

**Done when:** crawling a real site persists a snapshot with homepage HTML, headers, redirect chain, and TLS details; a robots-disallowed path is provably never requested.

### Day 5 — Crawler part 2

- `dns_collector.py`: A, AAAA, MX, NS, TXT, CNAME, `_dmarc`, DNSSEC
- `page_planner.py`: known contact paths + link discovery, robots-filtered, capped at 8
- `renderer.py`: Playwright fallback with the < 500-visible-chars heuristic
- Cookie capture; typed failure reasons for all modes
- Playwright browsers baked into the Docker image
- **Capture 8–10 fixture snapshots** covering: WordPress, Shopify, a React SPA, expired SSL, no DMARC, a 500, a parked domain, a clean modern site

**Done when:** ✅ **Gate 1** — a 10-business CSV scan runs end to end and produces 10 snapshots. The fixture corpus exists and every analyzer test from here on is offline.

> The fixture corpus is the single most valuable artifact of week one. Every analyzer day depends on it. Do not shortcut it.

---

## 4. Week 2 — The intelligence

### Day 6 — Contact extraction

- Email extraction from `mailto:` and text; classification and filtering
- **Synthesis guard:** an architecture test asserting no code path constructs an address
- Phone extraction + E.164 normalization
- Address extraction (schema.org first, heuristics second)
- Social profile and contact-form detection
- Ranking so the primary contact is the best available
- Tests against every fixture

**Done when:** ≥ 60% of fixtures yield a business email, zero synthesized addresses exist, and every contact has a `source_url`.

### Day 7 — Technology detection

- Rule loader with JSON Schema validation at startup
- Signal matcher: meta, HTML pattern, header, cookie, script URL, path presence
- Version extraction; confidence assignment; evidence capture
- **Write ≥ 60 fingerprints** across the [PRD §6.1](02-PRD.md) categories
- `known_versions.yaml` and outdated comparison
- `GET /meta/technologies`

**Done when:** every fixture is correctly identified, WordPress reports version and outdated status with evidence, and adding a fingerprint requires no Python change.

> Timebox the fingerprints to four hours. Sixty good ones beat two hundred half-tested ones, and the file grows for free every week after launch.

### Day 8 — Security part 1

- Security rule loader and `Finding` model
- TLS checks `TLS-01` … `TLS-08`
- Header checks `HDR-01` … `HDR-07`
- **`tests/architecture/test_passive_only.py`** — asserts no TCP connection to any port besides 80/443
- `GET /businesses/{id}/findings`

**Done when:** the expired-SSL fixture produces `TLS-03` and `TLS-04` failures with exact dates in evidence, and the passive-only test passes.

### Day 9 — Security part 2

- DNS auth checks `DNS-01` … `DNS-07` (SPF parsing, DMARC policy extraction, DKIM best-effort)
- Cookie checks `CKY-01` … `CKY-03`
- Content checks `CNT-01` … `CNT-06` (mixed content, disclosure, form targets, login over HTTP)
- Privacy signals `PRV-01`, `PRV-02`
- Quality analyzer: performance from timings, mobile viewport
- Security score computation

**Done when:** all 28 checks run against every fixture, each returning a status, severity, evidence, and remediation. A site with no DNS records produces `not_applicable`, never a crash.

### Day 10 — Opportunities, scoring, CSV

- Opportunity rule loader and engine; multi-finding conditions
- **Write the 16 baseline rules** from [PRD §8.1](02-PRD.md)
- The specificity gate; deduplication and merging
- All four scores with breakdowns and confidence
- CSV writer with the full column set; `GET /exports/scans/{id}/csv`
- `scripts/run_scan.py` — full CLI scan

**Done when:** ✅ **Gate 2** — `python scripts/run_scan.py --csv domains.csv` scans 20 real businesses and writes a CSV that opens correctly in Excel, averaging ≥ 2 opportunities per site, with manual review of 10 rows finding no generic filler.

> **This is the real milestone.** At the end of Day 10 the product works. Everything after this makes it pleasant.

---

## 5. Week 3 — The product

### Day 11 — Frontend foundation

- Vite + React + TypeScript + Tailwind scaffold
- `make generate-client` (OpenAPI → TypeScript), wired into CI
- API client wrapper, error normalization, TanStack Query setup
- App shell and routing
- **New Scan page**: form + CSV upload with validation preview
- **Live progress**: 2 s polling, per-business status, current business name

**Done when:** a scan can be started from the browser and progress updates visibly without a refresh.

### Day 12 — Results table

- Sortable columns for all four scores
- Filters: opportunity category, has-contact, minimum score, status
- Score badges with colour-coded severity
- Opportunity chips per row
- Rows appear as they complete, before the scan ends
- Export button

**Done when:** a 50-business scan is browsable, sortable, and filterable while it is still running.

### Day 13 — Business detail

- Contacts panel with source links
- Technology panel grouped by category, version and outdated flags
- Security findings grouped by severity
- **Evidence disclosure** — expandable on every finding
- Opportunities with pitch angles
- Score breakdowns showing every component
- Empty and failure states that explain themselves

**Done when:** every finding's evidence is visible in two clicks and a failed business explains why it failed.

### Day 14 — PDF reports

- ReportLab styles and layout primitives
- Business report: cover, scores, findings by severity with evidence, opportunities in plain language, technical appendix
- Scan summary: ranked list plus aggregate statistics
- Export endpoints and UI wiring

**Done when:** a generated PDF is judged presentable enough to attach to a real client email — by a human looking at it, not by a test.

### Day 15 — Hardening and ship

- Work the [release criteria](02-PRD.md#14-release-criteria-for-v10) as a checklist
- Full scan of 50 real businesses; measure against every NFR target
- Fix whatever the real run exposes (it will expose something)
- README quick start verified on a clean machine
- `.env.example` completed; startup warning when binding to `0.0.0.0`
- Tag `v1.0.0`

**Done when:** ✅ **Gate 3** — every release criterion is checked and a fresh clone reaches a working scan in under 15 minutes.

---

## 6. Critical path

```
Foundation → Job queue → Discovery → Crawler → Fixtures
     → Analyzers → Opportunities → Scoring → CSV
          → Frontend → PDF → Ship
```

Almost everything is on it. That is the nature of a 15-day pipeline product: each stage consumes the previous stage's output.

**The two genuinely parallel tracks:**

| Track | Can be done during | Why it floats |
|---|---|---|
| Writing fingerprints and rules | Any evening, any lull | Pure data, no code dependency |
| Capturing fixture snapshots | From Day 5 onward | More fixtures always help; never blocks |

**The one true external blocker:** the discovery-provider decision, needed by Day 3. Everything else is under the developer's control.

---

## 7. Risks

| # | Risk | Likelihood | Response |
|---|---|---|---|
| R1 | Crawler edge cases eat Day 5 (weird redirects, anti-bot pages, timeouts) | **High** | Accept partial snapshots. A snapshot with only DNS and TLS still produces findings. Do not chase perfection. |
| R2 | Playwright is slow or flaky in Docker | Medium | The httpx path covers most sites. If Playwright fights back, ship without it and mark JS-heavy sites `render_failure`. |
| R3 | Discovery provider costs or terms are unacceptable | Medium | CSV import already works. Ship with CSV + OSM; add the paid provider post-launch. |
| R4 | Fingerprint writing expands to fill available time | **High** | Hard four-hour timebox on Day 7. The file grows forever after launch; it does not need to be complete on Day 7. |
| R5 | Frontend takes four days, not three | Medium | Cut scan history (FR-UI-8) and column selection (FR-EXPORT-7) first. |
| R6 | PDF layout fights back on Day 14 | Medium | Ship a plain, well-structured report. Visual polish is a v1.1 afternoon. |
| R7 | Opportunities read as generic filler | **High — the product risk** | The specificity gate is built on Day 10, not retrofitted. Manually review 10 outputs before Gate 2. If they read as filler, fix rules before touching the UI. |

**R7 is the one that actually matters.** R1–R6 delay the launch. R7 means the product ships and nobody uses it twice.

---

## 8. If you fall behind

Cut in this order. Each line is a real feature; each is survivable.

| Order | Cut | Consequence |
|---|---|---|
| 1 | Scan history page (FR-UI-8) | The user re-runs from the form |
| 2 | CSV column selection (FR-EXPORT-7) | Fixed column set |
| 3 | Scan summary PDF (FR-EXPORT-4) | Per-business PDF is the one that gets emailed |
| 4 | Playwright fallback (FR-CRAWL-9) | SPAs report `render_failure` — visible and honest |
| 5 | Quality analyzer / website score | Three scores instead of four |
| 6 | Live progress detail (FR-UI-3) | A plain progress bar. **Painful — cut last.** |

**Never cut:** contact extraction, security analysis, the Opportunity Engine, CSV export, or evidence display. Those five *are* the product.

---

## 9. Daily discipline

Small habits that keep a 15-day solo sprint from drifting.

- **Commit at least twice a day.** A day's work in one commit is a day's work at risk.
- **Write the test with the code, not after.** For analyzers this costs nothing — fixtures already exist.
- **Run the real thing daily** from Day 5. Scan real sites. Bugs found on real sites are the only bugs that matter.
- **Capture a fixture every time something surprises you.** That is how the corpus grows and how a bug never returns.
- **Ship the ugly version first.** A working plain page beats a beautiful unfinished one.
- **Keep a `NOTES.md` of deferred decisions.** Write down what you skipped so week three has a real punch list instead of a vague unease.

---

## 10. Definition of Done — per feature

- [ ] Acceptance criteria met and demonstrated on a real site
- [ ] Unit tests for logic; fixture tests for analyzers
- [ ] Errors handled — an analyzer never raises
- [ ] Evidence attached to every finding
- [ ] `ruff` and `mypy --strict` clean
- [ ] Architecture tests still pass (no I/O in analyzers, no email synthesis, passive-only)
- [ ] OpenAPI regenerated if the contract changed
- [ ] Docs updated if behavior changed

---

## 11. After v1.0

Sequenced by what earns its place, not by what is fun to build. Details in the [Release Plan](13-RELEASE-PLAN.md).

| Version | Focus | Trigger |
|---|---|---|
| v1.1 | Fingerprint and rule expansion, bug fixes from real use | Immediately after launch |
| v1.2 | Saved projects, scan history, re-scan and diff | First user asks "what changed since last month?" |
| v2.0 | **Outreach Assistant** (Anthropic API, `claude-opus-5`; deterministic template fallback) | Users are copying findings into emails by hand |
| v3.0 | Multi-user SaaS: auth, teams, billing, quotas — see [SaaS Migration Plan](12-SAAS-MIGRATION-PLAN.md) | A second person needs their own account |
| v4.0 | **Monitoring**: watch a portfolio, alert on certificate expiry and stack changes | The strongest long-term position — recurring value, recurring revenue |
| v5.0 | CRM integrations (push out, not become one) | Users ask for it by name |
