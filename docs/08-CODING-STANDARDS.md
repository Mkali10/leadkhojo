# LeadKhojo — Coding Standards

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-30 |
| **Scope** | How code is written. For what you may and may not do, see [Development Rules](09-DEVELOPMENT-RULES.md). |

---

## 1. Philosophy

1. **Optimize for the reader.** Code is read far more than written — including by you, in three weeks, with no memory of writing it.
2. **Explicit beats implicit.** Magic saves keystrokes today and costs hours later.
3. **Boring is a feature.** The interesting problems live in the analyzers. Everywhere else, be predictable.
4. **Formatting is not an opinion.** It is automated so review time goes to logic.
5. **Delete freely.** Dead code is a lie about what the system does. Git remembers.
6. **Never over-engineer.** No abstraction without two concrete uses. No interface for a single implementation — except where [Architecture](03-ARCHITECTURE.md) names one as a future seam.

---

## 2. Tooling

All enforced in CI, all runnable via `make check`.

### Python

| Tool | Purpose | Config |
|---|---|---|
| `ruff format` | Formatting | Line length 100 |
| `ruff check` | Linting | `E,F,I,N,UP,B,C4,SIM,RUF,S,ASYNC,DTZ` |
| `mypy --strict` | Type checking | No unjustified `Any` |
| `pytest` | Testing | With `--cov` |
| `import-linter` | Module boundaries | Contracts from [Architecture §5.2](03-ARCHITECTURE.md) |
| `uv` | Dependencies | `uv.lock` committed |

### TypeScript

| Tool | Purpose | Config |
|---|---|---|
| `prettier` | Formatting | 100 cols |
| `eslint` | Linting | `typescript-eslint` strict + `react-hooks` |
| `tsc --noEmit` | Type checking | `strict`, `noUncheckedIndexedAccess` |
| `vitest` | Unit tests | — |
| `playwright` | E2E | — |

---

## 3. Python

### 3.1 Types

Full annotations on every function signature. `mypy --strict` passes.

```python
# Good
def extract_emails(snapshot: SiteSnapshot) -> list[ExtractedEmail]: ...

# Bad — the caller must read the body to learn the contract
def extract_emails(snapshot): ...
```

Use `Protocol` for the seams named in the architecture — structural typing keeps implementations decoupled:

```python
class DiscoveryProvider(Protocol):
    id: str
    async def search(self, query: DiscoveryQuery) -> list[DiscoveredBusiness]: ...

class Analyzer(Protocol):
    id: str
    def analyze(self, snapshot: SiteSnapshot) -> list[Finding]: ...
```

Model domain concepts as types where confusion is possible:

```python
Domain = NewType("Domain", str)      # canonical registrable domain
Url = NewType("Url", str)
CheckId = NewType("CheckId", str)    # "TLS-04"
```

Use frozen dataclasses for anything that crosses a module boundary:

```python
@dataclass(frozen=True, slots=True)
class Finding:
    check_id: CheckId
    category: str
    status: FindingStatus
    severity: Severity
    title: str
    description: str
    evidence: dict[str, Any]
    remediation: str | None = None
```

Frozen because findings are facts about a moment in time. Nothing downstream should be able to edit one.

### 3.2 Naming

| Rule | Example |
|---|---|
| Booleans read as assertions | `is_outdated`, `has_ssl`, `should_render` |
| Functions are verb phrases | `extract_emails`, `compute_security_score` |
| Collections are plural | `findings`, `pages` |
| No abbreviations except universal ones | `url`, `dns`, `tls`, `id` ✓ · `res`, `cfg`, `tmp` ✗ |
| Units in the name | `timeout_seconds`, `response_time_ms`, `size_bytes` |
| Rule IDs are constants | `CheckId("TLS-04")`, never a bare string in logic |

### 3.3 Functions

- One job each. Needing "and" to describe it means splitting it.
- Target under 40 lines. Over 60 needs a reason.
- Max 4 positional parameters; beyond that use a dataclass or keyword-only args.
- Guard clauses over nesting. Never nest more than three levels.

```python
# Good — guard clauses, happy path unindented at the bottom
def check_certificate_expiry(snapshot: SiteSnapshot) -> Finding:
    if snapshot.tls is None:
        return Finding.not_applicable(TLS_04, "No TLS connection was established")
    if snapshot.tls.not_after is None:
        return Finding.not_applicable(TLS_04, "Certificate has no expiry date")

    days = (snapshot.tls.not_after - utcnow()).days
    if days < 0:
        return Finding.fail(TLS_04, severity=Severity.CRITICAL, ...)
    if days < 30:
        return Finding.fail(TLS_04, severity=Severity.HIGH, ...)
    return Finding.passed(TLS_04, ...)
```

### 3.4 Analyzers are total functions

**An analyzer never raises.** Every input produces a result, including a snapshot from a site that returned nothing but a 500.

