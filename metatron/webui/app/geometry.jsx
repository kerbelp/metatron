/* ============================================================
   Geometry & visualization library
   Sacred-geometry emblem, Metatron's Cube, bespoke charts,
   count-ups, and the knowledge-flow animation.
   Exposes everything on window for the other babel scripts.
   ============================================================ */
const { useState, useEffect, useRef, useMemo, useCallback } = React;

/* ---------- line icons (stroke) ---------- */
function Icon({ name, size = 18, className = "", style }) {
  const p = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round" };
  const paths = {
    impact: <><circle cx="12" cy="12" r="3" {...p} /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" {...p} /></>,
    pulse: <path d="M2 12h4l2-7 4 14 2-7h8" {...p} />,
    star: <><path d="M12 3l8 14H4z" {...p} /><path d="M12 21L4 7h16z" {...p} /></>,
    loop: <><path d="M3 12a9 9 0 0 1 15-6.7L21 8" {...p} /><path d="M21 4v4h-4" {...p} /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" {...p} /><path d="M3 20v-4h4" {...p} /></>,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1" {...p} /><rect x="14" y="3" width="7" height="7" rx="1" {...p} /><rect x="3" y="14" width="7" height="7" rx="1" {...p} /><rect x="14" y="14" width="7" height="7" rx="1" {...p} /></>,
    list: <><path d="M8 6h13M8 12h13M8 18h13" {...p} /><circle cx="3.5" cy="6" r="1" fill="currentColor" stroke="none" /><circle cx="3.5" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="3.5" cy="18" r="1" fill="currentColor" stroke="none" /></>,
    gavel: <><path d="M14 13l-7 7" {...p} /><path d="M9.5 5.5l5 5M12.5 2.5l5 5M11 4l5 5" {...p} /><path d="M4 21h8" {...p} /></>,
    source: <><circle cx="6" cy="6" r="2.4" {...p} /><circle cx="6" cy="18" r="2.4" {...p} /><circle cx="18" cy="12" r="2.4" {...p} /><path d="M8 7l8 4M8 17l8-4" {...p} /></>,
    cost: <><circle cx="12" cy="12" r="9" {...p} /><path d="M12 7v10M9.5 9.5c0-1 1.1-1.5 2.5-1.5s2.5.6 2.5 1.6c0 2.4-5 1.4-5 3.8 0 1 1.1 1.6 2.5 1.6s2.5-.5 2.5-1.5" {...p} /></>,
    search: <><circle cx="11" cy="11" r="7" {...p} /><path d="M21 21l-4-4" {...p} /></>,
    chevron: <path d="M6 9l6 6 6-6" {...p} />,
    check: <path d="M5 12l4 4 10-11" {...p} />,
    x: <path d="M6 6l12 12M18 6L6 18" {...p} />,
    spark: <path d="M12 2l1.6 6.4L20 10l-6.4 1.6L12 18l-1.6-6.4L4 10l6.4-1.6z" {...p} />,
    arrow: <path d="M5 12h14M13 6l6 6-6 6" {...p} />,
    up: <path d="M6 15l6-6 6 6" {...p} />,
    down: <path d="M6 9l6 6 6-6" {...p} />,
    flat: <path d="M5 12h14" {...p} />,
    clock: <><circle cx="12" cy="12" r="9" {...p} /><path d="M12 7v5l3 2" {...p} /></>,
    file: <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" {...p} /><path d="M14 3v5h5" {...p} /></>,
    commit: <><circle cx="12" cy="12" r="3.2" {...p} /><path d="M2 12h6.8M15.2 12H22" {...p} /></>,
    bolt: <path d="M13 2L4 14h6l-1 8 9-12h-6z" {...p} />,
    layers: <><path d="M12 3l9 5-9 5-9-5z" {...p} /><path d="M3 13l9 5 9-5" {...p} /></>,
    target: <><circle cx="12" cy="12" r="9" {...p} /><circle cx="12" cy="12" r="5" {...p} /><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" /></>,
  };
  return <svg viewBox="0 0 24 24" width={size} height={size} className={className} style={style} aria-hidden="true">{paths[name] || null}</svg>;
}

