# LeadKhojo — Technical Architecture

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-30 |
| **Status** | Awaiting approval |
| **Depends on** | [02-PRD.md](02-PRD.md) |

---

## 1. Principles

Ordered. When two conflict, the earlier wins.

1. **Buildable by one developer in three weeks.** This is the hardest constraint and it removes more than it permits: no message broker, no auth system, no multi-tenancy, no service mesh, no abstraction that exists for a team we don't have.
2. **Crawl once, analyze many.** The crawler is the only component that touches the network. Everything downstream is a pure function over stored data. §3 explains why this single rule pays for itself repeatedly.
3. **Modules are independent.** Each has a defined interface and no knowledge of its siblings. Any one can become a service later without a rewrite (§12).
4. **Rules are data, not code.** Technology fingerprints, security checks, and opportunity rules live in YAML. Adding one is a data change.
5. **Total functions.** An analyzer never raises. Malformed HTML, missing headers, absent DNS — all produce a result. One broken site must not stop a scan.
6. **Evidence or nothing.** Every finding stores what was checked, what was seen, and when.
7. **Boring technology.** Postgres, FastAPI, React. The interesting problems are in the analyzers; that is where the novelty budget goes.
8. **Cloud-agnostic.** Everything runs with `docker compose up`.

---

## 2. Stack

### Backend

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12 | HTML parsing, network analysis, and rule engines are its home turf |
| API | FastAPI | Async-native, Pydantic validation, OpenAPI generated from code |
| ORM | SQLAlchemy 2.0 (async) | Explicit, mature, no magic |
| Validation | Pydantic v2 | One schema language for API, config, and domain models |
| Migrations | Alembic | Standard for SQLAlchemy |
| HTTP client | httpx | Async, proper timeout and connection-pool control |
| Browser | Playwright | Only for JS-rendered sites — see §7 |
| HTML | BeautifulSoup + lxml | Tolerant of the malformed markup we will constantly meet |
| DNS | dnspython | Async resolver, all record types we need |
| TLS | Python `ssl` + `cryptography` | Certificate parsing without an external service |
| PDF | ReportLab | Pure Python, no system dependencies, no headless-Chrome round trip |
| Server | Uvicorn | — |

### Data

| Concern | Choice | Why |
|---|---|---|
| Database | PostgreSQL 16 | Relational data plus JSONB for snapshots and evidence. One store for everything. |
| Job queue | **Postgres table + in-process async workers** | See §6. Redis and Celery arrive in v2, behind the same interface. |
| Snapshot storage | Postgres JSONB (v1) → object storage (v2) | Simplest thing that works; the adapter is already in place |

### Frontend

| Concern | Choice | Why |
|---|---|---|
| Framework | React 19 + TypeScript (strict) | Data-dense internal-tool UI |
| Build | Vite 6 | Fast, unremarkable |
| Styling | Tailwind CSS | No design system to maintain in a 3-week MVP |
| Server state | TanStack Query | Polling, caching, background refetch — exactly what a live scan needs |
| Table | TanStack Table | Sorting and filtering without writing it |
| Routing | React Router | Four routes. Nothing fancier is warranted. |

**Why no Redis in v1.** Redis buys distributed queuing and cross-process coordination. We have one process. A Postgres-backed job table gives durability, restart-resume, and progress queries — with one fewer service to run, deploy, and debug. `JobQueue` is an interface; swapping in Redis for v2 touches one file.

---

## 3. The core idea: crawl once, analyze many

**This is the most important section in this document.**

```
     NETWORK BOUNDARY
  ═══════════════════════════════════════════════════════
        │
        │   ┌─────────────────────────────────────────┐
   ┌────▼────┐   Crawler — the ONLY network component │
   │ Website │──▶  httpx → (Playwright fallback)      │
   └─────────┘    DNS resolution · TLS handshake      │
        │         robots.txt · rate limiting          │
        │   └──────────────────┬──────────────────────┘
  ═══════════════════════════════════════════════════════
                              ▼
                    ┌──────────────────┐
                    │   SiteSnapshot   │  ← immutable, persisted
                    │                  │
                    │  pages[]         │    url, status, headers,
                    │  tls             │    html, timing, size
                    │  dns             │
                    │  cookies[]       │
                    │  robots          │
                    │  timings         │
                    └────────┬─────────┘
                             │   pure functions — zero I/O
       ┌──────────┬──────────┼──────────┬──────────────┐
       ▼          ▼          ▼          ▼              ▼
    Contact     Tech      Security   Quality      (future analyzers
   Extractor  Analyzer   Analyzer   Analyzer       plug in here)
       │          │          │          │
       └──────────┴────┬─────┴──────────┘
                       ▼
              ┌─────────────────┐
              │   Findings[]    │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │ OpportunityEngine│  rules: findings → opportunities
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │  ScoringEngine  │  4 independent scores
              └────────┬────────┘
                       ▼
                CSV · PDF · API
```

