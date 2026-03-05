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
