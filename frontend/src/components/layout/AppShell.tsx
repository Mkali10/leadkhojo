import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useReadiness } from "@/api/queries";
import { classNames } from "@/lib/format";
import { Logo } from "./Logo";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/scans/new", label: "New scan", end: false },
  { to: "/compare", label: "Compare", end: false },
  { to: "/plugins", label: "Checks", end: false },
];

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          onClick={onNavigate}
          className={({ isActive }) =>
            classNames(
              "rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              isActive
                ? "bg-brand-50 text-brand-700"
                : "text-ink-600 hover:bg-ink-100 hover:text-ink-900",
            )
          }
        >
          {item.label}
        </NavLink>
      ))}
    </>
  );
}

/** Surfaces a degraded backend before the user starts a scan that cannot run. */
function BackendStatus() {
  const { data, isError } = useReadiness();

  if (isError) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-critical">
        <span className="size-1.5 rounded-full bg-critical" />
        API unreachable
      </span>
    );
  }
  if (!data) return null;

  const ok = data.status === "ready";
  return (
    <span
      className={classNames(
        "inline-flex items-center gap-1.5 text-xs",
        ok ? "text-ink-500" : "text-high",
      )}
      title={
        ok
          ? `${data.plugins} checks loaded · workers ${data.workers_running ? "running" : "stopped"}`
          : `database ${data.database ? "ok" : "down"} · rules ${data.rules_loaded ? "ok" : "missing"} · workers ${data.workers_running ? "running" : "stopped"}`
      }
    >
      <span className={classNames("size-1.5 rounded-full", ok ? "bg-good" : "bg-high")} />
      {ok ? `${data.plugins} checks ready` : "Degraded"}
    </span>
  );
}

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-ink-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[100rem] items-center gap-3 px-4 sm:px-6">
          <NavLink to="/" className="flex items-center gap-2" aria-label="LeadKhojo home">
            <Logo className="size-7 text-brand-600" />
            <span className="text-[15px] font-semibold tracking-tight text-ink-900">
              LeadKhojo
            </span>
          </NavLink>

          <nav className="ml-4 hidden items-center gap-1 md:flex">
            <NavItems />
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <BackendStatus />
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              aria-label="Toggle navigation"
              className="rounded-lg p-2 text-ink-600 hover:bg-ink-100 md:hidden"
            >
              <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2">
                {menuOpen ? (
                  <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
                ) : (
                  <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
                )}
              </svg>
            </button>
          </div>
        </div>

        {menuOpen && (
          <nav className="flex flex-col gap-1 border-t border-ink-200 px-4 py-2 md:hidden">
            <NavItems onNavigate={() => setMenuOpen(false)} />
          </nav>
        )}
      </header>

      <main className="mx-auto w-full max-w-[100rem] flex-1 px-4 py-6 sm:px-6 sm:py-8">
        <Outlet />
      </main>

      <footer className="border-t border-ink-200 px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-[100rem] flex-col gap-1 text-xs text-ink-500 sm:flex-row sm:items-center sm:justify-between">
          <p>
            Passive analysis of publicly published pages. Contacts are read from each
            company&rsquo;s own website and never guessed.
          </p>
          {/* Not a disclaimer for its own sake: this build genuinely has no
              auth, and someone will eventually be tempted to expose it. */}
          <p className="text-ink-400">Local instance · no authentication</p>
        </div>
      </footer>
    </div>
  );
}
