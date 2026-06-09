/* ============================================================
   Shared UI primitives — badges, decision rows, detail drawer.
   ============================================================ */

const { useState, useEffect, useRef, useMemo, useCallback } = React;

// Plain-language gloss for each status — surfaced as a tooltip on every badge and
// inline in the decision drawer, so "canonical" reads as what it actually means.
const STATUS_DESC = {
  canonical: "Approved by a human — served to coding agents",
  candidate: "Proposed — awaiting human review, not yet served",
  rejected: "Declined — not served to agents",
};

function StatusBadge({ status }) {
  const label = { canonical: "Canonical", candidate: "Candidate", rejected: "Rejected" }[status] || status;
  return <span className={"badge " + status} title={STATUS_DESC[status] || ""}><span className="pip" />{label}</span>;
}

function Confidence({ level, showLabel = false }) {
  return (
    <span className="conf-wrap" style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
      <span className={"conf " + level}><i /><i /><i /></span>
      {showLabel && <span className="mono dim" style={{ fontSize: 10.5, letterSpacing: ".1em", textTransform: "uppercase" }}>{level}</span>}
    </span>
  );
}

function ScopeTag({ scope }) {
  return <span className="scope-tag">{scope ? scope : "◇ global"}</span>;
}

const ORIGIN_LABEL = { bootstrap: "Bootstrap", agent_submitted: "Agent-submitted", agent_feedback: "Agent-feedback", human: "Human-authored" };
const ORIGIN_DESC = {
  bootstrap: "Mined from the codebase + git history",
  agent_submitted: "Proposed directly by a coding agent",
  agent_feedback: "Distilled from an agent's \u2018what was missing\u2019 report",
  human: "Authored directly by a human curator",
};
function OriginTag({ origin }) {
  const dot = { bootstrap: "var(--teal)", agent_submitted: "var(--violet)", agent_feedback: "var(--cyan)", human: "var(--emerald)" }[origin];
  return <span className="origin-tag" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><span style={{ width: 6, height: 6, borderRadius: 2, background: dot, transform: "rotate(45deg)" }} />{ORIGIN_LABEL[origin] || origin}</span>;
}

const TRIAGE_META = {
  approve: { c: "var(--teal)", bg: "rgba(45,212,191,.12)", bd: "rgba(45,212,191,.3)", label: "Judge: Approve", ic: "check" },
  reject: { c: "var(--rose)", bg: "rgba(251,113,133,.1)", bd: "rgba(251,113,133,.26)", label: "Judge: Reject", ic: "x" },
  borderline: { c: "var(--amber)", bg: "rgba(245,193,107,.1)", bd: "rgba(245,193,107,.26)", label: "Judge: Borderline", ic: "target" },
  none: { c: "var(--muted)", bg: "transparent", bd: "var(--line-2)", label: "No recommendation", ic: "flat" },
};
function TriageTag({ triage }) {
  const m = TRIAGE_META[triage] || TRIAGE_META.none;
  return <span className="badge" style={{ color: m.c, background: m.bg, borderColor: m.bd }}><Icon name={m.ic} size={11} />{m.label}</span>;
}

function EffectTag({ effect, score }) {
  const m = { up: ["var(--emerald)", "up", "rising"], down: ["var(--rose)", "down", "sinking"], flat: ["var(--muted)", "flat", "steady"] }[effect];
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: m[0], fontFamily: "var(--mono)", fontSize: 11 }}><Icon name={m[1]} size={13} />{m[2]}</span>;
}

function ScoreRing({ score, size = 46 }) {
  const r = (size - 6) / 2, c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, score / 10));
  const col = score >= 7 ? "var(--emerald)" : score >= 5 ? "var(--teal)" : score >= 3.5 ? "var(--amber)" : "var(--rose)";
  const [d, setD] = useState(0);
  useEffect(() => { const t = setTimeout(() => setD(pct), 100); return () => clearTimeout(t); }, [pct]);
  return (
    <div style={{ position: "relative", width: size, height: size, flex: "0 0 auto" }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(120,200,180,.1)" strokeWidth="3" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={col} strokeWidth="3" strokeLinecap="round"
          strokeDasharray={`${c * d} ${c}`} style={{ transition: "stroke-dasharray 1s cubic-bezier(.3,.8,.3,1)", filter: `drop-shadow(0 0 4px ${col})` }} />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
        <span className="mono tnum" style={{ fontSize: size * 0.3, fontWeight: 600, color: col }}>{score.toFixed(1)}</span>
      </div>
    </div>
  );
}