### What this buys

| Benefit | How |
|---|---|
| **Tests run in milliseconds** | Save a snapshot as a JSON fixture. Every analyzer test is offline, deterministic, and instant. No network, no mocking HTTP. |
| **Re-analysis is free** | Improve a fingerprint, re-run over stored snapshots. Nobody's site gets hit twice. |
| **We are a good citizen** | One visit per site per scan, guaranteed by structure — not by an analyzer remembering to be careful. |
| **Every bug is reproducible** | "Why did it say WordPress?" → open the snapshot, find the byte. |
| **Analyzers parallelize trivially** | Pure functions over immutable data. No coordination. |
| **New analyzers are cheap** | Write a function, register it. No crawler changes. |

### The rule

> **No analyzer may perform I/O. Not HTTP, not DNS, not file, not database.**
>
> If an analyzer needs data, the **crawler** must collect it and put it in the snapshot.

This is enforced by an architecture test that fails the build if `analyzers/` imports `httpx`, `socket`, `dns`, `requests`, `ssl`, or `open`.

The temptation to break it will be real: "I just need one more DNS lookup for this check." The answer is always to add it to the crawler's collection phase. Break the rule once and the test suite needs network access, scans hit sites unpredictably, and reproducibility is gone.

---

## 4. System overview

```
┌────────────────────────────────────────────────────────────────┐
│                     React SPA (Vite, Tailwind)                 │
│   New Scan · Live Progress · Results Table · Detail · Export   │
└──────────────────────────┬─────────────────────────────────────┘
                           │  REST/JSON, polling for progress
┌──────────────────────────▼─────────────────────────────────────┐
│                     FastAPI application                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ api/          routers · schemas · deps                   │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ modules/                                                 │  │
│  │  discovery  crawler  analyzers  opportunities  scoring   │  │
│  │                       export    scans                    │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ core/    config · logging · errors · types · jobs        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Worker pool (asyncio tasks, same process)                │  │
│  │   poll job table → crawl → analyze → score → persist     │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────┬───────────────────────────────────┬───────────────┘
             │                                   │
    ┌────────▼────────┐                 ┌────────▼────────┐
    │  PostgreSQL 16  │                 │  Playwright     │
    │  data + jobs +  │                 │  (in-container  │
    │  snapshots      │                 │   browsers)     │
    └─────────────────┘                 └─────────────────┘
                                                 │
                                        ┌────────▼────────┐
                                        │ Discovery API   │
                                        │ (Places / OSM)  │
                                        └─────────────────┘
```

**One image, two roles.** The same container runs `uvicorn` (API) and, in-process, the worker pool. For v1 that is a single deployable. In v2 the worker becomes a separate command against the same image.

---

## 5. Plugin architecture

All analysis is performed by **plugins** driven by a **core engine**. The engine knows nothing about SSL, DNS, or WordPress; the plugins know nothing about scans, databases, or HTTP.

```
                    ┌──────────────────────────────────┐
                    │          CORE ENGINE             │
                    │  registry · dependency resolution│
                    │  execution · isolation · timing  │
                    └───────────────┬──────────────────┘
                                    │ PluginContext (snapshot + prior results)
   ┌───────────┬───────────┬────────┴────┬────────────┬────────────┐
   ▼           ▼           ▼             ▼            ▼            ▼
 ┌─────┐   ┌─────┐   ┌─────────┐   ┌──────────┐  ┌─────┐   ┌───────────┐
 │ SSL │   │ DNS │   │ HEADERS │   │TECHNOLOG.│  │ CMS │   │PERFORMANCE│
 └─────┘   └─────┘   └─────────┘   └────┬─────┘  └──┬──┘   └───────────┘
                                        │  provides │ depends on
 ┌──────────┐                           └───────────┘  technologies
 │ CONTACTS │
 └──────────┘
   ┌──────────────────────────────────────────────────────────────┐
   ▼                        depends on ALL analyzers               │
 ┌───────────────┐                                                 │
 │ OPPORTUNITIES │  (synthesizer — deterministic, see §9)          │
 └───────┬───────┘                                                 │
         ▼                                                         │
 ┌───────────────┐                                                 │
 │    REPORTS    │  (reporter — CSV, PDF)  ◀──────────────────────┘
 └───────────────┘
```

