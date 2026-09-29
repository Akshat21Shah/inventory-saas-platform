"use client";

import { useEffect, useRef } from "react";

import { authWsTicket } from "@/lib/api/generated/endpoints/auth/auth";

/** What the server pushes (common/live.py): only what changed; screens refetch through the API. */
export interface LiveEvent {
  type: "order";
  event: string; // "order.placed", "order.accepted", "backorder.allocated", …
  order: string | null;
  number: string | null;
  status: string | null;
  retailer?: string | null; // staff only
  retailer_name?: string; // staff only
}

const MAX_WAIT_MS = 30_000;

function socketUrl(ticket: string): string {
  const { protocol, host } = window.location;
  return `${protocol === "https:" ? "wss" : "ws"}://${host}/ws/v1/?ticket=${encodeURIComponent(ticket)}`;
}

/**
 * Keeps a live-updates socket open while the component is mounted (same origin: Next proxies
 * /ws/). Each connection uses a fresh one-time ticket. After a drop it reconnects with growing
 * waits, and calls `onReconnect` so screens refetch what they may have missed.
 */
export function useLiveUpdates({
  enabled,
  onEvent,
  onNotification,
  onReconnect,
}: {
  enabled: boolean;
  onEvent: (event: LiveEvent) => void;
  /** A new message for this person (their bell): refetch the unread count. */
  onNotification?: () => void;
  onReconnect?: () => void;
}) {
  const handlers = useRef({ onEvent, onNotification, onReconnect });
  useEffect(() => {
    handlers.current = { onEvent, onNotification, onReconnect };
  });

  useEffect(() => {
    if (!enabled || typeof WebSocket === "undefined") return;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let stopped = false;

    const connect = async () => {
      if (stopped) return;
      try {
        const { data } = await authWsTicket();
        if (stopped) return;
        socket = new WebSocket(socketUrl(data.ticket));
      } catch {
        retry();
        return;
      }
      socket.onmessage = (message) => {
        try {
          const data = JSON.parse(String(message.data)) as { type?: string };
          if (data.type === "ready") {
            if (attempts > 0) handlers.current.onReconnect?.();
            attempts = 0;
          } else if (data.type === "order") {
            handlers.current.onEvent(data as LiveEvent);
          } else if (data.type === "notification") {
            handlers.current.onNotification?.();
          }
        } catch {
          // not ours: ignore
        }
      };
      socket.onclose = () => retry();
    };

    const retry = () => {
      if (stopped) return;
      attempts += 1;
      const wait = Math.min(MAX_WAIT_MS, 1000 * 2 ** Math.min(attempts, 5));
      timer = setTimeout(() => void connect(), wait);
    };

    void connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [enabled]);
}
