"""Python half of the runpod/browser checks; see check.sh.

    python browser_check.py screenshot <url> <out.png>
    python browser_check.py fonts <out.png>
    python browser_check.py png <file.png> [<file.png> ...]
"""

import struct
import sys

from playwright.sync_api import sync_playwright

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(path: str) -> tuple[int, int]:
    """Width and height from the IHDR chunk; raises if it is not a PNG."""
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != PNG_SIGNATURE or head[12:16] != b"IHDR":
        raise SystemExit(f"{path}: not a PNG")
    width, height = struct.unpack(">II", head[16:24])
    if not (width and height):
        raise SystemExit(f"{path}: empty {width}x{height} image")
    return width, height


def screenshot(url: str, out: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        page.screenshot(path=out)
        browser.close()
    print(f"{out} {'x'.join(map(str, png_size(out)))}")


# Each sample has no spaces or Latin, so every glyph in it has to come from
# the fonts listed — a fallback to anything else is a tofu box or Unifont's
# bitmap glyphs, neither of which belongs in a screenshot.
SAMPLES = {
    "ja": ("日本語の表示確認", ("IPA", "WenQuanYi")),
    "zh-CN": ("简体中文显示测试", ("WenQuanYi",)),
    "zh-TW": ("繁體中文顯示測試", ("WenQuanYi",)),
    "ko": ("한국어표시확인", ("WenQuanYi",)),
    "emoji": ("😀🚀🎉👍🏽🇯🇵", ("Noto Color Emoji",)),
}


def fonts(out: str) -> None:
    body = "".join(
        f'<p id="s{i}" lang="{lang}">{text}</p>'
        for i, (lang, (text, _)) in enumerate(SAMPLES.items())
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(f'<html><body style="font-size:32px">{body}</body></html>')
        page.screenshot(path=out, full_page=True)

        # Ask Chromium which platform fonts actually rendered each node,
        # rather than trusting fontconfig to pick what we expect.
        cdp = page.context.new_cdp_session(page)
        cdp.send("DOM.enable")
        cdp.send("CSS.enable")
        root = cdp.send("DOM.getDocument")["root"]["nodeId"]
        failed = False
        for i, (lang, (_, allowed)) in enumerate(SAMPLES.items()):
            node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": f"#s{i}"})
            used = cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node["nodeId"]})["fonts"]
            names = sorted({f["familyName"] for f in used})
            bad = [n for n in names if not n.startswith(allowed)]
            print(f"  {lang:<6} {', '.join(names)}{'  <-- unexpected' if bad else ''}")
            failed |= bool(bad) or not names
        browser.close()
    png_size(out)
    if failed:
        raise SystemExit("some text fell back to a font that cannot render it")


def main() -> None:
    cmd, *args = sys.argv[1:]
    if cmd == "screenshot":
        screenshot(*args)
    elif cmd == "fonts":
        fonts(*args)
    elif cmd == "png":
        for path in args:
            print(f"{path} {'x'.join(map(str, png_size(path)))}")
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
