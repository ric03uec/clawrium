import { PageHeader } from "@/components/layout";

export default function McpServersPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="MCP servers" description="Model Context Protocol servers" />
      <section className="rounded-xl border border-default bg-panel p-6">
        <h2 className="font-semibold">Coming soon</h2>
        <p className="mt-2 text-secondary">MCP server management is scoped for a follow-up milestone.</p>
      </section>
    </div>
  );
}
