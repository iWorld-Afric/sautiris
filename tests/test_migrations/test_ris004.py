"""Tests for ris004 migration — add study_instance_uid and scheduled_performing_physician_name."""

from __future__ import annotations

import importlib
import types


def _load_migration() -> types.ModuleType:
    """Import the ris004 migration module."""
    return importlib.import_module(
        "sautiris.migrations.versions.ris004_add_study_instance_uid_to_worklist"
    )


class TestRis004MigrationStructure:
    """Verify ris004 migration adds both worklist columns."""

    def test_revision_id(self) -> None:
        mod = _load_migration()
        assert mod.revision == "ris004"

    def test_down_revision(self) -> None:
        mod = _load_migration()
        assert mod.down_revision == "ris003"

    def test_upgrade_function_exists(self) -> None:
        mod = _load_migration()
        assert callable(mod.upgrade)

    def test_downgrade_function_exists(self) -> None:
        mod = _load_migration()
        assert callable(mod.downgrade)

    def test_upgrade_adds_both_columns(self) -> None:
        """Verify upgrade() calls op.add_column for both columns."""
        import inspect

        mod = _load_migration()
        source = inspect.getsource(mod.upgrade)
        assert "study_instance_uid" in source
        assert "scheduled_performing_physician_name" in source

    def test_downgrade_drops_both_columns(self) -> None:
        """Verify downgrade() calls op.drop_column for both columns."""
        import inspect

        mod = _load_migration()
        source = inspect.getsource(mod.downgrade)
        assert "study_instance_uid" in source
        assert "scheduled_performing_physician_name" in source