/* ============================================================
   METATRON EMBLEM — star-tetrahedron / merkaba inside a circle,
   the recurring sacred-geometry mark.
   ============================================================ */
function MetatronEmblem({ size = 40, glow = true, animate = true, stroke = "var(--teal)" }) {
  const id = useMemo(() => "me" + Math.random().toString(36).slice(2, 7), []);
  // Metatron's Cube: center + inner hexagon + outer hexagon (collinear spokes).
  const pt = (r, i) => { const a = (60 * i - 90) * Math.PI / 180; return [50 + r * Math.cos(a), 50 + r * Math.sin(a)]; };
  const inner = [0, 1, 2, 3, 4, 5].map((i) => pt(18, i));
  const outer = [0, 1, 2, 3, 4, 5].map((i) => pt(36, i));
  const nodes = [[50, 50], ...inner, ...outer];
  return (
    <svg viewBox="0 0 100 100" width={size} height={size} style={{ overflow: "visible" }}>
      <defs>
        <radialGradient id={id + "g"} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--emerald)" stopOpacity="0.95" />
          <stop offset="100%" stopColor="var(--teal)" stopOpacity="0.55" />
        </radialGradient>
        {glow && <filter id={id + "f"} x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="1.2" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>}
      </defs>
      <g filter={glow ? `url(#${id}f)` : undefined} stroke={stroke} fill="none" strokeWidth="1.1" strokeLinejoin="round" strokeLinecap="round">
        {/* rotating outer ring */}
        <circle cx="50" cy="50" r="44" strokeOpacity="0.28" className={animate ? "spin-slow" : ""} strokeDasharray="2 5" />
        {/* outer hexagon */}
        <g strokeOpacity="0.6">
          {outer.map((p, i) => { const q = outer[(i + 1) % 6]; return <line key={"o" + i} x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} />; })}
        </g>
        {/* inner hexagon + spokes */}
        <g strokeOpacity="0.4">
          {inner.map((p, i) => { const q = inner[(i + 1) % 6]; return <line key={"i" + i} x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} />; })}
          {outer.map((p, i) => <line key={"s" + i} x1="50" y1="50" x2={p[0]} y2={p[1]} />)}
        </g>
        {/* 13 nodes */}
        <g fill={stroke} stroke="none">
          {inner.concat(outer).map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r="2" />)}
        </g>
        {/* glowing core */}
        <circle cx="50" cy="50" r="4.6" fill={`url(#${id}g)`} stroke="none" />
        <circle cx="50" cy="50" r="8" strokeOpacity="0.55" style={animate ? { animation: "glow-breathe 3.4s ease-in-out infinite" } : undefined} />
      </g>
    </svg>
  );
}

/* ============================================================
   METATRON'S CUBE — full 13-circle field with connective lines.
   Used as a large ambient/hero motif.
   ============================================================ */
