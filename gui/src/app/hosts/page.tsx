import Link from "next/link";
import { PageHeader } from "@/components/layout";

export default function HostsPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Hosts" description="Machines in your agent fleet" />
      <section className="rounded-xl border border-default bg-panel p-6">
        <h2 className="font-semibold">Coming soon</h2>
        <p className="mt-2 text-secondary">The hosts management page is planned for a later delivery step. Until then, view and manage hosts in topology.</p>
        <Link className="mt-3 inline-block text-primary underline" href="/topology">Open topology</Link>
      </section>
    </div>
  );
}
