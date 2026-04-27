// Phase 8 — Service Mart Viewer (가상 데이터 시연 화면).
//
// 4 가상 유통사 (이마트/홈플러스/롯데마트/하나로마트) 데이터가 동일 구조로 모인
// service_mart.product_price 통합 조회.
//
// 화면 구성:
//   상단: 채널별 통계 카드 (row_count / promo / avg_confidence / review)
//   좌측: 표준 품목 (std_product) 목록
//   우측: 선택된 품목의 4 유통사 가격 비교 표 또는 전체 목록
import {
  AlertTriangle,
  CheckCircle2,
  Filter,
  Package,
  ShoppingCart,
  Tag,
  XCircle,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  type ServicePriceRow,
  useChannelStats,
  useServicePrices,
  useStdProducts,
} from "@/api/v2/service_mart";
import { PriceCompareCard } from "@/components/service_mart/PriceCompareCard";
import { PriceSummaryCard } from "@/components/service_mart/PriceSummaryCard";
import { PriceTrendChart } from "@/components/service_mart/PriceTrendChart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";

const RETAILER_LABELS: Record<string, string> = {
  emart: "이마트",
  homeplus: "홈플러스",
  lottemart: "롯데마트",
  hanaro: "하나로마트",
};

const RETAILER_COLORS: Record<string, string> = {
  emart: "bg-yellow-100 text-yellow-900",
  homeplus: "bg-red-100 text-red-900",
  lottemart: "bg-rose-100 text-rose-900",
  hanaro: "bg-green-100 text-green-900",
};

function formatPrice(p: string | null | undefined): string {
  if (p == null) return "—";
  const n = Number(p);
  if (isNaN(n)) return p;
  return new Intl.NumberFormat("ko-KR").format(n) + "원";
}

function stockBadge(s: string | null) {
  if (!s) return <Badge variant="muted">—</Badge>;
  if (s === "OUT_OF_STOCK") return <Badge variant="destructive">품절</Badge>;
  if (s === "IN_STOCK") return <Badge variant="success">판매중</Badge>;
  return <Badge variant="muted">{s}</Badge>;
}

function promoBadge(p: ServicePriceRow): React.ReactNode {
  if (!p.promo_type) return <span className="text-xs text-muted-foreground">—</span>;
  const labels: Record<string, string> = {
    CARD_DISCOUNT: "카드할인",
    ONE_PLUS_ONE: "1+1",
    PERIOD_DISCOUNT: "기간할인",
  };
  return (
    <Badge variant="warning">{labels[p.promo_type] ?? p.promo_type}</Badge>
  );
}

