import { Redirect, useLocalSearchParams } from "expo-router";

import { SignIn } from "@/components/auth/sign-in";
import { useAuth } from "@/lib/auth/auth-provider";

export default function SignInRoute() {
  const { status } = useAuth();
  const { distributor } = useLocalSearchParams<{ distributor?: string }>();
  if (status === "signedIn") return <Redirect href="/shop" />;
  return <SignIn distributor={distributor} />;
}
