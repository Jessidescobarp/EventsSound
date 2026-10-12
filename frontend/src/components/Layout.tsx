import { useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { es } from "../copy/es";
import { BackendStatusContext } from "../hooks/backendStatusContext";
import { useBackendStatus } from "../hooks/useBackendStatus";
import { DemoBanner } from "./DemoBanner";
import { WarmupBanner } from "./WarmupBanner";
import { Container } from "./ui/Container";

const NAV = [
  { to: "/", label: es.nav.home, end: true },
  { to: "/quienes-somos", label: es.nav.about, end: false },
  { to: "/portafolio", label: es.nav.portfolio, end: false },
  { to: "/servicios", label: es.nav.services, end: false },
  { to: "/cotizar", label: es.nav.chat, end: false },
] as const;

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `inline-flex min-h-11 items-center rounded-control px-3 text-base font-medium ${
    isActive ? "bg-brand-100 text-brand-900" : "text-ink hover:bg-surface-alt"
  }`;

export function Layout() {
  const backend = useBackendStatus();
  const { pathname } = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const firstRender = useRef(true);

  // After client-side navigation move focus to the content (not on the first load).
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus(); // focusing also scrolls the content into view
  }, [pathname]);

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#contenido"
        className="sr-only focus:not-sr-only focus:fixed focus:left-gutter focus:top-2 focus:z-50 focus:rounded-control focus:bg-white focus:px-4 focus:py-2 focus:font-semibold focus:text-brand-900 focus:shadow-card"
      >
        {es.a11y.skipLink}
      </a>
      <DemoBanner />
      <WarmupBanner status={backend.status} onRetry={backend.retry} />
      <header className="border-b border-line bg-surface">
        <Container className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 py-3">
          <NavLink
            to="/"
            end
            aria-label={es.brand.logoLabel}
            className="font-display text-xl font-extrabold tracking-tight text-brand-900"
          >
            {es.brand.name}
          </NavLink>
          <nav aria-label={es.a11y.mainNav}>
            <ul className="-mx-2 flex flex-wrap items-center gap-1">
              {NAV.map((entry) => (
                <li key={entry.to}>
                  <NavLink to={entry.to} end={entry.end} className={navLinkClass}>
                    {entry.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        </Container>
      </header>
      <main id="contenido" ref={mainRef} tabIndex={-1} className="flex-1 outline-none">
        <BackendStatusContext.Provider value={backend}>
          <Outlet />
        </BackendStatusContext.Provider>
      </main>
      <footer className="border-t border-line bg-surface-alt">
        <Container className="flex flex-col gap-1 py-6 text-sm text-ink-muted">
          <p className="font-semibold text-ink">{`${es.brand.name} · ${es.brand.tagline}`}</p>
          <p>{es.footer.note}</p>
          <p>{es.footer.rights(new Date().getFullYear())}</p>
        </Container>
      </footer>
    </div>
  );
}
