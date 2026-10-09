"""Stage 3 - MATCH: invoice -> vendor -> PO, with tolerance and cumulative logic.

Every computed number (similarity score, tolerance dollars, difference,
cumulative billed-to-date) is included in the output so the result view can
show the full evidence trail, not just a verdict.

`prior_invoices` is the list of previously processed, non-rejected invoices
(from the runs DB): [{"invoice_number", "vendor_name", "po_ref", "total"}, ...].
It drives cumulative billed-to-date for split-PO / progress billing.
"""

import re
from difflib import SequenceMatcher

from app import db

VENDOR_MATCH_THRESHOLD = 0.80
# Corporate suffixes ignored when comparing vendor names.
_SUFFIXES = {"ltd", "llc", "inc", "co", "corp", "corporation", "company", "group"}


def load_vendors() -> list[dict]:
    return db.get_vendors()


def load_purchase_orders() -> list[dict]:
    return db.get_purchase_orders()


def _normalize(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return " ".join(w for w in words if w not in _SUFFIXES)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def match_vendor(extracted_name: str | None, vendors: list[dict]) -> dict:
    if not vendors:
        return {
            "matched": False,
            "similarity": 0.0,
            "closest": None,
            "detail": "no vendor records configured in database; matching cannot be completed",
        }
    if not extracted_name:
        return {"matched": False, "detail": "no vendor name extracted"}
    best, best_score, best_alias = None, 0.0, None
    for vendor in vendors:
        for candidate in [vendor["name"], *vendor["aliases"]]:
            score = _similarity(extracted_name, candidate)
            if score > best_score:
                best, best_score, best_alias = vendor, score, candidate
    if best and best_score >= VENDOR_MATCH_THRESHOLD:
        return {
            "matched": True,
            "vendor_id": best["vendor_id"],
            "vendor_name": best["name"],
            "approved": best["approved"],
            "matched_against": best_alias,
            "similarity": round(best_score, 3),
            "detail": f"'{extracted_name}' matched '{best_alias}' (similarity {best_score:.2f})",
        }
    return {
        "matched": False,
        "similarity": round(best_score, 3),
        "closest": best["name"] if best else None,
        "detail": f"no vendor above threshold {VENDOR_MATCH_THRESHOLD} "
                  f"(closest: {best['name'] if best else 'n/a'} at {best_score:.2f})",
    }


def _tolerance(po: dict) -> float:
    return round(max(po["tolerance_pct"] / 100 * po["amount"], po["tolerance_abs"]), 2)


def _amount_check(po: dict, invoice_total: float, cumulative_prior: float) -> dict:
    tol = _tolerance(po)
    diff = round(invoice_total - po["amount"], 2)
    within_full = abs(diff) <= tol

    # Partial billing: invoice is well under the PO -> reconcile cumulatively.
    is_partial = diff < -tol
    cumulative = round(cumulative_prior + invoice_total, 2)
    cumulative_within = cumulative <= po["amount"] + tol

    return {
        "po_amount": po["amount"],
        "invoice_total": invoice_total,
        "tolerance": tol,
        "tolerance_rule": f"max({po['tolerance_pct']}% of PO, ${po['tolerance_abs']:,.2f}) = ${tol:,.2f}",
        "difference": diff,
        "within_tolerance": within_full,
        "billing_mode": "partial" if is_partial else "full",
        "cumulative_prior": round(cumulative_prior, 2),
        "cumulative_with_this_invoice": cumulative,
        "cumulative_within_po": cumulative_within,
    }


def match(extract_result: dict, prior_invoices: list[dict] | None = None) -> dict:
    prior_invoices = prior_invoices or []
    fields = extract_result["fields"]
    invoice_total = fields["total"]["value"]
    po_ref = fields["po_ref"]["value"]

    vendors, pos = load_vendors(), load_purchase_orders()
    vendor_result = match_vendor(fields["vendor_name"]["value"], vendors)

    result: dict = {"vendor_match": vendor_result, "po_match": None, "amount_check": None}
    if not vendor_result["matched"]:
        return result

    vendor_id = vendor_result["vendor_id"]
    vendor_pos = [p for p in pos if p["vendor_id"] == vendor_id and p["status"] == "open"]

    def cumulative_prior_for(po_number: str) -> float:
        return sum(inv["total"] for inv in prior_invoices if inv.get("po_ref") == po_number)

    if not pos:
        result["po_match"] = {
            "matched": False,
            "match_type": "explicit" if po_ref else "fuzzy_vendor_amount",
            "detail": "no purchase order records configured in database; PO matching cannot be completed",
        }
        return result

    if po_ref:
        po = next((p for p in pos if p["po_number"] == po_ref), None)
        if po is None:
            result["po_match"] = {
                "matched": False,
                "match_type": "explicit",
                "detail": f"PO reference '{po_ref}' not found in PO dataset",
            }
            return result
        if po["vendor_id"] != vendor_id:
            result["po_match"] = {
                "matched": False,
                "match_type": "explicit",
                "detail": f"'{po_ref}' exists but belongs to a different vendor "
                          f"({po['vendor_id']}, not {vendor_id})",
            }
            return result
        result["po_match"] = {
            "matched": True,
            "match_type": "explicit",
            "po_number": po["po_number"],
            "po_description": po["description"],
            "detail": f"explicit PO reference '{po_ref}' found, vendor matches",
        }
    else:
        # No PO on the document: fuzzy fallback by vendor + closest amount.
        if not vendor_pos:
            result["po_match"] = {
                "matched": False,
                "match_type": "fuzzy_vendor_amount",
                "detail": "no PO reference on invoice and no open POs for this vendor",
            }
            return result
        po = min(vendor_pos, key=lambda p: abs(p["amount"] - (invoice_total or 0)))
        result["po_match"] = {
            "matched": True,
            "match_type": "fuzzy_vendor_amount",
            "po_number": po["po_number"],
            "po_description": po["description"],
            "candidates_considered": [p["po_number"] for p in vendor_pos],
            "detail": f"no PO reference on invoice; closest open PO for vendor by amount "
                      f"is {po['po_number']} (${po['amount']:,.2f})",
        }

    if invoice_total is not None:
        result["amount_check"] = _amount_check(po, invoice_total, cumulative_prior_for(po["po_number"]))
    return result