/* ---------- decision row (browse / curation) ---------- */
function DecisionRow({ decision, onOpen, style, children, columns = "1fr auto" }) {
  return (
    <div className="row enter" style={{ gridTemplateColumns: columns, cursor: onOpen ? "pointer" : "default", ...style }} onClick={onOpen ? () => onOpen(decision) : undefined}>
      <div style={{ minWidth: 0 }}>
        <div className="pattern" style={{ marginBottom: 9 }}>{decision.pattern}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <ScopeTag scope={decision.scope} />
          <OriginTag origin={decision.origin} />
          <Confidence level={decision.confidence} showLabel />
        </div>
      </div>
      {children || (
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
            <StatusBadge status={decision.status} />
            {decision.created_at && (
              <span className="mono dim" style={{ fontSize: 10 }}
                title={new Date(decision.created_at).toLocaleString()}>{timeAgo(decision.created_at)}</span>
            )}
          </div>
          <span className="dim"><Icon name="arrow" size={16} /></span>
        </div>
      )}
    </div>
  );
}

/* ---------- shared decision editor (add + edit) ---------- */
const INPUT_STYLE = {
  width: "100%",
  background: "rgba(8,18,16,.7)",
  border: "1px solid var(--line)",
  borderRadius: 8,
  padding: "9px 12px",
  color: "#eafff8",
  fontFamily: "var(--mono)",
  fontSize: 13,
  resize: "vertical",
  boxSizing: "border-box",
  outline: "none",
};
function DecisionEditor({ repo, decision, onSaved, onCancel }) {
  const editing = !!decision;
  const [form, setForm] = useState({
    pattern: decision ? decision.pattern : "",
    scope: decision ? decision.scope : "",
    rationale: decision ? decision.rationale : "",
    confidence: decision ? (decision.confidence || "medium") : "medium",
  });
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const valid = MetatronDecisionEditor.validateDecisionForm(form).ok;
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async () => {
    if (!valid) return;
    setBusy(true);
    const r = editing
      ? await MetatronAPI.updateDecision(decision.id, form)
      : await MetatronAPI.createDecision(repo, form);
    setBusy(false);
    if (r && !r.ok) { toast(r.error || "Could not save the decision"); return; }
    onSaved && onSaved();
  };
  return (
    <div className="panel pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 2 }}>{editing ? "EDIT DECISION" : "NEW DECISION"}</div>
      <label className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em" }}>PATTERN</label>
      <textarea value={form.pattern} onChange={set("pattern")} rows={2} style={INPUT_STYLE} />
      <label className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em" }}>SCOPE</label>
      <input value={form.scope} onChange={set("scope")} style={INPUT_STYLE} />
      <label className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em" }}>RATIONALE</label>
      <textarea value={form.rationale} onChange={set("rationale")} rows={3} style={INPUT_STYLE} />
      <label className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em" }}>CONFIDENCE</label>
      <select value={form.confidence} onChange={set("confidence")} style={{ ...INPUT_STYLE, resize: "none" }}>
        <option value="low">low</option>
        <option value="medium">medium</option>
        <option value="high">high</option>
      </select>
      <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 4 }}>
        <button className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button className="btn primary" onClick={save} disabled={!valid || busy}>
          {busy ? <><Spinner size={14} /> Saving…</> : (editing ? "Save changes" : "Add decision")}
        </button>
      </div>
    </div>
  );
}

