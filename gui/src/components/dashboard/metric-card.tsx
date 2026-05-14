import { Card } from "@/components/ui/card";

interface MetricCardProps {
  label: string;
  value: string | number;
  sublabel?: string;
}

export function MetricCard({ label, value, sublabel }: MetricCardProps) {
  return (
    <Card padding="sm" className="flex flex-col gap-1 min-w-0">
      <span className="text-2xl font-semibold text-primary truncate">
        {value}
      </span>
      <span className="text-sm text-secondary truncate">{label}</span>
      {sublabel && (
        <span className="text-xs text-muted truncate">{sublabel}</span>
      )}
    </Card>
  );
}
