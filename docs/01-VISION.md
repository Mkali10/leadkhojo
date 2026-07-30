# LeadKhojo — Vision

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-29 |
| **Status** | Awaiting approval |

---

## 1. The problem

A security consultant wants to sell website hardening to small businesses in her city. Today, her process is:

1. Google "dental clinics in Austin."
2. Open 40 browser tabs.
3. For each: find the website, click through to the contact page, copy the email into a spreadsheet.
4. For each: check if the SSL certificate is valid, view source to guess the CMS, run a header checker, look up the DNS records.
5. Decide which ten are worth a pitch.
6. Write ten different emails, each referencing a different problem.

That is **six to eight hours** for one afternoon of outreach. Most of it is mechanical. All of it is information the websites publish freely — nobody has bothered to read it all and organize it.

She isn't short of prospects. She is short of **reasons to call them**.

---

## 2. The insight

Every business website publicly announces its own problems:

| What the site says | What it means | What you can sell |
|---|---|---|
| Certificate expires in 9 days | Nobody is watching | Certificate management |
| `<meta name="generator" content="WordPress 5.4">` | Years of unpatched releases | Upgrade and maintenance |
| No DMARC record in DNS | Anyone can spoof their domain | Email security |
| No `Content-Security-Policy` header | No XSS defense in depth | Security hardening |
| No CDN, 4.2 s to first byte | Losing customers to load time | Performance / CDN |
| Contact form over plain HTTP | Customer data in the clear | TLS remediation |

None of this is secret. All of it is served to anyone who visits. But nobody reads 47 websites carefully, because it takes six hours.

**A machine can do it in four minutes.**

That is the entire product.

---

## 3. Vision statement

> **LeadKhojo turns public websites into qualified sales opportunities.**

Enter a keyword and a location. Get back a ranked list of businesses, each annotated with what is wrong with their web presence, what you can sell them to fix it, and how to reach them — with evidence for every claim.

---

## 4. Mission

Replace manual prospect research with one intelligent platform. What takes a consultant a full working day should take four minutes and produce better output — because a machine checks all 40 sites with equal care, and a tired human does not.

---

## 5. Who this is for

| User | What they sell | What LeadKhojo gives them |
|---|---|---|
| **Cybersecurity companies** | Audits, hardening, monitoring, compliance | Sites with missing headers, weak TLS, no DMARC, exposed version banners |
| **MSPs** | Managed IT, hosting, patching, backup | Outdated CMS, expiring certificates, unmanaged infrastructure |
| **IT consultants** | Migrations, integrations, modernization | Legacy stacks, self-hosted setups, obsolete frameworks |
| **Agencies** | Web design, development, rebuilds | Slow, dated, unresponsive, poorly built sites |
| **SaaS companies** | Their product | Companies using a competitor's tech, or missing a category entirely |
| **Sales teams** | Anything with a technical angle | Verified reachable companies with a concrete conversation opener |
| **Freelancers** | Their own services | The same intelligence a large firm's research team would produce |

**The common thread:** everyone here sells a service that fixes a problem visible from the outside of a website. If your product can't be pitched from public evidence, LeadKhojo is not your tool.

---

## 6. Product philosophy

Every feature must answer one question:

> **"Will this help the user close more business?"**

If the answer is no, we do not build it. Not later, not behind a flag — not at all.

This is a real filter, and it has already removed things that look obviously necessary:

| Rejected for v1 | Why it fails the test |
|---|---|
| User accounts and login | Nobody closed a deal because they logged in |
| Billing and subscriptions | Revenue matters; it isn't the *user's* outcome |
| A CRM | They already have one. Give them a CSV. |
| Dashboards and analytics charts | Pretty. Closes nothing. |
| A settings page with 40 toggles | Configuration is not a feature |
| "AI-powered insights" as a banner | Adds a buzzword, not a meeting |

And it has protected things that look optional:

| Kept | Why it passes |
|---|---|
| Evidence on every finding | You can't pitch "you have a problem" without proof. Evidence *is* the pitch. |
| PDF report | The consultant attaches it to the first email. It's the sales asset. |
| Opportunity Engine | Findings are data. Opportunities are revenue. Conversion between them is the product. |
| Four separate scores | "Best prospect" means different things to a security firm and a design agency |

---

## 7. Principles

### 7.1 Public information only