/* ---------- decision detail drawer ---------- */
function DecisionDrawer({ decision, onClose, onApprove, onReject, busy, onEdited }) {
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  if (!decision) return null;
  // Opaque sticky footer so action buttons don't overlap content scrolling behind.
  const footer = {
    position: "sticky", bottom: 0, marginLeft: -28, marginRight: -28, marginTop: 10,
    padding: "18px 28px",
    background: "linear-gradient(180deg, rgba(6,15,13,0), #070f0d 26%)",
    borderTop: "1px solid var(--line)",
  };
  const canEdit = onEdited && decision.status !== "rejected";
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 120, display: "flex", justifyContent: "flex-end" }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "rgba(2,6,8,.6)", backdropFilter: "blur(3px)", animation: "fadeup .3s" }} />
      <aside style={{ position: "relative", width: "min(560px, 92vw)", height: "100%", background: "linear-gradient(180deg,#081512,#060f0d)", borderLeft: "1px solid var(--line-2)", boxShadow: "var(--shadow-deep)", overflowY: "auto", animation: "slidein .36s cubic-bezier(.2,.8,.3,1)" }}>
        <style>{`@keyframes slidein{from{transform:translateX(40px);opacity:.4}}`}</style>
        <div style={{ position: "sticky", top: 0, zIndex: 2, padding: "20px 26px", background: "linear-gradient(180deg,#081512,rgba(8,21,18,.7))", backdropFilter: "blur(8px)", borderBottom: "1px solid var(--line)", display: "flex", alignItems: "center", gap: 12 }}>
          <StatusBadge status={decision.status} />
          {decision.triage && decision.triage !== "none" && decision.status === "candidate" && <TriageTag triage={decision.triage} />}
          <div className="spacer" style={{ flex: 1 }} />
          {canEdit && !editing && (
            <button className="icon-btn" title="Edit decision" onClick={() => setEditing(true)}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
            </button>
          )}
          <button className="icon-btn" onClick={onClose}><Icon name="x" size={16} /></button>
        </div>
        <div className="muted" style={{ fontSize: 11.5, padding: "11px 28px 0", lineHeight: 1.5 }}>{STATUS_DESC[decision.status]}</div>
        {editing ? (
          <div style={{ padding: "20px 28px 40px" }}>
            <DecisionEditor decision={decision} onSaved={() => { setEditing(false); onEdited && onEdited(); }} onCancel={() => setEditing(false)} />
          </div>
        ) : (
        <div style={{ padding: "20px 28px 40px" }}>
          <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".24em", marginBottom: 10 }}>THE RULE</div>
          <div style={{ fontSize: 20, lineHeight: 1.4, fontWeight: 400, color: "#eafff8", textWrap: "pretty" }}>{decision.pattern}</div>

          <div style={{ display: "flex", gap: 26, margin: "26px 0", flexWrap: "wrap" }}>
            <div><div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 7 }}>SCOPE</div><ScopeTag scope={decision.scope} /></div>
            <div><div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 7 }}>CONFIDENCE</div><Confidence level={decision.confidence} showLabel /></div>
            <div><div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 7 }}>ORIGIN</div><OriginTag origin={decision.origin} /></div>
          </div>

          <div className="panel pad" style={{ background: "rgba(45,212,191,.04)", borderColor: "rgba(45,212,191,.14)", marginBottom: 18 }}>
            <div className="mono" style={{ fontSize: 10, letterSpacing: ".2em", color: "var(--teal)", marginBottom: 9 }}>RATIONALE — WHY IT EXISTS</div>
            <div style={{ fontSize: 14, lineHeight: 1.6, color: "var(--text-2)", textWrap: "pretty" }}>{decision.rationale}</div>
          </div>

          <div style={{ marginBottom: 8 }} className="mono dim"><span style={{ fontSize: 10, letterSpacing: ".2em" }}>ORIGIN NOTE</span></div>
          <div className="muted" style={{ fontSize: 12.5, marginBottom: 22 }}>{ORIGIN_DESC[decision.origin]}</div>

          {decision.triage && decision.triage !== "none" && (
            <div className="panel pad" style={{ marginBottom: 22 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 9 }}><TriageTag triage={decision.triage} /><span className="mono dim" style={{ fontSize: 10, letterSpacing: ".14em" }}>ADVISORY ONLY · A HUMAN DECIDES</span></div>
              <div className="muted" style={{ fontSize: 13, lineHeight: 1.55 }}>{decision.triage_reason}</div>
            </div>
          )}

          <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 12 }}>SOURCE REFS</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 30 }}>
            {decision.source_refs && decision.source_refs.length ? decision.source_refs.map((r, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 11, padding: "10px 13px", borderRadius: 10, border: "1px solid var(--line)", background: "rgba(8,18,16,.5)" }}>
                <span style={{ color: r.type === "commit" ? "var(--amber)" : "var(--cyan)" }}><Icon name={r.type === "commit" ? "commit" : "file"} size={16} /></span>
                <span className="mono" style={{ fontSize: 12.5, color: "var(--text-2)" }}>{r.ref}</span>
                {r.label && <span className="muted" style={{ fontSize: 12 }}>· {r.label}</span>}
              </div>
            )) : <span className="dim mono" style={{ fontSize: 12 }}>No source references recorded.</span>}
          </div>

          <div className="mono dim" style={{ fontSize: 10.5, letterSpacing: ".12em", marginBottom: 18 }}>
            created {timeAgo(decision.created_at)} · updated {timeAgo(decision.updated_at)} · <span style={{ color: "var(--dim)" }}>{decision.id}</span>
          </div>

          {decision.status === "candidate" && (onApprove || onReject) && (
            <div style={{ ...footer, display: "flex", gap: 12 }}>
              <button className="btn primary lg" style={{ flex: 1 }} disabled={busy} onClick={() => onApprove(decision)}><Icon name="check" size={16} />Approve → Canonical</button>
              <button className="btn danger lg" disabled={busy} onClick={() => onReject(decision)}><Icon name="x" size={16} />Reject</button>
            </div>
          )}

          {decision.status === "canonical" && onReject && (
            <div style={footer}>
              <div className="muted" style={{ fontSize: 12.5, marginBottom: 11, lineHeight: 1.55 }}>
                Knowledge changes. <b style={{ color: "var(--text-2)" }}>Retiring</b> removes this from the canonical set, so agents are no longer served it. You can restore it later from the <b style={{ color: "var(--text-2)" }}>rejected</b> filter.
              </div>
              <button className="btn danger lg" style={{ width: "100%" }} disabled={busy} onClick={() => onReject(decision)}><Icon name="x" size={16} />Retire decision</button>
            </div>
          )}

          {decision.status === "rejected" && onApprove && (
            <div style={footer}>
              <div className="muted" style={{ fontSize: 12.5, marginBottom: 11, lineHeight: 1.55 }}>This decision is retired and not served to agents.</div>
              <button className="btn primary lg" style={{ width: "100%" }} disabled={busy} onClick={() => onApprove(decision)}><Icon name="check" size={16} />Restore → Canonical</button>
            </div>
          )}
        </div>
        )}
      </aside>
    </div>
  );
}

