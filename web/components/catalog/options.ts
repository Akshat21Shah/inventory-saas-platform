"use client";

import {
  useCatalogBrandsList,
  useCatalogCategoriesTree,
  useCatalogTaxOptions,
  useCatalogUnitsList,
} from "@/lib/api/generated/endpoints/catalog/catalog";
import { formatQty } from "@/lib/format";

export interface Option {
  value: string;
  label: string;
}

export interface TreeNode {
  id: string;
  name: string;
  level: number;
  sort_order?: number;
  product_count?: number;
  children: TreeNode[];
}

/** The server sends children as plain objects; they have the same shape as the node. */
export function asTree(nodes: readonly unknown[] | undefined): TreeNode[] {
  return (nodes ?? []) as TreeNode[];
}

/** Every category as "Food › Biscuits › Cream", in tree order. */
export function flattenTree(nodes: TreeNode[], trail: string[] = []): Option[] {
  return nodes.flatMap((node) => {
    const path = [...trail, node.name];
    return [{ value: node.id, label: path.join(" › ") }, ...flattenTree(node.children, path)];
  });
}

export function useCategoryOptions(): Option[] {
  const query = useCatalogCategoriesTree();
  return flattenTree(asTree(query.data?.data));
}

export function useBrandOptions(): Option[] {
  const query = useCatalogBrandsList({ page_size: 200 });
  return (query.data?.data.results ?? []).map((b) => ({ value: b.id, label: b.name }));
}

export function useUnitOptions(): Option[] {
  const query = useCatalogUnitsList({ page_size: 200 });
  return (query.data?.data.results ?? [])
    .filter((u) => u.is_active !== false)
    .map((u) => ({ value: u.id, label: `${u.code} · ${u.name}` }));
}

export function percent(value: string): string {
  return `${formatQty(value)}%`;
}

export function useTaxOptions() {
  const query = useCatalogTaxOptions();
  const data = query.data?.data;
  return {
    gstRates: (data?.gst_rates ?? []).map((r) => ({ value: r.rate, label: percent(r.rate) })),
    cessTypes: (data?.cess_types ?? []).map((c) => ({ value: c.id, label: c.name })),
  };
}
