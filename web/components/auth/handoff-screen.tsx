"use client";

import Link from "next/link";
import { useTranslations } from "@/lib/i18n/translations";
import { useEffect, useRef, useState } from "react";

import { PageSkeleton } from "@/components/shared/skeletons";
import { ApiError } from "@/lib/api/errors";
import { authHandoffExchange } from "@/lib/api/generated/endpoints/auth/auth";
import { useErrorText } from "@/lib/api/use-error-text";

import { AuthCard } from "./auth-card";
import { EnrolStep, RecoveryCodesStep, useSignInFlow } from "./sign-in-flow";

/** Receives a sign-in moved from another host (ADR-020) or a support session (ADR-029). The code
 * arrives in the URL fragment and is removed from the address bar at once. */
export function HandoffScreen() {
  const t = useTranslations("auth");
  const errors = useErrorText();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  const [next, setNext] = useState<string | null>(null);
  const flow = useSignInFlow({ next, handoffNext: "/manage" });

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const params = new URLSearchParams(window.location.hash.slice(1));
    window.history.replaceState(null, "", window.location.pathname);
    const exchange = async () => {
      const code = params.get("code");
      setNext(params.get("next"));
      if (!code) throw new ApiError(400, { code: "TOKEN_INVALID", message: "", details: {} });
      await flow.apply((await authHandoffExchange({ code })).data);
    };
    exchange().catch((err: unknown) => setError(errors.message(err)));
  }, [errors, flow]);

  if (error) {
    return (
      <AuthCard title={t("handoff.failedTitle")}>
        <p role="alert" className="text-muted-foreground">
          {error}
        </p>
        <Link href="/login" className="text-primary underline-offset-4 hover:underline">
          {t("backToSignIn")}
        </Link>
      </AuthCard>
    );
  }
  if (flow.step.kind === "enrol") {
    return (
      <AuthCard title={t("enrol.title")}>
        <EnrolStep enrolmentToken={flow.step.enrolmentToken} onResult={flow.apply} />
      </AuthCard>
    );
  }
  if (flow.step.kind === "recoveryCodes") {
    const { codes, destination } = flow.step;
    return (
      <AuthCard title={t("recovery.title")}>
        <RecoveryCodesStep codes={codes} onDone={() => flow.leave(destination)} />
      </AuthCard>
    );
  }
  return <PageSkeleton />;
}
