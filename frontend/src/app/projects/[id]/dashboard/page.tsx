import { DashboardClient } from "./DashboardClient";

export default async function DashboardPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <DashboardClient projectId={id} />;
}
