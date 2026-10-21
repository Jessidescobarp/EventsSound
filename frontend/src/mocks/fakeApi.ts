/**
 * Demonstration-only fake of the backend, answering with the catalog-api contract.
 * It is loaded ONLY through a dynamic import guarded by isMockMode()
 * (see main.tsx), so default and production builds do not contain this module.
 * All data is synthetic.
 */
import type { CatalogItem, ServicePackage } from "../api/catalog";
import type { PortfolioEvent } from "../api/portfolio";
import type { ChatResponse, QuoteLine } from "../api/chat";
import { agentConfigRoute, resetDemoAgentConfig } from "./fakeAgentConfig";

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
  item("staff_dj", "DJ profesional (hasta 5 horas)", "staff", 2, 900_000),
  item("staff_mc", "Animador / maestro de ceremonias (hasta 5 horas)", "staff", 2, 700_000),
  item("staff_sound_tech", "Técnico de sonido en sitio", "staff", 3, 400_000),
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
    ["staff_mc", 1],
    ["staff_sound_tech", 1],
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
    ["staff_dj", 1],
    ["staff_mc", 1],
  ]),
].sort(byCode);

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

// ---- chat scenarios (POST /quote/chat), picked by a keyword in the last user message ----

const line = (kind: string, code: string, label: string | null, over: Partial<QuoteLine>): QuoteLine => ({
  kind, code, label, quantity: 1, periods: 1, unit_amount: null, rate_bps: null, basis: null, amount: 0, ...over,
});

const DEMO_LINES: QuoteLine[] = [
  line("item", "sound_speaker_active_15", "Parlante activo 15 pulgadas", { quantity: 2, unit_amount: 120_000, amount: 240_000 }),
  line("item", "sound_mixer_16", "Consola de mezcla de 16 canales", { unit_amount: 179_900, amount: 179_900 }),
  line("weekend_holiday", "weekend_holiday", null, { rate_bps: 1000, basis: 419_900, amount: 41_990 }),
  line("rounding", "rounding", null, { amount: 110 }),
];

const sum = (lines: QuoteLine[]) => lines.reduce((total, l) => total + l.amount, 0);
const base = { quote: null, availability: null, missing_fields: [] as string[], reply_source: "static", options: [] as string[] } as const;

const CHAT_QUOTE: ChatResponse = {
  ...base,
  request_id: "demo-chat-fixture-quote",
  status: "quote",
  reply: "Esta es tu propuesta de demostración.\nLos valores los calcula el sistema de precios.",
  quote: {
    version: 1,
    currency: "COP",
    rental_days: 1,
    lines: DEMO_LINES,
    subtotal: sum(DEMO_LINES.slice(0, -1)),
    total: sum(DEMO_LINES),
  },
  availability: { is_available: true, shortages: [] },
  reply_source: "llm",
};

const CHAT_SHORTAGE: ChatResponse = {
  ...CHAT_QUOTE,
  request_id: "demo-chat-fixture-shortage",
  reply: "Hay un equipo que no alcanza para esa fecha (demostración).",
  availability: {
    is_available: false,
    shortages: [{ item_code: "sound_speaker_active_15", requested: 2, available: 1 }],
  },
  reply_source: "template",
};

const CHAT_CLARIFICATION: ChatResponse = {
  ...base,
  request_id: "demo-chat-fixture-question",
  status: "clarification",
  reply: "Para armar tu cotización necesito algunos datos más (demostración):\n1.¿Cuántos invitados habrá?",
  missing_fields: ["guest_count", "event_date"],
  options: ["Paquete Fiesta", "Paquete DJ", "Ver todo el catalogo"],
};

const DEMO_WELCOME =
  "Hola, soy el asistente de EventSoundDR (demo). Cuentame tu evento y te armo una cotizacion.";

function chatRoute(init?: RequestInit): Response {
  let last: string;
  try {
    const body = JSON.parse(String(init?.body)) as { messages: Array<{ content: string }> };
    last = (body.messages.at(-1)?.content ?? "").toLowerCase();
  } catch {
    return json({ detail: "invalid_request", message: "Solicitud no valida.", errors: [] }, 422);
  }
  if (last.includes("apagado")) {
    return json({ detail: "chat_disabled", message: "El asistente de cotizaciones no esta disponible por ahora." }, 503);
  }
  if (last.includes("limite")) {
    return json({ detail: "rate_limited", message: "Has enviado demasiadas solicitudes. Intenta de nuevo en unos minutos." }, 429, { "Retry-After": "8" });
  }
  if (last.includes("pregunta")) return json(CHAT_CLARIFICATION);
  if (last.includes("faltante")) return json(CHAT_SHORTAGE);
  return json(CHAT_QUOTE);
}

