#!/usr/bin/env python3
"""Development server management script for uv run."""

import os
import subprocess
import sys
from pathlib import Path


def get_project_root():
    """Get the project root directory."""
    current = Path(__file__).parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find project root")


def run_script(script_name: str, args: list[str] = None):
    """Run a shell script from the scripts directory."""
    project_root = get_project_root()
    script_path = project_root / "scripts" / script_name

    if not script_path.exists():
        print(f"Error: Script {script_path} not found", file=sys.stderr)
        sys.exit(1)

    # Make sure script is executable
    os.chmod(script_path, 0o755)

    # Run the script
    cmd = [str(script_path)]
    if args:
        cmd.extend(args)

    try:
        result = subprocess.run(cmd, check=False)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error running script: {e}", file=sys.stderr)
        sys.exit(1)


def dev_start():
    """Start development server."""
    run_script("dev-start.sh", ["start"])


def dev_stop():
    """Stop development server."""
    run_script("dev-start.sh", ["stop"])


def dev_status():
    """Show development server status."""
    run_script("dev-start.sh", ["status"])


def dev_logs():
    """Show development logs."""
    run_script("dev-start.sh", ["logs"])


def dev_logs_follow():
    """Follow development logs."""
    run_script("dev-start.sh", ["logs-follow"])


def dev_test():
    """Run tests."""
    run_script("dev-start.sh", ["test"])


def dev_lint():
    """Run linting."""
    run_script("dev-start.sh", ["lint"])


def dev_format():
    """Format code."""
    run_script("dev-start.sh", ["format"])


def main():
    """Main entry point for dev command with subcommands."""
    if len(sys.argv) < 2:
        print("Usage: uv run dev <command>")
        print("Commands: start, stop, status, logs, logs-follow, test, lint, format")
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:] if len(sys.argv) > 2 else []

    if command == "start":
        dev_start()
    elif command == "stop":
        dev_stop()
    elif command == "status":
        dev_status()
    elif command == "logs":
        if args and args[0] == "follow":
            dev_logs_follow()
        else:
            dev_logs()
    elif command == "logs-follow":
        dev_logs_follow()
    elif command == "test":
        dev_test()
    elif command == "lint":
        dev_lint()
    elif command == "format":
        dev_format()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(
            "Available commands: start, stop, status, logs, logs-follow, test, lint, format"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
