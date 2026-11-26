import { StatBlock } from "@/design-system";

interface MetricCardProps {
  label: string;
  value: string | number;
  sublabel?: string;
  trackingId: string;
}

export function MetricCard({ label, value, sublabel, trackingId }: MetricCardProps) {
  return (
    <StatBlock
      trackingId={trackingId}
      layout="stacked"
      value={value}
      source={sublabel}
      className="dashboard-metric min-w-0"
    >
      <span className="text-sm text-secondary truncate">{label}</span>
    </StatBlock>
  );
}
