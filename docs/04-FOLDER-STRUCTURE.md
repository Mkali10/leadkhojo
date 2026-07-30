# LeadKhojo — Folder Structure

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-30 |
| **Depends on** | [03-ARCHITECTURE.md](03-ARCHITECTURE.md) |

---

## 1. Top level

```
leadkhojo/
├── backend/                 Python — FastAPI API + in-process workers
├── frontend/                React SPA
├── rules/                   YAML rule packs (fingerprints, checks, opportunities)
├── docs/                    This documentation
├── scripts/                 Developer and operational scripts
├── docker/                  Dockerfiles and container config
├── .github/workflows/       CI
├── docker-compose.yml       Full local stack
├── Makefile                 Canonical task entrypoints
├── .env.example             Every variable, documented, no real values
├── .gitignore
├── .editorconfig
└── README.md
```

**Why `rules/` is at the top level, not inside `backend/`.** Rule packs are the product's knowledge base, not application code. They are edited far more often than the Python, they are reviewed by different eyes, and they may eventually be distributed or user-extended. Keeping them out of the source tree makes that boundary visible.

---

## 2. Backend

```
backend/
├── src/leadkhojo/
│   ├── __init__.py
│   ├── main.py                  FastAPI app factory; starts the worker pool in lifespan
│   ├── cli.py                   Run a scan without the UI
│   │
│   ├── core/                    Cross-cutting. Imports NOTHING from above it.
│   │   ├── config.py            Pydantic Settings — all env vars, validated at boot
│   │   ├── constants.py         MAX_PAGES_PER_SITE, timeouts, UA string
│   │   ├── logging.py           Structured JSON logging
│   │   ├── errors.py            Exception hierarchy + FastAPI handlers
│   │   ├── types.py             Domain, Url, Email, E164Phone, Severity, FindingStatus
│   │   ├── findings.py          Finding — the shared currency of every plugin
│   │   ├── jobs.py              JobQueue protocol + PostgresJobQueue + worker loop
│   │   └── utils/
│   │       ├── domains.py       Public-suffix-aware canonicalization
│   │       ├── urls.py          Normalization, joining, same-site checks
│   │       ├── phones.py        E.164 parsing
│   │       ├── text.py          Visible-text extraction, normalization
│   │       ├── versions.py      Version comparison that survives "5.4.2-beta"
│   │       └── clock.py         UTC-only helpers; injected, never ambient
│   │
│   ├── db/
│   │   ├── base.py              DeclarativeBase, naming convention, TimestampMixin
│   │   ├── models.py            All ORM models (9 tables — small enough for one file)
│   │   ├── session.py           Async engine + sessionmaker
│   │   └── repository.py        BaseRepository
│   │
│   ├── crawler/                 ── ONLY NETWORK COMPONENT ────────
│   │   ├── snapshot.py          SiteSnapshot, PageCapture, TlsInfo, DnsInfo
│   │   ├── service.py           CrawlerService.crawl(url) -> SiteSnapshot
│   │   ├── fetcher.py           httpx, redirects, timeouts, retries, SSRF guard
│   │   ├── renderer.py          Playwright fallback
│   │   ├── robots.py            robots.txt fetch + parse + enforce
│   │   ├── page_planner.py      Which pages to fetch (capped, robots-filtered)
│   │   ├── dns_collector.py     A/AAAA/MX/NS/TXT/CNAME/_dmarc
│   │   ├── tls_collector.py     Certificate + protocol capture
│   │   ├── rate_limiter.py      Per-host concurrency + delay
│   │   ├── guards.py            Private-address rejection (SSRF) — before every connect
│   │   └── storage.py           SnapshotStore protocol + Postgres implementation
│   │
│   ├── plugins/                 ── CORE ENGINE + PLUGINS · NO I/O ──
│   │   ├── base.py              Plugin, PluginMeta, PluginContext, PluginResult, PluginKind
│   │   ├── engine.py            Registry, topological sort, isolation, timing
│   │   ├── registry.py          Explicit built-in registration (ADR-14)
│   │   ├── rules.py             YAML rule-pack loading + JSON Schema validation
│   │   └── builtin/
│   │       ├── ssl_plugin.py            TLS-01 … TLS-08
│   │       ├── dns_plugin.py            DNS-01 … DNS-07 (SPF, DMARC, DKIM)
│   │       ├── headers_plugin.py        HDR-01 … HDR-07, CKY-01 … CKY-03
│   │       ├── technologies_plugin.py   fingerprint matching
│   │       ├── cms_plugin.py            depends_on: technologies
│   │       ├── performance_plugin.py    timings, mobile viewport
│   │       ├── contacts_plugin.py       email / phone / address / social / forms
│   │       ├── opportunities_plugin.py  SYNTHESIZER — deterministic (§9)
│   │       └── reports_plugin.py        REPORTER — CSV + PDF
│   │
│   ├── opportunities/           ── DETERMINISTIC ENGINE ──────────
│   │   ├── schemas.py           Opportunity, Urgency, OpportunityCategory
│   │   ├── engine.py            Rules → Evidence → Opportunity
│   │   ├── conditions.py        Condition evaluation against findings/artifacts
│   │   ├── merge.py             Deduplicate / merge overlapping
│   │   └── rewriter.py          OpportunityRewriter protocol + NullRewriter
│   │                            ↑ the ONLY place AI may ever touch. Rewrite-only.
│   │
│   ├── discovery/
│   │   ├── schemas.py           DiscoveryQuery, DiscoveredBusiness
│   │   ├── service.py           Provider selection + dedup
│   │   ├── dedup.py             Canonical-domain deduplication
│   │   └── providers/
│   │       ├── base.py          DiscoveryProvider protocol
│   │       ├── csv_import.py    ← build this FIRST
│   │       ├── google_places.py
│   │       └── openstreetmap.py
│   │
│   ├── scoring/                 ── FOUR INDEPENDENT SCORES ───────
│   │   ├── schemas.py           Scores, ScoreBreakdown
│   │   ├── engine.py
│   │   ├── lead.py
│   │   ├── website.py
│   │   ├── security.py
│   │   └── opportunity.py
│   │
│   ├── export/
│   │   ├── csv_writer.py
│   │   ├── pdf/
│   │   │   ├── business_report.py
│   │   │   ├── scan_summary.py
│   │   │   └── styles.py
│   │   └── service.py
│   │
│   ├── pipeline/                ── ORCHESTRATION ─────────────────
│   │   ├── runner.py            discover → crawl → engine → score → persist
│   │   └── tasks.py             Job handlers
│   │
│   ├── api/
│   │   ├── deps.py
│   │   ├── middleware.py
│   │   ├── routers/
│   │   │   ├── scans.py
│   │   │   ├── businesses.py
│   │   │   ├── exports.py
│   │   │   ├── meta.py          Introspect loaded plugins and rules
│   │   │   └── health.py
│   │   └── openapi.py
│   │
│   └── workers/
│       ├── pool.py              Async worker pool, started in lifespan
│       └── handlers.py          job type → handler mapping
│
├── alembic/
│   ├── env.py
│   └── versions/
│
├── tests/
│   ├── conftest.py              DB fixtures, snapshot loaders, factories
│   ├── fixtures/
│   │   └── snapshots/           ← REAL captured snapshots. The test corpus.
│   │       ├── wordpress_outdated.json
│   │       ├── shopify_clean.json
│   │       ├── expired_ssl.json
│   │       ├── no_dmarc.json
│   │       ├── spa_react.json
│   │       ├── broken_500.json
│   │       └── parked_domain.json
│   ├── unit/                    Mirrors src/. No DB, no network.
│   ├── plugins/                 One file per plugin. Each runs in isolation.
│   │   ├── test_ssl_plugin.py
│   │   ├── test_dns_plugin.py
│   │   ├── test_headers_plugin.py
│   │   ├── test_technologies_plugin.py
│   │   ├── test_cms_plugin.py           deps stubbed, never really run
│   │   ├── test_performance_plugin.py
│   │   ├── test_contacts_plugin.py
│   │   └── test_opportunities_plugin.py
│   ├── integration/             Real Postgres via testcontainers
│   ├── e2e/                     Full scan against a local fixture server
│   └── architecture/
│       ├── test_no_io_in_plugins.py        ← the load-bearing test
│       ├── test_plugin_isolation.py        ← plugins never import each other
│       ├── test_ai_boundary.py             ← AI cannot produce a finding
│       ├── test_import_boundaries.py
│       ├── test_no_email_synthesis.py
│       └── test_passive_only.py            ← no port besides 80/443
│
├── pyproject.toml               Deps + ruff + mypy + pytest config
├── uv.lock
└── alembic.ini
```

