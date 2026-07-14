/* ============================================================
   APP SHELL — command rail, repo selector, router, particle field
   ============================================================ */

const { useState, useEffect, useRef, useMemo, useCallback } = React;

const NAV = [
  { group: "Impact", items: [
    { id: "impact", title: "Agent Impact", icon: "impact" },
    { id: "helpfulness", title: "Helpfulness", icon: "star" },
    { id: "loop", title: "Feedback Loop", icon: "loop" },
  ] },
  { group: "Knowledge", items: [
    { id: "overview", title: "Overview", icon: "grid" },
    { id: "decisions", title: "Decisions", icon: "list" },
    { id: "curation", title: "Curation", icon: "gavel" },
  ] },
  { group: "Sources", items: [
    { id: "origins", title: "Origins", icon: "source" },
    { id: "ingest", title: "Ingest", icon: "cost" },
  ] },
];
const NAV_FLAT = NAV.flatMap((g) => g.items.map((i) => ({ ...i, group: g.group })));

/* ---------- files-mode badge (git-tracked OKF bundle mounted read-only) ---------- */
function FilesModeBadge({ info }) {
  const dirty = info.dirty_files || 0;
  return (
    <div style={{
      position: "fixed", bottom: 14, left: "50%", transform: "translateX(-50%)",
      zIndex: 90, display: "flex", alignItems: "center", gap: 10,
      padding: "7px 16px", borderRadius: 999,
      background: "rgba(232,156,46,.12)", border: "1px solid rgba(232,156,46,.45)",
      backdropFilter: "blur(8px)", fontSize: 11.5, letterSpacing: ".06em",
    }} className="mono">
      <span style={{ color: "#e89c2e", fontWeight: 700 }}>FILES MODE</span>
      <span className="dim">{info.kb_dir}</span>
      <span className="dim">·</span>
      <span className="dim">edits write to the git working tree — review &amp; commit via git</span>
      {dirty > 0 && <span style={{ color: "#e89c2e" }}>{dirty} uncommitted change{dirty === 1 ? "" : "s"}</span>}
    </div>
  );
}