### 5.1 The plugin contract

Four types, one protocol. Everything else is engine machinery.

```python
class PluginKind(StrEnum):
    ANALYZER    = "analyzer"      # snapshot        → findings + artifacts
    SYNTHESIZER = "synthesizer"   # findings        → opportunities
    REPORTER    = "reporter"      # everything      → bytes

@dataclass(frozen=True, slots=True)
class PluginMeta:
    id: str                          # "ssl" — stable, appears in output
    name: str
    version: str
    kind: PluginKind
    depends_on: tuple[str, ...] = ()  # plugin ids that must run first
    provides:   tuple[str, ...] = ()  # artifact keys this plugin publishes
    budget_ms: int = 200

class Plugin(Protocol):
    meta: ClassVar[PluginMeta]
    def run(self, ctx: PluginContext) -> PluginResult: ...
```

`PluginContext` is the plugin's **entire world**. It receives the snapshot, the injected clock, settings, and the results of plugins it declared a dependency on — and nothing else. No database session, no HTTP client, no ambient global.

```python
class PluginContext:
    snapshot: SiteSnapshot
    now: datetime                     # injected — no plugin calls datetime.now()
    settings: PluginSettings
    def artifact(self, plugin_id: str, key: str, default=None) -> Any: ...
    def findings_from(self, plugin_id: str) -> tuple[Finding, ...]: ...
    def all_findings(self) -> tuple[Finding, ...]: ...
```

`PluginResult` is what comes back:

```python
@dataclass(frozen=True, slots=True)
class PluginResult:
    plugin_id: str
    findings:  tuple[Finding, ...] = ()
    artifacts: Mapping[str, Any] = ...   # e.g. {"technologies": [...]}
    opportunities: tuple[Opportunity, ...] = ()
```

### 5.2 The v1 plugin set

| Plugin | Kind | Depends on | Provides |
|---|---|---|---|
| `ssl` | analyzer | — | `certificate` |
| `dns` | analyzer | — | `spf`, `dmarc` |
| `headers` | analyzer | — | `security_headers` |
| `technologies` | analyzer | — | `technologies` |
| `cms` | analyzer | `technologies` | `cms` |
| `performance` | analyzer | — | `timings` |
| `contacts` | analyzer | — | `contacts` |
| `opportunities` | synthesizer | all analyzers | `opportunities` |
| `reports` | reporter | `opportunities` | — |

`cms` depending on `technologies` is the case that justifies the dependency graph: CMS-specific analysis (version currency, known-stale releases) needs the generic fingerprint result first. The engine topologically sorts, so `technologies` always runs before `cms` — and a plugin can never accidentally read a result that has not been produced.

### 5.3 What the engine guarantees

| Guarantee | How |
|---|---|
| **Deterministic order** | Topological sort with alphabetical tie-breaking. Same plugin set → same order, every run. |
| **Failure isolation** | Every `run()` is wrapped. A raising plugin is recorded as failed; the others complete. |
| **Dependency safety** | A plugin whose dependency failed is skipped, not run with missing input. |
| **No I/O** | Plugins receive data, never clients. Enforced by an architecture test. |
| **Timing** | Every plugin's duration is recorded; exceeding `budget_ms` logs a warning. |
| **Selective execution** | Any subset can be enabled — which is what makes each one independently testable. |

### 5.4 Independent testability

The requirement that drove this change. A plugin test needs no engine, no database, no network, and no other plugin:

```python
def test_expired_certificate_is_critical() -> None:
    ctx = PluginContext.for_testing(snapshot=load_fixture("expired_ssl"))
    result = SslPlugin().run(ctx)

    finding = find_by_check_id(result.findings, "TLS-03")
    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.CRITICAL
    assert finding.evidence["not_after"] == "2026-01-04T00:00:00Z"
```

For a plugin with dependencies, the dependency's output is **stubbed directly** — you never run the real `technologies` plugin to test `cms`:

```python
ctx = PluginContext.for_testing(
    snapshot=load_fixture("wordpress_outdated"),
    artifacts={"technologies": {"technologies": [Technology(id="wordpress", version="5.4.2")]}},
)
result = CmsPlugin().run(ctx)
```

