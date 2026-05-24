import re

_PRE_RELEASE_PATTERN = re.compile(
    r"-(pre|rc|snapshot)\d*$|^\d{2}w\d{2}[a-z]?$",
    re.IGNORECASE,
)


def is_stable_version(version_string: str) -> bool:
    return not _PRE_RELEASE_PATTERN.search(version_string)
