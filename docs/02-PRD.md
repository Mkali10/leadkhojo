# LeadKhojo — Product Requirements Document

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-30 |
| **Status** | Awaiting approval |
| **Depends on** | [01-VISION.md](01-VISION.md) |

---

## 1. Scope

### 1.1 In scope for v1.0 (MVP)

| # | Module | Ships in v1 |
|---|---|---|
| 1 | Business Discovery | ✅ |
| 2 | Website Intelligence (crawler) | ✅ |
| 3 | Contact Extraction | ✅ |
| 4 | Technology Intelligence | ✅ |
| 5 | Security Intelligence | ✅ |
| 6 | Opportunity Engine | ✅ |
| 7 | Lead Intelligence (scoring) | ✅ |
| 8 | Outreach Assistant | ❌ v2 |
| 9 | Reports (CSV + PDF) | ✅ |

### 1.2 Explicitly not in v1.0

Authentication · Billing · Subscriptions · CRM · Chrome extension · API marketplace · White label · Browser extension · AI agents · Multi-user · Email automation · Outreach Assistant.

Each is deferred with a defined home in the [Release Plan](13-RELEASE-PLAN.md). None is cancelled; none is in v1.

### 1.3 Requirement conventions

- **ID:** `FR-<MODULE>-<n>` functional, `NFR-<AREA>-<n>` non-functional.
- **Priority:** `M` = must (blocks v1) · `S` = should (v1 if time) · `V2` = deferred.
- Acceptance criteria are Given/When/Then. A `M` requirement without acceptance criteria is not ready to build.

---

## 2. Core workflow

```
   ┌─────────────────────────────────────────────────────────┐
   │  User enters:  keyword  +  location                     │
   │  (or uploads a CSV of domains)                          │
   └───────────────────────────┬─────────────────────────────┘
                               ▼
   ┌─────────────────────────────────────────────────────────┐
   │  1 · DISCOVER          find businesses, get websites    │
   └───────────────────────────┬─────────────────────────────┘
                               ▼
   ┌─────────────────────────────────────────────────────────┐
   │  2 · CRAWL             visit site → SiteSnapshot        │
   │     (the only module that touches the network)          │
   └───────────────────────────┬─────────────────────────────┘
                               ▼
   ┌──────────────┬──────────────┬──────────────┬────────────┐
   │ 3 · CONTACT  │ 4 · TECH     │ 5 · SECURITY │ QUALITY    │
   │   extract    │   detect     │   analyze    │  measure   │
   └──────────────┴──────┬───────┴──────────────┴────────────┘
                         ▼
   ┌─────────────────────────────────────────────────────────┐
   │  6 · OPPORTUNITY ENGINE     findings → things to sell   │
   └───────────────────────────┬─────────────────────────────┘
                               ▼
   ┌─────────────────────────────────────────────────────────┐
   │  7 · SCORING       lead · website · security · opp      │
   └───────────────────────────┬─────────────────────────────┘
                               ▼
   ┌─────────────────────────────────────────────────────────┐
   │  9 · EXPORT                CSV  ·  PDF                  │
   └─────────────────────────────────────────────────────────┘
```

Steps 3–5 and Quality run **against the stored snapshot, not the live site**. See [Architecture §3](03-ARCHITECTURE.md).

---

## 3. Module 1 — Business Discovery

**Purpose:** turn a human query into a list of businesses with websites.

| ID | Pri | Requirement |
|---|---|---|
| FR-DISC-1 | M | Accept a search: keyword (required), location (optional), result limit (default 25, max 100). |
| FR-DISC-2 | M | Return per business: name, website URL, address, city, country, category, phone (if published by the source), source identifier. |
| FR-DISC-3 | M | Discovery runs behind a `DiscoveryProvider` interface with at least two implementations, selectable by configuration. |
| FR-DISC-4 | M | **CSV import provider** — user uploads a file of domains or company names and skips discovery entirely. |
| FR-DISC-5 | M | Businesses without a resolvable website are recorded but marked `no_website` and excluded from crawling. |
| FR-DISC-6 | M | Deduplicate within a scan by canonical registrable domain (public-suffix aware). |
| FR-DISC-7 | M | A provider failure degrades gracefully: partial results are kept, the error is recorded on the job, the scan continues. |
| FR-DISC-8 | S | Location accepts free text ("Austin, TX") or country + city fields. |