### 2.1 The most important file in the repository

`tests/architecture/test_no_io_in_analyzers.py`.

It walks the AST of every module under `analyzers/` and fails the build on any import of `httpx`, `requests`, `socket`, `dns`, `ssl`, `urllib`, `subprocess`, or `open`, and on any use of a database session.

It exists because [ADR-02](03-ARCHITECTURE.md) is the architecture, and an architecture that is only a convention is not an architecture. Someone will eventually need "just one more DNS lookup" inside a check. This test is the answer.

### 2.2 Why `src/` layout

Forces the package to be installed rather than imported from the working directory. Tests then run against the *installed* package, so missing `__init__.py` files and packaging mistakes fail in CI rather than in production.

---

## 3. Rules

```
rules/
├── technology/
│   ├── cms.yaml               WordPress, Drupal, Joomla, Wix, Squarespace, …
│   ├── ecommerce.yaml         WooCommerce, Shopify, Magento, PrestaShop, …
│   ├── frontend.yaml          React, Angular, Vue, Next, jQuery, Bootstrap, …
│   ├── backend.yaml           Laravel, Django, Rails, Express, ASP.NET, …
│   ├── server.yaml            Nginx, Apache, LiteSpeed, IIS
│   ├── cdn_waf.yaml           Cloudflare, Akamai, Fastly, Sucuri, …
│   ├── hosting.yaml           AWS, Azure, GCP, DigitalOcean, GoDaddy, …
│   ├── analytics.yaml         GA4, GTM, Meta Pixel, Hotjar, Matomo, …
│   └── known_versions.yaml    Latest known version per technology
│
├── security/
│   ├── tls.yaml               TLS-01 … TLS-08
│   ├── headers.yaml           HDR-01 … HDR-07
│   ├── dns.yaml               DNS-01 … DNS-07
│   ├── cookies.yaml           CKY-01 … CKY-03
│   ├── content.yaml           CNT-01 … CNT-06
│   └── privacy.yaml           PRV-01 … PRV-02
│
├── opportunities/
│   ├── security.yaml
│   ├── performance.yaml
│   ├── maintenance.yaml
│   ├── development.yaml
│   └── marketing.yaml
│
└── schema/                    JSON Schema for each rule type — validated at startup
    ├── technology.schema.json
    ├── security.schema.json
    └── opportunity.schema.json
```

