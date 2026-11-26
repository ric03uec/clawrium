import Link from "next/link";
import { PageHeader } from "@/design-system";
import { ComingSoon } from "@/components/layout";

export default function HostsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        trackingId="hosts.page.header"
        eyebrow="Fleet"
        title="Hosts"
        description="Machines in your agent fleet"
      />
      <ComingSoon
        trackingId="hosts.page.coming-soon"
        description="The hosts management page is planned for a later delivery step. Until then, view and manage hosts in topology."
        actions={<Link className="text-primary-foreground underline" href="/topology">Open topology</Link>}
      />
    </div>
  );
}
