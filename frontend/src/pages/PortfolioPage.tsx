import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { Container } from "../components/ui/Container";
import { ImagePlaceholder } from "../components/ui/ImagePlaceholder";
import { PageHeader } from "../components/ui/PageHeader";
import { es } from "../copy/es";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function PortfolioPage() {
  useDocumentTitle(es.titles.portfolio);
  const t = es.portfolio;
  return (
    <>
      <PageHeader title={t.title} lead={t.lead} />
      <section className="py-10">
        <Container>
          <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {t.events.map((event) => (
              <Card as="li" key={event.id} className="flex flex-col gap-3">
                <ImagePlaceholder label={t.imageLabel(event.title)} />
                <div>
                  <Badge>{event.kind}</Badge>
                </div>
                <h2 className="text-xl font-semibold">{event.title}</h2>
                <p className="text-ink-muted">{event.description}</p>
                <div>
                  <p className="text-sm font-semibold">{t.equipmentLabel}</p>
                  <p className="text-sm text-ink-muted">{event.equipment.join(" · ")}</p>
                </div>
              </Card>
            ))}
          </ul>
        </Container>
      </section>
    </>
  );
}
