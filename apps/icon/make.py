"""AnyAssistant's icon: the Eyes skin's eyes at rest (awake, idle): two wide blue ovals,
26×17, 5 apart on each side, tilted −7° and +7°, the skin's blue (#34aff7) on black. Every
app's icon is made from here:

    uv run python apps/icon/make.py

- iPhone/iPad and Apple Watch: 1024, square to the edge (the system rounds it)
- Android: the launcher icons (mipmap-*), and the notification one (drawable/ic_eyes.xml)
- the Mac app: AppIcon.icns (a rounded square with a margin, as macOS icons are)
- Windows and Linux: the app's icon (rounded square) and the tray's (only the eyes)
- the web page and /admin: their favicon
"""

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
BLUE = (0x34, 0xAF, 0xF7, 255)
BLACK = (0, 0, 0, 255)
# The skin's measures (vmin): each eye 26 × 17, 5 of margin on each side, tilted 7°.
EYE_W, EYE_H, MARGIN, TILT = 26, 17, 5, 7
SPAN = 2 * EYE_W + 2 * MARGIN  # from the left eye's edge to the right one's: 62


def eyes(size: int, width: float, background=None, rounded: float = 0.0) -> Image.Image:
    """The eyes, `width` of the image wide (0–1), on a background (None: transparent); rounded:
    a rounded square of that fraction of the image (macOS), else the whole square."""
    big = size * 4  # drawn 4× and scaled down: smooth edges
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    if background:
        draw = ImageDraw.Draw(image)
        if rounded:
            body = big * rounded
            inset = (big - body) / 2
            draw.rounded_rectangle((inset, inset, big - inset, big - inset), radius=body * 0.225, fill=background)
        else:
            draw.rectangle((0, 0, big, big), fill=background)
    unit = width * big / SPAN
    for side, angle in ((-1, TILT), (1, -TILT)):  # the left one tilted back (CSS −7°), the right forward
        cx, cy = big / 2 + side * (EYE_W / 2 + MARGIN) * unit, big / 2
        layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse((cx - EYE_W * unit / 2, cy - EYE_H * unit / 2,
                                       cx + EYE_W * unit / 2, cy + EYE_H * unit / 2), fill=BLUE)
        layer = layer.rotate(angle, resample=Image.BICUBIC, center=(cx, cy))
        image = Image.alpha_composite(image, layer)
    return image.resize((size, size), Image.LANCZOS)


def save(image: Image.Image, path: str):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    print(path, image.size[0])


def vector() -> str:
    """Android's one-colour icon (notifications, the quick settings tile): the same two ovals."""
    unit = 22 / SPAN
    shapes = []
    for side, angle in ((-1, -TILT), (1, TILT)):
        cx = 12 + side * (EYE_W / 2 + MARGIN) * unit
        rx, ry = EYE_W * unit / 2, EYE_H * unit / 2
        shapes.append(
            f'    <group android:rotation="{angle}" android:pivotX="{cx:.2f}" android:pivotY="12">\n'
            f'        <path android:fillColor="#FFFFFFFF"\n'
            f'            android:pathData="M{cx - rx:.2f},12a{rx:.2f},{ry:.2f} 0 1,0 {2 * rx:.2f},0'
            f'a{rx:.2f},{ry:.2f} 0 1,0 {-2 * rx:.2f},0Z" />\n    </group>')
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<!-- The Eyes skin\'s eyes at rest, for notifications and the quick settings tile (one colour, as\n'
            '     Android wants). Made by apps/icon/make.py. -->\n'
            '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
            '    android:width="24dp" android:height="24dp" android:viewportWidth="24" android:viewportHeight="24">\n'
            + "\n".join(shapes) + "\n</vector>\n")


def main():
    full = lambda size: eyes(size, 0.72, BLACK)  # noqa: E731 (square to the edge: the system rounds it)
    save(full(1024), "apps/ios/Assets.xcassets/AppIcon.appiconset/icon.png")
    save(full(1024), "apps/watch/Assets.xcassets/AppIcon.appiconset/icon.png")
    for folder, size in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        save(full(size), f"apps/android/app/src/main/res/mipmap-{folder}/ic_launcher.png")
    (ROOT / "apps/android/app/src/main/res/drawable/ic_eyes.xml").write_text(vector())
    print("apps/android/app/src/main/res/drawable/ic_eyes.xml")

    # Rounded squares with a margin: the Mac, and Windows' and Linux' app icon.
    framed = lambda size: eyes(size, 0.6, BLACK, rounded=0.805)  # noqa: E731
    save(framed(512), "apps/desktop/icons/icon.png")
    save(eyes(32, 0.94), "apps/desktop/icons/tray.png")  # only the eyes: on light and dark bars
    save(eyes(64, 0.94), "apps/desktop/icons/tray@2x.png")
    with tempfile.TemporaryDirectory() as folder:
        iconset = Path(folder) / "AppIcon.iconset"
        iconset.mkdir()
        for points in (16, 32, 128, 256, 512):
            framed(points).save(iconset / f"icon_{points}x{points}.png")
            framed(points * 2).save(iconset / f"icon_{points}x{points}@2x.png")
        if shutil.which("iconutil"):
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ROOT / "apps/mac/Resources/AppIcon.icns")],
                           check=True)
            print("apps/mac/Resources/AppIcon.icns")

    # The web page (and the iPad's «Add to Home Screen») and /admin.
    save(full(180), "plugins/page/web/icon.png")
    save(framed(64), "plugins/admin/web/icon.png")


if __name__ == "__main__":
    main()
