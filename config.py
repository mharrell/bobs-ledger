r"""Shared install paths for the hearth-coach tools.

Every tool hardcoded the Windows client path — a non-default install (or a
non-Windows machine) meant editing each file separately. One module now owns
them; override the client root with the HEARTHSTONE_HOME env var.

Constants:
    HS_DIR        client root (default C:\Program Files (x86)\Hearthstone)
    HS_LOG_GLOB   glob for the per-session Power.log files
    HS_DATA_DIR   client data dir (UnityPy carddef*.unity3d bundles)
"""
import os

HS_DIR = os.environ.get("HEARTHSTONE_HOME", r"C:\Program Files (x86)\Hearthstone")
HS_LOG_GLOB = os.path.join(HS_DIR, "Logs", "Hearthstone_*", "Power.log")
HS_DATA_DIR = os.path.join(HS_DIR, "Data", "Win")