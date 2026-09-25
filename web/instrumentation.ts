// Server-side error monitoring (Node + edge runtimes). Only active when SENTRY_DSN is set.
import * as Sentry from "@sentry/nextjs";

export function register() {
  const dsn = process.env.SENTRY_DSN;
  if (!dsn) return;
  Sentry.init({
    dsn,
    environment: process.env.ENVIRONMENT ?? "local",
    tracesSampleRate: 0,
  });
}

export const onRequestError = Sentry.captureRequestError;
