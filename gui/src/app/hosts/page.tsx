import { PageHeader } from "@/design-system";
import { HostTable } from "@/components/hosts";

export default function HostsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        trackingId="hosts.page.header"
        eyebrow="Fleet"
        title="Hosts"
        description="Machines in your agent fleet"
      />
      <HostTable />
    </div>
  );
}
