"""On-demand Windows host, independent of a launcher's console/job lifetime.

No service, autostart, elevated privileges, shell strings or PID-based killing.
If the containing job forbids breakaway, creation fails; never silently weaken
the lifetime guarantee. The existing supervisor still owns its trading child.
"""
import os
from pathlib import Path
import subprocess
import sys

from .values import InvalidData


def spawn_host(arguments, *, cwd):
    if os.name != "nt":
        raise InvalidData("independent host requires native Windows")
    environment = {key: os.environ[key] for key in
        ("SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC") if key in os.environ}
    environment.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
        __PYVENV_LAUNCHER__=str(Path(sys.executable).resolve()))
    return subprocess.Popen([sys._base_executable, "-B", *arguments],
        cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
        shell=False, creationflags=(subprocess.DETACHED_PROCESS |
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_BREAKAWAY_FROM_JOB))
