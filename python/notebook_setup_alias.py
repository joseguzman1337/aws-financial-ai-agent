"""Notebook setup alias for AWS Authentication Phase bootstrap."""

from __future__ import annotations

import os
import subprocess
import sys
import warnings
import hashlib
from pathlib import Path

import requests


def aws_auth_phase_setup() -> dict:
    """Install deps, load GitHub runtimes, initialize R runtime state."""
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "rpy2",
            "awscli",
            "markdown",
            "boto3",
            "botocore",
            "requests",
        ],
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
    neofetch_out = subprocess.check_output(["neofetch"], text=True)
    print(neofetch_out, end="")

    warnings.filterwarnings(
        "ignore",
        message=r".*reticulate.*segfault.*",
        category=UserWarning,
    )
    from rpy2 import robjects

    bust = str(int(__import__("time").time()))
    py_raw = (
        "https://raw.githubusercontent.com/joseguzman1337/"
        "aws-financial-ai-agent/main/python/notebook_runtime_core.py"
        f"?v={bust}"
    )
    r_raw = (
        "https://raw.githubusercontent.com/joseguzman1337/"
        "aws-financial-ai-agent/main/r/notebook_runtime.R"
        f"?v={bust}"
    )
    py_file = Path("/tmp/notebook_runtime_core.py")
    r_file = Path("/tmp/notebook_runtime.R")
    py_txt = requests.get(py_raw, timeout=30).text
    r_txt = requests.get(r_raw, timeout=30).text
    py_file.write_text(py_txt, encoding="utf-8")
    r_file.write_text(r_txt, encoding="utf-8")
    py_hash = hashlib.sha256(py_txt.encode("utf-8")).hexdigest()[:12]
    print(f"Runtime core loaded: /tmp/notebook_runtime_core.py sha256={py_hash}")
    os.environ["NOTEBOOK_RUNTIME_PY_FILE"] = str(py_file)
    os.environ["RETICULATE_PYTHON"] = sys.executable

    robjects.r(f"source('{r_file}')")
    robjects.r("rt <- runtime_init(); rt <- refresh_clients(rt)")
    # Keep first block output minimal (neofetch only).
    return {"robjects": robjects}
