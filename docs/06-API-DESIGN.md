# LeadKhojo — API Design

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-30 |
| **Base URL** | `http://localhost:8000/api/v1` |
| **Spec** | OpenAPI 3.1, generated from code |
| **Depends on** | [05-DATABASE-SCHEMA.md](05-DATABASE-SCHEMA.md) |

---

## 1. Design rules

| Rule | Decision |
|---|---|
| Style | REST over HTTP, JSON only |
| Versioning | URL path (`/api/v1`) |
| Naming | Plural kebab-case resources; `snake_case` JSON fields (matches the Python backend — one convention end to end) |
| Timestamps | ISO 8601 UTC with `Z` |
| IDs | UUID strings |
| Pagination | Offset/limit. Result sets are ≤ 100 by design; cursors would be over-engineering. |
| Errors | RFC 9457 Problem Details |
| Long operations | `202 Accepted` + a resource to poll |
| **Auth** | **None in v1.** See §2. |

---

## 2. Authentication

**There is no authentication in v1.** LeadKhojo runs as a single-user local or self-hosted application.

This is a deliberate scope decision ([ADR-08](03-ARCHITECTURE.md)), not an oversight, and it comes with an operational obligation:

> **Do not expose a v1 instance to the public internet.** Bind to `127.0.0.1`, or put it behind a VPN, a reverse-proxy with basic auth, or a private network. An open instance lets anyone run scans that appear to originate from your IP.

This is stated in the README, in `.env.example`, and printed as a startup warning when the API binds to `0.0.0.0`.

**Where auth lands in v3:** an `Authorization: Bearer` header, resolved by a single FastAPI dependency, plus an `org_id` filter in the repository base class. The routes below do not change shape. See [SaaS Migration Plan](12-SAAS-MIGRATION-PLAN.md).

---

## 3. Standard headers

**Request**

| Header | When | Purpose |
|---|---|---|
| `Content-Type: application/json` | On write | — |
| `X-Correlation-Id` | Optional | Propagated through logs; echoed back |

**Response**

| Header | Always | Purpose |
|---|---|---|
| `X-Correlation-Id` | Yes | Quote this when reporting a problem |
| `Retry-After` | On `503` | Seconds |

---

## 4. Errors

RFC 9457 Problem Details. Every error is machine-readable and tells the user what to do next.

```json
{
  "type": "https://docs.leadkhojo.com/errors/invalid-csv",
  "title": "CSV could not be parsed",
  "status": 422,
  "detail": "3 of 40 rows are missing a value in the required 'domain' column.",
  "code": "invalid_csv",
  "correlation_id": "018f3a2b-7c1d-7890-a1b2-c3d4e5f6a7b8",
  "meta": {
    "invalid_rows": [
      { "row": 7,  "reason": "empty domain" },
      { "row": 19, "reason": "not a valid domain: 'n/a'" },
      { "row": 33, "reason": "empty domain" }
    ],
    "valid_row_count": 37
  }
}
```

Note that the error is **actionable and partial**: it names the exact rows, and it tells the user 37 rows are fine so they can decide whether to proceed. An error that says "invalid CSV" and nothing else forces the user to guess.

### 4.1 Error catalogue

| Status | `code` | Meaning |
|---|---|---|
| 400 | `malformed_request` | Unparseable body |
| 404 | `not_found` | No such scan or business |
| 409 | `scan_already_running` | Cannot re-run a scan that is still in progress |
| 409 | `scan_not_complete` | Export requested before the scan finished |
| 413 | `file_too_large` | Upload exceeds 5 MB |
| 422 | `validation_failed` | Semantic validation failure |
| 422 | `invalid_csv` | CSV parsed but rows are invalid |
| 424 | `discovery_provider_failed` | Upstream provider unavailable |
| 500 | `internal_error` | Our fault; correlation ID logged |
| 503 | `service_unavailable` | Database or a dependency is down |

Validation errors list **every** failure at once. Fail-fast on the first bad field makes users iterate one mistake at a time.

---

## 5. Endpoints