```python
# Good — missing data is a finding, not an exception
def check_dmarc(snapshot: SiteSnapshot) -> Finding:
    if snapshot.dns is None:
        return Finding.not_applicable(DNS_03, "DNS could not be resolved")
    if snapshot.dns.dmarc is None:
        return Finding.fail(DNS_03, severity=Severity.HIGH,
                            evidence={"query": f"_dmarc.{snapshot.domain}",
                                      "result": "NXDOMAIN"})
    return Finding.passed(DNS_03, evidence={"record": snapshot.dns.dmarc})

# Bad — one broken site kills the whole scan
def check_dmarc(snapshot: SiteSnapshot) -> Finding:
    return Finding.passed(DNS_03, evidence={"record": snapshot.dns.dmarc})  # AttributeError
```

The registry wraps every analyzer in a catch-all as a backstop and logs anything that escapes — but **relying on that backstop is a bug**. It exists to protect the scan, not to excuse partial functions.

### 3.5 Async

- **Never block the event loop.** No `time.sleep`, no `requests`, no synchronous file I/O in async code. Ruff's `ASYNC` rules catch most of it.
- CPU-bound work (HTML parsing of a very large page) goes to `run_in_executor`, not inline.
- Every external call has an explicit timeout. **A call without a timeout is a hang without a limit.**

```python
async with httpx.AsyncClient(
    timeout=httpx.Timeout(15.0, connect=5.0),
    follow_redirects=True,
    max_redirects=5,
    headers={"User-Agent": USER_AGENT},
) as client:
    response = await client.get(url)
```

- Use `asyncio.gather` for independent work; bound fan-out with a semaphore. Cross-site concurrency is 10; per-host is always 1.

### 3.6 Errors

A defined hierarchy. Never `raise Exception`, never bare `except:`.

```python
class LeadKhojoError(Exception):
    code: str
    status_code: int

class NotFoundError(LeadKhojoError):        code, status_code = "not_found", 404
class ValidationError(LeadKhojoError):      code, status_code = "validation_failed", 422
class InvalidCsvError(LeadKhojoError):      code, status_code = "invalid_csv", 422
class ProviderError(LeadKhojoError):        code, status_code = "discovery_provider_failed", 424
class CrawlError(LeadKhojoError):           ...  # internal; never reaches HTTP
```

Rules:
- Catch the narrowest exception that can occur.
- Never swallow silently — log with context or re-raise.
- Messages state **what happened, why, and what to do next**.
- Crawl failures are *data*, not exceptions: they become a `failure_reason` on the snapshot.

```python
# Good
raise InvalidCsvError(
    f"{len(invalid)} of {total} rows are missing a value in the 'domain' column.",
    meta={"invalid_rows": invalid, "valid_row_count": total - len(invalid)},
)
```

### 3.7 Database

**Repositories own all queries.**

```python
async def list_completed(self, scan_id: UUID, *, limit: int) -> Sequence[Business]:
    stmt = (
        select(Business)
        .where(Business.scan_id == scan_id, Business.status == BusinessStatus.COMPLETED)
        .options(selectinload(Business.scores))
        .order_by(Business.created_at)
        .limit(limit)
    )
    return (await self._session.scalars(stmt)).all()
```

- **Never build SQL by string concatenation or f-string.** Parameterized or SQLAlchemy only.
- Services own transactions; repositories never commit.
- Load relationships explicitly with `selectinload`. Lazy loading is disabled so an N+1 is a visible mistake, not a mystery.
- Every list query is bounded by `LIMIT`.

### 3.8 Configuration

All configuration through `core/config.py`, validated at boot. **No `os.environ` anywhere else.**

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LK_", env_file=".env")

    database_url: PostgresDsn
    max_pages_per_site: int = 8
    crawl_timeout_seconds: float = 15.0
    site_budget_seconds: float = 60.0
    max_concurrent_sites: int = 10
    user_agent: str = "LeadKhojoBot/1.0 (+https://leadkhojo.com/bot)"
    google_places_api_key: SecretStr | None = None