**Rules are validated at application startup, not first use.** A malformed rule file fails the boot loudly. Discovering it mid-scan, on someone's fortieth site, is strictly worse.

---

## 4. Frontend

```
frontend/
├── src/
│   ├── main.tsx
│   ├── App.tsx                Router setup
│   │
│   ├── pages/                 One file per route. Composition only.
│   │   ├── NewScanPage.tsx
│   │   ├── ScanResultsPage.tsx
│   │   ├── BusinessDetailPage.tsx
│   │   └── ScanHistoryPage.tsx
│   │
│   ├── features/              All domain logic lives here
│   │   ├── scan/
│   │   │   ├── api.ts
│   │   │   ├── hooks.ts       useCreateScan, useScanProgress (polling)
│   │   │   └── components/
│   │   │       ├── ScanForm.tsx
│   │   │       ├── CsvUpload.tsx
│   │   │       └── ScanProgress.tsx
│   │   ├── results/
│   │   │   ├── api.ts
│   │   │   ├── hooks.ts
│   │   │   └── components/
│   │   │       ├── ResultsTable.tsx
│   │   │       ├── ScoreBadge.tsx
│   │   │       ├── OpportunityChips.tsx
│   │   │       └── ResultsFilters.tsx
│   │   ├── business/
│   │   │   └── components/
│   │   │       ├── ContactPanel.tsx
│   │   │       ├── TechStackPanel.tsx
│   │   │       ├── SecurityFindings.tsx
│   │   │       ├── OpportunityList.tsx
│   │   │       ├── ScoreBreakdown.tsx
│   │   │       └── EvidenceDisclosure.tsx
│   │   └── export/
│   │       ├── api.ts
│   │       └── components/ExportMenu.tsx
│   │
│   ├── components/            Generic. Knows nothing about the domain.
│   │   ├── ui/                Button, Input, Select, Badge, Card, Dialog
│   │   ├── layout/            AppShell, PageHeader
│   │   └── feedback/          ErrorBoundary, Spinner, EmptyState, Toast
│   │
│   ├── lib/
│   │   ├── api/
│   │   │   ├── client.ts      Fetch wrapper, error normalization
│   │   │   └── generated.ts   ← GENERATED from OpenAPI. Never hand-edit.
│   │   ├── format.ts          Dates, durations, scores, byte sizes
│   │   └── severity.ts        Severity → colour/label mapping
│   │
│   ├── hooks/                 useDebounce, useLocalStorage
│   └── styles/globals.css     Tailwind entry
│
├── tests/
│   ├── unit/
│   └── e2e/                   Playwright
│
├── index.html
├── vite.config.ts
├── tsconfig.json              strict: true, noUncheckedIndexedAccess: true
├── tailwind.config.ts
└── package.json
```

