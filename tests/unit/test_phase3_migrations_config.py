"""Regression coverage for the explicit Compose migration entry point."""

from __future__ import annotations

from pathlib import Path

from app.migrations import alembic_config


def test_alembic_config_uses_repository_absolute_locations() -> None:
    """A container CWD must not redirect Alembic away from our revisions."""

    config = alembic_config("postgresql://axit:local@database.test/axit")

    scripts = Path(config.get_main_option("script_location")).resolve()
    import_root = Path(config.get_main_option("prepend_sys_path")).resolve()
    assert scripts.name == "alembic"
    assert (scripts / "versions" / "0001_durable_core.py").is_file()
    assert import_root.name == "api"
    assert config.attributes["database_url"] == "postgresql://axit:local@database.test/axit"
