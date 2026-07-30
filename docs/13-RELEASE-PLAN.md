# LeadKhojo — Release Plan

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-30 |
| **Depends on** | [07-ROADMAP.md](07-ROADMAP.md) |

---

## 1. Versioning

Semantic versioning.

| Bump | When |
|---|---|
| **Major** | Breaking API change, or a change requiring user action |
| **Minor** | New capability, backward compatible |
| **Patch** | Bug fixes, new rule packs, no behavior change |

**Rule packs bump the patch version.** Adding fingerprints or security checks changes what a scan finds but breaks nothing — and it will happen weekly. It should never require a minor release.

---

## 2. Release map

| Version | Theme | Ships | Trigger |
|---|---|---|---|
| **1.0** | **MVP** — the full pipeline | Discovery · Crawler · Contacts · Tech · Security · Opportunities · Scores · CSV · PDF | Day 15 of the roadmap |
| 1.1 | Accuracy | +40 fingerprints, +10 checks, fixes from real use | ~2 weeks after 1.0 |
| 1.2 | Repeat use | Saved projects, scan history, re-scan and diff | A user asks "what changed since last month?" |
| **2.0** | **Outreach Assistant** | Cold email, LinkedIn message, proposal summary, meeting notes, follow-ups | Users are copying findings into emails by hand |
| 3.0 | **SaaS** | Auth, teams, quotas, billing | A second person needs their own account |
| **4.0** | **Monitoring** | Watch a portfolio, alert on certificate expiry and stack changes | The strongest long-term position |
| 5.0 | Integrations | Push to HubSpot / Salesforce / Pipedrive | Users ask by name |

---

## 3. v1.0 — MVP

### 3.1 Scope

**In:** Business Discovery (CSV + one live provider) · Website Intelligence · Contact Extraction · Technology Detection (≥ 60 fingerprints) · Security Intelligence (28 checks) · Opportunity Engine (≥ 16 rules) · four independent scores · CSV export · PDF reports · React UI with live progress.

**Out:** Auth · billing · CRM · extensions · API marketplace · white label · AI agents · multi-user · email automation · Outreach Assistant.

### 3.2 Release gate

Every box, or it does not ship.

**Functional**
- [ ] All `M` requirements in the [PRD](02-PRD.md) implemented and demonstrated
- [ ] A 50-business scan runs end to end from the browser
- [ ] CSV opens cleanly in **both** Excel and Google Sheets
- [ ] PDF judged client-presentable by a human looking at it

**Quality**
- [ ] ≥ 60% of scanned businesses yield a usable business contact
- [ ] ≥ 2 opportunities per site on average
- [ ] **20 opportunities read aloud; none is generic filler** ← the one that decides whether this product survives
- [ ] Five findings hand-verified with `openssl s_client`, `dig`, and `curl -I`

**Rules (non-negotiable)**
- [ ] `test_passive_only.py` passes — no port outside 80/443/53
- [ ] `test_no_io_in_analyzers.py` passes
- [ ] `test_robots_enforced.py` passes
- [ ] `test_no_email_synthesis.py` passes
- [ ] SSRF guard rejects private addresses, including after a redirect

**Performance**
- [ ] 50-business scan ≤ 5 minutes
- [ ] p95 single-site crawl + analysis ≤ 20 s
- [ ] CSV ≤ 2 s, PDF ≤ 5 s

**Operational**
- [ ] `docker compose up` works from a clean clone
- [ ] README quick start verified on a fresh machine
- [ ] `.env.example` complete and documented
- [ ] Startup warning fires when binding to `0.0.0.0`
- [ ] Test coverage ≥ 80% overall, ≥ 90% on analyzers

### 3.3 What "shipped" means for v1

v1.0 is **self-hosted, single-user, and not publicly exposed**. Success is one person running one scan and contacting one company they would not otherwise have found.

It is not a launch. It is a proof.

---

## 4. v1.1 — Accuracy

Two weeks after v1.0, driven entirely by real use.

| Deliverable | Detail |
|---|---|
| +40 fingerprints | Whatever real scans failed to identify |
| +10 security checks | Gaps found in practice |
| Opportunity tuning | Rewrite any rule whose output reads as filler |
| False-positive fixes | Every one becomes a fixture and a test |
| Crawler robustness | The edge cases real websites produced |

**No new features.** v1.1 makes v1.0 correct. The temptation after a launch is to add; the value is in fixing.

**Gate:** false-positive rate on a 100-site sample below 5%, and every fix has a fixture test.

---

## 5. v1.2 — Repeat use

The first version that assumes a user comes back.

| Deliverable | Why |
|---|---|
| Saved projects | Group scans by client or campaign |
| Scan history with search | Find that scan from three weeks ago |
| **Re-scan and diff** | "What changed since last month?" — the foundation for v4 monitoring |
| Bulk re-analysis | Apply improved rules to stored snapshots across every past scan |

**Bulk re-analysis is the compounding feature.** Every rule improvement retroactively improves every scan ever run — without touching a single website again. It is the clearest payoff of [ADR-02](03-ARCHITECTURE.md), and it only becomes visible once there is history to re-analyze.

---

