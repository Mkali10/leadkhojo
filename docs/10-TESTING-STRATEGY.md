# LeadKhojo — Testing Strategy

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-30 |
| **Depends on** | [03-ARCHITECTURE.md](03-ARCHITECTURE.md) |

---

## 1. The strategy in one idea

**Because the crawler is the only component that touches the network, every analyzer test is offline, deterministic, and instant.**

This is not a happy accident — it is the payoff of [ADR-02](03-ARCHITECTURE.md). Capture one snapshot from a real website, save it as a JSON fixture, and every downstream test runs against it forever: no network, no mocking HTTP, no flakiness, no waiting.

```
Real website ──(once, manually)──► fixture.json ──► every analyzer test, forever
```

The consequence: the analyzer test suite — the part of the codebase with the most logic and the most edge cases — runs in **under two seconds**. Fast tests get run. Slow tests get skipped.

---

## 2. Test pyramid

```
              ╱╲
             ╱E2E╲          ~5 tests · full scan against a local fixture server
            ╱──────╲
           ╱  INT   ╲       ~30 tests · real Postgres, real repositories
          ╱──────────╲
         ╱   FIXTURE  ╲     ~150 tests · analyzers vs. stored snapshots ← THE CORE
        ╱──────────────╲
       ╱      UNIT      ╲   ~120 tests · pure functions, no I/O
      ╱──────────────────╲
     ╱    ARCHITECTURE    ╲  ~8 tests · boundary rules · THE MOST IMPORTANT
    ╱──────────────────────╲
```

Note the shape: **fixture tests are the widest layer**, not unit tests. That is correct for this product. The hard part is not "does this function work" — it is "does this rule produce the right answer on a real, messy website."

---

## 3. Architecture tests — the load-bearing layer

Small in number, largest in consequence. These enforce the [absolute rules](09-DEVELOPMENT-RULES.md) that make the product defensible.

| Test | Asserts | Protects |
|---|---|---|
| `test_no_io_in_plugins.py` | No module under `plugins/` imports `httpx`, `requests`, `socket`, `dns`, `ssl`, `urllib`, `subprocess`, or `open`; none takes a DB session | R1 · R13 · the entire architecture |
| `test_plugin_isolation.py` | No plugin imports another plugin; every declared dependency resolves; the graph is acyclic | R12 · ADR-12 |
| `test_ai_boundary.py` | No AI/model client is importable from `plugins/` or `opportunities/engine.py`; the rewriter signature returns `str`; `description` is never assigned from a rewrite | **R11** · ADR-13 |
| `test_opportunities_deterministic.py` | 50 runs over one fixture with a fixed clock produce identical output including order | FR-OPP-8 |
| `test_passive_only.py` | A full scan opens **no TCP connection to any port besides 80 and 443** | R2 · the legal boundary |
| `test_robots_enforced.py` | A disallowed path is never requested, under any code path | R3 |
| `test_no_email_synthesis.py` | No source constructs an address from a name and domain; every stored contact has a `source_url` | R4 |
| `test_import_boundaries.py` | Module dependency contracts hold | Architecture §5.2 |
| `test_rules_valid.py` | Every rule pack validates against its JSON Schema and IDs are unique | Rule integrity |
| `test_analyzers_total.py` | Every analyzer returns a result for an empty, minimal, and malformed snapshot | R6 |
| `test_scoring_deterministic.py` | The same snapshot yields identical scores across 100 runs | FR-SCORE-4 |

### 3.1 The two that matter most

**`test_no_io_in_analyzers.py`** walks the AST of every analyzer module:

```python
FORBIDDEN = {"httpx", "requests", "socket", "dns", "ssl", "urllib", "subprocess", "aiohttp"}

def test_analyzers_perform_no_io() -> None:
    violations: list[str] = []
    for path in (SRC / "modules" / "analyzers").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for name in _imported_roots(node):
                    if name in FORBIDDEN:
                        violations.append(f"{path.relative_to(SRC)} imports {name}")
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "open":
                violations.append(f"{path.relative_to(SRC)} calls open()")
    assert not violations, "Analyzers must be pure:\n  " + "\n  ".join(violations)
```

Someone will eventually need "just one more DNS lookup" inside a check. This test is the answer, and the error message tells them where to put it instead.

**`test_passive_only.py`** monkeypatches socket creation for the duration of a full scan and records every port dialled:

