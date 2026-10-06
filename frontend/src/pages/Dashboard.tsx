import { useState } from "react";
import { Link } from "react-router-dom";
import { useProducts, useRegister } from "../api/queries";
import { amount, timestamp } from "../format";
import {
  Empty,
  ErrorNotice,
  Loading,
  Pagination,
} from "../components/Feedback";

export function Dashboard() {
  const [page, setPage] = useState(1);
  const query = useProducts(page);
  const register = useRegister();
  const [identity, setIdentity] = useState("");
  const [domain, setDomain] = useState("com");
  const [location, setLocation] = useState("");
  const [validation, setValidation] = useState("");
  return (
    <>
      <div className="page-heading">
        <p className="eyebrow">Research workspace</p>
        <h1>Track products. Compare evidence.</h1>
        <p>
          Register an Amazon listing, collect dated snapshots, and inspect why a
          candidate matches.
        </p>
      </div>
      <section className="panel">
        <h2>Add a product</h2>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const value = identity.trim();
            if (
              !value.startsWith("https://") &&
              !/^[A-Z0-9]{10}$/i.test(value)
            ) {
              setValidation(
                "Enter a 10-character ASIN or an HTTPS Amazon product URL.",
              );
              return;
            }
            setValidation("");
            register.mutate(
              value.startsWith("https://")
                ? { url: value, requested_location: location || null }
                : {
                    asin: value.toUpperCase(),
                    domain,
                    requested_location: location || null,
                  },
              {
                onSuccess: () => {
                  setIdentity("");
                  setPage(1);
                },
              },
            );
          }}
        >
          <div className="form-grid">
            <label>
              ASIN or Amazon URL
              <input
                required
                value={identity}
                onChange={(e) => setIdentity(e.target.value)}
                placeholder="10-character ASIN or https://www.amazon…"
              />
            </label>
            <label>
              Marketplace
              <select
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
              >
                {["com", "in", "ca", "co.uk", "de", "fr", "it", "ae"].map(
                  (d) => (
                    <option key={d} value={d}>
                      amazon.{d}
                    </option>
                  ),
                )}
              </select>
            </label>
            <label>
              Delivery postal code (optional)
              <input
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="Marketplace postal code"
              />
            </label>
          </div>
          <p className="muted">
            For URLs, the marketplace is taken from the URL. Collection starts
            only when requested.
          </p>
          {validation && (
            <p role="alert" className="error">
              {validation}
            </p>
          )}
          {register.error && <ErrorNotice error={register.error} />}
          <button disabled={register.isPending}>
            {register.isPending ? "Registering…" : "Track product"}
          </button>
          {register.isSuccess && <p role="status">Product registered.</p>}
        </form>
      </section>
      <section>
        <div className="section-line">
          <h2>Tracked products</h2>
          <button className="secondary" onClick={() => void query.refetch()}>
            Refresh
          </button>
        </div>
        {query.isPending ? (
          <Loading />
        ) : query.error ? (
          <ErrorNotice error={query.error} retry={() => void query.refetch()} />
        ) : (
          <>
            {query.data.items.length === 0 ? (
              <Empty title="No tracked products yet">
                Add an ASIN or product URL above to begin.
              </Empty>
            ) : (
              <div className="product-grid">
                {query.data.items.map((p) => (
                  <article className="panel product-card" key={p.id}>
                    <div className="section-line">
                      <span className="badge">amazon.{p.domain}</span>
                      <span className="muted">{p.asin}</span>
                    </div>
                    <h3>
                      <Link to={`/products/${p.id}`}>{p.title || p.asin}</Link>
                    </h3>
                    <p className="price">
                      {amount(
                        p.latest_observation?.price_amount,
                        p.latest_observation?.currency,
                      )}
                    </p>
                    <p>{p.brand || "Brand not captured"}</p>
                    <span className="badge">
                      Price trend:{" "}
                      {(p.price_trend || "insufficient_data").replaceAll(
                        "_",
                        " ",
                      )}
                    </span>
                    <p className="muted">
                      {p.requested_location || "Default delivery context"} ·{" "}
                      {p.competitor_count} candidates
                    </p>
                    <p className="muted">
                      Captured: {timestamp(p.last_collected_at)}
                    </p>
                    <Link className="button secondary" to={`/products/${p.id}`}>
                      Inspect product
                    </Link>
                  </article>
                ))}
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
      </section>
    </>
  );
}