export function ServiceMartViewer() {
  const stats = useChannelStats();
  const std = useStdProducts();
  const [selectedStd, setSelectedStd] = useState<string | null>(null);
  const [retailerFilter, setRetailerFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  // Phase 8.4 — 시연용 필터 토글
  const [onlyPromo, setOnlyPromo] = useState(false);
  const [onlyOutOfStock, setOnlyOutOfStock] = useState(false);
  const [onlyNeedsReview, setOnlyNeedsReview] = useState(false);
  const prices = useServicePrices({
    std_product_code: selectedStd ?? undefined,
    retailer_code: retailerFilter || undefined,
    limit: 200,
  });

  const filteredPrices = useMemo(() => {
    if (!prices.data) return [];
    let rows = prices.data;
    if (search) {
      const q = search.toLowerCase();
      rows = rows.filter(
        (p) =>
          p.product_name.toLowerCase().includes(q) ||
          p.retailer_product_code.toLowerCase().includes(q) ||
          (p.display_name?.toLowerCase().includes(q) ?? false),
      );
    }
    if (onlyPromo) {
      rows = rows.filter((p) => p.price_promo && Number(p.price_promo) > 0);
    }
    if (onlyOutOfStock) {
      rows = rows.filter((p) => p.stock_status === "OUT_OF_STOCK");
    }
    if (onlyNeedsReview) {
      rows = rows.filter((p) => p.needs_review);
    }
    return rows;
  }, [prices.data, search, onlyPromo, onlyOutOfStock, onlyNeedsReview]);

  const selectedStdName = useMemo(() => {
    if (!selectedStd || !std.data) return null;
    return (
      std.data.find((p) => p.std_product_code === selectedStd)
        ?.std_product_name ?? null
    );
  }, [selectedStd, std.data]);

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Service Mart Viewer</h2>
        <p className="text-sm text-muted-foreground">
          4 가상 유통사 (이마트 / 홈플러스 / 롯데마트 / 하나로마트) 통합 가격 마트.
          Phase 8 Synthetic Data Service Rehearsal.
        </p>
      </div>

      {/* Channel stats */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {(stats.data ?? []).map((s) => (
          <Card key={s.retailer_code}>
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-xs">
                <ShoppingCart className="h-4 w-4 text-primary" />
                <span className="font-semibold">
                  {RETAILER_LABELS[s.retailer_code] ?? s.retailer_code}
                </span>
              </div>
              <div className="mt-1 text-2xl font-semibold">
                {s.row_count.toLocaleString()}
              </div>
              <div className="mt-0.5 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
                <span>행사 {s.products_with_promo}</span>
                <span>·</span>
                <span>
                  conf {s.avg_confidence ? Number(s.avg_confidence).toFixed(2) : "—"}
                </span>
                {s.needs_review_count > 0 && (
                  <>
                    <span>·</span>
                    <span className="text-amber-600">
                      <AlertTriangle className="inline h-2.5 w-2.5" />
                      검수 {s.needs_review_count}
                    </span>
                  </>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
        {(!stats.data || stats.data.length === 0) && (
          <Card className="col-span-4">
            <CardContent className="p-6 text-sm text-muted-foreground">
              아직 service_mart 데이터가 없습니다. seed script 실행 필요:
              <br />
              <code className="text-xs">
                python ../scripts/phase8_seed_synthetic_data.py
              </code>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Phase 8.4 — 표준품목 선택 시 가격 요약 카드 */}
      {selectedStd && filteredPrices.length > 0 && (
        <PriceSummaryCard
          prices={filteredPrices}
          stdProductName={selectedStdName}
        />
      )}

      {/* Phase 8.1/8.2 — 표준품목 선택 시 4 유통사 비교 + 추이 차트 */}
      {selectedStd && filteredPrices.length > 0 && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <PriceCompareCard
            prices={filteredPrices}
            stdProductName={selectedStdName}
          />
          <PriceTrendChart
            prices={filteredPrices}
            stdProductName={selectedStdName}
          />
        </div>
      )}

      {/* Filter row */}
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="text-xs text-muted-foreground">유통사</label>
              <select
                className="mt-1 h-9 w-44 rounded-md border bg-background px-3 text-sm"
                value={retailerFilter}
                onChange={(e) => setRetailerFilter(e.target.value)}
              >
                <option value="">전체</option>
                <option value="emart">이마트</option>
                <option value="homeplus">홈플러스</option>
                <option value="lottemart">롯데마트</option>
                <option value="hanaro">하나로마트</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">검색</label>
              <Input
                className="w-60"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="상품명 / 코드"
              />
            </div>
            <div className="ml-auto text-xs text-muted-foreground">
              <Filter className="inline h-3 w-3" /> {filteredPrices.length} rows
            </div>
          </div>
          {/* Phase 8.4 — 시연용 필터 토글 */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button
              type="button"
              onClick={() => setOnlyPromo(!onlyPromo)}
              className={cn(
                "rounded-md border px-2 py-0.5",
                onlyPromo
                  ? "border-rose-400 bg-rose-50 text-rose-700"
                  : "border-border hover:bg-secondary",
              )}
            >
              할인 중만
            </button>
            <button
              type="button"
              onClick={() => setOnlyOutOfStock(!onlyOutOfStock)}
              className={cn(
                "rounded-md border px-2 py-0.5",
                onlyOutOfStock
                  ? "border-zinc-500 bg-zinc-100 text-zinc-700"
                  : "border-border hover:bg-secondary",
              )}
            >
              품절만
            </button>
            <button
              type="button"
              onClick={() => setOnlyNeedsReview(!onlyNeedsReview)}
              className={cn(
                "rounded-md border px-2 py-0.5",
                onlyNeedsReview
                  ? "border-amber-400 bg-amber-50 text-amber-700"
                  : "border-border hover:bg-secondary",
              )}
            >
              검수 필요만
            </button>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-4 gap-4">
        {/* Std products sidebar */}
        <Card className="col-span-1">
          <CardContent className="space-y-1 p-2">
            <div className="px-2 py-1 text-xs font-semibold uppercase text-muted-foreground">
              표준 품목 ({std.data?.length ?? 0})
            </div>
            <button
              type="button"
              onClick={() => setSelectedStd(null)}
              className={cn(
                "flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left text-xs",
                !selectedStd
                  ? "border-primary bg-primary/10"
                  : "border-transparent hover:bg-secondary",
              )}
            >
              <Package className="h-3.5 w-3.5" />
              <span>전체</span>
            </button>
            {std.data?.map((p) => (
              <button
                key={p.std_product_code}
                type="button"
                onClick={() => setSelectedStd(p.std_product_code)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left text-xs",
                  selectedStd === p.std_product_code
                    ? "border-primary bg-primary/10"
                    : "border-transparent hover:bg-secondary",
                )}
              >
                <Tag className="h-3.5 w-3.5 text-muted-foreground" />
                <div className="flex-1">
                  <div className="font-semibold">{p.std_product_name}</div>
                  <div className="text-[10px] text-muted-foreground">
                    {p.category} · <code>{p.std_product_code}</code>
                  </div>
                </div>
              </button>
            ))}
          </CardContent>
        </Card>

        {/* Price table */}
        <Card className="col-span-3">
          <CardContent className="p-0">
            {prices.isLoading && (
              <div className="p-6 text-sm text-muted-foreground">불러오는 중...</div>
            )}
            {filteredPrices.length === 0 && !prices.isLoading && (
              <div className="p-6 text-sm text-muted-foreground">
                데이터가 없습니다.
              </div>
            )}
            {filteredPrices.length > 0 && (
              <Table>
                <Thead>
                  <Tr>
                    <Th>표준품목</Th>
                    <Th>유통사</Th>
                    <Th>상품명</Th>
                    <Th>정상가</Th>
                    <Th>행사가</Th>
                    <Th>행사</Th>
                    <Th>재고</Th>
                    <Th>산지</Th>
                    <Th>등급</Th>
                    <Th>conf</Th>
                    <Th>수집</Th>
                    <Th>원천</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {filteredPrices.map((p) => (
                    <Tr key={p.price_id}>
                      <Td className="text-xs">
                        {p.std_product_name ?? (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </Td>
                      <Td>
                        <span
                          className={cn(
                            "rounded px-2 py-0.5 text-[10px]",
                            RETAILER_COLORS[p.retailer_code] ?? "bg-muted",
                          )}
                        >
                          {RETAILER_LABELS[p.retailer_code] ?? p.retailer_code}
                        </span>
                      </Td>
                      <Td className="max-w-xs">
                        <div className="text-xs">{p.product_name}</div>
                        {p.display_name && p.display_name !== p.product_name && (
                          <div className="text-[10px] text-muted-foreground">
                            {p.display_name}
                          </div>
                        )}
                        <code className="text-[10px] text-muted-foreground">
                          {p.retailer_product_code}
                        </code>
                      </Td>
                      <Td className="whitespace-nowrap text-xs">
                        {formatPrice(p.price_normal)}
                      </Td>
                      <Td className="whitespace-nowrap text-xs">
                        {p.price_promo ? (
                          <span className="font-semibold text-rose-600">
                            {formatPrice(p.price_promo)}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </Td>
                      <Td>{promoBadge(p)}</Td>
                      <Td>{stockBadge(p.stock_status)}</Td>
                      <Td className="text-xs">{p.origin ?? "—"}</Td>
                      <Td className="text-xs">{p.grade ?? "—"}</Td>
                      <Td className="text-xs">
                        {p.standardize_confidence ? (
                          <span
                            className={cn(
                              Number(p.standardize_confidence) < 0.85
                                ? "text-amber-600"
                                : "",
                            )}
                          >
                            {Number(p.standardize_confidence).toFixed(2)}
                            {p.needs_review && (
                              <AlertTriangle className="ml-0.5 inline h-3 w-3 text-amber-600" />
                            )}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </Td>
                      <Td className="text-[10px] text-muted-foreground">
                        {formatDateTime(p.collected_at)}
                      </Td>
                      <Td className="text-[10px]">
                        {/* Phase 8.2 — lineage 링크: 해당 유통사 raw / workflow */}
                        <Link
                          to={`/raw-objects?source_code=${p.retailer_code}_src`}
                          className="text-primary hover:underline"
                          title="이 row 의 원천 raw_object 조회"
                        >
                          raw
                        </Link>
                        {" · "}
                        <Link
                          to={`/v2/operations/dashboard`}
                          className="text-primary hover:underline"
                          title="이 채널의 운영 상태"
                        >
                          ops
                        </Link>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      <p className="text-[11px] text-muted-foreground">
        ※ Phase 8 Synthetic Data — 실제 운영 데이터처럼 보이도록 4 가상 유통사
        + 표준 품목 + 행사 + 재고 + 산지/등급/단위 + 검수 큐 (
        <CheckCircle2 className="inline h-3 w-3" /> 정상 /
        <XCircle className="inline h-3 w-3" /> 오류) 패턴을 모두 시드.
      </p>
    </div>
  );
}
