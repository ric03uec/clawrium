"use client";

const LEGEND_ITEMS = [
  { label: "Running", color: "bg-status-running" },
  { label: "Degraded", color: "bg-status-warning" },
  { label: "Stopped", color: "bg-status-error" },
  { label: "Provisioning", color: "bg-status-info" },
];

export function TopologyLegend() {
  return (
    <div className="absolute bottom-4 left-4 bg-white/90 backdrop-blur-sm border border-default rounded-lg px-4 py-3 shadow-sm z-10">
      <div className="text-[10px] font-medium text-muted uppercase tracking-wide mb-2">
        Status
      </div>
      <div className="flex items-center gap-4">
        {LEGEND_ITEMS.map((item) => (
          <div key={item.label} className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${item.color}`} />
            <span className="text-xs text-secondary">{item.label}</span>
          </div>
        ))}
      </div>
      <div className="mt-2 pt-2 border-t border-default">
        <div className="flex items-center gap-1.5">
          <span className="w-4 border-t border-dashed border-primary" />
          <span className="text-xs text-secondary">SSH connection</span>
        </div>
      </div>
    </div>
  );
}
