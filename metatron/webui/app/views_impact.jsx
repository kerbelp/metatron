/* ============================================================
   IMPACT cluster — the emotional center.
   AgentImpact · Helpfulness · FeedbackLoop
   ============================================================ */

const { useState, useEffect, useRef, useMemo, useCallback } = React;

/* ---------- metric stat card with count-up + spark ---------- */
function StatCard({ label, value, decimals, suffix, prefix, series, color = "var(--teal)", delay = 0, sub }) {
  return (
    <div className="panel pad enter" style={{ animationDelay: delay + "s", overflow: "hidden", position: "relative" }}>
      <span className="corner tl" /><span className="corner br" />
      <div className="mono" style={{ fontSize: 10, letterSpacing: ".2em", color: "var(--muted)", textTransform: "uppercase", marginBottom: 14 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div className="mono tnum" style={{ fontSize: 38, fontWeight: 600, lineHeight: 1, color: "#eafff8" }}>
            <CountUp value={value} decimals={decimals || 0} prefix={prefix || ""} suffix={suffix || ""} />
          </div>
          {sub && <div className="muted" style={{ fontSize: 11.5, marginTop: 9 }}>{sub}</div>}
        </div>
        {series && <div style={{ opacity: .9 }}><Spark data={series} w={120} h={42} color={color} /></div>}
      </div>
    </div>
  );
}

/* ============================================================
   AGENT IMPACT — hero view
   ============================================================ */
function AgentImpactView({ repo, openPanel }) {
  const usage = useApi(() => MetatronAPI.getUsage(repo), [repo]);
  const fb = useApi(() => MetatronAPI.getFeedback(repo), [repo]);
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);

  // bidirectional agent constellation state. focusIdx === -1 means "no engineer
  // focused": the constellation highlights nothing and the side panel shows the
  // aggregate team view. Hovering an engineer focuses them.
  const [windowMins, setWindowMins] = useState(30);
  const [focusIdx, setFocusIdx] = useState(-1);
  // Poll every 4s so newly-recorded activity appears live without a manual reload;
  // the signature guard keeps the constellation stable between real changes.
  const act = usePolledApi(() => MetatronAPI.getAgentActivity(repo, windowMins), 4000,
    MetatronActivitySig.activitySignature, [repo, windowMins]);

  const queries = usage.data ? usage.data.recent_queries : [];
  useEffect(() => { setActive(0); }, [repo]);
  useEffect(() => {
    if (paused || !queries.length) return;
    const t = setInterval(() => setActive((a) => (a + 1) % queries.length), 4200);
    return () => clearInterval(t);
  }, [paused, queries.length]);
  useEffect(() => { setFocusIdx(-1); }, [repo, windowMins]);

  if (usage.loading) return <Loading label="Tracing agent activity…" />;
  if (usage.error) return <ErrorState onRetry={usage.reload} />;

  const u = usage.data;
  const helpfulRate = fb.data ? (() => { const t = fb.data.by_origin.reduce((a, o) => ({ h: a.h + o.helpful, n: a.n + o.noise }), { h: 0, n: 0 }); return (t.h + t.n) ? t.h / (t.h + t.n) : 0; })() : 0;
  const cur = queries[active] || queries[0];
  const WINDOW_LABEL = { 15: "15 min", 30: "30 min", 60: "1 hour" }[windowMins];
  const agNodes = act.data ? buildNodes(act.data.agents) : [];
  const fIdx = agNodes.length ? Math.min(focusIdx, agNodes.length - 1) : 0;

  return (
    <div className="view">
      <SectionTitle eyebrow="The main signal" title="Agent Impact"
        right={<div style={{ display: "flex", alignItems: "center", gap: 9, fontFamily: "var(--mono)", fontSize: 11, color: "var(--emerald)", letterSpacing: ".1em", whiteSpace: "nowrap" }}><span className="live-dot" />LIVE · {repo}</div>} />
      <style>{`.live-dot{width:8px;height:8px;border-radius:50%;background:var(--emerald);box-shadow:0 0 0 0 var(--emerald-glow);animation:livep 1.8s infinite}@keyframes livep{0%{box-shadow:0 0 0 0 rgba(52,211,153,.5)}70%{box-shadow:0 0 0 8px rgba(52,211,153,0)}100%{box-shadow:0 0 0 0 rgba(52,211,153,0)}}`}</style>

      {/* impact summary */}
      <div className="grid" style={{ gridTemplateColumns: "repeat(4,1fr)", marginBottom: 18 }}>
        <StatCard label="Queries answered" value={u.total_queries} series={[28, 36, 33, 48, 52, 60, 71, 83]} sub={`${u.avg_served} decisions served on average`} delay={0.02} />
        <StatCard label="Coverage" value={u.coverage * 100} decimals={1} suffix="%" color="var(--emerald)" series={[60, 66, 70, 74, 78, 80, 83, 84]} sub={`${u.misses.toLocaleString()} misses logged`} delay={0.08} />
        <StatCard label="Helpful rate" value={helpfulRate * 100} decimals={1} suffix="%" color="var(--cyan)" series={[70, 72, 75, 79, 80, 82, 84, 85]} sub="agents rate served decisions 1–10" delay={0.14} />
        <StatCard label="Decisions in flight" value={u.served_decisions} color="var(--violet)" series={[40, 52, 49, 63, 70, 81, 90, 99]} sub="cumulative decisions delivered" delay={0.2} />
      </div>

      {/* knowledge in flight — bidirectional agent constellation */}
      <div className="panel enter enter-2" style={{ padding: 0, overflow: "hidden", marginBottom: 18 }}>
        <div style={{ padding: "20px 24px 4px", display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 500, letterSpacing: ".03em" }}>Knowledge in flight</h3>
            <div className="mono" style={{ fontSize: 10, color: "var(--dim)", letterSpacing: ".14em", marginTop: 5, textTransform: "uppercase", whiteSpace: "nowrap" }}>Metatron ⇄ agents · last {WINDOW_LABEL}</div>
          </div>
          <div style={{ flex: 1 }} />
          <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
            <span className="mono" style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--emerald)", boxShadow: "0 0 6px var(--emerald)" }} /><span style={{ fontSize: 10, color: "var(--muted)" }}>decisions out</span></span>
            <span className="mono" style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--cyan)", boxShadow: "0 0 6px var(--cyan)" }} /><span style={{ fontSize: 10, color: "var(--muted)" }}>feedback in</span></span>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {[[15, "15 MIN"], [30, "30 MIN"], [60, "1 HR"]].map(([v, l]) => <button key={v} className={"chip " + (windowMins === v ? "on" : "")} onClick={() => setWindowMins(v)}>{l}</button>)}
          </div>
        </div>

        {act.loading ? <div style={{ height: 392 }}><Loading label="Locating active agents…" /></div>
          : act.error ? <div style={{ height: 392 }}><ErrorState onRetry={act.reload} /></div>
            : act.data.agents.length === 0 ? (
                <div style={{ height: 392, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 18, overflow: "hidden" }}>
                  <div style={{ animation: "float-y 6s ease-in-out infinite", flex: "0 0 auto" }}><MetatronCube size={140} opacity={1} hero /></div>
                  <div style={{ textAlign: "center", padding: "0 24px", maxWidth: 460 }}>
                    <div className="mono" style={{ fontSize: 11.5, letterSpacing: ".22em", color: "var(--teal)" }}>AWAITING AGENTS</div>
                    <div className="muted" style={{ fontSize: 12.5, marginTop: 7, lineHeight: 1.5 }}>No agents connected in the last {WINDOW_LABEL} — activity streams in here as agents query Metatron.</div>
                  </div>
                </div>
              )
              : (
                <div style={{ display: "grid", gridTemplateColumns: "1.35fr 1fr" }}>
                  <div onMouseLeave={() => setFocusIdx(-1)} style={{ position: "relative", borderRight: "1px solid var(--line)", background: "radial-gradient(440px 320px at 50% 50%, rgba(45,212,191,.06), transparent 70%)" }}>
                    <div style={{ position: "absolute", top: 14, left: 18, display: "flex", gap: 9, zIndex: 8, flexWrap: "wrap" }}>
                      <span className="badge ghost mono"><b style={{ color: "var(--text)" }}>{act.data.total_agents}</b>&nbsp;agents</span>
                      <span className="badge mono" style={{ color: "var(--emerald)", borderColor: "rgba(52,211,153,.28)", background: "rgba(52,211,153,.08)" }}>↓ {act.data.total_served} served</span>
                      <span className="badge mono" style={{ color: "var(--cyan)", borderColor: "rgba(34,211,238,.28)", background: "rgba(34,211,238,.08)" }}>↑ {act.data.total_feedback} feedback</span>
                    </div>
                    <AgentConstellation data={act.data} focusedIdx={fIdx} onFocus={(i) => setFocusIdx(i)} paused={false} height={392} />
                  </div>
                  <div style={{ padding: "20px 24px", minWidth: 0 }}>
                    {agNodes[fIdx]
                      ? <AgentDetailPanel node={agNodes[fIdx]} onDrill={(a, focus) => openPanel && openPanel({ type: "agent", agent: a, focus })} />
                      : <AgentAggregatePanel data={act.data} />}
                  </div>
                </div>
              )}
        <style>{`.decision-flit{animation:fadeup .5s both}`}</style>
      </div>

      {/* activity stream */}
      <div className="panel pad enter enter-3">
        <div className="panel-head"><h3>Activity stream</h3><span className="sub">agent queries</span><div className="spacer" /><span className="mono dim" style={{ fontSize: 11 }}>auto-cycling · hover to pause</span></div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {queries.map((q, i) => (
            <div key={i} onMouseEnter={() => { setPaused(true); setActive(i); }} onMouseLeave={() => setPaused(false)}
              onClick={() => openPanel && openPanel({ type: "query", query: q })} title="View this query's decisions"
              style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 16, alignItems: "center", padding: "13px 16px", borderRadius: 10, cursor: "pointer",
                border: "1px solid " + (i === active ? "rgba(45,212,191,.35)" : "var(--line)"), background: i === active ? "rgba(45,212,191,.07)" : "rgba(8,18,16,.3)", transition: "all .25s" }}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3, width: 44 }}>
                <span className="mono tnum" style={{ fontSize: 19, fontWeight: 600, color: i === active ? "var(--emerald)" : "var(--teal)" }}>{q.result_count}</span>
                <span className="mono dim" style={{ fontSize: 8.5, letterSpacing: ".1em" }}>DECISIONS</span>
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13.5, color: "var(--text)", marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{q.task}</div>
                <div className="mono" style={{ fontSize: 10.5, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{q.area}</div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                {q.agent && <span className="mono" style={{ display: "flex", alignItems: "center", gap: 7, padding: "4px 9px 4px 5px", borderRadius: 20, border: "1px solid var(--line-2)", background: "rgba(8,20,17,.5)" }}>
                  <span style={{ width: 18, height: 18, borderRadius: "50%", display: "grid", placeItems: "center", border: "1px solid var(--teal)", color: "var(--teal)", fontSize: 9.5, fontWeight: 600 }}>{q.agent.name.slice(0, 1)}</span>
                  <span style={{ fontSize: 11, color: "var(--text-2)" }}>{q.agent.name}</span>
                </span>}
                <span className="mono dim" style={{ fontSize: 10.5 }}>{timeAgo(q.timestamp)}</span>
                {i === active && <span style={{ color: "var(--emerald)" }}><Icon name="bolt" size={15} /></span>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   HELPFULNESS — leaderboard + misleading queue
   ============================================================ */
function RatedRow({ r, rank, onOpen }) {
  return (
    <div className="enter" onClick={onOpen} style={{ display: "grid", gridTemplateColumns: "auto auto 1fr auto", gap: 15, alignItems: "center", padding: "13px 14px", borderRadius: 11, border: "1px solid var(--line)", background: "rgba(8,18,16,.34)", cursor: "pointer", transition: "all .2s" }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--line-2)"; e.currentTarget.style.background = "rgba(11,24,21,.5)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.background = "rgba(8,18,16,.34)"; }}>
      <span className="mono" style={{ fontSize: 12, color: "var(--dim)", width: 18, textAlign: "right" }}>{rank}</span>
      <ScoreRing score={r.score} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, lineHeight: 1.4, color: "var(--text)", marginBottom: 5, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{r.pattern}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}><ScopeTag scope={r.scope} /><span className="mono dim" style={{ fontSize: 10.5 }}>{r.n_ratings} ratings</span></div>
      </div>
      <EffectTag effect={r.effect} />
    </div>
  );
}

