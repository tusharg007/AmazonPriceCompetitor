import { Link, NavLink, Route, Routes } from "react-router-dom";
import { lazy, Suspense } from "react";
const Dashboard = lazy(() =>
  import("./pages/Dashboard").then((m) => ({ default: m.Dashboard })),
);
const ProductDetail = lazy(() =>
  import("./pages/ProductDetail").then((m) => ({ default: m.ProductDetail })),
);
const JobsPage = lazy(() =>
  import("./pages/JobsPage").then((m) => ({ default: m.JobsPage })),
);
const AnalysisView = lazy(() =>
  import("./pages/AnalysisView").then((m) => ({ default: m.AnalysisView })),
);

export function App() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header>
        <Link className="brand" to="/">
          ACI <span>Amazon Competitor Intelligence</span>
        </Link>
        <nav aria-label="Main">
          <NavLink to="/" end>
            Products
          </NavLink>
          <NavLink to="/jobs">Jobs</NavLink>
        </nav>
      </header>
      <main id="main">
        <Suspense fallback={<p role="status">Loading page…</p>}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/products/:id" element={<ProductDetail />} />
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/analyses/:id" element={<AnalysisView />} />
            <Route
              path="*"
              element={
                <section>
                  <h1>Page not found</h1>
                  <Link to="/">Return to products</Link>
                </section>
              }
            />
          </Routes>
        </Suspense>
      </main>
      <footer>
        Captured evidence · Deterministic matching · Local research workspace
      </footer>
    </>
  );
}