### 3.1 Providers

| Provider | Status | Notes |
|---|---|---|
| `CsvImportProvider` | **Build first** | Zero external dependencies. Makes the whole pipeline testable on day 1. |
| `GooglePlacesProvider` | Default in production | Best coverage and website-field quality. Paid. **Caching restrictions apply — see §3.2.** |
| `OpenStreetMapProvider` | Free fallback / local dev | Overpass API. Good address data, patchy website coverage. |

### 3.2 Google Places constraint — read before implementing

Google's Places terms permit indefinite storage of `place_id` but restrict caching of other content fields (typically 30 days). This is a **hard product constraint**, not a footnote:

- Store `place_id` permanently as the dedup/refresh key.
- Treat all other discovery fields as **cached, with an expiry timestamp**.
- A scheduled job purges or refreshes expired discovery fields (see [Database Schema §6](05-DATABASE-SCHEMA.md)).
- **Crawled data is ours** — it came from the company's own website, not from Google. Only the discovery-provider fields are governed by this.

**AC (FR-DISC-4).** *Given* a CSV with a `domain` column and 30 rows, *when* uploaded, *then* 30 businesses are created, invalid rows are reported individually with row numbers, and the scan proceeds without any external discovery call.

**AC (FR-DISC-6).** *Given* discovery returns `acme.com`, `www.acme.com`, and `https://acme.com/about`, *when* deduplication runs, *then* exactly one business exists with `domain = acme.com`.

---

## 4. Module 2 — Website Intelligence (Crawler)

**Purpose:** visit a website once, politely, and capture everything the analyzers will need.

| ID | Pri | Requirement |
|---|---|---|
| FR-CRAWL-1 | M | Fetch the homepage; follow redirects (max 5); record the full redirect chain and final URL. |
| FR-CRAWL-2 | M | Fetch high-value additional pages, capped at **8 pages per site**: `/contact`, `/contact-us`, `/about`, `/privacy`, `/imprint`, `/legal`, plus homepage links whose text or href matches contact patterns. |
| FR-CRAWL-3 | M | Fetch and parse `robots.txt`. **Never fetch a disallowed path.** No override exists. |
| FR-CRAWL-4 | M | Fetch `sitemap.xml` and `/.well-known/security.txt` when present (record presence either way). |
| FR-CRAWL-5 | M | Capture per page: final URL, HTTP status, response headers, HTML body, content hash, response time, byte size. |
| FR-CRAWL-6 | M | Capture the TLS certificate: issuer, subject, SANs, not-before, not-after, TLS version, cipher. |
| FR-CRAWL-7 | M | Capture DNS: A, AAAA, MX, NS, TXT, CNAME, and `_dmarc` TXT. Record the resolved IP and, where available, ASN and organization. |
| FR-CRAWL-8 | M | Capture `Set-Cookie` headers with their attributes. |
| FR-CRAWL-9 | M | **httpx first; Playwright only as fallback.** Escalate when the HTML has < 500 characters of visible text, or a known SPA root element with an empty body is detected. |
| FR-CRAWL-10 | M | Honest, contactable `User-Agent`: `LeadKhojoBot/1.0 (+https://leadkhojo.com/bot)`. |
| FR-CRAWL-11 | M | Rate limit **≤ 1 concurrent request per host** with a ≥ 1 s delay between requests to the same host. |
| FR-CRAWL-12 | M | Per-request timeout 15 s; per-site budget 60 s. Exceeding either yields a partial snapshot, not a failure. |
| FR-CRAWL-13 | M | Honor `429` and `503` with `Retry-After`, up to 2 retries, then abandon that host for the scan. |
| FR-CRAWL-14 | M | The output is a single `SiteSnapshot` persisted before any analyzer runs. |
| FR-CRAWL-15 | M | Every failure mode is recorded as a typed reason: `dns_failure`, `connection_refused`, `tls_error`, `timeout`, `http_4xx`, `http_5xx`, `robots_denied`, `parked_domain`. |
| FR-CRAWL-16 | S | Detect parked/placeholder domains and skip full analysis. |

**AC (FR-CRAWL-9).** *Given* a React SPA whose server HTML is an empty `<div id="root">`, *when* crawled, *then* httpx returns first, the < 500-char rule triggers, Playwright re-renders, and the snapshot records `render_mode = "playwright"`.

