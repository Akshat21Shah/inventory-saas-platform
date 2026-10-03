/** Account → Messages (the web's /shop/account/messages). */
import { MessagesSettings } from "@/components/shop/messages";
import { Screen } from "@/components/ui/screen";

export default function MessagesScreen() {
  return (
    <Screen>
      <MessagesSettings />
    </Screen>
  );
}
