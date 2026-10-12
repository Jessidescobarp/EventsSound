import { ButtonLink } from "../components/ui/Button";
import { Container } from "../components/ui/Container";
import { es } from "../copy/es";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function NotFoundPage() {
  useDocumentTitle(es.titles.notFound);
  return (
    <Container className="py-16">
      <h1 className="text-3xl font-bold text-brand-900">{es.notFound.title}</h1>
      <p className="mt-3 text-lg text-ink-muted">{es.notFound.body}</p>
      <div className="mt-6">
        <ButtonLink to="/">{es.notFound.cta}</ButtonLink>
      </div>
    </Container>
  );
}
