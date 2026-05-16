import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _read_version() -> str:
    try:
        return version("mc-server-dashboard-api")
    except PackageNotFoundError:
        pass

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.is_file():
        with pyproject.open("rb") as f:
            data = tomllib.load(f)
        v = data.get("project", {}).get("version")
        if isinstance(v, str):
            return v

    return "0.0.0+unknown"


__version__ = _read_version()

__all__ = ["__version__"]
