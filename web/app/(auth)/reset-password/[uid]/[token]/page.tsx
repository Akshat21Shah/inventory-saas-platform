import { ResetPasswordScreen } from "@/components/auth/password-screens";

export default async function ResetPasswordPage({
  params,
}: {
  params: Promise<{ uid: string; token: string }>;
}) {
  const { uid, token } = await params;
  return <ResetPasswordScreen uid={uid} token={token} />;
}
