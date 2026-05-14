"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Card } from "@/components/ui/card";
import { useUsageHistory } from "@/hooks";

function formatDay(dateStr: string): string {
  const date = new Date(dateStr);
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return days[date.getDay()];
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function UsageChart() {
  const { data: history, isLoading } = useUsageHistory(7, "day");

  const chartData = (history ?? []).map((h) => ({
    name: formatDay(h.period),
    tokens: h.tokens,
    cost: h.cost,
  }));

  return (
    <Card padding="md" className="flex flex-col gap-4">
      <h3 className="text-sm font-medium text-secondary">
        Token Usage (7 Days)
      </h3>
      {isLoading ? (
        <div className="h-48 flex items-center justify-center text-muted text-sm">
          Loading...
        </div>
      ) : chartData.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-muted text-sm">
          No usage data yet
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={192}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="tokenGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#0D9488" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#0D9488" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
            <XAxis
              dataKey="name"
              tick={{ fontSize: 12, fill: "#94A3B8" }}
              axisLine={{ stroke: "#E2E8F0" }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 12, fill: "#94A3B8" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={formatTokens}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#FFFFFF",
                border: "1px solid #E2E8F0",
                borderRadius: "8px",
                fontSize: "12px",
              }}
              formatter={(value: number) => [
                formatTokens(value),
                "Tokens",
              ]}
            />
            <Area
              type="monotone"
              dataKey="tokens"
              stroke="#0D9488"
              strokeWidth={2}
              fill="url(#tokenGradient)"
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
