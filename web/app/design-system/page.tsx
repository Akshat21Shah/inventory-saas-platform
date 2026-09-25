import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { DesignSystemShowcase } from "./showcase";

export const metadata: Metadata = { title: "Design system", robots: { index: false } };

export default function DesignSystemPage() {
  if (process.env.NODE_ENV === "production" && process.env.ENABLE_DESIGN_SYSTEM !== "true")
    notFound();
  return <DesignSystemShowcase />;
}