```python
async def test_scan_never_connects_outside_web_ports(monkeypatch, local_site) -> None:
    dialled: list[int] = []
    _real = socket.socket.connect

    def _record(self, address):          # type: ignore[no-untyped-def]
        dialled.append(address[1])
        return _real(self, address)

    monkeypatch.setattr(socket.socket, "connect", _record)
    await run_full_scan(local_site.url)

    assert set(dialled) <= {80, 443, 53}, f"Non-web port contacted: {sorted(set(dialled))}"
```

Port 53 is DNS, which is expected and permitted. Anything else is a rule violation and, potentially, a legal one. See [Security Rules](11-SECURITY-RULES.md).

---

## 4. Fixture tests — the core

### 4.1 The corpus

Real snapshots from real websites, committed to `tests/fixtures/snapshots/`.

| Fixture | Exercises |
|---|---|
| `wordpress_outdated.json` | CMS detection, version extraction, outdated flag, maintenance opportunity |
| `wordpress_current.json` | The negative case — no outdated opportunity fires |
| `shopify_clean.json` | E-commerce detection, a well-configured site scoring high |
| `spa_react.json` | Playwright fallback path, JS-rendered contact info |
| `expired_ssl.json` | `TLS-03`, `TLS-04`, critical severity, SSL renewal opportunity |
| `no_dmarc.json` | `DNS-01`/`DNS-03`, email-security opportunity |
| `dmarc_p_none.json` | `DNS-04` — has DMARC but no enforcement. The subtle case. |
| `no_https.json` | `TLS-01`, `CNT-05`, `CNT-06`, critical findings |
| `mixed_content.json` | `CNT-01` |
| `broken_500.json` | Partial snapshot; analyzers must not crash |
| `dns_only.json` | DNS resolved but the site never responded |
| `parked_domain.json` | Detection and skip |
| `no_contact_info.json` | Contact extraction correctly yields **nothing** |
| `international_unicode.json` | Non-ASCII names, addresses, and phone formats |
| `empty.json` | The pathological minimum — every analyzer must survive it |

**Rule: every bug becomes a fixture.** Capture, commit, write a failing test, fix. The corpus only grows, and no bug returns.

```bash
python scripts/capture_snapshot.py https://example.com --name descriptive_name
```

### 4.2 Test shape

```python
def test_expired_certificate_produces_critical_finding() -> None:
    # Arrange
    snapshot = load_fixture("expired_ssl")

    # Act
    findings = SecurityAnalyzer().analyze(snapshot)

    # Assert
    tls_03 = find_by_check_id(findings, "TLS-03")
    assert tls_03.status is FindingStatus.FAIL
    assert tls_03.severity is Severity.CRITICAL
    assert "not_after" in tls_03.evidence
    assert tls_03.remediation is not None
```

- Test names are full sentences describing behavior, not method names.
- Arrange / Act / Assert, visually separated.
- One behavior per test.
- **Assert on evidence, not just status.** A finding without usable evidence is a defect even when the status is right.

### 4.3 What must be tested for every rule

Three cases, always:

| Case | Example |
|---|---|
| **Fires correctly** | Expired certificate → `TLS-03` fails with critical severity |
| **Stays silent correctly** | Valid certificate → `TLS-03` passes, no opportunity |
| **Not applicable** | No TLS connection at all → `not_applicable`, never `fail` |

The third is the one people skip and the one that produces false accusations. "We could not check" is not "you failed."

---

## 5. Unit tests

Pure functions with no I/O. Fast, numerous, unremarkable.

**Must be tested:**

| Area | Why |
|---|---|
| Domain canonicalization | `www.acme.co.uk` → `acme.co.uk` — public-suffix handling is subtle and load-bearing for dedup |
| Version comparison | `1.10` > `1.9`; `5.4.2-beta` must not crash |
| Email classification | The filter rules decide what the user sees |
| Phone normalization | E.164 across regions |
| SPF/DMARC parsing | Real records are messy |
| Score computation | Numeric, weighted, easy to get subtly wrong |
| CSV escaping | Commas, quotes, newlines, unicode inside business names |

**Injected time.** Any function that reads the clock takes it as a parameter. `check_certificate_expiry(snapshot, now=datetime(2026, 8, 1))` is testable; `datetime.now()` inside the function is a test that breaks in 30 days.

---

## 6. Integration tests

Real Postgres via testcontainers. No mocked database.

