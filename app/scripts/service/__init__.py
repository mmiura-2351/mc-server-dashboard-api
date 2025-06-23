#!/usr/bin/env python3
"""Service management script for uv run."""

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


def service_start():
    """Start production service."""
    run_script("service-manager.sh", ["start"])


def service_stop():
    """Stop production service."""
    run_script("service-manager.sh", ["stop"])


def service_restart():
    """Restart production service."""
    run_script("service-manager.sh", ["restart"])


def service_status():
    """Show production service status."""
    run_script("service-manager.sh", ["status"])


def service_logs():
    """Show production service logs."""
    run_script("service-manager.sh", ["logs"])


def service_logs_follow():
    """Follow production service logs."""
    run_script("service-manager.sh", ["logs-follow"])


def service_enable():
    """Enable auto-start on boot."""
    run_script("service-manager.sh", ["enable"])


def service_disable():
    """Disable auto-start on boot."""
    run_script("service-manager.sh", ["disable"])


def service_reload():
    """Reload service configuration."""
    run_script("service-manager.sh", ["reload"])


def main():
    """Main entry point for service command with subcommands."""
    if len(sys.argv) < 2:
        print("Usage: uv run service <command>")
        print(
            "Commands: start, stop, restart, status, logs, logs-follow, enable, disable, reload"
        )
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:] if len(sys.argv) > 2 else []

    if command == "start":
        service_start()
    elif command == "stop":
        service_stop()
    elif command == "restart":
        service_restart()
    elif command == "status":
        service_status()
    elif command == "logs":
        if args and args[0] == "follow":
            service_logs_follow()
        else:
            service_logs()
    elif command == "logs-follow":
        service_logs_follow()
    elif command == "enable":
        service_enable()
    elif command == "disable":
        service_disable()
    elif command == "reload":
        service_reload()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(
            "Available commands: start, stop, restart, status, logs, logs-follow, enable, disable, reload"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