We process what a business publishes about itself, on its own website, to anyone who visits. Nothing hidden, nothing inferred, nothing purchased, nothing personal.

**We collect:** role-based business email addresses (`info@`, `sales@`), business phone numbers, business addresses, official social profiles, contact form locations, technology fingerprints, security configuration.

**We never collect:** personal email addresses, employee names, individual mobile numbers, guessed or pattern-derived addresses, anything behind a login, anything from a source that forbids it.

### 7.2 Passive analysis only

We do what a browser does: fetch published pages, resolve public DNS, complete a TLS handshake, read the response.

We do **not** port scan, fuzz paths, probe for vulnerabilities, attempt authentication, or exploit anything. This is not caution — it is the line between a legitimate business intelligence tool and unauthorized computer access.

That line is architectural, not procedural: no code path exists to cross it. See [Security Rules](11-SECURITY-RULES.md).

### 7.3 Nothing is resold

Every scan is run for the user who requested it, from the live web, at the moment they asked. We do not accumulate a warehouse and monetize access to it. When the user deletes a scan, the data is gone.

### 7.4 Every claim carries evidence

"This site has no DMARC record" is an accusation. "This site has no DMARC record — we queried `_dmarc.acme.com` at 14:03 UTC and got NXDOMAIN" is something you can put in an email and defend on a call.

Every finding stores what we checked, what we saw, and when. A finding without evidence is a bug.

### 7.5 Speed is a feature

If a scan takes forty minutes, the user runs one and closes the tab. If it takes four, they run six today. Perceived speed — streaming results as they complete, rather than waiting for the whole batch — matters as much as raw throughput.

### 7.6 One developer, three weeks

The MVP must be buildable by a single developer in fifteen working days. This is a design constraint with teeth: it removes microservices, message brokers, authentication, multi-tenancy, and every abstraction that exists for a team we don't have. The [Architecture](03-ARCHITECTURE.md) is shaped by it.

---

## 8. What success looks like

### v1.0 — the only question that matters

> **Does a real user, running one real scan, find at least one company they actually contact?**

If yes, the product works and everything else is refinement. If no, no amount of features will save it.

### Supporting signals

| Signal | Target |
|---|---|
| Scan of 50 businesses completes in | < 5 minutes |
| Businesses with a usable business contact found | ≥ 60% |
| Opportunities generated per scanned site | ≥ 2 average |
| Findings a user disputes as wrong | < 5% |
| Time from opening the app to first exported CSV | < 6 minutes |

### The honest failure mode

The likely way this fails is not technical. It is **generic output**: every site reports "missing security headers," every opportunity says "offer security hardening," and the user reads three rows, sees the same three lines, and stops.

The defense is specificity. `WordPress 5.4.2, released March 2020, 31 security releases behind` beats `outdated CMS` every time. If the Opportunity Engine cannot say something specific, it should say nothing.

---

## 9. What we will never build

Permanent exclusions. Not "later" — never.

| Never | Because |
|---|---|
| A global people/contact database | It is a different, more legally fraught business. We chose not to be in it. |
| Personal contact enrichment | Same. Role addresses only, always. |
| Active vulnerability scanning without authorization | Unauthorized computer access. Not a product decision — a legal one. |
| Scraping any source whose terms forbid it | LinkedIn, Facebook, and similar. Technical feasibility is irrelevant. |
| Selling or brokering collected data | The user's scan belongs to the user. |
| Automated bulk emailing from the platform | Deliverability, spam liability, and abuse surface we don't want to own. We *draft* outreach; the user sends it. |
| "Dark web" or breach-data lookups | Adjacent-sounding, entirely different risk profile. |

---

## 10. Long-term direction

Once the core works, the product deepens rather than widens.

| Horizon | Direction |
|---|---|
| **v1** | Prove it: one scan produces one real conversation |
| **v2** | Outreach Assistant, saved projects, scan history, re-scan and diff |
| **v3** | Multi-user SaaS: accounts, teams, billing, quotas |
| **v4** | Monitoring: watch a portfolio, alert when a certificate is expiring or a stack changes |
| **v5** | Integrations: push to the CRM the user already has, rather than becoming one |

The strongest long-term position is **monitoring**, not discovery. Discovery is a one-time act; monitoring is a subscription. A consultant who watches 200 client and prospect sites and gets told the moment one breaks has a reason to keep paying every month. But that is v4, and it only exists if v1 earns it.
