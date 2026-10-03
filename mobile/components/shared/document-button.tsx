import Feather from "@expo/vector-icons/Feather";
import { useState } from "react";
import { Alert, Linking } from "react-native";

import { Button } from "@/components/ui/button";
import { useErrorText } from "@/lib/api/error-text";
import type { DocumentLink } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { useTheme } from "@/lib/theme/theme";

/** Opens a printed document (bill, credit note, receipt, confirmation): the server answers with
 * a short-lived link, or "being prepared" while the PDF is printed. */
export function DocumentButton({
  fetchLink,
  label,
}: {
  fetchLink: () => Promise<{ data: DocumentLink; status: number }>;
  label: string;
}) {
  const t = useTranslations("billing.document");
  const { message } = useErrorText();
  const { colors } = useTheme();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="outline"
      label={label}
      busy={busy}
      icon={<Feather name="file-text" size={16} color={colors.foreground} />}
      onPress={async () => {
        setBusy(true);
        try {
          const { data } = await fetchLink();
          if (data.status === "READY" && data.url) await Linking.openURL(data.url);
          else Alert.alert(data.status === "FAILED" ? t("failed") : t("preparing"));
        } catch (error) {
          Alert.alert(message(error));
        } finally {
          setBusy(false);
        }
      }}
    />
  );
}
