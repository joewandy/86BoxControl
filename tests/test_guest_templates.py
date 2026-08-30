from pathlib import Path


ROOT = Path(__file__).parents[1]
WINDOWS98 = ROOT / "guest" / "windows98"
DOS_LAUNCHERS = ROOT / "guest" / "dos" / "launchers"


def test_shortcut_creator_reads_user_manifest() -> None:
    source = (WINDOWS98 / "CREATE-SHORTCUTS.VBS").read_text(encoding="ascii")
    example = (WINDOWS98 / "SHORTCUTS.EXAMPLE.TXT").read_text(encoding="ascii")
    assert 'SourcePath(sourceDir, "SHORTCUTS.TXT")' in source
    assert "Title|Target|Working directory|Arguments|File that must exist" in example
    assert "Norton Commander" not in source
    assert "WordPerfect" not in source


def test_shortcut_organizer_reads_user_categories() -> None:
    source = (WINDOWS98 / "ORGANIZE-SHORTCUTS.VBS").read_text(encoding="ascii")
    example = (WINDOWS98 / "CATEGORIES.EXAMPLE.TXT").read_text(encoding="ascii")
    assert 'SourcePath(sourceDir, "CATEGORIES.TXT")' in source
    assert "Category|case-insensitive keyword|additional keyword" in example
    assert 'WriteText "C:\\' not in source
    assert "FoxPro" not in source


def test_collection_workflow_is_configuration_driven() -> None:
    config = (WINDOWS98 / "COLLECTION.EXAMPLE.CFG").read_text(encoding="ascii")
    for key in (
        "SourceFolder",
        "TargetRoot",
        "FileExtension",
        "ExpectedCount",
        "Markers",
        "ShortcutName",
    ):
        assert f"{key}=" in config

    copy = (WINDOWS98 / "COPY-COLLECTION-FROM-CD.VBS").read_text(encoding="ascii")
    verify = (WINDOWS98 / "VERIFY-COLLECTION.VBS").read_text(encoding="ascii")
    result = (WINDOWS98 / "WRITE-COLLECTION-RESULT.VBS").read_text(encoding="ascii")
    assert 'cdRoot & "COLLECT.CFG"' in copy
    assert 'fso.CopyFile sourceRoot & "\\*"' in copy
    assert 'fso.CopyFolder sourceRoot & "\\*"' in copy
    assert 'SourcePath(sourceDir, "COLLECT.CFG")' in verify
    assert 'SourcePath(sourceDir, "COLLECT.CFG")' in result
    assert "Not DigitsOnly(expectedCountText)" in verify
    assert "Not DigitsOnly(expectedCountText)" in result
    assert 'resultFile.WriteLine "file_count="' in result
    assert "ExpectedCount = 157" not in verify + result
    assert "MP3_80S" not in verify + result


def test_dos_launcher_is_an_adaptable_template() -> None:
    template = (DOS_LAUNCHERS / "APPLICATION.BAT").read_text(encoding="ascii")
    assert "replace APP and APP.EXE" in template
    assert not (DOS_LAUNCHERS / "DBASE3.BAT").exists()
    assert not (DOS_LAUNCHERS / "LOTUS123.BAT").exists()
    assert not (DOS_LAUNCHERS / "WORDSTAR.BAT").exists()


def test_provenance_contains_no_personal_absolute_path() -> None:
    provenance = (ROOT / "docs" / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "/Users/" not in provenance
    assert "Documents/Codex" not in provenance
