"use client";

import { useAuth } from "@/components/auth/auth-provider";
import type { Option } from "@/components/catalog/options";
import { usePriceListsList } from "@/lib/api/generated/endpoints/pricing/pricing";
import { usePublicStatesList } from "@/lib/api/generated/endpoints/public/public";
import { useRetailersSalespeople } from "@/lib/api/generated/endpoints/retailers/retailers";

export function usePriceListOptions(): Option[] {
  const { can } = useAuth();
  const query = usePriceListsList({ page_size: 200 }, { query: { enabled: can("pricing.view") } });
  return (query.data?.data.results ?? []).map((p) => ({ value: p.id, label: p.name }));
}

export function useSalespeopleOptions(): Option[] {
  const query = useRetailersSalespeople();
  return (query.data?.data ?? []).map((p) => ({ value: p.id, label: p.full_name || p.email }));
}

export function useStateOptions(): Option[] {
  const query = usePublicStatesList();
  return (query.data?.data ?? []).map((s) => ({ value: s.code, label: `${s.code} · ${s.name}` }));
}

export const LANGUAGES: Option[] = [
  { value: "en", label: "English" },
  { value: "hi", label: "हिन्दी" },
  { value: "mr", label: "मराठी" },
];