**AC (FR-CRAWL-3).** *Given* `robots.txt` disallows `/contact`, *when* the crawler builds its page list, *then* `/contact` is never requested and the snapshot records `robots_blocked_paths = ["/contact"]`.

**AC (FR-CRAWL-14).** *Given* a site returning 500 on the homepage, *when* crawling completes, *then* a snapshot still exists with `status = partial`, `failure_reason = http_5xx`, and any DNS/TLS data that was obtainable.

---

## 5. Module 3 — Contact Extraction

**Purpose:** find how to reach the business — from its own pages only.

| ID | Pri | Requirement |
|---|---|---|
| FR-CONTACT-1 | M | Extract email addresses from `mailto:` links and page text. |
| FR-CONTACT-2 | M | **Classify and filter.** Keep business/role addresses. Discard obvious personal addresses and non-contact noise. |
| FR-CONTACT-3 | M | Categorize emails: `general` (info@, hello@, contact@), `sales`, `support`, `careers`, `security`, `other`. |
| FR-CONTACT-4 | M | Extract phone numbers from `tel:` links and text; normalize to E.164 using the business's country as the default region. |
| FR-CONTACT-5 | M | Extract the postal address from the contact page (schema.org markup preferred, then heuristics). |
| FR-CONTACT-6 | M | Extract official social profiles: LinkedIn (company), Facebook, Twitter/X, Instagram, YouTube. |
| FR-CONTACT-7 | M | Detect the presence and URL of contact forms. |
| FR-CONTACT-8 | M | **Every contact stores its source page URL.** No provenance, no record. |
| FR-CONTACT-9 | M | **Never guess an address.** No `first.last@domain` construction, no pattern inference, no permutation. Only addresses literally present on the page. |
| FR-CONTACT-10 | M | Deduplicate case-insensitively per business. |
| FR-CONTACT-11 | S | Rank emails by usefulness so the export's primary contact column is the best available. |

### 5.1 Filtering rules

**Discard:**

- Image/asset filenames matching an email-like pattern
- Known placeholder domains: `example.com`, `domain.com`, `yourcompany.com`, `email.com`, `sentry.io`, `wixpress.com`
- Addresses on third-party domains (a `@gmail.com` on a company site is a personal address, not a business contact)
- Anything matching a personal-name pattern (`^[a-z]+\.[a-z]+@`) unless it is also a known role alias

**Keep:** role-prefixed addresses on the business's own domain, or on a domain that is a clear corporate variant.

**AC (FR-CONTACT-9).** *Given* the crawler found no email on any page, *when* extraction completes, *then* the business has zero emails. The system does **not** produce `info@<domain>` as a guess. A negative result is a correct result.

**AC (FR-CONTACT-8).** *Given* `sales@acme.com` is found, *when* stored, *then* the record includes `source_url = "https://acme.com/contact"` and the exported CSV can show where it came from.

---

## 6. Module 4 — Technology Intelligence

**Purpose:** determine what the site is built and run on.

| ID | Pri | Requirement |
|---|---|---|
| FR-TECH-1 | M | Detect technologies from HTML, meta tags, script/link URLs, cookie names, and response headers. |
| FR-TECH-2 | M | Extract versions where the site discloses them (generator meta, script paths, header banners). |
| FR-TECH-3 | M | Categorize: `cms`, `ecommerce`, `framework`, `javascript`, `server`, `hosting`, `cdn`, `waf`, `analytics`, `marketing`, `language`, `database_hint`. |
| FR-TECH-4 | M | Each detection stores a **confidence** (`certain` / `likely` / `possible`) and its **evidence** (which signal fired). |
| FR-TECH-5 | M | Detection rules are **declarative data**, not code. Adding a technology is a data change. |
| FR-TECH-6 | M | Ship with ≥ 60 fingerprints covering the categories in §6.1. |
| FR-TECH-7 | S | Flag a detected version as outdated against a maintained `known_latest` table. |

### 6.1 Required coverage