function MetatronCube({ size = 360, opacity = 0.5, spin = true, hero = false }) {
  // 13 circle centers of Metatron's Cube — Fruit of Life (center + 2 hex rings).
  const h = Math.sqrt(3);
  const centers = [
    [0, 0],
    [2, 0], [-2, 0], [1, h], [-1, h], [1, -h], [-1, -h],            // inner 6
    [4, 0], [-4, 0], [2, 2 * h], [-2, 2 * h], [2, -2 * h], [-2, -2 * h], // outer 6
  ];
  const map = ([x, y]) => [50 + x * 9.5, 50 + y * 9.5];
  const pts = centers.map(map);
  const ringOf = (i) => (i === 0 ? 0 : i < 7 ? 1 : 2);
  const lines = [];
  for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) lines.push([pts[i], pts[j]]);
  const id = useMemo(() => "mc" + Math.random().toString(36).slice(2, 7), []);

  if (hero) {
    // The www hero look: small glowing nodes (ring + pulsing core) + lit lattice.
    const nodeR = (r) => (r === 0 ? 2.6 : r === 1 ? 2.1 : 1.7);
    return (
      <svg viewBox="0 0 100 100" width={size} height={size} style={{ opacity, overflow: "visible" }}>
        <defs>
          <radialGradient id={id} cx="50%" cy="50%" r="60%">
            <stop offset="0%" stopColor="var(--teal)" stopOpacity="0.5" />
            <stop offset="60%" stopColor="var(--teal)" stopOpacity="0.12" />
            <stop offset="100%" stopColor="var(--teal)" stopOpacity="0" />
          </radialGradient>
          <radialGradient id={id + "c"} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#bafff0" stopOpacity="1" />
            <stop offset="100%" stopColor="var(--teal)" stopOpacity="0.9" />
          </radialGradient>
          <filter id={id + "g"} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="0.7" />
          </filter>
        </defs>
        <style>{`@keyframes mcpulse{0%,100%{opacity:.4}50%{opacity:1}}`}</style>
        <g className={spin ? "spin-slow" : ""} style={{ transformOrigin: "50px 50px" }}>
          <g stroke={`url(#${id})`} strokeWidth="0.35" fill="none">
            {lines.map((l, i) => <line key={i} x1={l[0][0]} y1={l[0][1]} x2={l[1][0]} y2={l[1][1]} />)}
          </g>
          {/* node halos */}
          <g fill="none" stroke="var(--teal)" strokeOpacity="0.7" strokeWidth="0.5" filter={`url(#${id}g)`}>
            {pts.map((pt, i) => <circle key={i} cx={pt[0]} cy={pt[1]} r={nodeR(ringOf(i)) + 1.2} />)}
          </g>
          {/* node cores, pulsing */}
          <g fill={`url(#${id}c)`}>
            {pts.map((pt, i) => (
              <circle key={i} cx={pt[0]} cy={pt[1]} r={nodeR(ringOf(i))}
                style={{ animation: `mcpulse ${(2.6 + (i % 5) * 0.45).toFixed(2)}s ease-in-out ${(i * 0.18).toFixed(2)}s infinite` }} />
            ))}
          </g>
        </g>
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 100 100" width={size} height={size} style={{ opacity }}>
      <defs>
        <radialGradient id={id} cx="50%" cy="50%" r="55%">
          <stop offset="0%" stopColor="var(--teal)" stopOpacity="0.55" />
          <stop offset="55%" stopColor="var(--teal)" stopOpacity="0.18" />
          <stop offset="100%" stopColor="var(--teal)" stopOpacity="0" />
        </radialGradient>
      </defs>
      <g className={spin ? "spin-slow" : ""} style={{ transformOrigin: "50px 50px" }}>
        <g stroke={`url(#${id})`} strokeWidth="0.25" fill="none">
          {lines.map((l, i) => <line key={i} x1={l[0][0]} y1={l[0][1]} x2={l[1][0]} y2={l[1][1]} />)}
        </g>
        <g stroke="var(--teal)" strokeOpacity="0.5" strokeWidth="0.4" fill="none">
          {pts.map((pt, i) => <circle key={i} cx={pt[0]} cy={pt[1]} r="9.5" />)}
        </g>
      </g>
    </svg>
  );
}

/* ============================================================
   COUNT-UP — animated number, eases to value on mount/change.
   ============================================================ */
