import Feather from "@expo/vector-icons/Feather";
import { useState } from "react";
import { Keyboard, Pressable, StyleSheet, TextInput, View } from "react-native";

import { Button } from "@/components/ui/button";
import { useCart } from "@/lib/cart/cart-state";
import { useTranslations } from "@/lib/i18n/translations";
import { formatQty } from "@/lib/shared/format";
import { firstQty, isZero, nextQty, previousQty, toMilli } from "@/lib/shared/qty";
import { space, text, TOUCH, useTheme } from "@/lib/theme/theme";

export interface Orderable {
  id: string;
  name: string;
  min_order_qty: string;
  order_multiple: string;
  unit: { name: string };
}

/** "Add" until there is a quantity, then − quantity + (the quantity can also be typed). Steps
 * start at the product's minimum and follow its multiple; the server still checks. */
export function QuantityStepper({
  product,
  disabled,
  wide,
}: {
  product: Orderable;
  disabled?: boolean;
  wide?: boolean;
}) {
  const t = useTranslations("shop.order");
  const { quantityOf, setQuantity } = useCart();
  const { colors, radius } = useTheme();
  const qty = quantityOf(product.id);
  // A tap outside the search box closes the keyboard (owner, checkpoint review), so the bottom
  // bar is in reach for the next tap; the tap itself still counts.
  const set = (quantity: string) => {
    Keyboard.dismiss();
    setQuantity(product.id, quantity);
  };
  const [draft, setDraft] = useState<{ text: string; from: string } | null>(null);
  const typed = draft && draft.from === qty ? draft.text : null;
  const { min_order_qty: min, order_multiple: multiple } = product;

  if (isZero(qty)) {
    return (
      <Button
        label={t("add")}
        accessibilityLabel={t("addNamed", { name: product.name })}
        disabled={disabled}
        icon={<Feather name="shopping-cart" size={16} color={colors.primaryForeground} />}
        onPress={() => set(firstQty(min, multiple))}
        style={wide ? styles.wide : styles.add}
      />
    );
  }
  const commit = () => {
    if (typed === null) return;
    const value = typed.trim() === "" ? "0" : typed.trim();
    setDraft(null);
    if (toMilli(value) === null) return;
    setQuantity(product.id, value);
  };
  const step = (name: "minus" | "plus", label: string, onPress: () => void, off?: boolean) => (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      disabled={off}
      onPress={onPress}
      style={[
        styles.step,
        { borderColor: colors.border, borderRadius: radius, opacity: off ? 0.5 : 1 },
      ]}
    >
      <Feather name={name} size={20} color={colors.foreground} />
    </Pressable>
  );
  return (
    <View
      style={[styles.row, wide && styles.wide]}
      accessibilityLabel={t("inCart", { qty: formatQty(qty), unit: product.unit.name })}
    >
      {step("minus", t("less", { name: product.name }), () => set(previousQty(qty, min, multiple)))}
      <TextInput
        accessibilityLabel={t("quantityOf", { name: product.name })}
        keyboardType="decimal-pad"
        value={typed ?? formatQty(qty).replace(/,/g, "")}
        onChangeText={(value) => setDraft({ text: value, from: qty })}
        onBlur={commit}
        onSubmitEditing={commit}
        selectTextOnFocus
        style={[
          styles.input,
          wide && styles.grow,
          { borderColor: colors.input, borderRadius: radius, color: colors.foreground },
        ]}
      />
      {step(
        "plus",
        t("more", { name: product.name }),
        () => set(nextQty(qty, min, multiple)),
        disabled,
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: space[1] },
  wide: { alignSelf: "stretch" },
  add: { minWidth: 96 }, // the web's min-w-24
  step: {
    width: TOUCH,
    height: TOUCH,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  // 64 wide as the web's w-16; it fills the row only in the wide stepper (the cart), so on a
  // product card the note beside it keeps its room.
  grow: { flexGrow: 1 },
  input: {
    width: 64,
    height: TOUCH,
    borderWidth: 1,
    textAlign: "center",
    fontSize: text.lg,
    fontWeight: "600",
  },
});
