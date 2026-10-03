/**
 * The shop's cart, as the web keeps it (`web/components/shop/cart-state.tsx`): the cart lives
 * on the server, a tap shows at once and its quantity is sent shortly after, one request at a
 * time and in order. Quantities are set, not added, so sending one again is harmless.
 */
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
import { Alert } from "react-native";

import { useErrorText } from "@/lib/api/error-text";
import {
  getShopCartRetrieveQueryKey,
  shopCartLineSet,
  useShopCartRetrieve,
} from "@/lib/api/generated/endpoints/shop/shop";
import type { Quote } from "@/lib/api/generated/model";
import { isZero } from "@/lib/shared/qty";

const SEND_AFTER_MS = 350;

interface CartState {
  cart: Quote | undefined;
  loading: boolean;
  error: unknown;
  refetch: () => void;
  quantityOf: (productId: string) => string;
  setQuantity: (productId: string, quantity: string) => void;
  /** Taps not yet confirmed by the server (checkout waits for none). */
  pending: boolean;
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
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const chain = useRef<Promise<unknown>>(Promise.resolve());

  const send = useCallback(
    (productId: string, quantity: string) => {
      chain.current = chain.current.then(async () => {
        try {
          const response = await shopCartLineSet(productId, { quantity });
          client.setQueryData(getShopCartRetrieveQueryKey(), response);
          void client.invalidateQueries({
            predicate: (q) => isCartKey(q.queryKey) && q.queryKey.length > 1,
          });
        } catch (error) {
          Alert.alert(message(error));
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
      count: [...ids].filter((id) => !isZero(quantityOf(id))).length,
      version: bought.map((l) => `${l.product_id}:${l.quantity}`).join("|"),
    };
  }, [cart, overlay, query, setQuantity]);
  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}
