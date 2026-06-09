/* ============================================================
   Agent constellation — Metatron at the center, agents orbiting,
   knowledge flowing OUT (decisions) and feedback flowing BACK IN.
   Groups overflow agents past a threshold into a +N cluster.
   ============================================================ */
const { useState, useEffect, useRef, useMemo, useCallback } = React;

const AGENT_MAX_NODES = 8;          // beyond this, overflow collapses into a group
const AGENT_STATUS = {
  serving:  { c: "var(--emerald)", label: "receiving decisions" },
  feedback: { c: "var(--cyan)",    label: "sending feedback" },
  idle:     { c: "var(--muted)",   label: "idle" },
};
// Never crash on an unrecognised status: fall back to a neutral style so a new
// backend status value degrades gracefully instead of breaking the whole panel.
const statusStyle = (s) => AGENT_STATUS[s] || { c: "var(--muted)", label: s || "unknown" };
const initials = (name) => name.slice(0, 1).toUpperCase();

/* build the node list (agents + optional group) from activity data */
function buildNodes(agents) {
  if (agents.length <= AGENT_MAX_NODES) return agents.map((a) => ({ kind: "agent", key: a.id, agent: a, status: a.status }));
  const shown = agents.slice(0, AGENT_MAX_NODES - 1).map((a) => ({ kind: "agent", key: a.id, agent: a, status: a.status }));
  const rest = agents.slice(AGENT_MAX_NODES - 1);
  shown.push({
    kind: "group", key: "group", members: rest, status: "idle",
    received: rest.reduce((s, a) => s + a.decisions_received, 0),
    feedback: rest.reduce((s, a) => s + a.feedback_sent, 0),
  });
  return shown;
}

