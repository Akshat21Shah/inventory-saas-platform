/** Suggest a better word (the web's dialog, 11a; ADR-060 item 11): the words on the screen and the
 * shop's better word, in Hindi or Marathi, with the screen the shop was on. */
import { router } from "expo-router";
import { useState } from "react";
import { Alert } from "react-native";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useErrorText } from "@/lib/api/error-text";
import { textsSuggestionsCreate } from "@/lib/api/generated/endpoints/texts/texts";
import { currentLanguage } from "@/lib/i18n/language";
import { useTranslations } from "@/lib/i18n/translations";
import { lastShoppingScreen } from "@/lib/last-screen";

export default function SuggestScreen() {
  const t = useTranslations("suggestWord");
  const errors = useErrorText();
  const [current, setCurrent] = useState("");
  const [better, setBetter] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function send() {
    setBusy(true);
    setFieldErrors({});
    try {
      await textsSuggestionsCreate({
        language: currentLanguage(),
        screen: `app:${lastShoppingScreen()}`,
        current_text: current.trim(),
        suggestion: better.trim(),
      });
      Alert.alert(t("thanks"));
      router.back();
    } catch (error) {
      const byField = errors.fields(error);
      setFieldErrors(byField);
      if (!Object.keys(byField).length) Alert.alert(errors.message(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Text size="2xl" weight="bold">
        {t("title")}
      </Text>
      <Text tone="muted" size="sm">
        {t("body")}
      </Text>
      <Input
        label={t("current")}
        value={current}
        onChangeText={setCurrent}
        error={fieldErrors.current_text}
        multiline
      />
      <Input
        label={t("better")}
        value={better}
        onChangeText={setBetter}
        error={fieldErrors.suggestion}
        multiline
      />
      <Button label={t("send")} busy={busy} disabled={!better.trim()} onPress={() => void send()} />
    </Screen>
  );
}
