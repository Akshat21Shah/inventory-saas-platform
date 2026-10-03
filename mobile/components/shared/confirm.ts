import { Alert } from "react-native";

/** The web's ConfirmDialog, as Android's own dialog: a title, what happens, cancel and confirm. */
export function confirm({
  title,
  body,
  confirmLabel,
  cancelLabel,
  destructive = false,
  onConfirm,
}: {
  title: string;
  body?: string;
  confirmLabel: string;
  cancelLabel: string;
  destructive?: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  Alert.alert(title, body, [
    { text: cancelLabel, style: "cancel" },
    {
      text: confirmLabel,
      style: destructive ? "destructive" : "default",
      onPress: () => void onConfirm(),
    },
  ]);
}