That is the entire benefit of the plugin boundary: **every unit of analysis has a documented input, a documented output, and no hidden collaborators.**

### 5.5 Supporting modules

Not plugins — they surround the engine.

| Module | Owns | Touches network |
|---|---|---|
| `discovery` | Finding businesses | ✅ provider API |
| `crawler` | Visiting websites → `SiteSnapshot` | ✅ **only network component in the pipeline** |
| `plugins` | The engine and the built-in plugin set | ❌ |
| `scoring` | Four independent scores | ❌ |
| `pipeline` | Orchestration: discover → crawl → engine → score → persist | ❌ delegates |
| `db` | Models, session, persistence | ❌ |
| `api` | HTTP surface | ❌ |

### 5.6 Boundary rules

Enforced by `import-linter` and architecture tests in CI.

| Rule | Meaning |
|---|---|
| **Plugins do no I/O** | No `httpx`, `socket`, `dns`, `ssl`, `open`, no DB session. The single most important rule in the codebase. |
| **Plugins import nothing from `db`, `api`, `crawler`, or `pipeline`** | A plugin depends on `plugins.base` and `core` only. |
| **Plugins never import each other** | Cross-plugin data flows through `depends_on` + `ctx.artifact()`. Never a direct import. |
| **The engine imports no specific plugin** | It receives a registry. It has no knowledge of SSL or DNS. |
| **Only crawler and discovery reach the network** | Everything else operates on stored data. |
| **`core` imports nothing from anywhere above it** | Cross-cutting code has no domain knowledge. |
| **No import cycles** | If A and B need each other, the shared concept belongs in `core`. |

**"Plugins never import each other" is the rule that keeps this real.** The moment `cms.py` does `from .technologies import detect`, the plugin boundary is decorative — the dependency is invisible to the engine, untestable in isolation, and unorderable. The dependency graph must be declared, not imported.

---

## 6. Job execution

A scan of 50 sites takes minutes. It cannot run inside an HTTP request. It also does not justify Redis and Celery for a single-process MVP.

### 6.1 Design

```
POST /scans
      │
      ├─▶ INSERT scan (status=pending)
      ├─▶ INSERT job (type=discover, scan_id=…)
      └─◀ 202 { scan_id }          ← returns immediately

Worker pool (N asyncio tasks, started in FastAPI lifespan)
      │
      └─▶ loop:
            SELECT … FROM jobs
             WHERE status='pending' AND run_after <= now()
             ORDER BY priority, created_at
             FOR UPDATE SKIP LOCKED          ← the whole concurrency story
             LIMIT 1
            → mark running → execute → mark done/failed → repeat
```

`FOR UPDATE SKIP LOCKED` is what makes this safe. Multiple workers — and later, multiple processes — can poll the same table without double-claiming a job. This is a well-trodden Postgres pattern, not a clever trick.

### 6.2 Job types

| Type | Does | Enqueues |
|---|---|---|
| `discover` | Runs the discovery provider, creates business rows | one `analyze_business` per business with a website |
| `analyze_business` | Crawl → analyze → opportunities → score → persist | — |
| `finalize_scan` | Aggregate stats, mark scan complete | — |

### 6.3 Rules

- **Idempotent.** Every job can be re-run safely. Re-running `analyze_business` replaces that business's results.
- **Bounded.** Explicit timeout per job type. A job without a timeout is an outage waiting to happen.
- **Isolated.** A failed `analyze_business` marks that business failed and does not touch the scan or its siblings.
- **Resumable.** State lives in Postgres. Kill the process mid-scan and it resumes on restart.
- **Retried.** Max 2 retries with backoff, then `failed` with the error recorded.

**Migration to Redis/Celery (v2):** `JobQueue` is a protocol with `enqueue`, `claim`, `complete`, `fail`. `PostgresJobQueue` implements it today; `CeleryJobQueue` implements it later. No caller changes.

---

## 7. Crawler design

The only network component, and therefore the one with the most rules.

### 7.1 Fetch strategy

