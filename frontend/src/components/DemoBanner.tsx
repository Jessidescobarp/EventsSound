import { es } from "../copy/es";
import { isMockMode } from "../env";

/** Always visible when the fake API is active, so demo data is never mistaken for real. */
export function DemoBanner() {
  if (!isMockMode()) return null;
  return (
    <div role="note" className="bg-accent-400 px-gutter py-2 text-center text-sm text-ink">
      <strong>{es.banners.demoTitle}</strong>
      <span>{`. ${es.banners.demoBody}`}</span>
    </div>
  );
}
