import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "./api";
import type { Filters, PackageName, ResultDetail, Run, Status, Summary, TestResult, TrendResponse } from "./types";

const packages: PackageName[] = ["environment", "driver", "gpu", "cpu"];
const statuses: Status[] = ["PASS", "FAIL", "ERROR", "SKIP"];
const initialFilters: Filters = {
  execution_mode: "real",
  package: "",
  machine: "",
  status: "",
  test_key: "",
  started_after: "",
  started_before: "",
};

function StatusPill({ value }: { value: string }) {
  return <span className={`pill status-${value.toLowerCase()}`}>{value}</span>;
}

function Empty({ children }: { children: string }) {
  return <div className="empty">{children}</div>;
}

export default function App() {
  const [filters, setFilters] = useState(initialFilters);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [laneSummary, setLaneSummary] = useState<Summary | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [results, setResults] = useState<TestResult[]>([]);
  const [selectedResult, setSelectedResult] = useState<ResultDetail | null>(null);
  const [trendData, setTrendData] = useState<TrendResponse>({ items: [], baseline: null, comparison: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const filterKey = JSON.stringify(filters);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const allLaneFilters: Filters = { ...filters, package: "" };
    Promise.all([api.summary(filters), api.summary(allLaneFilters), api.runs(filters)])
      .then(([summaryData, laneSummaryData, runData]) => {
        if (!active) return;
        setSummary(summaryData);
        setLaneSummary(laneSummaryData);
        setRuns(runData.items);
      })
      .catch((reason: Error) => active && setError(reason.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [filterKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedRun) return;
    let active = true;
    api.results(selectedRun.run_id, filters)
      .then((data) => active && setResults(data.items))
      .catch((reason: Error) => active && setError(reason.message));
    const timer = selectedRun.status === "RUNNING" ? window.setInterval(() => {
      api.run(selectedRun.run_id).then((data) => active && setSelectedRun(data)).catch(() => undefined);
    }, 5000) : undefined;
    return () => {
      active = false;
      if (timer) window.clearInterval(timer);
    };
  }, [selectedRun?.run_id, selectedRun?.status, filterKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    api.trends("cpu.workload", "elapsed", filters.execution_mode, filters.machine)
      .then((data) => setTrendData({ ...data, items: [...data.items].reverse() }))
      .catch(() => setTrendData({ items: [], baseline: null, comparison: null }));
  }, [filters.execution_mode, filters.machine]);

  const update = (name: keyof Filters, value: string) => setFilters((current) => ({ ...current, [name]: value }));
  const passRate = summary?.pass_rate == null ? "—" : `${(summary.pass_rate * 100).toFixed(1)}%`;
  const chartData = useMemo(
    () => trendData.items.map((item) => ({ ...item, label: new Date(item.timestamp).toLocaleString() })),
    [trendData.items],
  );

  return (
    <main>
      <header className="hero">
        <div>
          <p className="eyebrow">SYSTEM QUALIFICATION CONSOLE</p>
          <h1>Workstation Test Lab</h1>
          <p className="subtitle">Trace every probe from immutable package logs to comparable measurements.</p>
        </div>
        <div className="live"><span /> API DATA</div>
      </header>

      <section className="filter-panel" aria-label="Result filters">
        <label>Mode<select value={filters.execution_mode} onChange={(event) => update("execution_mode", event.target.value)}><option value="real">Real hardware</option><option value="simulated">Simulation</option><option value="all">All modes</option></select></label>
        <label>Package<select value={filters.package} onChange={(event) => update("package", event.target.value)}><option value="">All packages</option>{packages.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label>Status<select value={filters.status} onChange={(event) => update("status", event.target.value)}><option value="">All statuses</option>{statuses.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label>Machine<input value={filters.machine} onChange={(event) => update("machine", event.target.value)} placeholder="lab-001" /></label>
        <label>From<input type="date" value={filters.started_after} onChange={(event) => update("started_after", event.target.value)} /></label>
        <label>To<input type="date" value={filters.started_before} onChange={(event) => update("started_before", event.target.value)} /></label>
        <button className="clear" onClick={() => setFilters(initialFilters)}>Clear filters</button>
      </section>

      {filters.execution_mode === "simulated" && <div className="simulation-banner">SIMULATION DATA — synthetic hardware values</div>}
      {filters.execution_mode === "all" && <div className="simulation-banner">MIXED MODES — rows retain their individual mode labels</div>}
      {error && <div className="error" role="alert"><strong>API unavailable</strong><span>{error}</span></div>}

      <section className="metrics" aria-label="Overview">
        <article><span>Pass rate</span><strong>{passRate}</strong><small>PASS / evaluated</small></article>
        <article><span>Runs</span><strong>{summary?.run_count ?? "—"}</strong><small>in current selection</small></article>
        <article><span>Needs attention</span><strong>{(summary?.status_counts.FAIL ?? 0) + (summary?.status_counts.ERROR ?? 0)}</strong><small>failures and errors</small></article>
        <article><span>Incomplete</span><strong>{summary?.incomplete_run_count ?? "—"}</strong><small>missing package ingestion</small></article>
      </section>

      <section>
        <div className="section-heading"><div><p className="eyebrow">PACKAGE HEALTH</p><h2>Four independent test lanes</h2></div></div>
        <div className="package-grid">
          {packages.map((name) => {
            const counts = laneSummary?.package_counts[name];
            return <button key={name} className={`package-card ${filters.package === name ? "selected" : ""}`} onClick={() => update("package", filters.package === name ? "" : name)}>
              <div><span className="package-index">0{packages.indexOf(name) + 1}</span><h3>{name}</h3></div>
              <div className="status-row">{statuses.map((status) => <span key={status} title={status}><i className={`dot status-${status.toLowerCase()}`} />{counts?.[status] ?? 0}</span>)}</div>
            </button>;
          })}
        </div>
      </section>

      <section className="split">
        <div className="panel runs-panel">
          <div className="section-heading"><div><p className="eyebrow">RUN HISTORY</p><h2>Recent executions</h2></div>{loading && <span>Loading…</span>}</div>
          {!loading && runs.length === 0 ? <Empty>No runs match these filters.</Empty> : <div className="table-wrap"><table><thead><tr><th>Started</th><th>Machine</th><th>Mode</th><th>State</th><th>Packages</th></tr></thead><tbody>
            {runs.map((run) => <tr key={run.run_id} className={selectedRun?.run_id === run.run_id ? "active" : ""} onClick={() => { setSelectedRun(run); setSelectedResult(null); }} tabIndex={0} onKeyDown={(event) => event.key === "Enter" && setSelectedRun(run)}>
              <td>{new Date(run.started_at).toLocaleString()}</td><td>{run.machine_id}</td><td><span className={`pill mode-${run.execution_mode}`}>{run.execution_mode}</span></td><td><StatusPill value={run.completeness.complete ? run.status : "INCOMPLETE"} /></td><td>{run.completeness.ingested_packages.length}/{run.selected_packages.length}</td>
            </tr>)}
          </tbody></table></div>}
        </div>

        <aside className="panel detail-panel">
          <p className="eyebrow">RUN INSPECTOR</p>
          {!selectedRun ? <Empty>Select a run to inspect its environment and results.</Empty> : <>
            <div className="detail-title"><h2>{selectedRun.machine_id}</h2><span className={`pill mode-${selectedRun.execution_mode}`}>{selectedRun.execution_mode}</span></div>
            <dl className="facts"><div><dt>Run</dt><dd title={selectedRun.run_id}>{selectedRun.run_id.slice(0, 13)}…</dd></div><div><dt>Driver</dt><dd>{String(selectedRun.environment_snapshot.driver || "Unavailable")}</dd></div><div><dt>OS</dt><dd>{String(selectedRun.environment_snapshot.os || "Unknown")}</dd></div><div><dt>Missing</dt><dd>{selectedRun.completeness.missing_packages.join(", ") || "None"}</dd></div></dl>
            <label className="search">Test key<input value={filters.test_key} onChange={(event) => update("test_key", event.target.value)} placeholder="gpu.detect" /></label>
            <div className="result-list">{results.length === 0 ? <Empty>No results match this run and filter.</Empty> : results.map((result) => <button key={result.result_id} onClick={() => api.result(result.result_id).then(setSelectedResult).catch((reason: Error) => setError(reason.message))}><StatusPill value={result.status} /><span><strong>{result.test_key}</strong><small>Attempt {result.attempt} · {result.duration_ms} ms</small></span><b>›</b></button>)}</div>
          </>}
        </aside>
      </section>

      {selectedResult && <section className="panel result-detail">
        <div className="section-heading"><div><p className="eyebrow">RESULT DETAIL</p><h2>{selectedResult.test_key}</h2></div><button className="close" onClick={() => setSelectedResult(null)} aria-label="Close result detail">×</button></div>
        <div className="detail-title"><StatusPill value={selectedResult.status} /><span>Attempt {selectedResult.attempt}</span><span>{selectedResult.duration_ms} ms</span>{selectedResult.failure_category && <span>Category: {selectedResult.failure_category}</span>}</div>
        <p className="message">{selectedResult.message}</p>
        {selectedResult.metrics.length > 0 && <div className="metric-chips">{selectedResult.metrics.map((metric, index) => <span key={`${metric.name}-${index}`}><b>{metric.value.toLocaleString()}</b> {metric.unit}<small>{metric.name} · sample {metric.iteration}</small></span>)}</div>}
        {selectedResult.artifacts.length > 0 && <div className="artifact-list">{selectedResult.artifacts.map((artifact) => <a key={artifact.artifact_id} href={api.artifactUrl(artifact.artifact_id)} target="_blank" rel="noreferrer">Open {artifact.kind}: {artifact.filename}</a>)}</div>}
      </section>}

      <section className="panel performance">
        <div className="section-heading"><div><p className="eyebrow">PERFORMANCE</p><h2>CPU workload trend</h2></div><span>elapsed · lower is better</span></div>
        {trendData.comparison && <div className={`comparison comparison-${trendData.comparison.state}`}><strong>{trendData.comparison.state.replace("_", " ")}</strong><span>{trendData.comparison.degradation_percent == null ? trendData.comparison.reason : `${trendData.comparison.degradation_percent.toFixed(1)}% degradation · ${trendData.comparison.statistics.count} samples · CV ${trendData.comparison.statistics.coefficient_of_variation?.toFixed(1) ?? "—"}%`}</span>{trendData.baseline && <small>Approved baseline {trendData.baseline.value} {trendData.baseline.unit} by {trendData.baseline.approved_by}</small>}</div>}
        {chartData.length === 0 ? <Empty>No comparable CPU measurements in this selection.</Empty> : <div className="chart" aria-label="CPU elapsed time trend chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={chartData}><CartesianGrid stroke="#263047" strokeDasharray="3 3" /><XAxis dataKey="label" tick={{ fill: "#8993a8", fontSize: 11 }} /><YAxis tick={{ fill: "#8993a8", fontSize: 11 }} unit=" ms" /><Tooltip contentStyle={{ background: "#141a2b", border: "1px solid #39445e" }} /><Line dataKey="value" type="monotone" stroke="#78f0c4" strokeWidth={2} dot={{ fill: "#78f0c4" }} /></LineChart></ResponsiveContainer></div>}
      </section>
      <footer>WORKSTATION TEST LAB · LOCAL DEMO · UTC DATA</footer>
    </main>
  );
}

