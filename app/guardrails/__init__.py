"""Guardrails layer: the single place every trust boundary in this pipeline is
enforced, instead of scattered try/except blocks.

An LLM-adjacent invoice pipeline has five distinct places things go wrong, and
each one gets its own module here:

  file_validation  - GUARDRAIL 1: reject bad uploads before extraction ever runs.
  prompt_injection  - GUARDRAIL 2: extracted PDF text is untrusted; detect and
                       flag attempts to manipulate the pipeline through it.
  output_bounds     - GUARDRAIL 3: sanity-bound numeric fields coming out of
                       extraction (regex or LLM) before Validate trusts them.
  resilience        - GUARDRAIL 5: size/token pre-checks and retry/backoff
                       policy for every external Groq call.

GUARDRAIL 4 (the auto-approval dollar cap) lives as a named constant directly
in app/pipeline/decide.py, next to the rule that enforces it - the decision
engine IS the place to point to for that one.

Every guardrail either raises a caller-facing, clean-message exception, or
returns a structured result that feeds a rule in the Decide stage - never a
silent strip-and-continue and never a raw 500.
"""
