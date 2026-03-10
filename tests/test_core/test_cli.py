"""Tests for the SautiRIS CLI."""

from __future__ import annotations

from click.testing import CliRunner

from sautiris.cli import main


class TestCLI:
    """Tests for SautiRIS CLI commands."""

    def test_main_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "SautiRIS" in result.output

    def test_serve_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
        assert "--workers" in result.output

    def test_db_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["db", "--help"])
        assert result.exit_code == 0
        assert "upgrade" in result.output
        assert "seed" in result.output

    def test_db_seed(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["db", "seed"])
        assert result.exit_code == 0
        assert "Seeding" in result.output

    def test_mwl_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["mwl", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output

    def test_mwl_start_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["mwl", "start", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--ae-title" in result.output

    def test_rotate_key_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["security", "rotate-key", "--help"])
        assert result.exit_code == 0
        assert "--old-key" in result.output
        assert "--new-key" in result.output
        assert "--database-url" in result.output

    def test_rotate_key_reads_keys_from_envvars(self) -> None:
        """rotate-key accepts --old-key and --new-key via environment variables."""
        from cryptography.fernet import Fernet

        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()
        runner = CliRunner()
        # Pass keys via envvar only (no --old-key / --new-key flags).
        # Without a database URL the command will fail at DB connect, but we
        # verify the key validation step succeeds (no "Missing option" error).
        result = runner.invoke(
            main,
            ["security", "rotate-key"],
            env={
                "SAUTIRIS_OLD_ENCRYPTION_KEY": old_key,
                "SAUTIRIS_NEW_ENCRYPTION_KEY": new_key,
                "SAUTIRIS_DATABASE_URL": "sqlite:///nonexistent.db",
            },
        )
        # Should NOT fail with "Missing option --old-key" or "--new-key"
        assert "Missing option" not in (result.output or "")
        assert "--old-key" not in (result.output or "")
        assert "--new-key" not in (result.output or "")
