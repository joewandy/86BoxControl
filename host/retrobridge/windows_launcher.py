"""Windows launcher artwork generated as a reproducible multi-size icon."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _pixel_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    origin: tuple[int, int],
    *,
    scale: int,
    fill: str,
) -> None:
    glyphs = {
        "8": ("111", "101", "101", "111", "101", "101", "111"),
        "9": ("111", "101", "101", "111", "001", "001", "111"),
    }
    x, y = origin
    for character in text:
        glyph = glyphs[character]
        for row, pixels in enumerate(glyph):
            for column, pixel in enumerate(pixels):
                if pixel == "1":
                    draw.rectangle(
                        (
                            x + column * scale,
                            y + row * scale,
                            x + (column + 1) * scale - 1,
                            y + (row + 1) * scale - 1,
                        ),
                        fill=fill,
                    )
        x += 4 * scale


def render_icon() -> Image.Image:
    """Render the 256px RetroBridge CRT-and-bridge application mark."""

    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((20, 24, 238, 242), radius=48, fill="#07132166")
    draw.rounded_rectangle(
        (12, 12, 230, 230),
        radius=48,
        fill="#102942",
        outline="#58D6D0",
        width=8,
    )

    # Chunky CRT silhouette, kept bold enough to remain legible at 16px.
    draw.rounded_rectangle(
        (42, 44, 200, 166),
        radius=19,
        fill="#E9E2C6",
        outline="#06111E",
        width=7,
    )
    draw.rounded_rectangle((57, 59, 185, 144), radius=11, fill="#071A27")
    draw.rectangle((103, 165, 139, 190), fill="#E9E2C6")
    draw.rounded_rectangle((72, 185, 170, 203), radius=8, fill="#E9E2C6")

    # A suspension bridge across the screen: two worlds joined by one span.
    bridge = "#FFB84D"
    draw.line((70, 123, 70, 82), fill=bridge, width=7)
    draw.line((172, 123, 172, 82), fill=bridge, width=7)
    draw.line((65, 123, 177, 123), fill=bridge, width=7)
    draw.arc((68, 70, 174, 137), start=185, end=355, fill=bridge, width=6)
    for x, top in ((84, 101), (101, 111), (121, 115), (141, 111), (158, 101)):
        draw.line((x, top, x, 123), fill=bridge, width=3)
    draw.ellipse((58, 112, 76, 130), fill="#60E58B")
    draw.ellipse((166, 112, 184, 130), fill="#60E58B")

    _pixel_text(draw, "98", (169, 174), scale=5, fill="#58D6D0")
    return image


def write_icon(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    render_icon().save(path, format="ICO", sizes=[(size, size) for size in ICON_SIZES])


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate RetroBridge98 Windows artwork")
    parser.add_argument("output", type=Path, help="destination .ico path")
    args = parser.parse_args()
    write_icon(args.output)


if __name__ == "__main__":
    main()