### 5.1 Scans

| Method | Path | Description |
|---|---|---|
| `POST` | `/scans` | Create and start a scan → `202` |
| `GET` | `/scans` | List scans (paginated) |
| `GET` | `/scans/{id}` | Scan detail with summary statistics |
| `GET` | `/scans/{id}/progress` | Lightweight progress — **the polling endpoint** |
| `GET` | `/scans/{id}/businesses` | Results, sortable and filterable |
| `POST` | `/scans/{id}/cancel` | Stop a running scan |
| `POST` | `/scans/{id}/rerun` | Re-run the same query as a new scan |
| `DELETE` | `/scans/{id}` | Delete the scan and everything under it |

**`POST /scans`**

```json
{
  "keyword": "dental clinics",
  "location": "Austin, TX",
  "provider": "google_places",
  "limit": 50
}
```

```json
// 202 Accepted
{
  "id": "018f3a2b-7c1d-7890-a1b2-c3d4e5f6a7b8",
  "status": "pending",
  "keyword": "dental clinics",
  "location": "Austin, TX",
  "provider": "google_places",
  "limit": 50,
  "created_at": "2026-07-30T14:03:11Z"
}
```

**`GET /scans/{id}/progress`** — polled every 2 s by the UI while a scan runs. Deliberately small and cheap.

```json
{
  "id": "018f3a2b-…",
  "status": "analyzing",
  "total_businesses": 50,
  "completed_count": 12,
  "failed_count": 1,
  "percent_complete": 26,
  "current_business": "Northwind Dental",
  "elapsed_seconds": 74,
  "estimated_remaining_seconds": 210
}
```

`current_business` exists purely so the UI can say *"analyzing Northwind Dental"* rather than showing an anonymous spinner (FR-UI-3). A progress bar tells the user to wait; a name tells them the thing is alive.

**`GET /scans/{id}/businesses`**

Query parameters:

| Param | Values | Default |
|---|---|---|
| `sort` | `opportunity_score`, `lead_score`, `security_score`, `website_score`, `name` | `opportunity_score` |
| `order` | `asc`, `desc` | `desc` |
| `status` | `completed`, `failed`, `no_website`, `all` | `completed` |
| `has_contact` | `true`, `false` | — |
| `opportunity_category` | `security`, `performance`, … (repeatable) | — |
| `min_opportunity_score` | 0–100 | — |
| `limit` / `offset` | ≤ 100 / ≥ 0 | 50 / 0 |

```json
{
  "data": [
    {
      "id": "018f3a2c-…",
      "name": "Northwind Dental",
      "domain": "northwinddental.com",
      "website_url": "https://northwinddental.com",
      "city": "Austin",
      "country_code": "US",
      "status": "completed",
      "primary_email": "info@northwinddental.com",
      "primary_phone": "+15125550142",
      "contact_count": 4,
      "scores": {
        "lead": 78, "website": 41, "security": 32, "opportunity": 87
      },
      "top_technologies": [
        { "name": "WordPress", "version": "5.4.2", "category": "cms", "is_outdated": true },
        { "name": "Nginx", "version": null, "category": "server", "is_outdated": null }
      ],
      "opportunity_count": 5,
      "top_opportunity": {
        "title": "SSL certificate expires in 9 days",
        "category": "security",
        "urgency": "critical"
      },
      "critical_findings": 2,
      "high_findings": 4,
      "scanned_at": "2026-07-30T14:05:22Z"
    }
  ],
  "pagination": { "total": 47, "limit": 50, "offset": 0 },
  "meta": { "scan_status": "completed" }
}
```

The row is designed so the results table needs **no follow-up requests** to render. Everything a user sorts, filters, or scans visually is here.

### 5.2 Businesses

| Method | Path | Description |
|---|---|---|
| `GET` | `/businesses/{id}` | Full detail — contacts, tech, findings, opportunities, scores |
| `GET` | `/businesses/{id}/findings` | Security findings, filterable by severity/status |
| `GET` | `/businesses/{id}/opportunities` | Opportunities with evidence |
| `GET` | `/businesses/{id}/snapshot` | Raw snapshot metadata (debugging; excludes page HTML) |
| `POST` | `/businesses/{id}/reanalyze` | Re-run analyzers on the **stored snapshot** — no re-crawl |

