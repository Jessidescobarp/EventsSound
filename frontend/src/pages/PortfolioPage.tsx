import { loadPortfolio } from "../api/portfolio";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Container } from "../components/ui/Container";
import { ImagePlaceholder } from "../components/ui/ImagePlaceholder";
import { PageHeader } from "../components/ui/PageHeader";
import { Spinner } from "../components/ui/Spinner";
import { es } from "../copy/es";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useRequest } from "../hooks/useRequest";

export default function PortfolioPage() {
  useDocumentTitle(es.titles.portfolio);
  const t = es.portfolio;
  const { state, reload } = useRequest(loadPortfolio);
  return (
    <>
      <PageHeader title={t.title} lead={t.lead} />
      <section className="py-10">
        <Container>
          {state.status === "loading" ? (
            <div role="status" className="flex items-center gap-3 text-ink-muted">
              <Spinner />
              <span>{t.loading}</span>
            </div>
          ) : null}
          {state.status === "error" ? (
            <div className="max-w-xl space-y-4">
              <Alert tone="info" title={t.unavailableTitle} role="status">
                {t.unavailableBody}
              </Alert>
              <Button variant="secondary" onClick={reload}>
                {es.common.retry}
              </Button>
            </div>
          ) : null}
          {state.status === "success" && state.data.length === 0 ? (
            <p className="text-ink-muted">{t.empty}</p>
          ) : null}
          {state.status === "success" && state.data.length > 0 ? (
            <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {state.data.map((event) => (
                <Card as="li" key={event.id} className="flex flex-col gap-3">
                  <ImagePlaceholder label={t.imageLabel(event.title)} />
                  <div>
                    <Badge>{event.kind}</Badge>
                  </div>
                  <h2 className="text-xl font-semibold break-words">{event.title}</h2>
                  <p className="break-words text-ink-muted">{event.description}</p>
                  {event.equipment.length > 0 ? (
                    <div>
                      <p className="text-sm font-semibold">{t.equipmentLabel}</p>
                      <p className="text-sm break-words text-ink-muted">{event.equipment.join(" · ")}</p>
                    </div>
                  ) : null}
                </Card>
              ))}
            </ul>
          ) : null}
        </Container>
      </section>
    </>
  );
}