// ---- auth and saved records (demo accounts; the "password" is public by design) ----

export const DEMO_PASSWORD = "demo-password";
const TOKENS = { admin: "demo.admin.token", client: "demo.client.token" } as const;
const ACCOUNTS: Record<string, "admin" | "client"> = {
  "admin@eventsounddr.example": "admin",
  "cliente@eventsounddr.example": "client",
};

function loginRoute(init?: RequestInit): Response {
  let body: { email?: unknown; password?: unknown };
  try {
    body = JSON.parse(String(init?.body)) as typeof body;
  } catch {
    return json({ detail: "invalid_request", message: "Solicitud no valida." }, 422);
  }
  const email = typeof body.email === "string" ? body.email.toLowerCase() : "";
  if (email.startsWith("limite")) {
    return json({ detail: "rate_limited", message: "Demasiados intentos." }, 429, { "Retry-After": "5" });
  }
  const role = ACCOUNTS[email];
  if (!role || body.password !== DEMO_PASSWORD) {
    return json({ detail: "invalid_credentials", message: "El correo o la contrasena no son correctos." }, 401);
  }
  return json({ access_token: TOKENS[role], token_type: "bearer", expires_in: 3600, role });
}

const callerRole = (init?: RequestInit): "admin" | "client" | null => {
  const header = new Headers(init?.headers).get("Authorization") ?? "";
  return header === `Bearer ${TOKENS.admin}` ? "admin" : header === `Bearer ${TOKENS.client}` ? "client" : null;
};

const DEMO_TYPES = ["wedding", "corporate", "birthday", "graduation", "concert"];
const demoQuotes = Array.from({ length: 25 }, (_, n) => ({
  id: `demo-quote-${String(n + 1).padStart(2, "0")}`,
  created_at: new Date(Date.UTC(2026, 9, 15, 12, 0) - n * 3_600_000).toISOString(),
  registered: n % 4 === 0,
  owner_email: n % 4 === 0 ? "cliente@eventsounddr.example" : null,
  event_type: DEMO_TYPES[n % DEMO_TYPES.length],
  event_start: new Date(Date.UTC(2026, 10, 14 + (n % 20), 23, 0)).toISOString(),
  event_end: new Date(Date.UTC(2026, 10, 15 + (n % 20), 3, 0)).toISOString(),
  guest_count: 40 + n * 5,
  total_cop: CHAT_QUOTE.quote?.total ?? 0,
  available: n % 5 === 0 ? false : n % 7 === 0 ? null : true,
  quote: CHAT_QUOTE.quote,
}));
const demoBookings = Array.from({ length: 12 }, (_, n) => ({
  booking_code: `DEMO-${String(100 + Math.floor(n / 2))}`,
  item_code: n % 2 === 0 ? "sound_speaker_active_15" : "lighting_led_par",
  quantity: 2 + (n % 3),
  starts_at: new Date(Date.UTC(2026, 10, 14 + n, 23, 0)).toISOString(),
  ends_at: new Date(Date.UTC(2026, 10, 15 + n, 3, 0)).toISOString(),
  status: ["pending", "confirmed", "cancelled"][n % 3],
  created_at: new Date(Date.UTC(2026, 9, 14, 12, 0) - n * 3_600_000).toISOString(),
}));

function pageOf<T>(rows: T[], search: URLSearchParams, extra: object = {}): Response {
  const limit = Number(search.get("limit") ?? 20);
  const offset = Number(search.get("offset") ?? 0);
  if (!Number.isInteger(limit) || limit < 1 || limit > 100 || !Number.isInteger(offset) || offset < 0) {
    return json({ detail: "invalid_request", message: "Solicitud no valida." }, 422);
  }
  return json({ items: rows.slice(offset, offset + limit), total: rows.length, limit, offset, ...extra });
}

const demoSecurity = Array.from({ length: 12 }, (_, n) => ({
  id: 12 - n,
  at: new Date(Date.UTC(2026, 9, 15, 12, 0) - n * 1_800_000).toISOString(),
  kind: n % 3 === 0 ? "login_failed" : "chat_refused",
  client: (0xa1b2c3d4e5f60 + (n % 3) * 0x1111111).toString(16).padStart(16, "0"),
}));

function recordsRoute(pathname: string, init: RequestInit | undefined, search: URLSearchParams): Response {
  const role = callerRole(init);
  if (role === null) return json({ detail: "not_authenticated", message: "Debes iniciar sesion." }, 401);
  if (pathname === "/me/quotes") return pageOf(demoQuotes.filter((q) => q.registered), search);
  if (role !== "admin") return json({ detail: "forbidden", message: "No tienes permiso." }, 403);
  if (pathname === "/admin/security") {
    const count = (kind: string) => demoSecurity.filter((e) => e.kind === kind).length;
    return pageOf(demoSecurity, search, {
      last_24h: { chat_refused: count("chat_refused"), login_failed: count("login_failed") },
    });
  }
  return pathname === "/admin/quotes" ? pageOf(demoQuotes, search) : pageOf(demoBookings, search);
}

