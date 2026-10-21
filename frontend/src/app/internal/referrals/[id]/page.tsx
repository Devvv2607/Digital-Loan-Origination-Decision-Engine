import { ReferralDetail } from "@/components/internal/referrals";

export default async function ReferralDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReferralDetail id={id} />;
}