function HelpfulnessView({ repo, openDecision }) {
  const lb = useApi(() => MetatronAPI.getLeaderboard(repo), [repo]);
  if (lb.loading) return <Loading label="Tallying agent ratings…" />;
  if (lb.error) return <ErrorState onRetry={lb.reload} />;
  const d = lb.data;
  const resolve = (id) => MetatronAPI.getDecisions(repo, { page_size: 100 }).then((r) => r.items.find((p) => p.id === id)).then((p) => p && openDecision(p));
  return (
    <div className="view">
      <SectionTitle eyebrow="Live helpfulness signal" title="What's actually helping agents"
        right={<div style={{ display: "flex", gap: 22 }}>
          <div className="metric" style={{ textAlign: "right" }}><div className="big" style={{ fontSize: 24, color: "var(--emerald)" }}><CountUp value={d.rated_total} /></div><div className="lab">ratings collected</div></div>
          <div className="metric" style={{ textAlign: "right" }}><div className="big" style={{ fontSize: 24, color: "var(--teal)" }}><CountUp value={d.neutral} decimals={1} /></div><div className="lab">neutral baseline</div></div>
        </div>} />
      <div className="grid" style={{ gridTemplateColumns: "1.4fr 1fr", alignItems: "start" }}>
        <div className="panel pad enter">
          <div className="panel-head"><span style={{ color: "var(--emerald)" }}><Icon name="star" size={16} /></span><h3>Most-helpful canonical decisions</h3><div className="spacer" /><span className="sub">score · rising/sinking</span></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {d.most_helpful.map((r, i) => <RatedRow key={r.id} r={r} rank={i + 1} onOpen={() => resolve(r.id)} />)}
          </div>
        </div>
        <div className="panel pad enter enter-2" style={{ borderColor: "rgba(251,113,133,.16)" }}>
          <div className="panel-head"><span style={{ color: "var(--rose)" }}><Icon name="target" size={16} /></span><h3>Misleading queue</h3><div className="spacer" /><span className="nav-badge" style={{ background: "rgba(251,113,133,.14)", color: "var(--rose)", borderColor: "rgba(251,113,133,.22)" }}>{d.review_count} to review</span></div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 14, lineHeight: 1.5 }}>Low-scoring decisions agents flagged as noise. Pull these from canonical or refine them.</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {d.misleading.length ? d.misleading.map((r, i) => <RatedRow key={r.id} r={r} rank={i + 1} onOpen={() => resolve(r.id)} />) : <Empty title="No misleading decisions" detail="Every served decision is scoring above the neutral baseline." />}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   FEEDBACK LOOP — gaps ("what was missing") → refine to candidate
   ============================================================ */
