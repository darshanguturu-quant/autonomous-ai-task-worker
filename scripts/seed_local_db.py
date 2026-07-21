"""Explicitly load the fabricated fixtures/ vendor+PO dataset into your LOCAL
data/runs.db, for manual testing/demo prep against the fixture invoices.

The running app (`python main.py`) never does this automatically - it always
starts with zero vendors and zero POs, so nothing in the live product is
fabricated. Run this yourself, deliberately, when you want to test the full
pipeline (including Match/Decide) against the fixture invoices in fixtures/.

Run:  python scripts/seed_local_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402 - needs the sys.path fixup above

if __name__ == "__main__":
    db.init_db()
    db.seed_master_data(
        config.FIXTURES_DIR / "vendors.json",
        config.FIXTURES_DIR / "purchase_orders.json",
    )
    vendors = db.get_vendors()
    pos = db.get_purchase_orders()
    print(f"Seeded {config.DB_PATH} with {len(vendors)} vendors and {len(pos)} POs "
          f"from {config.FIXTURES_DIR}.")
    print("Restart the app (or it'll pick this up on the next request) - "
          "the fixture invoices in fixtures/invoices/ will now match cleanly.")
