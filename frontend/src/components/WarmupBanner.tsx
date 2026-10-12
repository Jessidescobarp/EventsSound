import { es } from "../copy/es";
import type { BackendStatus } from "../hooks/useBackendStatus";
import { Button } from "./ui/Button";
import { Container } from "./ui/Container";
import { Spinner } from "./ui/Spinner";

/**
 * Non-blocking cold-start notice. The live region is always mounted (and empty when
 * there is nothing to say) so screen readers announce the text when it appears.
 */
export function WarmupBanner({ status, onRetry }: { status: BackendStatus; onRetry: () => void }) {
  const waking = status === "waking";
  const unavailable = status === "unavailable";
  return (
    <div role="status" aria-live="polite">
      {waking || unavailable ? (
        <div className={unavailable ? "bg-danger-soft text-danger" : "bg-warn-soft text-warn"}>
          <Container className="flex flex-wrap items-center gap-3 py-3 text-sm">
            {waking ? <Spinner /> : null}
            <p className="min-w-0 flex-1">
              <strong>{waking ? es.banners.wakingTitle : es.banners.unavailableTitle}</strong>
              {`. ${waking ? es.banners.wakingBody : es.banners.unavailableBody}`}
            </p>
            {unavailable ? (
              <Button variant="secondary" onClick={onRetry}>
                {es.common.retry}
              </Button>
            ) : null}
          </Container>
        </div>
      ) : null}
    </div>
  );
}
