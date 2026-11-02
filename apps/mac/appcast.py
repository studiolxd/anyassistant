"""The appcast.xml of a version (apps/release.sh): what the installed Macs' Sparkle reads, from the
latest release (their SUFeedURL), to offer it with its notes and one click.

    python3 apps/mac/appcast.py <notes.md> <tag> <version> <build> '<sign_update's output>' <appcast.xml>

The notes (docs/versiones/<tag>.md) go as simple HTML: headings, paragraphs, lists, **bold**, `code`.
"""

import email.utils
import html
import re
import sys


def notes_html(markdown: str) -> str:
    body, listing = [], False
    for raw in markdown.splitlines():
        line = raw.strip()
        item = line.startswith("- ")
        text = html.escape(line[2:] if item else line.lstrip("#").strip())
        text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        if item:
            body.append(("" if listing else "<ul>") + f"<li>{text}</li>")
            listing = True
            continue
        if listing:
            body.append("</ul>")
            listing = False
        if line.startswith("#"):
            body.append(f"<h3>{text}</h3>")
        elif text:
            body.append(f"<p>{text}</p>")
    if listing:
        body.append("</ul>")
    return "".join(body)


def appcast(notes: str, tag: str, version: str, build: str, signed: str) -> str:
    url = f"https://github.com/studiolxd/anyassistant/releases/download/{tag}/AnyAssistant-{version}-mac.dmg"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>AnyAssistant</title>
    <item>
      <title>AnyAssistant {version}</title>
      <pubDate>{email.utils.formatdate()}</pubDate>
      <sparkle:version>{build}</sparkle:version>
      <sparkle:shortVersionString>{version}</sparkle:shortVersionString>
      <sparkle:minimumSystemVersion>14.0</sparkle:minimumSystemVersion>
      <description><![CDATA[{notes_html(notes)}]]></description>
      <enclosure url="{url}" {signed.strip()} type="application/octet-stream"/>
    </item>
  </channel>
</rss>
"""


if __name__ == "__main__":
    notes, tag, version, build, signed, out = sys.argv[1:]
    with open(notes, encoding="utf-8") as f:
        text = f.read()
    with open(out, "w", encoding="utf-8") as f:
        f.write(appcast(text, tag, version, build, signed))
