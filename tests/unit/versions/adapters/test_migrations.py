from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    text,
)

from app.versions.adapters.migrations import migrate_version_stability

metadata = MetaData()

minecraft_versions_table = Table(
    "minecraft_versions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("server_type", String(20), nullable=False),
    Column("version", String(50), nullable=False),
    Column("download_url", Text, nullable=False),
    Column("is_stable", Boolean, default=True, nullable=False),
)


def _make_engine():
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    return engine


def _seed_rows(engine):
    with engine.connect() as conn:
        rows = [
            ("paper", "1.21", True),
            ("paper", "1.21-pre1", True),
            ("paper", "1.21-rc1", True),
            ("vanilla", "1.20.1", True),
            ("forge", "1.19.4", True),
            ("paper", "24w13a", True),
        ]
        for server_type, version, is_stable in rows:
            conn.execute(
                text(
                    "INSERT INTO minecraft_versions "
                    "(server_type, version, download_url, is_stable) "
                    "VALUES (:st, :v, :url, :s)"
                ),
                {
                    "st": server_type,
                    "v": version,
                    "url": f"https://example.com/{version}.jar",
                    "s": is_stable,
                },
            )
        conn.commit()


def _get_stability_map(engine) -> dict[str, bool]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT version, is_stable FROM minecraft_versions")
        ).fetchall()
    return {r[0]: bool(r[1]) for r in rows}


def test_backfill_corrects_prerelease_rows():
    engine = _make_engine()
    _seed_rows(engine)

    migrate_version_stability(engine)

    result = _get_stability_map(engine)
    assert result["1.21"] is True
    assert result["1.20.1"] is True
    assert result["1.19.4"] is True
    assert result["1.21-pre1"] is False
    assert result["1.21-rc1"] is False
    assert result["24w13a"] is False


def test_backfill_is_idempotent():
    engine = _make_engine()
    _seed_rows(engine)

    migrate_version_stability(engine)
    migrate_version_stability(engine)

    result = _get_stability_map(engine)
    assert result["1.21"] is True
    assert result["1.21-pre1"] is False


def test_backfill_noop_on_empty_table():
    engine = _make_engine()
    migrate_version_stability(engine)
