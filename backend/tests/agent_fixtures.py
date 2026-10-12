"""A small in-test catalog for search and tool tests (6 items, 2 packages)."""

from eventssound.domain.catalog import (
    Catalog,
    EquipmentCategory,
    EquipmentItem,
    PackageLine,
    ServicePackage,
)
from eventssound.domain.money import Money

SOUND, LIGHT = EquipmentCategory.SOUND, EquipmentCategory.LIGHTING
DJ, FX = EquipmentCategory.DJ, EquipmentCategory.EFFECTS


def make_catalog() -> Catalog:
    return Catalog(
        items=(
            EquipmentItem(
                "sound_speaker_15", "Parlante activo de 15 pulgadas", SOUND, 3, Money(80_000)
            ),
            EquipmentItem(
                "sound_wireless_mic", "Micrófono inalámbrico de mano", SOUND, 12, Money(35_000)
            ),
            EquipmentItem(
                "sound_mixer_16", "Consola digital de 16 canales", SOUND, 3, Money(180_000)
            ),
            EquipmentItem("light_led_par", "Luz LED PAR RGB", LIGHT, 24, Money(25_000)),
            EquipmentItem("dj_controller", "Controlador DJ de 4 canales", DJ, 3, Money(200_000)),
            EquipmentItem("fx_fog_machine", "Máquina de humo", FX, 5, Money(55_000)),
        ),
        packages=(
            ServicePackage(
                "pkg_party",
                "Paquete Fiesta",
                (
                    PackageLine("sound_speaker_15", 2),
                    PackageLine("sound_wireless_mic", 1),
                    PackageLine("light_led_par", 6),
                ),
                500,
            ),
            ServicePackage(
                "pkg_dj",
                "Paquete DJ",
                (PackageLine("dj_controller", 1), PackageLine("sound_speaker_15", 2)),
                0,
            ),
        ),
    )