/* ---------- files-mode activity: the KB's git history as the event stream ---------- */
function FilesActivityView({ repo }) {
  const act = useApi(() => MetatronAPI.getFilesActivity(), [repo]);
  const [focusIdx, setFocusIdx] = useState(-1);
  // Contributors from git history become the constellation nodes: the same
  // "knowledge in flight" animation as MCP mode, with commits as the events.
  const commitsData = (act.data && act.data.commits) || [];
  const flightData = useMemo(() => {
    const by = {};
    commitsData.forEach((c) => {
      const b = by[c.author] || (by[c.author] = { name: c.author, promoted: 0, proposed: 0, commits: 0, last: c.date || "" });
      b.commits += 1;
      if ((c.date || "") > b.last) b.last = c.date || "";
      (c.changes || []).forEach((ch) => {
        if (ch.kind === "promoted" || ch.kind === "adopted") b.promoted += 1;
        else if (ch.kind === "proposed") b.proposed += 1;
      });
    });
    return {
      agents: Object.values(by).map((c) => ({
        id: c.commits + " commit" + (c.commits === 1 ? "" : "s") + " - last " + c.last.slice(0, 10),
        name: c.name,
        status: c.promoted > 0 ? "serving" : (c.proposed > 0 ? "feedback" : "idle"),
        decisions_received: c.promoted,
        feedback_sent: c.proposed,
      })),
      traces: [],
    };
  }, [commitsData]);
  if (act.loading) return <div className="dim mono" style={{ padding: 30 }}>reading git history...</div>;
  if (act.error || !act.data) return <div className="dim mono" style={{ padding: 30 }}>could not read git history</div>;
  const s = act.data.summary || {};
  const commits = act.data.commits || [];
  const KIND = {
    promoted: { label: "PROMOTED", color: "#3ecf8e" },
    adopted:  { label: "ADOPTED",  color: "#3ecf8e" },
    proposed: { label: "PROPOSED", color: "#e8c15a" },
    edited:   { label: "EDITED",   color: "#7ab8e8" },
    removed:  { label: "REMOVED",  color: "#e87a7a" },
    moved:    { label: "MOVED",    color: "#9aa5a0" },
  };
  const card = { flex: 1, padding: "18px 20px", borderRadius: 14, border: "1px solid var(--line)", background: "rgba(120,200,180,.04)" };
  const label = { fontSize: 11, letterSpacing: ".12em" };
  const num = { fontSize: 34, fontWeight: 700, marginTop: 6 };
  const sub = { fontSize: 12 };
  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div style={{ display: "flex", gap: 14 }}>
        <div style={card}>
          <div className="mono dim" style={label}>CANONICAL DECISIONS</div>
          <div style={num}>{s.canonical ?? 0}</div>
          <div className="dim" style={sub}>in decisions/ — what agents follow</div>
        </div>
        <div style={card}>
          <div className="mono dim" style={label}>AWAITING REVIEW</div>
          <div style={num}>{s.candidate ?? 0}</div>
          <div className="dim" style={sub}>in candidate/ — proposals, never binding</div>
        </div>
        <div style={card}>
          <div className="mono dim" style={label}>PROMOTIONS LANDED</div>
          <div style={num}>{s.promoted ?? 0}</div>
          <div className="dim" style={sub}>candidate/ to decisions/ moves in git history</div>
        </div>
        <div style={{ ...card, borderColor: (s.dirty_files || 0) > 0 ? "rgba(232,156,46,.5)" : "var(--line)" }}>
          <div className="mono dim" style={label}>UNCOMMITTED CHANGES</div>
          <div style={{ ...num, color: (s.dirty_files || 0) > 0 ? "#e89c2e" : undefined }}>{s.dirty_files ?? 0}</div>
          <div className="dim" style={sub}>working-tree edits awaiting your git review</div>
        </div>
      </div>
      <div style={{ borderRadius: 14, border: "1px solid var(--line)", padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "18px 20px 4px", display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 14 }}>Knowledge in flight</div>
            <div className="mono dim" style={{ fontSize: 10, letterSpacing: ".14em", marginTop: 4, textTransform: "uppercase" }}>repository {"\u21c4"} contributors - from git history</div>
          </div>
          <div style={{ flex: 1 }} />
          <span className="mono" style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--emerald)", boxShadow: "0 0 6px var(--emerald)" }} /><span style={{ fontSize: 10, color: "var(--muted)" }}>decisions adopted</span></span>
          <span className="mono" style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--cyan)", boxShadow: "0 0 6px var(--cyan)" }} /><span style={{ fontSize: 10, color: "var(--muted)" }}>candidates proposed</span></span>
        </div>
        {flightData.agents.length ? (
          <AgentConstellation data={flightData} focusedIdx={focusIdx} onFocus={setFocusIdx} paused={false} height={330} />
        ) : (
          <div style={{ height: 240, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14 }}>
            <div style={{ animation: "float-y 6s ease-in-out infinite" }}><MetatronCube size={110} opacity={1} hero /></div>
            <div className="mono" style={{ fontSize: 11, letterSpacing: ".22em", color: "var(--teal)" }}>AWAITING KNOWLEDGE</div>
            <div className="muted" style={{ fontSize: 12.5 }}>commit decision files to the knowledge base and contributors appear here</div>
          </div>
        )}
      </div>

      <div style={{ borderRadius: 14, border: "1px solid var(--line)", padding: "16px 20px" }}>
        <div style={{ fontWeight: 700 }}>Knowledge history</div>
        <div className="dim" style={{ fontSize: 12, margin: "4px 0 10px" }}>
          every commit that touched the knowledge base — a candidate/ to decisions/ rename is a promotion, reviewed like code
        </div>
        {commits.map((c) => (
          <div key={c.sha} style={{ display: "flex", gap: 14, padding: "10px 0", borderTop: "1px solid var(--line)", alignItems: "baseline" }}>
            <span className="mono dim" style={{ fontSize: 11, minWidth: 80 }}>{(c.date || "").slice(0, 10)}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13.5 }}>{c.subject}</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 5 }}>
                {c.changes.map((ch, i) => {
                  const k = KIND[ch.kind] || KIND.moved;
                  return (
                    <span key={i} className="mono" style={{ fontSize: 10.5, padding: "2px 8px", borderRadius: 999, border: "1px solid " + k.color + "55", color: k.color }}>
                      {k.label} {ch.file.replace(/\.md$/, "")}
                    </span>
                  );
                })}
              </div>
            </div>
            <span className="mono dim" style={{ fontSize: 11 }}>{c.author} - {c.sha}</span>
          </div>
        ))}
        {!commits.length && <div className="dim">no knowledge-base commits yet - author a candidate and commit it to start the history</div>}
      </div>
    </div>
  );
}

