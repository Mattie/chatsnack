"""Keep paid-test opt-ins explicit before chatsnack loads the project .env."""

import os


for _live_flag in (
    "CHATSNACK_RUN_LIVE_TESTS",
    "CHATSNACK_RUN_OPENROUTER_LIVE",
):
    os.environ.setdefault(_live_flag, "")
