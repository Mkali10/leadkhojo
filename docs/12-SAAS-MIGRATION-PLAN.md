# LeadKhojo — Future SaaS Migration Plan

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-07-30 |
| **Status** | Forward-looking. **No v1 work is derived from this document.** |
| **Target** | v3.0 |

---

## 1. Purpose

v1 is a single-user application with no authentication, no tenancy, and no billing. That is [a deliberate decision](03-ARCHITECTURE.md#14-architecture-decision-records) — nobody closed a deal by logging in, and auth would consume two of fifteen days.

This document exists so that decision is **reversible cheaply**. It records:

1. What v1 must *not* do, so the migration stays a migration rather than a rewrite.
2. The concrete sequence when the time comes.
3. What the migration will genuinely cost.

**Nothing here is built in v1.** Building for a future tenancy model is exactly the over-engineering that [Development Rules §2.1](09-DEVELOPMENT-RULES.md) forbids. The point is to keep the door unlocked, not to walk through it early.

---

## 2. The five v1 decisions that make this cheap

These are already in the v1 design. They are not extra work — they are the *simplest* option that also happens to be the migratable one.

| # | v1 decision | Why it matters later |
|---|---|---|
| 1 | **All queries go through repositories** | Tenant scoping is added in one base class, not in 200 call sites |
| 2 | **`JobQueue` is a protocol** | Swapping Postgres → Celery/Redis touches one file |
| 3 | **`SnapshotStore` is a protocol** | Moving snapshots to object storage touches one file |
| 4 | **Config comes only from `core/config.py`** | Per-tenant configuration slots in at one point |
| 5 | **Every table has a UUID primary key** | No integer-key collisions when merging or sharding |

**The one that carries the migration is #1.** If even a handful of queries bypass the repository layer, adding tenancy becomes an audit of the entire codebase and a permanent source of cross-tenant leaks. This is why the boundary rule is enforced by `import-linter` in v1, when there is not yet a tenant to leak to. The rule is cheap to keep and expensive to acquire.

---

## 3. What changes

### 3.1 Schema

The core insight: **almost nothing changes.** Everything already hangs off `scans`, so tenancy attaches at exactly one place.

**New tables:**

```sql
CREATE TABLE organizations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL,
    slug                CITEXT NOT NULL UNIQUE,
    plan_id             UUID REFERENCES plans(id),
    stripe_customer_id  TEXT UNIQUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               CITEXT NOT NULL UNIQUE,
    password_hash       TEXT,
    full_name           TEXT NOT NULL,
    email_verified_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id    UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role      member_role NOT NULL DEFAULT 'member',
    CONSTRAINT uq_memberships UNIQUE (org_id, user_id)
);

CREATE TABLE plans           (…);   -- limits, pricing
CREATE TABLE subscriptions   (…);   -- Stripe lifecycle
CREATE TABLE usage_records   (…);   -- scans and sites consumed per period
CREATE TABLE audit_logs      (…);   -- who did what
```

**Changes to existing tables — one column:**

```sql
ALTER TABLE scans ADD COLUMN org_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE scans ADD COLUMN created_by UUID REFERENCES users(id);
CREATE INDEX ix_scans__org_created ON scans (org_id, created_at DESC);
```

**Everything else is untouched.** `businesses`, `site_snapshots`, `business_contacts`, `business_technologies`, `security_findings`, `opportunities`, and `business_scores` all reach their tenant through `scan_id`.

**Backfill:** create one organization and one user, assign every existing scan to it, then make `org_id` `NOT NULL`. A migration that runs in seconds on any realistic v1 dataset.

### 3.2 Tenant isolation — two layers

Cross-tenant leakage is the failure mode that ends a SaaS company. One layer is not enough, because layer one is code that humans write.

**Layer 1 — repository scoping.** `TenantRepository` injects `org_id` into every query. There is no code path to a tenant table that bypasses it, and an architecture test fails the build if a tenant model is queried through a bare session.

```python
class TenantRepository(BaseRepository[T]):
    def __init__(self, session: AsyncSession, org_id: UUID) -> None:
        super().__init__(session)
        self._org_id = org_id

    def _scoped(self, stmt: Select[Any]) -> Select[Any]:
        return stmt.where(self.model.org_id == self._org_id)
```

For the child tables that reach tenancy through `scan_id`, the scope is a join to `scans` — applied in the same base class, once.

**Layer 2 — Postgres row-level security**, keyed on a session variable set at connection checkout:

```sql
ALTER TABLE scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE scans FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON scans
    USING (org_id = current_setting('app.current_org_id', TRUE)::uuid);
```

```sql
SET LOCAL app.current_org_id = '…';
```

**`SET LOCAL`, not `SET`.** With a connection pool, a plain `SET` persists onto the next request that borrows the connection — a cross-tenant leak wearing the costume of a performance optimization.

### 3.3 Authentication

| Piece | Choice |
|---|---|
| Sessions | Short-lived access JWT (15 min) + rotating refresh token (30 d), both httpOnly/Secure/SameSite=Lax cookies |
| Passwords | Argon2id at OWASP-recommended parameters |
| OAuth | Google and Microsoft |
| Refresh rotation | Reuse of a consumed token revokes the whole session family and raises a security event |
| API keys | `lk_live_…`, SHA-256 hashed at rest, prefix stored for display, scoped and revocable |

**The API routes do not change shape.** A single FastAPI dependency resolves the principal and the active org; every router gains it via `Depends`. This is why [API Design §2](06-API-DESIGN.md) is written the way it is.

### 3.4 Quotas and billing

Multi-tenancy without limits is an unbounded bill. Two metered dimensions:

| Metric | Why |
|---|---|
| Scans per month | The user-facing unit |
| **Sites analyzed per month** | The actual cost driver — crawling and provider calls |

Enforcement happens at scan creation, before any job is enqueued. A quota checked after work has started is a quota that has already been exceeded.

Stripe for checkout, subscription lifecycle, and the customer portal. Webhooks verified by signature and deduplicated on the Stripe event ID before any processing — Stripe delivers at least once.

### 3.5 Infrastructure

| Concern | v1 | v3 |
|---|---|---|
| Workers | In-process asyncio | Separate containers, autoscaled |
| Job queue | Postgres + `SKIP LOCKED` | Celery + Redis via the same `JobQueue` protocol |
| Snapshots | Postgres JSONB | S3-compatible via the same `SnapshotStore` protocol |
| Database | Single instance | Primary + read replica |
| Crawler egress | The app's IP | **Dedicated egress IP pool** |
| Deployment | Docker Compose | Managed containers + IaC |

**Egress IPs matter more than they look.** With one shared address, one aggressive tenant's scanning gets *everyone* blocked. A pool with per-tenant rate accounting is a v3 requirement, not an optimization.

---

## 4. Sequence

Six phases, roughly six weeks with a small team. Each is independently shippable and independently valuable.

| Phase | Delivers | Duration |
|---|---|---|
| **1 — Foundations** | Tables, `org_id` on `scans`, backfill, `TenantRepository`, RLS, isolation tests | 1 week |
| **2 — Authentication** | Signup, login, refresh rotation, password reset, OAuth, route dependency | 1 week |
| **3 — Teams** | Invitations, roles, permission matrix, org switching, member management | 4 days |
| **4 — Quotas** | Plans, usage metering, enforcement at scan creation, usage UI | 3 days |
| **5 — Billing** | Stripe checkout, portal, webhooks, dunning, plan changes | 1 week |
| **6 — Infra & hardening** | Worker split, Redis, object storage, egress pool, pen test | 1.5 weeks |

**Phase 1 is the one that must not be rushed.** Everything after it assumes isolation holds. If Phase 1 is shaky, Phases 2–6 build on sand and the defect surfaces as a customer seeing another customer's data.

### 4.1 Phase 1 gate

Do not start Phase 2 until all of these pass:

- [ ] An automated test asserts isolation on **every** tenant-scoped endpoint
- [ ] RLS policies exist on every tenant table and are `FORCE`d
- [ ] `SET LOCAL` (not `SET`) verified under pooled connections
- [ ] An architecture test fails the build on any bare-session query of a tenant model
- [ ] The backfill has been rehearsed on a copy of real data

---

## 5. What this will actually cost

Honest estimates, so the decision is made with real numbers.

| Area | Effort | Notes |
|---|---|---|
| Schema + tenancy | 1 week | Cheap **only because** of v1 decision #1 |
| Auth | 1 week | Well-trodden; don't invent anything |
| Teams & permissions | 4 days | The permission matrix is fiddlier than it looks |
| Quotas | 3 days | — |
| Billing | 1 week | Stripe is straightforward; **dunning and edge cases are not** |
| Infra | 1.5 weeks | Worker split, Redis, object storage, egress |
| Testing & hardening | 1 week | Isolation tests, pen test, remediation |
| **Total** | **~6 weeks** | With one or two engineers |

**Ongoing costs that arrive with SaaS and never leave:** support, abuse handling, uptime obligations, security patching, and compliance questionnaires. These frequently exceed the build cost and are the real reason to defer until there is demand.

---

## 6. Trigger conditions

Do not start this until at least one is true:

| Trigger | Why it is the right signal |
|---|---|
| A second person needs their own account and data | The actual definition of multi-tenancy |
| Users ask to pay | Willingness to pay validates the product; building billing before it is speculative |
| Manual per-user deployment is consuming real time | The workaround has become more expensive than the fix |
| A customer requires a hosted, audited environment | An external requirement, not an internal wish |

**Do not start because it feels like the natural next step.** It is not — [monitoring (v4)](07-ROADMAP.md) creates more durable value than tenancy does, and tenancy is a tax on every feature built after it.

---

## 7. What will hurt

Named in advance, because each is easier to plan for than to discover.

| # | Problem | Mitigation |
|---|---|---|
| 1 | **A missed query in tenant scoping** — the leak that ends the company | Two independent layers + an isolation test per endpoint. Non-negotiable. |
| 2 | **Shared crawler egress IPs** — one tenant's volume gets everyone blocked | Egress pool with per-tenant rate accounting from day one of Phase 6 |
| 3 | **Snapshot storage cost** at multi-tenant volume | `SnapshotStore` → object storage; lifecycle rules to age snapshots out |
| 4 | **Noisy-neighbour job queues** — one 500-site scan starves everyone | Per-tenant fair-share scheduling, not plain FIFO |
| 5 | **Support load** arriving with the first paying customer | Budget for it before launch, not after |
| 6 | **Abuse** — someone using the platform to scan targets aggressively | Per-tenant rate limits, anomaly alerts, a documented suspension path |

**#2 and #4 are specific to this product** and are routinely missed in generic SaaS migrations. A crawler is a shared-reputation asset: one tenant's behavior directly degrades every other tenant's results. Plan for it as a first-class concern, not an operational afterthought.

---

## 8. What must stay true through the migration

The single-user product must not get worse to serve the multi-tenant one.

- **Self-hosting stays supported.** Users who run their own instance are a real segment, and the Docker Compose path must keep working.
- **The passive-only boundary is unchanged.** Multi-tenancy is a business model, not a licence to scan differently.
- **The data rules are unchanged.** No personal data, no synthesis, no resale — at any scale.
- **`docker compose up` still works.** If it stops working, the migration went wrong.
