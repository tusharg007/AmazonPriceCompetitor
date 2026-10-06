import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi, expect, it } from "vitest";
import type { ReactNode } from "react";
import { useJobProgress } from "../hooks/useJobProgress";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

it("leaves polling available when WebSocket construction fails", () => {
  vi.stubGlobal(
    "WebSocket",
    class {
      constructor() {
        throw new Error("Unavailable");
      }
    },
  );
  const hook = renderHook(() => useJobProgress("test-job"), { wrapper });
  expect(hook.result.current).toBeNull();
  vi.unstubAllGlobals();
});

it("rejects malformed progress and closes the socket on teardown", () => {
  const close = vi.fn();
  const socket: {
    onmessage: ((event: { data: string }) => void) | null;
    close: () => void;
  } = { onmessage: null, close };
  vi.stubGlobal(
    "WebSocket",
    class {
      onmessage: typeof socket.onmessage = null;
      close: () => void = close;
      constructor() {
        return socket;
      }
    },
  );
  const hook = renderHook(() => useJobProgress("test-job"), { wrapper });
  act(() =>
    socket.onmessage?.({
      data: JSON.stringify({ status: "running", progress: 101 }),
    }),
  );
  expect(hook.result.current).toBeNull();
  act(() =>
    socket.onmessage?.({
      data: JSON.stringify({ status: "running", progress: 40 }),
    }),
  );
  expect(hook.result.current?.progress).toBe(40);
  hook.unmount();
  expect(close).toHaveBeenCalled();
  vi.unstubAllGlobals();
});
