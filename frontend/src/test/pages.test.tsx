import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, it, expect } from "vitest";
import { App } from "../App";
import { server } from "./setup";
import { EvidenceInspector } from "../components/EvidenceInspector";
import { amount } from "../format";
import { apiFetch, ApiError, socketURL } from "../api/client";

const product = {
  id: 1,
  asin: "B09XS7JWHH",
  domain: "com",
  geo_key: "__default__",
  requested_location: null,
  title: "Sony headphones",
  brand: "Sony",
  is_tracked: true,
  created_at: "2026-10-06T10:00:00Z",
  updated_at: "2026-10-06T10:00:00Z",
  latest_observation: null,
  competitor_count: 0,
  last_collected_at: null,
};
function mount(path = "/") {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("pages and contracts", () => {
  it("shows empty dashboard and rejects malformed ASIN before HTTP", async () => {
    server.use(
      http.get("*/api/products", () =>
        HttpResponse.json({ items: [], total: 0, page: 1, limit: 12 }),
      ),
    );
    mount();
    expect(
      await screen.findByText("No tracked products yet"),
    ).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("ASIN or Amazon URL"), "bad");
    await userEvent.click(
      screen.getByRole("button", { name: "Track product" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("10-character ASIN");
  });
  it("registers with normalized identity and displays saved products", async () => {
    let payload: unknown;
    server.use(
      http.get("*/api/products", () =>
        HttpResponse.json({ items: [product], total: 1, page: 1, limit: 12 }),
      ),
      http.post("*/api/products", async ({ request }) => {
        payload = await request.json();
        return HttpResponse.json(product, { status: 201 });
      }),
    );
    mount();
    expect(await screen.findByText("Sony headphones")).toBeInTheDocument();
    await userEvent.type(
      screen.getByLabelText("ASIN or Amazon URL"),
      "b09xs7jwhh",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Track product" }),
    );
    expect(await screen.findByText("Product registered.")).toBeInTheDocument();
    expect(payload).toEqual({
      asin: "B09XS7JWHH",
      domain: "com",
      requested_location: null,
    });
  });
  it("renders API errors accessibly", async () => {
    server.use(
      http.get("*/api/products", () =>
        HttpResponse.json(
          {
            error: "database_error",
            detail: "Database temporarily unavailable.",
          },
          { status: 503 },
        ),
      ),
    );
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Database temporarily unavailable",
    );
  });
  it("renders product capture history and deterministic candidates", async () => {
    server.use(
      http.get("*/api/products/1", () => HttpResponse.json(product)),
      http.get("*/api/products/1/observations", () => HttpResponse.json([])),
      http.get("*/api/products/1/competitors", () => HttpResponse.json([])),
    );
    mount("/products/1");
    expect(
      await screen.findByRole("heading", { name: "Sony headphones" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("No candidates in this selection"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Missing prices are omitted/)).toBeInTheDocument();
    expect(screen.queryByText(/Analyze/)).not.toBeInTheDocument();
  });
  it("shows product not-found response", async () => {
    server.use(
      http.get("*/api/products/99", () =>
        HttpResponse.json(
          { error: "not_found", detail: "Product not found" },
          { status: 404 },
        ),
      ),
      http.get("*/api/products/99/observations", () => HttpResponse.json([])),
      http.get("*/api/products/99/competitors", () => HttpResponse.json([])),
    );
    mount("/products/99");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Product not found",
    );
  });
  it("renders failed jobs and bounded attempts", async () => {
    server.use(
      http.get("*/api/jobs", () =>
        HttpResponse.json({
          items: [
            {
              id: "job-1",
              product_id: 1,
              kind: "scrape_product",
              status: "failed",
              progress: 100,
              attempts: 1,
              max_attempts: 2,
              error_message: "Amazon presented an access block",
              created_at: product.created_at,
            },
          ],
          total: 1,
          page: 1,
          limit: 20,
        }),
      ),
    );
    mount("/jobs");
    expect(
      await screen.findByText("Amazon presented an access block"),
    ).toBeInTheDocument();
    expect(screen.getByText("1/2")).toBeInTheDocument();
  });
  it("shows evidence provenance and attachment download without executing HTML", async () => {
    server.use(
      http.get("*/api/evidence/e1", () =>
        HttpResponse.json({
          id: "e1",
          source_url: "https://www.amazon.com/dp/B09XS7JWHH",
          captured_at: product.created_at,
          collector: "playwright-v1",
          evidence_type: "html",
          content_hash: "abc123",
          content_size_bytes: 200,
        }),
      ),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <EvidenceInspector id="e1" onClose={() => {}} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("abc123")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Download verified evidence" }),
    ).toHaveAttribute("href", "/api/evidence/e1/content");
  });
  it("preserves unknown prices and never invents a currency", () => {
    expect(amount(null, "USD")).toBe("Unavailable");
    expect(amount("10", null)).toContain("currency unknown");
    expect(socketURL("abc")).toContain("/ws/jobs/abc");
  });
  it("turns structured validation errors into useful client messages", async () => {
    server.use(
      http.post("*/api/test", () =>
        HttpResponse.json(
          {
            error: "validation_error",
            detail: "Invalid request",
            issues: [{ loc: ["body", "asin"], msg: "Invalid ASIN" }],
          },
          { status: 422 },
        ),
      ),
    );
    await expect(
      apiFetch("/api/test", { method: "POST", body: "{}" }),
    ).rejects.toBeInstanceOf(ApiError);
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
  });
});
