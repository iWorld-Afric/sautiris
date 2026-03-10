"""Tests for ris005 migration — notification tracking columns."""

from __future__ import annotations

import importlib
import types


def _load_migration() -> types.ModuleType:
    """Import the ris005 migration module."""
    return importlib.import_module(
        "sautiris.migrations.versions.ris005_add_alert_notification_tracking"
    )


class TestRis005MigrationStructure:
    """M7: Verify ris005 migration is loadable and has correct structure."""

    def test_revision_id(self) -> None:
        mod = _load_migration()
        assert mod.revision == "ris005"

    def test_down_revision(self) -> None:
        mod = _load_migration()
        assert mod.down_revision == "ris004"

    def test_upgrade_function_exists(self) -> None:
        mod = _load_migration()
        assert callable(mod.upgrade)

    def test_downgrade_function_exists(self) -> None:
        mod = _load_migration()
        assert callable(mod.downgrade)

    def test_upgrade_adds_notification_columns(self) -> None:
        """Verify upgrade() references both notification tracking columns."""
        import inspect

        mod = _load_migration()
        source = inspect.getsource(mod.upgrade)
        assert "notification_failed" in source
        assert "notification_error" in source

    def test_downgrade_drops_notification_columns(self) -> None:
        """Verify downgrade() references both notification tracking columns."""
        import inspect

        mod = _load_migration()
        source = inspect.getsource(mod.downgrade)
        assert "notification_failed" in source
        assert "notification_error" in source