```
1. Canonicalize the URL, resolve DNS
       ↓  (DNS fails → snapshot with failure_reason=dns_failure, stop)
2. Fetch robots.txt, parse disallow rules
       ↓
3. Fetch homepage over httpx (follow ≤ 5 redirects)
       ↓
4. Capture the TLS certificate from the connection
       ↓
5. Does the HTML need JavaScript?
       ├─ visible text < 500 chars, or empty SPA root
       │        ↓ YES → re-render with Playwright, replace page HTML
       └─ NO → continue
       ↓
6. Build the page list: known contact paths + homepage links matching
   contact patterns, minus robots-disallowed, capped at 8
       ↓
7. Fetch each (≥ 1 s apart, same host, sequential)
       ↓
8. Collect DNS records: A, AAAA, MX, NS, TXT, CNAME, _dmarc
       ↓
9. Assemble and persist the SiteSnapshot
```

### 7.2 Why httpx first

Playwright costs roughly 20× the time and memory of an HTTP fetch. Most business websites are server-rendered and need none of it. Escalating only when the fast path visibly fails keeps a 50-site scan inside its five-minute budget.

The escalation heuristic is deliberately crude: if we cannot see meaningful text, we need a browser. It over-triggers occasionally, which costs seconds. Under-triggering would cost a wrong answer.

### 7.3 Politeness — non-negotiable

| Rule | Value |
|---|---|
| `robots.txt` | Always honored. No override flag exists. |
| Concurrency per host | 1 |
| Delay between requests to a host | ≥ 1 s |
| Pages per site | ≤ 8 |
| User-Agent | `LeadKhojoBot/1.0 (+https://leadkhojo.com/bot)` |
| `429` / `503` | Honor `Retry-After`, max 2 retries, then abandon the host |
| Per-request timeout | 15 s |
| Per-site budget | 60 s |

Cross-site concurrency is 10; per-host concurrency is 1. We finish a scan quickly by breadth, never by hammering one server.

---

## 8. Analyzers

Every analyzer is the same shape:

```python
class Analyzer(Protocol):
    id: str
    def analyze(self, snapshot: SiteSnapshot) -> list[Finding]: ...
```

Pure. Deterministic. No I/O. Total — it returns a result for any input, including a snapshot from a site that returned 500 and nothing else.

### 8.1 Rules as data

Technology fingerprints, security checks, and opportunity rules are YAML in `rules/`, loaded and validated at startup.

```yaml
# rules/security/dns.yaml
- id: DNS-03
  name: DMARC record present
  category: email_auth
  severity: high
  check: { type: dns_txt_exists, host: "_dmarc.{domain}" }
  pass_when: exists
  remediation: >
    Publish a DMARC TXT record at _dmarc.{domain}. Start with
    "v=DMARC1; p=none; rua=mailto:dmarc@{domain}" to collect reports,
    then tighten to quarantine and reject.
  opportunity: email_security_hardening
```

This is what makes NFR-MAINT-1 true: adding a security check is a YAML edit and a test, with no Python change and no migration. It also means non-engineers can extend coverage.

### 8.2 Findings

Every analyzer emits the same structure:

```python
@dataclass(frozen=True)
class Finding:
    check_id: str            # "DNS-03"
    category: str            # "email_auth"
    status: FindingStatus    # pass | fail | warn | info | not_applicable
    severity: Severity       # critical | high | medium | low | info
    title: str
    description: str
    evidence: dict           # what we checked, what we saw, when
    remediation: str | None
```

`evidence` is not optional. It is what the user pastes into an email.

---

## 9. Opportunity Engine — deterministic by construction

The synthesizer plugin that turns a technical audit into a sales list. **It is deterministic. AI is never part of producing it.**

```
   Rules  ──▶  Evidence  ──▶  Opportunity  ──▶  (optional AI rewrite)
   ▲                                              ▲
   │  declarative YAML                            │  presentation only
   │  no model involved                           │  adds no facts
   └──────────── deterministic core ──────────────┘
```

### 9.1 The four stages

| Stage | Input | Output | Deterministic |
|---|---|---|---|
| **1 · Rules** | Findings + artifacts from analyzer plugins | Matched rules | ✅ always |
| **2 · Evidence** | The specific findings that matched | An evidence bundle: what was checked, seen, when | ✅ always |
| **3 · Opportunity** | Rule templates + evidence | Title, description, pitch angle, urgency | ✅ always |
| **4 · AI rewrite** | A completed opportunity | A rephrased `description` | ❌ optional, off by default |

Stages 1–3 are the product. Stage 4 is a presentation layer that may be removed entirely without changing a single fact.

### 9.2 Rules

