import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { Observation } from "../api/types";
import { amount } from "../format";
import { Empty } from "./Feedback";

export function PriceHistoryChart({
  observations,
  currency,
}: {
  observations: Observation[];
  currency: string | null;
}) {
  const data = observations
    .filter((row) => row.price_amount != null && row.currency === currency)
    .map((row) => ({
      captured: new Date(row.captured_at).getTime(),
      price: Number(row.price_amount),
      raw: row.price_amount,
    }));
  if (!data.length)
    return (
      <Empty title="No priced observations in this window">
        Collect a product to start its history. Missing prices are never filled
        with zero.
      </Empty>
    );
  return (
    <div
      className="chart"
      role="img"
      aria-label={`Price history in ${currency || "unknown currency"} across ${data.length} observations`}
    >
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="captured"
            tickFormatter={(value) => new Date(value).toLocaleDateString()}
            minTickGap={32}
          />
          <YAxis
            width={85}
            tickFormatter={(value) => amount(String(value), currency)}
            domain={["auto", "auto"]}
          />
          <Tooltip
            labelFormatter={(value) => new Date(Number(value)).toLocaleString()}
            formatter={(value) => [
              amount(String(value), currency),
              "Observed price",
            ]}
          />
          <Line
            type="linear"
            dataKey="price"
            stroke="#13746d"
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="muted">
        {data.length} saved observations · {currency || "currency unknown"} · no
        inferred historical values
      </p>
    </div>
  );
}
