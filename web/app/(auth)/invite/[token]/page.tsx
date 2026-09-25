import { InviteScreen } from "@/components/auth/invite-screen";

export default async function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <InviteScreen token={token} />;
}
