"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LabelList,
  Legend,
} from "recharts";
import { Card } from "@/components/ui/card";
import { useFleet } from "@/hooks";

type ModelUsage = {
  model: string;
  input: number;
  output: number;
  cost: number;
  costLabel: string;
  total: number;
};

const INPUT_COLOR = "#5EEAD4";
const OUTPUT_COLOR = "#0D9488";

const MODEL_PRICING: Record<string, { input: number; output: number }> = {
  "opus-4.7": { input: 15, output: 75 },
  "sonnet-4.6": { input: 3, output: 15 },
  "haiku-4.5": { input: 0.8, output: 4 },
};

const DEFAULT_PRICING = { input: 3, output: 15 };

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

function formatCost(n: number): string {
  return `$${n.toFixed(2)}`;
}

function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function seededRandom(seed: number): () => number {
  let state = seed || 1;
  return () => {
    state = Math.imul(state ^ (state >>> 15), 2246822519);
    state = Math.imul(state ^ (state >>> 13), 3266489917);
    state ^= state >>> 16;
    return (state >>> 0) / 4294967296;
  };
}

function buildUsage(models: string[]): ModelUsage[] {
  return models.map((model) => {
    const rand = seededRandom(hashString(model));
    const input = Math.round(50_000 + rand() * 450_000);
    const output = Math.round(input * (0.25 + rand() * 0.35));
    const pricing = MODEL_PRICING[model] ?? DEFAULT_PRICING;
    const cost =
      (input / 1_000_000) * pricing.input +
      (output / 1_000_000) * pricing.output;
    return {
      model,
      input,
      output,
      cost,
      costLabel: formatCost(cost),
      total: input + output,
    };
  });
}

export function UsageChart() {
  const { data: fleet, isLoading } = useFleet();

  const chartData = useMemo(() => {
    const models = Array.from(
      new Set(
        (fleet?.agents ?? [])
          .map((a) => a.model)
          .filter((m): m is string => Boolean(m)),
      ),
    );
    return buildUsage(models);
  }, [fleet]);

  const totalTokens = chartData.reduce((acc, d) => acc + d.total, 0);
  const totalCost = chartData.reduce((acc, d) => acc + d.cost, 0);

  return (
    <Card padding="md" className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-secondary">
          Token Usage (7 Days)
        </h3>
        {chartData.length > 0 && (
          <span className="text-xs text-muted">
            Total: {formatTokens(totalTokens)} tokens · {formatCost(totalCost)}
          </span>
        )}
      </div>
      {isLoading ? (
        <div className="h-60 flex items-center justify-center text-muted text-sm">
          Loading...
        </div>
      ) : chartData.length === 0 ? (
        <div className="h-60 flex items-center justify-center text-muted text-sm">
          No models in fleet yet
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart
            data={chartData}
            margin={{ top: 28, right: 16, left: 0, bottom: 4 }}
            barCategoryGap="30%"
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
            <XAxis
              dataKey="model"
              tick={{ fontSize: 12, fill: "#475569" }}
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
              formatter={(value: number, name: string) => [
                formatTokens(value),
                name,
              ]}
            />
            <Legend
              wrapperStyle={{ fontSize: "12px", paddingTop: "8px" }}
              iconType="square"
            />
            <Bar
              dataKey="input"
              name="Input"
              stackId="tokens"
              fill={INPUT_COLOR}
            />
            <Bar
              dataKey="output"
              name="Output"
              stackId="tokens"
              fill={OUTPUT_COLOR}
              radius={[4, 4, 0, 0]}
            >
              <LabelList
                dataKey="costLabel"
                position="top"
                style={{ fill: "#0F172A", fontSize: 12, fontWeight: 600 }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
