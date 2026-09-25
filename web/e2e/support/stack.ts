import { execFileSync } from "node:child_process";
import { createHmac, randomInt } from "node:crypto";
import { resolve } from "node:path";

/**
 * Helpers for the full-stack specs (backend, worker, Mailpit and the seed must be running).
 * Every value here is a public demo value from `make seed`.
 */
export const FULL_STACK = Boolean(process.env.E2E_FULL_STACK);
export const PORT = new URL(process.env.E2E_BASE_URL ?? "http://localhost:3000").port || "3000";
export const MAILPIT = process.env.E2E_MAILPIT_URL ?? "http://localhost:8025";
export const ADMIN = {
  email: "admin@platform.local",
  password: "admin-dev-password",
  totpSecret: process.env.E2E_ADMIN_TOTP_SECRET ?? "DEVSEEDADMINTOTPKEYDEVSEEDADMIN2",
};
export const OTP_CODE = "123456"; // dev mock SMS (OTP_FIXED_CODE)
export const SHOP_PHONES = ["9876500000", "9876500001", "9876500002"];

/**
 * Clear rate-limit counters, lockouts and 2FA replay state for test accounts (dev-only backend
 * command), so runs and retries never depend on a time window. Override the command with
 * E2E_RESET_COMMAND when the stack is not the local docker compose one.
 */
export function resetLimits({
  emails = [],
  phones = [],
}: {
  emails?: string[];
  phones?: string[];
}) {
  const base = process.env.E2E_RESET_COMMAND
    ? process.env.E2E_RESET_COMMAND.split(" ")
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
        "reset_e2e_limits",
      ];
  const args = [
    ...emails.flatMap((email) => ["--email", email]),
    ...phones.flatMap((phone) => ["--phone", phone]),
  ];
  execFileSync(base[0]!, [...base.slice(1), ...args], { stdio: "pipe" });
}

export const origin = (sub?: string) => `http://${sub ? `${sub}.` : ""}localhost:${PORT}`;

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
