import { useMemo } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  Calculator,
  Search,
  FileText,
  ShieldCheck,
  Tag,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { RunTrace } from "@/lib/types";
import { formatMoney } from "@/lib/utils";

export type FieldOrigin = "EXTRACTED" | "CALCULATED" | "MATCHED" | "MISSING" | "UNCERTAIN";

interface ResultRow {
  key: string;
  field: string;
  value: string;
  origin: FieldOrigin;
  status: "success" | "warning" | "destructive" | "neutral";
  confidenceText?: string;
  evidence: string;
  rawConfidence?: number;
}

export function StructuredResultsTable({ trace }: { trace: RunTrace }) {
  const { extract, validate, match, decide } = trace;

  const rows = useMemo<ResultRow[]>(() => {
    const list: ResultRow[] = [];
    const fields = (extract.fields as Record<
      string,
      { value: unknown; confidence: number; source: string }
    >) || {};

    const vendorMatch = match.vendor_match as
      | {
          matched: boolean;
          vendor_name?: string;
          vendor_id?: string;
          approved?: boolean;
          similarity?: number;
          detail?: string;
          closest?: string;
        }
      | undefined;

    const poMatch = match.po_match as
      | {
          matched: boolean;
          po_number?: string;
          match_type?: string;
          detail?: string;
        }
      | undefined;

    const amountCheck = match.amount_check as
      | {
          po_amount?: number;
          invoice_total?: number;
          tolerance?: number;
          tolerance_rule?: string;
          difference?: number;
          within_tolerance?: boolean;
          billing_mode?: string;
          cumulative_prior?: number;
          cumulative_with_this_invoice?: number;
          cumulative_within_po?: boolean;
        }
      | undefined;

    const validationChecks = (validate.checks as Array<{
      name: string;
      passed: boolean;
      detail: string;
    }>) || [];

    // 1. Invoice Number
    const invNo = fields.invoice_number?.value as string | undefined;
    const invConf = fields.invoice_number?.confidence ?? 0;
    list.push({
      key: "invoice_number",
      field: "Invoice Number",
      value: invNo ? String(invNo) : "Missing / Not Extracted",
      origin: !invNo ? "MISSING" : invConf < 0.7 ? "UNCERTAIN" : "EXTRACTED",
      status: invNo ? (invConf >= 0.7 ? "success" : "warning") : "destructive",
      confidenceText: invNo ? `${Math.round(invConf * 100)}% confidence` : "Unavailable",
      evidence: fields.invoice_number?.source || "No invoice number pattern matched in text layer",
      rawConfidence: invConf,
    });

    // 2. Vendor Name
    const vName = fields.vendor_name?.value as string | undefined;
    const vConf = fields.vendor_name?.confidence ?? 0;
    list.push({
      key: "vendor_name",
      field: "Vendor Name",
      value: vName ? String(vName) : "Missing / Not Extracted",
      origin: !vName ? "MISSING" : vConf < 0.7 ? "UNCERTAIN" : "EXTRACTED",
      status: vName ? (vConf >= 0.7 ? "success" : "warning") : "destructive",
      confidenceText: vName ? `${Math.round(vConf * 100)}% confidence` : "Unavailable",
      evidence: fields.vendor_name?.source || "No vendor name detected",
      rawConfidence: vConf,
    });

    // 3. Invoice Date
    const invDate = fields.invoice_date?.value as string | undefined;
    const dateConf = fields.invoice_date?.confidence ?? 0;
    list.push({
      key: "invoice_date",
      field: "Invoice Date",
      value: invDate ? String(invDate) : "Missing / Not Extracted",
      origin: !invDate ? "MISSING" : dateConf < 0.7 ? "UNCERTAIN" : "EXTRACTED",
      status: invDate ? (dateConf >= 0.7 ? "success" : "warning") : "destructive",
      confidenceText: invDate ? `${Math.round(dateConf * 100)}% confidence` : "Unavailable",
      evidence: fields.invoice_date?.source || "No invoice date matched",
      rawConfidence: dateConf,
    });

    // 4. Purchase Order Reference
    const poRef = fields.po_ref?.value as string | undefined;
    const poRefConf = fields.po_ref?.confidence ?? 0;
    const hasExplicitPo = Boolean(poRef);
    list.push({
      key: "po_ref",
      field: "Purchase Order Reference",
      value: poRef
        ? String(poRef)
        : poMatch?.matched && poMatch.po_number
          ? `${poMatch.po_number} (Inferred PO Candidate)`
          : "Not Referenced on Document",
      origin: hasExplicitPo
        ? "EXTRACTED"
        : poMatch?.matched
          ? "MATCHED"
          : "MISSING",
      status: hasExplicitPo
        ? "success"
        : poMatch?.matched
          ? "warning"
          : "neutral",
      confidenceText: hasExplicitPo
        ? `${Math.round(poRefConf * 100)}% confidence`
        : poMatch?.matched
          ? "Fuzzy Candidate"
          : "None",
      evidence: hasExplicitPo
        ? fields.po_ref?.source || "Extracted from document"
        : poMatch?.detail || "No explicit PO reference printed on document",
      rawConfidence: hasExplicitPo ? poRefConf : undefined,
    });

    // 5. Subtotal
    const subtotal = fields.subtotal?.value as number | undefined;
    const subConf = fields.subtotal?.confidence ?? 0;
    list.push({
      key: "subtotal",
      field: "Subtotal",
      value: subtotal != null ? formatMoney(subtotal) : "Missing / Not Extracted",
      origin: subtotal != null ? "EXTRACTED" : "MISSING",
      status: subtotal != null ? "success" : "destructive",
      confidenceText: subtotal != null ? `${Math.round(subConf * 100)}% confidence` : "Unavailable",
      evidence: fields.subtotal?.source || "Subtotal label and amount not found",
      rawConfidence: subConf,
    });

    // 6. Tax
    const tax = fields.tax?.value as number | undefined;
    const taxConf = fields.tax?.confidence ?? 0;
    list.push({
      key: "tax",
      field: "Tax",
      value: tax != null ? formatMoney(tax) : "$0.00 (No explicit tax line)",
      origin: tax != null ? "EXTRACTED" : "CALCULATED",
      status: "neutral",
      confidenceText: tax != null ? `${Math.round(taxConf * 100)}% confidence` : "Calculated 0.00",
      evidence: fields.tax?.source || "Zero tax assumed by deterministic policy if omitted",
      rawConfidence: tax != null ? taxConf : 1.0,
    });

    // 7. Total
    const total = fields.total?.value as number | undefined;
    const totConf = fields.total?.confidence ?? 0;
    list.push({
      key: "total",
      field: "Total Amount",
      value: total != null ? formatMoney(total) : "Missing / Not Extracted",
      origin: total != null ? "EXTRACTED" : "MISSING",
      status: total != null ? "success" : "destructive",
      confidenceText: total != null ? `${Math.round(totConf * 100)}% confidence` : "Unavailable",
      evidence: fields.total?.source || "Total due label not identified",
      rawConfidence: totConf,
    });

    // 8. Overall Extraction Confidence
    const extConf = (extract.extraction_confidence as number) ?? 0;
    const method = (extract.method as string) ?? "text";
    list.push({
      key: "extraction_confidence",
      field: "Extraction Quality & Routing",
      value: `${Math.round(extConf * 100)}% Confidence (${method === "vision" ? "Vision-LLM Path" : "Direct Text-Native Parse"})`,
      origin: "CALCULATED",
      status: extConf >= 0.7 ? "success" : "warning",
      confidenceText: extConf >= 0.7 ? "Acceptable (>= 70%)" : "Low Confidence (< 70%)",
      evidence: (extract.routing as string) || "Grounded mean of critical fields",
      rawConfidence: extConf,
    });

    // 9. Validation Status
    const valPassed = Boolean(validate.passed);
    const failedChecks = validationChecks.filter((c) => !c.passed);
    list.push({
      key: "validation_status",
      field: "Document Integrity Validation",
      value: valPassed
        ? `Passed (${validationChecks.length} checks verified)`
        : `Failed (${failedChecks.length} check(s) violated)`,
      origin: "CALCULATED",
      status: valPassed ? "success" : "destructive",
      confidenceText: valPassed ? "100% Deterministic Pass" : "Check Failure",
      evidence: valPassed
        ? "Subtotal + tax arithmetic reconciled, sanity bounds verified, required fields present"
        : failedChecks.map((c) => c.detail).join("; "),
    });

    // 10. Vendor Matching Status
    const isVendorMatched = Boolean(vendorMatch?.matched);
    const isApproved = Boolean(vendorMatch?.approved);
    list.push({
      key: "vendor_match",
      field: "Vendor Master Matching",
      value: isVendorMatched
        ? `${vendorMatch?.vendor_name} (${vendorMatch?.vendor_id}) · ${isApproved ? "Approved" : "Unapproved"}`
        : "Unmatched in Master Vendor Database",
      origin: isVendorMatched ? "MATCHED" : "MISSING",
      status: isVendorMatched && isApproved ? "success" : isVendorMatched ? "warning" : "destructive",
      confidenceText: isVendorMatched
        ? `${Math.round((vendorMatch?.similarity ?? 1) * 100)}% similarity`
        : "Unverified",
      evidence:
        vendorMatch?.detail ||
        (isVendorMatched
          ? `Matched against master alias: ${vendorMatch?.matched_against}`
          : "No matching record in vendors table"),
      rawConfidence: vendorMatch?.similarity,
    });

    // 11. PO Matching & Tolerance Status
    const isPoMatched = Boolean(poMatch?.matched);
    let poStatusVal = "No PO Matched";
    let poEvidence = poMatch?.detail || "PO record not identified";
    let poBadgeStatus: "success" | "warning" | "destructive" | "neutral" = "destructive";

    if (isPoMatched && amountCheck) {
      if (amountCheck.billing_mode === "partial") {
        poStatusVal = `PO ${poMatch?.po_number} · Partial Billing (${amountCheck.cumulative_within_po ? "Within Budget" : "Exceeds PO"})`;
        poBadgeStatus = amountCheck.cumulative_within_po ? "success" : "destructive";
        poEvidence = `Cumulative billed: ${formatMoney(amountCheck.cumulative_with_this_invoice ?? 0)} of PO ${formatMoney(amountCheck.po_amount ?? 0)}`;
      } else {
        poStatusVal = `PO ${poMatch?.po_number} · ${amountCheck.within_tolerance ? "Within Tolerance" : "Out of Tolerance"}`;
        poBadgeStatus = amountCheck.within_tolerance ? "success" : "warning";
        poEvidence = `Difference: ${formatMoney(amountCheck.difference ?? 0)} · ${amountCheck.tolerance_rule}`;
      }
    } else if (isPoMatched) {
      poStatusVal = `PO ${poMatch?.po_number} (${poMatch?.match_type})`;
      poBadgeStatus = "warning";
    }

    list.push({
      key: "po_match",
      field: "Purchase Order Reconciliation",
      value: poStatusVal,
      origin: isPoMatched ? "MATCHED" : "MISSING",
      status: poBadgeStatus,
      confidenceText: isPoMatched ? (poMatch?.match_type ?? "Matched") : "Unmatched",
      evidence: poEvidence,
    });

    // 12. Final Decision
    const decision = decide.decision as string;
    list.push({
      key: "final_decision",
      field: "Final Pipeline Decision",
      value:
        decision === "auto_approve"
          ? "AUTO-APPROVE"
          : decision === "needs_review"
            ? "NEEDS REVIEW"
            : "REJECT",
      origin: "CALCULATED",
      status:
        decision === "auto_approve"
          ? "success"
          : decision === "needs_review"
            ? "warning"
            : "destructive",
      confidenceText: "Deterministic Rules Engine",
      evidence: (decide.primary_reason as string) || "Evaluated by business rules matrix",
    });

    return list;
  }, [extract, validate, match, decide]);

  return (
    <div className="space-y-4">
      <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
        <div>
          <h2 className="font-display text-base font-bold tracking-tight text-foreground">
            Structured Extraction &amp; Verification Results
          </h2>
          <p className="text-xs text-muted-foreground">
            Every entry originates from the uploaded document, verified master data, or a deterministic calculation.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
          <span className="font-semibold text-foreground/80">Classification Key:</span>
          <OriginBadge origin="EXTRACTED" />
          <OriginBadge origin="CALCULATED" />
          <OriginBadge origin="MATCHED" />
          <OriginBadge origin="MISSING" />
          <OriginBadge origin="UNCERTAIN" />
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-border bg-surface text-faint uppercase tracking-wider">
              <tr>
                <th className="py-3 pr-4 pl-4 font-semibold">Field / Entity</th>
                <th className="py-3 pr-4 pl-2 font-semibold">Value</th>
                <th className="py-3 pr-4 pl-2 font-semibold">Classification</th>
                <th className="py-3 pr-4 pl-2 font-semibold">Status / Confidence</th>
                <th className="py-3 pr-4 pl-2 font-semibold">Traceability &amp; Evidence Trail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {rows.map((row) => (
                <tr key={row.key} className="transition-colors hover:bg-surface/50">
                  <td className="py-3 pr-4 pl-4 font-medium text-foreground">
                    <div className="flex items-center gap-1.5">
                      <RowIcon origin={row.origin} status={row.status} />
                      <span>{row.field}</span>
                    </div>
                  </td>
                  <td className="py-3 pr-4 pl-2 font-mono text-xs font-semibold text-foreground">
                    {row.value}
                  </td>
                  <td className="py-3 pr-4 pl-2">
                    <OriginBadge origin={row.origin} />
                  </td>
                  <td className="py-3 pr-4 pl-2 whitespace-nowrap text-muted-foreground">
                    <span
                      className={`inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono text-[11px] ${
                        row.status === "success"
                          ? "bg-success/10 text-success"
                          : row.status === "warning"
                            ? "bg-warning/10 text-warning"
                            : row.status === "destructive"
                              ? "bg-destructive/10 text-destructive"
                              : "bg-surface text-muted-foreground"
                      }`}
                    >
                      {row.confidenceText}
                    </span>
                  </td>
                  <td className="max-w-md py-3 pr-4 pl-2 text-[11px] leading-relaxed text-muted-foreground">
                    <span className="font-mono text-foreground/80">{row.evidence}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function OriginBadge({ origin }: { origin: FieldOrigin }) {
  switch (origin) {
    case "EXTRACTED":
      return (
        <span className="inline-flex items-center gap-1 rounded-md border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-sky-600 dark:text-sky-400">
          <FileText className="size-3" /> EXTRACTED
        </span>
      );
    case "CALCULATED":
      return (
        <span className="inline-flex items-center gap-1 rounded-md border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-purple-600 dark:text-purple-400">
          <Calculator className="size-3" /> CALCULATED
        </span>
      );
    case "MATCHED":
      return (
        <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-emerald-600 dark:text-emerald-400">
          <ShieldCheck className="size-3" /> MATCHED
        </span>
      );
    case "MISSING":
      return (
        <span className="inline-flex items-center gap-1 rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-rose-600 dark:text-rose-400">
          <XCircle className="size-3" /> MISSING
        </span>
      );
    case "UNCERTAIN":
      return (
        <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-amber-600 dark:text-amber-400">
          <AlertTriangle className="size-3" /> UNCERTAIN
        </span>
      );
  }
}

function RowIcon({ origin, status }: { origin: FieldOrigin; status: ResultRow["status"] }) {
  if (status === "success") {
    return <CheckCircle2 className="size-3.5 text-success shrink-0" />;
  }
  if (status === "destructive") {
    return <XCircle className="size-3.5 text-destructive shrink-0" />;
  }
  if (status === "warning") {
    return <AlertTriangle className="size-3.5 text-warning shrink-0" />;
  }
  return <Tag className="size-3.5 text-muted-foreground shrink-0" />;
}
