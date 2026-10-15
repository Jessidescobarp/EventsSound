import { Navigate, Outlet, useLocation } from "react-router";
import type { Role } from "../api/auth";
import { ButtonLink } from "../components/ui/Button";
import { Alert } from "../components/ui/Alert";
import { Container } from "../components/ui/Container";
import { es } from "../copy/es";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useAuth } from "./authContext";

/**
 * Route guard. This only decides what the UI shows: the API enforces every permission.
 * Signed out visitors go to the login page and come back to where they were headed.
 */
export function RequireRole({ roles }: { roles: readonly Role[] }) {
  const { session } = useAuth();
  const location = useLocation();
  if (session === null) {
    return <Navigate to="/ingresar" replace state={{ from: location.pathname }} />;
  }
  if (!roles.includes(session.role)) return <Forbidden />;
  return <Outlet />;
}

function Forbidden() {
  useDocumentTitle(es.titles.forbidden);
  return (
    <Container className="py-14">
      <div className="max-w-xl space-y-4">
        <Alert tone="warn" title={es.auth.forbiddenTitle} role="alert">
          {es.auth.forbiddenBody}
        </Alert>
        <ButtonLink to="/" variant="secondary">
          {es.auth.backHome}
        </ButtonLink>
      </div>
    </Container>
  );
}