function AgentConstellation({ data, focusedIdx, onFocus, paused, height = 392 }) {
  const ref = useRef(null);
  const [dim, setDim] = useState({ w: 560, h: height });
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const ro = new ResizeObserver((e) => { const r = e[0].contentRect; setDim({ w: r.width, h: r.height }); });
    ro.observe(el); return () => ro.disconnect();
  }, []);

  const nodes = useMemo(() => buildNodes(data.agents), [data.agents]);
  const W = dim.w, H = dim.h, cx = W / 2, cy = H / 2;
  const rx = Math.max(120, Math.min(W * 0.38, W / 2 - 112));
  const ry = Math.max(92, Math.min(H * 0.34, H / 2 - 66));

  const placed = nodes.map((n, i) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / nodes.length;
    return { ...n, ang, x: cx + rx * Math.cos(ang), y: cy + ry * Math.sin(ang) };
  });

  // Refinement-to-serve highlight: when the focused node is the target of a trace
  // (its decision was refined from another engineer's feedback), light up the path.
  const traces = data.traces || [];
  const active = (typeof MetatronTrace !== "undefined")
    ? MetatronTrace.activeTraceForFocus(placed, traces, focusedIdx)
    : null;

  const conduit = (p, i) => {
    const mx = (cx + p.x) / 2, my = (cy + p.y) / 2;
    let dx = p.x - cx, dy = p.y - cy; const len = Math.hypot(dx, dy) || 1;
    const ox = -dy / len, oy = dx / len; const off = 18 * (i % 2 ? 1 : -1);
    return `M ${cx} ${cy} Q ${mx + ox * off} ${my + oy * off} ${p.x} ${p.y}`;
  };

  return (
    <div ref={ref} style={{ position: "relative", width: "100%", height }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <defs>
          <radialGradient id="agcCore" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="var(--emerald)" /><stop offset="100%" stopColor="var(--teal-deep)" /></radialGradient>
          <filter id="agcGlow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="2.2" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>

        {/* orbit guide */}
        <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill="none" stroke="rgba(120,200,180,.10)" strokeWidth="1" strokeDasharray="2 6" className="spin-slow" style={{ transformOrigin: `${cx}px ${cy}px` }} />

        {placed.map((p, i) => {
          const focused = i === focusedIdx;
          const sc = statusStyle(p.status).c;
          const d = conduit(p, i);
          const fb = p.kind === "agent" ? p.agent.feedback_sent : p.feedback;
          const pid = "agc" + i;
          return (
            <g key={p.key}>
              <path id={pid} d={d} fill="none" stroke={focused ? sc : "url(#agcCore)"} strokeOpacity={focused ? 0.55 : 0.18} strokeWidth={focused ? 1.6 : 1} />
              {/* outbound: decisions served (Metatron → agent) */}
              {!paused && (
                <circle r={focused ? 3.6 : 2.6} fill="var(--emerald)" filter="url(#agcGlow)" opacity="0.95">
                  <animateMotion dur={`${2.4 + (i % 4) * 0.35}s`} repeatCount="indefinite" path={d} begin={`${i * 0.3}s`} />
                </circle>
              )}
              {/* inbound: feedback (agent → Metatron) */}
              {!paused && fb > 0 && (
                <circle r="2.4" fill="var(--cyan)" filter="url(#agcGlow)" opacity="0.9">
                  <animateMotion dur={`${3 + (i % 3) * 0.5}s`} repeatCount="indefinite" path={d} keyPoints="1;0" keyTimes="0;1" calcMode="linear" begin={`${i * 0.45 + 1}s`} />
                </circle>
              )}
            </g>
          );
        })}

        {/* center pulse */}
        {!paused && <circle cx={cx} cy={cy} r="40" fill="none" stroke="var(--teal)" strokeWidth="1" opacity="0" style={{ transformOrigin: `${cx}px ${cy}px`, animation: "pulse-ring 3.4s ease-out infinite" }} />}

        {/* refinement-to-serve trace: A's feedback → refined decision → served to B */}
        {active && !paused && (() => {
          const B = placed[active.toIdx];
          const A = active.fromIdx >= 0 ? placed[active.fromIdx] : null;
          const dB = conduit(B, active.toIdx);
          const dA = A ? conduit(A, active.fromIdx) : null;
          return (
            <g className="enter">
              {dA && <path d={dA} fill="none" stroke="var(--cyan)" strokeOpacity="0.65" strokeWidth="2.2" />}
              <path d={dB} fill="none" stroke="var(--emerald)" strokeOpacity="0.85" strokeWidth="2.2" />
              {/* the originating feedback relays in along A's conduit … */}
              {dA && (
                <circle r="4.4" fill="var(--cyan)" filter="url(#agcGlow)">
                  <animateMotion dur="1.25s" repeatCount="indefinite" path={dA} keyPoints="1;0" keyTimes="0;1" calcMode="linear" />
                </circle>
              )}
              {/* … then the refined decision relays out along B's conduit */}
              <circle r="4.4" fill="var(--emerald)" filter="url(#agcGlow)">
                <animateMotion dur="1.25s" repeatCount="indefinite" path={dB} begin="1.25s" />
              </circle>
              {/* emphasised pulse at the refined node (the center) */}
              <circle cx={cx} cy={cy} r="30" fill="none" stroke="var(--emerald)" strokeWidth="1.5" opacity="0" style={{ transformOrigin: `${cx}px ${cy}px`, animation: "pulse-ring 2.5s ease-out infinite" }} />
            </g>
          );
        })()}
      </svg>

      {/* Metatron core */}
      <div style={{ position: "absolute", left: cx, top: cy, transform: "translate(-50%,-50%)", display: "flex", flexDirection: "column", alignItems: "center", gap: 6, pointerEvents: "none" }}>
        <div style={{ animation: "float-y 5s ease-in-out infinite" }}><MetatronEmblem size={66} /></div>
        <div className="mono" style={{ fontSize: 9.5, letterSpacing: ".22em", color: "var(--teal)" }}>METATRON</div>
      </div>

      {/* agent nodes */}
      {placed.map((p, i) => {
        const focused = i === focusedIdx;
        const sc = statusStyle(p.status).c;
        const right = p.x >= cx;
        return (
          <div key={p.key} onMouseEnter={() => onFocus(i)} onClick={() => onFocus(i)}
            style={{ position: "absolute", left: p.x, top: p.y, transform: "translate(-50%,-50%)", cursor: "pointer", zIndex: focused ? 6 : 4 }}>
            <div className="agc-node" style={{
              display: "flex", flexDirection: right ? "row" : "row-reverse", alignItems: "center", gap: 9,
              padding: "6px 9px", borderRadius: 12,
              border: "1px solid " + (focused ? sc : "var(--line-2)"),
              background: focused ? "rgba(8,24,21,.92)" : "rgba(7,18,16,.7)",
              boxShadow: focused ? `0 0 22px -6px ${sc}` : "none", transition: "all .25s", backdropFilter: "blur(6px)",
            }}>
              <div style={{ position: "relative", flex: "0 0 auto" }}>
                <div style={{ width: 30, height: 30, borderRadius: "50%", display: "grid", placeItems: "center",
                  border: "1.5px solid " + sc, color: sc, fontFamily: "var(--mono)", fontSize: p.kind === "group" ? 11 : 13, fontWeight: 600,
                  background: "rgba(4,10,9,.7)" }}>
                  {p.kind === "group" ? `+${p.members.length}` : initials(p.agent.name)}
                </div>
                {p.kind === "agent" && <span style={{ position: "absolute", right: -1, bottom: -1, width: 8, height: 8, borderRadius: "50%", background: sc, boxShadow: `0 0 6px ${sc}`, border: "1.5px solid #06100e", animation: p.status !== "idle" ? "glow-breathe 2.2s infinite" : "none" }} />}
              </div>
              <div style={{ textAlign: right ? "left" : "right", lineHeight: 1.15, paddingRight: right ? 2 : 0, paddingLeft: right ? 0 : 2 }}>
                <div style={{ fontSize: 12.5, fontWeight: 500, color: focused ? "#eafff8" : "var(--text)", whiteSpace: "nowrap" }}>
                  {p.kind === "group" ? "More agents" : p.agent.name}
                </div>
                <div className="mono" style={{ fontSize: 9, color: "var(--dim)", whiteSpace: "nowrap" }}>
                  {p.kind === "group" ? "grouped · low activity" : p.agent.id}
                </div>
              </div>
            </div>
          </div>
        );
      })}

      {/* trace caption — names the refinement-to-serve relationship being highlighted */}
      {active && (
        <div className="mono enter" title={active.trace.pattern}
          style={{ position: "absolute", left: "50%", bottom: 6, transform: "translateX(-50%)",
            display: "flex", alignItems: "center", gap: 8, padding: "6px 11px", borderRadius: 999,
            border: "1px solid rgba(52,211,153,.3)", background: "rgba(6,16,14,.86)", backdropFilter: "blur(6px)",
            whiteSpace: "nowrap", maxWidth: "94%", overflow: "hidden", textOverflow: "ellipsis", zIndex: 7 }}>
          <span className="badge canonical" style={{ flex: "0 0 auto" }}><span className="pip" />Refined</span>
          <span style={{ fontSize: 11, color: "var(--text-2)" }}>
            from <b style={{ color: "var(--cyan)" }}>{active.trace.from_name}</b>’s feedback · served to <b style={{ color: "var(--emerald)" }}>{active.trace.to_name}</b>
          </span>
        </div>
      )}
    </div>
  );
}

