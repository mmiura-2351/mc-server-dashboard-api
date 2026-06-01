"""Unit tests for the pure ``_tail_file_lines`` log-tail helper (issue #436)."""

from app.servers.application.minecraft.monitoring import _tail_file_lines


def test_tail_small_file_returns_all_lines(tmp_path):
    log_file = tmp_path / "server.log"
    log_file.write_text("line one\nline two\nline three\n")

    lines, end = _tail_file_lines(log_file, max_bytes=64 * 1024, max_lines=100)

    assert lines == ["line one", "line two", "line three"]
    assert end == log_file.stat().st_size


def test_tail_caps_to_max_lines(tmp_path):
    log_file = tmp_path / "server.log"
    log_file.write_text("".join(f"line {i}\n" for i in range(10)))

    lines, end = _tail_file_lines(log_file, max_bytes=64 * 1024, max_lines=3)

    assert lines == ["line 7", "line 8", "line 9"]
    assert end == log_file.stat().st_size


def test_tail_bounded_window_drops_partial_first_line(tmp_path):
    # 100 lines of fixed width; a small byte window starts mid-file, so the
    # first (partial) line must be dropped and only whole lines kept.
    log_file = tmp_path / "server.log"
    log_file.write_text("".join(f"line-{i:04d}\n" for i in range(100)))

    # Each line is "line-NNNN\n" == 10 bytes. A 35-byte window spans the tail
    # of one line plus the last three full lines.
    lines, end = _tail_file_lines(log_file, max_bytes=35, max_lines=100)

    assert lines == ["line-0097", "line-0098", "line-0099"]
    # Partial leading fragment is never emitted.
    assert all(line.startswith("line-") and len(line) == 9 for line in lines)
    assert end == log_file.stat().st_size


def test_tail_skips_blank_lines(tmp_path):
    log_file = tmp_path / "server.log"
    log_file.write_text("first\n\n   \nsecond\n")

    lines, _ = _tail_file_lines(log_file, max_bytes=64 * 1024, max_lines=100)

    assert lines == ["first", "second"]


def test_tail_empty_file(tmp_path):
    log_file = tmp_path / "server.log"
    log_file.write_text("")

    lines, end = _tail_file_lines(log_file, max_bytes=64 * 1024, max_lines=100)

    assert lines == []
    assert end == 0


def test_tail_preserves_original_minecraft_timestamps(tmp_path):
    log_file = tmp_path / "server.log"
    log_file.write_text(
        "[12:34:56] [Server thread/INFO]: Starting\n"
        "[12:35:01] [Server thread/INFO]: Done\n"
    )

    lines, _ = _tail_file_lines(log_file, max_bytes=64 * 1024, max_lines=100)

    # Original embedded [HH:MM:SS] timestamps are preserved verbatim.
    assert lines == [
        "[12:34:56] [Server thread/INFO]: Starting",
        "[12:35:01] [Server thread/INFO]: Done",
    ]
