import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { useMe } from "@/api/auth";
import { Layout } from "@/components/Layout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { CrowdTaskQueue } from "@/pages/CrowdTaskQueue";
import { DashboardPage } from "@/pages/DashboardPage";
import { DeadLetterQueue } from "@/pages/DeadLetterQueue";
import { JobsPage } from "@/pages/JobsPage";
import { LoginPage } from "@/pages/LoginPage";
import { PipelineDesigner } from "@/pages/PipelineDesigner";
import { PipelineReleases } from "@/pages/PipelineReleases";
import { PipelineRunDetail } from "@/pages/PipelineRunDetail";
import { PipelineRunsList } from "@/pages/PipelineRunsList";
import { SqlStudio } from "@/pages/SqlStudio";
import { RawObjectsPage } from "@/pages/RawObjectsPage";
import { RuntimeMonitor } from "@/pages/RuntimeMonitor";
import { AdminPartitionsPage } from "@/pages/AdminPartitionsPage";
import { ApiKeysPage } from "@/pages/ApiKeysPage";
import { MasterMergePage } from "@/pages/MasterMergePage";
import { SecurityEventsPage } from "@/pages/SecurityEventsPage";
import { SourcesPage } from "@/pages/SourcesPage";
import { UsersPage } from "@/pages/UsersPage";
import { DryRunResults } from "@/pages/v2/DryRunResults";
import { EtlCanvasV2 } from "@/pages/v2/EtlCanvasV2";
import { FieldMappingDesigner } from "@/pages/v2/FieldMappingDesigner";
import { InboundChannelDesigner } from "@/pages/v2/InboundChannelDesigner";
import { MartDesigner } from "@/pages/v2/MartDesigner";
import { MockApiPage } from "@/pages/v2/MockApiPage";
import { OperationsDashboard } from "@/pages/v2/OperationsDashboard";
import { PublishApproval } from "@/pages/v2/PublishApproval";
import { QualityWorkbench } from "@/pages/v2/QualityWorkbench";
import { ServiceMartViewer } from "@/pages/v2/ServiceMartViewer";
import { SourceApiDesigner } from "@/pages/v2/SourceApiDesigner";
import { TransformDesigner } from "@/pages/v2/TransformDesigner";
import { useAuthStore } from "@/store/auth";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});

function MeBootstrapper() {
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  // 토큰은 있지만 user 정보가 없을 때만 /me 조회.
  const me = useMe(!!accessToken && !user);
  useEffect(() => {
    if (me.error) {
      // 토큰이 만료되었거나 무효 — apiClient 가 401 시 자동 로그아웃.
    }
  }, [me.error]);
  return null;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <MeBootstrapper />
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          <Route element={<ProtectedRoute />}>
            <Route element={<Layout />}>
              <Route index element={<DashboardPage />} />
              <Route path="/sources" element={<SourcesPage />} />
              <Route path="/jobs" element={<JobsPage />} />
              <Route path="/raw-objects" element={<RawObjectsPage />} />
              <Route path="/pipelines/runs" element={<PipelineRunsList />} />
              <Route
                path="/pipelines/runs/:runId"
                element={<PipelineRunDetail />}
              />
              <Route path="/pipelines/releases" element={<PipelineReleases />} />
              <Route path="/runtime" element={<RuntimeMonitor />} />
            </Route>
          </Route>

          <Route
            element={
              <ProtectedRoute requireAnyRole={["ADMIN", "REVIEWER", "APPROVER"]} />
            }
          >
            <Route element={<Layout />}>
              <Route path="/crowd-tasks" element={<CrowdTaskQueue />} />
            </Route>
          </Route>

          <Route
            element={<ProtectedRoute requireAnyRole={["ADMIN", "APPROVER"]} />}
          >
            <Route element={<Layout />}>
              <Route path="/pipelines/designer" element={<PipelineDesigner />} />
              <Route
                path="/pipelines/designer/:workflowId"
                element={<PipelineDesigner />}
              />
              <Route path="/v2/pipelines/designer" element={<EtlCanvasV2 />} />
              <Route
                path="/v2/pipelines/designer/:workflowId"
                element={<EtlCanvasV2 />}
              />
              <Route path="/master-merge" element={<MasterMergePage />} />
            </Route>
          </Route>

          {/* Phase 6 Wave 1 — v2 Source/API Designer (workbench 1) */}
          <Route
            element={
              <ProtectedRoute
                requireAnyRole={["ADMIN", "APPROVER", "OPERATOR"]}
              />
            }
          >
            <Route element={<Layout />}>
              <Route
                path="/v2/connectors/public-api"
                element={<SourceApiDesigner />}
              />
              <Route
                path="/v2/inbound-channels/designer"
                element={<InboundChannelDesigner />}
              />
              <Route
                path="/v2/mappings/designer"
                element={<FieldMappingDesigner />}
              />
              <Route
                path="/v2/transforms/designer"
                element={<TransformDesigner />}
              />
              <Route
                path="/v2/quality/designer"
                element={<QualityWorkbench />}
              />
              <Route
                path="/v2/marts/designer"
                element={<MartDesigner />}
              />
              <Route
                path="/v2/operations/dashboard"
                element={<OperationsDashboard />}
              />
              <Route
                path="/v2/service-mart"
                element={<ServiceMartViewer />}
              />
              <Route path="/v2/mock-api" element={<MockApiPage />} />
              <Route
                path="/v2/dryrun/workflow/:workflowId"
                element={<DryRunResults />}
              />
              <Route
                path="/v2/publish/:entityType/:entityId"
                element={<PublishApproval />}
              />
            </Route>
          </Route>

          <Route
            element={
              <ProtectedRoute requireAnyRole={["ADMIN", "APPROVER", "OPERATOR"]} />
            }
          >
            <Route element={<Layout />}>
              <Route path="/sql-studio" element={<SqlStudio />} />
            </Route>
          </Route>

          <Route element={<ProtectedRoute requireRole="ADMIN" />}>
            <Route element={<Layout />}>
              <Route path="/users" element={<UsersPage />} />
              <Route path="/api-keys" element={<ApiKeysPage />} />
              <Route path="/security-events" element={<SecurityEventsPage />} />
              <Route path="/admin/partitions" element={<AdminPartitionsPage />} />
              <Route path="/dead-letters" element={<DeadLetterQueue />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" richColors closeButton />
    </QueryClientProvider>
  );
}
