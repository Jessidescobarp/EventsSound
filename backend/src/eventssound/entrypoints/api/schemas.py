"""Response models of the public catalog API. They never expose database ids."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eventssound.application.quote_chat import AgentOutcome
from eventssound.domain.catalog import Catalog, EquipmentItem, ServicePackage

Code = Annotated[str, Field(description="Stable machine-readable identifier.")]


class CatalogItemOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: Code
    name: str = Field(description="Display name, in Spanish.")
    category: str = Field(description="One of: sound, lighting, dj, stage, effects, video, staff.")
    stock_quantity: int = Field(description="Units the company owns.")
    unit_price_cop: int = Field(description="Rental price per unit per day, in Colombian pesos.")

    @classmethod
    def from_domain(cls, item: EquipmentItem) -> "CatalogItemOut":
        return cls(
            code=item.code,
            name=item.name,
            category=item.category.value,
            stock_quantity=item.stock_quantity,
            unit_price_cop=item.unit_price.amount,
        )


class ItemsResponse(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "code": "dj_controller",
                            "name": "Controlador DJ de 4 canales",
                            "category": "dj",
                            "stock_quantity": 3,
                            "unit_price_cop": 200000,
                        },
                        {
                            "code": "fx_fog_machine",
                            "name": "Máquina de humo",
                            "category": "effects",
                            "stock_quantity": 5,
                            "unit_price_cop": 55000,
                        },
                        {
                            "code": "light_led_par",
                            "name": "Luz LED PAR RGB",
                            "category": "lighting",
                            "stock_quantity": 24,
                            "unit_price_cop": 25000,
                        },
                        {
                            "code": "sound_active_speaker_12",
                            "name": "Parlante activo de 12 pulgadas",
                            "category": "sound",
                            "stock_quantity": 12,
                            "unit_price_cop": 60000,
                        },
                        {
                            "code": "sound_wireless_mic",
                            "name": "Micrófono inalámbrico de mano",
                            "category": "sound",
                            "stock_quantity": 12,
                            "unit_price_cop": 35000,
                        },
                    ]
                }
            ]
        },
    )

    items: list[CatalogItemOut] = Field(description="Rentable equipment, ordered by code.")

    @classmethod
    def from_domain(cls, catalog: Catalog) -> "ItemsResponse":
        ordered = sorted(catalog.items, key=lambda item: item.code)
        return cls(items=[CatalogItemOut.from_domain(item) for item in ordered])


class PackageLineOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_code: Code
    quantity: int = Field(description="Units of the item included in the package.")


class ServicePackageOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: Code
    name: str = Field(description="Display name, in Spanish.")
    discount_bps: int = Field(description="Package discount in basis points (500 = 5%).")
    base_price_cop: int = Field(
        description="Sum of the member prices per day, before the discount, in Colombian pesos."
    )
    items: list[PackageLineOut] = Field(description="Items included in the package.")

    @classmethod
    def from_domain(cls, package: ServicePackage, catalog: Catalog) -> "ServicePackageOut":
        return cls(
            code=package.code,
            name=package.name,
            discount_bps=package.discount_bps,
            base_price_cop=package.base_unit_price(catalog).amount,
            items=[
                PackageLineOut(item_code=line.item_code, quantity=line.quantity)
                for line in package.lines
            ],
        )


class PackagesResponse(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "packages": [
                        {
                            "code": "pkg_basic_party",
                            "name": "Paquete Fiesta Básica",
                            "discount_bps": 500,
                            "base_price_cop": 560000,
                            "items": [
                                {"item_code": "dj_controller", "quantity": 1},
                                {"item_code": "fx_fog_machine", "quantity": 1},
                                {"item_code": "light_led_par", "quantity": 6},
                                {"item_code": "sound_active_speaker_12", "quantity": 2},
                                {"item_code": "sound_wireless_mic", "quantity": 1},
                            ],
                        }
                    ]
                }
            ]
        },
    )

    packages: list[ServicePackageOut] = Field(description="Bundles of equipment, ordered by code.")

    @classmethod
    def from_domain(cls, catalog: Catalog) -> "PackagesResponse":
        ordered = sorted(catalog.packages, key=lambda package: package.code)
        return cls(packages=[ServicePackageOut.from_domain(p, catalog) for p in ordered])


class ErrorOut(BaseModel):
    detail: str = Field(
        description="Machine-readable error code.", examples=["catalog_unavailable"]
    )


# --- POST /quote/chat -------------------------------------------------------------------------

MAX_MESSAGES = 8
MAX_MESSAGE_CHARS = 1000
MAX_TOTAL_CHARS = 4000

_STRICT = ConfigDict(extra="forbid", strict=True)


class ChatMessageIn(BaseModel):
    model_config = _STRICT

    role: Literal["user", "assistant"] = Field(description="Who wrote the message.")
    content: str = Field(
        min_length=1, max_length=MAX_MESSAGE_CHARS, description="Message text, in Spanish."
    )


class ChatRequestIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "examples": [
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": "Hola, necesito sonido para una fiesta el sabado 17 de "
                            "octubre de 8 pm a 11:30 pm, somos 150 personas, en un lugar a unos "
                            "45 km de Bogota. Quiero 2 parlantes activos de 15 pulgadas y 1 "
                            "mezcladora de 16 canales.",
                        }
                    ]
                },
                {"messages": [{"role": "user", "content": "Necesito sonido para una fiesta."}]},
            ]
        },
    )

    messages: list[ChatMessageIn] = Field(
        min_length=1,
        max_length=MAX_MESSAGES,
        description=(
            f"The conversation so far, oldest first: 1 to {MAX_MESSAGES} messages of up to "
            f"{MAX_MESSAGE_CHARS} characters ({MAX_TOTAL_CHARS} in total). The last one must "
            "come from the user. The server keeps no conversation: send the history each time."
        ),
    )

    @model_validator(mode="after")
    def _bounded_and_ends_with_the_user(self) -> "ChatRequestIn":
        if self.messages[-1].role != "user":
            raise ValueError("last_message_must_be_user")
        if sum(len(m.content) for m in self.messages) > MAX_TOTAL_CHARS:
            raise ValueError("conversation_too_long")
        return self


class QuoteLineOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str = Field(description="item, guest_size, weekend_holiday, night, distance, rounding.")
    code: str
    label: str | None
    quantity: int
    periods: int
    unit_amount: int | None = Field(description="Pesos per unit, when the line has one.")
    rate_bps: int | None = Field(description="Surcharge in basis points (100 = 1%).")
    basis: int | None = Field(description="Pesos the surcharge was computed on.")
    amount: int = Field(description="Line amount in whole Colombian pesos.")


class QuoteOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int
    rules_version: str
    currency: str = Field(description="Always COP.")
    rental_days: int
    lines: list[QuoteLineOut] = Field(description="Every charge; they add up to `total`.")
    subtotal: int = Field(description="Sum of the lines before the rounding adjustment.")
    total: int = Field(
        description="Final price in whole pesos, computed by the pricing rules, never by the AI."
    )


class RequestedLineOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    quantity: int


class EventRequestOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: str
    start: str = Field(description="ISO 8601 local date and time with UTC offset.")
    end: str
    guest_count: int
    distance_km: int
    venue: str
    items: list[RequestedLineOut]
    packages: list[RequestedLineOut]


class ShortageOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_code: str
    requested: int
    available: int


class AvailabilityOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_available: bool
    shortages: list[ShortageOut]


class ChatResponseOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str = Field(description="Opaque id, also sent in the X-Request-ID header.")
    status: Literal["clarification", "quote", "refused"]
    reply: str = Field(description="Answer for the customer, in Spanish.")
    quote: QuoteOut | None = Field(description="Present only when status is `quote`.")
    event_request: EventRequestOut | None
    availability: AvailabilityOut | None
    missing_fields: list[str] = Field(description="What to ask next; only for `clarification`.")
    reply_source: Literal["llm", "template", "static"] = Field(
        description="`llm` when the model wrote the reply, `template` or `static` otherwise."
    )
    quote_id: str | None = Field(
        default=None, description="Id of the saved quote; null when it could not be saved."
    )

    @classmethod
    def from_outcome(cls, request_id: str, outcome: AgentOutcome) -> "ChatResponseOut":
        request = outcome.event_request
        report = outcome.availability
        return cls(
            request_id=request_id,
            status=outcome.status.value,
            reply=outcome.reply,
            quote=QuoteOut.model_validate(outcome.quote.to_dict()) if outcome.quote else None,
            event_request=None
            if request is None
            else EventRequestOut(
                event_type=request.event_type.value,
                start=request.start.isoformat(),
                end=request.end.isoformat(),
                guest_count=request.guest_count,
                distance_km=request.distance_km,
                venue=request.venue.value,
                items=[RequestedLineOut(code=x.code, quantity=x.quantity) for x in request.items],
                packages=[
                    RequestedLineOut(code=x.code, quantity=x.quantity) for x in request.packages
                ],
            ),
            availability=None
            if report is None
            else AvailabilityOut(
                is_available=report.is_available,
                shortages=[
                    ShortageOut(item_code=s.item_code, requested=s.requested, available=s.remaining)
                    for s in report.shortages
                ],
            ),
            missing_fields=list(outcome.missing_fields),
            reply_source=outcome.reply_source,
        )


class ChatInvalidOut(BaseModel):
    detail: Literal["invalid_request"]
    message: str
    errors: list[dict[str, str]] = Field(description="Field path and error code; no input echo.")


class ChatErrorOut(BaseModel):
    detail: str = Field(description="Machine-readable error code.", examples=["rate_limited"])
    message: str = Field(description="Sentence for the customer, in Spanish.")


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class LoginOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Seconds until the token expires.")
    role: Literal["client", "admin"]


# --- Saved quotes and admin lists -------------------------------------------------------------


class QuoteRecordOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    created_at: str
    registered: bool = Field(description="True when the quote was made while logged in.")
    owner_email: str | None = Field(
        description="Email of the account that made the quote; null when anonymous."
    )
    event_type: str
    event_start: str
    event_end: str
    guest_count: int
    total_cop: int
    available: bool | None
    # Stored as validated at save time (same shape as the chat response `quote` and
    # `event_request`). Not re-validated on read, so a later schema change cannot break old rows.
    quote: dict[str, Any]
    event_request: dict[str, Any]


class QuotePageOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[QuoteRecordOut]
    total: int
    limit: int
    offset: int


class BookingOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    booking_code: str
    item_code: str
    quantity: int
    starts_at: str
    ends_at: str
    status: str
    created_at: str


class BookingPageOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[BookingOut]
    total: int
    limit: int
    offset: int