/* ---------- ambient particle field ---------- */
function ParticleField() {
  const ref = useRef(null);
  useEffect(() => {
    const cv = ref.current; if (!cv) return; const ctx = cv.getContext("2d");
    let w, h, dpr = Math.min(2, window.devicePixelRatio || 1), raf, parts = [];
    const resize = () => { w = cv.width = innerWidth * dpr; h = cv.height = innerHeight * dpr; cv.style.width = innerWidth + "px"; cv.style.height = innerHeight + "px"; };
    resize(); window.addEventListener("resize", resize);
    const N = Math.min(70, Math.floor(innerWidth / 22));
    parts = Array.from({ length: N }, () => ({ x: Math.random() * w, y: Math.random() * h, vx: (Math.random() - .5) * .12 * dpr, vy: (Math.random() - .5) * .12 * dpr, r: (Math.random() * 1.4 + .4) * dpr, a: Math.random() * .5 + .15 }));
    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      for (let i = 0; i < parts.length; i++) {
        const p = parts[i]; p.x += p.vx; p.y += p.vy;
        if (p.x < 0) p.x = w; if (p.x > w) p.x = 0; if (p.y < 0) p.y = h; if (p.y > h) p.y = 0;
        for (let j = i + 1; j < parts.length; j++) {
          const q = parts[j], dx = p.x - q.x, dy = p.y - q.y, d2 = dx * dx + dy * dy, max = (120 * dpr) ** 2;
          if (d2 < max) { const o = (1 - d2 / max) * .12; ctx.strokeStyle = `rgba(45,212,191,${o})`; ctx.lineWidth = dpr * .5; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke(); }
        }
        ctx.fillStyle = `rgba(80,220,190,${p.a})`; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 7); ctx.fill();
      }
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, []);
  return <canvas id="particle-canvas" ref={ref} />;
}

