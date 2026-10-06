import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { it, expect } from "vitest";
import { App } from "../App";
import { server } from "./setup";

const id = "00000000-0000-0000-0000-000000000001";
function mount() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[`/analyses/${id}`]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("renders labelled claims and exact observation citations", async () => {
  server.use(
    http.get("*/api/analyses/:id", () =>
      HttpResponse.json({
        id,
        product_id: 1,
        status: "succeeded",
        model: "test-model",
        completed_at: "2026-10-06T10:00:00Z",
        input_hash: "abc",
        prompt_version: "v1",
        schema_version: "v2",
        claims: [
          {
            id: "claim",
            claim_type: "summary",
            claim_text: "A filtered cohort of stored listing claims.",
            claim_value: { origin: "llm_interpretation" },
            evidence: [
              {
                observation_id: "obs",
                product_id: 1,
                product_asin: "B000000001",
                price_text: "$100",
                captured_at: "2026-10-06T10:00:00Z",
                collector: "playwright-v1",
                extraction_method: "json_ld",
                evidence_id: "hash",
                role: "baseline",
                evidence_artifact_id: null,
              },
            ],
          },
        ],
        withheld_quantitative_claims: 1,
      }),
    ),
  );
  mount();
  expect(
    await screen.findByText("Generated interpretation"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/quantitative statements were withheld/),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByText("Source captures (1)"));
  expect(screen.getByText(/Observation: obs/)).toBeVisible();
  expect(
    screen.getByText(/do not prove every interpretation/),
  ).toBeInTheDocument();
});
it("handles analysis not found", async () => {
  server.use(
    http.get("*/api/analyses/:id", () =>
      HttpResponse.json(
        { detail: "Analysis run not found", error: "not_found" },
        { status: 404 },
      ),
    ),
  );
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Analysis run not found",
  );
});
it("handles failed analysis without placeholder insights", async () => {
  server.use(
    http.get("*/api/analyses/:id", () =>
      HttpResponse.json({
        id,
        product_id: 1,
        status: "failed",
        model: "test",
        completed_at: null,
        input_hash: "abc",
        prompt_version: "v1",
        schema_version: "v2",
        claims: [],
        error_message: "Provider unavailable",
      }),
    ),
  );
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Provider unavailable",
  );
  expect(screen.getByText("No validated claims saved")).toBeInTheDocument();
});