**`POST /businesses/{id}/reanalyze` is the payoff of [ADR-02](03-ARCHITECTURE.md).** Improve a fingerprint, re-run analysis on data already captured, get corrected results in under a second — and the target website is never contacted again.

**`GET /businesses/{id}`** (abridged):

```json
{
  "id": "018f3a2c-…",
  "name": "Northwind Dental",
  "domain": "northwinddental.com",
  "final_url": "https://northwinddental.com/",
  "status": "completed",

  "contacts": {
    "emails": [
      { "value": "info@northwinddental.com", "category": "general",
        "source_url": "https://northwinddental.com/contact", "rank": 10 }
    ],
    "phones": [
      { "value": "+15125550142", "source_url": "https://northwinddental.com/contact" }
    ],
    "address": "1200 Congress Ave, Austin, TX 78701",
    "socials": [
      { "category": "facebook", "value": "https://facebook.com/northwinddental",
        "source_url": "https://northwinddental.com/" }
    ],
    "contact_form_url": "https://northwinddental.com/contact"
  },

  "technologies": [
    { "technology_id": "wordpress", "name": "WordPress", "category": "cms",
      "version": "5.4.2", "confidence": "certain",
      "is_outdated": true, "versions_behind": 4,
      "evidence": { "meta_generator": "WordPress 5.4.2", "html_pattern": "/wp-content/" } }
  ],

  "findings": [
    {
      "check_id": "TLS-04",
      "category": "tls",
      "status": "fail",
      "severity": "high",
      "title": "SSL certificate expires soon",
      "description": "The certificate expires on 2026-08-08, in 9 days.",
      "evidence": {
        "not_after": "2026-08-08T00:00:00Z",
        "days_remaining": 9,
        "issuer": "Let's Encrypt R3",
        "checked_at": "2026-07-30T14:05:19Z"
      },
      "remediation": "Renew the certificate and enable automatic renewal via ACME."
    }
  ],

  "opportunities": [
    {
      "rule_id": "ssl_renewal",
      "title": "SSL certificate renewal & monitoring",
      "category": "security",
      "urgency": "critical",
      "description": "Their SSL certificate expires in 9 days. When it lapses, every visitor sees a full-page browser security warning and the site is effectively offline for most users.",
      "pitch_angle": "Lead with the date. This is verifiable in ten seconds and creates a real deadline without any pressure tactics.",
      "triggered_by": ["TLS-04"],
      "evidence": { "expires": "2026-08-08", "days_remaining": 9 }
    }
  ],

  "scores": {
    "lead":        { "total": 78, "confidence": 1.0,
                     "components": { "contact_availability": 40, "business_signals": 18,
                                     "site_reachable": 20, "category_fit": 0 } },
    "website":     { "total": 41, "confidence": 1.0, "components": { "…": 0 } },
    "security":    { "total": 32, "confidence": 0.9, "components": { "…": 0 } },
    "opportunity": { "total": 87, "confidence": 1.0, "components": { "…": 0 } }
  },

  "snapshot_meta": {
    "captured_at": "2026-07-30T14:05:14Z",
    "render_mode": "http",
    "page_count": 4,
    "duration_ms": 3820,
    "status": "complete"
  }
}
```

Note `"category_fit": 0` in the lead breakdown — the component is present and zero, not omitted. **A component that scored nothing still reports itself**, so the user can see it was considered.

### 5.3 CSV import

| Method | Path | Description |
|---|---|---|
| `POST` | `/imports/csv/validate` | Dry run — parse and report, create nothing |
| `POST` | `/imports/csv` | Create a scan from an uploaded CSV |

`multipart/form-data` with a `file` field. Max 5 MB, max 500 rows. Accepts a `domain` or `website` column; optional `name`, `city`, `country`.