/* ---------- repo selector ---------- */
function RepoSelect({ repo, repos, onPick }) {
  const [open, setOpen] = useState(false);
  useEffect(() => { const c = () => setOpen(false); if (open) { window.addEventListener("click", c); return () => window.removeEventListener("click", c); } }, [open]);
  return (
    <div className="repo-select" onClick={(e) => e.stopPropagation()}>
      <div className={"repo-trigger " + (open ? "open" : "")} onClick={() => setOpen((o) => !o)}>
        <span className="dim mono" style={{ fontSize: 10, letterSpacing: ".14em" }}>REPO</span>
        <span className="dot" /><span className="name">{repo}</span>
        <span className="chev"><Icon name="chevron" size={15} /></span>
      </div>
      {open && (
        <div className="repo-menu">
          <div className="mono dim" style={{ fontSize: 9.5, letterSpacing: ".2em", padding: "6px 11px 8px" }}>SELECT REPOSITORY · SCOPES EVERYTHING</div>
          {repos.map((r) => (
            <div key={r} className={"repo-opt " + (r === repo ? "sel" : "")} onClick={() => { onPick(r); setOpen(false); }}>
              <span className="dot" style={{ width: 7, height: 7, borderRadius: "50%", background: r === repo ? "var(--teal)" : "var(--dim)", boxShadow: r === repo ? "0 0 8px var(--teal-glow)" : "none" }} />
              <span className="name">{r}</span>
              {r === repo && <span className="meta" style={{ color: "var(--teal)" }}><Icon name="check" size={14} /></span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- the app ---------- */
function App() {
  const [repo, setRepo] = useState(null);
  const [view, setView] = useState("impact");
  const [drawer, setDrawer] = useState(null);
  const [drawerBusy, setDrawerBusy] = useState(false);
  const [panel, setPanel] = useState(null);  // agent/query drill-down side drawer
  const [statsV, setStatsV] = useState(0);
  const [dataV, setDataV] = useState(0);

  // From a drill-down drawer, follow a decision: close the panel, open the decision drawer.
  const openPanelDecision = useCallback((id) => {
    setPanel(null);
    MetatronAPI.getDecision(id).then((d) => d && d.id && setDrawer(d));
  }, []);

  const repos = useApi(() => MetatronAPI.getRepos(), []);
  const ver = useApi(() => MetatronAPI.getVersion(), []);
  const mode = useApi(() => MetatronAPI.getMode(), [dataV, statsV]);
  const filesMode = mode.data && mode.data.mode === "files" ? mode.data : null;
  // Files mode: Helpfulness/Feedback Loop need the MCP event stream and stay
  // hidden; Impact becomes the git-history activity view.
  const nav = useMemo(() => {
    if (!filesMode) return NAV;
    return NAV.map((g) => ({ ...g, items: g.items
      .filter((i) => i.id !== "helpfulness" && i.id !== "loop")
      .map((i) => (i.id === "impact" ? { ...i, title: "Knowledge Activity" } : i)) }))
      .filter((g) => g.items.length);
  }, [filesMode]);
  // Restore the last-chosen repo across refreshes; fall back to the first repo.
  useEffect(() => {
    if (repos.data && !repo) {
      const saved = localStorage.getItem("metatron.repo");
      const list = repos.data.repos;
      setRepo(list.includes(saved) ? saved : list[0]);
    }
  }, [repos.data]);
  const pickRepo = useCallback((r) => { setRepo(r); localStorage.setItem("metatron.repo", r); }, []);
  const stats = useApi(() => (repo ? MetatronAPI.getStats(repo) : Promise.resolve(null)), [repo, statsV]);

  const refreshStats = useCallback(() => setStatsV((v) => v + 1), []);
  const refreshAll = useCallback(() => { setStatsV((v) => v + 1); setDataV((v) => v + 1); }, []);

  // reveal safety: after each view settles, force entrance elements visible
  // (covers paused-tab / reduced-motion where keyframes don't play).
  const scrollRef = useRef(null);
  useEffect(() => {
    const el = scrollRef.current; if (!el) return;
    el.classList.remove("anim-safe");
    const t = setTimeout(() => el.classList.add("anim-safe"), 1000);
    return () => clearTimeout(t);
  }, [view, repo, dataV]);

  // Boot watchdog: tick elapsed time while the repo list is loading so the splash
  // can give up and surface an error instead of spinning forever (e.g. the local
  // server died mid-request).
  const [bootElapsed, setBootElapsed] = useState(0);
  useEffect(() => {
    if (!repos.loading) { setBootElapsed(0); return; }
    const t0 = Date.now();
    const id = setInterval(() => setBootElapsed(Date.now() - t0), 500);
    return () => clearInterval(id);
  }, [repos.loading]);

  const boot = MetatronBoot.bootScreenState({
    loading: repos.loading,
    error: repos.error,
    repos: repos.data ? repos.data.repos : null,
    elapsedMs: bootElapsed,
    timeoutMs: 10000,
  });

  if (boot === "error" || boot === "timeout") return (
    <div style={{ height: "100vh", display: "grid", placeItems: "center" }}>
      <ErrorState
        onRetry={repos.reload}
        detail={boot === "timeout"
          ? "The Metatron API stopped responding. Is the local server still running?"
          : "Could not reach the Metatron API to list repositories."}
      />
    </div>
  );
  if (boot === "empty") return (
    <div style={{ height: "100vh", display: "grid", placeItems: "center" }}>
      <div className="state-box" style={{ maxWidth: 460 }}>
        <div style={{ animation: "float-y 3s ease-in-out infinite" }}><MetatronEmblem size={88} /></div>
        <div className="t" style={{ marginTop: 18 }}>Onboard your first repo</div>
        <div className="d">Metatron mines a repo's code and git history into decision candidates for you to curate. Start with:</div>
        <code className="mono" style={{ display: "block", padding: "12px 16px", borderRadius: 10, background: "rgba(120,200,180,.07)", border: "1px solid var(--line)", color: "var(--teal)", fontSize: 12.5, userSelect: "all" }}>metatron ingest /path/to/your/repo</code>
        <div className="d dim" style={{ fontSize: 11.5 }}>Then refresh — the catalog appears here. If you set <span className="mono">METATRON_DB</span>, confirm it points at the right directory.</div>
        <button className="btn" onClick={repos.reload}>Refresh</button>
      </div>
    </div>
  );
  if (boot === "loading" || !repo) return (
    <div style={{ height: "100vh", display: "grid", placeItems: "center" }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ animation: "float-y 3s ease-in-out infinite" }}><MetatronEmblem size={88} /></div>
        <div className="mono" style={{ marginTop: 24, letterSpacing: ".3em", fontSize: 12, color: "var(--teal)" }}>METATRON</div>
        <div className="mono dim" style={{ marginTop: 10, letterSpacing: ".14em", fontSize: 11 }}>initializing knowledge base…</div>
      </div>
    </div>
  );

  const cur = nav.flatMap((g) => g.items.map((i) => ({ ...i, group: g.group })))
    .find((n) => n.id === view) || NAV_FLAT.find((n) => n.id === view);

  return (
    <ToastHost>
      {filesMode && <FilesModeBadge info={filesMode} />}
      <div className="shell">
        {/* command rail */}
        <nav className="rail">
          <div style={{ position: "absolute", bottom: -90, left: -90, opacity: .6, pointerEvents: "none" }}><MetatronCube size={280} opacity={0.08} /></div>
          <div className="rail-brand">
            <MetatronEmblem size={38} />
            <div className="wordmark">METATRON<small>KNOWLEDGE BASE</small></div>
          </div>
          {nav.map((g) => (
            <div className="rail-group" key={g.group}>
              <div className="label">{g.group}</div>
              {g.items.map((it) => (
                <div key={it.id} className={"nav-item " + (view === it.id ? "active" : "")} onClick={() => { setView(it.id); }}>
                  <span className="ico"><Icon name={it.icon} size={18} /></span>
                  <span>{it.title}</span>
                  {it.id === "curation" && stats.data && stats.data.candidate > 0 && <span className="nav-badge">{stats.data.candidate}</span>}
                </div>
              ))}
            </div>
          ))}
          <div className="rail-foot">
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--emerald)", boxShadow: "0 0 8px var(--emerald-glow)" }} />
              <span className="mono dim" style={{ fontSize: 10.5, letterSpacing: ".1em" }} title={ver.data ? `revision ${ver.data.revision}` : ""}>API connected{ver.data ? ` · v${ver.data.version}` : ""}</span>
              {ver.data && ver.data.update_available && (
                <span className="chip" title={"v" + ver.data.latest + " · run: " + ver.data.upgrade_command}
                  style={{ marginLeft: 8, fontSize: 9, color: "var(--amber)", borderColor: "rgba(245,193,107,.3)" }}>
                  update available
                </span>
              )}
            </div>
          </div>
        </nav>

        {/* stage */}
        <div className="stage">
          <header className="topbar">
            <div className="crumb">
              <span className="eyebrow">{cur.group} / Metatron</span>
              <h1>{cur.title}</h1>
            </div>
            <div className="spacer" />
            <RepoSelect repo={repo} repos={repos.data.repos} onPick={pickRepo} />
          </header>
          <div className="stage-scroll" ref={scrollRef} key={view + repo + dataV}>
            <Router view={view} repo={repo} openDecision={setDrawer} openPanel={setPanel} goto={setView} refreshStats={refreshStats} dataV={dataV} filesMode={filesMode} />
          </div>
        </div>
      </div>

      <DecisionDrawer decision={drawer} busy={drawerBusy} onClose={() => setDrawer(null)}
        onApprove={async (p) => { setDrawerBusy(true); await MetatronAPI.approveDecision(p.id); setDrawerBusy(false); setDrawer(null); refreshAll(); }}
        onReject={async (p) => { setDrawerBusy(true); await MetatronAPI.rejectDecision(p.id); setDrawerBusy(false); setDrawer(null); refreshAll(); }}
        onEdited={async () => { if (drawer) { const fresh = await MetatronAPI.getDecision(drawer.id); setDrawer(fresh); } refreshAll(); }} />

      {panel && panel.type === "agent" && <AgentActivityDrawer agent={panel.agent} focus={panel.focus} onOpenDecision={openPanelDecision} onClose={() => setPanel(null)} />}
      {panel && panel.type === "query" && <QueryDrawer query={panel.query} onOpenDecision={openPanelDecision} onClose={() => setPanel(null)} />}
    </ToastHost>
  );
}

function Router({ view, repo, openDecision, openPanel, goto, refreshStats, filesMode }) {
  switch (view) {
    case "impact": return filesMode
      ? <FilesActivityView repo={repo} />
      : <AgentImpactView repo={repo} openPanel={openPanel} />;
    case "helpfulness": return <HelpfulnessView repo={repo} openDecision={openDecision} />;
    case "loop": return <FeedbackLoopView repo={repo} refresh={refreshStats} openDecision={openDecision} />;
    case "overview": return <OverviewView repo={repo} openDecision={openDecision} goto={goto} />;
    case "decisions": return <DecisionsView repo={repo} openDecision={openDecision} />;
    case "curation": return <CurationView repo={repo} openDecision={openDecision} refresh={refreshStats} />;
    case "origins": return <OriginsView repo={repo} />;
    case "ingest": return <IngestView repo={repo} />;
    default: return null;
  }
}

/* ---------- desktop-only gate (shown under a mobile breakpoint via CSS) ---------- */
function MobileNotice() {
  return (
    <div className="mobile-gate">
      <div style={{ textAlign: "center", padding: 32, maxWidth: 360 }}>
        <div style={{ animation: "float-y 3s ease-in-out infinite" }}><MetatronEmblem size={72} /></div>
        <div className="mono" style={{ marginTop: 22, letterSpacing: ".3em", fontSize: 12, color: "var(--teal)" }}>METATRON</div>
        <h2 style={{ margin: "16px 0 10px", fontSize: 18, fontWeight: 500 }}>Best on desktop</h2>
        <p className="muted" style={{ fontSize: 13.5, lineHeight: 1.6 }}>
          The Metatron console is built for a wide screen — dense decision tables,
          side-by-side panels, and the live agent constellation. Open it on a desktop to
          curate and explore your knowledge base.
        </p>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<React.StrictMode><AppRoot /></React.StrictMode>);
function AppRoot() { return <><ParticleField /><App /><MobileNotice /></>; }
