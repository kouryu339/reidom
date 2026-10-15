from __future__ import annotations

import ctypes
import os
import sys
import threading
from pathlib import Path


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _watch_parent() -> None:
    raw_pid = os.getenv("REIDOM_PARENT_PID", "").strip()
    if not raw_pid.isdigit() or os.name != "nt":
        return
    parent_pid = int(raw_pid)
    kernel32 = ctypes.windll.kernel32
    synchronize = 0x00100000
    infinite = 0xFFFFFFFF
    handle = kernel32.OpenProcess(synchronize, False, parent_pid)
    if not handle:
        os._exit(0)
    kernel32.WaitForSingleObject(handle, infinite)
    kernel32.CloseHandle(handle)
    os._exit(0)


os.environ.setdefault(
    "COREWORK_AGENT_TOOL_PROTO",
    str(_bundle_root() / "corework_agent_tool_v1.proto"),
)
threading.Thread(target=_watch_parent, name="reidom-parent-watch", daemon=True).start()

from reidom_midi_tools.project_tools import main


if __name__ == "__main__":
    main()