| Category | Must detect |
|---|---|
| CMS | WordPress, Drupal, Joomla, Wix, Squarespace, Webflow, Ghost, TYPO3 |
| E-commerce | WooCommerce, Shopify, Magento, PrestaShop, BigCommerce, OpenCart |
| Frontend | React, Angular, Vue, Next.js, Nuxt, Svelte, jQuery, Bootstrap, Tailwind |
| Backend | Laravel, Symfony, Django, Rails, Express/Node, ASP.NET, Spring, CodeIgniter |
| Language | PHP, Node.js, Python, Java, .NET, Ruby |
| Server | Nginx, Apache, LiteSpeed, IIS, Caddy |
| CDN / WAF | Cloudflare, Akamai, Fastly, CloudFront, Sucuri, Imperva |
| Hosting | AWS, Azure, GCP, DigitalOcean, GoDaddy, Hostinger, SiteGround, Netlify, Vercel |
| Analytics | Google Analytics (UA / GA4), GTM, Meta Pixel, Hotjar, Matomo, Plausible |
| Marketing | HubSpot, Mailchimp, Intercom, Drift, Zendesk |
| Database hint | MySQL / Postgres / MSSQL error strings or driver banners only — never probed |

### 6.2 Fingerprint format

```yaml
- id: wordpress
  name: WordPress
  category: cms
  signals:
    - { type: meta_generator, pattern: "^WordPress\\s*([\\d.]+)?", confidence: certain, version_group: 1 }
    - { type: html,           pattern: "/wp-content/",            confidence: certain }
    - { type: header,         name: x-pingback,                    confidence: likely }
    - { type: path_exists,    path: /wp-login.php,                 confidence: likely }
  opportunity_hooks: [outdated_cms, cms_maintenance]
```

> `path_exists` checks only conventional, publicly documented paths already gathered by the crawler. It is **not** a discovery scan and never enumerates.

**AC (FR-TECH-4).** *Given* a page containing `/wp-content/themes/x/style.css` and `<meta name="generator" content="WordPress 5.4.2">`, *when* analyzed, *then* WordPress is detected once with `version = "5.4.2"`, `confidence = certain`, and evidence naming both signals.

**AC (FR-TECH-5).** *Given* a new fingerprint is added to the YAML file and the app restarts, *when* a scan runs, *then* the technology is detected — with no Python change and no migration.

---

## 7. Module 5 — Security Intelligence

**Purpose:** assess public security posture from what the site serves. Passive only.

> **Boundary.** Every check below is satisfied by data the crawler already collected: HTTP response headers, the TLS handshake, public DNS, and page HTML. Nothing here sends a probe the site did not already answer. See [Security Rules](11-SECURITY-RULES.md).

| ID | Pri | Requirement |
|---|---|---|
| FR-SEC-1 | M | Run the check catalogue in §7.1 against the snapshot. |
| FR-SEC-2 | M | Each check yields `pass` / `fail` / `warn` / `info` / `not_applicable`, plus severity, evidence, and remediation guidance. |
| FR-SEC-3 | M | Checks are declarative and independently testable; adding one does not modify existing ones. |
| FR-SEC-4 | M | Produce a 0–100 Security Score (see §8). |
| FR-SEC-5 | M | **No active scanning.** No port scanning, no path enumeration, no payload injection, no auth attempts. |
| FR-SEC-6 | M | Port scanning is **out of scope for v1** and remains permanently gated behind explicit per-target written authorization. See [Security Rules §5](11-SECURITY-RULES.md). |
| FR-SEC-7 | M | A finding never asserts exploitability — only observable configuration. |

### 7.1 Check catalogue (v1)

**Transport — TLS/SSL**

| ID | Check | Severity when failing |
|---|---|---|
| `TLS-01` | HTTPS available at all | Critical |
| `TLS-02` | HTTP redirects to HTTPS | High |
| `TLS-03` | Certificate currently valid (not expired, not future-dated) | Critical |
| `TLS-04` | Certificate expires in > 30 days | High / Medium |
| `TLS-05` | Hostname matches certificate CN/SAN | Critical |
| `TLS-06` | TLS ≥ 1.2 negotiated | High |
| `TLS-07` | Certificate chain complete | Medium |
| `TLS-08` | Not a self-signed certificate | High |

**HTTP security headers**

| ID | Header | Severity |
|---|---|---|
| `HDR-01` | `Strict-Transport-Security` | High |
| `HDR-02` | `Content-Security-Policy` | High |
| `HDR-03` | `X-Content-Type-Options: nosniff` | Medium |
| `HDR-04` | `X-Frame-Options` or CSP `frame-ancestors` | Medium |
| `HDR-05` | `Referrer-Policy` | Low |
| `HDR-06` | `Permissions-Policy` | Low |
| `HDR-07` | No `X-Powered-By` / version-disclosing `Server` banner | Low |

