import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateScan, useCreateScanFromCsv, useValidateCsv } from "@/api/queries";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { TextArea, TextInput } from "@/components/ui/Field";
import { ErrorState } from "@/components/ui/Feedback";
import { classNames } from "@/lib/format";

type Mode = "urls" | "csv";

const MAX_URLS = 500;

function parseUrls(raw: string): string[] {
  return raw
    .split(/[\s,;]+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

export function NewScanPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("urls");

  const [urlText, setUrlText] = useState("");
  const [keyword, setKeyword] = useState("");
  const [location, setLocation] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const createScan = useCreateScan();
  const createFromCsv = useCreateScanFromCsv();
  const validateCsv = useValidateCsv();

  const urls = parseUrls(urlText);
  const tooMany = urls.length > MAX_URLS;
  const canSubmitUrls = urls.length > 0 && !tooMany;

  const submitUrls = async () => {
    const scan = await createScan.mutateAsync({
      urls,
      keyword: keyword.trim() || null,
      location: location.trim() || null,
      provider: "manual",
      limit: Math.min(Math.max(urls.length, 1), MAX_URLS),
    });
    navigate(`/scans/${scan.id}`);
  };

  const chooseFile = (next: File | null) => {
    setFile(next);
    validateCsv.reset();
    if (next) validateCsv.mutate(next);
  };

  const submitCsv = async () => {
    if (!file) return;
    const scan = await createFromCsv.mutateAsync(file);
    navigate(`/scans/${scan.id}`);
  };

  const validation = validateCsv.data;

  return (
    <>
      <PageHeader
        title="New scan"
        subtitle="Each website is fetched once, politely, and analysed from what it served."
        back={{ to: "/", label: "Dashboard" }}
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="card p-5">
          <div
            role="tablist"
            aria-label="How to supply targets"
            className="mb-5 inline-flex rounded-lg bg-ink-100 p-0.5"
          >
            {(
              [
                ["urls", "Paste domains"],
                ["csv", "Upload a CSV"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                role="tab"
                type="button"
                id={`tab-${value}`}
                aria-selected={mode === value}
                aria-controls={`panel-${value}`}
                onClick={() => setMode(value)}
                className={classNames(
                  "rounded-[7px] px-3 py-1.5 text-sm font-medium transition-colors",
                  mode === value ? "bg-white text-ink-900 shadow-sm" : "text-ink-600 hover:text-ink-900",
                )}
              >
                {label}
              </button>
            ))}
          </div>

          {mode === "urls" ? (
            <div role="tabpanel" id="panel-urls" aria-labelledby="tab-urls" className="space-y-4">
              <TextArea
                label="Domains"
                rows={8}
                spellCheck={false}
                placeholder={"acme.com\nnorthwind-dental.co.uk\nhttps://example.org"}
                value={urlText}
                onChange={(event) => setUrlText(event.target.value)}
                error={tooMany ? `That is ${urls.length} domains. The limit is ${MAX_URLS}.` : null}
                hint="One per line, or separated by commas. Protocol optional."
              />

              <div className="grid gap-4 sm:grid-cols-2">
                <TextInput
                  label="Label"
                  placeholder="Dental clinics, Austin"
                  value={keyword}
                  onChange={(event) => setKeyword(event.target.value)}
                  hint="Optional. Names the scan and its exported files."
                  maxLength={255}
                />
                <TextInput
                  label="Location"
                  placeholder="Austin, TX"
                  value={location}
                  onChange={(event) => setLocation(event.target.value)}
                  hint="Optional. Recorded with the scan."
                  maxLength={255}
                />
              </div>

              {createScan.error && <ErrorState error={createScan.error} />}

              <div className="flex items-center gap-3">
                <Button
                  variant="primary"
                  disabled={!canSubmitUrls}
                  loading={createScan.isPending}
                  onClick={() => void submitUrls()}
                >
                  Start scan
                </Button>
                <span className="tnum text-sm text-ink-500">
                  {urls.length} {urls.length === 1 ? "domain" : "domains"}
                </span>
              </div>
            </div>
          ) : (
            <div role="tabpanel" id="panel-csv" aria-labelledby="tab-csv" className="space-y-4">
              <div>
                <label
                  htmlFor="csv-file"
                  className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-ink-200 px-6 py-10 text-center hover:border-brand-400 hover:bg-brand-50/30"
                >
                  <svg viewBox="0 0 24 24" className="mb-2 size-8 text-ink-300" fill="none" stroke="currentColor" strokeWidth="1.6">
                    <path d="M12 16V4m0 0L8 8m4-4l4 4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span className="text-sm font-medium text-ink-800">
                    {file ? file.name : "Choose a CSV file"}
                  </span>
                  <span className="mt-1 text-xs text-ink-500">
                    Needs a domain or website column. Up to {MAX_URLS} rows.
                  </span>
                </label>
                <input
                  id="csv-file"
                  ref={fileInput}
                  type="file"
                  accept=".csv,text/csv"
                  className="sr-only"
                  onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
                />
              </div>

              {validateCsv.isPending && <p className="text-sm text-ink-500">Checking the file…</p>}
              {validateCsv.error && <ErrorState error={validateCsv.error} />}

              {/* A dry run before committing. Nobody should upload 400 rows and
                  find out afterwards that column detection went wrong. */}
              {validation && (
                <div className="rounded-lg border border-ink-200 bg-ink-50/50 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={validation.valid_row_count > 0 ? "good" : "high"}>
                      {validation.valid_row_count} usable{" "}
                      {validation.valid_row_count === 1 ? "row" : "rows"}
                    </Badge>
                    {validation.invalid_rows.length > 0 && (
                      <Badge tone="high">{validation.invalid_rows.length} skipped</Badge>
                    )}
                    {validation.detected_columns && (
                      <span className="text-xs text-ink-500">
                        columns:{" "}
                        {Object.entries(validation.detected_columns)
                          .map(([role, column]) => `${role}→${column}`)
                          .join(", ")}
                      </span>
                    )}
                  </div>

                  {validation.preview.length > 0 && (
                    <ul className="mt-3 space-y-0.5 text-xs text-ink-600">
                      {validation.preview.map((row) => (
                        <li key={row.domain} className="truncate">
                          <span className="font-medium">{row.domain}</span>
                          {row.name && row.name !== row.domain && (
                            <span className="text-ink-400"> · {row.name}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}

                  {validation.invalid_rows.length > 0 && (
                    <details className="mt-3">
                      <summary className="cursor-pointer text-xs font-medium text-ink-600">
                        Rows that will be skipped
                      </summary>
                      <ul className="mt-1.5 space-y-0.5 text-xs text-ink-500">
                        {validation.invalid_rows.slice(0, 20).map((row) => (
                          <li key={row.row}>
                            row {row.row} — {row.reason}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              )}

              {createFromCsv.error && <ErrorState error={createFromCsv.error} />}

              <div className="flex items-center gap-3">
                <Button
                  variant="primary"
                  disabled={!file || validation?.valid_row_count === 0}
                  loading={createFromCsv.isPending}
                  onClick={() => void submitCsv()}
                >
                  Start scan
                </Button>
                {file && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setFile(null);
                      validateCsv.reset();
                      if (fileInput.current) fileInput.current.value = "";
                    }}
                  >
                    Clear
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>

        <aside className="space-y-4">
          <div className="card p-4">
            <h2 className="text-sm font-semibold text-ink-800">What happens next</h2>
            <ol className="mt-2 space-y-2 text-sm text-ink-600">
              {[
                "Each site is fetched once — a handful of public pages, one request at a time.",
                "Certificates, DNS, headers, technology and contact details are read from what came back.",
                "Findings become opportunities only where there is specific evidence behind them.",
                "Everything is scored, and you can export it as CSV or PDF.",
              ].map((step, index) => (
                <li key={step} className="flex gap-2.5">
                  <span className="tnum mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-ink-100 text-[11px] font-semibold text-ink-600">
                    {index + 1}
                  </span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
          </div>

          {/* Not decorative. These are the boundaries the crawler actually
              enforces, and a user pointing it at a site should know them. */}
          <div className="card p-4">
            <h2 className="text-sm font-semibold text-ink-800">How it behaves</h2>
            <ul className="mt-2 space-y-1.5 text-xs text-ink-600">
              <li>robots.txt is always honoured. There is no override.</li>
              <li>Requests identify themselves as LeadKhojoBot with a contact URL.</li>
              <li>One request per site at a time — never a burst.</li>
              <li>Ordinary page fetches only. No port scans, no probing, no login attempts.</li>
              <li>Contacts come from the company&rsquo;s own pages, and are never guessed.</li>
            </ul>
          </div>
        </aside>
      </div>
    </>
  );
}