| Test | Asserts |
|---|---|
| Job claim under concurrency | Ten workers claiming simultaneously never double-claim (`FOR UPDATE SKIP LOCKED`) |
| Scan resumption | Kill mid-scan, restart, work resumes from the last completed business |
| Cascade deletion | Deleting a scan removes businesses, snapshots, contacts, findings, opportunities, scores |
| Dedup constraint | Two businesses with the same domain in one scan → constraint violation, handled |
| Contact provenance | Inserting a contact without `source_url` fails |
| Re-analysis | `POST /businesses/{id}/reanalyze` replaces results without a new crawl |
| Progress accuracy | Counters match reality throughout a scan |

Each test runs in a transaction that is rolled back. No shared state, no ordering dependencies.

---

## 7. End-to-end tests

Few, slow, high value. Run against a **local fixture server** — a static site served on localhost with deliberately planted characteristics — never against the live internet.

| Test | Covers |
|---|---|
| Full CSV scan | Import → crawl → analyze → score → CSV, verified end to end |
| Failure isolation | One site returning 500 does not fail the other four |
| Robots enforcement | A disallowed path is never in the access log |
| Export correctness | Downloaded CSV parses and contains expected values |
| UI happy path (Playwright) | Start scan → watch progress → open detail → expand evidence → export |

**Why a local fixture server rather than real sites:** real sites change, go down, and rate-limit. An E2E suite that depends on the live internet is a suite that fails on Monday for reasons unrelated to the code — and gets disabled by Wednesday.

---

## 8. Coverage

| Area | Minimum | Reason |
|---|---|---|
| Analyzers | **90%** | The core logic. Highest bug density, cheapest tests. |
| Scoring | **90%** | Numeric, subtly wrong-able |
| Opportunity engine | **90%** | Directly shapes what the user says to a prospect |
| Contact extraction | **90%** | Where the no-synthesis rule lives |
| Crawler | 70% | Network paths are harder; failure modes matter most |
| Repositories / services | 70% | — |
| API routers | 60% | Thin by design |
| Frontend | 50% | E2E carries the critical paths |
| **Overall** | **80%** | — |

Coverage is a floor, not a goal. 90% coverage with no `not_applicable` test is worse than 75% with one — a percentage is not a substitute for thinking about what can go wrong.

---

## 9. Manual testing

Some things cannot be automated and must not be skipped.

**Daily from Day 5:** run a real scan against ten real websites. Read the output. Automated tests confirm the code does what you told it to; only reading real output tells you whether what you told it was right.

**Before every release:**

| Check | Method |
|---|---|
| Do opportunities read as specific, or as filler? | Read 20 of them aloud. If they sound like spam, they are. |
| Is the PDF presentable to a client? | Look at it. There is no test for this. |
| Does the CSV open cleanly in Excel and Google Sheets? | Open it in both. BOM handling breaks silently. |
| Do findings match reality? | Pick five, verify by hand with `openssl s_client`, `dig`, `curl -I` |
| Does the UI explain a failure? | Scan a domain that does not exist |
| Is the empty state helpful? | Scan a keyword that returns nothing |

**The most valuable manual check is the first one.** [R7 in the roadmap](07-ROADMAP.md) — generic output — is the failure mode most likely to kill the product, and no automated test detects it.

---

## 10. CI

```
push / PR
   ├─ lint          ruff format --check · ruff check · prettier · eslint
   ├─ types         mypy --strict · tsc --noEmit
   ├─ architecture  ← runs FIRST after lint; fails fast on a rule violation
   ├─ unit          pytest tests/unit · vitest
   ├─ fixture       pytest tests/fixture
   ├─ integration   pytest tests/integration (Postgres service container)
   ├─ e2e           pytest tests/e2e + playwright (main branch only)
   ├─ client-drift  regenerate OpenAPI client, fail if it differs from committed
   └─ security      dependency audit · secret scan
```

**Architecture tests run early and fail fast.** A violation of an absolute rule should stop the pipeline in twenty seconds, not after a six-minute integration suite.

**Never merge red.** On a solo sprint, a red `main` blocks the only person who can unblock it.

---

## 11. Test data rules

- **Never test against production or customer data.** There is none in v1, and the habit should predate the risk.
- **Fixtures are captured from real public websites** — that is the point — but sanitize before committing: strip any personal data that appeared, redact anything that looks like a credential in a page, and prefer well-known sites over small businesses that did not ask to be in a test corpus.
- **Never commit an API key**, including inside a captured snapshot's page HTML. `capture_snapshot.py` runs a redaction pass; review its output before committing.
- **Fixtures are frozen.** Editing a fixture to make a test pass inverts the relationship between test and reality. Capture a new one instead.
