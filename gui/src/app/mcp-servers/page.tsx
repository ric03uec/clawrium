import { PageHeader } from "@/design-system";
import { ComingSoon } from "@/components/layout";

export default function McpServersPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        trackingId="mcp-servers.page.header"
        eyebrow="Configuration"
        title="MCP servers"
        description="Model Context Protocol servers"
      />
      <ComingSoon
        trackingId="mcp-servers.page.coming-soon"
        description="MCP server management is scoped for a follow-up milestone. No create, edit, or delete actions are available in this release."
      />
    </div>
  );
}