// ---- admin catalog edits: a live copy of the demo catalog that the edits change ----

let liveItems: CatalogItem[] = [];
let livePackages: ServicePackage[] = [];

/** Back to the built-in demo catalog (tests call this between cases). */
export function resetDemoCatalog(): void {
  liveItems = MOCK_ITEMS.map((i) => ({ ...i }));
  livePackages = MOCK_PACKAGES.map((p) => ({ ...p, items: p.items.map((m) => ({ ...m })) }));
  livePortfolio = MOCK_PORTFOLIO.map((e) => ({ ...e, equipment: [...e.equipment] }));
  resetDemoAgentConfig();
}

// ---- portfolio: the six illustrative events the real database is seeded with ----

const event = (id: number, title: string, kind: string, description: string, equipment: string[]) => ({
  id,
  title,
  kind,
  description,
  equipment,
  visible: true,
});

export const MOCK_PORTFOLIO: PortfolioEvent[] = [
  event(1, "Boda en jardín", "Boda", "Ceremonia y recepción para 180 invitados con sonido ambiental y pista de baile iluminada.", ["Sonido", "Micrófonos inalámbricos", "Luces LED"]),
  event(2, "Lanzamiento corporativo", "Corporativo", "Presentación de producto con pantalla LED, micrófonos de solapa y escenario modular.", ["Pantalla LED", "Consola de mezcla", "Tarima"]),
  event(3, "Festival universitario", "Festival", "Dos escenarios con bandas en vivo y DJs durante un día completo.", ["Sistema de sonido", "Cabezas móviles", "Efectos"]),
  event(4, "Noche de DJ en terraza", "DJ", "Sesión nocturna al aire libre con cabina de DJ, láser y máquina de humo.", ["Equipo de DJ", "Láser", "Humo"]),
  event(5, "Fiesta de quince años", "Fiesta", "Vals, baile sorpresa y pista con efectos de chispas frías.", ["Sonido", "Chispas frías", "Luces LED"]),
  event(6, "Concierto en teatro", "Concierto", "Montaje de sonido e iluminación para un concierto acústico con aforo de 400 personas.", ["Line array", "Monitores", "Iluminación escénica"]),
];

let livePortfolio: PortfolioEvent[] = [];
resetDemoCatalog();

function portfolioRoute(pathname: string, init?: RequestInit): Response {
  if (pathname === "/portfolio") {
    return init?.method === undefined || init.method === "GET"
      ? json({ events: livePortfolio.filter((e) => e.visible) })
      : json({ detail: "Method Not Allowed" }, 405);
  }
  const role = callerRole(init);
  if (role === null) return json({ detail: "not_authenticated", message: "Debes iniciar sesion." }, 401);
  if (role !== "admin") return json({ detail: "forbidden", message: "No tienes permiso." }, 403);
  if (pathname === "/admin/portfolio" && (init?.method === undefined || init.method === "GET")) {
    return json({ events: livePortfolio });
  }
  const match = /^\/admin\/portfolio(?:\/(\d+))?$/.exec(pathname);
  const creating = init?.method === "POST" && match?.[1] === undefined;
  const editing = init?.method === "PUT" && match?.[1] !== undefined;
  if (!match || !(creating || editing)) return json({ detail: "Not Found" }, 404);
  let body: Partial<PortfolioEvent>;
  try {
    body = JSON.parse(String(init?.body)) as Partial<PortfolioEvent>;
  } catch {
    return json({ detail: "invalid_portfolio_event", message: "Datos no validos." }, 422);
  }
  const next = {
    title: String(body.title ?? "").trim(),
    kind: String(body.kind ?? "").trim(),
    description: String(body.description ?? "").trim(),
    equipment: Array.isArray(body.equipment) ? body.equipment.map(String) : [],
    visible: body.visible === true,
  };
  if (!next.title || !next.kind || !next.description) {
    return json({ detail: "invalid_portfolio_event", message: "Datos no validos." }, 422);
  }
  if (creating) {
    const id = Math.max(0, ...livePortfolio.map((e) => e.id)) + 1;
    livePortfolio.push({ id, ...next });
    return json({ id }, 201);
  }
  const id = Number(match[1]);
  const at = livePortfolio.findIndex((e) => e.id === id);
  if (at === -1) return json({ detail: "not_found", message: "No existe." }, 404);
  livePortfolio[at] = { id, ...next };
  return json({ id });
}

