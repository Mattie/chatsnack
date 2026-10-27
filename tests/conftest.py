"""Keep paid-test opt-ins explicit before chatsnack loads the project .env."""

import os


for _live_flag in (
    "CHATSNACK_RUN_LIVE_TESTS",
    "CHATSNACK_RUN_OPENROUTER_LIVE",
    "CHATSNACK_RUN_MUSE_LIVE",
    "CHATSNACK_RUN_TYPESAFE_LIVE",
    "CHATSNACK_RUN_DECISIONS_LIVE",
    "CHATSNACK_RUN_DECISIONS_CONTEXT_LIVE",
):
    os.environ.setdefault(_live_flag, "")
