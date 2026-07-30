# LeadKhojo — Security Rules

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-30 |
| **Status** | Awaiting approval |
| **Audience** | Everyone who touches the crawler or the security analyzer. **Read before writing code.** |

---

## 1. Why this document exists

LeadKhojo analyzes computers it does not own. That places it in a category where the difference between a legitimate business tool and an offence is a matter of **what requests you send** — not of intent, not of what you do with the results.

The distinction is simple and absolute:

| Legitimate | Not legitimate |
|---|---|
| Requesting a page the server publishes to everyone | Requesting things the server did not offer, to see what exists |
| Reading what the response contains | Probing to see how the server reacts to malformed input |
| Completing a normal TLS handshake and reading the certificate | Testing which ciphers can be downgraded |
| Resolving public DNS | Attempting zone transfers |
| Identifying ourselves honestly | Impersonating a browser to avoid detection |

A visitor is welcome. A visitor trying door handles is not — even if every door turns out to be locked, and even if they meant well.

**LeadKhojo is a visitor. Always.**

---

## 2. The passive-only boundary

### 2.1 What we do

| Action | Why it is passive |
|---|---|
| HTTP `GET` on published pages | Exactly what a browser does |
| Follow redirects (≤ 5) | The server instructed us to |
| Read response headers | The server sent them |
| Complete a TLS handshake, read the certificate | Required to load the page at all |
| Resolve public DNS records | Public directory data, by design |
| Fetch `robots.txt`, `sitemap.xml`, `security.txt` | Published specifically for automated clients |
| Parse the HTML we received | Local processing of data already given to us |

Every one of these is a request the server answers for any visitor, or data it publishes deliberately.

### 2.2 What we never do

| Forbidden | Why |
|---|---|
| **Port scanning** | Probing services the site never advertised. See §5. |
| **Path enumeration / directory brute-forcing** | Requesting thousands of URLs to discover unpublished ones |
| **Vulnerability probing** | Sending input designed to trigger a flaw |
| **Payload injection** (SQLi, XSS, traversal) | Attempted exploitation. Unambiguous. |
| **Authentication attempts** | Trying credentials, default or otherwise |
| **Any exploitation of a finding** | We report configuration. We never demonstrate impact. |
| **DNS zone transfers (AXFR)** | Requesting bulk data not published for public resolution |
| **Subdomain brute-forcing** | Enumeration by another name |
| **Excessive request rates** | Volume alone can constitute a denial of service |
| **Bypassing `robots.txt`, WAFs, rate limits, or bot detection** | Circumvention converts a permitted visit into an unauthorized one |
| **Spoofing our User-Agent** | Evasion. Also destroys the defence "we identified ourselves." |

### 2.3 The test for anything new

Before adding a check, ask:

> **Would a normal visitor's browser, loading this site once, have caused this request?**

- **Yes** → passive. Permitted.
- **No** → active. Forbidden without authorization (§5).
- **Unsure** → treat as active. Ask. The cost of asking is minutes; the cost of guessing wrong is the company.

### 2.4 Two edge cases worth naming

**`path_exists` in technology fingerprints.** Checking for `/wp-login.php` sits close to the line. It is permitted only because:
- It is a single request to a **conventional, publicly documented** path.
- We check a **small fixed list** — never enumerate, never generate candidates.
- The path is already in our fetch budget of 8 pages.
- A 404 is recorded as a 404 and never triggers a follow-up.

If a fingerprint ever needs more than one or two such paths, the fingerprint is wrong. Enumeration is enumeration regardless of how the list was written.

**DKIM selector discovery.** We query a handful of *common, documented* selectors (`default`, `google`, `k1`, `selector1`, `selector2`) as ordinary public DNS lookups. We do not iterate a wordlist. If a domain uses a custom selector, the correct outcome is `not_applicable` — not a broader search.

---

## 3. Crawler conduct

Politeness is not courtesy here — it is what keeps our traffic indistinguishable from legitimate visiting.

| Rule | Value | Rationale |
|---|---|---|
| `robots.txt` | **Always honored. No override exists.** | Explicit instruction from the site owner |
| Concurrency per host | 1 | Never a load spike on one server |
| Delay between requests to a host | ≥ 1 s | Below any reasonable threshold of concern |
| Pages per site | ≤ 8 | Bounded footprint |
| Requests per site per scan | ≤ ~12 including robots/DNS | Less than one human browsing session |
| User-Agent | `LeadKhojoBot/1.0 (+https://leadkhojo.com/bot)` | Identifiable and contactable |
| `429` / `503` | Honor `Retry-After`, ≤ 2 retries, then abandon the host | "Slow down" means slow down |
| Timeouts | 15 s request, 60 s site | Never hold a connection open |
| Sites in parallel | 10 | Breadth, never depth on one target |

### 3.1 The bot page

`https://leadkhojo.com/bot` must exist before public launch and must state:

