import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { classifyLoginError, login, type LoginFailure, type Role } from "../api/auth";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/authContext";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Container } from "../components/ui/Container";
import { PageHeader } from "../components/ui/PageHeader";
import { es } from "../copy/es";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useNoIndex } from "../hooks/useNoIndex";

const t = es.auth;
const MAX_EMAIL = 254;
const MAX_PASSWORD = 200;

/** Where each role lands after signing in, unless a guard sent them here from another page. */
export const HOME_BY_ROLE: Record<Role, string> = { client: "/mis-cotizaciones", admin: "/admin" };

/** Only same-site paths are honoured: a `from` that is not one falls back to the role home. */
function safeTarget(from: unknown, role: Role): string {
  if (typeof from === "string" && /^\/[A-Za-z0-9/_-]*$/.test(from) && from !== "/ingresar") return from;
  return HOME_BY_ROLE[role];
}

interface Problem {
  kind: LoginFailure;
  waitSeconds?: number;
}

export default function LoginPage() {
  useDocumentTitle(es.titles.login);
  useNoIndex();
  const { session, signIn, expired } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const emailId = useId();
  const passwordId = useId();
  const errorId = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [wait, setWait] = useState(0);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);
  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait((seconds) => seconds - 1), 1_000);
    return () => clearTimeout(timer);
  }, [wait]);

  if (session !== null && !sending) {
    return <Navigate to={safeTarget((location.state as { from?: unknown } | null)?.from, session.role)} replace />;
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (sending || wait > 0) return;
    const controller = new AbortController();
    inFlight.current = controller;
    setSending(true);
    setProblem(null);
    try {
      const result = await login(email, password, controller.signal);
      setPassword("");
      signIn(result);
      void navigate(safeTarget((location.state as { from?: unknown } | null)?.from, result.role), { replace: true });
    } catch (caught) {
      const kind = classifyLoginError(caught);
      if (kind === "aborted") return;
      const seconds = caught instanceof ApiError ? caught.retryAfterSeconds : undefined;
      if (kind === "rate_limited") setWait(seconds ?? 30);
      setProblem({ kind, waitSeconds: seconds });
    } finally {
      inFlight.current = null;
      setSending(false);
    }
  }

  const canSubmit = email.trim().length > 0 && password.length > 0 && !sending && wait <= 0;
  return (
    <>
      <PageHeader title={t.title} lead={t.lead} />
      <Container className="py-10">
        <div className="max-w-md space-y-4">
          {expired && problem === null ? (
            <Alert tone="info" title={t.expiredTitle} role="status">
              {t.expiredBody}
            </Alert>
          ) : null}
          <form onSubmit={(event) => void onSubmit(event)} className="space-y-4" noValidate>
            <div className="space-y-1">
              <label htmlFor={emailId} className="block text-sm font-semibold">
                {t.email}
              </label>
              <input
                id={emailId}
                type="email"
                autoComplete="username"
                maxLength={MAX_EMAIL}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                aria-describedby={problem ? errorId : undefined}
                className="block w-full rounded-control border border-line bg-surface px-3 py-2 text-base"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor={passwordId} className="block text-sm font-semibold">
                {t.password}
              </label>
              <input
                id={passwordId}
                type="password"
                autoComplete="current-password"
                maxLength={MAX_PASSWORD}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                aria-describedby={problem ? errorId : undefined}
                className="block w-full rounded-control border border-line bg-surface px-3 py-2 text-base"
              />
            </div>
            {problem ? (
              <div id={errorId}>
                <Alert tone="danger" title={t.errors[problem.kind] ?? t.errors.unexpected ?? ""} role="alert">
                  {wait > 0 ? t.waitSeconds(wait) : null}
                </Alert>
              </div>
            ) : null}
            <Button type="submit" disabled={!canSubmit}>
              {sending ? t.submitting : t.submit}
            </Button>
          </form>
        </div>
      </Container>
    </>
  );
}
