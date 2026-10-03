import Feather from "@expo/vector-icons/Feather";
import { useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";

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
        onPress={() => setQuantity(product.id, firstQty(min, multiple))}
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
      {step("minus", t("less", { name: product.name }), () =>
        setQuantity(product.id, previousQty(qty, min, multiple)),
      )}
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
          { borderColor: colors.input, borderRadius: radius, color: colors.foreground },
        ]}
      />
      {step(
        "plus",
        t("more", { name: product.name }),
        () => setQuantity(product.id, nextQty(qty, min, multiple)),
        disabled,
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: space[1] },
  wide: { alignSelf: "stretch" },
  add: { minWidth: 112 },
  step: {
    width: TOUCH,
    height: TOUCH,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  input: {
    minWidth: 64,
    flexGrow: 1,
    height: TOUCH,
    borderWidth: 1,
    textAlign: "center",
    fontSize: text.lg,
    fontWeight: "600",
  },
});
