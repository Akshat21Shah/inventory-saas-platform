/**
 * The shop's cart, as the web keeps it (`web/components/shop/cart-state.tsx`): the cart lives
 * on the server, a tap shows at once and its quantity is sent shortly after, one request at a
 * time and in order. Quantities are set, not added, so sending one again is harmless.
 *
 * Without a connection (ADR-061 item 10) the cart still works: the changes are kept on the phone
 * (also across a restart) and sent, in order, when the connection is back; the server's totals
 * come back then.
 */
import { onlineManager, useQueryClient, type QueryKey } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Alert } from "react-native";

import { useErrorText } from "@/lib/api/error-text";
import {
  getShopCartRetrieveQueryKey,
  shopCartLineSet,
  useShopCartRetrieve,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { Quote } from "@/lib/api/generated/model";
import { ApiError, NETWORK_ERROR } from "@/lib/shared/errors";
import { isZero } from "@/lib/shared/qty";
import { fileStore } from "@/lib/storage/file-store";

const SEND_AFTER_MS = 350;
const PENDING_KEY = "cart-pending"; // changes not yet confirmed by the server

interface CartState {
  cart: Quote | undefined;
  loading: boolean;
  error: unknown;
  refetch: () => void;
  quantityOf: (productId: string) => string;
  setQuantity: (productId: string, quantity: string) => void;
  /** Taps not yet confirmed by the server (checkout waits for none). */
  pending: boolean;
  /** Products changed on the phone that the server's cart doesn't have yet (offline). */
  waiting: string[];
  count: number;
  /** Changes whenever the cart's contents change (a checkout attempt belongs to one version). */
  version: string;
}

const CartContext = createContext<CartState | null>(null);

export function useCart(): CartState {
  const value = useContext(CartContext);
  if (!value) throw new Error("useCart() outside <CartProvider>");
  return value;
}

function isCartKey(key: QueryKey): boolean {
  return key[0] === getShopCartRetrieveQueryKey()[0];
}

export function CartProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const { message } = useErrorText();
  const query = useShopCartRetrieve();
  const cart = query.data?.data;
  const [overlay, setOverlay] = useState<Record<string, string>>({});
  const latest = useRef(overlay);
  const loaded = useRef(false);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const chain = useRef<Promise<unknown>>(Promise.resolve());

  const send = useCallback(
    (productId: string, quantity: string) => {
      chain.current = chain.current.then(async () => {
        if (!onlineManager.isOnline()) return; // kept on the phone; sent when back online
        try {
          const response = await shopCartLineSet(productId, { quantity });
          client.setQueryData(getShopCartRetrieveQueryKey(), response);
          void client.invalidateQueries({
            predicate: (q) => isCartKey(q.queryKey) && q.queryKey.length > 1,
          });
        } catch (error) {
          if (error instanceof ApiError && error.code === NETWORK_ERROR) return; // kept, as above
          Alert.alert(message(error));
          void client.invalidateQueries({ predicate: (q) => isCartKey(q.queryKey) });
        }
        setOverlay((current) => {
          if (current[productId] !== quantity) return current; // a newer tap is on its way
          const next = { ...current };
          delete next[productId];
          return next;
        });
      });
    },
    [client, message],
  );

  // Everything still waiting, in the order it was changed.
  const flush = useCallback(() => {
    for (const [productId, quantity] of Object.entries(latest.current)) {
      if (!timers.current.has(productId)) send(productId, quantity);
    }
  }, [send]);

  // The changes kept on the phone survive a restart, and go once the connection is back.
  useEffect(() => {
    void fileStore.getItem(PENDING_KEY).then((text) => {
      const saved = text ? (JSON.parse(text) as Record<string, string>) : {};
      loaded.current = true;
      setOverlay((current) => ({ ...saved, ...current }));
    });
    return onlineManager.subscribe((online) => {
      if (online) flush();
    });
  }, [flush]);

  useEffect(() => {
    const added = Object.keys(overlay).some((id) => !(id in latest.current));
    latest.current = overlay;
    if (!loaded.current) return;
    void fileStore.setItem(PENDING_KEY, JSON.stringify(overlay));
    if (added && onlineManager.isOnline()) flush(); // after a restart: what was kept goes now
  }, [overlay, flush]);

  const setQuantity = useCallback(
    (productId: string, quantity: string) => {
      setOverlay((current) => ({ ...current, [productId]: quantity }));
      const waiting = timers.current.get(productId);
      if (waiting) clearTimeout(waiting);
      timers.current.set(
        productId,
        setTimeout(() => {
          timers.current.delete(productId);
          send(productId, quantity);
        }, SEND_AFTER_MS),
      );
    },
    [send],
  );

  useEffect(() => {
    const pendingTimers = timers.current;
    return () => pendingTimers.forEach((timer) => clearTimeout(timer));
  }, []);

  const value = useMemo<CartState>(() => {
    const bought = (cart?.lines ?? []).filter((line) => !line.is_free);
    const serverQty = new Map(bought.map((line) => [line.product_id, line.quantity]));
    const ids = new Set([...serverQty.keys(), ...Object.keys(overlay)]);
    const quantityOf = (id: string) => overlay[id] ?? serverQty.get(id) ?? "0";
    return {
      cart,
      loading: query.isLoading,
      error: query.error,
      refetch: () => void query.refetch(),
      quantityOf,
      setQuantity,
      pending: Object.keys(overlay).length > 0,
      waiting: Object.keys(overlay).filter((id) => !serverQty.has(id) && !isZero(overlay[id]!)),
      count: [...ids].filter((id) => !isZero(quantityOf(id))).length,
      version: bought.map((l) => `${l.product_id}:${l.quantity}`).join("|"),
    };
  }, [cart, overlay, query, setQuantity]);
  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}
