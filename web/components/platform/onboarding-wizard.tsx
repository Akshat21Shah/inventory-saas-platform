"use client";

import { Check, ChevronLeft, ChevronRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { FormField } from "@/components/shared/form-field";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  platformTenantsCreate,
  platformTenantsSlugAvailable,
  usePlatformPlansList,
} from "@/lib/api/generated/endpoints/platform/platform";
import {
  usePublicLanguages,
  usePublicStatesList,
} from "@/lib/api/generated/endpoints/public/public";
import type { OnboardingRequest } from "@/lib/api/generated/model";
import { useErrorText } from "@/lib/api/use-error-text";
import { useTranslations } from "@/lib/i18n/translations";
import { DEFAULT_BRAND_COLOR, isHexColor } from "@/lib/theme/palette";
import { cn, omitKey } from "@/lib/utils";

type Values = Required<Omit<OnboardingRequest, "plan_code" | "primary_color">> & {
  plan_code: string;
  primary_color: string;
};

// The owner's invitation email: blank sends it in the super admin's own language (ADR-060).
const YOURS = "yours";

const STEPS = [
  { id: "company", fields: ["name", "legal_name", "email", "phone"] },
  {
    id: "gst",
    fields: ["gstin", "state_code", "address_line1", "address_line2", "city", "pincode"],
  },
  { id: "owner", fields: ["owner_name", "owner_email", "owner_language"] },
  { id: "address", fields: ["slug", "primary_color"] },
  { id: "plan", fields: ["plan_code"] },
  { id: "review", fields: [] },
] as const;

const EMPTY: Values = {
  name: "",
  legal_name: "",
  email: "",
  phone: "",
  gstin: "",
  state_code: "",
  address_line1: "",
  address_line2: "",
  city: "",
  pincode: "",
  owner_name: "",
  owner_email: "",
  owner_language: "",
  slug: "",
  primary_color: DEFAULT_BRAND_COLOR,
  plan_code: "",
};

// Light checks for quick feedback only; the server validates everything (GSTIN checksum, etc.).
const QUICK: Partial<Record<keyof Values, RegExp>> = {
  email: /^\S+@\S+\.\S+$/,
  owner_email: /^\S+@\S+\.\S+$/,
  gstin: /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/,
  pincode: /^[1-9][0-9]{5}$/,
  slug: /^[a-z0-9][a-z0-9-]{1,28}[a-z0-9]$/,
  phone: /^\+?[0-9]{10,15}$/,
};
const OPTIONAL = new Set<keyof Values>([
  "address_line2",
  "owner_name",
  "owner_language",
  "primary_color",
  "plan_code",
]);

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 30);
}

/** Onboarding wizard (spec 5.1): creates the distributor, its Beta plan and the owner invitation
 * in one server transaction on the last step. */
