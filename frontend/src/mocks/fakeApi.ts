/**
 * Demonstration-only fake of the backend, answering with the catalog-api contract.
 * It is loaded ONLY through a dynamic import guarded by VITE_USE_MOCKS === "true"
 * (see main.tsx), so default and production builds do not contain this module.
 * All data is synthetic.
 */
import type { CatalogItem, ServicePackage } from "../api/catalog";

const item = (
  code: string,
  name: string,
  category: string,
  stock_quantity: number,
  unit_price_cop: number,
): CatalogItem => ({ code, name, category, stock_quantity, unit_price_cop });

const byCode = (a: { code: string }, b: { code: string }) =>
  a.code < b.code ? -1 : a.code > b.code ? 1 : 0;

export const MOCK_ITEMS: CatalogItem[] = [
  item("dj_booth", "Mesa de DJ con frente iluminado", "dj", 4, 150_000),
  item("dj_cdj_pair", "Par de reproductores CDJ", "dj", 3, 380_000),
  item("dj_controller", "Controlador DJ de 4 canales", "dj", 5, 220_000),
  item("effects_fog_machine", "Máquina de humo", "effects", 8, 60_000),
  item("effects_spark_fountain", "Fuente de chispas frías", "effects", 4, 140_000),
  item("lighting_dmx_controller", "Controlador DMX de 192 canales", "lighting", 6, 70_000),
  item("lighting_laser", "Láser RGB de 5 W", "lighting", 3, 180_000),
  item("lighting_led_par", "Luz LED PAR RGBW", "lighting", 24, 25_000),
  item("lighting_moving_head_spot", "Cabeza móvil spot", "lighting", 10, 95_000),
  item("lighting_moving_head_wash", "Cabeza móvil wash", "lighting", 10, 85_000),
  item("sound_mic_wired", "Micrófono alámbrico", "sound", 20, 20_000),
  item("sound_mic_wireless", "Micrófono inalámbrico de mano", "sound", 12, 55_000),
  item("sound_mixer_16", "Consola de mezcla de 16 canales", "sound", 5, 180_000),
  item("sound_speaker_active_12", "Parlante activo 12 pulgadas", "sound", 12, 90_000),
  item("sound_speaker_active_15", "Parlante activo 15 pulgadas", "sound", 8, 120_000),
  item("sound_speaker_stand", "Soporte para parlante", "sound", 24, 10_000),
  item("sound_subwoofer_18", "Subwoofer de 18 pulgadas", "sound", 6, 150_000),
  item("stage_module_2x1", "Módulo de tarima de 2 x 1 m", "stage", 16, 80_000),
  item("video_led_screen_3x2", "Pantalla LED de 3 x 2 m", "video", 2, 900_000),
  item("video_projector", "Proyector con pantalla", "video", 3, 250_000),
].sort(byCode);

const unitPrice = new Map(MOCK_ITEMS.map((i) => [i.code, i.unit_price_cop]));

const pkg = (
  code: string,
  name: string,
  discount_bps: number,
  members: Array<[string, number]>,
): ServicePackage => ({
  code,
  name,
  discount_bps,
  base_price_cop: members.reduce((sum, [c, q]) => sum + (unitPrice.get(c) ?? 0) * q, 0),
  items: members.map(([item_code, quantity]) => ({ item_code, quantity })),
});

export const MOCK_PACKAGES: ServicePackage[] = [
  pkg("pkg_basic_party", "Fiesta básica", 1000, [
    ["lighting_led_par", 4],
    ["sound_mic_wired", 2],
    ["sound_mixer_16", 1],
    ["sound_speaker_active_15", 2],
    ["sound_speaker_stand", 2],
    ["sound_subwoofer_18", 1],
  ]),
  pkg("pkg_corporate", "Evento corporativo", 800, [
    ["sound_mic_wireless", 2],
    ["sound_mixer_16", 1],
    ["sound_speaker_active_12", 2],
    ["sound_speaker_stand", 2],
    ["video_projector", 1],
  ]),
  pkg("pkg_dj_night", "Noche DJ", 1200, [
    ["dj_booth", 1],
    ["dj_controller", 1],
    ["effects_fog_machine", 1],
    ["lighting_led_par", 6],
    ["lighting_moving_head_spot", 2],
    ["sound_speaker_active_15", 2],
    ["sound_subwoofer_18", 2],
  ]),
  pkg("pkg_wedding", "Boda", 1500, [
    ["effects_fog_machine", 1],
    ["lighting_led_par", 8],
    ["lighting_moving_head_wash", 2],
    ["sound_mic_wireless", 2],
    ["sound_mixer_16", 1],
    ["sound_speaker_active_15", 2],
    ["sound_subwoofer_18", 1],
  ]),
].sort(byCode);

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function route(pathname: string): Response {
  switch (pathname) {
    case "/health":
      return json({ status: "ok" });
    case "/catalog/items":
      return json({ items: MOCK_ITEMS });
    case "/catalog/packages":
      return json({ packages: MOCK_PACKAGES });
    default:
      return json({ detail: "Not Found" }, 404);
  }
}

/** A fetch replacement with a small artificial latency so loading states are visible. */
export function createFakeFetch({ latencyMs = 350 }: { latencyMs?: number } = {}): typeof fetch {
  return (input, init) =>
    new Promise<Response>((resolve, reject) => {
      const signal = init?.signal;
      const url = new URL(input instanceof Request ? input.url : String(input));
      const timer = setTimeout(() => resolve(route(url.pathname)), latencyMs);
      signal?.addEventListener(
        "abort",
        () => {
          clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    });
}

export function installMocks(): void {
  globalThis.fetch = createFakeFetch();
}
