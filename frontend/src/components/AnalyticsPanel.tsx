import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { useAnalytics, usePosition } from "../api/queries";
import { API_BASE } from "../api/client";
import { amount } from "../format";
import { Empty, ErrorNotice, Loading } from "./Feedback";

export function AnalyticsPanel({
  id,
  days,
  currency,
}: {
  id: number;
  days: number;
  currency: string;
}) {
  const stats = useAnalytics(id, days, currency);
  const position = usePosition(id);
  return (
    <section className="panel">
      <div className="section-line">
        <h2>Computed price intelligence</h2>
        <a
          className="button secondary"
          href={`${API_BASE}/api/products/${id}/observations/export`}
        >
          Export capture CSV
        </a>
      </div>
      <p className="muted">
        Statistics use captured prices with known currency and delivery context.
        No missing-day interpolation or currency conversion.
      </p>
      {stats.isPending ? (
        <Loading />
      ) : stats.error ? (
        <ErrorNotice error={stats.error} />
      ) : (
        <>
          <div className="stat-grid">
            {[
              ["Minimum", stats.data.minimum],
              ["Maximum", stats.data.maximum],
              ["Average", stats.data.average],
              ["Capture-to-capture change", stats.data.change],
            ].map(([label, value]) => (
              <div key={label}>
                <small>{label}</small>
                <strong>{amount(value, stats.data.currency)}</strong>
              </div>
            ))}
          </div>
          <p>
            <span className="badge">
              Trend: {stats.data.trend.replaceAll("_", " ")}
            </span>{" "}
            · {stats.data.priced_count} priced of {stats.data.observation_count}{" "}
            captures in {days} days
          </p>
          <p className="muted">
            Trend compares capture averages over the last seven days with the
            prior seven; a change greater than ±5% is rising/falling.
            Insufficient history or a zero prior average has no trend.
          </p>
        </>
      )}
      {position.isPending ? (
        <Loading />
      ) : position.error ? (
        <ErrorNotice error={position.error} />
      ) : (
        <>
          <h3>Confirmed comparison cohort</h3>
          {position.data.reason ? (
            <Empty title="Insufficient comparable current prices">
              {position.data.reason}
            </Empty>
          ) : (
            <>
              <p>
                Price rank {position.data.price_rank} of{" "}
                {position.data.total_in_set} · Cohort median{" "}
                {amount(position.data.median, position.data.currency)}
              </p>
              <div
                className="chart"
                role="img"
                aria-label={`Current captured prices for ${position.data.total_in_set} listings in ${position.data.currency}`}
              >
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart
                    data={position.data.entries.map((e) => ({
                      asin: e.asin,
                      price: Number(e.price_amount),
                      baseline: e.baseline,
                    }))}
                  >
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="asin" />
                    <YAxis
                      width={85}
                      tickFormatter={(v) =>
                        amount(String(v), position.data.currency)
                      }
                    />
                    <Tooltip
                      formatter={(v) =>
                        amount(String(v), position.data.currency)
                      }
                    />
                    <Bar dataKey="price" fill="#13746d" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </>
          )}
          <p className="muted">
            {position.data.excluded_count} listings excluded for missing or
            incompatible current prices. Latest captures may have different
            times; this is a saved cohort, not the entire market.
          </p>
        </>
      )}
    </section>
  );
}
