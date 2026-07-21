import { useMemo, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnFiltersState,
  type SortingState,
} from "@tanstack/react-table";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  FileSearch,
  FilterX,
  Search,
} from "lucide-react";
import { Badge, DecisionBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { absoluteTime, cn, formatMoney, relativeTime } from "@/lib/utils";
import type { Decision, RunSummary } from "@/lib/types";

const col = createColumnHelper<RunSummary>();

const DECISION_FILTERS: { value: Decision | "failed"; label: string; cls: string }[] = [
  { value: "auto_approve", label: "Approved", cls: "data-[on=true]:border-success/50 data-[on=true]:text-success data-[on=true]:bg-success/10" },
  { value: "needs_review", label: "Review", cls: "data-[on=true]:border-warning/50 data-[on=true]:text-warning data-[on=true]:bg-warning/10" },
  { value: "reject", label: "Rejected", cls: "data-[on=true]:border-destructive/50 data-[on=true]:text-destructive data-[on=true]:bg-destructive/10" },
  { value: "failed", label: "Failed", cls: "data-[on=true]:border-border-strong data-[on=true]:text-foreground data-[on=true]:bg-foreground/8" },
];

const DATE_PRESETS = [
  { value: "all", label: "All time" },
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
] as const;

export function RunsTable({
  runs,
  onOpenRun,
  onGoProcess,
}: {
  runs: RunSummary[] | null;
  onOpenRun: (run: RunSummary) => void;
  onGoProcess: () => void;
}) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "id", desc: true }]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [search, setSearch] = useState("");
  const [decisionFilter, setDecisionFilter] = useState<Set<string>>(new Set());
  const [datePreset, setDatePreset] = useState<(typeof DATE_PRESETS)[number]["value"]>("all");

  const filtered = useMemo(() => {
    if (!runs) return [];
    const q = search.trim().toLowerCase();
    const now = Date.now();
    return runs.filter((r) => {
      if (q) {
        const hay = `${r.invoice_number ?? ""} ${r.vendor_name ?? ""} ${r.filename} ${r.po_ref ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (decisionFilter.size) {
        const key = r.status === "failed" ? "failed" : (r.decision ?? "");
        if (!decisionFilter.has(key)) return false;
      }
      if (datePreset !== "all") {
        const t = new Date(r.created_at.endsWith("Z") ? r.created_at : r.created_at + "Z").getTime();
        const cutoff = datePreset === "today" ? new Date().setHours(0, 0, 0, 0) : now - 7 * 864e5;
        if (t < cutoff) return false;
      }
      return true;
    });
  }, [runs, search, decisionFilter, datePreset]);

  const columns = useMemo(
    () => [
      col.accessor("id", {
        header: "#",
        cell: (c) => <span className="font-mono text-xs text-faint">{c.getValue()}</span>,
        size: 48,
      }),
      col.accessor("invoice_number", {
        header: "Invoice",
        cell: (c) => (
          <div className="min-w-0">
            <div className="truncate font-mono text-xs font-medium">
              {c.getValue() ?? "—"}
            </div>
            <div className="truncate text-[11px] text-faint">{c.row.original.filename}</div>
          </div>
        ),
      }),
      col.accessor("vendor_name", {
        header: "Vendor",
        cell: (c) => <span className="truncate text-xs">{c.getValue() ?? "—"}</span>,
      }),
      col.accessor("total", {
        header: "Total",
        cell: (c) => (
          <span className="font-mono text-xs tabular-nums">{formatMoney(c.getValue())}</span>
        ),
        sortUndefined: "last",
      }),
      col.accessor("po_ref", {
        header: "PO",
        cell: (c) => <span className="font-mono text-xs">{c.getValue() ?? "—"}</span>,
        enableSorting: false,
      }),
      col.accessor((r) => (r.status === "failed" ? "failed" : (r.decision ?? "")), {
        id: "decision",
        header: "Decision",
        cell: (c) =>
          c.row.original.status === "failed" ? (
            <Badge tone="neutral" title={c.row.original.error ?? undefined}>
              <span className="size-1.5 rounded-full bg-faint" /> Failed
            </Badge>
          ) : (
            <DecisionBadge decision={c.row.original.decision} />
          ),
      }),
      col.accessor("scenario", {
        header: "Scenario",
        cell: (c) =>
          c.getValue() ? (
            <span className="rounded-md border border-border bg-surface px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {c.getValue()}
            </span>
          ) : (
            <span className="text-[10px] text-faint">upload</span>
          ),
        enableSorting: false,
      }),
      col.accessor("created_at", {
        header: "Run at",
        cell: (c) => (
          <span className="text-xs text-muted-foreground" title={absoluteTime(c.getValue())}>
            {relativeTime(c.getValue())}
          </span>
        ),
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting, columnFilters },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 10 } },
  });

  const anyFilter = search || decisionFilter.size > 0 || datePreset !== "all";

  /* ---- loading ---- */
  if (runs === null) {
    return (
      <div className="space-y-2 rounded-xl border border-border bg-card p-4">
        <div className="flex gap-3 pb-2">
          <Skeleton className="h-9 w-64" />
          <Skeleton className="h-9 w-40" />
        </div>
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-11 w-full" />
        ))}
      </div>
    );
  }

  /* ---- true empty state (no runs at all) ---- */
  if (runs.length === 0) {
    return (
      <div className="dot-grid flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-surface/40 px-6 py-16 text-center">
        <div className="flex size-14 items-center justify-center rounded-2xl border border-border bg-card shadow-sm">
          <FileSearch className="size-6 text-muted-foreground" />
        </div>
        <h3 className="font-display mt-5 text-base font-bold tracking-tight">No runs yet</h3>
        <p className="mt-1.5 max-w-sm text-sm text-muted-foreground">
          Upload an invoice PDF — every stage of the pipeline will stream here
          live as it executes.
        </p>
        <Button className="mt-5" onClick={onGoProcess}>
          Process an invoice
        </Button>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
        <div className="relative">
          <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-faint" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search invoice, vendor, PO…"
            className="w-60 pl-8"
          />
        </div>
        <div className="flex items-center gap-1">
          {DECISION_FILTERS.map((f) => (
            <button
              key={f.value}
              data-on={decisionFilter.has(f.value)}
              onClick={() =>
                setDecisionFilter((prev) => {
                  const next = new Set(prev);
                  next.has(f.value) ? next.delete(f.value) : next.add(f.value);
                  return next;
                })
              }
              className={cn(
                "h-8 cursor-pointer rounded-md border border-border px-2.5 text-xs",
                "text-muted-foreground transition-colors hover:border-border-strong",
                f.cls,
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <select
          value={datePreset}
          onChange={(e) => setDatePreset(e.target.value as typeof datePreset)}
          className="h-8 cursor-pointer rounded-md border border-border bg-surface px-2 text-xs text-muted-foreground focus-visible:outline-none"
        >
          {DATE_PRESETS.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
        {anyFilter && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSearch("");
              setDecisionFilter(new Set());
              setDatePreset("all");
            }}
          >
            <FilterX className="size-3.5" /> Clear
          </Button>
        )}
        <span className="ml-auto text-xs text-faint tabular-nums">
          {filtered.length} of {runs.length} runs
        </span>
      </div>

      {/* table */}
      <table className="w-full text-left">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="border-b border-border">
              {hg.headers.map((h) => (
                <th
                  key={h.id}
                  className="px-3 py-2.5 text-[11px] font-semibold tracking-wider text-faint uppercase select-none first:pl-4 last:pr-4"
                >
                  {h.column.getCanSort() ? (
                    <button
                      className="inline-flex cursor-pointer items-center gap-1 hover:text-foreground"
                      onClick={h.column.getToggleSortingHandler()}
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {h.column.getIsSorted() === "asc" ? (
                        <ArrowUp className="size-3" />
                      ) : h.column.getIsSorted() === "desc" ? (
                        <ArrowDown className="size-3" />
                      ) : (
                        <ArrowUpDown className="size-3 opacity-40" />
                      )}
                    </button>
                  ) : (
                    flexRender(h.column.columnDef.header, h.getContext())
                  )}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => onOpenRun(row.original)}
              className="cursor-pointer border-b border-border/60 transition-colors last:border-0 hover:bg-foreground/4"
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-3 py-2.5 first:pl-4 last:pr-4">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
          {/* filtered-empty state (runs exist, filters exclude all) */}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-4 py-12 text-center">
                <p className="text-sm text-muted-foreground">
                  No runs match the current filters.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  onClick={() => {
                    setSearch("");
                    setDecisionFilter(new Set());
                    setDatePreset("all");
                  }}
                >
                  <FilterX className="size-3.5" /> Clear filters
                </Button>
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {/* pagination */}
      {table.getPageCount() > 1 && (
        <div className="flex items-center justify-between border-t border-border px-4 py-2.5">
          <span className="text-xs text-faint tabular-nums">
            Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
          </span>
          <div className="flex gap-1.5">
            <Button
              variant="outline"
              size="sm"
              disabled={!table.getCanPreviousPage()}
              onClick={() => table.previousPage()}
            >
              <ChevronLeft className="size-3.5" /> Prev
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!table.getCanNextPage()}
              onClick={() => table.nextPage()}
            >
              Next <ChevronRight className="size-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
