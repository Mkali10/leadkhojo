import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ApiError } from "@/api/client";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/layout/ErrorBoundary";
import { BusinessDetailPage } from "@/pages/BusinessDetailPage";
import { ComparePage } from "@/pages/ComparePage";
import { DashboardPage } from "@/pages/DashboardPage";
import { NewScanPage } from "@/pages/NewScanPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { PluginsPage } from "@/pages/PluginsPage";
import { ScanDetailPage } from "@/pages/ScanDetailPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Retrying a 404 or a 422 just delays showing the user the answer. Only
      // genuine transport or server faults are worth a second attempt.
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status < 500) return false;
        return failureCount < 2;
      },
      staleTime: 5_000,
      refetchOnWindowFocus: false,
    },
    mutations: { retry: false },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ErrorBoundary>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<DashboardPage />} />
              <Route path="scans/new" element={<NewScanPage />} />
              <Route path="scans/:scanId" element={<ScanDetailPage />} />
              <Route path="businesses/:businessId" element={<BusinessDetailPage />} />
              <Route path="compare" element={<ComparePage />} />
              <Route path="plugins" element={<PluginsPage />} />
              <Route path="scans" element={<Navigate to="/" replace />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </ErrorBoundary>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