### 4.1 `pages/` vs `features/` vs `components/`

The most common structural question, so the rule is explicit:

- **`pages/`** — reads route params, composes feature components, sets the title. Over ~120 lines means logic belongs in `features/`.
- **`features/`** — all data fetching, business logic, and domain-aware components. Never imports from `pages/`.
- **`components/`** — no domain knowledge. If it imports a domain type, it belongs in `features/`.

### 4.2 The generated API client

`lib/api/generated.ts` is produced from the backend's OpenAPI spec by `make generate-client`. It is committed so builds are reproducible and diffs are reviewable, but never hand-edited. CI regenerates it and fails if the result differs from what is committed — which makes an unannounced backend contract change impossible to merge quietly.

---

## 5. Supporting directories

```
docker/
├── backend.Dockerfile         Multi-stage; Playwright browsers baked in
├── frontend.Dockerfile        Build → nginx
├── nginx.conf
└── postgres/init.sql          Extensions

scripts/
├── capture_snapshot.py        Crawl one URL → save as a test fixture ← use constantly
├── run_scan.py                CLI scan without the UI
├── validate_rules.py          Lint every rule pack
├── seed_dev_data.py           Sample scan for frontend work
└── generate_client.py         OpenAPI → TypeScript
```

**`capture_snapshot.py` is the highest-leverage script in the repository.** Every analyzer bug starts as "this real site produced the wrong answer." Capture it, commit it as a fixture, write a failing test, fix it. The test corpus grows with every bug and never shrinks.

---

## 6. Naming conventions

| Item | Convention | Example |
|---|---|---|
| Python file | `snake_case.py` | `page_planner.py` |
| Python class | `PascalCase` | `CrawlerService` |
| Python function | `snake_case` | `extract_emails` |
| Python constant | `UPPER_SNAKE` | `MAX_PAGES_PER_SITE` |
| DB table | `snake_case`, plural | `security_findings` |
| DB column | `snake_case`, singular | `scanned_at` |
| DB index | `ix_<table>__<cols>` | `ix_businesses__scan_id` |
| DB unique | `uq_<table>__<cols>` | `uq_businesses__scan_domain` |
| Rule ID | `<PREFIX>-<nn>` | `TLS-04`, `DNS-03` |
| Technology ID | `snake_case` | `wordpress`, `google_analytics` |
| Opportunity ID | `snake_case` | `ssl_renewal`, `email_security_hardening` |
| React component | `PascalCase.tsx` | `SecurityFindings.tsx` |
| React hook | `useCamelCase` | `useScanProgress` |
| TS type | `PascalCase`, no `I` prefix | `SiteSnapshot` |
| TS non-component file | `kebab-case.ts` | `severity.ts` |
| Env var | `LK_` + `UPPER_SNAKE` | `LK_DATABASE_URL` |
| Job type | `snake_case` | `analyze_business` |

---

## 7. Where does this file go?

| I'm writing… | It goes in… |
|---|---|
| A new API endpoint | `modules/<module>/router.py` |
| Logic behind that endpoint | `modules/<module>/service.py` |
| A database query | `modules/<module>/repository.py` |
| A new technology fingerprint | `rules/technology/<category>.yaml` — **not Python** |
| A new security check | `rules/security/<category>.yaml` + a fixture test |
| A new opportunity rule | `rules/opportunities/<category>.yaml` |
| Something that needs a network call | `modules/crawler/` — **nowhere else in the pipeline** |
| Interpretation of crawled data | `modules/analyzers/<domain>/` |
| A helper used by 3+ modules | `core/utils/` |
| A background job | `modules/<module>/tasks.py` + register in `workers/handlers.py` |
| A generic React component | `components/ui/` |
| A domain-aware React component | `features/<feature>/components/` |
| A page | `pages/` — composition only |
| A test fixture from a real site | `tests/fixtures/snapshots/` via `capture_snapshot.py` |
| A test for a pure function | `tests/unit/` mirroring the source path |
| A test needing a database | `tests/integration/` |
| A test enforcing a boundary rule | `tests/architecture/` |
| A one-off data fix | `scripts/` — never a migration |
