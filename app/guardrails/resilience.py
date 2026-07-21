"""GUARDRAIL 5 - LLM / API RESILIENCE.

Every external Groq call is wrapped by three independent guardrails, defined
here as policy rather than left as a one-off fix buried in extraction code:

  1. Pre-flight size/token budget check (REQUEST_TOKEN_BUDGET, RENDER_LADDER) -
     estimate the full request cost (prompt + image + max completion tokens)
     BEFORE calling Groq, and only ever send a render that fits. This is what
     actually fixed the 413 "request too large" failures - by pre-checking
     instead of reacting to them. See app/pipeline/vision.py:_budgeted_renders.

  2. Retry with exponential backoff on 429 (rate limit) - transient, so it is
     safe to retry (RATE_LIMIT_RETRIES, BACKOFF_BASE_SECONDS). 413 (the
     request itself is too large) is deliberately NOT retried here: waiting
     cannot shrink an oversized request, so the caller downscales the image
     instead. See app/pipeline/vision.py:_completion_with_backoff.

  3. Clean, user-facing failure states - ExtractionServiceBusy and
     VisionNotConfigured (app/pipeline/extract.py) carry messages that are
     already safe to show in the UI. app/pipeline/run.py:public_error()
     collapses any other Groq SDK exception (which carries org IDs, billing
     URLs, etc.) into a generic "temporarily busy" message before it can
     reach the UI. A failed run renders as a clear FailureBanner, never a
     raw stack trace or an unhandled 500.
"""

MAX_COMPLETION_TOKENS = 4000    # JSON + hidden reasoning. Bumped from 3000: adding the
                                 # prompt-injection defense instruction (GUARDRAIL 2) gave
                                 # the reasoning model more to deliberate over, and it was
                                 # measured exhausting the smaller budget mid-JSON, returning
                                 # a 400 "max completion tokens reached" instead of a result.
IMAGE_TOKENS_FLOOR = 2400       # Groq pre-check charges ~2.4-2.7K per image regardless of size
TOKENS_PER_IMAGE_BYTE = 0.015   # measured billing rate for large renders
PROMPT_TOKENS = 900             # schema prompt + message overhead, generous
REQUEST_TOKEN_BUDGET = 7500     # free-tier TPM is 8 000; leave headroom
# 100 dpi grayscale is the sharpest render worth paying for: measured extraction
# quality is identical to 120 dpi on real invoices at ~40% fewer bytes.
RENDER_LADDER = [(100, 68), (85, 60), (72, 55), (60, 50)]  # (dpi, jpeg quality)

RATE_LIMIT_RETRIES = 3          # extra attempts on 429 before giving up
BACKOFF_BASE_SECONDS = 2.0      # 2s -> 4s -> 8s when Groq sends no retry-after
