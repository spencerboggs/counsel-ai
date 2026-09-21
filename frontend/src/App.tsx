import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/layouts/AppShell";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { DiscoverPage } from "@/features/stocks/DiscoverPage";
import { FoundStocksPage } from "@/features/stocks/FoundStocksPage";
import { StockDetailPage } from "@/features/stocks/StockDetailPage";
import { TradePage } from "@/features/stocks/TradePage";
import { PortfolioPage } from "@/features/portfolio/PortfolioPage";
import { AutopilotPage } from "@/features/autopilot/AutopilotPage";
import { TaxLedgerPage } from "@/features/tax/TaxLedgerPage";
import { CompliancePage } from "@/features/tax/CompliancePage";
import { ModelsPage } from "@/features/models/ModelsPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { applyTheme, getStoredTheme } from "@/lib/theme";

applyTheme(getStoredTheme());

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="stocks/discover" element={<DiscoverPage />} />
          <Route path="stocks/found" element={<FoundStocksPage />} />
          <Route path="stocks/trade" element={<TradePage />} />
          <Route path="stocks/portfolio" element={<PortfolioPage />} />
          <Route path="stocks/view/:ticker" element={<StockDetailPage />} />
          <Route path="autopilot" element={<AutopilotPage />} />
          <Route path="tax" element={<TaxLedgerPage />} />
          <Route path="compliance" element={<CompliancePage />} />
          <Route path="research" element={<Navigate to="/" replace />} />
          <Route path="evidence" element={<Navigate to="/" replace />} />
          <Route path="models" element={<ModelsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
