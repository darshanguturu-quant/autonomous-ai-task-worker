"""Stage - GUARDRAILS: prompt-injection screening on untrusted extracted text.

Runs immediately after Extract and before Validate/Match/Decide ever see the
data. Every free-text field pulled from the PDF - vendor name, PO reference,
line-item descriptions - is scanned for known prompt-injection phrasing
("ignore previous instructions", "system:", role-play framing, explicit
auto-approve directives). A match is never silently stripped: it is recorded
here, and the Decide stage's R0 rule turns a flagged run into a hard Needs
Review, evaluated before any other rule.

This stage is deliberately a static pattern scan with no LLM call, so it
cannot itself be tricked by the text it is screening.
"""

from app.guardrails.prompt_injection import scan_extracted_invoice


def screen(extract_result: dict) -> dict:
    return scan_extracted_invoice(extract_result)
