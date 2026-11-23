"""Start the shared ShortTrip server (PC browser + Android app, accounts in GaussDB/openGauss).

    python start_server.py                 # listen on the LAN, port 8790
    python start_server.py --host 127.0.0.1 --port 8890
"""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PLANNER = ROOT / "combined version_personalized"


def main():
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32:
        sys.exit("请使用 64 位 Windows 版 Python 3.12 运行。")
    env_dir = PLANNER / ".venv"
    python = env_dir / "Scripts/python.exe"
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(env_dir)], check=True)
    requirements = [PLANNER / "requirements.txt", ROOT / "shorttrip_cloud/requirements-cloud.txt"]
    wanted = b"".join(path.read_bytes() for path in requirements)
    stamp = env_dir / "shorttrip-requirements.txt"
    if not stamp.exists() or stamp.read_bytes() != wanted:
        index = ["--index-url", os.environ["SHORTTRIP_PIP_INDEX"]] if os.environ.get("SHORTTRIP_PIP_INDEX") else []
        args = [str(python), "-m", "pip", "install", "--disable-pip-version-check", *index]
        for path in requirements:
            args += ["-r", str(path)]
        subprocess.run(args, check=True)
        stamp.write_bytes(wanted)
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}
    command = [str(python), "-B", "-X", "utf8", "-m", "shorttrip_cloud", "serve", "--release", str(ROOT), *sys.argv[1:]]
    raise SystemExit(subprocess.run(command, cwd=ROOT, env=env).returncode)


if __name__ == "__main__":
    main()
