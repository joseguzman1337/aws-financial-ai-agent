"""Notebook setup alias for AWS Authentication Phase bootstrap."""

from __future__ import annotations

import os
import subprocess
import sys
import warnings
from pathlib import Path

import requests


def aws_auth_phase_setup() -> dict:
    """Install deps, load GitHub runtimes, initialize R runtime state."""
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "rpy2"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        "sudo apt-get update -y -q > /dev/null && sudo apt-get install -y -q r-base neofetch > /dev/null",
        shell=True,
        check=True,
    )
    subprocess.run(
        ["R", "-q", "-e", "install.packages(c('reticulate'), repos='https://cloud.r-project.org', quiet=TRUE)"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Keep visible by request.
    subprocess.run(["neofetch"], check=True)

    warnings.filterwarnings(
        "ignore",
        message=r".*reticulate.*segfault.*",
        category=UserWarning,
    )
    from rpy2 import robjects

    py_raw = "https://raw.githubusercontent.com/joseguzman1337/aws-financial-ai-agent/main/python/notebook_runtime_core.py"
    r_raw = "https://raw.githubusercontent.com/joseguzman1337/aws-financial-ai-agent/main/r/notebook_runtime.R"
    py_file = Path("/tmp/notebook_runtime_core.py")
    r_file = Path("/tmp/notebook_runtime.R")
    py_file.write_text(requests.get(py_raw, timeout=30).text, encoding="utf-8")
    r_file.write_text(requests.get(r_raw, timeout=30).text, encoding="utf-8")
    os.environ["NOTEBOOK_RUNTIME_PY_FILE"] = str(py_file)

    robjects.r(f"source('{r_file}')")
    robjects.r("rt <- runtime_init(); rt <- refresh_clients(rt)")
    # Keep first block output minimal (neofetch only).
    return {"robjects": robjects}
