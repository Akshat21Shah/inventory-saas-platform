"use client";

import { useAuth } from "@/components/auth/auth-provider";
import type { Option } from "@/components/catalog/options";
import { languages } from "@/lib/i18n/config";
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

/** The languages this business may use (ADR-060), plus a shop's saved one if it's not among them
 * any more, so the form still shows what is saved. */
export function useLanguageOptions(saved?: string): Option[] {
  const { me } = useAuth();
  const codes = new Set((me?.languages ?? []).map((l) => l.code));
  if (saved) codes.add(saved);
  return languages
    .filter((l) => codes.has(l.code))
    .map((l) => ({ value: l.code, label: l.native }));
}
