import { Card } from "../components/ui/Card";
import { Container } from "../components/ui/Container";
import { PageHeader } from "../components/ui/PageHeader";
import { es } from "../copy/es";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function AboutPage() {
  useDocumentTitle(es.titles.about);
  const t = es.about;
  return (
    <>
      <PageHeader title={t.title} lead={t.lead} />
      <section aria-labelledby="about-story" className="py-10">
        <Container>
          <h2 id="about-story" className="text-2xl font-bold">
            {t.storyTitle}
          </h2>
          <div className="mt-4 max-w-3xl space-y-4 text-lg text-ink-muted">
            {t.story.map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
          </div>
        </Container>
      </section>
      <section aria-labelledby="about-values" className="bg-surface-alt py-10">
        <Container>
          <h2 id="about-values" className="text-2xl font-bold">
            {t.valuesTitle}
          </h2>
          <ul className="mt-6 grid gap-4 sm:grid-cols-3">
            {t.values.map((value) => (
              <Card as="li" key={value.title}>
                <h3 className="text-lg font-semibold text-brand-900">{value.title}</h3>
                <p className="mt-2 text-ink-muted">{value.body}</p>
              </Card>
            ))}
          </ul>
        </Container>
      </section>
    </>
  );
}
