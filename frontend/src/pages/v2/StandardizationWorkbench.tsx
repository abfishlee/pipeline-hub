import { ArrowRight, BookOpen, CheckCircle2, GitMerge, Ruler, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useDomains } from "@/api/v2/domains";
import { useNamespaceCodes, useNamespaces } from "@/api/v2/namespaces";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";

const FLOW = [
  { label: "Field Mapping", desc: "JSONB key를 평탄 컬럼으로 꺼냅니다." },
  { label: "Transform", desc: "값을 계산, 파싱, 보강합니다." },
  { label: "Standardization", desc: "표준코드, 표준명, 표준단위로 맞춥니다." },
  { label: "DQ / Quality", desc: "표준화 결과가 맞는지 검증합니다." },
  { label: "Mart", desc: "서비스용 마트에 적재합니다." },
];

const RULE_TYPES = [
  {
    icon: BookOpen,
    title: "Code namespace",
    desc: "품목, 단위, 지역, 판매상태처럼 표준코드 체계를 namespace로 관리합니다.",
  },
  {
    icon: GitMerge,
    title: "Alias mapping",
    desc: "원천 값의 별칭을 표준코드에 연결합니다. 예: 사과/부사/apple -> APPLE.",
  },
  {
    icon: Ruler,
    title: "Unit normalization",
    desc: "g, kg, 묶음, 팩 같은 단위를 표준 단위와 환산 계수로 맞춥니다.",
  },
  {
    icon: Sparkles,
    title: "Candidate matching",
    desc: "exact, alias, trigram, embedding, external API 순서로 후보를 만들고 confidence를 기록합니다.",
  },
];

export function StandardizationWorkbench() {
  const domains = useDomains();
  const [domainCode, setDomainCode] = useState("agri_price");
  const namespaces = useNamespaces(domainCode || undefined);
  const [selectedNamespaceId, setSelectedNamespaceId] = useState<number | null>(null);
  const codes = useNamespaceCodes(selectedNamespaceId, 200);

  const selectedNamespace = useMemo(
    () => namespaces.data?.find((n) => n.namespace_id === selectedNamespaceId) ?? null,
    [namespaces.data, selectedNamespaceId],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Standardization Rules</h2>
          <p className="max-w-4xl text-sm text-muted-foreground">
            원천별 표현을 서비스 공통 기준으로 맞추는 설계 영역입니다. 값 변환은 Transform에서,
            표준코드/표준단위 귀속은 Standardization에서, 검증은 DQ / Quality에서 관리합니다.
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/v2/transforms/designer">
            <Button variant="outline">
              Transform
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
          <Link to="/v2/quality/designer">
            <Button variant="outline">
              Quality Rules
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        </div>
      </div>

      <Card>
        <CardContent className="grid gap-3 p-4 md:grid-cols-5">
          {FLOW.map((step, index) => (
            <div key={step.label} className="rounded-md border p-3">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Badge variant={step.label === "Standardization" ? "default" : "muted"}>
                  {index + 1}
                </Badge>
                {step.label}
              </div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">{step.desc}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <Card>
          <CardContent className="space-y-4 p-4">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <label className="text-xs text-muted-foreground">Domain</label>
                <select
                  className="mt-1 h-9 w-56 rounded-md border bg-background px-3 text-sm"
                  value={domainCode}
                  onChange={(e) => {
                    setDomainCode(e.target.value);
                    setSelectedNamespaceId(null);
                  }}
                >
                  {(domains.data ?? []).map((d) => (
                    <option key={d.domain_code} value={d.domain_code}>
                      {d.domain_code} ({d.name})
                    </option>
                  ))}
                </select>
              </div>
              <Badge variant="muted">STANDARDIZE node asset</Badge>
            </div>

            <div>
              <div className="mb-2 text-sm font-semibold">Standard code namespaces</div>
              {namespaces.isLoading && (
                <div className="rounded-md border p-4 text-sm text-muted-foreground">Loading...</div>
              )}
              {namespaces.data?.length === 0 && (
                <div className="rounded-md border p-4 text-sm text-muted-foreground">
                  아직 namespace가 없습니다. 다음 단계에서는 여기서 품목/단위/지역 같은 표준코드 체계를
                  생성하고 alias를 등록할 수 있게 확장합니다.
                </div>
              )}
              {(namespaces.data?.length ?? 0) > 0 && (
                <Table>
                  <Thead>
                    <Tr>
                      <Th>Name</Th>
                      <Th>Code table</Th>
                      <Th></Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {namespaces.data?.map((ns) => (
                      <Tr key={ns.namespace_id}>
                        <Td>
                          <div className="font-medium">{ns.name}</div>
                          {ns.description && (
                            <div className="text-xs text-muted-foreground">{ns.description}</div>
                          )}
                        </Td>
                        <Td>
                          <code className="text-xs">{ns.std_code_table ?? "-"}</code>
                        </Td>
                        <Td>
                          <Button
                            variant={selectedNamespaceId === ns.namespace_id ? "secondary" : "ghost"}
                            size="sm"
                            onClick={() => setSelectedNamespaceId(ns.namespace_id)}
                          >
                            Preview
                          </Button>
                        </Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              )}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardContent className="space-y-3 p-4">
              <div className="flex items-center gap-2 font-semibold">
                <CheckCircle2 className="h-4 w-4 text-primary" />
                Rule design model
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {RULE_TYPES.map((item) => (
                  <div key={item.title} className="rounded-md border p-3">
                    <div className="flex items-center gap-2 text-sm font-semibold">
                      <item.icon className="h-4 w-4 text-primary" />
                      {item.title}
                    </div>
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">{item.desc}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-3 p-4">
              <div className="font-semibold">
                {selectedNamespace ? `${selectedNamespace.name} preview` : "Standard code preview"}
              </div>
              {!selectedNamespace && (
                <div className="text-sm text-muted-foreground">
                  왼쪽에서 namespace를 선택하면 표준코드 샘플을 확인할 수 있습니다.
                </div>
              )}
              {selectedNamespace && codes.isLoading && (
                <div className="text-sm text-muted-foreground">Loading codes...</div>
              )}
              {selectedNamespace && (codes.data?.length ?? 0) === 0 && (
                <div className="text-sm text-muted-foreground">표준코드 row가 없습니다.</div>
              )}
              {(codes.data?.length ?? 0) > 0 && (
                <Table>
                  <Thead>
                    <Tr>
                      <Th>std_code</Th>
                      <Th>display_name</Th>
                      <Th>description</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {codes.data?.slice(0, 20).map((row) => (
                      <Tr key={row.std_code}>
                        <Td>
                          <code className="text-xs">{row.std_code}</code>
                        </Td>
                        <Td>{row.display_name ?? "-"}</Td>
                        <Td className="text-xs text-muted-foreground">{row.description ?? "-"}</Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