function CountUp({ value, dur = 1200, decimals = 0, prefix = "", suffix = "", className = "", style }) {
  const [disp, setDisp] = useState(0);
  const from = useRef(0); const raf = useRef(0);
  useEffect(() => {
    const start = performance.now(); const a = from.current; const b = value;
    const ease = (t) => 1 - Math.pow(1 - t, 3);
    const tick = (now) => {
      const t = Math.min(1, (now - start) / dur);
      setDisp(a + (b - a) * ease(t));
      if (t < 1) raf.current = requestAnimationFrame(tick); else from.current = b;
    };
    cancelAnimationFrame(raf.current); raf.current = requestAnimationFrame(tick);
    // safety: if rAF is throttled/paused (inactive tab, reduced-motion),
    // snap to the final value so numbers are never stuck at 0.
    const safety = setTimeout(() => { from.current = b; setDisp(b); }, dur + 500);
    return () => { cancelAnimationFrame(raf.current); clearTimeout(safety); };
  }, [value, dur]);
  const n = decimals ? disp.toFixed(decimals) : Math.round(disp).toLocaleString();
  return <span className={className} style={style}>{prefix}{n}{suffix}</span>;
}

/* ============================================================
   DONUT — self-drawing arc ring (canonical / candidate / rejected)
   ============================================================ */
function Donut({ segments, size = 160, thickness = 14, children }) {
  const total = segments.reduce((a, s) => a + s.value, 0) || 1;
  const r = (size - thickness) / 2; const c = 2 * Math.PI * r; const cx = size / 2;
  const [draw, setDraw] = useState(0);
  useEffect(() => { const t = setTimeout(() => setDraw(1), 80); return () => clearTimeout(t); }, []);
  let off = 0;
  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={cx} cy={cx} r={r} fill="none" stroke="rgba(120,200,180,.08)" strokeWidth={thickness} />
        {segments.map((s, i) => {
          const len = (s.value / total) * c * draw;
          const el = <circle key={i} cx={cx} cy={cx} r={r} fill="none" stroke={s.color} strokeWidth={thickness}
            strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-off} strokeLinecap="round"
            style={{ transition: "stroke-dasharray 1.1s cubic-bezier(.3,.8,.3,1), stroke-dashoffset 1.1s cubic-bezier(.3,.8,.3,1)", filter: `drop-shadow(0 0 6px ${s.color}66)` }} />;
          off += (s.value / total) * c * draw;
          return el;
        })}
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>{children}</div>
    </div>
  );
}

/* ============================================================
   BAR METER — horizontal animated bar (rates, helpful vs noise)
   ============================================================ */
function Meter({ value, max = 1, color = "var(--teal)", track = "rgba(120,200,180,.08)", height = 8, delay = 0 }) {
  const [w, setW] = useState(0);
  useEffect(() => { const t = setTimeout(() => setW(Math.max(0, Math.min(1, value / max))), 120 + delay); return () => clearTimeout(t); }, [value, max, delay]);
  return (
    <div style={{ height, borderRadius: 20, background: track, overflow: "hidden" }}>
      <div style={{ height: "100%", width: `${w * 100}%`, borderRadius: 20, background: color, boxShadow: `0 0 10px ${typeof color === "string" && color.startsWith("var") ? "var(--teal-glow)" : color}`, transition: "width 1.1s cubic-bezier(.3,.8,.3,1)" }} />
    </div>
  );
}

/* ============================================================
   SPARK / AREA — self-drawing line+area chart from a series
   ============================================================ */