## 6. v2.0 — Outreach Assistant

| Deliverable | Detail |
|---|---|
| Cold email generation | From findings, opportunities, and the user's service description |
| LinkedIn message | Short form |
| Proposal summary | Client-facing |
| Meeting notes & talking points | Pre-call prep |
| Follow-up suggestions | Sequenced, not automated |
| User service profile | What the user sells, so drafts are relevant |

**Implementation:** Anthropic API with model `claude-opus-5`. Findings and opportunities are passed as structured context; the model composes prose but is **never the source of a factual claim**. A deterministic template path exists for offline operation and for users without an API key.

**Gate — the tone rule.** Twenty generated messages reviewed. Any message that implies threat, manufactures urgency, or suggests the sender could cause harm is a **release blocker**, not a tuning note. See [Security Rules §7.2](11-SECURITY-RULES.md).

**LeadKhojo never sends anything.** It drafts; the user sends. That boundary is permanent.

---

## 7. v3.0 — SaaS

Auth, teams, quotas, billing. Fully specified in the [SaaS Migration Plan](12-SAAS-MIGRATION-PLAN.md).

**Gate additions:**
- [ ] Tenant isolation test on every endpoint
- [ ] RLS enabled and `FORCE`d on every tenant table
- [ ] Third-party penetration test with no unresolved high or critical findings
- [ ] Stripe flows verified including failed payment and dunning
- [ ] Dedicated crawler egress IP pool with per-tenant rate accounting
- [ ] Backup restore rehearsed into a clean environment
- [ ] Privacy policy, terms, and the `/bot` page published

---

## 8. v4.0 — Monitoring

**The most valuable version in this plan.**

Discovery is a one-time act; monitoring is a subscription. A consultant watching 200 client and prospect sites, told the moment a certificate is expiring or a stack changes, has a reason to pay every month — and a reason to call the client that day.

| Deliverable | Detail |
|---|---|
| Watchlists | Portfolios of domains, scanned on a schedule |
| Change detection | Diff snapshots; surface what moved |
| Alerts | Certificate expiring, technology changed, security posture degraded, site down |
| Notifications | Email and webhook |
| Timeline view | A domain's history at a glance |

**The architecture already supports it.** Snapshots are already captured and stored; monitoring is scheduled re-crawls plus a diff engine. That is a feature, not a rewrite — because [ADR-02](03-ARCHITECTURE.md) put the snapshot at the centre from day one.

---

## 9. Release process

### 9.1 Every release

```
1. Freeze          no new features; fixes only
2. Verify          run the version's gate checklist end to end
3. Real scan       50 real businesses; read the output like a user would
4. Version         bump, update CHANGELOG.md
5. Tag             git tag -a v1.0.0
6. Build           docker build, tag with version and sha
7. Document        update README and docs for anything that changed
8. Announce        release notes: what changed, what to watch for
```

### 9.2 CHANGELOG

Keep a Changelog format. Every user-visible change gets a line, in the user's language:

```markdown
## [1.1.0] — 2026-08-15

### Added
- 40 new technology fingerprints (Craft CMS, Statamic, Astro, Remix, …)
- Security check DNS-08: BIMI record detection

### Fixed
- WordPress version was mis-detected on sites using a caching plugin that
  strips the generator meta tag
- CSV export mangled business names containing an em dash
```

### 9.3 Rollback

- Docker images are tagged by version and never overwritten.
- Migrations are expand/contract, so release N-1 runs against release N's schema.
- Rule packs are versioned with the release; a bad rule pack rolls back with the image.
- **Rollback plan is verified before tagging**, not improvised during an incident.

---

## 10. Post-release monitoring

For the first week of any release, watch:

| Signal | Action if bad |
|---|---|
| Scan completion rate | Below 90% → investigate crawler failures immediately |
| Crawl failures by reason | A spike in one reason means a regression, not bad luck |
| Contact discovery rate | A drop means an extraction regression |
| Opportunities per site | A drop means a rule regression; a spike may mean false positives |
| Scan duration | Regression in the crawler or an analyzer |
| Complaints about our crawler | **Stop and investigate immediately** — this is the highest-severity signal in the list |

---

## 11. Deprecation

| Change | Notice |
|---|---|
| Removing an API field | One minor version, documented in the changelog |
| Removing an endpoint | Major version only |
| Changing a rule ID | **Never** — IDs appear in exported CSVs and PDFs users have already sent to clients |
| Changing scoring weights | Minor version, announced — a user's saved ranking will shift |
| Changing the snapshot shape | Internal; requires fixture migration in the same release |

**Rule IDs are permanent.** A consultant who emailed a client a report citing `TLS-04` must find `TLS-04` still means the same thing a year later. Retire a rule by marking it inactive; never reuse its ID.

---

## 12. What ships in every release, without exception

Regardless of version or schedule pressure:

- [ ] All architecture tests pass
- [ ] Passive-only boundary intact
- [ ] `robots.txt` honored
- [ ] No synthesized contacts
- [ ] Every finding carries evidence
- [ ] `docker compose up` works from a clean clone

These are not release criteria that scale with the size of the release. They are the product's identity. A version that ships without them is not a version of LeadKhojo.
