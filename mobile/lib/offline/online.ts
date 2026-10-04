/**
 * Whether the phone can reach the internet (ADR-061 item 10): TanStack Query pauses requests while
 * it can't and resumes them when it can, and screens say so in plain words.
 */
import NetInfo from "@react-native-community/netinfo";
import { onlineManager } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

/** Once, at start: follow the phone's connection. */
export function followConnection(): void {
  onlineManager.setEventListener((setOnline) =>
    NetInfo.addEventListener((state) => {
      setOnline(state.isConnected !== false && state.isInternetReachable !== false);
    }),
  );
}

export function useOnline(): boolean {
  return useSyncExternalStore(
    (listener) => onlineManager.subscribe(listener),
    () => onlineManager.isOnline(),
  );
}

interface QueryLike {
  isPending: boolean;
  fetchStatus: string;
  error: unknown;
  data: unknown;
}

/** Still coming: loading, or the saved copy being read. (A query waiting for a connection is
 * pending but not loading, so screens must not take it for an error.) */
export function isWaiting(query: QueryLike): boolean {
  return query.isPending && query.fetchStatus !== "paused";
}

/** Offline, and this page wasn't saved: it waits for the connection. */
export function isUnsaved(query: QueryLike): boolean {
  return query.isPending && query.fetchStatus === "paused";
}

/** An error worth showing: only when there's nothing (saved) to show instead. */
export function failed(query: QueryLike): boolean {
  return Boolean(query.error) && query.data === undefined;
}
