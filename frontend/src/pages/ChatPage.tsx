import { ButtonLink } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { Container } from "../components/ui/Container";
import { ImagePlaceholder } from "../components/ui/ImagePlaceholder";
import { PageHeader } from "../components/ui/PageHeader";
import { es } from "../copy/es";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/** Placeholder route for the quote assistant (arrives with a later change). */
export default function ChatPage() {
  useDocumentTitle(es.titles.chat);
  const t = es.chat;
  return (
    <>
      <PageHeader title={t.title} lead={t.lead}>
        <div className="mt-4">
          <Badge tone="accent">{t.badge}</Badge>
        </div>
      </PageHeader>
      <section className="py-10">
        <Container className="grid items-center gap-8 md:grid-cols-2">
          <div>
            <p className="text-lg text-ink-muted">{t.body}</p>
            <div className="mt-6">
              <ButtonLink to="/servicios">{t.cta}</ButtonLink>
            </div>
          </div>
          <ImagePlaceholder label={t.imageLabel} className="opacity-60" />
        </Container>
      </section>
    </>
  );
}
