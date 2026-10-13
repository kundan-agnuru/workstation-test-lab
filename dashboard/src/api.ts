import type { Filters, Mode, PackageName, ResultDetail, Run, Summary, TestResult, TrendResponse } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

function params(input: Record<string, string | number | undefined>): string {
  const values = new URLSearchParams();
  Object.entries(input).forEach(([key, value]) => {
    if (value !== undefined && value !== "") values.set(key, String(value));
  });
  const query = values.toString();
  return query ? `?${query}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(typeof body.detail === "string" ? body.detail : `API returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function shared(filters: Filters): Record<string, string> {
  return {
    execution_mode: filters.execution_mode,
    machine: filters.machine,
    package: filters.package,
    started_after: filters.started_after ? new Date(`${filters.started_after}T00:00:00`).toISOString() : "",
    started_before: filters.started_before ? new Date(`${filters.started_before}T23:59:59`).toISOString() : "",
  };
}

export const api = {
  summary: (filters: Filters) => request<Summary>(`/api/v1/summary${params({ ...shared(filters), status: filters.status })}`),
  runs: (filters: Filters, offset = 0) =>
    request<{ items: Run[]; total: number; limit: number; offset: number }>(
      `/api/v1/runs${params({ ...shared(filters), status: filters.status, limit: 25, offset })}`,
    ),
  run: (id: string) => request<Run>(`/api/v1/runs/${id}`),
  results: (id: string, filters: Filters, offset = 0) =>
    request<{ items: TestResult[]; total: number; limit: number; offset: number }>(
      `/api/v1/runs/${id}/results${params({ package: filters.package, status: filters.status, test_key: filters.test_key, limit: 100, offset })}`,
    ),
  result: (id: number) => request<ResultDetail>(`/api/v1/results/${id}`),
  rerun: (packageName: PackageName, executionMode: Exclude<Mode, "all">) =>
    request<Run>(`/api/v1/reruns/${packageName}${params({ execution_mode: executionMode })}`, { method: "POST" }),
  rerunAll: (executionMode: Exclude<Mode, "all">) =>
    request<Run>(`/api/v1/reruns${params({ execution_mode: executionMode })}`, { method: "POST" }),
  trends: (testKey: string, metricName: string, mode: string, machine: string) =>
    request<TrendResponse>(
      `/api/v1/metrics/trends${params({ test_key: testKey, metric_name: metricName, execution_mode: mode, machine })}`,
    ),
  artifactUrl: (id: number) => `${API_BASE}/api/v1/artifacts/${id}`,
};

