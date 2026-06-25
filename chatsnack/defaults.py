import os
import sys

from snapclass import Stash

# give the default system message a name
try:
    script_name = sys.argv[0]
    # remove any file extension
    basenamestr = os.path.splitext(os.path.basename(script_name))[0]
    namestr = f" for an intelligent program called {basenamestr}"
except:
    namestr = ""

# This is the default directory for chatsnack's persisted prompt assets.
# The stash owns env override behavior; the string export is kept for existing
# user code and tests that treat CHATSNACK_BASE_DIR as a filesystem path.
# Keep the default relative. Existing notebook/test workflows import chatsnack,
# then chdir into a scratch workspace before saving prompt assets.
_DEFAULT_CHATSNACK_BASE_DIR = "./datafiles/chatsnack"
CHATSNACK_ROOT = Stash(_DEFAULT_CHATSNACK_BASE_DIR, env="CHATSNACK_BASE_DIR")
CHATSNACK_PROMPTS = CHATSNACK_ROOT


def _normalize_exported_path(path):
    """Normalize compatibility path exports without corrupting filesystem roots."""
    return os.path.normpath(os.fspath(path))


CHATSNACK_BASE_DIR = _normalize_exported_path(os.getenv("CHATSNACK_BASE_DIR", _DEFAULT_CHATSNACK_BASE_DIR))

if os.getenv("CHATSNACK_LOGS_DIR") is None:
    CHATSNACK_LOGS_DIR = None   # no logging by default
else:
    CHATSNACK_LOGS_DIR = os.getenv("CHATSNACK_LOGS_DIR")
    CHATSNACK_LOGS_DIR = CHATSNACK_LOGS_DIR.rstrip("/")