function Spark({ data, w = 260, h = 64, color = "var(--teal)", fill = true, strokeW = 2 }) {
  const id = useMemo(() => "sp" + Math.random().toString(36).slice(2, 7), []);
  const ref = useRef(null);
  const max = Math.max(...data, 1), min = Math.min(...data, 0);
  const pts = data.map((d, i) => [(i / (data.length - 1)) * w, h - ((d - min) / (max - min || 1)) * (h - 8) - 4]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = line + ` L ${w} ${h} L 0 ${h} Z`;
  useEffect(() => {
    const path = ref.current; if (!path) return;
    const len = path.getTotalLength(); path.style.transition = "none";
    path.style.strokeDasharray = len; path.style.strokeDashoffset = len;
    requestAnimationFrame(() => { path.style.transition = "stroke-dashoffset 1.6s cubic-bezier(.3,.8,.3,1)"; path.style.strokeDashoffset = 0; });
    // safety: ensure the line is fully drawn even if rAF is paused (inactive tab)
    const t = setTimeout(() => { if (ref.current) ref.current.style.strokeDashoffset = 0; }, 1900);
    return () => clearTimeout(t);
  }, [data.join(",")]);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block", overflow: "visible" }}>
      <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity="0.28" /><stop offset="100%" stopColor={color} stopOpacity="0" /></linearGradient></defs>
      {fill && <path d={area} fill={`url(#${id})`} stroke="none" style={{ opacity: 0, animation: "fadeup .9s .4s forwards" }} />}
      <path ref={ref} d={line} fill="none" stroke={color} strokeWidth={strokeW} strokeLinecap="round" strokeLinejoin="round" style={{ filter: `drop-shadow(0 0 5px ${color}66)` }} />
      {pts.length > 0 && <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="3" fill={color} style={{ filter: `drop-shadow(0 0 5px ${color})` }} />}
    </svg>
  );
}

/* ============================================================
   KNOWLEDGE FLOW — the signature viz. A central Metatron core
   pulses decisions outward along curved conduits into an agent node.
   ============================================================ */
function KnowledgeFlow({ count = 8, active = true, height = 220 }) {
  const id = useMemo(() => "kf" + Math.random().toString(36).slice(2, 7), []);
  const W = 640, H = height;
  const core = [120, H / 2];
  const agent = [W - 110, H / 2];
  // fan of conduits between core and agent
  const conduits = Array.from({ length: 5 }, (_, i) => {
    const spread = (i - 2) * 34;
    const c1 = [W * 0.42, H / 2 + spread * 1.3];
    const c2 = [W * 0.62, H / 2 - spread * 0.6];
    return `M ${core[0]} ${core[1]} C ${c1[0]} ${c1[1]}, ${c2[0]} ${c2[1]}, ${agent[0]} ${agent[1]}`;
  });
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }} preserveAspectRatio="xMidYMid meet">
      <defs>
        <radialGradient id={id + "core"} cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="var(--emerald)" /><stop offset="100%" stopColor="var(--teal-deep)" /></radialGradient>
        <linearGradient id={id + "wire"} x1="0" x2="1"><stop offset="0%" stopColor="var(--teal)" stopOpacity="0.05" /><stop offset="50%" stopColor="var(--teal)" stopOpacity="0.5" /><stop offset="100%" stopColor="var(--cyan)" stopOpacity="0.15" /></linearGradient>
        <filter id={id + "glow"} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.2" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      {/* conduits */}
      {conduits.map((d, i) => <path key={i} d={d} fill="none" stroke={`url(#${id}wire)`} strokeWidth="1.2" className={active ? "flow-line" : ""} style={{ animationDelay: `${i * -1.7}s` }} />)}
      {/* travelling decision packets */}
      {active && conduits.map((d, i) => (
        <circle key={"p" + i} r="3.4" fill="var(--emerald)" filter={`url(#${id}glow)`}>
          <animateMotion dur={`${2.6 + i * 0.4}s`} repeatCount="indefinite" path={d} begin={`${i * 0.5}s`} />
          <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.85;1" dur={`${2.6 + i * 0.4}s`} repeatCount="indefinite" begin={`${i * 0.5}s`} />
        </circle>
      ))}
      {/* agent node */}
      <g>
        <circle cx={agent[0]} cy={agent[1]} r="30" fill="rgba(34,211,238,.06)" stroke="var(--cyan)" strokeOpacity="0.4" strokeWidth="1" />
        <rect x={agent[0] - 13} y={agent[1] - 13} width="26" height="26" rx="6" fill="rgba(8,22,24,.9)" stroke="var(--cyan)" strokeWidth="1.2" />
        <path d={`M ${agent[0] - 6} ${agent[1] - 4} l -4 4 l 4 4 M ${agent[0] + 6} ${agent[1] - 4} l 4 4 l -4 4`} stroke="var(--cyan)" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <text x={agent[0]} y={agent[1] + 46} textAnchor="middle" fill="var(--muted)" style={{ font: "600 11px var(--mono)", letterSpacing: ".12em" }}>AGENT</text>
      </g>
      {/* metatron core */}
      <g style={{ transformOrigin: `${core[0]}px ${core[1]}px` }}>
        {active && <circle cx={core[0]} cy={core[1]} r="34" fill="none" stroke="var(--teal)" strokeWidth="1" opacity="0" style={{ transformOrigin: `${core[0]}px ${core[1]}px`, animation: "pulse-ring 3s ease-out infinite" }} />}
        <g transform={`translate(${core[0] - 36}, ${core[1] - 36})`}><MetatronEmblem size={72} /></g>
        <text x={core[0]} y={core[1] + 56} textAnchor="middle" fill="var(--teal)" style={{ font: "600 11px var(--mono)", letterSpacing: ".12em" }}>METATRON</text>
      </g>
      <text x={(core[0] + agent[0]) / 2} y={28} textAnchor="middle" fill="var(--dim)" style={{ font: "600 10px var(--mono)", letterSpacing: ".24em" }}>{count} DECISIONS SERVED →</text>
    </svg>
  );
}

