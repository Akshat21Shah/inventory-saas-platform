import { BrowserPayPage } from "@/components/shop/browser-pay";

/** The Android app's payment page (ADR-061 item 9): outside the shop's menus and sign-in. */
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <BrowserPayPage intentId={id} />;
}
