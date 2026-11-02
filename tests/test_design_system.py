"""The design system (plugins/page/web/tokens.css): the tokens and components of the pages around
the face (themes, the web admin, pairing, the QR page), and those pages using only them."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "plugins/page/web"
TOKENS = (WEB / "tokens.css").read_text()
PAGES = {
    "themes": ROOT / "plugins/themes/themes.html",
    "admin": ROOT / "plugins/admin/web/index.html",
    "device": WEB / "index.html",
    "connect": WEB / "connect.html",
}
STYLESHEETS = [ROOT / "plugins/themes/themes.css", ROOT / "plugins/admin/web/admin.css"]


def without_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def declared(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", block))


def test_the_tokens_are_there_dark_only():
    """Dark only: the brand's blue (the logo's, Eyes') the same everywhere."""
    css = without_comments(TOKENS)
    assert "prefers-color-scheme" not in css
    dark = declared(css.split("/* --- Components")[0] if "/* --- Components" in css else css.split(".ui")[0])
    assert dark["--color-primary"] == "#34AFF7"
    colours = ["primary", "primary-text", "background", "surface", "surface-raised", "border", "text",
               "text-secondary", "success", "warning", "danger"]
    assert all(f"--color-{c}" in dark for c in colours)
    others = ["--font-family", "--font-mono", "--weight-regular", "--weight-medium", "--weight-semibold",
              "--shadow", "--duration", "--easing", "--content-width"]
    others += [f"--text-{s}" for s in ("xs", "sm", "md", "lg", "xl", "2xl", "code")]
    others += [f"--space-{n}" for n in range(1, 9)] + [f"--radius-{r}" for r in ("sm", "md", "lg", "full")]
    assert all(name in dark for name in others), [n for n in others if n not in dark]
    assert [dark[f"--space-{n}"] for n in range(1, 9)] == ["4px", "8px", "12px", "16px", "20px", "24px", "32px", "48px"]


def test_the_components_apply_only_inside_ui():
    """The device's page also shows a theme (someone else's HTML): .card, .row… must stay its own."""
    css = without_comments(TOKENS)
    components = css[css.index("}", css.index(":root")) + 1:]  # after the tokens
    selectors = [x for x in re.findall(r"([^{}]+)\{", components) if not x.strip().startswith("@media")]
    assert selectors
    for group in selectors:
        for selector in group.split(","):
            assert selector.strip().startswith((".ui", "body.ui")), selector
    for name in ("button", "secondary", "danger", "link", "field", "card", "row", "segmented", "badge", "header"):
        assert f".{name}" in components, name


def test_every_page_links_the_tokens_first():
    for name, page in PAGES.items():
        html = page.read_text()
        sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
        assert sheets and re.fullmatch(r"/web/tokens\.css\?v=\d+", sheets[0]), name
        assert html.index(sheets[0]) < (html.index("<style>") if "<style>" in html else len(html)), name


def test_the_logo_is_on_every_page():
    for name, page in PAGES.items():
        html = page.read_text()
        assert re.search(r'<img class="logo( large)?" src="/web/logo.png"', html), name
    assert 'class="ui centered"' in PAGES["device"].read_text()  # the pairing panel, not the theme's screen


def test_the_pages_use_tokens_not_their_own_colours():
    """Only the face's black (behind a view of it, a screenshot) and the QR's and the switch's white."""
    system = (WEB / "system.css").read_text()
    pairing = system[system.index("#pair {"):system.index("/* Settings show_time")]
    for css in [p.read_text() for p in STYLESHEETS] + [pairing]:
        colours = set(re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", without_comments(css)))
        assert colours <= {"#000", "#fff"}, colours


def test_old_chrome_can_read_what_the_device_page_loads():
    """Chrome 81 (the oldest tablets) has no `inset` and no flex `gap`."""
    for css in (TOKENS, (WEB / "system.css").read_text()):
        css = without_comments(css)
        assert not re.search(r"(^|[;{\s])inset\s*:", css)
        assert not re.search(r"(^|[;{\s])gap\s*:", css)
        assert "color-mix" not in css



# The pages and what writes their HTML: no styles of their own inside them; everything from the
# design system's components (tokens.css) or the page's stylesheet with tokens. Computed geometry
# set from code (element.style.top = …) is allowed: it can't be CSS.
WRITERS = list(PAGES.values()) + [ROOT / "plugins/page/__init__.py", ROOT / "plugins/admin/web/admin.js",
                                  ROOT / "plugins/themes/themes.js", WEB / "app.js"]
INLINE = [(r"<style[\s>]", "a <style> block"), (r"""\bstyle\s*=\s*["'{]""", "a style attribute"),
          (r"""\bstyle\s*:\s*['"]""", "a style in el(…)"), (r"\.cssText\b", "style.cssText"),
          (r"""setAttribute\(\s*['"]style['"]""", "setAttribute('style')")]


def test_no_page_writes_styles_of_its_own():
    found = [f"{path.relative_to(ROOT)}: {what}" for path in WRITERS for pattern, what in INLINE
             if re.search(pattern, path.read_text())]
    assert not found, "use the design system's components (tokens.css) instead: " + "; ".join(found)