/* ---------- small shared bits ---------- */
function Spinner({ size = 34 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 50 50" className="spinner">
      <circle cx="25" cy="25" r="20" fill="none" stroke="rgba(120,200,180,.12)" strokeWidth="4" />
      <circle cx="25" cy="25" r="20" fill="none" stroke="var(--teal)" strokeWidth="4" strokeLinecap="round" strokeDasharray="80 200" style={{ animation: "spin 1s linear infinite", transformOrigin: "center", filter: "drop-shadow(0 0 4px var(--teal-glow))" }} />
    </svg>
  );
}
function Loading({ label = "Reading the lattice…" }) {
  return <div className="state-box"><Spinner /><div className="mono dim" style={{ fontSize: 12, letterSpacing: ".14em" }}>{label}</div></div>;
}
function ErrorState({ onRetry, detail }) {
  return <div className="state-box"><div style={{ color: "var(--rose)" }}><Icon name="x" size={28} /></div><div className="t">Signal lost</div><div className="d">{detail || "The Metatron API did not respond. Check the local server and retry."}</div>{onRetry && <button className="btn" onClick={onRetry}>Retry</button>}</div>;
}
function Empty({ title = "Nothing here yet", detail, icon = "spark" }) {
  return <div className="state-box"><div className="dim"><Icon name={icon} size={26} /></div><div className="t">{title}</div>{detail && <div className="d">{detail}</div>}</div>;
}

/* ---------- data fetch hook with loading/error/empty ---------- */
function useApi(fn, deps) {
  const [state, setState] = useState({ loading: true, error: null, data: null });
  const reload = useCallback(() => {
    let live = true; setState((s) => ({ ...s, loading: true, error: null }));
    Promise.resolve().then(fn).then((data) => { if (live) setState({ loading: false, error: null, data }); })
      .catch((e) => { if (live) setState({ loading: false, error: e, data: null }); });
    return () => { live = false; };
  }, deps);
  useEffect(reload, deps);
  return { ...state, reload };
}

/* ---------- relative time ---------- */
function timeAgo(iso) {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return s + "s ago";
  const m = Math.floor(s / 60); if (m < 60) return m + "m ago";
  const h = Math.floor(m / 60); if (h < 24) return h + "h ago";
  const d = Math.floor(h / 24); return d + "d ago";
}

Object.assign(window, {
  Icon, MetatronEmblem, MetatronCube, CountUp, Donut, Meter, Spark, KnowledgeFlow,
  Spinner, Loading, ErrorState, Empty, useApi, timeAgo,
});
