import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { AnalyticsPanel } from "../components/AnalyticsPanel";
import { server } from "./setup";

function mount() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AnalyticsPanel id={1} days={30} currency="USD" />
    </QueryClientProvider>,
  );
}
it("renders insufficient history without fabricated trends and CSV export", async () => {
  mount();
  expect(
    await screen.findByText("Trend: insufficient data"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Export capture CSV" }),
  ).toHaveAttribute("href", "/api/products/1/observations/export");
  expect(
    await screen.findByRole("heading", {
      name: "Insufficient comparable current prices",
    }),
  ).toBeInTheDocument();
});
it("renders useful analytics API errors", async () => {
  server.use(
    http.get("*/api/products/1/analytics", () =>
      HttpResponse.json(
        { detail: "Database temporarily unavailable" },
        { status: 503 },
      ),
    ),
  );
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Database temporarily unavailable",
  );
});
