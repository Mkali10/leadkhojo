# LeadKhojo — Development Rules

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-30 |
| **Scope** | What you may and may not do. For how to write the code itself, see [Coding Standards](08-CODING-STANDARDS.md). |

---

## 1. The absolute rules

Violating any of these is a revert, not a discussion. Each is enforced by an automated test where enforcement is possible.

| # | Rule | Enforced by |
|---|---|---|
| **R1** | **No network I/O inside an analyzer.** No HTTP, DNS, socket, TLS, or file access. If an analyzer needs data, the crawler collects it. | `tests/architecture/test_no_io_in_analyzers.py` |
| **R2** | **Passive analysis only.** No port scanning, path enumeration, fuzzing, payload injection, or authentication attempts. No connection to any port besides 80/443. | `tests/architecture/test_passive_only.py` |
| **R3** | **`robots.txt` is always honored.** No override flag exists, and none may be added. | `tests/architecture/test_robots_enforced.py` |
| **R4** | **Never synthesize a contact.** No `first.last@domain`, no pattern inference, no permutation. Only addresses literally present on a fetched page. | `tests/architecture/test_no_email_synthesis.py` + `source_url NOT NULL` |
| **R5** | **Every finding carries evidence.** What was checked, what was seen, when. | `evidence JSONB NOT NULL` |
| **R6** | **Analyzers never raise.** Every input produces a result. | Fixture tests including malformed and empty snapshots |
| **R7** | **No SQL built by string interpolation.** Parameterized or SQLAlchemy only. | `ruff` S608 + review |
| **R8** | **No secrets in code, config files, or images.** Environment variables only. | Secret scanning in CI |
| **R9** | **No external call without an explicit timeout.** | Review + `ruff` ASYNC rules |
| **R10** | **Honest User-Agent on every request.** No spoofing a browser to evade detection. | Review; the UA is a single constant |
| **R11** | **AI never generates a finding, fact, number, date, or opportunity.** It may only rewrite text the rule engine already produced, into a separate field, never overwriting the deterministic original. | `tests/architecture/test_ai_boundary.py` + the `rewrite() -> str` signature |
| **R12** | **Plugins never import each other.** Cross-plugin data flows through declared `depends_on` and `ctx.artifact()`. | `tests/architecture/test_plugin_isolation.py` |
| **R13** | **Plugins do no I/O and receive no clients.** A plugin's world is its `PluginContext`. | `tests/architecture/test_no_io_in_plugins.py` |

**On R2 and R10 together:** a tool that scans quietly and pretends to be Chrome is a different kind of tool than the one we are building. Being identifiable and passive is what makes LeadKhojo defensible — technically, legally, and in conversation with a prospect who noticed the traffic. Read [Security Rules](11-SECURITY-RULES.md) before touching the crawler.

---

## 2. Rules for a three-week MVP

These exist because the schedule is real. They will feel restrictive; that is their job.

### 2.1 Never over-engineer

| Do not build | Until |
|---|---|
| An abstraction | Two concrete implementations exist |
| An interface | The architecture names it a future seam ([ADR list](03-ARCHITECTURE.md)) |
| A configuration option | Someone actually needs a different value |
| A plugin system | A third party is plugging in |
| A cache | A measurement shows it is needed |
| A generic "engine" | The specific version is written and working |

**The test:** if you cannot name the second caller, do not build the abstraction. Write the specific thing. It is easier to extract an abstraction from two working implementations than to bend one implementation to fit a guessed abstraction.

### 2.2 No placeholder architecture

Do not create empty modules, stub interfaces, "for later" directories, or classes whose only method is `pass`.

Every file in the repository must do something on the day it is committed. A folder tree full of `TODO` implies a system that does not exist and makes it impossible to tell what is real.

**Exception:** the `SnapshotStore`, `JobQueue`, and `DiscoveryProvider` protocols each have a *working* implementation from day one. They are seams, not placeholders.

