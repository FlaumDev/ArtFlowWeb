from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = PROJECT_ROOT / "static" / "images"
WEBP_QUALITY = 84


def convert_webp(source_name: str, target_name: str, max_width: int) -> None:
    source = IMAGE_ROOT / source_name
    target = IMAGE_ROOT / target_name
    temporary = target.with_name(f".{target.name}.tmp")

    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        if image.width > max_width:
            height = round(image.height * max_width / image.width)
            image = image.resize(
                (max_width, height),
                Image.Resampling.LANCZOS,
            )
        image.save(
            temporary,
            format="WEBP",
            quality=WEBP_QUALITY,
            method=6,
        )

    temporary.replace(target)


def main() -> None:
    primary_images = (
        ("hero-main.webp", "hero-main.webp", 1600),
        ("hero-secondary.webp", "hero-secondary.webp", 1200),
        ("about-project.webp", "about-project.webp", 1600),
        ("gallery-01.webp", "gallery-01.webp", 1400),
        ("gallery-02.webp", "gallery-02.webp", 1400),
        ("gallery-03.webp", "gallery-03.webp", 1400),
        ("gallery-04.webp", "gallery-04.webp", 1400),
        ("gallery-05.webp", "gallery-05.webp", 1400),
        ("gallery-06.webp", "gallery-06.webp", 1400),
        ("organizer_1.png", "organizer-1.webp", 800),
        ("organizer_2.png", "organizer-2.webp", 800),
    )
    responsive_images = (
        ("hero-main.webp", "hero-main-960.webp", 960),
        ("hero-secondary.webp", "hero-secondary-720.webp", 720),
        ("about-project.webp", "about-project-960.webp", 960),
        ("gallery-01.webp", "gallery-01-800.webp", 800),
        ("gallery-02.webp", "gallery-02-800.webp", 800),
        ("gallery-03.webp", "gallery-03-800.webp", 800),
        ("gallery-04.webp", "gallery-04-800.webp", 800),
        ("gallery-05.webp", "gallery-05-800.webp", 800),
        ("gallery-06.webp", "gallery-06-800.webp", 800),
        ("organizer-1.webp", "organizer-1-480.webp", 480),
        ("organizer-2.webp", "organizer-2-480.webp", 480),
    )

    for image_spec in primary_images:
        convert_webp(*image_spec)
    for image_spec in responsive_images:
        convert_webp(*image_spec)


if __name__ == "__main__":
    main()
