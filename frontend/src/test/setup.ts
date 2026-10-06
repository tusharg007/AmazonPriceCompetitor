import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeAll, afterAll, vi } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
export const server = setupServer(
  http.get("*/api/products/:id/analytics", () =>
    HttpResponse.json({
      product_id: 1,
      currency: "USD",
      window_days: 30,
      as_of: "2026-10-06T12:00:00Z",
      observation_count: 0,
      priced_count: 0,
      minimum: null,
      maximum: null,
      average: null,
      current: null,
      previous: null,
      change: null,
      change_percent: null,
      recent_average: null,
      prior_average: null,
      trend_change_percent: null,
      trend: "insufficient_data",
      daily: [],
    }),
  ),
  http.get("*/api/products/:id/position", () =>
    HttpResponse.json({
      product_id: 1,
      currency: "USD",
      price_rank: null,
      price_percentile: null,
      total_in_set: 0,
      median: null,
      excluded_count: 0,
      reason: "Insufficient comparable current prices",
      entries: [],
    }),
  ),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
Object.defineProperty(window, "WebSocket", {
  value: class {
    onmessage = null;
    close() {}
  },
  writable: true,
});
Object.defineProperty(window, "ResizeObserver", {
  value: class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
});
HTMLDialogElement.prototype.showModal = vi.fn(function (
  this: HTMLDialogElement,
) {
  this.setAttribute("open", "");
});
HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
  this.removeAttribute("open");
});