```python
@dataclass(frozen=True, slots=True)
class OpportunityRule:
    id: str
    requires: tuple[Condition, ...]     # ALL must match
    category: OpportunityCategory
    urgency: Urgency
    title_template: str
    description_template: str
    pitch_angle: str
    evidence_from: tuple[str, ...]      # which check_ids supply the evidence
```

**Rules compose.** A rule may require multiple findings — `no CDN` AND `TTFB > 1.5 s` produces a performance opportunity that neither finding alone justifies.

**The specificity gate.** A template that cannot be filled with concrete values produces nothing. If we know the CMS but not its version, the outdated-CMS rule stays silent — because "your CMS might be old" wastes the user's attention and damages trust in every other row.

### 9.3 The AI boundary — absolute

> **AI may never generate a finding, a fact, a number, a date, or an opportunity.**
> **AI may only rewrite text the rule engine has already produced.**

Structurally enforced, not merely stated:

```python
class OpportunityRewriter(Protocol):
    """Rephrases an existing opportunity. Cannot create or alter facts."""
    def rewrite(self, opportunity: Opportunity) -> str: ...   # returns prose only
```

| Control | Mechanism |
|---|---|
| The rewriter runs **after** the opportunity exists | It cannot influence whether one is produced |
| It returns **a string**, not an `Opportunity` | It cannot add a field, change urgency, or invent evidence |
| Output is stored in `description_ai`, **never overwriting `description`** | The deterministic text is always retained and always retrievable |
| `evidence` is **never** passed through the rewriter | Facts cannot be laundered through prose |
| Failure, timeout, or absent API key → deterministic text is used | AI is never on the critical path |
| Default implementation is `NullRewriter` (identity) | v1 ships with no model call at all |
| A numeric-claim guard rejects rewrites introducing digits absent from the evidence | Catches hallucinated figures mechanically |

**Why this matters more than it looks.** The product's value is that a user can forward a finding to a prospect and defend it on a call. One hallucinated certificate date destroys that for every finding they ever send. Keeping the model downstream of, and structurally unable to alter, the facts is what makes the output safe to put someone's name on.

**In v1 the rewriter is `NullRewriter` and no AI code path executes.** The seam exists so v2's Outreach Assistant plugs in without redesign — and so the boundary is settled before there is pressure to blur it.

### 9.4 Determinism test

```python
def test_opportunities_are_deterministic() -> None:
    snapshot = load_fixture("wordpress_outdated")
    runs = [OpportunityEngine().generate(snapshot, now=FIXED_TIME) for _ in range(50)]
    assert all(r == runs[0] for r in runs)
```

Same snapshot, same clock, same rules → byte-identical opportunities. Fifty times. This test is what makes "deterministic" a property rather than an intention.

---

## 10. Scoring

Four independent 0–100 scores, each a weighted sum of components, with weights in configuration.

```python
@dataclass(frozen=True)
class ScoreBreakdown:
    total: int                        # 0–100
    components: dict[str, float]      # name → contribution
    confidence: float                 # 0–1, lowered by missing inputs
```

**Deterministic:** same snapshot in, same scores out. Asserted by test.

**Confidence, not silent zeros:** if DNS failed entirely, the email-auth component is *unknown*, not *zero*. A site we could not check is not a site that failed. Confidence drops; the score does not lie.

---

## 11. Frontend

Four routes. Nothing more is warranted for v1.

```
/                      New scan form
/scans/:id             Live progress + results table
/scans/:id/:bizId      Business detail
/scans                 History
```

- **Server state** lives in TanStack Query. Progress is polled every 2 s while a scan is running, then stops. No WebSocket — polling is 15 lines and needs no reconnect handling.
- **Client state** is `useState`. There is no state library, because there is no state problem.
- **API types** are generated from the OpenAPI spec into `lib/api/generated.ts` and committed. CI regenerates and fails on drift, which makes an unannounced contract change impossible to merge quietly.

---

## 12. Path to microservices

The PRD requires modules that can become services without a rewrite. They can, because the seams already exist.

| Extract | When | What changes |
|---|---|---|
| **Crawler** | First and most likely — it is the I/O-bound, independently scalable part | `CrawlerService` becomes an HTTP client; `SiteSnapshot` is already a serializable contract |
| **Analyzers** | If analysis becomes CPU-bound at scale | They already take a snapshot and return findings — a stateless HTTP service, verbatim |
| **Export** | If PDF generation needs isolation | Takes IDs, returns bytes |
| **Discovery** | If provider management grows complex | Already behind a provider interface |

