import type { ContactDetail } from "@/api/types";
import { Badge } from "@/components/ui/Badge";

/**
 * Contacts read from the company's own website.
 *
 * The source URL is shown for every one. Nothing here is inferred, permuted
 * or constructed from a pattern — if a business publishes no address, the
 * honest output is nothing, and that is what this renders.
 */
export function ContactList({ contacts }: { contacts: ContactDetail[] }) {
  if (contacts.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-ink-200 px-4 py-6 text-center">
        <p className="text-sm font-medium text-ink-700">No contact details published</p>
        <p className="mx-auto mt-1 max-w-sm text-xs text-ink-500">
          Nothing usable was found on this website. No address is ever guessed, inferred from a
          name, or built from a pattern, so an empty result here is a correct one.
        </p>
      </div>
    );
  }

  return (
    <ul className="divide-y divide-ink-100">
      {contacts.map((contact, index) => {
        const isEmail = contact.kind === "email";
        const href = isEmail
          ? `mailto:${contact.value}`
          : contact.kind === "phone"
            ? `tel:${contact.value.replace(/\s+/g, "")}`
            : contact.value;

        return (
          <li key={`${contact.kind}-${contact.value}-${index}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
            <Badge tone={contact.category === "role" ? "brand" : "neutral"}>
              {contact.category || contact.kind}
            </Badge>
            <a
              href={href}
              target={isEmail || contact.kind === "phone" ? undefined : "_blank"}
              rel="noreferrer noopener"
              className="min-w-0 flex-1 truncate text-sm text-brand-700 hover:underline"
            >
              {contact.value}
            </a>
            {contact.source_url && (
              <a
                href={contact.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="truncate text-xs text-ink-400 hover:text-ink-600 hover:underline"
                title={`Found on ${contact.source_url}`}
              >
                source
              </a>
            )}
          </li>
        );
      })}
    </ul>
  );
}
