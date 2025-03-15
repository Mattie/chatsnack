import os
import sys

# give the default system message a name
try:
    script_name = sys.argv[0]
    # remove any file extension
    basenamestr = os.path.splitext(os.path.basename(script_name))[0]
    namestr = f" for an intelligent program called {basenamestr}"
except:
    namestr = ""

# if there's a "CHATSNACK_BASE_DIR" env variable, use that for our default path variable and set it to './datafiles/plunkylib'
# this is the default directory for all chatsnack datafiles
if os.getenv("CHATSNACK_BASE_DIR") is None:
    CHATSNACK_BASE_DIR = "./datafiles/chatsnack"
else:
    CHATSNACK_BASE_DIR = os.getenv("CHATSNACK_BASE_DIR")
    CHATSNACK_BASE_DIR = CHATSNACK_BASE_DIR.rstrip("/")

if os.getenv("CHATSNACK_LOGS_DIR") is None:
    CHATSNACK_LOGS_DIR = None   # no logging by default
else:
    CHATSNACK_LOGS_DIR = os.getenv("CHATSNACK_LOGS_DIR")
    CHATSNACK_LOGS_DIR = CHATSNACK_LOGS_DIR.rstrip("/")