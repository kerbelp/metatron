/* ============================================================
   KNOWLEDGE cluster — Overview · Decisions · Curation
   ============================================================ */

const { useState, useEffect, useRef, useMemo, useCallback } = React;

/* ============================================================
   OVERVIEW — health of the knowledge base
   ============================================================ */
function OverviewView({ repo, openDecision, goto }) {
  const stats = useApi(() => MetatronAPI.getStats(repo), [repo]);
  const usage = useApi(() => MetatronAPI.getUsage(repo), [repo]);
  const origins = useApi(() => MetatronAPI.getOrigins(repo), [repo]);

  if (stats.loading) return <Loading label="Surveying the knowledge base…" />;
  if (stats.error) return <ErrorState onRetry={stats.reload} />;
  const s = stats.data;
  const segs = [
    { value: s.canonical, color: "var(--teal)", label: "Canonical" },
    { value: s.candidate, color: "var(--amber)", label: "Candidate" },
    { value: s.rejected, color: "var(--rose)", label: "Rejected" },
  ];
  const cov = usage.data ? usage.data.coverage : 0;

  return (
    <div className="view">
      <SectionTitle eyebrow="Knowledge health" title="Knowledge base overview" />

      <div className="grid" style={{ gridTemplateColumns: "auto 1fr", alignItems: "stretch", marginBottom: 18 }}>
        {/* donut hero */}
        <div className="panel pad enter" style={{ display: "flex", alignItems: "center", gap: 30, position: "relative", overflow: "hidden", minWidth: 440 }}>
          <div style={{ position: "absolute", right: -60, top: -60, opacity: .5, pointerEvents: "none" }}><MetatronCube size={260} opacity={0.1} /></div>
          <Donut segments={segs} size={186} thickness={16}>
            <div style={{ textAlign: "center" }}>
              <div className="mono tnum" style={{ fontSize: 40, fontWeight: 600, color: "#eafff8", lineHeight: 1 }}><CountUp value={s.total} /></div>
              <div className="mono dim" style={{ fontSize: 9.5, letterSpacing: ".2em", marginTop: 5 }}>TOTAL DECISIONS</div>
            </div>
          </Donut>
          <div style={{ display: "flex", flexDirection: "column", gap: 16, position: "relative" }}>
            {segs.map((seg) => (
              <div key={seg.label} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span style={{ width: 10, height: 10, borderRadius: 3, background: seg.color, boxShadow: `0 0 8px ${seg.color}` }} />
                <div>
                  <div className="mono tnum" style={{ fontSize: 22, fontWeight: 600, color: seg.color, lineHeight: 1 }}><CountUp value={seg.value} /></div>
                  <div className="mono" style={{ fontSize: 10, letterSpacing: ".14em", color: "var(--muted)", marginTop: 3 }}>{seg.label.toUpperCase()}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* served-only callout + coverage + growth */}
        <div className="grid" style={{ gridTemplateRows: "auto 1fr", gap: 18 }}>
          <div className="panel pad enter enter-2" style={{ display: "flex", alignItems: "center", gap: 22 }}>
            <div style={{ flex: 1 }}>
              <div className="mono" style={{ fontSize: 10, letterSpacing: ".2em", color: "var(--teal)", marginBottom: 8 }}>SERVED TO AGENTS</div>
              <div style={{ fontSize: 14.5, lineHeight: 1.5, color: "var(--text-2)", maxWidth: 430 }}>Only the <b style={{ color: "var(--teal)" }}>{s.canonical} canonical</b> decisions reach agents. Nothing is served until a human approves it.</div>
            </div>
            <Donut segments={[{ value: cov, color: "var(--emerald)" }, { value: 1 - cov, color: "transparent" }]} size={104} thickness={10}>
              <div style={{ textAlign: "center" }}><div className="mono tnum" style={{ fontSize: 22, fontWeight: 600, color: "var(--emerald)" }}><CountUp value={cov * 100} decimals={0} suffix="%" /></div><div className="mono dim" style={{ fontSize: 8, letterSpacing: ".18em", marginTop: 2 }}>COVERAGE</div></div>
            </Donut>
          </div>
          <div className="panel pad enter enter-3" style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
            <div className="panel-head"><h3>Knowledge growth</h3><span className="sub">canonical decisions over time</span></div>
            <Spark data={[6, 9, 12, 18, 21, 27, 33, 38, 41, 44, s.canonical]} w={560} h={78} color="var(--teal)" strokeW={2.4} />
          </div>
        </div>
      </div>

      {/* candidates awaiting + origin mini */}
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 18 }}>
        <div className="panel pad enter enter-3" style={{ borderColor: s.candidate ? "rgba(245,193,107,.22)" : "var(--line)", cursor: "pointer" }} onClick={() => goto("curation")}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <div style={{ width: 54, height: 54, borderRadius: 14, display: "grid", placeItems: "center", background: "rgba(245,193,107,.1)", border: "1px solid rgba(245,193,107,.26)", color: "var(--amber)" }}><Icon name="gavel" size={24} /></div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 15, color: "#eafff8", marginBottom: 4 }}><b className="mono tnum" style={{ fontSize: 20, color: "var(--amber)" }}>{s.candidate}</b> candidates awaiting your review</div>
              <div className="muted" style={{ fontSize: 12.5 }}>Curate them into canonical knowledge →</div>
            </div>
            <span className="dim"><Icon name="arrow" size={18} /></span>
          </div>
        </div>
        <div className="panel pad enter enter-4" style={{ cursor: "pointer" }} onClick={() => goto("origins")}>
          <div className="panel-head"><h3>Where knowledge comes from</h3><div className="spacer" /><span className="dim"><Icon name="arrow" size={16} /></span></div>
          {origins.data ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {origins.data.origins.map((o) => (
                <div key={o.origin} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <OriginTag origin={o.origin} />
                  <div style={{ flex: 1 }}><Meter value={o.canonical} max={Math.max(...origins.data.origins.map((x) => x.canonical))} /></div>
                  <span className="mono tnum" style={{ fontSize: 12, color: "var(--text-2)", width: 26, textAlign: "right" }}>{o.canonical}</span>
                </div>
              ))}
            </div>
          ) : <div className="skeleton" style={{ height: 80 }} />}
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   DECISIONS — browse with search + filters
   ============================================================ */
