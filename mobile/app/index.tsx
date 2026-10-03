import { Redirect } from "expo-router";

import { useAuth } from "@/lib/auth/auth-provider";

/** Start: the shop when signed in, else sign-in. */
export default function Start() {
  const { status } = useAuth();
  if (status === "loading") return null;
  return <Redirect href={status === "signedIn" ? "/shop" : "/sign-in"} />;
}