**Email authentication (DNS)**

| ID | Check | Severity |
|---|---|---|
| `DNS-01` | SPF record present | High |
| `DNS-02` | SPF not overly permissive (`+all`) | High |
| `DNS-03` | DMARC record present | High |
| `DNS-04` | DMARC policy is `quarantine` or `reject`, not `none` | Medium |
| `DNS-05` | DKIM selector discoverable (common selectors only, best-effort) | Low |
| `DNS-06` | MX records present | Info |
| `DNS-07` | DNSSEC enabled | Low |

**Cookies**

| ID | Check | Severity |
|---|---|---|
| `CKY-01` | `Secure` flag on all cookies | Medium |
| `CKY-02` | `HttpOnly` on session-like cookies | Medium |
| `CKY-03` | `SameSite` set | Low |

**Content & disclosure**

| ID | Check | Severity |
|---|---|---|
| `CNT-01` | No mixed content (HTTP assets on an HTTPS page) | Medium |
| `CNT-02` | CMS version not disclosed in generator meta | Low |
| `CNT-03` | No detected outdated JS library versions | Medium |
| `CNT-04` | `security.txt` present (RFC 9116) | Info |
| `CNT-05` | Login page, if present, is served over HTTPS | Critical |
| `CNT-06` | Forms post to HTTPS endpoints | High |

**Privacy signals**

| ID | Check | Severity |
|---|---|---|
| `PRV-01` | Privacy policy page found | Info |
| `PRV-02` | Cookie consent banner present when tracking scripts are present | Low |

**AC (FR-SEC-2).** *Given* `_dmarc.acme.com` returns NXDOMAIN, *when* `DNS-03` runs, *then* the finding records `status = fail`, `severity = high`, `evidence = {"query": "_dmarc.acme.com TXT", "result": "NXDOMAIN", "checked_at": "..."}`, and remediation text describing the record to publish.

**AC (FR-SEC-5).** *Given* the full security suite runs, *when* network traffic is captured, *then* the only outbound connections are HTTP(S) to published pages, DNS queries, and TLS handshakes. **No TCP connection to any port other than 80/443. Asserted by an automated test.**

---

## 8. Modules 6 & 7 — Opportunity Engine and Lead Intelligence

### 8.1 Opportunity Engine

**Purpose:** convert technical findings into things the user can sell. This is where the product earns its keep.

| ID | Pri | Requirement |
|---|---|---|
| FR-OPP-1 | M | Map findings to opportunities via declarative rules. |
| FR-OPP-2 | M | Each opportunity carries: title, service category, urgency, plain-language description, the evidence that triggered it, and a suggested pitch angle. |
| FR-OPP-3 | M | Rules may require multiple findings (`no CDN` AND `slow TTFB` → performance opportunity). |
| FR-OPP-4 | M | Deduplicate and merge overlapping opportunities into the strongest single one. |
| FR-OPP-5 | M | Ship with ≥ 15 rules covering security, performance, modernization, and hosting. |
| FR-OPP-6 | M | **Specificity gate.** If a rule cannot produce a concrete, evidence-backed statement, it produces nothing. Generic filler is a defect. |
| FR-OPP-7 | S | Filter opportunities by the user's own service categories. |
| **FR-OPP-8** | **M** | **The engine is deterministic.** The same snapshot and clock produce byte-identical opportunities on every run. Asserted by a 50-iteration test. |
| **FR-OPP-9** | **M** | **AI never generates a finding, fact, number, date, or opportunity.** Its only permitted role is rewriting prose the rule engine already produced. |
| **FR-OPP-10** | **M** | An AI rewrite is written to `description_ai` and **never overwrites** the deterministic `description`. Both are retained and both are retrievable. |
| **FR-OPP-11** | **M** | `evidence` is never passed to a rewriter, and a rewrite introducing a numeric claim absent from the evidence is rejected. |
| **FR-OPP-12** | **M** | Rewriting is **off by default**. Failure, timeout, or a missing API key falls back to the deterministic text. AI is never on the critical path. |

### 8.1.1 Pipeline

```
Rules ──▶ Evidence ──▶ Opportunity ──▶ (optional AI rewrite)
 ▲                                        ▲
 └──────── deterministic core ────────────┘  presentation only, adds no facts
```

