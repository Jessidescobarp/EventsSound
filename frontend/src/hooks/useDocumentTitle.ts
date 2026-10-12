import { useEffect } from "react";
import { es } from "../copy/es";

/** Sets "<page> · EventSoundDR" so each route has a distinct title for screen readers and tabs. */
export function useDocumentTitle(page: string): void {
  useEffect(() => {
    document.title = `${page} · ${es.brand.name}`;
  }, [page]);
}
