"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Headset, Mail, Pencil, Play, ShieldOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { AuditTable } from "@/components/shared/audit-table";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { FormField } from "@/components/shared/form-field";
import { KpiCard } from "@/components/shared/kpi-card";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { PageSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  platformImpersonationsStart,
  platformTenantFeatureSet,
  platformTenantOwnerResendInvite,
  platformTenantSubscriptionUpdate,
  platformTenantsReactivate,
  platformTenantsSuspend,
  platformTenantsUpdate,
  usePlatformAuditLogs,
  usePlatformFeatureFlagsList,
  usePlatformPlansList,
  usePlatformTenantSubscription,
  usePlatformTenantUsers,
  usePlatformTenantsRetrieve,
} from "@/lib/api/generated/endpoints/platform/platform";
import type { Membership, TenantDetail as Detail } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { handoffUrl } from "@/lib/auth/urls";

const EDITABLE = [
  "name",
  "legal_name",
  "gstin",
  "state_code",
  "address_line1",
  "address_line2",
  "city",
  "pincode",
  "email",
  "phone",
  "slug",
] as const;

function EditDialog({ tenant, onSaved }: { tenant: Detail; onSaved: () => void }) {
  const t = useTranslations("platform");
  const tc = useTranslations("common");
  const errors = useErrorText();
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState(() =>
    Object.fromEntries(EDITABLE.map((f) => [f, String(tenant[f] ?? "")])),
  );
  const [confirmSlug, setConfirmSlug] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const slugChanged = values.slug !== tenant.slug;

  async function save(event: FormEvent) {
    event.preventDefault();
    const changes = Object.fromEntries(
      EDITABLE.filter((f) => values[f] !== String(tenant[f] ?? "")).map((f) => [f, values[f]]),
    );
    try {
      await platformTenantsUpdate(tenant.id, { ...changes, confirm_slug_change: confirmSlug });
      toast.success(t("detail.saved"));
      setOpen(false);
      onSaved();
    } catch (err) {
      const fields = errors.fields(err);
      setFieldErrors(fields);
      if (Object.keys(fields).length === 0) toast.error(errors.message(err));
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" className="min-h-10">
          <Pencil aria-hidden />
          {t("detail.edit")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <form onSubmit={save} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{t("detail.editTitle")}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            {EDITABLE.map((f) => (
              <FormField key={f} label={t(`onboarding.fields.${f}`)} error={fieldErrors[f]}>
                <Input
                  className="h-10"
                  value={values[f]}
                  onChange={(e) =>
                    setValues((v) => ({
                      ...v,
                      [f]: f === "gstin" ? e.target.value.toUpperCase() : e.target.value,
                    }))
                  }
                />
              </FormField>
            ))}
          </div>
          {slugChanged ? (
            <label className="bg-warning/15 flex items-start gap-2 rounded-lg p-3 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 size-4"
                checked={confirmSlug}
                onChange={(e) => setConfirmSlug(e.target.checked)}
              />
              {t("detail.slugWarning")}
            </label>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              {tc("cancel")}
            </Button>
            <Button type="submit" disabled={slugChanged && !confirmSlug}>
              {t("detail.saveChanges")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Overview({ tenant, refresh }: { tenant: Detail; refresh: () => void }) {
  const t = useTranslations("platform");
  // Dialog actions: the dialogs show failures themselves.
  const run = async (action: () => Promise<unknown>, done: string) => {
    await action();
    toast.success(done);
    refresh();
  };
  const rows: [string, string][] = [
    [t("onboarding.fields.legal_name"), tenant.legal_name],
    [t("onboarding.fields.gstin"), tenant.gstin],
    [t("onboarding.fields.state_code"), tenant.state_code],
    [
      t("detail.address"),
      [tenant.address_line1, tenant.address_line2, tenant.city, tenant.pincode]
        .filter(Boolean)
        .join(", "),
    ],
    [t("onboarding.fields.email"), tenant.email],
    [t("onboarding.fields.phone"), tenant.phone],
    [t("onboarding.fields.slug"), tenant.slug],
  ];
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        <EditDialog tenant={tenant} onSaved={refresh} />
        {tenant.status === "ONBOARDING" ? (
          <ConfirmDialog
            trigger={
              <Button variant="outline" className="min-h-10">
                <Mail aria-hidden />
                {t("detail.resendInvite")}
              </Button>
            }
            title={t("detail.resendTitle", { email: tenant.owner?.email ?? "" })}
            description={t("detail.resendBody")}
            confirmLabel={t("detail.resendInvite")}
            onConfirm={() =>
              run(() => platformTenantOwnerResendInvite(tenant.id), t("detail.inviteResent"))
            }
          />
        ) : null}
        {tenant.status === "SUSPENDED" ? (
          <ConfirmDialog
            trigger={
              <Button className="min-h-10">
                <Play aria-hidden />
                {t("detail.reactivate")}
              </Button>
            }
            title={t("detail.reactivateTitle", { name: tenant.name })}
            confirmLabel={t("detail.reactivate")}
            onConfirm={() =>
              run(() => platformTenantsReactivate(tenant.id), t("detail.reactivated"))
            }
          />
        ) : (
          <ReasonDialog
            trigger={
              <Button variant="destructive" className="min-h-10">
                <ShieldOff aria-hidden />
                {t("detail.suspend")}
              </Button>
            }
            destructive
            title={t("detail.suspendTitle", { name: tenant.name })}
            description={t("detail.suspendBody")}
            reasonLabel={t("detail.reason")}
            confirmLabel={t("detail.suspend")}
            onConfirm={(reason) =>
              run(() => platformTenantsSuspend(tenant.id, { reason }), t("detail.suspended"))
            }
          />
        )}
      </div>
      {tenant.status === "SUSPENDED" && tenant.suspended_reason ? (
        <p className="bg-destructive/5 border-destructive/30 rounded-lg border p-3 text-sm">
          {t("detail.suspendedBecause", { reason: tenant.suspended_reason })}
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-3">
        <KpiCard label={t("detail.staff")} value={tenant.usage.staff} />
        <KpiCard label={t("detail.retailers")} value={tenant.usage.retailers} />
        <KpiCard label={t("detail.pendingInvitations")} value={tenant.usage.pending_invitations} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>
              <h2 className="text-base">{t("detail.business")}</h2>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[10rem_1fr] gap-y-2 text-sm">
              {rows.map(([label, value]) => (
                <div key={label} className="contents">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="break-all">{value || "—"}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>
              <h2 className="text-base">{t("detail.owner")}</h2>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {tenant.owner ? (
              <>
                <p className="font-medium">{tenant.owner.full_name || tenant.owner.email}</p>
                <p className="text-muted-foreground">{tenant.owner.email}</p>
                <p>{t(`detail.ownerStatus.${tenant.owner.status}`)}</p>
              </>
            ) : (
              <p className="text-muted-foreground">—</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Modules({ tenant, refresh }: { tenant: Detail; refresh: () => void }) {
  const t = useTranslations("platform");
  const errors = useErrorText();
  const catalogue = usePlatformFeatureFlagsList();
  const [pending, setPending] = useState<string | null>(null);
  return (
    <Card>
      <CardContent className="divide-y py-2">
        {(catalogue.data?.data ?? []).map((flag) => (
          <div key={flag.code} className="flex items-center justify-between gap-4 py-3">
            <div>
              <p className="font-medium">{flag.name}</p>
              <p className="text-muted-foreground text-sm">{flag.description}</p>
            </div>
            <Switch
              aria-label={flag.name}
              checked={Boolean(tenant.features[flag.code ?? ""])}
              disabled={pending === flag.code}
              onCheckedChange={async (enabled) => {
                setPending(flag.code ?? null);
                try {
                  await platformTenantFeatureSet(tenant.id, flag.code ?? "", { enabled });
                  refresh();
                } catch (err) {
                  toast.error(errors.message(err));
                } finally {
                  setPending(null);
                }
              }}
            />
          </div>
        ))}
        {catalogue.error ? <ErrorState error={catalogue.error} /> : null}
        <p className="text-muted-foreground pt-3 text-xs">{t("detail.modulesNote")}</p>
      </CardContent>
    </Card>
  );
}

function PlanTab({ tenant }: { tenant: Detail }) {
  const t = useTranslations("platform");
  const errors = useErrorText();
  const plans = usePlatformPlansList();
  const subscription = usePlatformTenantSubscription(tenant.id);
  const current = subscription.data?.data;
  return (
    <Card>
      <CardContent className="space-y-4 py-6">
        <p>
          {t("detail.currentPlan")}: <strong>{current?.plan.name ?? "—"}</strong>
          {current?.starts_at ? (
            <span className="text-muted-foreground">
              {" · "}
              {t("detail.since")} <DateText value={current.starts_at} />
            </span>
          ) : null}
        </p>
        <FormField label={t("detail.changePlan")}>
          <Select
            value={current?.plan.code ?? ""}
            onValueChange={async (code) => {
              try {
                await platformTenantSubscriptionUpdate(tenant.id, { plan_code: code });
                toast.success(t("detail.planChanged"));
                void subscription.refetch();
              } catch (err) {
                toast.error(errors.message(err));
              }
            }}
          >
            <SelectTrigger className="min-h-10 w-full sm:w-72">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
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
        <p className="text-muted-foreground text-xs">{t("detail.planNote")}</p>
      </CardContent>
    </Card>
  );
}

function Users({ tenant }: { tenant: Detail }) {
  const t = useTranslations("platform");
  const cursor = useCursor();
  const query = usePlatformTenantUsers(tenant.id, { cursor: cursor.cursor });
  const page = query.data?.data;
  const columns: DataTableColumn<Membership>[] = [
    {
      id: "name",
      header: t("detail.person"),
      cell: ({ row }) => row.original.user.full_name || row.original.user.email,
    },
    {
      id: "email",
      header: t("onboarding.fields.email"),
      cell: ({ row }) => row.original.user.email,
    },
    { id: "role", header: t("detail.role"), cell: ({ row }) => row.original.role.name },
    {
      id: "active",
      header: t("tenants.status"),
      cell: ({ row }) => <StatusBadge status={row.original.is_active ? "ACTIVE" : "INACTIVE"} />,
    },
    {
      id: "act",
      header: "",
      cell: ({ row }) =>
        row.original.is_active && tenant.status !== "ONBOARDING" ? (
          <ReasonDialog
            trigger={
              <Button variant="outline" size="sm" className="min-h-9">
                <Headset aria-hidden />
                {t("detail.actAs")}
              </Button>
            }
            title={t("detail.actAsTitle", {
              name: row.original.user.full_name || row.original.user.email,
            })}
            description={t("detail.actAsBody")}
            reasonLabel={t("detail.reason")}
            confirmLabel={t("detail.startSession")}
            onConfirm={async (reason) => {
              // Open the tab first (popup blockers allow it only inside the click), then point it
              // at the tenant's subdomain with the one-time code.
              const tab = window.open("about:blank", "_blank");
              const started = await platformImpersonationsStart({
                tenant_id: tenant.id,
                user_id: row.original.user.id,
                reason,
              });
              const next = started.data.target_type === "RETAILER" ? "/shop" : "/manage";
              const url = handoffUrl(started.data.tenant_slug, started.data.handoff_code, next);
              if (tab) tab.location.href = url;
              else window.location.assign(url);
            }}
          />
        ) : null,
    },
  ];
  return (
    <DataTable
      columns={columns}
      data={page?.results ?? []}
      getRowId={(row) => row.id}
      isLoading={query.isLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      pagination={cursor.pagination(page)}
      empty={{ title: t("detail.noStaff") }}
    />
  );
}

function TenantAudit({ tenant }: { tenant: Detail }) {
  const [filter, setFilter] = useState("");
  const cursor = useCursor();
  const query = usePlatformAuditLogs({
    tenant_id: tenant.id,
    action: filter || undefined,
    cursor: cursor.cursor,
  });
  const page = query.data?.data;
  return (
    <AuditTable
      rows={page?.results ?? []}
      isLoading={query.isLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      filter={filter}
      onFilterChange={(value) => {
        setFilter(value);
        cursor.reset();
      }}
      pagination={cursor.pagination(page)}
    />
  );
}

export function TenantDetail({ tenantId }: { tenantId: string }) {
  const t = useTranslations("platform");
  const queryClient = useQueryClient();
  const query = usePlatformTenantsRetrieve(tenantId);
  const refresh = () => void queryClient.invalidateQueries();
  if (query.isLoading) return <PageSkeleton />;
  if (query.error || !query.data)
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const tenant = query.data.data;
  return (
    <>
      <PageHeader
        title={tenant.name}
        description={`${tenant.slug} · ${tenant.gstin}`}
        actions={<StatusBadge status={tenant.status} />}
      />
      <Tabs defaultValue="overview">
        <TabsList className="mb-4 flex h-auto flex-wrap">
          {["overview", "modules", "plan", "users", "audit"].map((tab) => (
            <TabsTrigger key={tab} value={tab} className="min-h-9">
              {t(`detail.tabs.${tab}`)}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="overview">
          <Overview tenant={tenant} refresh={refresh} />
        </TabsContent>
        <TabsContent value="modules">
          <Modules tenant={tenant} refresh={refresh} />
        </TabsContent>
        <TabsContent value="plan">
          <PlanTab tenant={tenant} />
        </TabsContent>
        <TabsContent value="users">
          <Users tenant={tenant} />
        </TabsContent>
        <TabsContent value="audit">
          <TenantAudit tenant={tenant} />
        </TabsContent>
      </Tabs>
    </>
  );
}
