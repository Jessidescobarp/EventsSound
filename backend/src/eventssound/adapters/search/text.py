"""Spanish text folding and tokenization shared by every search adapter."""

import re
import unicodedata

from eventssound.adapters.search.synonyms import CANONICAL

_TOKEN = re.compile(r"[^\W_]+")
_SPACES = re.compile(r"\s+")

STOPWORDS = frozenset(
    [
        "a",
        "al",
        "con",
        "de",
        "del",
        "el",
        "en",
        "la",
        "las",
        "lo",
        "los",
        "o",
        "para",
        "por",
        "que",
        "se",
        "sin",
        "sobre",
        "su",
        "sus",
        "un",
        "una",
        "unos",
        "unas",
        "y",
        "es",
        "hay",
        "tengo",
        "tienen",
        "necesito",
        "necesitamos",
        "quiero",
        "quisiera",
        "busco",
        "mi",
        "mis",
        "me",
        "este",
        "esta",
        "ese",
        "esa",
        "como",
        "muy",
        "mas",
        "entre",
    ]
)


def normalize(text: str) -> str:
    """NFKC, invisible characters removed, case and accents folded, whitespace collapsed."""
    kept: list[str] = []
    for char in unicodedata.normalize("NFKC", text):
        category = unicodedata.category(char)
        if category == "Cf" or (category == "Cc" and not char.isspace()):
            continue
        kept.append(char)
    folded = unicodedata.normalize("NFD", "".join(kept).casefold())
    return _SPACES.sub(
        " ", "".join(c for c in folded if not unicodedata.category(c).startswith("M"))
    ).strip()


def stem(word: str) -> str:
    """Light Spanish plural rule: `luces` -> `luz`, `parlantes` -> `parlante`."""
    if len(word) > 4 and word.endswith("ces"):
        return word[:-3] + "z"
    if len(word) > 5 and word.endswith(("ores", "ones", "iles", "ales")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokens(text: str) -> tuple[str, ...]:
    """Meaningful tokens in order: stopwords dropped, plurals stemmed, synonyms made canonical."""
    result = []
    for word in _TOKEN.findall(normalize(text)):
        if word in STOPWORDS:
            continue
        stemmed = stem(word)
        result.append(CANONICAL.get(stemmed, stemmed))
    return tuple(result)
