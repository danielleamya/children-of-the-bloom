from pathlib import Path

from PIL import Image

LOGOS = Path(__file__).resolve().parents[1] / "assets" / "logos"


def crop_to_alpha(img: Image.Image, pad: int = 8) -> Image.Image:
    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    if not bbox:
        return img
    left, top, right, bottom = bbox
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(img.width, right + pad)
    bottom = min(img.height, bottom + pad)
    return img.crop((left, top, right, bottom))


def museum_to_white(src: Path, dest: Path) -> None:
    """Pink wordmark on navy -> white wordmark on transparent."""
    img = Image.open(src).convert("RGBA")
    out = []
    for r, g, b, _a in img.getdata():
        # Keep vivid / bright logo pixels; drop dark navy background.
        chroma = max(r, g, b) - min(r, g, b)
        brightness = max(r, g, b)
        if chroma < 40 and brightness < 90:
            out.append((255, 255, 255, 0))
            continue
        strength = max(chroma, brightness - 40)
        alpha = max(0, min(255, int(round(strength * 1.35))))
        out.append((255, 255, 255, alpha))
    result = Image.new("RGBA", img.size)
    result.putdata(out)
    result = crop_to_alpha(result)
    result.save(dest)
    print(f"{src.name} -> {dest.name} size={result.size}")


def new_inc_to_white(src: Path, dest: Path) -> None:
    """Black wordmark on white -> white wordmark on transparent."""
    img = Image.open(src).convert("RGBA")
    out = []
    for r, g, b, _a in img.getdata():
        # Dark ink becomes white alpha; light paper becomes transparent.
        darkness = 255 - max(r, g, b)
        if darkness < 18:
            out.append((255, 255, 255, 0))
            continue
        alpha = max(0, min(255, int(round(darkness * 1.15))))
        out.append((255, 255, 255, alpha))
    result = Image.new("RGBA", img.size)
    result.putdata(out)
    result = crop_to_alpha(result)
    result.save(dest)
    print(f"{src.name} -> {dest.name} size={result.size}")


def main() -> None:
    museum_to_white(LOGOS / "new-museum.webp", LOGOS / "new-museum-white.png")
    new_inc_to_white(LOGOS / "new-inc.avif", LOGOS / "new-inc-white.png")


if __name__ == "__main__":
    main()
