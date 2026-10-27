"""Exercise the real shell supervisor with controlled services, without Docker."""

import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BASH = shutil.which("bash")
if not BASH and Path("C:/Program Files/Git/bin/bash.exe").is_file():
    BASH = "C:/Program Files/Git/bin/bash.exe"
pytestmark = pytest.mark.skipif(
    not BASH, reason="Bash is needed for container shell tests"
)


def script(path, content):
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def test_supervisor_restarts_worker_and_forwards_shutdown(tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    service = """#!/usr/bin/env bash
trap 'exit 0' TERM INT
while true; do sleep 0.05 & wait $!; done
"""
    for name in ("uvicorn", "next"):
        script(binaries / name, service)
    script(
        binaries / "python",
        """#!/usr/bin/env bash
printf '%s\n' "$$" >> "$POSTFORGE_TEST_WORKERS"
trap 'exit 0' TERM INT
while true; do sleep 0.05 & wait $!; done
""",
    )
    supervisor = (ROOT / "scripts/container-entrypoint.sh").read_text()
    supervisor = supervisor.replace(
        "cd /app/backend", f"cd {shlex.quote(tmp_path.as_posix())}"
    )
    supervisor = supervisor.replace(
        "cd /app/frontend", f"cd {shlex.quote(tmp_path.as_posix())}"
    )
    script(tmp_path / "supervisor.sh", supervisor)
    harness = """#!/usr/bin/env bash
set -euo pipefail
cd "$1"
export PATH="$(cd bin && pwd):$PATH"
export POSTFORGE_TEST_WORKERS="$(pwd)/workers"
bash supervisor.sh > supervisor.log 2>&1 &
manager=$!
cleanup() {
  kill -TERM "$manager" 2>/dev/null || true
  wait "$manager" 2>/dev/null || true
}
trap cleanup EXIT
for ((i=0;i<100;i++)); do
  [[ -s workers ]] && break
  sleep 0.05
done
[[ -s workers ]]
first=$(tail -n 1 workers)
kill -TERM "$first"
for ((i=0;i<100;i++)); do
  [[ $(wc -l < workers) -ge 2 ]] && break
  sleep 0.05
done
[[ $(wc -l < workers) -ge 2 ]]
second=$(tail -n 1 workers)
[[ "$first" != "$second" ]]
kill -0 "$manager"
kill -0 "$second"
kill -TERM "$manager"
wait "$manager"
! kill -0 "$second" 2>/dev/null
trap - EXIT
"""
    script(tmp_path / "harness.sh", harness)
    result = subprocess.run(
        [BASH, str(tmp_path / "harness.sh"), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, (
        result.stderr + (tmp_path / "supervisor.log").read_text()
    )
    assert "Generation worker exited" in (tmp_path / "supervisor.log").read_text()


@pytest.mark.parametrize("age,expected", [(0, 0), (120, 1)])
def test_healthcheck_requires_recent_worker_heartbeat(tmp_path, age, expected):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    script(binaries / "curl", "#!/usr/bin/env bash\nprintf 200\n")
    script(
        binaries / "python",
        "#!/usr/bin/env bash\n"
        f'exec {shlex.quote(Path(sys.executable).as_posix())} "$@"\n',
    )
    heartbeat = tmp_path / "heartbeat"
    heartbeat.write_text(str(time.time() - age))
    env = {**os.environ, "GENERATION_WORKER_HEARTBEAT": str(heartbeat)}
    command = 'export PATH="$(cd "$1" && pwd):$PATH"; exec bash "$2"'
    result = subprocess.run(
        [
            BASH,
            "-c",
            command,
            "test",
            str(binaries),
            str(ROOT / "scripts/container-healthcheck.sh"),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == expected, result.stderr
