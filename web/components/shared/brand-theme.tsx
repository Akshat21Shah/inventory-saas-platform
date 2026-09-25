import { brandStyleSheet, DEFAULT_BRAND_COLOR, isHexColor } from "@/lib/theme/palette";

/**
 * Injects the tenant brand palette as CSS variables. The colour is validated as #rrggbb, so the
 * generated stylesheet cannot carry arbitrary CSS. Phase 1 passes the tenant's colour from the API.
 */
export function BrandTheme({ color = DEFAULT_BRAND_COLOR }: { color?: string }) {
  const safe = isHexColor(color) ? color : DEFAULT_BRAND_COLOR;
  return <style id="brand-theme" dangerouslySetInnerHTML={{ __html: brandStyleSheet(safe) }} />;
}
