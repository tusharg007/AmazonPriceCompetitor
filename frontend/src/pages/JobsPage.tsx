import { useState } from "react";
import { Link } from "react-router-dom";
import { useJobs } from "../api/queries";
import { timestamp } from "../format";
import {
  Empty,
  ErrorNotice,
  Loading,
  Pagination,
} from "../components/Feedback";
import { JobProgress } from "../components/JobProgress";

export function JobsPage() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const query = useJobs(page, status);
  return (
    <>
      <div className="page-heading">
        <p className="eyebrow">Durable collection queue</p>
        <h1>Jobs</h1>
        <p>
          Inspect collection progress, bounded retry attempts, and terminal
          failures.
        </p>
      </div>
      <section className="panel">
        <div className="section-line">
          <h2>Active and recent jobs</h2>
          <label>
            Status
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {[
                "queued",
                "running",
                "succeeded",
                "partial",
                "failed",
                "cancelled",
              ].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        </div>
        {query.isPending ? (
          <Loading />
        ) : query.error ? (
          <ErrorNotice error={query.error} retry={() => void query.refetch()} />
        ) : (
          <>
            {query.data.items.length === 0 ? (
              <Empty title="No jobs in this selection">
                Collection jobs appear after a product is queued.
              </Empty>
            ) : (
              <div className="table-scroll">
                <table>
                  <caption>Collection queue</caption>
                  <thead>
                    <tr>
                      <th>Created</th>
                      <th>Product</th>
                      <th>Kind</th>
                      <th>Status</th>
                      <th>Progress</th>
                      <th>Attempts / error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {query.data.items.map((j) => (
                      <tr key={j.id}>
                        <td>
                          <button
                            className="secondary"
                            onClick={() => setSelected(j.id)}
                          >
                            {timestamp(j.created_at)}
                          </button>
                          <small className="hash">{j.id}</small>
                        </td>
                        <td>
                          <Link to={`/products/${j.product_id}`}>
                            Product {j.product_id}
                          </Link>
                        </td>
                        <td>{j.kind.replaceAll("_", " ")}</td>
                        <td>
                          <span className={`badge ${j.status}`}>
                            {j.status}
                          </span>
                        </td>
                        <td>
                          <progress max={100} value={j.progress} />
                          <small>{j.progress}%</small>
                        </td>
                        <td>
                          {j.attempts}/{j.max_attempts}
                          <small>{j.error_message || "—"}</small>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Pagination
              page={page}
              total={query.data.total}
              limit={query.data.limit}
              onChange={setPage}
            />
          </>
        )}
        {selected && <JobProgress id={selected} />}
      </section>
    </>
  );
}
