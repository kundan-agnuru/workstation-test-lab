export type Mode = "real" | "simulated" | "all";
export type Status = "PASS" | "FAIL" | "ERROR" | "SKIP";
export type PackageName = "environment" | "driver" | "gpu" | "cpu";

export interface Completeness {
  ingested_packages: string[];
  missing_packages: string[];
  complete: boolean;
}

export interface Run {
  run_id: string;
  machine_id: string;
  status: "RUNNING" | "COMPLETED" | "ABORTED";
  execution_mode: "real" | "simulated";
  selected_packages: PackageName[];
  environment_snapshot: Record<string, unknown>;
  started_at: string;
  ended_at: string | null;
  completeness: Completeness;
  status_counts?: Record<Status, number>;
}

export interface TestResult {
  result_id: number;
  package_execution_id: string;
  package: PackageName;
  test_key: string;
  attempt: number;
  status: Status;
  duration_ms: number;
  timestamp: string;
  failure_category: string | null;
  message: string;
}

export interface ResultDetail extends TestResult {
  metrics: Array<{ name: string; value: number; unit: string; iteration: number; direction: string }>;
  artifacts: Array<{ artifact_id: number; kind: string; filename: string; sha256: string; media_type: string }>;
}

export interface Summary {
  status_counts: Record<Status, number>;
  pass_rate: number | null;
  run_count: number;
  incomplete_run_count: number;
  package_counts: Record<PackageName, Record<Status, number>>;
}

export interface Filters {
  execution_mode: Mode;
  package: string;
  machine: string;
  status: string;
  test_key: string;
  started_after: string;
  started_before: string;
}

export interface TrendPoint {
  timestamp: string;
  value: number;
  unit: string;
  iteration: number;
  direction: string;
  run_id: string;
  machine_id: string;
}

export interface TrendResponse {
  items: TrendPoint[];
  baseline: null | { baseline_id: number; value: number; unit: string; direction: string; approved_by: string; approved_at: string };
  comparison: null | {
    state: "degraded" | "within_threshold" | "inconclusive";
    degradation_percent: number | null;
    reason: string;
    statistics: { count: number; mean: number; median: number; standard_deviation: number | null; coefficient_of_variation: number | null };
  };
}

