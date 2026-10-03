// Synced from web/lib/api/errors.ts by scripts/sync-from-web.mjs (npm run sync). Do not edit.
/** API error envelope: {"error": {"code", "message", "details"}} (CLAUDE.md §5). */

export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
  }

  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500;
  }
}

export const NETWORK_ERROR = "NETWORK_ERROR";
export const UNKNOWN_ERROR = "UNKNOWN_ERROR";

export function isErrorBody(value: unknown): value is { error: ApiErrorBody } {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return typeof error === "object" && error !== null && "code" in error && "message" in error;
}

/** i18n key for any thrown value; users never see raw technical errors. */
export function errorMessageKey(error: unknown, knownCodes: ReadonlySet<string>): string {
  const code =
    error instanceof ApiError
      ? error.code
      : error instanceof TypeError
        ? NETWORK_ERROR
        : UNKNOWN_ERROR;
  return knownCodes.has(code) ? `errors.${code}` : `errors.${UNKNOWN_ERROR}`;
}
