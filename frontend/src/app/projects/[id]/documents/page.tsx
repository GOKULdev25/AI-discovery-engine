import { DocumentsClient } from "./DocumentsClient";

export default async function DocumentsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <DocumentsClient projectId={id} />;
}
