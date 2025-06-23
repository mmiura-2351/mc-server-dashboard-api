#!/usr/bin/env python3
"""Deployment management script for uv run."""

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


def deploy():
    """Deploy to production."""
    run_script("deploy.sh")


def main():
    """Main entry point for deploy command."""
    deploy()


if __name__ == "__main__":
    main()