export function OnboardingWizard() {
  const t = useTranslations("platform.onboarding");
  const errors = useErrorText();
  const router = useRouter();
  const states = usePublicStatesList();
  const languages = usePublicLanguages();
  const plans = usePlatformPlansList();
  const [step, setStep] = useState(0);
  const [values, setValues] = useState<Values>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [slugTouched, setSlugTouched] = useState(false);
  const [slugFree, setSlugFree] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (field: keyof Values, value: string) => {
    setValues((v) => ({ ...v, [field]: value }));
    setFieldErrors((current) => omitKey(current, field));
  };

  // Suggest a web address from the business name until the admin edits it.
  const suggested = slugTouched ? values.slug : slugify(values.name);
  const slug = suggested;
  useEffect(() => {
    if (!QUICK.slug!.test(slug)) return;
    const timer = window.setTimeout(() => {
      platformTenantsSlugAvailable({ slug })
        .then((r) => setSlugFree(r.data.available))
        .catch(() => setSlugFree(null));
    }, 350);
    return () => window.clearTimeout(timer);
  }, [slug]);

  const current = STEPS[step]!;
  const derivedState = QUICK.gstin!.test(values.gstin) ? values.gstin.slice(0, 2) : "";
  const effective: Values = { ...values, slug, state_code: values.state_code || derivedState };

  function validateStep(index: number): boolean {
    const missing: Record<string, string> = {};
    for (const field of STEPS[index]!.fields as readonly (keyof Values)[]) {
      const value = effective[field].trim();
      if (!value && !OPTIONAL.has(field)) missing[field] = t("required");
      else if (value && QUICK[field] && !QUICK[field]!.test(value))
        missing[field] = t(`invalid.${field}`);
    }
    if (index === 3 && slugFree === false) missing.slug = t("slugTaken");
    setFieldErrors(missing);
    return Object.keys(missing).length === 0;
  }

  async function create() {
    setBusy(true);
    try {
      const body: OnboardingRequest = {
        ...effective,
        gstin: effective.gstin.toUpperCase(),
        plan_code: effective.plan_code || null,
        primary_color: isHexColor(effective.primary_color) ? effective.primary_color : null,
      };
      const response = await platformTenantsCreate(body);
      toast.success(t("created", { name: response.data.name }));
      router.push(`/platform/tenants/${response.data.id}`);
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(fields);
      const first = STEPS.findIndex((s) =>
        (s.fields as readonly string[]).some((f) => f in fields),
      );
      if (first >= 0) setStep(first);
      else toast.error(errors.message(err));
    } finally {
      setBusy(false);
    }
  }

  const field = (
    name: keyof Values,
    props: { type?: string; hint?: string; upper?: boolean } = {},
  ) => (
    <FormField
      label={t(`fields.${name}`)}
      hint={props.hint}
      error={fieldErrors[name]}
      required={!OPTIONAL.has(name)}
    >
      <Input
        type={props.type ?? "text"}
        className="h-10"
        value={name === "slug" ? slug : values[name]}
        onChange={(e) => {
          if (name === "slug") setSlugTouched(true);
          // A GSTIN is often copied with spaces ("29 AAGFK 7315R 1ZL"); the server removes them too.
          const raw = name === "gstin" ? e.target.value.replace(/\s+/g, "") : e.target.value;
          set(name, props.upper ? raw.toUpperCase() : raw);
        }}
      />
    </FormField>
  );

  return (
    <>
      <PageHeader title={t("title")} description={t("body")} />
      <ol className="mb-6 flex flex-wrap gap-2" aria-label={t("progress")}>
        {STEPS.map((s, index) => (
          <li
            key={s.id}
            aria-current={index === step ? "step" : undefined}
            className={cn(
              "flex items-center gap-2 rounded-full border px-3 py-1 text-sm",
              index === step && "border-primary bg-brand-50 text-brand-900 font-medium",
              index < step && "text-muted-foreground",
            )}
          >
            {index < step ? (
              <Check aria-hidden className="size-3.5" />
            ) : (
              <span aria-hidden>{index + 1}</span>
            )}
            {t(`steps.${s.id}`)}
          </li>
        ))}
      </ol>
      <Card>
        <CardContent className="grid gap-4 py-6 sm:grid-cols-2">
          {current.id === "company" ? (
            <>
              {field("name", { hint: t("hints.name") })}
              {field("legal_name")}
              {field("email", { type: "email" })}
              {field("phone", { type: "tel" })}
            </>
          ) : null}
          {current.id === "gst" ? (
            <>
              {field("gstin", { upper: true, hint: t("hints.gstin") })}
              <FormField label={t("fields.state_code")} error={fieldErrors.state_code} required>
                <Select value={effective.state_code} onValueChange={(v) => set("state_code", v)}>
                  <SelectTrigger className="min-h-10 w-full">
                    <SelectValue placeholder={t("choose")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(states.data?.data ?? []).map((s) => (
                      <SelectItem key={s.code} value={s.code}>
                        {s.code} · {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              {field("address_line1")}
              {field("address_line2")}
              {field("city")}
              {field("pincode")}
            </>
          ) : null}
          {current.id === "owner" ? (
            <>
              {field("owner_name")}
              {field("owner_email", { type: "email", hint: t("hints.owner_email") })}
              <FormField label={t("fields.owner_language")} hint={t("hints.owner_language")}>
                <Select
                  value={values.owner_language || YOURS}
                  onValueChange={(v) => set("owner_language", v === YOURS ? "" : v)}
                >
                  <SelectTrigger className="min-h-10 w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={YOURS}>{t("yourLanguage")}</SelectItem>
                    {(languages.data?.data ?? [])
                      .filter((option) => option.enabled)
                      .map((option) => (
                        <SelectItem key={option.code} value={option.code} lang={option.code}>
                          {option.native}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </FormField>
            </>
          ) : null}
          {current.id === "address" ? (
            <>
              <div className="space-y-1">
                {field("slug", {
                  hint: t("hints.slug", {
                    domain:
                      typeof window !== "undefined"
                        ? window.location.hostname.replace(/^admin\./, "")
                        : "",
                  }),
                })}
                {slugFree === true && QUICK.slug!.test(slug) ? (
                  <p className="text-success-strong text-xs">{t("slugFree")}</p>
                ) : null}
              </div>
              <FormField label={t("fields.primary_color")} hint={t("hints.primary_color")}>
                <div className="flex items-center gap-3">
                  <input
                    type="color"
                    aria-label={t("fields.primary_color")}
                    className="size-10 cursor-pointer rounded border"
                    value={
                      isHexColor(values.primary_color) ? values.primary_color : DEFAULT_BRAND_COLOR
                    }
                    onChange={(e) => set("primary_color", e.target.value)}
                  />
                  <span className="font-mono text-sm">{values.primary_color}</span>
                </div>
              </FormField>
            </>
          ) : null}
          {current.id === "plan" ? (
            <FormField
              label={t("fields.plan_code")}
              hint={t("hints.plan_code")}
              error={fieldErrors.plan_code}
            >
              <Select
                value={values.plan_code || "default"}
                onValueChange={(v) => set("plan_code", v === "default" ? "" : v)}
              >
                <SelectTrigger className="min-h-10 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">{t("defaultPlan")}</SelectItem>
                  {(plans.data?.data ?? [])
                    .filter((p) => p.is_active)
                    .map((p) => (
                      <SelectItem key={p.code} value={p.code}>
                        {p.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </FormField>
          ) : null}
          {current.id === "review" ? (
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:col-span-2 sm:grid-cols-[12rem_1fr]">
              {(Object.keys(EMPTY) as (keyof Values)[]).map((key) => (
                <div key={key} className="contents">
                  <dt className="text-muted-foreground">{t(`fields.${key}`)}</dt>
                  <dd className="font-medium break-all">
                    {key === "plan_code"
                      ? effective.plan_code || t("defaultPlan")
                      : key === "owner_language"
                        ? (languages.data?.data ?? []).find((l) => l.code === effective[key])
                            ?.native || t("yourLanguage")
                        : effective[key] || "—"}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
        </CardContent>
      </Card>
      <div className="mt-6 flex justify-between gap-2">
        <Button
          variant="outline"
          disabled={step === 0 || busy}
          onClick={() => setStep((s) => s - 1)}
          className="min-h-10"
        >
          <ChevronLeft aria-hidden />
          {t("back")}
        </Button>
        {current.id === "review" ? (
          <Button onClick={() => void create()} disabled={busy} className="min-h-10">
            {t("create")}
          </Button>
        ) : (
          <Button
            className="min-h-10"
            onClick={() => {
              if (validateStep(step)) setStep((s) => s + 1);
            }}
          >
            {t("next")}
            <ChevronRight aria-hidden />
          </Button>
        )}
      </div>
    </>
  );
}
