"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function BackTo({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Button asChild variant="ghost" className="mb-2 -ml-3 min-h-10">
      <Link href={href}>
        <ArrowLeft aria-hidden />
        {children}
      </Link>
    </Button>
  );
}

/** A small figure card; clickable when it filters or leads somewhere. */
export function CountCard({
  label,
  value,
  onClick,
  href,
  active,
  tone,
}: {
  label: string;
  value: ReactNode;
  onClick?: () => void;
  href?: string;
  active?: boolean;
  tone?: "warning" | "danger" | "info";
}) {
  const body = (
    <Card
      className={cn(
        "h-full transition-colors",
        (onClick || href) && "hover:bg-muted",
        active && "border-brand-400 bg-brand-50",
      )}
    >
      <CardContent className="py-4">
        <p className="text-muted-foreground text-sm">{label}</p>
        <p
          className={cn(
            "text-2xl font-semibold tabular-nums",
            tone === "warning" && "text-warning-strong",
            tone === "danger" && "text-destructive",
            tone === "info" && "text-info-strong",
          )}
        >
          {value}
        </p>
      </CardContent>
    </Card>
  );
  if (href) {
    return (
      <Link href={href} className="block min-h-11 rounded-xl">
        {body}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-pressed={active}
        className="block min-h-11 w-full rounded-xl text-left"
      >
        {body}
      </button>
    );
  }
  return body;
}
