"use client";

import type { Option } from "@/components/catalog/options";
import { useSuppliersList } from "@/lib/api/generated/endpoints/purchasing/purchasing";

/** Active suppliers to pick from (the first 100 by name; enough for a pick list). */
export function useSupplierOptions(enabled = true): Option[] {
  const query = useSuppliersList({ active: true, page_size: 100 }, { query: { enabled } });
  return (query.data?.data.results ?? []).map((s) => ({ value: s.id, label: s.name }));
}