function LoopStage({ icon, label, n, color, active }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, flex: 1 }}>
      <div style={{ width: 52, height: 52, borderRadius: 14, display: "grid", placeItems: "center", border: "1px solid " + (active ? color : "var(--line-2)"), background: active ? color.replace(")", ",.12)").replace("var(--", "rgba(").replace("rgb", "rgb") : "rgba(8,18,16,.5)", color: active ? color : "var(--muted)", boxShadow: active ? `0 0 18px -4px ${color}` : "none", transition: "all .4s" }}>
        <Icon name={icon} size={22} />
      </div>
      <div className="mono" style={{ fontSize: 9.5, letterSpacing: ".12em", color: active ? "var(--text-2)" : "var(--dim)", textTransform: "uppercase", textAlign: "center" }}>{label}</div>
      {n != null && <div className="mono tnum" style={{ fontSize: 13, color }}>{n}</div>}
    </div>
  );
}

function FeedbackLoopView({ repo, refresh, openDecision }) {
  const [filter, setFilter] = useState("all");
  const ev = useApi(() => MetatronAPI.getFeedbackEvents(repo, filter), [repo, filter]);
  const toast = useToast();
  const [refining, setRefining] = useState(null);
  const openById = useCallback((id) => {
    MetatronAPI.getDecision(id).then((d) => d && d.id && openDecision && openDecision(d));
  }, [openDecision]);

  const doRefine = async (e) => {
    setRefining(e.id);
    await MetatronAPI.refineFeedback(e.id);
    setRefining(null);
    toast("Gap refined into a new candidate decision", { icon: "loop" });
    ev.reload(); refresh && refresh();
  };

  return (
    <div className="view">
      <SectionTitle eyebrow="The self-improving loop" title="Gaps become knowledge" />

      {/* loop diagram */}
      <div className="panel pad enter" style={{ marginBottom: 18, position: "relative", overflow: "hidden" }}>
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", opacity: .5, pointerEvents: "none" }}><MetatronCube size={300} opacity={0.12} /></div>
        <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 6, maxWidth: 760, margin: "6px auto" }}>
          <LoopStage icon="source" label="Mine knowledge" color="var(--teal)" active />
          <LoopArrow />
          <LoopStage icon="gavel" label="Human curates" color="var(--emerald)" active />
          <LoopArrow />
          <LoopStage icon="impact" label="Agents query" color="var(--cyan)" active />
          <LoopArrow />
          <LoopStage icon="pulse" label="Agents rate + report gaps" color="var(--amber)" active />
          <LoopArrow />
          <LoopStage icon="loop" label="Refine → candidate" color="var(--violet)" active />
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 500 }}>“What was missing” reports</h3>
        <div style={{ flex: 1 }} />
        {["all", "unhandled", "handled"].map((f) => <button key={f} className={"chip " + (filter === f ? "on" : "")} onClick={() => setFilter(f)}>{f}</button>)}
      </div>

      {ev.loading ? <Loading label="Gathering feedback gaps…" /> : ev.error ? <ErrorState onRetry={ev.reload} /> :
        ev.data.events.length === 0 ? <Empty title="No gaps in this view" detail="Every reported gap has been refined into a candidate decision." icon="loop" /> :
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {ev.data.events.map((e, i) => <GapCard key={e.id} e={e} delay={i * 0.06} onRefine={() => doRefine(e)} refining={refining === e.id} onOpenDecision={openById} />)}
          </div>}
    </div>
  );
}