Stages 1–3 are the product. Stage 4 may be removed entirely without changing a single fact. In v1 the rewriter is `NullRewriter` and **no AI code path executes**.

**AC (FR-OPP-9).** *Given* the AI rewriter is enabled and returns text asserting "your certificate expired 40 days ago" when the evidence says 9 days remain, *when* the guard runs, *then* the rewrite is rejected, the deterministic description is used, and a warning is logged.

**AC (FR-OPP-8).** *Given* the `wordpress_outdated` fixture and a fixed clock, *when* the engine runs 50 times, *then* all 50 results are identical including ordering.

**Baseline rules**

| Trigger | Opportunity | Category | Urgency |
|---|---|---|---|
| Certificate expires < 30 days | SSL certificate renewal & monitoring | Security | Critical |
| No HTTPS / invalid certificate | SSL implementation | Security | Critical |
| CMS version > 2 major releases behind | CMS upgrade & maintenance plan | Maintenance | High |
| No SPF or no DMARC | Email security hardening (anti-spoofing) | Security | High |
| DMARC policy = `none` | DMARC enforcement rollout | Security | Medium |
| ≥ 3 security headers missing | Security header hardening | Security | Medium |
| No CDN + TTFB > 1.5 s | CDN & performance optimization | Performance | Medium |
| No WAF + WordPress detected | WAF / managed security | Security | Medium |
| Outdated jQuery (< 3.0) | Frontend modernization | Development | Medium |
| No mobile viewport meta | Responsive redesign | Development | High |
| Mixed content present | HTTPS migration completion | Security | High |
| Login page over HTTP | Urgent TLS remediation | Security | Critical |
| No analytics detected | Analytics & tracking setup | Marketing | Low |
| Tracking scripts + no cookie banner | Privacy compliance review | Compliance | Medium |
| `X-Powered-By` version disclosed | Server hardening | Security | Low |
| Self-hosted on shared/legacy host | Managed hosting migration | Hosting | Low |

**AC (FR-OPP-6).** *Given* a site where the CMS is detected but the version is unknown, *when* the outdated-CMS rule evaluates, *then* **no opportunity is created** — because "your CMS might be old" is not a pitch.

**AC (FR-OPP-2).** *Given* a certificate expiring in 9 days, *when* the rule fires, *then* the opportunity reads: *"SSL certificate for acme.com expires 2026-08-08 (9 days). An expired certificate shows every visitor a browser security warning."* — with the issuer and expiry as evidence.

### 8.2 Lead Intelligence — four independent scores

| ID | Pri | Requirement |
|---|---|---|
| FR-SCORE-1 | M | Compute four independent 0–100 scores: **Lead Quality**, **Website Quality**, **Security**, **Opportunity**. |
| FR-SCORE-2 | M | Each score exposes its component breakdown. A score without a breakdown is not shippable. |
| FR-SCORE-3 | M | Weights live in configuration, not code. |
| FR-SCORE-4 | M | Scores are deterministic: the same snapshot always yields the same scores. |
| FR-SCORE-5 | M | A missing input lowers confidence, never silently zeroes a component. |

**They are independent by design.** A security firm sorts by Opportunity Score. A design agency sorts by Website Quality (ascending — worst first). A generalist sorts by Lead Quality. One blended number would serve none of them.

| Score | Answers | Components |
|---|---|---|
| **Lead Quality** | Can I reach and work with them? | Contact availability (40) · business signals (25) · site reachable and real (20) · category fit (15) |
| **Website Quality** | How good is their site? | Performance (30) · modernity of stack (25) · mobile-ready (20) · completeness (15) · UX signals (10) |
| **Security** | How exposed are they? | TLS (35) · headers (25) · email auth (25) · disclosure & content (15) |
| **Opportunity** | How much can I sell? | Count and severity of opportunities, weighted by urgency and by contactability — an unreachable prospect is worth nothing regardless of how broken their site is |

**AC (FR-SCORE-2).** *Given* a scanned business, *when* its detail is requested, *then* each score returns its numeric value **and** its per-component contributions, so the user can see *why* it scored what it did.

---

## 9. Module 9 — Reports

