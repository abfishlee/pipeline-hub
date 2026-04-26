// Phase 8 — Service Mart Viewer client.
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../client";

export interface StdProduct {
  std_product_code: string;
  std_product_name: string;
  category: string | null;
  unit_kind: string | null;
  description: string | null;
}

export interface ServicePriceRow {
  price_id: number;
  std_product_code: string | null;
  std_product_name: string | null;
  retailer_code: string;
  retailer_product_code: string;
  product_name: string;
  display_name: string | null;
  price_normal: string | null;
  price_promo: string | null;
  promo_type: string | null;
  promo_start: string | null;
  promo_end: string | null;
  stock_qty: number | null;
  stock_status: string | null;
  unit: string | null;
  origin: string | null;
  grade: string | null;
  standardize_confidence: string | null;
  needs_review: boolean;
  collected_at: string;
}

export interface ChannelStats {
  retailer_code: string;
  row_count: number;
  products_with_promo: number;
  avg_confidence: string | null;
  needs_review_count: number;
}

export function useStdProducts() {
  return useQuery({
    queryKey: ["v2-service-mart-std"],
    queryFn: () =>
      apiRequest<StdProduct[]>("/v2/service-mart/std-products"),
  });
}

export function useServicePrices(params: {
  std_product_code?: string;
  retailer_code?: string;
  limit?: number;
} = {}) {
  return useQuery({
    queryKey: ["v2-service-mart-prices", params],
    queryFn: () =>
      apiRequest<ServicePriceRow[]>("/v2/service-mart/prices", {
        params: { ...params },
      }),
  });
}

export function useChannelStats() {
  return useQuery({
    queryKey: ["v2-service-mart-stats"],
    queryFn: () => apiRequest<ChannelStats[]>("/v2/service-mart/channel-stats"),
    refetchInterval: 30_000,
  });
}
