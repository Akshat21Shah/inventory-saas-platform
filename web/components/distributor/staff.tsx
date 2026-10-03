"use client";

import { Check, Mail, RotateCw, UserPlus, UserRoundX, UserRoundCheck, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Fragment, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { FieldsDialog } from "@/components/shared/fields-dialog";
import { AuditTable } from "@/components/shared/audit-table";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/error-state";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { TableSkeleton } from "@/components/shared/skeletons";
import { StatusBadge } from "@/components/shared/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuditLogsList } from "@/lib/api/generated/endpoints/settings/settings";
import {
  getStaffInvitationsListQueryKey,
  staffInvitationsCreate,
  staffInvitationsResend,
  staffInvitationsRevoke,
  staffUpdate,
  usePermissionsList,
  useRolesList,
  useStaffInvitationsList,
  useStaffList,
} from "@/lib/api/generated/endpoints/staff/staff";
import type { Invitation, Membership, Role } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";

function roleLabel(t: ReturnType<typeof useTranslations>, role: { code: string; name: string }) {
  return t.has(`roles.${role.code}`) ? t(`roles.${role.code}`) : role.name;
}

function RoleSelect({
  member,
  roles,
  disabled,
  onChanged,
}: {
  member: Membership;
  roles: Role[];
  disabled: boolean;
  onChanged: () => void;
}) {
  const t = useTranslations("staff");
  const errors = useErrorText();
  const [pending, setPending] = useState(false);
  return (
    <Select
      value={member.role.code}
      disabled={disabled || pending}
      onValueChange={async (role_code) => {
        setPending(true);
        try {
          await staffUpdate(member.id, { role_code });
          toast.success(t("roleChanged"));
        } catch (err) {
          toast.error(errors.message(err));
        } finally {
          setPending(false);
          onChanged();
        }
      }}
    >
      <SelectTrigger
        className="min-h-9 w-40"
        aria-label={t("roleFor", { name: member.user.full_name || member.user.email })}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {roles.map((role) => (
          <SelectItem key={role.code} value={role.code}>
            {roleLabel(t, role)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function StaffTable({ roles }: { roles: Role[] }) {
  const t = useTranslations("staff");
  const { me } = useAuth();
  const cursor = useCursor();
  const query = useStaffList({ cursor: cursor.cursor });
  const page = query.data?.data;

  const columns: DataTableColumn<Membership>[] = [
    {
      id: "name",
      header: t("name"),
      cell: ({ row }) => (
        <span>
          <span className="block font-medium">
            {row.original.user.full_name || row.original.user.email}
            {row.original.user.id === me?.id ? (
              <span className="text-muted-foreground font-normal"> ({t("you")})</span>
            ) : null}
          </span>
          <span className="text-muted-foreground block text-xs">{row.original.user.email}</span>
        </span>
      ),
    },
    {
      id: "role",
      header: t("role"),
      cell: ({ row }) => (
        <RoleSelect
          member={row.original}
          roles={roles}
          disabled={row.original.is_active === false}
          onChanged={() => void query.refetch()}
        />
      ),
    },
    {
      id: "mfa",
      header: t("twoStep"),
      cell: ({ row }) =>
        row.original.user.mfa_enabled ? (
          <Badge variant="secondary">{t("mfaOn")}</Badge>
        ) : (
          <span className="text-muted-foreground text-sm">{t("mfaOff")}</span>
        ),
    },
    {
      id: "lastLogin",
      header: t("lastSignIn"),
      cell: ({ row }) =>
        row.original.user.last_login ? (
          <DateText value={row.original.user.last_login} withTime />
        ) : (
          <span className="text-muted-foreground text-sm">{t("never")}</span>
        ),
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => (
        <StatusBadge status={row.original.is_active === false ? "INACTIVE" : "ACTIVE"} />
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => {
        const member = row.original;
        const name = member.user.full_name || member.user.email;
        if (member.user.id === me?.id) return null; // nobody deactivates themselves
        const active = member.is_active !== false;
        return (
          <ConfirmDialog
            destructive={active}
            trigger={
              <Button
                variant="ghost"
                size="icon"
                className="size-10"
                aria-label={`${active ? t("deactivate") : t("reactivate")}: ${name}`}
                title={active ? t("deactivate") : t("reactivate")}
              >
                {active ? <UserRoundX aria-hidden /> : <UserRoundCheck aria-hidden />}
              </Button>
            }
            title={active ? t("deactivateTitle", { name }) : t("reactivateTitle", { name })}
            description={active ? t("deactivateBody") : undefined}
            confirmLabel={active ? t("deactivate") : t("reactivate")}
            onConfirm={async () => {
              await staffUpdate(member.id, { is_active: !active });
              toast.success(active ? t("deactivated") : t("reactivated"));
              void query.refetch();
            }}
          />
        );
      },
    },
  ];

  return (
    <DataTable
      columns={columns}
      cardLayout={{
        name: "title",
        role: "primary",
        status: "primary",
        mfa: "secondary",
        lastLogin: "secondary",
      }}
      data={page?.results ?? []}
      getRowId={(row) => row.id}
      isLoading={query.isLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      pagination={cursor.pagination(page)}
      empty={{ title: t("noStaff") }}
    />
  );
}

function invitationState(invitation: Invitation): string {
  if (invitation.status === "PENDING" && new Date(invitation.expires_at).getTime() < Date.now())
    return "EXPIRED";
  return invitation.status;
}

function Invitations() {
  const t = useTranslations("staff");
  const cursor = useCursor();
  const query = useStaffInvitationsList({ cursor: cursor.cursor });
  const page = query.data?.data;
  const rows = page?.results ?? [];
  const columns: DataTableColumn<Invitation>[] = [
    { id: "email", header: t("email"), cell: ({ row }) => row.original.email },
    { id: "role", header: t("role"), cell: ({ row }) => roleLabel(t, row.original.role) },
    {
      id: "sent",
      header: t("sent"),
      cell: ({ row }) => <DateText value={row.original.created_at} />,
    },
    {
      id: "status",
      header: t("status"),
      cell: ({ row }) => <StatusBadge status={invitationState(row.original)} />,
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => {
        const invitation = row.original;
        const state = invitationState(invitation);
        if (state !== "PENDING" && state !== "EXPIRED") return null;
        return (
          <div className="flex justify-end gap-1">
            <ConfirmDialog
              trigger={
                <Button variant="ghost" size="sm" className="min-h-9">
                  <RotateCw aria-hidden />
                  {t("resend")}
                </Button>
              }
              title={t("resendTitle", { email: invitation.email })}
              description={t("resendBody")}
              confirmLabel={t("resend")}
              onConfirm={async () => {
                await staffInvitationsResend(invitation.id);
                toast.success(t("resent"));
                void query.refetch();
              }}
            />
            {state === "PENDING" ? (
              <ConfirmDialog
                destructive
                trigger={
                  <Button variant="ghost" size="sm" className="min-h-9">
                    <X aria-hidden />
                    {t("revoke")}
                  </Button>
                }
                title={t("revokeTitle", { email: invitation.email })}
                confirmLabel={t("revoke")}
                onConfirm={async () => {
                  await staffInvitationsRevoke(invitation.id);
                  toast.success(t("revoked"));
                  void query.refetch();
                }}
              />
            ) : null}
          </div>
        );
      },
    },
  ];
  if (!query.isLoading && !query.error && rows.length === 0 && !cursor.cursor) return null;
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">{t("invitations")}</h2>
      <DataTable
        columns={columns}
        cardLayout={{ email: "title", role: "primary", status: "primary", sent: "secondary" }}
        data={rows}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        pagination={cursor.pagination(page)}
      />
    </section>
  );
}

export function StaffPage() {
  const t = useTranslations("staff");
  const roles = useRolesList();
  const queryClient = useQueryClient();
  const roleOptions = (roles.data?.data ?? []).map((role) => ({
    value: role.code,
    label: roleLabel(t, role),
  }));
  // The invitation's language: the inviter's own unless they choose another (ADR-060).
  const { me } = useAuth();
  const languageOptions = (me?.languages ?? []).map((option) => ({
    value: option.code,
    label: option.native,
  }));
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("body")}
        actions={
          <FieldsDialog
            trigger={
              <Button className="min-h-10" disabled={roleOptions.length === 0}>
                <UserPlus aria-hidden />
                {t("invite")}
              </Button>
            }
            title={t("inviteTitle")}
            description={t("inviteBody")}
            fields={[
              { name: "email", label: t("email"), required: true },
              { name: "role_code", label: t("role"), kind: "select", options: roleOptions },
              ...(languageOptions.length > 1
                ? [
                    {
                      name: "language",
                      label: t("inviteLanguage"),
                      kind: "select" as const,
                      options: languageOptions,
                      hint: t("inviteLanguageHint"),
                    },
                  ]
                : []),
            ]}
            initial={{ email: "", role_code: "SALES", language: me?.language ?? "en" }}
            submitLabel={t("sendInvite")}
            onSubmit={async (values) => {
              await staffInvitationsCreate({
                email: String(values.email).trim(),
                role_code: String(values.role_code),
                ...(languageOptions.length > 1 ? { language: String(values.language) } : {}),
              });
              toast.success(t("invited", { email: String(values.email).trim() }));
              void queryClient.invalidateQueries({ queryKey: getStaffInvitationsListQueryKey() });
            }}
          />
        }
      />
      <div className="space-y-8">
        {roles.error ? (
          <ErrorState error={roles.error} onRetry={() => void roles.refetch()} />
        ) : (
          <StaffTable roles={roles.data?.data ?? []} />
        )}
        <Invitations />
      </div>
      <p className="text-muted-foreground mt-6 flex items-center gap-2 text-sm">
        <Mail aria-hidden className="size-4" />
        {t("inviteNote")}
      </p>
    </>
  );
}

/** Who can do what: every permission (grouped by area) against every role. Read-only for now. */
export function RolesPage() {
  const t = useTranslations("staff");
  const roles = useRolesList();
  const permissions = usePermissionsList();
  const list = roles.data?.data ?? [];
  const byModule = new Map<string, { code: string; description: string }[]>();
  for (const p of permissions.data?.data ?? []) {
    byModule.set(p.module, [...(byModule.get(p.module) ?? []), p]);
  }
  const error = roles.error ?? permissions.error;
  return (
    <>
      <PageHeader title={t("rolesTitle")} description={t("rolesBody")} />
      {roles.isLoading || permissions.isLoading ? (
        <TableSkeleton columns={6} />
      ) : error ? (
        <ErrorState
          error={error}
          onRetry={() => {
            void roles.refetch();
            void permissions.refetch();
          }}
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-56">{t("permission")}</TableHead>
                {list.map((role) => (
                  <TableHead key={role.code} className="text-center">
                    {roleLabel(t, role)}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...byModule.entries()].map(([module, perms]) => (
                <Fragment key={module}>
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    <TableCell colSpan={list.length + 1} className="font-medium">
                      {t.has(`modules.${module}`) ? t(`modules.${module}`) : module}
                    </TableCell>
                  </TableRow>
                  {perms.map((p) => (
                    <TableRow key={p.code}>
                      <TableCell className="text-sm">{p.description}</TableCell>
                      {list.map((role) => {
                        const has = role.permissions.includes(p.code);
                        return (
                          <TableCell key={role.code} className="text-center">
                            {has ? (
                              <Check
                                aria-label={t("allowed")}
                                className="text-success-strong inline size-4"
                              />
                            ) : (
                              <span aria-label={t("notAllowed")} className="text-muted-foreground">
                                –
                              </span>
                            )}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ))}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}

export function TenantAuditPage() {
  const t = useTranslations("audit");
  const [filter, setFilter] = useState("");
  const cursor = useCursor();
  const query = useAuditLogsList({ action: filter || undefined, cursor: cursor.cursor });
  const page = query.data?.data;
  return (
    <>
      <PageHeader title={t("title")} description={t("tenantBody")} />
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
    </>
  );
}
