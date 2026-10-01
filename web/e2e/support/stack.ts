import { execFileSync } from "node:child_process";
import { createHmac, randomInt } from "node:crypto";
import { resolve } from "node:path";

/**
 * Helpers for the full-stack specs (backend, worker, Mailpit and the seed must be running).
 * Every value here is a public demo value from `make seed`.
 */
export const FULL_STACK = Boolean(process.env.E2E_FULL_STACK);
const BASE_URL = new URL(process.env.E2E_BASE_URL ?? "http://localhost:3000");
export const PORT = BASE_URL.port || "3000";
/** `localhost`, or the dev stack's LAN domain (`make lan`, e.g. 192-168-0-106.nip.io) when
 * E2E_BASE_URL names it, so the suites also run without switching the stack back. */
const DOMAIN = BASE_URL.hostname;
export const MAILPIT = process.env.E2E_MAILPIT_URL ?? "http://localhost:8025";
export const ADMIN = {
  email: "admin@platform.local",
  password: "admin-dev-password",
  totpSecret: process.env.E2E_ADMIN_TOTP_SECRET ?? "DEVSEEDADMINTOTPKEYDEVSEEDADMIN2",
};
export const OTP_CODE = "123456"; // dev mock SMS (OTP_FIXED_CODE)
export const SHOP_PHONES = ["9876500000", "9876500001", "9876500002"];

/**
 * Run a dev-only backend management command and return its output. Override the prefix with
 * E2E_MANAGE_COMMAND (everything up to and including `manage.py`) when the stack is not the local
 * docker compose one.
 */
export function manage(args: string[]): string {
  const base = process.env.E2E_MANAGE_COMMAND
    ? process.env.E2E_MANAGE_COMMAND.split(" ")
    : [
        "docker",
        "compose",
        "-f",
        resolve(__dirname, "../../../infra/docker-compose.yml"),
        "exec",
        "-T",
        "backend",
        "python",
        "manage.py",
      ];
  return execFileSync(base[0]!, [...base.slice(1), ...args], {
    stdio: "pipe",
    maxBuffer: 64 * 1024 * 1024,
  }).toString();
}

/**
 * Clear rate-limit counters, lockouts and 2FA replay state for test accounts (dev-only backend
 * command), so runs and retries never depend on a time window.
 */
export function resetLimits({
  emails = [],
  phones = [],
}: {
  emails?: string[];
  phones?: string[];
}) {
  manage([
    "reset_e2e_limits",
    ...emails.flatMap((email) => ["--email", email]),
    ...phones.flatMap((phone) => ["--phone", phone]),
  ]);
}

/** A real .xlsx import file made by the backend (dev-only `e2e_workbook` command). */
export function workbook(args: string[]): Buffer {
  return Buffer.from(manage(["e2e_workbook", ...args]).trim(), "base64");
}

export const origin = (sub?: string) => `http://${sub ? `${sub}.` : ""}${DOMAIN}:${PORT}`;

function base32(secret: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secret.replace(/=+$/, "")) {
    bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

export interface TotpState {
  server_time: number; // seconds since the epoch, by the backend's clock
  server_step: number;
  last_step: number | null; // the last step the account used (replay protection)
}

/** The backend's clock and the account's last accepted 2FA step (dev-only command). */
export function totpState(email: string): TotpState {
  return JSON.parse(manage(["e2e_totp_state", "--email", email])) as TotpState;
}

export interface SentCode {
  code: string;
  step: number;
  clientMinusServer: number; // seconds this machine's clock is ahead of the backend's
}

/**
 * A 2FA code the backend will accept now, whatever the state of the clocks (issue: a Mac that
 * slept leaves Docker's VM clock minutes behind until its next time sync):
 * - computed for the backend's clock, not this machine's;
 * - never for a step the account already used (replay protection): wait for the next step;
 * - never in the last 3 seconds of a step, so it can't expire in flight.
 */
export async function freshTotp(secret: string, email: string): Promise<SentCode> {
  for (;;) {
    const state = totpState(email);
    const intoStep = state.server_time % 30;
    const used = state.last_step !== null && state.server_step <= state.last_step;
    if (!used && intoStep < 27) {
      return {
        code: totp(secret, state.server_time * 1000),
        step: state.server_step,
        clientMinusServer: Date.now() / 1000 - state.server_time,
      };
    }
    await new Promise((resolve) => setTimeout(resolve, (30 - intoStep + 0.5) * 1000));
  }
}

/** Why the backend refused a code we sent: replay, clock skew or an invalid code. */
export function explainRefusal(sent: SentCode, email: string): string {
  const state = totpState(email);
  const skew = Date.now() / 1000 - state.server_time;
  const reason =
    state.last_step !== null && sent.step <= state.last_step
      ? `replay: step ${sent.step} was already used (last used ${state.last_step})`
      : Math.abs(state.server_step - sent.step) > 1
        ? `clock skew: sent for step ${sent.step}, the server is at step ${state.server_step}`
        : "invalid code for the server's step (wrong key?)";
  return `${reason}; this machine's clock is ${skew.toFixed(1)}s ahead of the backend's`;
}

/** RFC 6238 code for the current 30-second step. */
export function totp(secret: string, now = Date.now()): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(now / 30_000)));
  const hmac = createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = hmac[hmac.length - 1]! & 15;
  return String((hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

const GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";

/** A checksum-valid, random GSTIN for Maharashtra (27) with a company PAN. */
export function randomGstin(): string {
  const letter = () => String.fromCharCode(65 + randomInt(26));
  const pan = `${letter()}${letter()}${letter()}C${letter()}${String(randomInt(10_000)).padStart(4, "0")}${letter()}`;
  const first14 = `27${pan}1Z`;
  let sum = 0;
  for (let i = 0; i < 14; i++) {
    const product = GSTIN_CHARS.indexOf(first14[i]!) * (i % 2 ? 2 : 1);
    sum += Math.floor(product / 36) + (product % 36);
  }
  return first14 + GSTIN_CHARS[(36 - (sum % 36)) % 36];
}

interface MailpitSummary {
  ID: string;
}

/** The first link in the newest email to `to` matching `pattern`, polling while the worker sends. */
export async function linkFromEmail(to: string, pattern: RegExp): Promise<string> {
  for (let attempt = 0; attempt < 40; attempt++) {
    const search = await fetch(
      `${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}`,
    );
    const { messages } = (await search.json()) as { messages: MailpitSummary[] };
    if (messages.length > 0) {
      const message = await fetch(`${MAILPIT}/api/v1/message/${messages[0]!.ID}`);
      const { Text, HTML } = (await message.json()) as { Text: string; HTML: string };
      const found = `${Text}\n${HTML}`.match(pattern);
      if (found) return found[0].replace(/&amp;/g, "&");
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`No email to ${to} with a link matching ${pattern}`);
}
