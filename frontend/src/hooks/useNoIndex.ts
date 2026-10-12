import { useEffect } from "react";

/** Adds <meta name="robots" content="noindex"> while the page is mounted (404 pages). */
export function useNoIndex(): void {
  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex";
    document.head.appendChild(meta);
    return () => {
      meta.remove();
    };
  }, []);
}
