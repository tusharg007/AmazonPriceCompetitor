import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useCollect,
  useHistory,
  useMatches,
  useProduct,
  useUntrack,
  useAnalyze,
} from "../api/queries";
import { amount, timestamp } from "../format";
import {
  Empty,
  ErrorNotice,
  Loading,
  Pagination,
} from "../components/Feedback";
import { AnalyticsPanel } from "../components/AnalyticsPanel";
import { PriceHistoryChart } from "../components/PriceHistoryChart";
import { JobProgress } from "../components/JobProgress";
import { EvidenceInspector } from "../components/EvidenceInspector";

export function ProductDetail() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [days, setDays] = useState(30);
  const [status, setStatus] = useState("");
  const [matchPage, setMatchPage] = useState(1);
  const [include, setInclude] = useState(false);
  const [evidence, setEvidence] = useState<string | null>(null);
  const [currency, setCurrency] = useState("");
  const [job, setJob] = useState<string | null>(null);
  const product = useProduct(id);
  const history = useHistory(id, days);
  const matches = useMatches(id, status, matchPage);
  const collect = useCollect(id);
  const untrack = useUntrack(id);
  const analyze = useAnalyze(id);
  if (!Number.isInteger(id) || id <= 0)
    return <ErrorNotice error={new Error("Invalid product identifier.")} />;
  if (product.isPending) return <Loading />;
  if (product.error) return <ErrorNotice error={product.error} />;
  const p = product.data;
  const currencies = [
    ...new Set(
      (history.data || [])
        .map((o) => o.currency)
        .filter((c): c is string => !!c),
    ),
  ];
  const selected = currencies.includes(currency)
    ? currency
    : p.latest_observation?.currency || currencies[0] || "";
  return (
    <>
      <Link to="/">← Products</Link>
      <div className="page-heading">
        <p className="eyebrow">
          amazon.{p.domain} · {p.asin}
        </p>
        <h1>{p.title || p.asin}</h1>
        <p>
          {p.brand || "Brand not captured"} · Delivery:{" "}
          {p.requested_location || "default context"}
        </p>
        <p className="price">
          {amount(
            p.latest_observation?.price_amount,
            p.latest_observation?.currency,
          )}
        </p>
        <p className="muted">
          {p.latest_observation?.availability || "Availability not captured"} ·
          Location {p.latest_observation?.location_status || "not captured"} ·{" "}
          {timestamp(p.last_collected_at)}
        </p>
      </div>
      <section className="panel">
        <div className="actions">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={include}
              onChange={(e) => setInclude(e.target.checked)}
            />{" "}
            Discover competitors in this collection
          </label>
          <button
            disabled={collect.isPending}
            onClick={() =>
              collect.mutate(include, { onSuccess: (j) => setJob(j.id) })
            }
          >
            Collect evidence
          </button>
          <button
            disabled={
              analyze.isPending || !p.latest_observation || !p.competitor_count
            }
            onClick={() =>
              analyze.mutate(undefined, { onSuccess: (j) => setJob(j.id) })
            }
          >
            Analyze saved evidence
          </button>
          <button
            className="secondary"
            disabled={untrack.isPending}
            onClick={() =>
              untrack.mutate(undefined, { onSuccess: () => navigate("/") })
            }
          >
            Stop tracking
          </button>
        </div>
        {collect.error && <ErrorNotice error={collect.error} />}{" "}
        {analyze.error && <ErrorNotice error={analyze.error} />}
        {untrack.error && <ErrorNotice error={untrack.error} />}{" "}
        {job && <JobProgress id={job} />}
      </section>
      <section className="panel">
        <div className="section-line">
          <h2>Price history</h2>
          <div className="actions">
            <label>
              Window
              <select
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
              >
                {[30, 90, 365].map((d) => (
                  <option key={d} value={d}>
                    Last {d} days
                  </option>
                ))}
              </select>
            </label>
            {currencies.length > 1 && (
              <label>
                Currency
                <select
                  value={selected}
                  onChange={(e) => setCurrency(e.target.value)}
                >
                  {currencies.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </div>
        {history.isPending ? (
          <Loading />
        ) : history.error ? (
          <ErrorNotice error={history.error} />
        ) : (
          <>
            <PriceHistoryChart
              observations={history.data}
              currency={selected}
            />
            <p className="muted">
              Actual captured prices in {selected || "a known currency"}.
              Missing prices are omitted. No currency conversion. Up to 1,000
              captures per window.
            </p>
            <div className="table-scroll">
              <table>
                <caption>Capture history and provenance</caption>
                <thead>
                  <tr>
                    <th>Captured</th>
                    <th>Price</th>
                    <th>Rating</th>
                    <th>Location</th>
                    <th>Extraction</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {history.data.map((o) => (
                    <tr key={o.id}>
                      <td>{timestamp(o.captured_at)}</td>
                      <td>{amount(o.price_amount, o.currency)}</td>
                      <td>{o.rating ?? "—"}</td>
                      <td>{o.location_status}</td>
                      <td>
                        {o.extraction_method}
                        <small>{o.collector}</small>
                      </td>
                      <td>
                        {o.evidence_artifact_id ? (
                          <button
                            className="secondary"
                            onClick={() => setEvidence(o.evidence_artifact_id)}
                          >
                            Inspect source
                          </button>
                        ) : (
                          "Artifact unavailable"
                        )}
                        <small className="hash">Observation {o.id}</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {history.data.length === 0 && (
              <Empty title="No captures in this window">
                Collect evidence to start an append-only price history.
              </Empty>
            )}
          </>
        )}
      </section>
      <section className="panel">
        <div className="section-line">
          <h2>Competitor candidates</h2>
          <label>
            Match status
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setMatchPage(1);
              }}
            >
              <option value="">All statuses</option>
              {["confirmed", "ambiguous", "rejected"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        </div>
        <p className="muted">
          Scores are deterministic. Ambiguous candidates require review;
          rejected listings remain visible for audit.
        </p>
        {matches.isPending ? (
          <Loading />
        ) : matches.error ? (
          <ErrorNotice error={matches.error} />
        ) : matches.data.items.length === 0 ? (
          <Empty title="No candidates in this selection">
            Run a collection with competitor discovery enabled.
          </Empty>
        ) : (
          <div className="table-scroll">
            <table>
              <caption>Saved competitor matching decisions</caption>
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Latest price</th>
                  <th>Score</th>
                  <th>Decision</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {matches.data.items.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <Link to={`/products/${m.competitor_product_id}`}>
                        {m.competitor?.title ||
                          `Product ${m.competitor_product_id}`}
                      </Link>
                      <small>
                        {m.competitor?.asin} · {m.match_method}
                      </small>
                    </td>
                    <td>
                      {amount(
                        m.competitor?.latest_observation?.price_amount,
                        m.competitor?.latest_observation?.currency,
                      )}
                    </td>
                    <td>{m.match_score.toFixed(2)}</td>
                    <td>
                      <span className={`badge ${m.match_status}`}>
                        {m.match_status}
                      </span>
                      <small>{m.exclusion_reason?.replaceAll("_", " ")}</small>
                    </td>
                    <td>
                      {m.competitor?.latest_observation
                        ?.evidence_artifact_id ? (
                        <button
                          className="secondary"
                          onClick={() =>
                            setEvidence(
                              m.competitor!.latest_observation!
                                .evidence_artifact_id,
                            )
                          }
                        >
                          Inspect source
                        </button>
                      ) : (
                        "No artifact"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {matches.data && (
          <Pagination
            page={matchPage}
            total={matches.data.total}
            limit={20}
            onChange={setMatchPage}
          />
        )}
      </section>
      <AnalyticsPanel id={id} days={days} currency={selected} />
      {evidence && (
        <EvidenceInspector id={evidence} onClose={() => setEvidence(null)} />
      )}
    </>
  );
}
