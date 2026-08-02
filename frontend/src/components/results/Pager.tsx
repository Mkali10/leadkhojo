import type { Pagination } from "@/api/types";
import { Button } from "@/components/ui/Button";

export function Pager({
  pagination,
  onOffset,
}: {
  pagination: Pagination;
  onOffset: (offset: number) => void;
}) {
  const { total, limit, offset } = pagination;
  if (total <= limit) return null;

  const from = offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <nav className="mt-4 flex items-center justify-between gap-3" aria-label="Pagination">
      <p className="tnum text-sm text-ink-500">
        {from}–{to} of {total}
      </p>
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={offset === 0}
          onClick={() => onOffset(Math.max(0, offset - limit))}
        >
          Previous
        </Button>
        <Button size="sm" disabled={to >= total} onClick={() => onOffset(offset + limit)}>
          Next
        </Button>
      </div>
    </nav>
  );
}
