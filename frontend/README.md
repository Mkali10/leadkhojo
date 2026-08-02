# LeadKhojo — web

React + Vite + TypeScript + Tailwind. Consumes the LeadKhojo REST API and
nothing else.

## Running it

The backend must be up first — the UI has no data of its own.

```bash
# terminal 1 — API on :8000
cd backend && .venv/Scripts/python.exe -m uvicorn leadkhojo.api.app:app --host 127.0.0.1 --port 8000

# terminal 2 — UI on :5173
cd frontend && npm install && npm run dev
```

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on `127.0.0.1:5173`, proxying `/api` to `:8000` |
| `npm run build` | Typecheck then production build into `dist/` |
| `npm run preview` | Serve the built bundle |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc` only |
| `npm run smoke` | End-to-end browser test (needs the API and the dev server running) |

## How it talks to the backend

Everything goes through `src/api/`. `types.ts` is the contract transcribed
from `/openapi.json`; `client.ts` is the only place `fetch` is called;
`endpoints.ts` is one function per route; `queries.ts` wraps them in TanStack
Query hooks. No component calls `fetch` directly.

The base URL is the relative path `/api/v1` in every environment. In
development Vite proxies it, so the browser sees a single origin and there is
no CORS preflight; in production the bundle is served from the same origin as
the API. Nothing host-specific is baked into the build.

`POST /scans` returns `202` with an id, so the UI polls
`/scans/{id}/progress` every two seconds and **stops as soon as the status is
terminal**. Polling forever after a scan finishes is the easy bug here.

## Layout

```
src/
  api/          contract, fetch client, endpoints, query hooks
  components/
    ui/         Button, Badge, Score, Evidence, Field, Feedback, Spinner
    layout/     AppShell, PageHeader, ErrorBoundary, Logo
    scan/       ProgressPanel
    results/    ResultsTable, ResultFilters, Pager
    business/   FindingList, OpportunityList, ContactList, TechnologyList
    compare/    ComparisonTable
  pages/        one file per route
  lib/          formatting and score helpers
```

## Things the interface is deliberately careful about

These are not stylistic choices. They are the product's guarantees, and the UI
is the last place they can be broken.

**A missing contact is stated, not left blank.** `primary_email: null` renders
as "none published" with an explanation. The backend never guesses an address
— no `info@domain` fallback, no pattern inference — so an empty result is a
correct answer and the UI says so rather than showing an empty cell that looks
like a bug.

**`not_applicable` is not a pass and not a failure.** Findings are grouped into
Problems, Passing and Not checked. "Not checked" means the check could not be
evaluated — a DNS lookup that never answered, a page that was never fetched.
Rendering it as either of the other two would put a claim on screen that the
data does not support.

**Every problem shows its evidence.** Expandable, verbatim, selectable. The
user is going to repeat these claims to a stranger, so the record behind each
one has to be one click away.

**The deterministic wording is the one on display.** `description` comes from
the rule engine and is shown as the primary text. If `description_ai` is ever
populated it appears beside it, labelled, never replacing it.

**A failed crawl says so before anything else.** The business page leads with
the failure and notes that whatever follows came from DNS, which is collected
independently of the page fetch.

**Score colours are not one scale.** High security is good; high opportunity
means there is a lot wrong with the site, which is good for the user and bad
for the prospect. They are coloured inversely on purpose.

## Responsive

The results table becomes cards below `md`. Wide content scrolls inside its
own container so the page body never scrolls sideways. Verified at 390px in
the smoke test.

## No authentication

There is none, in the API or here. The header shows backend readiness and the
footer says "local instance". Do not expose either service to the internet.