/* aggregate panel — shown when no single engineer is focused: team totals plus the
   live refinement-to-serve lineage across everyone. */
function AgentAggregatePanel({ data }) {
  const traces = data.traces || [];
  const tile = (label, value, color) => (
    <div style={{ padding: "11px 13px", borderRadius: 11, border: "1px solid var(--line)", background: "rgba(8,18,16,.4)" }}>
      <div className="mono" style={{ fontSize: 9, letterSpacing: ".12em", color, marginBottom: 6 }}>{label}</div>
      <div className="mono tnum" style={{ fontSize: 24, fontWeight: 600, color }}>{value}</div>
    </div>
  );
  return (
    <div className="enter" style={{ minWidth: 0 }}>
      <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 14 }}>TEAM ACTIVITY</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginBottom: 18 }}>
        {tile("ENGINEERS", data.total_agents, "#eafff8")}
        {tile("SERVED", data.total_served, "var(--emerald)")}
        {tile("FEEDBACK", data.total_feedback, "var(--cyan)")}
      </div>
      {traces.length > 0 ? (
        <>
          <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 9 }}>KNOWLEDGE REFINED &amp; RESHARED</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 196, overflowY: "auto", paddingRight: 4 }}>
            {traces.map((t, i) => (
              <div key={i} className="decision-flit" style={{ animationDelay: (0.05 + i * 0.06) + "s", padding: "9px 11px", borderRadius: 9, border: "1px solid var(--line)", background: "rgba(8,18,16,.4)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 5, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 12, color: "var(--cyan)" }}>{t.from_name}</span>
                  <span className="mono dim" style={{ fontSize: 12 }}>→</span>
                  <span style={{ fontSize: 12, color: "var(--emerald)" }}>{t.to_name}</span>
                  <span className="badge canonical" style={{ marginLeft: "auto" }}><span className="pip" />Refined</span>
                </div>
                <div style={{ fontSize: 11.5, lineHeight: 1.4, color: "var(--text-2)" }}>{t.pattern}</div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
          No feedback has been refined and reshared in this window yet.
        </div>
      )}
      <div className="mono dim" style={{ fontSize: 10.5, marginTop: 14, letterSpacing: ".04em" }}>Hover an engineer to see their decisions.</div>
    </div>
  );
}

/* right-hand detail for the focused node */
function AgentDetailPanel({ node, onDrill, onClearFocus }) {
  if (!node) return null;
  if (node.kind === "group") {
    return (
      <div className="enter" style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <span className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em" }}>GROUPED AGENTS</span>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
            {onClearFocus && (
              <button className="chip" onClick={onClearFocus} title="Back to the team view"
                style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Icon name="arrow" size={13} style={{ transform: "rotate(180deg)" }} /> All agents
              </button>
            )}
            <span className="badge ghost mono">+{node.members.length}</span>
          </div>
        </div>
        <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.5, marginBottom: 14 }}>
          {node.members.length} agents with lower activity in this window. Together they received <b style={{ color: "var(--emerald)" }}>{node.received}</b> decisions and sent <b style={{ color: "var(--cyan)" }}>{node.feedback}</b> feedback signals.
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 7, maxHeight: 220, overflowY: "auto", paddingRight: 4 }}>
          {node.members.map((a) => (
            <div key={a.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 9, border: "1px solid var(--line)", background: "rgba(8,18,16,.4)" }}>
              <div style={{ width: 24, height: 24, borderRadius: "50%", display: "grid", placeItems: "center", border: "1.5px solid " + statusStyle(a.status).c, color: statusStyle(a.status).c, fontFamily: "var(--mono)", fontSize: 11, fontWeight: 600 }}>{initials(a.name)}</div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12.5, color: "var(--text)" }}>{a.name}</div>
                <div className="mono" style={{ fontSize: 9.5, color: "var(--dim)" }}>{a.id}</div>
              </div>
              <div style={{ marginLeft: "auto", display: "flex", gap: 12 }}>
                <span className="mono" style={{ fontSize: 11, color: "var(--emerald)" }}>↓{a.decisions_received}</span>
                <span className="mono" style={{ fontSize: 11, color: "var(--cyan)" }}>↑{a.feedback_sent}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }
  const a = node.agent;
  const sc = statusStyle(a.status).c;
  return (
    <div key={a.id} className="enter" style={{ minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <div style={{ width: 42, height: 42, borderRadius: "50%", display: "grid", placeItems: "center", border: "2px solid " + sc, color: sc, fontFamily: "var(--mono)", fontSize: 17, fontWeight: 600, background: "rgba(4,10,9,.6)", boxShadow: `0 0 16px -4px ${sc}` }}>{initials(a.name)}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 16, color: "#eafff8", fontWeight: 500 }}>{a.name}</div>
          <div className="mono" style={{ fontSize: 10.5, color: "var(--dim)" }}>{a.id}</div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          {onClearFocus && (
            <button className="chip" onClick={onClearFocus} title="Back to the team view"
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <Icon name="arrow" size={13} style={{ transform: "rotate(180deg)" }} /> All agents
            </button>
          )}
          <span className="badge" style={{ color: sc, borderColor: sc, background: "transparent" }}><span className="pip" style={{ background: sc }} />{statusStyle(a.status).label}</span>
        </div>
      </div>

      <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 7 }}>NOW WORKING ON</div>
      <div className="mono" style={{ fontSize: 10.5, color: "var(--cyan)", marginBottom: 8, lineHeight: 1.5, wordBreak: "break-word" }}>{a.area}</div>
      <div style={{ fontSize: 14.5, lineHeight: 1.45, color: "var(--text)", marginBottom: 16, textWrap: "pretty" }}>{a.task}</div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
        <div onClick={() => onDrill && onDrill(a, "received")} title="View the decisions this agent received"
          className="drill-stat" style={{ padding: "11px 13px", borderRadius: 11, border: "1px solid rgba(52,211,153,.2)", background: "rgba(52,211,153,.05)", cursor: onDrill ? "pointer" : "default" }}>
          <div className="mono" style={{ fontSize: 9.5, letterSpacing: ".12em", color: "var(--emerald)", marginBottom: 6, display: "flex", alignItems: "center", gap: 5 }}><Icon name="down" size={13} />DECISIONS RECEIVED{onDrill && <span style={{ marginLeft: "auto", opacity: .6 }}><Icon name="chevron" size={12} /></span>}</div>
          <div className="mono tnum" style={{ fontSize: 24, fontWeight: 600, color: "var(--emerald)" }}>{a.decisions_received}</div>
        </div>
        <div onClick={() => onDrill && onDrill(a, "feedback")} title="View the feedback this agent sent"
          className="drill-stat" style={{ padding: "11px 13px", borderRadius: 11, border: "1px solid rgba(34,211,238,.2)", background: "rgba(34,211,238,.05)", cursor: onDrill ? "pointer" : "default" }}>
          <div className="mono" style={{ fontSize: 9.5, letterSpacing: ".12em", color: "var(--cyan)", marginBottom: 6, display: "flex", alignItems: "center", gap: 5 }}><Icon name="up" size={13} />FEEDBACK SENT{onDrill && <span style={{ marginLeft: "auto", opacity: .6 }}><Icon name="chevron" size={12} /></span>}</div>
          <div className="mono tnum" style={{ fontSize: 24, fontWeight: 600, color: "var(--cyan)" }}>{a.feedback_sent}</div>
        </div>
      </div>

      <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 9 }}>DECISIONS METATRON SERVED IT</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 7, maxHeight: 150, overflowY: "auto", paddingRight: 4 }}>
        {a.served.slice(0, 5).map((p, i) => (
          <div key={p.id} className="decision-flit" style={{ animationDelay: (0.08 + i * 0.07) + "s", display: "flex", gap: 9, alignItems: "flex-start", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--line)", background: "rgba(8,18,16,.4)" }}>
            <span style={{ color: "var(--teal)", marginTop: 1 }}><Icon name="spark" size={13} /></span>
            <span style={{ fontSize: 12, lineHeight: 1.4, color: "var(--text-2)" }}>{p.pattern}</span>
          </div>
        ))}
        {a.decisions_received > 5 && <div className="mono dim" style={{ fontSize: 11, paddingLeft: 10 }}>+ {a.decisions_received - 5} more delivered…</div>}
      </div>
      <div className="mono dim" style={{ fontSize: 10.5, letterSpacing: ".06em", marginTop: 14 }}>last active {timeAgo(a.last_active)}</div>
    </div>
  );
}

