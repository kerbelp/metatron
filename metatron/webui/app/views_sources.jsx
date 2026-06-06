/* ============================================================
   SOURCES cluster — Origins · Ingest telemetry
   ============================================================ */

/* ============================================================
   ORIGINS — where canonical knowledge comes from + accept rate
   ============================================================ */
const { useState, useEffect, useRef, useMemo, useCallback } = React;

function OriginsView({ repo }) {
  const res = useApi(() => MetatronAPI.getOrigins(repo), [repo]);
  if (res.loading) return <Loading label="Tracing knowledge origins…" />;
  if (res.error) return <ErrorState onRetry={res.reload} />;
  const origins = res.data.origins;
  const totalCanon = origins.reduce((a, o) => a + o.canonical, 0);
  const maxTotal = Math.max(...origins.map((o) => o.total));

  return (
    <div className="view">
      <SectionTitle eyebrow="Provenance" title="Where knowledge comes from" />

      {/* contribution bar */}
      <div className="panel pad enter" style={{ marginBottom: 18 }}>
        <div className="panel-head"><h3>Canonical knowledge by origin</h3><div className="spacer" /><span className="sub">{totalCanon} canonical decisions</span></div>
        <div style={{ display: "flex", height: 26, borderRadius: 8, overflow: "hidden", border: "1px solid var(--line)", marginBottom: 14 }}>
          {origins.map((o, i) => { const dot = { bootstrap: "var(--teal)", agent_submitted: "var(--violet)", agent_feedback: "var(--cyan)" }[o.origin]; return (
            <div key={o.origin} title={`${o.origin}: ${o.canonical}`} style={{ width: `${(o.canonical / totalCanon) * 100}%`, background: dot, opacity: .85, display: "grid", placeItems: "center", borderRight: i < origins.length - 1 ? "1px solid #04080a" : "none", animation: "growx 1s cubic-bezier(.3,.8,.3,1)", transformOrigin: "left" }}>
              <span className="mono" style={{ fontSize: 11, color: "#04100d", fontWeight: 600 }}>{o.canonical}</span>
            </div>); })}
        </div>
        <style>{`@keyframes growx{from{transform:scaleX(0)}}`}</style>
        <div style={{ display: "flex", gap: 22 }}>
          {origins.map((o) => <div key={o.origin} style={{ display: "flex", alignItems: "center", gap: 8 }}><OriginTag origin={o.origin} /></div>)}
        </div>
      </div>

      {/* per-origin cards */}
      <div className="grid" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
        {origins.map((o, i) => (
          <div key={o.origin} className="panel pad enter" style={{ animationDelay: i * 0.07 + "s" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
              <OriginTag origin={o.origin} />
              <span className="mono dim" style={{ fontSize: 10.5 }}>{o.total} total</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 18, marginBottom: 18 }}>
              <Donut segments={[{ value: o.accept_rate, color: o.accept_rate > 0.7 ? "var(--emerald)" : o.accept_rate > 0.5 ? "var(--amber)" : "var(--rose)" }, { value: 1 - o.accept_rate, color: "transparent" }]} size={92} thickness={9}>
                <div style={{ textAlign: "center" }}><div className="mono tnum" style={{ fontSize: 18, fontWeight: 600, color: o.accept_rate > 0.7 ? "var(--emerald)" : o.accept_rate > 0.5 ? "var(--amber)" : "var(--rose)" }}><CountUp value={o.accept_rate * 100} decimals={0} suffix="%" /></div></div>
              </Donut>
              <div>
                <div className="mono dim" style={{ fontSize: 9.5, letterSpacing: ".16em", marginBottom: 6 }}>ACCEPT RATE</div>
                <div className="muted" style={{ fontSize: 11.5, lineHeight: 1.5, maxWidth: 150 }}>{OriginDesc[o.origin]}</div>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              <BreakdownRow label="Canonical" n={o.canonical} max={maxTotal} c="var(--teal)" />
              <BreakdownRow label="Candidate" n={o.candidate} max={maxTotal} c="var(--amber)" />
              <BreakdownRow label="Rejected" n={o.rejected} max={maxTotal} c="var(--rose)" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function BreakdownRow({ label, n, max, c }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
      <span className="mono" style={{ fontSize: 10.5, color: "var(--muted)", width: 66 }}>{label}</span>
      <div style={{ flex: 1 }}><Meter value={n} max={max} color={c} height={6} /></div>
      <span className="mono tnum" style={{ fontSize: 12, color: "var(--text-2)", width: 22, textAlign: "right" }}>{n}</span>
    </div>
  );
}

/* ============================================================
   INGEST — knowledge-import run volume + estimated cost
   ============================================================ */
function IngestView({ repo }) {
  const res = useApi(() => MetatronAPI.getIngestCost(repo), [repo]);
  if (res.loading) return <Loading label="Reading ingest telemetry…" />;
  if (res.error) return <ErrorState onRetry={res.reload} />;
  const runs = res.data.runs;
  if (!runs.length) return <Empty title="No ingest runs yet" detail="Run the bootstrap miner to import knowledge from this repo." icon="layers" />;
  const latest = runs[0];
  const totalCost = runs.reduce((a, r) => a + r.estimated_cost, 0);
  const totalDecisions = runs.reduce((a, r) => a + r.decisions_created, 0);
  const fmt = (n) => n >= 1e6 ? (n / 1e6).toFixed(2) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : n;

  return (
    <div className="view">
      <SectionTitle eyebrow="Knowledge import" title="Ingest telemetry"
        right={<div style={{ display: "flex", gap: 24 }}>
          <div className="metric" style={{ textAlign: "right" }}><div className="big" style={{ fontSize: 22, color: "var(--emerald)" }}><CountUp value={totalCost} decimals={2} prefix="$" /></div><div className="lab">total spent</div></div>
          <div className="metric" style={{ textAlign: "right" }}><div className="big" style={{ fontSize: 22, color: "var(--teal)" }}><CountUp value={totalDecisions} /></div><div className="lab">decisions mined</div></div>
        </div>} />

      {/* latest run hero */}
      <div className="panel pad enter" style={{ marginBottom: 18, position: "relative", overflow: "hidden" }}>
        <div style={{ position: "absolute", right: -40, top: "50%", transform: "translateY(-50%)", opacity: .5, pointerEvents: "none" }}><MetatronCube size={300} opacity={0.1} /></div>
        <div className="panel-head"><span style={{ color: "var(--teal)" }}><Icon name="layers" size={16} /></span><h3>Latest run</h3><span className="badge ghost mono">{latest.model}</span><div className="spacer" /><span className="mono dim" style={{ fontSize: 11 }} title={new Date(latest.timestamp).toLocaleString()}>{timeAgo(latest.timestamp)}</span></div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr) 1.1fr", gap: 0, position: "relative" }}>
          <RunStat label="Files parsed" value={latest.files_parsed} />
          <RunStat label="Commits read" value={latest.commits_read} />
          <RunStat label="Scopes found" value={latest.scopes} />
          <RunStat label="Decisions created" value={latest.decisions_created} accent />
          <div style={{ paddingLeft: 24, borderLeft: "1px solid var(--line)" }}>
            <div className="mono dim" style={{ fontSize: 9.5, letterSpacing: ".18em", marginBottom: 12 }}>ESTIMATED COST</div>
            <div className="mono tnum" style={{ fontSize: 38, fontWeight: 600, color: "var(--emerald)", lineHeight: 1 }}><CountUp value={latest.estimated_cost} decimals={2} prefix="$" /></div>
            <div style={{ display: "flex", gap: 16, marginTop: 14 }}>
              <div><div className="mono dim" style={{ fontSize: 9, letterSpacing: ".12em" }}>INPUT TOK</div><div className="mono" style={{ fontSize: 13, color: "var(--text-2)" }}>{fmt(latest.input_tokens)}</div></div>
              <div><div className="mono dim" style={{ fontSize: 9, letterSpacing: ".12em" }}>OUTPUT TOK</div><div className="mono" style={{ fontSize: 13, color: "var(--text-2)" }}>{fmt(latest.output_tokens)}</div></div>
            </div>
          </div>
        </div>
        {/* token flow bar */}
        <div style={{ marginTop: 22 }}>
          <div className="mono dim" style={{ fontSize: 9.5, letterSpacing: ".16em", marginBottom: 8 }}>TOKEN VOLUME · INPUT vs OUTPUT</div>
          <div style={{ display: "flex", height: 10, borderRadius: 20, overflow: "hidden", background: "rgba(120,200,180,.08)" }}>
            <div style={{ width: `${latest.input_tokens / (latest.input_tokens + latest.output_tokens) * 100}%`, background: "linear-gradient(90deg,var(--teal-deep),var(--teal))", animation: "growx 1.1s cubic-bezier(.3,.8,.3,1)", transformOrigin: "left" }} />
            <div style={{ flex: 1, background: "var(--cyan)", opacity: .6 }} />
          </div>
        </div>
      </div>

      {/* run history table */}
      <div className="panel pad enter enter-2">
        <div className="panel-head"><h3>Run history</h3><div className="spacer" /><span className="sub">{runs.length} runs</span></div>
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr repeat(5, 1fr) 0.9fr", gap: 12, padding: "0 6px 12px", borderBottom: "1px solid var(--line)" }}>
          {["MODEL", "FILES", "COMMITS", "SCOPES", "DECISIONS", "TOKENS", "COST"].map((h) => <span key={h} className="mono dim" style={{ fontSize: 9.5, letterSpacing: ".14em" }}>{h}</span>)}
        </div>
        {runs.map((r, i) => (
          <div key={i} className="enter" style={{ display: "grid", gridTemplateColumns: "1.4fr repeat(5, 1fr) 0.9fr", gap: 12, padding: "14px 6px", borderBottom: i < runs.length - 1 ? "1px solid var(--line)" : "none", alignItems: "center", animationDelay: i * 0.05 + "s" }}>
            <div><div className="mono" style={{ fontSize: 12, color: "var(--text)" }}>{r.model}</div><div className="mono dim" style={{ fontSize: 10, marginTop: 3 }} title={new Date(r.timestamp).toLocaleString()}>{timeAgo(r.timestamp)}</div></div>
            <span className="mono tnum" style={{ fontSize: 13, color: "var(--text-2)" }}>{r.files_parsed.toLocaleString()}</span>
            <span className="mono tnum" style={{ fontSize: 13, color: "var(--text-2)" }}>{r.commits_read.toLocaleString()}</span>
            <span className="mono tnum" style={{ fontSize: 13, color: "var(--text-2)" }}>{r.scopes}</span>
            <span className="mono tnum" style={{ fontSize: 13, color: "var(--teal)" }}>{r.decisions_created}</span>
            <span className="mono tnum" style={{ fontSize: 13, color: "var(--text-2)" }}>{fmt(r.input_tokens + r.output_tokens)}</span>
            <span className="mono tnum" style={{ fontSize: 13, color: "var(--emerald)" }}>${r.estimated_cost.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function RunStat({ label, value, accent }) {
  return (
    <div style={{ paddingRight: 18 }}>
      <div className="mono dim" style={{ fontSize: 9.5, letterSpacing: ".18em", marginBottom: 12 }}>{label.toUpperCase()}</div>
      <div className="mono tnum" style={{ fontSize: 30, fontWeight: 600, color: accent ? "var(--teal)" : "#eafff8", lineHeight: 1 }}><CountUp value={value} /></div>
    </div>
  );
}

Object.assign(window, { OriginsView, IngestView });