function LoopArrow() {
  return <div style={{ flex: "0 0 auto", color: "var(--dim)", display: "grid", placeItems: "center", paddingBottom: 28 }}>
    <svg width="34" height="12" viewBox="0 0 34 12"><line x1="0" y1="6" x2="28" y2="6" stroke="var(--line-strong)" strokeWidth="1" strokeDasharray="3 3" className="flow-line" /><path d="M26 2l6 4-6 4" fill="none" stroke="var(--teal)" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
  </div>;
}

function GapCard({ e, delay, onRefine, refining, onOpenDecision }) {
  const ratings = Object.entries(e.ratings || {});
  return (
    <div className="panel pad enter" style={{ animationDelay: delay + "s" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 11, color: "var(--cyan)" }}>{e.area}</span>
        <span className="dim">·</span>
        <span style={{ fontSize: 13, color: "var(--text-2)" }}>{e.task}</span>
        <div style={{ flex: 1 }} />
        <span className="mono dim" style={{ fontSize: 10.5 }}>{timeAgo(e.timestamp)}</span>
        {e.handled
          ? <span className="badge canonical"><span className="pip" />Refined</span>
          : <span className="badge candidate"><span className="pip" />Open gap</span>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 22 }}>
        <div>
          <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 9 }}>WHAT THE AGENT SAID WAS MISSING</div>
          <div style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--text)", padding: "13px 15px", borderRadius: 11, border: "1px solid rgba(245,193,107,.18)", background: "rgba(245,193,107,.04)", textWrap: "pretty" }}>{e.missing}</div>
        </div>
        <div>
          <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 9 }}>RATINGS THIS RUN · 1–10</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            {ratings.map(([id, score]) => (
              <div key={id} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className="mono link-id" title={"Open decision " + id} onClick={() => onOpenDecision && onOpenDecision(id)}
                  style={{ fontSize: 11, color: "var(--cyan)", width: 96, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", cursor: "pointer", textDecoration: "underline", textDecorationStyle: "dotted", textUnderlineOffset: 2 }}>{id}</span>
                <div style={{ flex: 1 }}><Meter value={score} max={10} color={score >= 6 ? "var(--emerald)" : score >= 4 ? "var(--amber)" : "var(--rose)"} height={6} /></div>
                <span className="mono tnum" style={{ fontSize: 12, width: 18, textAlign: "right", color: score >= 6 ? "var(--emerald)" : score >= 4 ? "var(--amber)" : "var(--rose)" }}>{score}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
        <span className="mono dim" style={{ fontSize: 11 }}>{e.handled ? "A candidate decision was distilled from this gap." : "Distill this gap into a new candidate decision for human review."}</span>
        <div style={{ flex: 1 }} />
        <button className="btn primary" disabled={e.handled || refining} onClick={onRefine}>
          {refining ? <><Spinner size={15} /> Refining…</> : e.handled ? <><Icon name="check" size={15} /> Refined</> : <><Icon name="loop" size={15} /> Refine into candidate</>}
        </button>
      </div>
    </div>
  );
}

/* ---------- drill-down: a single agent query and the decisions it returned ---------- */
function QueryDrawer({ query, onOpenDecision, onClose }) {
  if (!query) return null;
  const decisions = query.decisions || [];
  const miss = query.result_count === 0;
  return (
    <SideDrawer eyebrow="AGENT QUERY" title={query.task || query.area || "Query"} onClose={onClose}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        {(query.actor_name || query.actor_email) && <span className="mono" style={{ fontSize: 11, color: "var(--text-2)" }}>{query.actor_name || query.actor_email}</span>}
        <span className="mono dim" style={{ fontSize: 10.5 }} title={new Date(query.timestamp).toLocaleString()}>{timeAgo(query.timestamp)}</span>
      </div>
      <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 7 }}>AREA</div>
      <div className="mono" style={{ fontSize: 11.5, color: "var(--cyan)", marginBottom: 16, lineHeight: 1.5, wordBreak: "break-word" }}>{query.area || "—"}</div>
      {query.task && <>
        <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 7 }}>TASK</div>
        <div style={{ fontSize: 14, lineHeight: 1.5, color: "var(--text)", marginBottom: 18, textWrap: "pretty" }}>{query.task}</div>
      </>}
      <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 12 }}>
        <span style={{ color: miss ? "var(--rose)" : "var(--emerald)" }}>DECISIONS RETURNED</span> <span style={{ color: "var(--dim)" }}>· {query.result_count}</span>
      </div>
      {decisions.length
        ? <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>{decisions.map((d) => <AgentDecisionRow key={d.id} d={d} onOpenDecision={onOpenDecision} />)}</div>
        : <div className="dim mono" style={{ fontSize: 12 }}>{miss ? "No decisions matched — logged as a coverage miss." : "No decisions recorded for this query."}</div>}
    </SideDrawer>
  );
}

Object.assign(window, { AgentImpactView, HelpfulnessView, FeedbackLoopView, StatCard, QueryDrawer });