- What LeadKhojo is and what the crawler collects
- That it honors `robots.txt`
- How to block it (`User-agent: LeadKhojoBot` / `Disallow: /`)
- A working contact address for complaints
- A commitment to respond within two business days

**A crawler that identifies itself but leads nowhere is worse than one that says nothing** — it advertises accountability it does not provide.

### 3.2 If someone asks us to stop

Immediately, without argument, and without asking why:

1. Add the domain to a permanent blocklist checked before any request.
2. Confirm to the requester.
3. Delete existing snapshots for that domain.

A site owner does not owe us a justification.

---

## 4. Data rules

### 4.1 What we collect

Business contact information a company publishes on its own website: role-based email addresses, business phone numbers, business addresses, official social profiles, contact form URLs.

Plus technical configuration: technologies, headers, certificate details, DNS records.

### 4.2 What we never collect

| Never | Why |
|---|---|
| Personal email addresses | Not business contact data; different legal regime |
| Employee names or titles | We are not building a people database ([Vision §9](01-VISION.md)) |
| Personal mobile numbers | Same |
| **Synthesized addresses** | Guessing `first.last@domain` invents personal data. See R4. |
| Anything behind a login | Not public |
| Anything from a source whose terms forbid it | LinkedIn, Facebook, and similar |
| Special-category data | Never relevant to this product |

### 4.3 The synthesis rule, restated

**We never construct a contact that does not literally appear on a fetched page.**

Not `info@{domain}` as a fallback. Not a pattern inferred from one known address. Not a permutation.

Enforced three ways:
1. `business_contacts.source_url` is `NOT NULL` — a synthesized contact has no source URL to give.
2. An architecture test scans for address-construction patterns.
3. Code review.

**A business with no discoverable contact is a correct result.** Reporting "no contact found" is honest. Reporting a guess is inventing personal data and passing it off as observed fact.

### 4.4 Retention and deletion

- Deleting a scan hard-deletes everything beneath it (`ON DELETE CASCADE`).
- Discovery-provider fields are purged at their permitted expiry ([Database Schema §6.1](05-DATABASE-SCHEMA.md)).
- Crawled data has no forced expiry in v1 — it came from the company's own public website. It is deleted when the user deletes the scan, or on request (§3.2).

### 4.5 Where this sits legally

LeadKhojo processes business contact details, published by businesses, for business-to-business purposes. That is a materially lighter regime than personal-data brokerage — which is precisely why [Vision §9](01-VISION.md) rules out becoming the latter.

It is not *zero* obligation. Named individuals' business contact details are still personal data under GDPR, which is one more reason the role-addresses-only rule is absolute rather than a preference.

**Before public launch:** a privacy policy stating what we collect and why, and a working contact route for removal requests. Neither is a v1 engineering task, but neither is optional before real users arrive.

---

## 5. Port scanning — permanently gated

The master specification allows port scanning **"ONLY when authorized and legally appropriate."** This section defines exactly what that means.

### 5.1 Status

**Not in v1. Not planned for v2.** No port-scanning code exists in the repository, and none may be added without the process below.

### 5.2 Why it is different in kind

Every other check in LeadKhojo reads something the server volunteered. A port scan asks *"what else are you running?"* — a question the operator never invited. In several jurisdictions unauthorized scanning is, by itself, an offence regardless of intent or outcome.

The gap between "we sent one HTTP GET like any browser" and "we probed 1,000 ports" is not a difference of degree. It is the difference between the two columns in §1.

### 5.3 If it is ever built

Every one of these is required. Not most.

| # | Requirement |
|---|---|
| 1 | **Written authorization from the domain owner**, stored as a record with the authorizing person, their verified relationship to the domain, scope, and expiry |
| 2 | **Per-target, not per-account.** Authorization for `acme.com` never extends to `acme-subsidiary.com`. |
| 3 | **Verified domain ownership** — DNS TXT record or a file at a well-known path, checked at authorization time |
| 4 | **Time-limited**, maximum 90 days, requiring re-authorization |
| 5 | **A separate module**, feature-flagged off, that refuses to run without a valid, unexpired authorization record |
| 6 | **Fully audited** — who authorized, who ran it, when, what was scanned, what was found |
| 7 | **Legal review** of the flow in every jurisdiction of operation, before any code ships |
| 8 | **Never bundled into a normal scan.** Explicit, separate, deliberate user action. |

### 5.4 The default answer

**No.**

If someone asks for "just a quick port check on the sites we scan," the answer is no. The product's entire defensibility rests on the passive boundary, and it is worth more than any single feature.

---

## 6. Application security

Ordinary engineering hygiene, plus the items specific to running a crawler.

### 6.1 Input handling