/* ---------- drill-down: an agent's received decisions + feedback sent ---------- */
function AgentDecisionRow({ d, onOpenDecision }) {
  return (
    <div onClick={() => onOpenDecision(d.id)} style={{ display: "flex", gap: 9, alignItems: "flex-start", padding: "10px 12px", borderRadius: 9, border: "1px solid var(--line)", background: "rgba(8,18,16,.4)", cursor: "pointer" }}>
      <span style={{ color: "var(--teal)", marginTop: 1 }}><Icon name="spark" size={13} /></span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12.5, lineHeight: 1.4, color: "var(--text-2)" }}>{d.pattern}</div>
        <div style={{ display: "flex", gap: 10, marginTop: 6, alignItems: "center", flexWrap: "wrap" }}>
          <ScopeTag scope={d.scope} />{d.status && <StatusBadge status={d.status} />}
        </div>
      </div>
    </div>
  );
}

function FeedbackDetailCard({ f, onOpenDecision }) {
  const ratings = Object.entries(f.ratings || {});
  return (
    <div className="panel pad" style={{ background: "rgba(8,18,16,.4)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 11, color: "var(--cyan)" }}>{f.area || "—"}</span>
        <div style={{ flex: 1 }} />
        <span className="mono dim" style={{ fontSize: 10.5 }} title={new Date(f.timestamp).toLocaleString()}>{timeAgo(f.timestamp)}</span>
        {f.handled ? <span className="badge canonical"><span className="pip" />Refined</span> : <span className="badge candidate"><span className="pip" />Open gap</span>}
      </div>
      {f.task && <div style={{ fontSize: 12.5, color: "var(--text-2)", marginBottom: 8 }}>{f.task}</div>}
      {f.missing && <div style={{ fontSize: 13, lineHeight: 1.55, color: "var(--text)", padding: "10px 12px", borderRadius: 9, border: "1px solid rgba(245,193,107,.18)", background: "rgba(245,193,107,.04)", marginBottom: ratings.length ? 10 : 0, textWrap: "pretty" }}>{f.missing}</div>}
      {ratings.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {ratings.map(([id, score]) => (
            <div key={id} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span className="mono" onClick={() => onOpenDecision(id)} title={"Open decision " + id}
                style={{ fontSize: 11, color: "var(--cyan)", width: 90, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", cursor: "pointer", textDecoration: "underline", textDecorationStyle: "dotted", textUnderlineOffset: 2 }}>{id}</span>
              <div style={{ flex: 1 }}><Meter value={score} max={10} color={score >= 6 ? "var(--emerald)" : score >= 4 ? "var(--amber)" : "var(--rose)"} height={6} /></div>
              <span className="mono tnum" style={{ fontSize: 12, width: 18, textAlign: "right", color: score >= 6 ? "var(--emerald)" : score >= 4 ? "var(--amber)" : "var(--rose)" }}>{score}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentActivityDrawer({ agent, focus, onOpenDecision, onClose }) {
  if (!agent) return null;
  const received = agent.received || [];
  const feedback = agent.feedback || [];
  const header = (title, count, color) => (
    <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 12 }}>
      <span style={{ color }}>{title}</span> <span style={{ color: "var(--dim)" }}>· {count}</span>
    </div>
  );
  const receivedBlock = (
    <div style={{ marginBottom: 26 }}>
      {header("DECISIONS RECEIVED", received.length, "var(--emerald)")}
      {received.length
        ? <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>{received.map((d) => <AgentDecisionRow key={d.id} d={d} onOpenDecision={onOpenDecision} />)}</div>
        : <div className="dim mono" style={{ fontSize: 12 }}>No decisions served in this window.</div>}
    </div>
  );
  const feedbackBlock = (
    <div style={{ marginBottom: 26 }}>
      {header("FEEDBACK SENT", feedback.length, "var(--cyan)")}
      {feedback.length
        ? <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>{feedback.map((f) => <FeedbackDetailCard key={f.id} f={f} onOpenDecision={onOpenDecision} />)}</div>
        : <div className="dim mono" style={{ fontSize: 12 }}>No feedback sent in this window.</div>}
    </div>
  );
  return (
    <SideDrawer eyebrow="AGENT ACTIVITY" title={agent.name} onClose={onClose}>
      {focus === "feedback" ? <>{feedbackBlock}{receivedBlock}</> : <>{receivedBlock}{feedbackBlock}</>}
    </SideDrawer>
  );
}

Object.assign(window, { AgentConstellation, AgentDetailPanel, AgentAggregatePanel, AgentActivityDrawer, buildNodes, AGENT_STATUS });