const withBasePrices = (): ServicePackage[] =>
  livePackages.map((p) => ({
    ...p,
    base_price_cop: p.items.reduce(
      (sum, m) => sum + (liveItems.find((i) => i.code === m.item_code)?.unit_price_cop ?? 0) * m.quantity,
      0,
    ),
  }));

const CODE_SHAPE = /^[a-z0-9_]{3,64}$/;

function adminCatalogRoute(pathname: string, init?: RequestInit): Response {
  const role = callerRole(init);
  if (role === null) return json({ detail: "not_authenticated", message: "Debes iniciar sesion." }, 401);
  if (role !== "admin") return json({ detail: "forbidden", message: "No tienes permiso." }, 403);
  const match = /^\/admin\/catalog\/(items|packages)(?:\/([^/]+))?$/.exec(pathname);
  const creating = init?.method === "POST" && match !== null && match[2] === undefined;
  const editing = init?.method === "PUT" && match !== null && match[2] !== undefined;
  if (!match || !(creating || editing)) return json({ detail: "Not Found" }, 404);
  let body: Record<string, unknown>;
  try {
    body = JSON.parse(String(init?.body)) as Record<string, unknown>;
  } catch {
    return json({ detail: "invalid_request", message: "Solicitud no valida." }, 422);
  }
  const code = creating ? body.code : decodeURIComponent(match[2] ?? "");
  const invalid = json({ detail: "invalid_catalog_entry", message: "Los datos no son validos." }, 422);
  if (typeof code !== "string" || !CODE_SHAPE.test(code) || typeof body.name !== "string" || !body.name.trim()) {
    return invalid;
  }
  const list: { code: string }[] = match[1] === "items" ? liveItems : livePackages;
  const at = list.findIndex((entry) => entry.code === code);
  if (creating && at !== -1) return json({ detail: "code_taken", message: "Ya existe." }, 409);
  if (editing && at === -1) return json({ detail: "not_found", message: "No existe." }, 404);

  if (match[1] === "items") {
    const next: CatalogItem = {
      code,
      name: body.name.trim(),
      category: String(body.category),
      stock_quantity: Number(body.stock_quantity),
      unit_price_cop: Number(body.unit_price_cop),
    };
    if (!Number.isInteger(next.stock_quantity) || !Number.isInteger(next.unit_price_cop)) return invalid;
    if (at === -1) liveItems.push(next);
    else liveItems[at] = next;
  } else {
    const lines = Array.isArray(body.lines) ? (body.lines as { item_code: string; quantity: number }[]) : [];
    if (lines.length === 0) return invalid;
    if (lines.some((l) => !liveItems.some((i) => i.code === l.item_code))) {
      return json({ detail: "unknown_item", message: "Equipo desconocido." }, 422);
    }
    const next: ServicePackage = {
      code,
      name: body.name.trim(),
      discount_bps: Number(body.discount_bps),
      base_price_cop: 0,
      items: lines.map((l) => ({ item_code: l.item_code, quantity: l.quantity })),
    };
    if (at === -1) livePackages.push(next);
    else livePackages[at] = next;
  }
  return json({ status: "saved" }, creating ? 201 : 200);
}

function route(pathname: string, init?: RequestInit, search = new URLSearchParams()): Response {
  if (pathname.startsWith("/admin/agent-config")) {
    const role = callerRole(init);
    if (role === null) return json({ detail: "not_authenticated", message: "Debes iniciar sesion." }, 401);
    if (role !== "admin") return json({ detail: "forbidden", message: "No tienes permiso." }, 403);
    return agentConfigRoute(pathname, init, search, DEMO_PASSWORD);
  }
  if (pathname.startsWith("/admin/catalog/")) return adminCatalogRoute(pathname, init);
  if (pathname === "/portfolio" || pathname.startsWith("/admin/portfolio")) {
    return portfolioRoute(pathname, init);
  }
  switch (pathname) {
    case "/auth/login":
      return init?.method === "POST" ? loginRoute(init) : json({ detail: "Method Not Allowed" }, 405);
    case "/me/quotes":
    case "/admin/quotes":
    case "/admin/bookings":
    case "/admin/security":
      return recordsRoute(pathname, init, search);
    case "/quote/chat":
      return init?.method === "POST" ? chatRoute(init) : json({ detail: "Method Not Allowed" }, 405);
    case "/quote/config":
      return json({ welcome_message: DEMO_WELCOME });
    case "/health":
      return json({ status: "ok" });
    case "/catalog/items":
      return json({ items: [...liveItems].sort(byCode) });
    case "/catalog/packages":
      return json({ packages: withBasePrices().sort(byCode) });
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
      const timer = setTimeout(() => resolve(route(url.pathname, init, url.searchParams)), latencyMs);
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