const STATUS_OPTS = ["", "canonical", "candidate", "rejected"];
const ORIGIN_OPTS = ["", "bootstrap", "agent_submitted", "agent_feedback"];
const CONF_OPTS = ["", "high", "medium", "low"];

function DecisionsView({ repo, openDecision }) {
  const [f, setF] = useState({ status: "", origin: "", confidence: "", search: "", page: 1 });
  const [searchInput, setSearchInput] = useState("");
  useEffect(() => { const t = setTimeout(() => setF((s) => ({ ...s, search: searchInput, page: 1 })), 280); return () => clearTimeout(t); }, [searchInput]);
  useEffect(() => { setF({ status: "", origin: "", confidence: "", search: "", page: 1 }); setSearchInput(""); }, [repo]);

  const res = useApi(() => MetatronAPI.getDecisions(repo, { ...f, page_size: 7 }), [repo, f.status, f.origin, f.confidence, f.search, f.page]);
  const set = (k, v) => setF((s) => ({ ...s, [k]: s[k] === v ? "" : v, page: 1 }));
  const hasFilter = f.status || f.origin || f.confidence || f.search;

  return (
    <div className="view">
      <SectionTitle eyebrow="Knowledge base" title="Browse decisions"
        right={<div className="search"><Icon name="search" size={16} className="dim" /><input placeholder="search patterns, scopes, rationale…" value={searchInput} onChange={(e) => setSearchInput(e.target.value)} /></div>} />

      {/* filter rail */}
      <div className="panel pad enter" style={{ marginBottom: 16, display: "flex", flexWrap: "wrap", gap: 18, alignItems: "center" }}>
        <FilterGroup label="STATUS" opts={STATUS_OPTS} value={f.status} onPick={(v) => set("status", v)} render={(v) => v ? <StatusBadge status={v} /> : "all"} />
        <span style={{ width: 1, height: 24, background: "var(--line)" }} />
        <FilterGroup label="ORIGIN" opts={ORIGIN_OPTS} value={f.origin} onPick={(v) => set("origin", v)} render={(v) => v ? OriginLabel[v] : "all"} />
        <span style={{ width: 1, height: 24, background: "var(--line)" }} />
        <FilterGroup label="CONFIDENCE" opts={CONF_OPTS} value={f.confidence} onPick={(v) => set("confidence", v)} render={(v) => v || "all"} />
        {hasFilter && <button className="chip" style={{ marginLeft: "auto" }} onClick={() => { setF({ status: "", origin: "", confidence: "", search: "", page: 1 }); setSearchInput(""); }}>✕ clear</button>}
      </div>

      {res.loading ? <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 74 }} />)}</div>
        : res.error ? <ErrorState onRetry={res.reload} />
          : res.data.items.length === 0 ? <Empty title="No decisions match" detail="Try clearing a filter or broadening your search." icon="search" />
            : (
              <>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                  <span className="mono dim" style={{ fontSize: 11 }}>{res.data.total} decision{res.data.total === 1 ? "" : "s"}{hasFilter ? " matched" : ""}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {res.data.items.map((p) => <DecisionRow key={p.id} decision={p} onOpen={openDecision} />)}
                </div>
                {res.data.pages > 1 && (
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, marginTop: 24 }}>
                    <button className="icon-btn" disabled={f.page <= 1} onClick={() => setF((s) => ({ ...s, page: s.page - 1 }))} style={{ transform: "rotate(90deg)" }}><Icon name="chevron" size={16} /></button>
                    <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>{res.data.page} / {res.data.pages}</span>
                    <button className="icon-btn" disabled={f.page >= res.data.pages} onClick={() => setF((s) => ({ ...s, page: s.page + 1 }))} style={{ transform: "rotate(-90deg)" }}><Icon name="chevron" size={16} /></button>
                  </div>
                )}
              </>
            )}
    </div>
  );
}