```

A missing or malformed variable fails at startup, loudly. Failing later, mid-scan, with a `KeyError` is strictly worse.

### 3.9 Logging

```python
logger.info(
    "crawl.completed",
    extra={"domain": domain, "pages": len(pages),
           "render_mode": mode, "duration_ms": elapsed},
)
```

- Structured, event-named (`noun.verb_past`), never f-string messages.
- `print()` is banned outside `scripts/`.
- Never log full page HTML — log its length and hash.
- Levels: `DEBUG` local · `INFO` pipeline events · `WARNING` recoverable (site failed, provider degraded) · `ERROR` something needs attention · `CRITICAL` the app cannot function.

---

## 4. Rule packs

Rule YAML is code with a different syntax. It gets the same care.

```yaml
- id: TLS-04
  name: Certificate expires soon
  category: tls
  severity_when_failing: high
  applies_when: { tls: present }
  check:
    type: cert_days_remaining
    thresholds: [{ under: 0, severity: critical }, { under: 30, severity: high }]
  evidence_fields: [not_after, days_remaining, issuer]
  remediation: >
    Renew the certificate before it expires and enable automatic renewal
    via ACME (Let's Encrypt, ZeroSSL) so this cannot recur.
  opportunity: ssl_renewal
```

**Standards:**

- **Every rule has a stable ID.** IDs appear in exports and reports and never change.
- **`remediation` is written for the recipient**, not for us. The user forwards it.
- **Every rule declares `applies_when`.** A check that cannot apply returns `not_applicable`, never `fail`.
- **Every rule has a fixture test.** New rule, new test, same commit.
- **Validated at startup** against JSON Schema. A malformed file fails the boot.

### 4.1 Opportunity text

The description is read by a salesperson and shapes what they say. Write it accordingly.

```yaml
description_template: >
  The SSL certificate for {domain} expires on {not_after} ({days_remaining} days).
  When it lapses, every visitor sees a full-page browser security warning and
  the site is effectively offline for most users.
pitch_angle: >
  Lead with the date. It is verifiable in ten seconds and creates a real
  deadline without any pressure tactics.
```

**Rules for this text:**

- **Specific, or absent.** No template that could describe any site. If the data to fill it is missing, produce nothing.
- **Business consequence, not technical description.** "Every visitor sees a security warning" beats "certificate validity period ending."
- **Never alarmist.** State the fact and its consequence. No threat framing, no manufactured urgency, no implication that the sender could cause harm. Alarmism is both a product defect and an ethical one.

---

## 5. TypeScript / React

### 5.1 Types

```tsx
interface ScoreBadgeProps {
  label: string
  value: number
  variant?: 'default' | 'inverse'   // inverse: lower is better
}

export function ScoreBadge({ label, value, variant = 'default' }: ScoreBadgeProps) {
```

- `any` is banned. Use `unknown` and narrow.
- Never hand-write API types — import from `lib/api/generated.ts`.
- No `React.FC` (adds implicit children, weakens inference).
- Discriminated unions for mutually exclusive states:

```ts
type ScanState =
  | { status: 'pending' }
  | { status: 'running'; completed: number; total: number; current: string | null }
  | { status: 'completed'; businesses: Business[] }
  | { status: 'failed'; error: string }
```

### 5.2 Components

- One component per file, named the same as the file.
- Under 200 lines. Beyond that, extract.
- Presentational components take props and do not fetch.
- Data fetching lives in `features/*/hooks.ts` via TanStack Query — never an inline `useEffect` fetch.
- No business logic in `pages/`.

### 5.3 State

| Kind | Where |
|---|---|
| Server data | TanStack Query |
| Sort / filter / pagination | URL search params |
| Ephemeral UI (expanded, hovered) | `useState` |
| Form state | `useState` — the forms are small |

**Sort and filter live in the URL.** A user must be able to send a colleague a link to a filtered result set. That is a product requirement expressed as a state rule.

### 5.4 Polling

```tsx
export function useScanProgress(scanId: string) {
  return useQuery({
    queryKey: ['scan', scanId, 'progress'] as const,
    queryFn: () => api.getScanProgress(scanId),
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return s && ['pending', 'discovering', 'analyzing'].includes(s) ? 2000 : false
    },
  })
}
```

Returning `false` stops polling. A poll that never stops is a bug that only shows up on someone's laptop three hours later.

### 5.5 Accessibility

Not a polish pass — part of done.

- Semantic HTML first. A `div` with `onClick` is a bug; use `button`.
- Every interactive element keyboard-reachable with a visible focus state.
- Every input has a `label`.
- Icon-only buttons have `aria-label`.
- Contrast ≥ 4.5:1 for text.
- **Severity is never communicated by colour alone** — always colour *and* text. A red badge reading "critical" works for everyone.

---

## 6. Documentation in code

Docstrings where behavior is not obvious from the signature. Document **why**, not what.

```python
def should_render_with_browser(page: PageCapture) -> bool:
    """Decide whether the HTTP fetch returned usable content.

    Server-rendered sites are the common case and cost ~20x less than a
    browser render, so we only escalate when the fast path visibly failed:
    almost no visible text, or an empty SPA root element.

    The heuristic is deliberately crude. Over-triggering costs a few
    seconds; under-triggering costs a wrong answer for the whole site.
    """
```

Comments explain the non-obvious. If a comment restates the code, delete one of them — usually the comment.

```python
# Good — explains a decision the code cannot express
# Sequential, not gathered: one concurrent request per host is a politeness
# guarantee, and gathering here would silently break it.
for url in page_urls:
    pages.append(await self._fetch(url))
    await asyncio.sleep(HOST_DELAY_SECONDS)
```

---

## 7. Commits

Conventional Commits.

```
feat(security): add DMARC policy strength check (DNS-04)

A DMARC record with p=none provides reporting but no enforcement, so
"has DMARC" alone overstated a domain's protection. Splitting presence
(DNS-03) from policy strength (DNS-04) lets the opportunity engine pitch
enforcement rollout separately from initial setup.
```

- Subject: imperative, ≤ 72 chars, no trailing period.
- Body explains **why**. The diff shows what.
- Commit at least twice a day. A day's work in one commit is a day's work at risk.
