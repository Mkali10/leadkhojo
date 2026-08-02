/** A magnifier over a bar chart: find, then measure. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} fill="none" aria-hidden="true">
      <rect x="1.5" y="1.5" width="29" height="29" rx="8" className="fill-current opacity-10" />
      <path
        d="M9 21.5v-4.5M14 21.5v-9M19 21.5v-6"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <circle cx="21.5" cy="12" r="4.5" stroke="currentColor" strokeWidth="2.2" />
      <path d="M25 15.5l3.5 3.5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}