function FilterGroup({ label, opts, value, onPick, render }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span className="mono dim" style={{ fontSize: 9.5, letterSpacing: ".18em" }}>{label}</span>
      <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
        {opts.map((o) => <button key={o} className={"chip " + (value === o ? "on" : "")} onClick={() => onPick(o)}>{render(o, value === o)}</button>)}
      </div>
    </div>
  );
}

/* ============================================================
   CURATION — candidate review queue. Approving feels great.
   ============================================================ */
function CurationView({ repo, openDecision, refresh }) {
  const res = useApi(() => MetatronAPI.getDecisions(repo, { status: "candidate", page_size: 50 }), [repo]);
  const toast = useToast();
  const [busy, setBusy] = useState(null);
  const [leaving, setLeaving] = useState({});
  const [burst, setBurst] = useState(null);
  const [approvingAll, setApprovingAll] = useState(false);

  const recommended = res.data ? res.data.items.filter((p) => p.triage === "approve") : [];

  const animateOut = (id) => new Promise((r) => { setLeaving((l) => ({ ...l, [id]: true })); setTimeout(r, 480); });

  const approve = async (p, e) => {
    setBusy(p.id);
    if (e) setBurst({ x: e.clientX, y: e.clientY, id: Math.random() });
    await MetatronAPI.approveDecision(p.id);
    await animateOut(p.id);
    toast("Canonized — now served to every agent");
    setBusy(null); res.reload(); refresh && refresh();
  };
  const reject = async (p) => {
    setBusy(p.id);
    await MetatronAPI.rejectDecision(p.id);
    await animateOut(p.id);
    toast("Candidate rejected");
    setBusy(null); res.reload(); refresh && refresh();
  };
  const approveAll = async () => {
    setApprovingAll(true);
    setBurst({ x: window.innerWidth / 2, y: 260, id: Math.random(), big: true });
    const ids = recommended.map((p) => p.id);
    await MetatronAPI.approveRecommended(repo);
    for (const id of ids) setLeaving((l) => ({ ...l, [id]: true }));
    await new Promise((r) => setTimeout(r, 560));
    toast(`${ids.length} recommended decisions canonized at once`);
    setApprovingAll(false); res.reload(); refresh && refresh();
  };

  return (
    <div className="view">
      {burst && <ApproveBurst key={burst.id} x={burst.x} y={burst.y} big={burst.big} onDone={() => setBurst(null)} />}
      <SectionTitle eyebrow="Human curation" title="Candidate review"
        right={recommended.length > 0 && <button className="btn primary lg" disabled={approvingAll} onClick={approveAll}>
          {approvingAll ? <><Spinner size={16} /> Canonizing…</> : <><Icon name="bolt" size={17} /> Approve all {recommended.length} recommended</>}
        </button>} />

      {/* judge summary banner */}
      <div className="panel pad enter" style={{ marginBottom: 18, display: "flex", alignItems: "center", gap: 18, background: "linear-gradient(100deg, rgba(45,212,191,.06), rgba(7,17,15,.5))" }}>
        <MetatronEmblem size={44} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, color: "#eafff8", marginBottom: 4 }}>The advisory judge has triaged this queue</div>
          <div className="muted" style={{ fontSize: 12.5 }}>Recommendations are guidance only — <b style={{ color: "var(--text-2)" }}>nothing becomes canonical without you</b>. Review each, or batch-approve the judge's picks.</div>
        </div>
        {res.data && <div style={{ display: "flex", gap: 18 }}>
          <TriageCount label="approve" n={res.data.items.filter((p) => p.triage === "approve").length} c="var(--teal)" />
          <TriageCount label="borderline" n={res.data.items.filter((p) => p.triage === "borderline").length} c="var(--amber)" />
          <TriageCount label="reject" n={res.data.items.filter((p) => p.triage === "reject").length} c="var(--rose)" />
        </div>}
      </div>

      {res.loading ? <Loading label="Loading the review queue…" />
        : res.error ? <ErrorState onRetry={res.reload} />
          : res.data.items.length === 0 ? <Empty title="Queue clear" detail="No candidates awaiting review. New ones arrive as knowledge is mined and gaps are refined." icon="check" />
            : <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {res.data.items.map((p, i) => <CandidateCard key={p.id} p={p} delay={i * 0.05} leaving={leaving[p.id]} busy={busy === p.id} onApprove={(e) => approve(p, e)} onReject={() => reject(p)} onOpen={() => openDecision(p)} />)}
            </div>}
    </div>
  );
}

