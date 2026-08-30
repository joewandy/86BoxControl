from pathlib import Path

from PIL import Image

from retrobridge.windows_launcher import ICON_SIZES, render_icon, write_icon


def test_launcher_mark_is_full_resolution_rgba() -> None:
    image = render_icon()
    assert image.mode == "RGBA"
    assert image.size == (256, 256)
    assert image.getbbox() is not None


def test_windows_icon_contains_expected_resolutions(tmp_path: Path) -> None:
    destination = tmp_path / "retrobridge98.ico"
    write_icon(destination)
    with Image.open(destination) as icon:
        assert icon.format == "ICO"
        assert set(icon.info["sizes"]) == {(size, size) for size in ICON_SIZES}
