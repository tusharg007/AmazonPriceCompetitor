import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { API_BASE, apiFetch } from "../api/client";
import type { Evidence } from "../api/types";
import { timestamp } from "../format";
import { ErrorNotice, Loading } from "./Feedback";

export function EvidenceInspector({
  id,
  onClose,
}: {
  id: string;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const query = useQuery({
    queryKey: ["evidence", id],
    queryFn: () => apiFetch<Evidence>(`/api/evidence/${id}`),
  });
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return (
    <dialog ref={dialog} onCancel={onClose} aria-labelledby="evidence-heading">
      <div className="section-line">
        <h2 id="evidence-heading">Evidence inspector</h2>
        <button
          className="secondary"
          onClick={onClose}
          aria-label="Close evidence inspector"
        >
          Close
        </button>
      </div>
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorNotice error={query.error} />
      ) : (
        <>
          <p>
            Original captured page evidence. Values remain linked to this
            capture.
          </p>
          <dl className="evidence-grid">
            <dt>Source URL</dt>
            <dd>
              <a href={query.data.source_url} target="_blank" rel="noreferrer">
                {query.data.source_url}
              </a>
            </dd>
            <dt>Captured</dt>
            <dd>{timestamp(query.data.captured_at)}</dd>
            <dt>Collector</dt>
            <dd>{query.data.collector}</dd>
            <dt>Type</dt>
            <dd>{query.data.evidence_type}</dd>
            <dt>SHA-256</dt>
            <dd className="hash">{query.data.content_hash}</dd>
            <dt>Size</dt>
            <dd>{query.data.content_size_bytes.toLocaleString()} bytes</dd>
          </dl>
          <a className="button" href={`${API_BASE}/api/evidence/${id}/content`}>
            Download verified evidence
          </a>
        </>
      )}
    </dialog>
  );
}
