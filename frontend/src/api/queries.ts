import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type {
  Job,
  Match,
  Observation,
  Page,
  Product,
  ProductInput,
} from "./types";

export const active = (status?: string) =>
  status === "queued" || status === "running";
export const useProducts = (page = 1) =>
  useQuery({
    queryKey: ["products", page],
    queryFn: () =>
      apiFetch<Page<Product>>(`/api/products?page=${page}&limit=12`),
    refetchInterval: 30000,
  });
export const useProduct = (id: number) =>
  useQuery({
    queryKey: ["product", id],
    queryFn: () => apiFetch<Product>(`/api/products/${id}`),
    enabled: Number.isInteger(id) && id > 0,
  });
export const useHistory = (id: number, days: number) =>
  useQuery({
    queryKey: ["observations", id, days],
    queryFn: () =>
      apiFetch<Observation[]>(
        `/api/products/${id}/observations?limit=1000&from=${encodeURIComponent(new Date(Date.now() - days * 86400000).toISOString())}`,
      ),
    enabled: id > 0,
  });
export const useMatches = (id: number, status = "", page = 1) =>
  useQuery({
    queryKey: ["competitors", id, status, page],
    queryFn: async () => {
      let total = 0;
      const items = await apiFetch<Match[]>(
        `/api/products/${id}/competitors?limit=20&offset=${(page - 1) * 20}${status ? `&status=${status}` : ""}`,
        undefined,
        (headers) => {
          total = Number(headers.get("X-Total-Count") || 0);
        },
      );
      return { items, total, page, limit: 20 };
    },
    enabled: id > 0,
  });

export const useAnalytics = (id: number, days: number, currency: string) =>
  useQuery({
    queryKey: ["analytics", id, days, currency],
    queryFn: () =>
      apiFetch<import("./types").Analytics>(
        `/api/products/${id}/analytics?window_days=${days}${currency ? `&currency=${currency}` : ""}`,
      ),
    enabled: id > 0,
  });
export const usePosition = (id: number) =>
  useQuery({
    queryKey: ["position", id],
    queryFn: () =>
      apiFetch<import("./types").Position>(`/api/products/${id}/position`),
    enabled: id > 0,
  });
export const useJobs = (page = 1, status = "") =>
  useQuery({
    queryKey: ["jobs", page, status],
    queryFn: () =>
      apiFetch<Page<Job>>(
        `/api/jobs?page=${page}&limit=20${status ? `&status=${status}` : ""}`,
      ),
    refetchInterval: 5000,
  });
export const useJob = (id: string | null) =>
  useQuery({
    queryKey: ["job", id],
    queryFn: () => apiFetch<Job>(`/api/jobs/${id}`),
    enabled: !!id,
    refetchInterval: (query) =>
      active(query.state.data?.status) ? 3000 : false,
  });

export function useRegister() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: ProductInput) =>
      apiFetch<Product>("/api/products", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["products"] }),
  });
}

export function useCollect(id: number) {
  return useMutation({
    mutationFn: (include: boolean) =>
      apiFetch<Job>(`/api/products/${id}/collect`, {
        method: "POST",
        body: JSON.stringify({ include_competitors: include }),
      }),
  });
}

export function useAnalyze(id: number) {
  return useMutation({
    mutationFn: () =>
      apiFetch<Job>(`/api/products/${id}/analyze`, { method: "POST" }),
  });
}

export function useUntrack(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<void>(`/api/products/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["products"] }),
  });
}