/* ---------- generic right-side drawer shell (overlay + slide-in + Esc) ---------- */
function SideDrawer({ title, eyebrow, onClose, width = 560, children }) {
  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 130, display: "flex", justifyContent: "flex-end" }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "rgba(2,6,8,.6)", backdropFilter: "blur(3px)", animation: "fadeup .3s" }} />
      <aside style={{ position: "relative", width: `min(${width}px, 92vw)`, height: "100%", background: "linear-gradient(180deg,#081512,#060f0d)", borderLeft: "1px solid var(--line-2)", boxShadow: "var(--shadow-deep)", overflowY: "auto", animation: "slidein .36s cubic-bezier(.2,.8,.3,1)" }}>
        <style>{`@keyframes slidein{from{transform:translateX(40px);opacity:.4}}`}</style>
        <div style={{ position: "sticky", top: 0, zIndex: 2, padding: "20px 26px", background: "linear-gradient(180deg,#081512,rgba(8,21,18,.7))", backdropFilter: "blur(8px)", borderBottom: "1px solid var(--line)", display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            {eyebrow && <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".2em", marginBottom: 4 }}>{eyebrow}</div>}
            <div style={{ fontSize: 15, color: "#eafff8", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
          </div>
          <div className="spacer" style={{ flex: 1 }} />
          <button className="icon-btn" onClick={onClose}><Icon name="x" size={16} /></button>
        </div>
        <div style={{ padding: "20px 28px 40px" }}>{children}</div>
      </aside>
    </div>
  );
}

/* ---------- section header ---------- */
function SectionTitle({ eyebrow, title, right }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 16, marginBottom: 18 }}>
      <div>
        {eyebrow && <div className="mono" style={{ fontSize: 10, letterSpacing: ".26em", color: "var(--dim)", marginBottom: 7, textTransform: "uppercase" }}>{eyebrow}</div>}
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 500, letterSpacing: ".01em" }}>{title}</h2>
      </div>
      <div style={{ flex: 1 }} />
      {right}
    </div>
  );
}

/* ---------- toast host ---------- */
const ToastCtx = React.createContext(() => {});
function ToastHost({ children }) {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((msg, opts = {}) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, msg, ...opts }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), opts.dur || 3200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap">
        {toasts.map((t) => (
          <div className="toast" key={t.id}>
            <span className="tk">{t.icon === "loop" ? <Icon name="loop" size={17} /> : <Icon name="check" size={17} />}</span>
            <span>{t.msg}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
const useToast = () => React.useContext(ToastCtx);

Object.assign(window, {
  StatusBadge, Confidence, ScopeTag, OriginTag, OriginLabel: ORIGIN_LABEL, OriginDesc: ORIGIN_DESC,
  TriageTag, TriageMeta: TRIAGE_META, EffectTag, ScoreRing, DecisionRow, DecisionEditor, DecisionDrawer, SideDrawer, SectionTitle, ToastHost, useToast,
});
