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
  const [statsV, setStatsV] = useState(0);
  const [dataV, setDataV] = useState(0);

  const repos = useApi(() => MetatronAPI.getRepos(), []);
  const ver = useApi(() => MetatronAPI.getVersion(), []);
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

  if (repos.loading || !repo) return (
    <div style={{ height: "100vh", display: "grid", placeItems: "center" }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ animation: "float-y 3s ease-in-out infinite" }}><MetatronEmblem size={88} /></div>
        <div className="mono" style={{ marginTop: 24, letterSpacing: ".3em", fontSize: 12, color: "var(--teal)" }}>METATRON</div>
        <div className="mono dim" style={{ marginTop: 10, letterSpacing: ".14em", fontSize: 11 }}>initializing knowledge lattice…</div>
      </div>
    </div>
  );
  if (repos.error) return <div style={{ height: "100vh", display: "grid", placeItems: "center" }}><ErrorState onRetry={repos.reload} detail="Could not reach the Metatron API to list repositories." /></div>;

  const cur = NAV_FLAT.find((n) => n.id === view);

  return (
    <ToastHost>
      <div className="shell">
        {/* command rail */}
        <nav className="rail">
          <div style={{ position: "absolute", bottom: -90, left: -90, opacity: .6, pointerEvents: "none" }}><MetatronCube size={280} opacity={0.08} /></div>
          <div className="rail-brand">
            <MetatronEmblem size={38} />
            <div className="wordmark">METATRON<small>KNOWLEDGE LATTICE</small></div>
          </div>
          {NAV.map((g) => (
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
            <Router view={view} repo={repo} openDecision={setDrawer} goto={setView} refreshStats={refreshStats} dataV={dataV} />
          </div>
        </div>
      </div>

      <DecisionDrawer decision={drawer} busy={drawerBusy} onClose={() => setDrawer(null)}
        onApprove={async (p) => { setDrawerBusy(true); await MetatronAPI.approveDecision(p.id); setDrawerBusy(false); setDrawer(null); refreshAll(); }}
        onReject={async (p) => { setDrawerBusy(true); await MetatronAPI.rejectDecision(p.id); setDrawerBusy(false); setDrawer(null); refreshAll(); }} />
    </ToastHost>
  );
}

function Router({ view, repo, openDecision, goto, refreshStats }) {
  switch (view) {
    case "impact": return <AgentImpactView repo={repo} />;
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
          side-by-side panels, and the live agent lattice. Open it on a desktop to
          curate and explore your knowledge base.
        </p>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<React.StrictMode><AppRoot /></React.StrictMode>);
function AppRoot() { return <><ParticleField /><App /><MobileNotice /></>; }
