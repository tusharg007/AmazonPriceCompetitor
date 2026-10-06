import { Link, NavLink, Route, Routes } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { ProductDetail } from "./pages/ProductDetail";
import { JobsPage } from "./pages/JobsPage";

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
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/products/:id" element={<ProductDetail />} />
          <Route path="/jobs" element={<JobsPage />} />
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
      </main>
      <footer>
        Captured evidence · Deterministic matching · Local research workspace
      </footer>
    </>
  );
}