**`/validate` exists so a user never uploads 400 rows and discovers afterwards that column detection went wrong.** It returns the same body shape as the import, with `created: false`.

```json
{
  "created": false,
  "valid_row_count": 37,
  "invalid_rows": [{ "row": 7, "reason": "empty domain" }],
  "detected_columns": { "domain": "Website URL", "name": "Company" },
  "preview": [{ "row": 1, "name": "Acme Corp", "domain": "acme.com" }]
}
```

### 5.4 Exports

| Method | Path | Returns |
|---|---|---|
| `GET` | `/exports/scans/{id}/csv` | `text/csv` |
| `GET` | `/exports/scans/{id}/pdf` | `application/pdf` — scan summary |
| `GET` | `/exports/businesses/{id}/pdf` | `application/pdf` — single-business report |

Query parameters mirror `/scans/{id}/businesses` (`sort`, `status`, filters) so **what you see is what you export**.

Exports are generated synchronously — 100 businesses is a two-second CSV and a five-second PDF. Returned with `Content-Disposition: attachment; filename="leadkhojo-dental-clinics-austin-20260730.csv"`.

Requesting an export for an unfinished scan returns `409 scan_not_complete` with the current progress in `meta`, so the UI can show "ready in about 3 minutes" rather than a bare error.

### 5.5 Metadata

| Method | Path | Description |
|---|---|---|
| `GET` | `/meta/providers` | Available discovery providers and their configuration status |
| `GET` | `/meta/technologies` | The loaded fingerprint catalogue |
| `GET` | `/meta/checks` | The loaded security check catalogue |
| `GET` | `/meta/opportunity-rules` | The loaded opportunity rules |

These make the rule packs introspectable. When a user asks "do you detect Craft CMS?", the answer is a URL, not a code read.

### 5.6 Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Liveness — process is up. **No dependency checks.** |
| `GET` | `/readyz` | Readiness — database reachable, rules loaded |
| `GET` | `/version` | Build SHA and version |

Liveness must not check the database. If it did, a brief database blip would cause the orchestrator to kill a healthy API container — turning a degradation into an outage.

---

## 6. Polling contract

The UI polls `/scans/{id}/progress` every 2 seconds while `status` is `pending`, `discovering`, or `analyzing`, and stops on any terminal status.

Deliberately chosen over WebSockets ([ADR-09](03-ARCHITECTURE.md)): polling is ~15 lines with no reconnection, backpressure, or proxy-compatibility concerns. A 2-second delay on a 4-minute operation is imperceptible.

**Client responsibilities:**

1. Stop polling on `completed`, `failed`, or `cancelled`.
2. Back off to 10 s after 5 minutes of polling (a stuck scan should not generate load forever).
3. Fetch `/scans/{id}/businesses` when `completed_count` increases, so finished rows appear during the scan.
4. Treat a `404` as "the scan was deleted" and stop.

---

## 7. Versioning and stability

| Change | Breaking? |
|---|---|
| New endpoint | No |
| New optional request field | No |
| New response field | No — clients must ignore unknown fields |
| New enum value | **Yes in practice** — clients must handle unknown values gracefully |
| Removing or renaming a field | Yes → `/api/v2` |
| Tightening validation | Yes → `/api/v2` |

**Snapshot JSONB shapes are an internal contract, not a public one** ([Database Schema §4](05-DATABASE-SCHEMA.md)). `/businesses/{id}/snapshot` returns metadata only and is explicitly documented as unstable, for debugging.

---

## 8. Client responsibilities

Stated explicitly, because the alternative is discovering them in a bug report.

1. **Ignore unknown response fields.** Fields are added in minor releases.
2. **Handle unknown enum values.** New severities, categories, and failure reasons will appear.
3. **Stop polling on terminal status.**
4. **Expect partial results.** A `completed` scan can still contain `failed` businesses — that is normal, not an error.
5. **Never assume a contact exists.** `primary_email` is frequently `null`, and that is a correct answer, not a bug.
6. **Render evidence.** Every finding carries it. A UI that hides evidence throws away the product's main advantage.
