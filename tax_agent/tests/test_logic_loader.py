"""Tests for Chain-of-Logic Loader — Step 3."""
import pytest
from pathlib import Path

from app.services import logic_loader
from app.services.logic_loader import get_logic_rules, clear_cache


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear loader cache before each test."""
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def logic_dir(tmp_path):
    """Create a temp logic directory with a sample VAT rules file."""
    vat_file = tmp_path / "vat_rules.md"
    vat_file.write_text("## დღგ წესები\nRule 1: 18% rate.", encoding="utf-8")
    return tmp_path


def test_load_rules_for_vat(monkeypatch, logic_dir):
    """Loads VAT rules from file when flag is enabled."""
    monkeypatch.setattr(logic_loader, "LOGIC_DIR", logic_dir)
    monkeypatch.setenv("LOGIC_RULES_ENABLED", "true")
    from config import Settings
    monkeypatch.setattr(logic_loader, "settings", Settings())

    result = get_logic_rules("VAT")
    assert result is not None
    assert "18%" in result
    assert "დღგ" in result


def test_cache_reuses_loaded(monkeypatch, logic_dir):
    """Second call returns cached value, no re-read."""
    monkeypatch.setattr(logic_loader, "LOGIC_DIR", logic_dir)
    monkeypatch.setenv("LOGIC_RULES_ENABLED", "true")
    from config import Settings
    monkeypatch.setattr(logic_loader, "settings", Settings())

    r1 = get_logic_rules("VAT")
    # Delete the file — cache should still return content
    (logic_dir / "vat_rules.md").unlink()
    r2 = get_logic_rules("VAT")
    assert r1 == r2


def test_missing_domain_returns_none(monkeypatch, logic_dir):
    """Domain without a rules file returns None."""
    monkeypatch.setattr(logic_loader, "LOGIC_DIR", logic_dir)
    monkeypatch.setenv("LOGIC_RULES_ENABLED", "true")
    from config import Settings
    monkeypatch.setattr(logic_loader, "settings", Settings())

    assert get_logic_rules("CUSTOMS") is None


def test_loader_disabled_returns_none(monkeypatch, logic_dir):
    """Flag off → returns None without touching filesystem."""
    monkeypatch.setattr(logic_loader, "LOGIC_DIR", logic_dir)
    # Flag defaults to false — don't set LOGIC_RULES_ENABLED
    from config import Settings
    monkeypatch.setattr(logic_loader, "settings", Settings())

    assert get_logic_rules("VAT") is None


def test_utf8_georgian_content(monkeypatch, tmp_path):
    """Georgian Markdown content loads correctly."""
    geo_file = tmp_path / "income_tax_rules.md"
    geo_file.write_text("## საშემოსავლო გადასახადი\nგანაკვეთი: 20%", encoding="utf-8")
    monkeypatch.setattr(logic_loader, "LOGIC_DIR", tmp_path)
    monkeypatch.setenv("LOGIC_RULES_ENABLED", "true")
    from config import Settings
    monkeypatch.setattr(logic_loader, "settings", Settings())

    result = get_logic_rules("INCOME_TAX")
    assert "საშემოსავლო" in result
    assert "20%" in result


def test_empty_file_returns_empty_string(monkeypatch, tmp_path):
    """Empty .md file returns '' (not None) — file exists but no content."""
    empty_file = tmp_path / "general_rules.md"
    empty_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(logic_loader, "LOGIC_DIR", tmp_path)
    monkeypatch.setenv("LOGIC_RULES_ENABLED", "true")
    from config import Settings
    monkeypatch.setattr(logic_loader, "settings", Settings())

    result = get_logic_rules("GENERAL")
    assert result == ""


def test_clear_cache_resets_state(monkeypatch, logic_dir):
    """clear_cache() forces re-read on next call."""
    monkeypatch.setattr(logic_loader, "LOGIC_DIR", logic_dir)
    monkeypatch.setenv("LOGIC_RULES_ENABLED", "true")
    from config import Settings
    monkeypatch.setattr(logic_loader, "settings", Settings())

    get_logic_rules("VAT")
    assert "VAT" in logic_loader._cache

    clear_cache()
    assert "VAT" not in logic_loader._cache


# ─── Bug #2: Path traversal guard ───────────────────────────────────────────


def test_path_traversal_blocked(monkeypatch, logic_dir):
    """Bug #2: Domain '../../etc/passwd' must return None (path escapes LOGIC_DIR)."""
    monkeypatch.setattr(logic_loader, "LOGIC_DIR", logic_dir)
    monkeypatch.setenv("LOGIC_RULES_ENABLED", "true")
    from config import Settings
    monkeypatch.setattr(logic_loader, "settings", Settings())

    result = get_logic_rules("../../etc/passwd")
    assert result is None
    assert "../../etc/passwd" not in logic_loader._cache


# ─── Bug #4: Cache poisoning guard ──────────────────────────────────────────


def test_missing_file_not_cached(monkeypatch, logic_dir):
    """Bug #4: Missing domain file should NOT be cached as None."""
    monkeypatch.setattr(logic_loader, "LOGIC_DIR", logic_dir)
    monkeypatch.setenv("LOGIC_RULES_ENABLED", "true")
    from config import Settings
    monkeypatch.setattr(logic_loader, "settings", Settings())

    result = get_logic_rules("NONEXISTENT")
    assert result is None
    assert "NONEXISTENT" not in logic_loader._cache
