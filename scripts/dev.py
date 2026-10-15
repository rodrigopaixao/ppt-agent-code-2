"""Run the API and web development servers together."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    processes = [
        subprocess.Popen(["npm", "run", "dev:api"], cwd=ROOT, start_new_session=True),
        subprocess.Popen(["npm", "run", "dev:web"], cwd=ROOT, start_new_session=True),
    ]

    def stop(_signum=None, _frame=None) -> None:
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while True:
            if any(process.poll() is not None for process in processes):
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        stop()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    return next((process.returncode or 0 for process in processes if process.returncode), 0)


if __name__ == "__main__":
    sys.exit(main())
