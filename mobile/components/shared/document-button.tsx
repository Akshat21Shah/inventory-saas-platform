import Feather from "@expo/vector-icons/Feather";
import { File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import { useState } from "react";
import { Alert, Linking, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { useErrorText } from "@/lib/api/error-text";
import type { DocumentLink } from "@/lib/api/generated/model";
import { useTranslations } from "@/lib/i18n/translations";
import { space, TOUCH, useTheme } from "@/lib/theme/theme";

/**
 * A printed document (bill, credit note, receipt, confirmation): the server answers with a
 * short-lived link, or "being prepared" while the PDF is printed. Open shows it in the phone's PDF
 * viewer; Share (the app's addition to the web) hands the PDF to WhatsApp, email or Drive.
 */
export function DocumentButton({
  fetchLink,
  label,
  fileName,
  primary = false,
}: {
  fetchLink: () => Promise<{ data: DocumentLink; status: number }>;
  label: string;
  /** The shared file's name, e.g. the bill's number. */
  fileName?: string;
  primary?: boolean;
}) {
  const t = useTranslations("billing.document");
  const ta = useTranslations("app.document");
  const { message } = useErrorText();
  const { colors } = useTheme();
  const [busy, setBusy] = useState<"open" | "share" | null>(null);

  async function withLink(kind: "open" | "share", act: (url: string) => Promise<unknown>) {
    setBusy(kind);
    try {
      const { data } = await fetchLink();
      if (data.status === "READY" && data.url) await act(data.url);
      else Alert.alert(data.status === "FAILED" ? t("failed") : t("preparing"));
    } catch (error) {
      Alert.alert(message(error));
    } finally {
      setBusy(null);
    }
  }

  const share = () =>
    withLink("share", async (url) => {
      const name = `${(fileName ?? label).replace(/[^\w.-]+/g, "-")}.pdf`;
      const file = await File.downloadFileAsync(url, new File(Paths.cache, name), {
        idempotent: true,
      });
      await Sharing.shareAsync(file.uri, { mimeType: "application/pdf", dialogTitle: label });
    });

  return (
    <View style={styles.row}>
      <Button
        variant={primary ? "primary" : "outline"}
        label={label}
        needsInternet
        busy={busy === "open"}
        disabled={busy !== null}
        icon={
          <Feather
            name="file-text"
            size={16}
            color={primary ? colors.primaryForeground : colors.foreground}
          />
        }
        onPress={() => void withLink("open", (url) => Linking.openURL(url))}
        style={styles.flex}
      />
      <Button
        variant="outline"
        label={ta("share")}
        needsInternet
        busy={busy === "share"}
        disabled={busy !== null}
        icon={<Feather name="share-2" size={16} color={colors.foreground} />}
        onPress={() => void share()}
        style={styles.share}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: space[2] },
  flex: { flex: 1 },
  share: { minWidth: TOUCH },
});