What makes this real rather than aspirational: **modules communicate through serializable data structures today.** `SiteSnapshot`, `Finding`, `Opportunity`, and `Scores` are all Pydantic models. Extraction means changing a function call to an HTTP call — not untangling shared state.

**Do not extract anything in v1.** The seams exist so that the option is cheap later; using it now would cost a week we do not have.

---

## 13. Deployment

```yaml
services:
  db:        postgres:16          # volume-backed
  api:       leadkhojo:latest     # uvicorn + in-process workers
  web:       leadkhojo-web        # nginx serving the built SPA
```

Single `docker compose up`. No cloud dependency, no managed service required.

**Portability rules:**
- Config exclusively from environment variables.
- No cloud SDK in `modules/`.
- Snapshot storage behind a `SnapshotStore` interface (Postgres JSONB in v1, S3-compatible later).
- Playwright browsers baked into the image at build time, never downloaded at runtime.

**Environments:** `local` (compose) → `ci` (ephemeral Postgres) → `production` (same compose file, real config).

---

## 14. Architecture decision records

| # | Decision | Rejected | Why | Revisit when |
|---|---|---|---|---|
| ADR-01 | Modular monolith | Microservices | One developer, three weeks. Boundaries preserved for later. | Team > 4, or one module's load profile diverges |
| ADR-02 | **Crawl once, analyze many** | Analyzers fetch what they need | Testability, politeness, reproducibility, re-analysis | Never |
| ADR-03 | Postgres job queue | Redis + Celery | One fewer service; `FOR UPDATE SKIP LOCKED` is sufficient at this scale | Multi-process workers or > 1000 jobs/min |
| ADR-04 | httpx first, Playwright fallback | Playwright always | 20× cost for a capability most sites don't need | Majority of targets become SPAs |
| ADR-05 | Rules as YAML | Rules in Python | Extending coverage without touching code is the whole maintenance story | Never |
| ADR-06 | Snapshots in Postgres JSONB | Object storage from day 1 | One store, no extra dependency; adapter already in place | Snapshot table exceeds ~50 GB |
| ADR-07 | ReportLab for PDF | Headless-Chrome HTML→PDF | No second browser pipeline, no extra memory, deterministic output | Design complexity outgrows it |
| ADR-08 | No auth in v1 | Auth from the start | Nobody closed a deal by logging in. Migration plan exists. | First multi-user deployment |
| ADR-09 | Polling, not WebSockets | WebSocket progress | 15 lines vs. reconnect/backpressure handling | Sub-second updates become a requirement |
| ADR-10 | Four independent scores | One blended score | Different buyers rank prospects differently | Never |
| ADR-11 | **Plugin architecture for all analysis** | Direct function calls between analyzers | Independent testability; declared rather than imported dependencies; selective execution; a new capability is a new file, not an edit to an existing one | Never |
| ADR-12 | **Declared dependencies, never imports, between plugins** | `from .technologies import detect` | An imported dependency is invisible to the engine, unorderable, and untestable in isolation | Never |
| ADR-13 | **Deterministic Opportunity Engine; AI is rewrite-only** | AI generates or ranks opportunities | Every finding must be defensible on a call. A model that can touch facts can hallucinate one, and one bad date discredits every finding a user ever sends. | Never |
| ADR-14 | Explicit plugin registry, not entry-point discovery | Auto-discovery via `importlib.metadata` | Explicit is debuggable and has no import side effects. Third-party plugin discovery is a real feature for later, not a v1 need. | Third-party plugins are supported |

---

## 15. Scaling path

| Stage | Trigger | Action |
|---|---|---|
| 1 | v1 launch | Single container, in-process workers, 10 concurrent sites |
| 2 | Scans queue up | Separate worker container from API (same image, different command) |
| 3 | Multiple worker hosts | Swap `PostgresJobQueue` → `CeleryJobQueue`; add Redis |
| 4 | Snapshot table grows | Move snapshots to object storage via `SnapshotStore` |
| 5 | Crawling dominates cost | Extract the crawler as a service; scale it independently |
| 6 | Multi-tenant SaaS | Follow [SaaS Migration Plan](12-SAAS-MIGRATION-PLAN.md) |

**Deliberately deferred:** Kubernetes, service mesh, GraphQL, event sourcing, CQRS, read replicas. Each solves a problem we do not have, and each would consume days we do not have.
