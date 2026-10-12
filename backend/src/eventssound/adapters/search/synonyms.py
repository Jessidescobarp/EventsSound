"""Spanish synonym groups and category names for keyword search.

Members are stored in normalized AND stemmed form (a test enforces it), so `luces` and `luz`
land on the same token. All catalog names are invented; extend the groups when the catalog grows.
"""

from eventssound.application.search import CATEGORY_ES  # noqa: F401  (re-exported)

SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("parlante", "altavoz", "bocina", "bafle", "speaker"),
    ("luz", "iluminacion", "lampara"),
    ("microfono", "mic", "microphone"),
    ("consola", "mezcladora", "mezclador", "mixer"),
    ("humo", "neblina", "fog", "smoke"),
    ("tarima", "escenario", "tablado", "plataforma", "platform"),
    ("subwoofer", "sub", "woofer"),
    ("cabeza", "head"),
    ("movil", "moving"),
    ("inalambrico", "wireless"),
    ("estroboscopica", "estrobo", "strobe"),
    ("controlador", "controller"),
    ("chispa", "spark"),
    ("fria", "frio", "cold"),
    ("escalera", "escalon", "stair"),
    ("pantalla", "screen"),
    ("reproductor", "player"),
    ("canal", "channel"),
    ("fiesta", "party"),
)

CANONICAL: dict[str, str] = {word: group[0] for group in SYNONYM_GROUPS for word in group}
