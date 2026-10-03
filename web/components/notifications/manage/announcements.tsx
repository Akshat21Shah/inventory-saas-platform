"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { DateText } from "@/components/shared/money-text";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  announcementCreate,
  announcementUpdate,
  useAnnouncements,
} from "@/lib/api/generated/endpoints/notifications/notifications";
import type { Announcement } from "@/lib/api/generated/model";
import { useCursor } from "@/lib/api/pagination";
import { useErrorText } from "@/lib/api/use-error-text";
import { useTranslations } from "@/lib/i18n/translations";

import { NotificationsNav } from "./nav";

/** "2026-09-29T14:30" in the browser's time for a datetime-local input, and back to ISO. */
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function fromLocalInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

function state(row: Announcement): "running" | "stopped" | "scheduled" | "ended" {
  const now = Date.now();
  if (!row.is_active) return "stopped";
  if (new Date(row.starts_at).getTime() > now) return "scheduled";
  if (row.ends_at && new Date(row.ends_at).getTime() <= now) return "ended";
  return "running";
}

function AnnouncementDialog({ row, onClose }: { row: Announcement | null; onClose: () => void }) {
  const t = useTranslations("notifyAdmin.announcements");
  const client = useQueryClient();
  const { message, fields } = useErrorText();
  const [title, setTitle] = useState(row?.title ?? "");
  const [body, setBody] = useState(row?.body ?? "");
  const [starts, setStarts] = useState(toLocalInput(row?.starts_at ?? new Date().toISOString()));
  const [ends, setEnds] = useState(toLocalInput(row?.ends_at));
  const [active, setActive] = useState(row?.is_active ?? true);
  const [whatsapp, setWhatsapp] = useState(row?.send_whatsapp ?? false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const sent = Boolean(row?.published_at);

  const save = async () => {
    setBusy(true);
    setErrors({});
    const data = {
      title,
      body,
      starts_at: fromLocalInput(starts) ?? new Date().toISOString(),
      ends_at: fromLocalInput(ends),
      is_active: active,
      send_whatsapp: whatsapp,
    };
    try {
      if (row) await announcementUpdate(row.id, data);
      else await announcementCreate(data);
      void client.invalidateQueries({
        predicate: (q) => String(q.queryKey[0] ?? "").startsWith("/api/v1/announcements"),
      });
      toast.success(t("saved"));
      onClose();
    } catch (thrown) {
      const byField = fields(thrown);
      setErrors(byField);
      if (!Object.keys(byField).length) toast.error(message(thrown));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{row ? t("edit") : t("new")}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <div className="space-y-1">
            <Label htmlFor="announcement-title">{t("titleField")}</Label>
            <Input
              id="announcement-title"
              value={title}
              maxLength={120}
              onChange={(e) => setTitle(e.target.value)}
              aria-invalid={Boolean(errors.title)}
              className="min-h-10"
            />
            {errors.title ? <p className="text-destructive text-sm">{errors.title}</p> : null}
          </div>
          <div className="space-y-1">
            <Label htmlFor="announcement-body">{t("body")}</Label>
            <Textarea
              id="announcement-body"
              value={body}
              rows={4}
              maxLength={1000}
              onChange={(e) => setBody(e.target.value)}
              aria-invalid={Boolean(errors.body)}
            />
            {errors.body ? <p className="text-destructive text-sm">{errors.body}</p> : null}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="announcement-starts">{t("starts")}</Label>
              <Input
                id="announcement-starts"
                type="datetime-local"
                value={starts}
                onChange={(e) => setStarts(e.target.value)}
                className="min-h-10"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="announcement-ends">{t("ends")}</Label>
              <Input
                id="announcement-ends"
                type="datetime-local"
                value={ends}
                onChange={(e) => setEnds(e.target.value)}
                aria-describedby="announcement-ends-hint"
                aria-invalid={Boolean(errors.ends_at)}
                className="min-h-10"
              />
              <p id="announcement-ends-hint" className="text-muted-foreground text-xs">
                {errors.ends_at ?? t("endsHint")}
              </p>
            </div>
          </div>
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <Switch checked={active} onCheckedChange={setActive} aria-label={t("active")} />
            {t("active")}
          </label>
          <div className="space-y-1">
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <Checkbox
                checked={whatsapp}
                disabled={sent}
                onCheckedChange={(checked) => setWhatsapp(checked === true)}
              />
              {t("whatsapp")}
            </label>
            <p className="text-muted-foreground text-xs">{sent ? t("sent") : t("whatsappHint")}</p>
          </div>
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" className="min-h-11" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" className="min-h-11" disabled={busy}>
              {t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Settings → Messages → Announcements: notices on every shop's home. */
export function AnnouncementsPage() {
  const t = useTranslations("notifyAdmin.announcements");
  const cursor = useCursor();
  const query = useAnnouncements({ cursor: cursor.cursor });
  const page = query.data?.data;
  const [editing, setEditing] = useState<Announcement | "new" | null>(null);
  const columns: DataTableColumn<Announcement>[] = [
    {
      id: "title",
      header: t("titleField"),
      cell: ({ row }) => (
        <span className="block min-w-0">
          <span className="block font-medium break-words">{row.original.title}</span>
          <span className="text-muted-foreground line-clamp-2 block text-xs break-words">
            {row.original.body}
          </span>
        </span>
      ),
    },
    {
      id: "state",
      header: t("active"),
      cell: ({ row }) => t(state(row.original)),
    },
    {
      id: "starts",
      header: t("starts"),
      cell: ({ row }) => <DateText value={row.original.starts_at} withTime />,
    },
    {
      id: "ends",
      header: t("ends"),
      cell: ({ row }) =>
        row.original.ends_at ? <DateText value={row.original.ends_at} withTime /> : "—",
    },
    {
      id: "sent",
      header: t("sent"),
      cell: ({ row }) =>
        row.original.published_at ? (
          <DateText value={row.original.published_at} withTime />
        ) : (
          t("notSent")
        ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button
          variant="outline"
          className="min-h-10 max-md:min-h-11"
          onClick={() => setEditing(row.original)}
          aria-label={`${t("edit")}: ${row.original.title}`}
        >
          {t("edit")}
        </Button>
      ),
    },
  ];
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button className="min-h-11 gap-2" onClick={() => setEditing("new")}>
            <Plus aria-hidden />
            {t("new")}
          </Button>
        }
      />
      <NotificationsNav />
      <DataTable
        columns={columns}
        data={page?.results ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        pagination={cursor.pagination(page)}
        caption={t("title")}
        empty={{ title: t("empty"), description: t("emptyBody") }}
        cardLayout={{
          title: "title",
          state: "primary",
          starts: "primary",
          ends: "secondary",
          sent: "secondary",
          actions: "actions",
        }}
      />
      {editing ? (
        <AnnouncementDialog
          row={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </>
  );
}
