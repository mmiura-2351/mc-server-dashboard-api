import re

# Covers: -pre1, -rc1, -snapshot1, weekly snapshots (24w13a),
# and experimental snapshots (1.18_experimental-snapshot-7).
# Combat test builds and other ancient formats (< 1.8) are excluded
# from discovery by the version_manager's minimum_version filter.
_PRE_RELEASE_PATTERN = re.compile(
    r"-(pre|rc|snapshot)\d*$"
    r"|^\d{2}w\d{2}[a-z]?$"
    r"|_experimental-snapshot",
    re.IGNORECASE,
)


def is_stable_version(version_string: str) -> bool:
    return not _PRE_RELEASE_PATTERN.search(version_string)
