import { Navigate, Route, Routes } from "react-router";
import { AuthProvider } from "./auth/AuthProvider";
import { RequireRole } from "./auth/RequireRole";
import { Layout } from "./components/Layout";
import AboutPage from "./pages/AboutPage";
import { AdminCatalogPage } from "./pages/AdminCatalogPage";
import { AdminBookingsPage, AdminLayout, AdminQuotesPage } from "./pages/AdminPages";
import ChatPage from "./pages/ChatPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import MyQuotesPage from "./pages/MyQuotesPage";
import NotFoundPage from "./pages/NotFoundPage";
import PortfolioPage from "./pages/PortfolioPage";
import ServicesPage from "./pages/ServicesPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="quienes-somos" element={<AboutPage />} />
        <Route path="portafolio" element={<PortfolioPage />} />
        <Route path="servicios" element={<ServicesPage />} />
        <Route path="cotizar" element={<ChatPage />} />
        <Route path="ingresar" element={<LoginPage />} />
        <Route element={<RequireRole roles={["client", "admin"]} />}>
          <Route path="mis-cotizaciones" element={<MyQuotesPage />} />
        </Route>
        <Route path="admin" element={<RequireRole roles={["admin"]} />}>
          <Route element={<AdminLayout />}>
            <Route index element={<Navigate to="cotizaciones" replace />} />
            <Route path="cotizaciones" element={<AdminQuotesPage />} />
            <Route path="catalogo" element={<AdminCatalogPage />} />
            <Route path="reservas" element={<AdminBookingsPage />} />
          </Route>
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
      </Routes>
    </AuthProvider>
  );
}
