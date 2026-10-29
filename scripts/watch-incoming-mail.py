"""Run the read-only terminal demo using the existing operator certificate identities."""

import sys

from agenttrace_feasibility.mail_monitor import main

if __name__ == "__main__":
    raise SystemExit(main(["--demo-heuristic", *sys.argv[1:]]))
