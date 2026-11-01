"""Pure text helpers for ForumIssues. No Red imports, so `python text.py` runs the self-check."""
import re

DISCORD_LIMIT = 2000


def quote(text: str) -> str:
    return "> " + text.replace("\r\n", "\n").strip().replace("\n", "\n> ")


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def fit(content: str, suffix: str = "") -> str:
    """Trim content so content+suffix fits Discord's 2,000 UTF-16 unit limit, keeping suffix whole."""
    limit = DISCORD_LIMIT - utf16_len(suffix)
    if utf16_len(content) <= limit:
        return content + suffix
    units = 0
    for i, ch in enumerate(content):
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > limit - 1:
            return content[:i] + "…" + suffix
    return content + suffix


def safe_filename(name: str) -> str:
    """One plain repository path segment."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


_MD = str.maketrans({"\\": "\\\\", "[": "\\[", "]": "\\]", "`": "\\`", "*": "\\*", "_": "\\_",
                     "<": "&lt;", ">": "&gt;", "\n": " ", "\r": " "})


def md_text(name: str) -> str:
    """Escape text for a Markdown link label."""
    return name.translate(_MD)


def code_safe(name: str) -> str:
    """Text safe to place inside a single-backtick code span."""
    return name.replace("`", "").replace("\n", " ").replace("\r", " ")


def neutralize(text: str) -> str:
    """Break GitHub @mention syntax so copied Discord text never pings GitHub users or teams."""
    return text.replace("@", "@​")


def strip_mention(slug: str, text: str) -> str:
    """Remove each @slug (or @slug[bot]) mention plus a trailing comma/colon and space.
    A longer handle such as @slug-two is someone else and stays."""
    pattern = re.compile(r"(?<![\w-])@" + re.escape(slug) + r"(?:\[bot\])?([,:]?[ \t]?)",
                         re.IGNORECASE | re.ASCII)

    def repl(m: "re.Match[str]") -> str:
        nxt = m.string[m.end():m.end() + 1]
        if not m.group(1) and nxt and (nxt.isascii() and (nxt.isalnum() or nxt in "-_")):
            return m.group(0)
        return ""

    return pattern.sub(repl, text)


def mentions(slug: str, text: str) -> bool:
    return strip_mention(slug, text) != text


if __name__ == "__main__":
    assert quote("a\r\nb\n") == "> a\n> b"
    assert fit("x" * 1990, "y" * 5) == "x" * 1990 + "y" * 5
    long = fit("😀" * 1500, "!")
    assert utf16_len(long) <= DISCORD_LIMIT and long.endswith("…!"), utf16_len(long)
    assert safe_filename("../a b.png") == ".._a_b.png"
    assert md_text("a_[b]") == "a\\_\\[b\\]"
    assert strip_mention("bot", "Thanks @bot, can you") == "Thanks can you"
    assert strip_mention("bot", "@Bot[bot]: hi") == "hi"
    assert strip_mention("bot", "@bot @bot hi") == "hi"
    assert not mentions("bot", "ping @bot-two please")
    assert strip_mention("bot", "x@bot") == "x@bot"
    assert mentions("bot", "(@bot)")
    print("ok")