### 2.3 Prefer readable over clever

```python
# Good
def is_outdated(current: str, latest: str) -> bool:
    return parse_version(current) < parse_version(latest)

# Bad — clever, and wrong on "1.10" vs "1.9"
def is_outdated(c, l): return tuple(map(int, c.split('.'))) < tuple(map(int, l.split('.')))
```

The second one also fails on `5.4.2-beta`, which real sites serve.

### 2.4 Rules are data

Adding a technology fingerprint, security check, or opportunity rule must be a **YAML change plus a test**. If you find yourself writing Python to add a detection, the rule engine is missing a capability — extend the engine, not the special cases.

This is what keeps the product improvable after launch by someone who is not deep in the codebase.

### 2.5 Ship the ugly version first

A working plain page beats a beautiful unfinished one. Get the pipeline end-to-end, then improve. Every day of week three has a working product behind it.

---

## 3. Decision rules

### 3.1 When to add a dependency

Ask, in order:

1. Does the standard library do it? (`ssl`, `csv`, `email.utils`, `urllib.parse` cover more than expected)
2. Is it fewer than ~50 lines to write ourselves? Write it.
3. Is it actively maintained, permissively licensed, and widely used?
4. Does it pull in a large transitive tree?

Then add it, and note *why* in the commit message.

**Already approved:** `httpx`, `playwright`, `beautifulsoup4`, `lxml`, `dnspython`, `cryptography`, `reportlab`, `phonenumbers`, `tldextract`, `pyyaml`, `jsonschema`.

### 3.2 When to write a test

**Always**, for: analyzers, rule evaluation, scoring, contact filtering, CSV output, and anything with a numeric threshold.

**Usually**, for: repositories, services, API contracts.

**Rarely**, for: React presentational components, trivial getters, generated code.

Full guidance in [Testing Strategy](10-TESTING-STRATEGY.md).

### 3.3 When to capture a fixture

**Every time a real site surprises you.** That is the whole rule.

```bash
python scripts/capture_snapshot.py https://weird-site.com \
    --name spa_with_cloudflare_challenge
```

Commit it, write a failing test, fix it. The corpus grows with every bug and the bug never returns.

### 3.4 When to stop and ask

Stop and raise it rather than deciding alone if the change would:

- Cross an [absolute rule](#1-the-absolute-rules)
- Change the `SiteSnapshot` shape (it is a contract with six modules and the whole fixture corpus)
- Add a paid external service
- Collect any data category not already permitted
- Extend the schedule

Everything else: decide, note it in `NOTES.md`, move on. A solo three-week sprint dies from deliberation, not from wrong small calls.

---

## 4. Git

### 4.1 Branches

```
main                      always working
feat/<slug>               feature
fix/<slug>                bug fix
chore/<slug>              tooling, deps, docs
```

Branch from `main`, rebase on `main`, squash-merge. Linear history.

**Solo-developer note:** during the MVP sprint, committing small changes directly to `main` is acceptable *provided CI is green*. Branch when a change spans more than a day or touches an absolute rule. Ceremony that protects a team from itself is overhead for a team of one — but a red `main` is never acceptable.

### 4.2 Never commit

- Secrets, API keys, `.env` files
- `node_modules`, `__pycache__`, `.venv`
- Large binaries — **except** fixture snapshots, which belong in `tests/fixtures/snapshots/`
- Generated files, **except** `lib/api/generated.ts` (committed deliberately so drift is reviewable)
- Commented-out code. Delete it; git remembers.

### 4.3 Never merge red

If CI fails, fix it or revert. A red `main` blocks everything and, on a solo sprint, blocks the only person who can unblock it.

---

## 5. Code review

During the MVP a second reviewer may not exist. **The checklist still applies — run it against your own diff before merging.** Reading your own code with a checklist catches a surprising amount.

**Correctness**
- [ ] Does it do what the commit message claims?
- [ ] Edge cases: empty, null, malformed, very large, non-ASCII?
- [ ] For an analyzer: what happens with an empty snapshot?

**Rules**
- [ ] Any network call inside an analyzer? (R1)
- [ ] Any connection beyond 80/443? (R2)
- [ ] Any synthesized contact? (R4)
- [ ] Evidence attached to every finding? (R5)
- [ ] Explicit timeout on every external call? (R9)

**Data**
- [ ] Migration is expand/contract safe?
- [ ] Query bounded by `LIMIT`?
- [ ] N+1 avoided via `selectinload`?
- [ ] Snapshot shape unchanged — or fixtures migrated?

**Quality**
- [ ] Tests cover the new behavior, including failure paths?
- [ ] Names accurate?
- [ ] Anything to delete?
- [ ] Would this be understandable in three weeks with no memory of writing it?

---

## 6. Definition of Done

A change is done when **every** box is true. No partial credit.

- [ ] Works, verified against a real site or a real fixture
- [ ] Tests written and passing
- [ ] `ruff` and `mypy --strict` clean
- [ ] Architecture tests pass
- [ ] Errors handled; analyzers still total
- [ ] Evidence attached where a finding is produced
- [ ] OpenAPI regenerated if the contract changed
- [ ] Fixtures updated if the snapshot shape changed
- [ ] Docs updated if behavior changed
- [ ] Committed with a message explaining why

---

## 7. Working with rules

The rule packs are the product's knowledge, and they will be edited far more often than the Python.

### 7.1 Adding a technology fingerprint

1. Capture a fixture from a real site using that technology.
2. Add the entry to the right `rules/technology/*.yaml`.
3. Add a test asserting detection against the fixture.
4. Verify no false positives across the existing corpus — **this step is not optional.**

### 7.2 Adding a security check

1. Assign the next ID in the category (`DNS-08`).
2. Add the rule with `applies_when`, severity, evidence fields, and remediation.
3. Fixture tests for **pass, fail, and not-applicable** — all three.
4. Decide whether it feeds an opportunity, and wire it if so.

### 7.3 Adding an opportunity rule

1. Confirm the triggering findings exist and are reliable.
2. Write the templates. Apply the specificity gate: **could this text describe any site?** If yes, rewrite or discard.
3. Add a fixture test asserting the rule fires *and* one asserting it stays silent when data is missing.
4. Read the output aloud. If it sounds like spam, it is.

### 7.4 False positives are worse than gaps

A missing detection costs one opportunity. A wrong finding costs the user's trust in every other row — and they will not tell you, they will just stop using it.

When uncertain, lower the confidence or emit nothing.

---

## 8. Performance rules

Only these. Everything else is measured before it is optimized.

| Rule | Why |
|---|---|
| Never fetch the same URL twice in a scan | Politeness and speed |
| Never re-crawl for re-analysis | The entire point of [ADR-02](03-ARCHITECTURE.md) |
| Never load full snapshot HTML in a list query | It is megabytes per row |
| Never `await` inside a per-item loop when the items are independent | Use `gather` with a semaphore |
| Never render with Playwright when httpx succeeded | ~20× the cost |
| Bound every list query with `LIMIT` | — |

**Do not optimize anything else without a measurement.** The analyzers run in milliseconds over in-memory data; the crawler is network-bound. Guessing at hot spots wastes days that the schedule does not have.

---

## 9. What to do when stuck

In order:

1. **Capture a fixture** of the failing case. Half the time, seeing the actual data resolves it.
2. **Write the failing test.** Now the problem is defined.
3. **Timebox to 90 minutes.** After that, ship the degraded-but-honest version — mark it `not_applicable`, record the failure reason, move on. Return with a fresh head.
4. **Write it in `NOTES.md`.** Week three needs a real punch list, not a vague unease.

**Never** leave a silent failure. A check that quietly returns `pass` when it could not actually evaluate is worse than one that says `not_applicable` — the first lies, the second is honest.