| ID | Pri | Requirement |
|---|---|---|
| FR-EXPORT-1 | M | Export scan results to CSV: one row per business, all key fields flattened. |
| FR-EXPORT-2 | M | CSV is UTF-8 with BOM (opens correctly in Excel) and RFC 4180 quoted. |
| FR-EXPORT-3 | M | Export a per-business PDF report: findings, opportunities, scores, evidence. |
| FR-EXPORT-4 | M | Export a scan-level PDF summary: ranked list plus aggregate statistics. |
| FR-EXPORT-5 | M | The PDF is client-presentable — the user attaches it to their first email. |
| FR-EXPORT-6 | M | Every finding in the PDF shows its evidence. |
| FR-EXPORT-7 | S | User selects which columns the CSV includes. |

**CSV columns (v1):**

`business_name, website, domain, city, country, category, primary_email, all_emails, phone, address, linkedin, facebook, twitter, instagram, contact_form_url, cms, cms_version, framework, server, cdn, waf, hosting, analytics, has_ssl, ssl_expires_at, ssl_days_remaining, tls_version, has_hsts, has_csp, has_spf, has_dmarc, dmarc_policy, missing_headers_count, lead_score, website_score, security_score, opportunity_score, opportunity_count, top_opportunity, opportunities, scanned_at`

**AC (FR-EXPORT-5).** *Given* a completed business scan, *when* the PDF is generated, *then* it contains a cover page with the business name and scores, a findings section grouped by severity with evidence, an opportunities section written in plain business language, and a technical appendix.

---

## 10. Module 8 — Outreach Assistant *(v2 — not in MVP)*

Specified now so v1's data model does not have to change later.

| ID | Pri | Requirement |
|---|---|---|
| FR-OUT-1 | V2 | Generate a cold email from a business's findings, opportunities, and the user's service description. |
| FR-OUT-2 | V2 | Generate a LinkedIn connection message (short form). |
| FR-OUT-3 | V2 | Generate a proposal summary and meeting talking points. |
| FR-OUT-4 | V2 | Generate follow-up suggestions. |
| FR-OUT-5 | V2 | Every draft cites the specific finding it references. No invented claims. |
| FR-OUT-6 | V2 | **Tone rule: advisory, never alarmist.** Drafts must not imply threat, urgency-by-fear, or any suggestion that the sender caused or could cause harm. A message that reads as pressure is a defect, not a conversion tactic. |
| FR-OUT-7 | V2 | Drafts are always editable. LeadKhojo never sends anything. |

**Implementation note (v2):** generation uses the Anthropic API with model `claude-opus-5`. Findings and opportunities are passed as structured context; the model composes prose but is never the source of a factual claim. A deterministic template fallback exists for offline/no-key operation.

---

## 11. User interface (v1)

| ID | Pri | Requirement |
|---|---|---|
| FR-UI-1 | M | Single-page app: new scan → live progress → results table → business detail → export. |
| FR-UI-2 | M | Scan form: keyword, location, limit, provider; or CSV upload. |
| FR-UI-3 | M | **Live progress** with per-business status as results stream in. The user must never stare at a spinner with no information. |
| FR-UI-4 | M | Results table sortable by any of the four scores, filterable by opportunity category and by "has contact". |
| FR-UI-5 | M | Business detail view: contacts, technologies, security findings by severity, opportunities, scores with breakdowns. |
| FR-UI-6 | M | One-click CSV download; one-click PDF per business and per scan. |
| FR-UI-7 | M | Every finding displays its evidence, expandable inline. |
| FR-UI-8 | S | Scan history list with re-run. |

**AC (FR-UI-3).** *Given* a 50-business scan, *when* it is running, *then* the UI shows `12 / 50 complete`, names the business currently being crawled, and renders each finished business's row immediately — results are usable before the scan ends.

---

## 12. Non-functional requirements

### 12.1 Performance

| ID | Requirement |
|---|---|
| NFR-PERF-1 | A 50-business scan completes in ≤ 5 minutes on a 4-core machine. |
| NFR-PERF-2 | Single-site crawl + full analysis ≤ 20 s at p95 (httpx path). |
| NFR-PERF-3 | Analyzers run in ≤ 200 ms per site — they are pure CPU over stored data. |
| NFR-PERF-4 | Up to 10 sites crawled concurrently, but never more than 1 concurrent request per host. |
| NFR-PERF-5 | CSV export of 100 businesses in ≤ 2 s; PDF in ≤ 5 s. |
| NFR-PERF-6 | UI first meaningful paint ≤ 1.5 s. |

