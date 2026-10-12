import { Container } from "../components/ui/Container";
import { ButtonLink } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { es } from "../copy/es";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function HomePage() {
  useDocumentTitle(es.titles.home);
  const t = es.home;
  return (
    <>
      <section className="bg-linear-to-br from-brand-900 via-brand-700 to-brand-600 text-white">
        <Container className="py-14 sm:py-20">
          <h1 className="max-w-3xl font-display text-4xl font-extrabold tracking-tight sm:text-5xl">
            {t.heroTitle}
          </h1>
          <p className="mt-4 max-w-2xl text-lg text-brand-100">{t.heroLead}</p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <ButtonLink to="/servicios" variant="inverse">
              {t.ctaServices}
            </ButtonLink>
            <ButtonLink to="/cotizar" variant="secondary">
              {t.ctaChat}
            </ButtonLink>
          </div>
        </Container>
      </section>

      <section aria-labelledby="home-offer" className="py-12">
        <Container>
          <h2 id="home-offer" className="text-2xl font-bold">
            {t.offerTitle}
          </h2>
          <ul className="mt-6 grid gap-4 sm:grid-cols-3">
            {t.offer.map((entry) => (
              <Card as="li" key={entry.title}>
                <h3 className="text-lg font-semibold text-brand-900">{entry.title}</h3>
                <p className="mt-2 text-ink-muted">{entry.body}</p>
              </Card>
            ))}
          </ul>
        </Container>
      </section>

      <section aria-labelledby="home-steps" className="bg-surface-alt py-12">
        <Container>
          <h2 id="home-steps" className="text-2xl font-bold">
            {t.stepsTitle}
          </h2>
          <ol className="mt-6 grid gap-4 sm:grid-cols-3">
            {t.steps.map((step, index) => (
              <li key={step.title} className="flex gap-3">
                <span
                  aria-hidden="true"
                  className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-600 font-bold text-white"
                >
                  {index + 1}
                </span>
                <div>
                  <h3 className="font-semibold">{step.title}</h3>
                  <p className="text-ink-muted">{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </Container>
      </section>

      <section aria-labelledby="home-closing" className="py-12">
        <Container className="text-center">
          <h2 id="home-closing" className="text-2xl font-bold">
            {t.closingTitle}
          </h2>
          <p className="mt-2 text-ink-muted">{t.closingBody}</p>
          <div className="mt-6 flex justify-center">
            <ButtonLink to="/servicios">{t.ctaServices}</ButtonLink>
          </div>
        </Container>
      </section>
    </>
  );
}