function TriageCount({ label, n, c }) {
  return <div style={{ textAlign: "center" }}><div className="mono tnum" style={{ fontSize: 22, fontWeight: 600, color: c }}>{n}</div><div className="mono" style={{ fontSize: 9, letterSpacing: ".14em", color: "var(--muted)", textTransform: "uppercase" }}>{label}</div></div>;
}

function CandidateCard({ p, delay, leaving, busy, onApprove, onReject, onOpen }) {
  return (
    <div className="panel pad enter" style={{ animationDelay: delay + "s", transition: "all .48s cubic-bezier(.4,0,.2,1)", ...(leaving ? { opacity: 0, transform: "translateX(60px) scale(.97)", filter: "blur(2px)" } : {}) }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 18 }}>
        <div style={{ flex: 1, minWidth: 0, cursor: "pointer" }} onClick={onOpen}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 11, flexWrap: "wrap" }}>
            <TriageTag triage={p.triage} />
            <Confidence level={p.confidence} showLabel />
          </div>
          <div style={{ fontSize: 15.5, lineHeight: 1.45, color: "#eafff8", marginBottom: 10, textWrap: "pretty" }}>{p.pattern}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 12 }}>
            <ScopeTag scope={p.scope} /><OriginTag origin={p.origin} />
          </div>
          {p.triage !== "none" && (
            <div style={{ display: "flex", gap: 9, alignItems: "flex-start", padding: "10px 13px", borderRadius: 10, border: "1px solid var(--line)", background: "rgba(8,18,16,.4)", maxWidth: 640 }}>
              <span style={{ color: TriageMeta[p.triage].c, marginTop: 1 }}><Icon name="spark" size={13} /></span>
              <span className="muted" style={{ fontSize: 12.5, lineHeight: 1.5 }}>{p.triage_reason}</span>
            </div>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 9, width: 150, flex: "0 0 auto" }}>
          <button className="btn primary" disabled={busy} onClick={onApprove}><Icon name="check" size={15} />Approve</button>
          <button className="btn danger" disabled={busy} onClick={onReject}><Icon name="x" size={15} />Reject</button>
          <button className="btn" onClick={onOpen} style={{ fontSize: 12 }}>Inspect</button>
        </div>
      </div>
    </div>
  );
}

/* celebratory particle burst when a decision is canonized */
function ApproveBurst({ x, y, big, onDone }) {
  const parts = useMemo(() => Array.from({ length: big ? 36 : 18 }, (_, i) => {
    const a = (i / (big ? 36 : 18)) * Math.PI * 2 + Math.random(); const v = (big ? 120 : 70) + Math.random() * 60;
    return { dx: Math.cos(a) * v, dy: Math.sin(a) * v, s: 3 + Math.random() * 4, d: Math.random() * 0.1, c: ["var(--teal)", "var(--emerald)", "var(--cyan)"][i % 3] };
  }), []);
  useEffect(() => { const t = setTimeout(onDone, 1000); return () => clearTimeout(t); }, []);
  return (
    <div style={{ position: "fixed", left: x, top: y, zIndex: 300, pointerEvents: "none" }}>
      <style>{`@keyframes burst{to{transform:translate(var(--dx),var(--dy)) scale(0);opacity:0}}`}</style>
      {parts.map((p, i) => <span key={i} style={{ position: "absolute", width: p.s, height: p.s, borderRadius: "50%", background: p.c, boxShadow: `0 0 8px ${p.c}`, "--dx": p.dx + "px", "--dy": p.dy + "px", animation: `burst ${.8}s cubic-bezier(.2,.7,.3,1) ${p.d}s forwards` }} />)}
    </div>
  );
}

Object.assign(window, { OverviewView, DecisionsView, CurationView });
