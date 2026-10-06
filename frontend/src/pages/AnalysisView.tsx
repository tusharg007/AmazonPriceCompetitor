import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import type { Analysis } from "../api/types";
import { Empty, ErrorNotice, Loading } from "../components/Feedback";
import { EvidenceInspector } from "../components/EvidenceInspector";
import { timestamp } from "../format";

export function AnalysisView() {
  const { id } = useParams();
  const [evidence, setEvidence] = useState<string | null>(null);
  const valid =
    /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(
      id || "",
    );
  const query = useQuery({
    queryKey: ["analysis", id],
    queryFn: () => apiFetch<Analysis>(`/api/analyses/${id}`),
    enabled: valid,
  });
  if (!valid)
    return <ErrorNotice error={new Error("Invalid analysis identifier.")} />;
  if (query.isPending)
    return <Loading text="Loading saved analysis and citations…" />;
  if (query.error) return <ErrorNotice error={query.error} />;
  const run = query.data;
  const claims = run.claims || [];
  return (
    <>
      <Link to={`/products/${run.product_id}`}>← Product evidence</Link>
      <div className="page-heading">
        <p className="eyebrow">Evidence-linked reasoning</p>
        <h1>Saved analysis</h1>
        <p>
          {run.model} · {timestamp(run.completed_at)} · {run.status}
        </p>
        <p className="muted">
          Generated interpretations describe a filtered cohort of saved
          confirmed matches, not the entire market. Citations identify model
          inputs; they do not prove every interpretation. Numerical comparisons
          are computed by Python.
        </p>
        <small className="hash">
          Input SHA-256: {run.input_hash} · {run.prompt_version} ·{" "}
          {run.schema_version}
        </small>
      </div>
      {run.error_message && (
        <ErrorNotice error={new Error(run.error_message)} />
      )}{" "}
      {!!run.withheld_quantitative_claims && (
        <p role="status" className="feedback">
          {run.withheld_quantitative_claims} generated quantitative statements
          were withheld.
        </p>
      )}
      {claims.length === 0 ? (
        <Empty title="No validated claims saved">
          Retry from the product after checking the failure message.
        </Empty>
      ) : (
        claims.map((c) => (
          <section className="panel" key={c.id}>
            <div className="section-line">
              <h2>{c.claim_type.replaceAll("_", " ")}</h2>
              <span className="badge">
                {c.claim_value?.origin === "deterministic"
                  ? "Computed from captures"
                  : "Generated interpretation"}
              </span>
            </div>
            <p>{c.claim_text}</p>
            <details>
              <summary>Source captures ({c.evidence.length})</summary>
              {c.evidence.map((s) => (
                <div className="citation" key={s.observation_id}>
                  <p>
                    <Link to={`/products/${s.product_id}`}>
                      {s.product_asin}
                    </Link>{" "}
                    · {s.role} · {s.price_text || "Price unavailable"} ·{" "}
                    {timestamp(s.captured_at)}
                  </p>
                  <small>
                    {s.collector} · {s.extraction_method}
                  </small>
                  <small className="hash">
                    Observation: {s.observation_id} · Evidence: {s.evidence_id}
                  </small>
                  {s.evidence_artifact_id ? (
                    <button
                      className="secondary"
                      onClick={() => setEvidence(s.evidence_artifact_id)}
                    >
                      Inspect source capture
                    </button>
                  ) : (
                    <p>Artifact unavailable</p>
                  )}
                </div>
              ))}
            </details>
          </section>
        ))
      )}
      {evidence && (
        <EvidenceInspector id={evidence} onClose={() => setEvidence(null)} />
      )}
    </>
  );
}
