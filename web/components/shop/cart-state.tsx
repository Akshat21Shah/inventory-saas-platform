"use client";

import { useQueryClient, type QueryKey } from "@tanstack/react-query";
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
import { toast } from "sonner";

import { useAuth } from "@/components/auth/auth-provider";
import { useErrorText } from "@/lib/api/use-error-text";
import {
  getShopCartRetrieveQueryKey,
  shopCartLineSet,
  useShopCartRetrieve,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { Quote } from "@/lib/api/generated/model";
import { isZero } from "@/lib/qty";

/** How long taps on a stepper are gathered before the new quantity is sent. */
const SEND_AFTER_MS = 350;

interface CartState {
  cart: Quote | undefined;
  loading: boolean;
  /** What the shop sees now: a tap shows at once, the server's cart follows. */
  quantityOf: (productId: string) => string;
  setQuantity: (productId: string, quantity: string) => void;
  /** Taps not yet confirmed by the server (checkout waits for none). */
  pending: boolean;
  /** Products in the cart (for the badge on the cart tab). */
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

/** Every cached cart (with and without a chosen address) is the same cart. */
function isCartKey(key: QueryKey): boolean {
  return key[0] === getShopCartRetrieveQueryKey()[0];
}

export function CartProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const client = useQueryClient();
  const { message } = useErrorText();
  const query = useShopCartRetrieve(undefined, { query: { enabled: Boolean(me?.retailer) } });
  const cart = query.data?.data;
  const [overlay, setOverlay] = useState<Record<string, string>>({});
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const chain = useRef<Promise<unknown>>(Promise.resolve());

  const send = useCallback(
    (productId: string, quantity: string) => {
      // One request at a time, in order, so a slower earlier request can't win.
      chain.current = chain.current.then(async () => {
        try {
          const response = await shopCartLineSet(productId, { quantity });
          client.setQueryData(getShopCartRetrieveQueryKey(), response);
          void client.invalidateQueries({
            predicate: (q) => isCartKey(q.queryKey) && q.queryKey.length > 1,
          });
        } catch (error) {
          toast.error(message(error));
          void client.invalidateQueries({ predicate: (q) => isCartKey(q.queryKey) });
        } finally {
          setOverlay((current) => {
            if (current[productId] !== quantity) return current; // a newer tap is on its way
            const next = { ...current };
            delete next[productId];
            return next;
          });
        }
      });
    },
    [client, message],
  );

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
    // Free lines (ADR-056) aren't what the shop asked for: only bought lines set the steppers.
    const bought = (cart?.lines ?? []).filter((line) => !line.is_free);
    const serverQty = new Map(bought.map((line) => [line.product_id, line.quantity]));
    const ids = new Set([...serverQty.keys(), ...Object.keys(overlay)]);
    const quantityOf = (id: string) => overlay[id] ?? serverQty.get(id) ?? "0";
    const count = [...ids].filter((id) => !isZero(quantityOf(id))).length;
    return {
      cart,
      loading: query.isLoading,
      quantityOf,
      setQuantity,
      pending: Object.keys(overlay).length > 0,
      count,
      version: bought.map((l) => `${l.product_id}:${l.quantity}`).join("|"),
    };
  }, [cart, overlay, query.isLoading, setQuantity]);

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}
