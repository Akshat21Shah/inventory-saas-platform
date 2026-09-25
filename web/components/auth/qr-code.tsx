"use client";

import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";

/** QR code for an otpauth:// URI, rendered in the browser (the secret never leaves the page). */
export function QrCode({ value, label }: { value: string; label: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    QRCode.toString(value, { type: "svg", margin: 1, errorCorrectionLevel: "M" })
      .then((markup) => active && setSvg(markup))
      .catch(() => active && setSvg(null));
    return () => {
      active = false;
    };
  }, [value]);
  if (!svg) return <Skeleton className="size-48" />;
  return (
    <div
      role="img"
      aria-label={label}
      className="size-48 rounded-lg border bg-white p-2"
      // Generated locally by the qrcode library from the otpauth URI: no external markup.
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
