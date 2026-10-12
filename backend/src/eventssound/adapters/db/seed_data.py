"""Synthetic seed definitions: plain domain values, no database access.

All data is invented. Codes are English slugs (stable upsert keys); display names are Spanish.
Prices are whole COP pesos per rental day. To grow the demo catalog, edit this module only.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from eventssound.domain.availability import Booking, BookingStatus
from eventssound.domain.catalog import EquipmentCategory, EquipmentItem, PackageLine, ServicePackage
from eventssound.domain.money import Money

_BOGOTA = ZoneInfo("America/Bogota")
_SOUND, _LIGHT, _DJ = EquipmentCategory.SOUND, EquipmentCategory.LIGHTING, EquipmentCategory.DJ
_STAGE, _FX, _VIDEO = EquipmentCategory.STAGE, EquipmentCategory.EFFECTS, EquipmentCategory.VIDEO


def _item(code: str, name: str, category: EquipmentCategory, stock: int, price: int):
    return EquipmentItem(code, name, category, stock, Money(price))


def _package(code: str, name: str, discount_bps: int, *lines: tuple[str, int]) -> ServicePackage:
    return ServicePackage(code, name, tuple(PackageLine(c, q) for c, q in lines), discount_bps)


SEED_ITEMS: tuple[EquipmentItem, ...] = (
    _item("sound_active_speaker_12", "Parlante activo de 12 pulgadas", _SOUND, 12, 60_000),
    _item("sound_active_speaker_15", "Parlante activo de 15 pulgadas", _SOUND, 10, 80_000),
    _item("sound_subwoofer_18", "Subwoofer activo de 18 pulgadas", _SOUND, 6, 120_000),
    _item("sound_line_array_module", "Módulo line array", _SOUND, 16, 150_000),
    _item("sound_stage_monitor", "Monitor de piso", _SOUND, 8, 50_000),
    _item("sound_mixer_16ch", "Consola digital de 16 canales", _SOUND, 3, 180_000),
    _item("sound_wireless_mic", "Micrófono inalámbrico de mano", _SOUND, 12, 35_000),
    _item("light_led_par", "Luz LED PAR RGB", _LIGHT, 24, 25_000),
    _item("light_moving_head_spot", "Cabeza móvil spot", _LIGHT, 8, 90_000),
    _item("light_moving_head_wash", "Cabeza móvil wash", _LIGHT, 8, 85_000),
    _item("light_strobe", "Luz estroboscópica", _LIGHT, 4, 40_000),
    _item("light_dmx_controller", "Controlador DMX", _LIGHT, 3, 70_000),
    _item("dj_controller", "Controlador DJ de 4 canales", _DJ, 3, 200_000),
    _item("dj_cdj_pair", "Par de reproductores CDJ", _DJ, 2, 350_000),
    _item("dj_mixer", "Mezclador DJ profesional", _DJ, 2, 220_000),
    _item("stage_platform_2x1", "Tarima modular de 2 x 1 metros", _STAGE, 20, 45_000),
    _item("stage_access_stairs", "Escalera de acceso a tarima", _STAGE, 4, 30_000),
    _item("fx_fog_machine", "Máquina de humo", _FX, 5, 55_000),
    _item("fx_cold_spark", "Fuente de chispas frías", _FX, 3, 180_000),
    _item("video_led_screen_3x2", "Pantalla LED de 3 x 2 metros", _VIDEO, 2, 900_000),
)

SEED_PACKAGES: tuple[ServicePackage, ...] = (
    _package(
        "pkg_basic_party",
        "Paquete Fiesta Básica",
        500,
        ("sound_active_speaker_12", 2),
        ("sound_wireless_mic", 1),
        ("light_led_par", 6),
        ("dj_controller", 1),
        ("fx_fog_machine", 1),
    ),
    _package(
        "pkg_wedding",
        "Paquete Boda",
        1000,
        ("sound_active_speaker_15", 2),
        ("sound_subwoofer_18", 1),
        ("sound_wireless_mic", 2),
        ("light_led_par", 8),
        ("light_moving_head_wash", 4),
        ("stage_platform_2x1", 4),
    ),
    _package(
        "pkg_corporate",
        "Paquete Evento Corporativo",
        800,
        ("sound_line_array_module", 4),
        ("sound_mixer_16ch", 1),
        ("sound_wireless_mic", 3),
        ("stage_platform_2x1", 6),
        ("stage_access_stairs", 1),
        ("video_led_screen_3x2", 1),
    ),
    _package(
        "pkg_dj_night",
        "Paquete Noche DJ",
        1500,
        ("dj_cdj_pair", 1),
        ("dj_mixer", 1),
        ("sound_active_speaker_15", 2),
        ("sound_subwoofer_18", 2),
        ("light_moving_head_spot", 4),
        ("light_strobe", 2),
    ),
)


def _booking(code: str, item: str, quantity: int, start: tuple, end: tuple, status: BookingStatus):
    return Booking(
        code,
        item,
        quantity,
        datetime(*start, tzinfo=_BOGOTA),
        datetime(*end, tzinfo=_BOGOTA),
        status,
    )


_CONFIRMED, _PENDING, _CANCELLED = (
    BookingStatus.CONFIRMED,
    BookingStatus.PENDING,
    BookingStatus.CANCELLED,
)

# Demo reservations that make availability interesting on Saturday 2026-11-14 and 2026-11-21.
# Codes start with DEMO- and are the upsert keys together with the item code.
SEED_BOOKINGS: tuple[Booking, ...] = (
    _booking(
        "DEMO-001", "sound_active_speaker_12", 4, (2026, 11, 14, 18), (2026, 11, 14, 23), _CONFIRMED
    ),
    _booking("DEMO-001", "light_led_par", 10, (2026, 11, 14, 18), (2026, 11, 14, 23), _CONFIRMED),
    _booking("DEMO-002", "dj_controller", 1, (2026, 11, 14, 14), (2026, 11, 14, 20), _PENDING),
    _booking(
        "DEMO-003", "sound_active_speaker_12", 6, (2026, 11, 14, 18), (2026, 11, 14, 23), _CANCELLED
    ),
    _booking(
        "DEMO-004", "stage_platform_2x1", 8, (2026, 11, 21, 12), (2026, 11, 21, 20), _CONFIRMED
    ),
)
