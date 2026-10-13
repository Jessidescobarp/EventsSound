"""A small in-test catalog for search and tool tests (6 items, 2 packages)."""

from datetime import timedelta

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


def neutral_rules():
    """Every adjustment off and no rounding: the quote is just the equipment subtotal."""
    import dataclasses

    from eventssound.domain.pricing_rules import (
        DistanceBand,
        GuestTier,
        default_pricing_rules,
    )

    values = {
        "guest_tiers": (GuestTier(1, 0),),
        "weekend_holiday_surcharge_bps": 0,
        "night": dataclasses.replace(default_pricing_rules().night, surcharge_bps=0),
        "distance_bands": (DistanceBand(None, Money(0)),),
        "rounding_step": 1,
    }
    return dataclasses.replace(default_pricing_rules(), **values)


def make_deps(provider, *, catalog=None, search=None, bookings=(), **overrides):
    """A full AgentDeps over the in-test catalog: keyword search, no bookings, neutral pricing."""
    from zoneinfo import ZoneInfo

    from eventssound.adapters.agent.nodes import AgentDeps
    from eventssound.adapters.search.keyword import KeywordSearch
    from eventssound.application.quote_chat import ChatLimits
    from eventssound.domain.availability import AvailabilityRules, check_request_availability
    from eventssound.domain.pricing import calculate_price

    catalog = catalog or make_catalog()
    rules = neutral_rules()

    def load_catalog():
        return catalog

    def check_availability(request):
        return check_request_availability(
            request, catalog, bookings, AvailabilityRules(timedelta(0))
        )

    def price(request):
        return calculate_price(request, catalog, rules)

    values = dict(
        provider=provider,
        search=search or KeywordSearch(catalog),
        load_catalog=load_catalog,
        check_availability=check_availability,
        price=price,
        limits=ChatLimits(),
        timezone=ZoneInfo("America/Bogota"),
        scenario=None,
        token_factory=lambda: "abcdef0123456789",
    )
    values.update(overrides)
    return AgentDeps(**values)
