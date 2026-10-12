"""Response models of the public catalog API. They never expose database ids."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from eventssound.domain.catalog import Catalog, EquipmentItem, ServicePackage

Code = Annotated[str, Field(description="Stable machine-readable identifier.")]


class CatalogItemOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: Code
    name: str = Field(description="Display name, in Spanish.")
    category: str = Field(description="One of: sound, lighting, dj, stage, effects, video.")
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
