export const API_BASE = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
  ) {
    super(message);
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const issues = error.issues
      ?.map((issue: { msg: string }) => issue.msg)
      .join("; ");
    throw new ApiError(
      issues || error.detail || "Request failed. Please try again.",
      response.status,
      error.error || "request_failed",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export function socketURL(jobId: string): string {
  const url = new URL(
    `${API_BASE}/ws/jobs/${encodeURIComponent(jobId)}`,
    window.location.href,
  );
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