### 12.2 Reliability

| ID | Requirement |
|---|---|
| NFR-REL-1 | One site failing never fails the scan. Failures are recorded per business and the scan continues. |
| NFR-REL-2 | Jobs are resumable: an app restart mid-scan resumes from the last completed business. |
| NFR-REL-3 | Every analyzer is total — malformed HTML, missing headers, and absent DNS all produce a result, never an exception that stops the pipeline. |
| NFR-REL-4 | Every external call has an explicit timeout. |
| NFR-REL-5 | Snapshots persist so analysis can re-run without re-crawling. |

### 12.3 Security & compliance

| ID | Requirement |
|---|---|
| NFR-SEC-1 | Passive analysis only — enforced by architecture and asserted by test. |
| NFR-SEC-2 | `robots.txt` always honored; no override. |
| NFR-SEC-3 | Honest, contactable User-Agent on every request. |
| NFR-SEC-4 | Business contact data only; no personal data collection. |
| NFR-SEC-5 | No secrets in code, images, or version control. |
| NFR-SEC-6 | All SQL parameterized; no string-built queries. |
| NFR-SEC-7 | Uploaded CSVs validated for size, type, and row count before parsing. |
| NFR-SEC-8 | Discovery-provider fields respect their source's caching terms. |

### 12.4 Maintainability

| ID | Requirement |
|---|---|
| NFR-MAINT-1 | Adding a technology fingerprint, a security check, or an opportunity rule is a **data change**, not a code change. |
| NFR-MAINT-2 | Modules communicate through defined interfaces only. |
| NFR-MAINT-3 | `mypy --strict` and `ruff` pass on every commit. |
| NFR-MAINT-4 | Every analyzer has fixture-based tests using stored snapshots. |
| NFR-MAINT-5 | A new developer runs the full stack locally within 15 minutes. |

### 12.5 Deployment

| ID | Requirement |
|---|---|
| NFR-DEP-1 | Runs via `docker compose up` with no cloud dependency. |
| NFR-DEP-2 | All configuration from environment variables. |
| NFR-DEP-3 | No cloud-vendor SDK in business logic. |
| NFR-DEP-4 | Playwright browsers baked into the image, not downloaded at runtime. |

---

## 13. Assumptions and open questions

| # | Item | Needed by | Impact if wrong |
|---|---|---|---|
| A1 | Google Places is the production discovery provider | Day 3 | Falls back to OSM + CSV import; lower coverage, no cost |
| A2 | Single-user, single-machine deployment for v1 | — | Multi-tenancy is v3 and already planned for ([SaaS Migration](12-SAAS-MIGRATION-PLAN.md)) |
| A3 | ~60 fingerprints is enough coverage for v1 | Day 7 | Add data, not code |
| A4 | 8 pages per site is enough for contact extraction | Day 5 | Tunable constant |
| **Q1** | **Which discovery provider do we pay for, and what is the budget?** | **Day 3 — blocking** | Determines default provider and per-scan cost |
| Q2 | Do we ship a "known latest version" table for outdated detection, or a static list? | Day 8 | Static list is fine for v1; needs a refresh mechanism later |
| Q3 | Target deployment — the user's laptop, or a hosted instance? | Day 12 | Changes packaging and the PDF/CSV delivery path |

---

## 14. Release criteria for v1.0

- [ ] All `M` requirements implemented and demonstrated
- [ ] Test asserting no outbound connection to any port besides 80/443
- [ ] Test asserting `robots.txt` disallow is honored
- [ ] Test asserting no email address is ever synthesized
- [ ] End-to-end scan of 50 real businesses completes within 5 minutes
- [ ] ≥ 60% of scanned businesses yield a usable business contact
- [ ] ≥ 2 opportunities per site on average, and manual review of 20 finds no generic filler
- [ ] CSV opens cleanly in Excel and Google Sheets
- [ ] PDF reviewed and judged client-presentable
- [ ] `docker compose up` works from a clean clone
- [ ] README quick-start verified on a fresh machine

---

## 15. Approval

| Role | Decision | Date |
|---|---|---|
| Product owner | ☐ Approve ☐ Approve with changes ☐ Reject | |
| Engineering | ☐ Approve ☐ Approve with changes ☐ Reject | |