| Input | Risk | Control |
|---|---|---|
| Uploaded CSV | Zip bombs, huge files, malformed encoding | 5 MB / 500-row cap; streaming parse; type check before parse |
| Domain / URL from a user | **SSRF** — `localhost`, `169.254.169.254`, internal ranges | Resolve first; reject private, loopback, and link-local addresses. **Non-negotiable.** |
| Crawled HTML | Enormous documents, decompression bombs, XXE | Size cap; `lxml` with entity resolution disabled; parse in a bounded context |
| Discovery provider response | Malformed or hostile payload | Validate through Pydantic before use |
| Rule YAML | Malformed rules | JSON Schema validation at startup; `yaml.safe_load` only |

**SSRF is the highest-severity application risk in this product.** A crawler takes a user-supplied URL and fetches it — which is the textbook SSRF setup. The control (resolve, then reject private ranges, *before* connecting) must be in the fetcher itself, not in a caller that might be bypassed.

```python
BLOCKED = [ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10",
)]

def assert_public_address(resolved_ip: str) -> None:
    addr = ip_address(resolved_ip)
    if any(addr in net for net in BLOCKED):
        raise CrawlError(f"Refusing to fetch a non-public address: {resolved_ip}")
```

This check runs **after DNS resolution and before connecting**, and it re-runs after every redirect. A redirect to `http://169.254.169.254/` is the classic bypass.

### 6.2 Output handling

- **Never render crawled HTML in our UI.** We display extracted text and structured fields only. Crawled HTML is hostile input, and rendering it is stored XSS with extra steps.
- **CSV injection:** a business name beginning with `=`, `+`, `-`, or `@` becomes a formula in Excel. Prefix such values with `'` on export.
- **PDF:** all crawled content is inserted as text, never as markup.

### 6.3 Secrets

- Environment variables only. Never in code, images, or version control.
- `SecretStr` in config so a key cannot be logged by accident.
- Secret scanning in CI.
- **Never log crawled page content** — a page may contain a leaked key, and logging it copies someone else's secret into our logs.

### 6.4 Dependencies

- `uv.lock` committed; builds are reproducible.
- Dependency audit in CI; high and critical severities block.
- Playwright browsers pinned and baked into the image, never fetched at runtime.

### 6.5 Deployment

**v1 has no authentication.** The operational consequence:

> **Never expose a v1 instance to the public internet.**

Bind to `127.0.0.1`, or place it behind a VPN, a reverse proxy with basic auth, or a private network. An open instance lets anyone run scans that appear to originate from your IP — which makes your address the one that gets blocked, and your organization the one that gets the complaint.

Enforced as a **loud startup warning** whenever the API binds to `0.0.0.0`, and stated in the README and `.env.example`.

---

## 7. The ethics of what we produce

Not a legal section — a product one. It matters because it shapes what users say to strangers.

### 7.1 Findings are observations, never accusations

| Write | Never write |
|---|---|
| "No `Content-Security-Policy` header is present." | "Your site is vulnerable to XSS attacks." |
| "The certificate expires on 2026-08-08." | "Your site is about to be hacked." |
| "WordPress 5.4.2 is 4 major releases behind." | "Your site has known exploits." |

We observe configuration. We do **not** assert exploitability, because we have not tested for it — and asserting it would be both false and, in an outreach email, closer to a threat than a pitch.

### 7.2 Outreach must be advisory, never coercive

When the Outreach Assistant ships (v2), generated messages must:

- State the observation and its business consequence
- Offer help
- Never imply threat, never manufacture urgency, never suggest the sender could cause or worsen a problem

**A message that reads as pressure is a defect**, not a conversion tactic. It is also the fastest route to being reported as a malicious actor by the very prospect it was sent to.

### 7.3 We are guests

Every scanned website belongs to someone who did not ask to be analyzed. That is legitimate — the information is public and the analysis is passive — but it warrants restraint:

- We take what we need and leave.
- We identify ourselves.
- We stop when asked.
- We never claim more than we observed.

---

## 8. Incident response

| Situation | Action |
|---|---|
| Site owner asks us to stop | Blocklist immediately, confirm, delete their data. No questions. |
| We are accused of unauthorized access | Preserve logs, stop scanning that target, review what was actually sent, respond with the request record within two business days |
| A vulnerability is found in LeadKhojo | Do **not** open a public issue. Report privately, patch, disclose to affected users. |
| A finding is materially wrong | Fix the rule, capture a fixture, add a test, and consider notifying users who exported that finding |
| The crawler misbehaves (loop, excessive rate) | Kill it. Fix it. Add a test. A runaway crawler is our worst possible incident. |

---

## 9. Non-negotiable summary

Print this. It is the whole document in ten lines.

1. **Passive only.** If a browser wouldn't have sent it, we don't.
2. **`robots.txt` always.** No override, ever.
3. **Identify honestly.** No spoofing, no evasion.
4. **≤ 1 request per second per host.** Never more.
5. **Business contacts only.** Never personal, never synthesized.
6. **No port scanning.** Not without written, verified, time-limited, per-target authorization.
7. **Reject private addresses.** Before connecting, and after every redirect.
8. **Never render crawled HTML.**
9. **Findings are observations, not accusations.**
10. **Stop when asked.** Immediately, and without argument.
