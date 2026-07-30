# LeadKhojo

**Find • Analyze • Prioritize • Convert**

A **Website Intelligence Platform**. Enter a keyword and a location, and LeadKhojo discovers businesses, analyzes their public websites, detects their technology and security posture, converts the findings into concrete sales opportunities, scores every lead, and exports the result as CSV and PDF.

---

## What LeadKhojo is

You sell a service — security hardening, web development, hosting, IT support, marketing. Your prospects are companies with websites that have problems you can fix. LeadKhojo finds those companies and tells you exactly what to pitch.

```
"cybersecurity firms in Austin"
        ↓
   47 businesses discovered
        ↓
   47 websites crawled and analyzed
        ↓
   "Northwind Corp — WordPress 5.4 (outdated), SSL expires in 11 days,
    no DMARC record, no CSP header, no CDN. 5 opportunities. Score 87."
        ↓
   CSV + PDF report, ready to work
```

## What LeadKhojo is not

- **Not a people database.** We never build, store, or sell a global directory of individuals.
- **Not a contact marketplace.** Nothing is resold. Every scan is run for and by the user who requested it.
- **Not a data broker.** We hold only publicly published business information, gathered from each company's own website at the moment the user asks for it.
- **Not Apollo / ZoomInfo / Lusha / Cognism.** Different product, different problem.

The unit of value is **analysis**, not data. A company's website is public; what nobody has done is read all of it and tell you what's wrong with it.

---

## Documentation

Read in order.

| # | Document | What it covers |
|---|---|---|
| — | **[README](README.md)** | You are here |
| 1 | [Vision](docs/01-VISION.md) | Why this exists, who it serves, what we will never build |
| 2 | [Product Requirements](docs/02-PRD.md) | Every module, every requirement, acceptance criteria |
| 3 | [Architecture](docs/03-ARCHITECTURE.md) | System shape, the crawl-once/analyze-many core, module boundaries |
| 4 | [Folder Structure](docs/04-FOLDER-STRUCTURE.md) | Where every file goes |
| 5 | [Database Schema](docs/05-DATABASE-SCHEMA.md) | Tables, relationships, indexes |
| 6 | [API Design](docs/06-API-DESIGN.md) | Endpoints, contracts, errors |
| 7 | [Development Roadmap](docs/07-ROADMAP.md) | Day-by-day, 15 working days to MVP |
| 8 | [Coding Standards](docs/08-CODING-STANDARDS.md) | How we write code |
| 9 | [Development Rules](docs/09-DEVELOPMENT-RULES.md) | Non-negotiable engineering rules |
| 10 | [Testing Strategy](docs/10-TESTING-STRATEGY.md) | What to test and how |
| 11 | [Security Rules](docs/11-SECURITY-RULES.md) | Crawler ethics, the passive-only boundary, legal limits |
| 12 | [SaaS Migration Plan](docs/12-SAAS-MIGRATION-PLAN.md) | Single-user MVP → multi-tenant SaaS, without a rewrite |
| 13 | [Release Plan](docs/13-RELEASE-PLAN.md) | Versions, gates, what ships when |

---

## The one idea that shapes everything

**Crawl once. Analyze many times.**

```
                    ┌──────────────────────────┐
   Website  ──────► │      SiteSnapshot        │
   (network I/O)    │  pages, headers, TLS,    │
                    │  DNS, timings, cookies   │
                    └────────────┬─────────────┘
                                 │  (pure data — no network)
        ┌──────────────┬─────────┼─────────┬──────────────┐
        ▼              ▼         ▼         ▼              ▼
   TechAnalyzer  SecurityAnalyzer  ContactExtractor  QualityAnalyzer
        │              │                   │              │
        └──────────────┴─────────┬─────────┴──────────────┘
                                 ▼
                        OpportunityEngine
                                 ▼
                            ScoringEngine
                                 ▼
                        CSV  ·  PDF  ·  API
```

The crawler is the **only** component that touches the network. Every analyzer is a **pure function** from `SiteSnapshot` to findings.

This gives us, for free:
- **Testability** — save one snapshot as a fixture, test every analyzer offline in milliseconds.
- **Re-analysis** — improve a detection rule, re-run against stored snapshots. No re-crawling.
- **Politeness** — one visit per site per scan. We never hammer a target because an analyzer needed one more page.
- **Debuggability** — every finding traces to a specific byte in a stored snapshot.

If you break this rule and put a network call inside an analyzer, you lose all four.

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · Pydantic v2 |
| Crawler | httpx (fast path) → Playwright (JS fallback) · BeautifulSoup |
| Database | PostgreSQL 16 |
| Frontend | React 19 · TypeScript · Vite · Tailwind CSS |
| Reports | ReportLab (PDF) · Python `csv` (CSV) |
| Jobs | Postgres-backed queue + in-process async workers *(Redis/Celery: v2)* |
| Deploy | Docker · Docker Compose · cloud-agnostic |

---

## MVP scope

**In v1.0:**
Business Discovery · Website Intelligence · Contact Extraction · Technology Detection · Security Intelligence · Opportunity Engine · Lead Scores · CSV Export · PDF Report

**Deliberately not in v1.0:**
Authentication · Billing · Subscriptions · CRM · Chrome Extension · API Marketplace · White Label · AI Agents · Multi-user · Email Automation · Outreach Assistant

Every one of those is a real feature with a real place on the roadmap. None of them helps the first user close their first deal, so none of them is in v1.

---

## Hard boundaries

Not preferences. Violating any of these is a revert, not a discussion.

- **Passive analysis only.** We send ordinary HTTP requests to publicly served pages, resolve public DNS, and complete a TLS handshake. **No port scanning, no vulnerability probing, no path brute-forcing, no exploitation, no authentication bypass.** See [Security Rules](docs/11-SECURITY-RULES.md).
- **Business information only.** Role addresses (`info@`, `sales@`, `support@`) and business phone numbers from a company's own published pages. Never personal data, never inferred or pattern-guessed contacts.
- **Respect `robots.txt`.** Always. A disallowed path is not fetched, and there is no override flag.
- **Identify ourselves.** Every request carries an honest, contactable `User-Agent`.
- **No network calls inside analyzers.** Crawler only.
- **Every finding carries evidence.** A URL, a header value, a DNS record — something a user can verify themselves.

---

## Quick start (once built)

```bash
cp .env.example .env      # set LK_DATABASE_URL and any discovery API key
make dev                  # Postgres + API + web, seeded
make scan KEYWORD="dental clinics" LOCATION="Austin, TX"
```

## Repository status

**Documentation phase.** No application code written yet. Awaiting approval of the documents above before implementation begins.
