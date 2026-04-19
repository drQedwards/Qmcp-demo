import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import "@/App.css";
import axios from "axios";
import ForceGraph2D from "react-force-graph-2d";
import {
  Brain, Database, Search, Zap, Trash2, Plus, Play, Activity,
  GitBranch, Sparkles, Network, Clock, ArrowRight, ChevronRight,
  Radio, Layers, X, RefreshCw, Send, Target, Waves,
} from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;
const SESSION_ID = "default";

const RELATION_COLORS = {
  relates_to: "#64748b",
  depends_on: "#f59e0b",
  implements: "#10b981",
  references: "#3b82f6",
  similar_to: "#a855f7",
  contains: "#ec4899",
};

const TYPE_COLORS = {
  concept: "#a855f7",
  tool: "#10b981",
  task: "#f59e0b",
  memory: "#3b82f6",
  default: "#64748b",
};

function App() {
  const [status, setStatus] = useState(null);
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [silo, setSilo] = useState([]);
  const [selectedNode, setSelectedNode] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [newNode, setNewNode] = useState({ type: "concept", label: "", content: "" });
  const [newKV, setNewKV] = useState({ key: "", value: "" });
  const [pruneThreshold, setPruneThreshold] = useState(0.1);
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(false);
  const fgRef = useRef();

  const graphContainerRef = useRef();
  const [dims, setDims] = useState({ w: 800, h: 600 });

  useEffect(() => {
    const update = () => {
      if (graphContainerRef.current) {
        const r = graphContainerRef.current.getBoundingClientRect();
        setDims({ w: r.width, h: r.height });
      }
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  useEffect(() => {
    if (fgRef.current) fgRef.current._didFit = false;
  }, [graphData.nodes.length]);

  const showToast = (msg, kind = "ok") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 2600);
  };

  const initSession = async () => {
    await axios.post(`${API}/init`, { session_id: SESSION_ID, silo_size: 256 });
  };

  const refreshStatus = async () => {
    const r = await axios.post(`${API}/memory_status`, { session_id: SESSION_ID });
    setStatus(r.data);
  };

  const refreshGraph = async () => {
    const r = await axios.get(`${API}/graph/${SESSION_ID}`);
    const nodes = r.data.nodes.map((n) => ({
      ...n,
      color: TYPE_COLORS[n.type] || TYPE_COLORS.default,
    }));
    const links = r.data.edges.map((e) => ({
      ...e,
      source: e.source_id,
      target: e.target_id,
      color: RELATION_COLORS[e.relation] || "#64748b",
    }));
    setGraphData({ nodes, links });
  };

  const refreshSilo = async () => {
    const r = await axios.get(`${API}/silo/${SESSION_ID}`);
    setSilo(r.data.silo);
  };

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshStatus(), refreshGraph(), refreshSilo()]);
  }, []);

  useEffect(() => {
    (async () => {
      await initSession();
      await refreshAll();
    })();
    const t = setInterval(refreshAll, 8000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, []);

  const seedDemo = async () => {
    setLoading(true);
    try {
      const r = await axios.post(`${API}/seed/${SESSION_ID}`);
      showToast(`Seeded ${r.data.seeded_nodes} nodes + ${r.data.explicit_edges} edges`);
      await refreshAll();
      setTimeout(() => fgRef.current?.zoomToFit(400, 80), 300);
    } finally {
      setLoading(false);
    }
  };

  const addNode = async (e) => {
    e.preventDefault();
    if (!newNode.label || !newNode.content) return;
    setLoading(true);
    try {
      await axios.post(`${API}/add_interlinked_context`, {
        session_id: SESSION_ID,
        items: [newNode],
        auto_link: true,
      });
      showToast(`Added node "${newNode.label}" with auto-links`);
      setNewNode({ type: "concept", label: "", content: "" });
      await refreshAll();
    } finally {
      setLoading(false);
    }
  };

  const setSilo2 = async (e) => {
    e.preventDefault();
    if (!newKV.key) return;
    await axios.post(`${API}/set`, { session_id: SESSION_ID, ...newKV });
    setNewKV({ key: "", value: "" });
    showToast(`Cached "${newKV.key}" in silo`);
    await refreshAll();
  };

  const flushSilo = async () => {
    await axios.post(`${API}/flush`, { session_id: SESSION_ID });
    showToast("Silo flushed");
    await refreshAll();
  };

  const promoteKey = async (key) => {
    await axios.post(`${API}/promote_to_long_term`, { session_id: SESSION_ID, key, node_type: "memory" });
    showToast(`Promoted "${key}" to long-term`);
    await refreshAll();
  };

  const doSearch = async (e) => {
    e?.preventDefault();
    if (!searchQuery.trim()) return;
    const r = await axios.post(`${API}/search_memory_graph`, {
      session_id: SESSION_ID,
      query: searchQuery,
      max_depth: 1,
      top_k: 5,
    });
    setSearchResults(r.data);
    // highlight top match
    if (r.data.direct?.length && fgRef.current) {
      const topId = r.data.direct[0].id;
      const node = graphData.nodes.find((n) => n.id === topId);
      if (node && node.x !== undefined) {
        fgRef.current.centerAt(node.x, node.y, 800);
        fgRef.current.zoom(3, 800);
      }
    }
  };

  const prune = async () => {
    const r = await axios.post(`${API}/prune_stale_links`, { session_id: SESSION_ID, threshold: pruneThreshold });
    showToast(`Pruned ${r.data.edges_pruned} edges, ${r.data.orphans_removed} orphans`);
    await refreshAll();
  };

  const nodeDetails = useMemo(() => {
    if (!selectedNode) return null;
    const related = graphData.links.filter(
      (l) => (l.source.id || l.source) === selectedNode.id || (l.target.id || l.target) === selectedNode.id
    );
    return { node: selectedNode, related };
  }, [selectedNode, graphData.links]);

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-slate-100 font-sans overflow-hidden">
      {/* Animated background */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,_rgba(168,85,247,0.15),_transparent_50%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_right,_rgba(16,185,129,0.12),_transparent_50%)]" />
        <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:48px_48px]" />
      </div>

      {/* Top Bar */}
      <header className="relative z-10 flex items-center justify-between px-6 py-4 border-b border-white/5 backdrop-blur-xl bg-black/20">
        <div className="flex items-center gap-3">
          <div className="relative">
            <div className="absolute inset-0 bg-purple-500 blur-xl opacity-60 animate-pulse" />
            <div className="relative w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 via-pink-500 to-orange-400 flex items-center justify-center shadow-lg">
              <Brain className="w-5 h-5 text-white" />
            </div>
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight bg-gradient-to-r from-white via-purple-200 to-pink-200 bg-clip-text text-transparent">
              PMLL Memory Graph
            </h1>
            <p className="text-[11px] text-slate-400 tracking-wider uppercase">
              Persistent Memory · Q-Promise · TF-IDF Semantic Graph
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={seedDemo}
            disabled={loading}
            data-testid="seed-button"
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 rounded-lg text-sm font-medium transition-all shadow-lg shadow-purple-900/40 disabled:opacity-50"
          >
            <Sparkles className="w-4 h-4" /> Seed Demo
          </button>
          <button
            onClick={refreshAll}
            data-testid="refresh-button"
            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 transition"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </header>

      <main className="relative z-10 grid grid-cols-12 gap-4 p-4 h-[calc(100vh-73px)]">
        {/* LEFT PANEL */}
        <aside className="col-span-3 flex flex-col gap-4 overflow-y-auto pr-1 custom-scroll">
          {/* Status card */}
          <div className="rounded-2xl p-4 bg-gradient-to-br from-white/[0.04] to-white/[0.01] border border-white/10 backdrop-blur-xl">
            <div className="flex items-center gap-2 mb-3">
              <Activity className="w-4 h-4 text-emerald-400" />
              <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-300">Session Status</h2>
              <span className="ml-auto text-[10px] text-emerald-400 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" /> LIVE
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Stat icon={<Layers className="w-3 h-3" />} label="Nodes" value={status?.long_term?.nodes ?? 0} accent="purple" />
              <Stat icon={<GitBranch className="w-3 h-3" />} label="Edges" value={status?.long_term?.edges ?? 0} accent="pink" />
              <Stat icon={<Radio className="w-3 h-3" />} label="Silo" value={`${status?.short_term?.size ?? 0}/${status?.short_term?.capacity ?? 0}`} accent="emerald" />
              <Stat icon={<Target className="w-3 h-3" />} label="Hits" value={status?.short_term?.stats?.hits ?? 0} accent="amber" />
            </div>
          </div>

          {/* Semantic Search */}
          <div className="rounded-2xl p-4 bg-gradient-to-br from-white/[0.04] to-white/[0.01] border border-white/10 backdrop-blur-xl">
            <div className="flex items-center gap-2 mb-3">
              <Search className="w-4 h-4 text-purple-400" />
              <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-300">Semantic Search</h2>
            </div>
            <form onSubmit={doSearch} className="flex gap-2">
              <input
                data-testid="search-input"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="e.g. temporal decay"
                className="flex-1 bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500/50 transition"
              />
              <button
                data-testid="search-button"
                type="submit"
                className="px-3 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 transition text-sm flex items-center gap-1"
              >
                <Zap className="w-4 h-4" />
              </button>
            </form>
            {searchResults && (
              <div className="mt-3 space-y-1.5 max-h-64 overflow-y-auto custom-scroll">
                {searchResults.direct?.map((r) => (
                  <ResultItem key={r.id} r={r} onClick={() => setSelectedNode(r)} kind="direct" />
                ))}
                {searchResults.neighbors?.map((r) => (
                  <ResultItem key={r.id + "-n"} r={r} onClick={() => setSelectedNode(r)} kind="neighbor" />
                ))}
                {!searchResults.direct?.length && !searchResults.neighbors?.length && (
                  <p className="text-xs text-slate-500 italic">No matches — try seeding demo data.</p>
                )}
              </div>
            )}
          </div>

          {/* Add Node */}
          <div className="rounded-2xl p-4 bg-gradient-to-br from-white/[0.04] to-white/[0.01] border border-white/10 backdrop-blur-xl">
            <div className="flex items-center gap-2 mb-3">
              <Plus className="w-4 h-4 text-emerald-400" />
              <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-300">Add Memory Node</h2>
            </div>
            <form onSubmit={addNode} className="space-y-2">
              <div className="flex gap-2">
                <select
                  data-testid="node-type-select"
                  value={newNode.type}
                  onChange={(e) => setNewNode({ ...newNode, type: e.target.value })}
                  className="bg-black/30 border border-white/10 rounded-lg px-2 py-2 text-xs focus:outline-none"
                >
                  <option value="concept">concept</option>
                  <option value="tool">tool</option>
                  <option value="task">task</option>
                  <option value="memory">memory</option>
                </select>
                <input
                  data-testid="node-label-input"
                  value={newNode.label}
                  onChange={(e) => setNewNode({ ...newNode, label: e.target.value })}
                  placeholder="Label"
                  className="flex-1 bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500/50"
                />
              </div>
              <textarea
                data-testid="node-content-input"
                value={newNode.content}
                onChange={(e) => setNewNode({ ...newNode, content: e.target.value })}
                placeholder="Content (used for TF-IDF auto-linking)"
                rows={3}
                className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500/50 resize-none"
              />
              <button
                data-testid="add-node-button"
                type="submit"
                disabled={loading}
                className="w-full py-2 rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 transition text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-50"
              >
                <Sparkles className="w-4 h-4" /> Add + Auto-Link
              </button>
            </form>
          </div>

          {/* Prune */}
          <div className="rounded-2xl p-4 bg-gradient-to-br from-white/[0.04] to-white/[0.01] border border-white/10 backdrop-blur-xl">
            <div className="flex items-center gap-2 mb-3">
              <Waves className="w-4 h-4 text-amber-400" />
              <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-300">Temporal Decay · Prune</h2>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">Threshold</span>
                <span className="font-mono text-amber-300">{pruneThreshold.toFixed(2)}</span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={pruneThreshold}
                onChange={(e) => setPruneThreshold(parseFloat(e.target.value))}
                className="w-full accent-amber-500"
              />
              <button
                onClick={prune}
                data-testid="prune-button"
                className="w-full py-2 rounded-lg bg-amber-600/80 hover:bg-amber-500 transition text-sm font-medium flex items-center justify-center gap-2"
              >
                <Trash2 className="w-4 h-4" /> Prune Stale Links
              </button>
            </div>
          </div>
        </aside>

        {/* CENTER: Graph */}
        <section ref={graphContainerRef} className="col-span-6 rounded-2xl border border-white/10 bg-black/30 backdrop-blur-xl relative overflow-hidden">
          <div className="absolute top-3 left-3 z-10 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-black/60 border border-white/10">
            <Network className="w-4 h-4 text-purple-400" />
            <span className="text-xs font-medium">Memory Graph</span>
            <span className="text-[10px] text-slate-400">· {graphData.nodes.length}n / {graphData.links.length}e</span>
          </div>
          <div className="absolute top-3 right-3 z-10 flex flex-col gap-1 p-2 rounded-lg bg-black/60 border border-white/10 text-[10px]">
            {Object.entries(RELATION_COLORS).map(([k, v]) => (
              <div key={k} className="flex items-center gap-2">
                <span className="inline-block w-3 h-0.5" style={{ background: v }} />
                <span className="text-slate-300">{k}</span>
              </div>
            ))}
          </div>
          {graphData.nodes.length === 0 ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-8">
              <div className="relative mb-6">
                <div className="absolute inset-0 bg-purple-500 blur-3xl opacity-30" />
                <Brain className="relative w-20 h-20 text-purple-400" />
              </div>
              <h3 className="text-xl font-semibold mb-2">Empty Memory Graph</h3>
              <p className="text-sm text-slate-400 mb-4 max-w-sm">
                Seed with demo data or add your own nodes to watch TF-IDF auto-link them with cosine similarity ≥ 0.72
              </p>
              <button
                onClick={seedDemo}
                className="px-5 py-2.5 bg-gradient-to-r from-purple-600 to-pink-600 rounded-lg text-sm font-medium flex items-center gap-2 shadow-lg shadow-purple-900/40"
              >
                <Sparkles className="w-4 h-4" /> Seed Demo Graph
              </button>
            </div>
          ) : (
            <ForceGraph2D
              ref={fgRef}
              width={dims.w}
              height={dims.h}
              graphData={graphData}
              backgroundColor="transparent"
              nodeLabel={(n) => `${n.label} (${n.type})`}
              nodeRelSize={6}
              nodeVal={(n) => 1 + Math.log1p(n.access_count || 1) * 2}
              linkColor={(l) => l.color}
              linkWidth={(l) => 0.5 + (l.decayed_weight || l.weight) * 2.5}
              linkDirectionalParticles={(l) => (l.decayed_weight > 0.3 ? 2 : 0)}
              linkDirectionalParticleWidth={2}
              linkDirectionalParticleColor={(l) => l.color}
              onNodeClick={(node) => {
                setSelectedNode(node);
                fgRef.current?.centerAt(node.x, node.y, 500);
                fgRef.current?.zoom(2.5, 500);
              }}
              nodeCanvasObject={(node, ctx, globalScale) => {
                if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) return;
                const r = 5 + Math.log1p(node.access_count || 1) * 1.5;
                // glow
                const grd = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, r * 3);
                grd.addColorStop(0, node.color + "cc");
                grd.addColorStop(1, node.color + "00");
                ctx.fillStyle = grd;
                ctx.beginPath();
                ctx.arc(node.x, node.y, r * 3, 0, 2 * Math.PI);
                ctx.fill();
                // core
                ctx.beginPath();
                ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
                ctx.fillStyle = node.color;
                ctx.strokeStyle = "#fff";
                ctx.lineWidth = selectedNode?.id === node.id ? 2 : 0.5;
                ctx.fill();
                ctx.stroke();
                // label
                if (globalScale > 1.2) {
                  ctx.font = `${11 / globalScale + 3}px Inter, sans-serif`;
                  ctx.fillStyle = "#e2e8f0";
                  ctx.textAlign = "center";
                  ctx.fillText(node.label, node.x, node.y + r + 10);
                }
              }}
              cooldownTicks={100}
              warmupTicks={50}
              d3AlphaDecay={0.03}
              d3VelocityDecay={0.3}
              onEngineTick={() => {
                if (fgRef.current && graphData.nodes.length > 0 && !fgRef.current._didFit) {
                  fgRef.current._didFit = true;
                  setTimeout(() => fgRef.current?.zoomToFit(600, 80), 100);
                }
              }}
              onEngineStop={() => fgRef.current?.zoomToFit(400, 60)}
            />
          )}
        </section>

        {/* RIGHT PANEL */}
        <aside className="col-span-3 flex flex-col gap-4 overflow-y-auto pl-1 custom-scroll">
          {/* Node detail */}
          <div className="rounded-2xl p-4 bg-gradient-to-br from-white/[0.04] to-white/[0.01] border border-white/10 backdrop-blur-xl min-h-[200px]">
            <div className="flex items-center gap-2 mb-3">
              <Target className="w-4 h-4 text-pink-400" />
              <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-300">Node Inspector</h2>
              {selectedNode && (
                <button onClick={() => setSelectedNode(null)} className="ml-auto p-1 rounded hover:bg-white/10">
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
            {selectedNode ? (
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: TYPE_COLORS[selectedNode.type] || TYPE_COLORS.default }} />
                  <span className="text-[10px] uppercase tracking-wider text-slate-400">{selectedNode.type}</span>
                </div>
                <h3 className="text-base font-semibold mb-2">{selectedNode.label}</h3>
                <p className="text-xs text-slate-300 leading-relaxed mb-3">{selectedNode.content}</p>
                <div className="text-[10px] text-slate-500 font-mono mb-3">id: {selectedNode.id?.slice(0, 8)}…</div>
                {nodeDetails?.related?.length > 0 && (
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1.5">Connections ({nodeDetails.related.length})</div>
                    <div className="space-y-1 max-h-40 overflow-y-auto custom-scroll">
                      {nodeDetails.related.map((l, i) => {
                        const otherId = (l.source.id || l.source) === selectedNode.id ? (l.target.id || l.target) : (l.source.id || l.source);
                        const other = graphData.nodes.find((n) => n.id === otherId);
                        return (
                          <div key={i} onClick={() => other && setSelectedNode(other)} className="flex items-center gap-2 text-xs p-1.5 rounded hover:bg-white/5 cursor-pointer">
                            <span className="inline-block w-2 h-0.5" style={{ background: l.color }} />
                            <span className="text-slate-400 text-[10px]">{l.relation}</span>
                            <ArrowRight className="w-3 h-3 text-slate-500" />
                            <span className="truncate flex-1">{other?.label || otherId.slice(0, 6)}</span>
                            <span className="font-mono text-[10px] text-slate-500">{(l.decayed_weight || l.weight).toFixed(2)}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-xs text-slate-500 italic text-center py-6">
                Click any node in the graph to inspect its content and connections.
              </div>
            )}
          </div>

          {/* Silo */}
          <div className="rounded-2xl p-4 bg-gradient-to-br from-white/[0.04] to-white/[0.01] border border-white/10 backdrop-blur-xl">
            <div className="flex items-center gap-2 mb-3">
              <Database className="w-4 h-4 text-blue-400" />
              <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-300">Short-Term Silo</h2>
              <button onClick={flushSilo} data-testid="flush-button" className="ml-auto text-[10px] px-2 py-1 rounded bg-red-500/20 hover:bg-red-500/40 text-red-300 transition">
                Flush
              </button>
            </div>
            <form onSubmit={setSilo2} className="flex gap-1 mb-3">
              <input
                data-testid="silo-key-input"
                value={newKV.key}
                onChange={(e) => setNewKV({ ...newKV, key: e.target.value })}
                placeholder="key"
                className="w-20 bg-black/30 border border-white/10 rounded px-2 py-1.5 text-xs focus:outline-none focus:border-blue-500/50"
              />
              <input
                data-testid="silo-value-input"
                value={newKV.value}
                onChange={(e) => setNewKV({ ...newKV, value: e.target.value })}
                placeholder="value"
                className="flex-1 bg-black/30 border border-white/10 rounded px-2 py-1.5 text-xs focus:outline-none focus:border-blue-500/50"
              />
              <button data-testid="silo-set-button" className="px-2 rounded bg-blue-600 hover:bg-blue-500 transition">
                <Send className="w-3 h-3" />
              </button>
            </form>
            <div className="space-y-1 max-h-48 overflow-y-auto custom-scroll">
              {silo.length === 0 ? (
                <p className="text-xs text-slate-500 italic text-center py-3">Empty silo</p>
              ) : (
                silo.map((item) => (
                  <div key={item.key} className="flex items-center gap-2 p-2 rounded bg-black/20 hover:bg-black/40 transition">
                    <span className="text-[11px] font-mono text-blue-300 truncate max-w-[60px]">{item.key}</span>
                    <span className="text-[11px] text-slate-300 truncate flex-1">{item.value}</span>
                    <span className="text-[9px] text-slate-500">×{item.access}</span>
                    <button onClick={() => promoteKey(item.key)} title="Promote to long-term" className="p-1 rounded hover:bg-purple-500/30 text-purple-300">
                      <ChevronRight className="w-3 h-3" />
                    </button>
                  </div>
                ))
              )}
            </div>
            <div className="mt-2 pt-2 border-t border-white/5 flex justify-between text-[10px] text-slate-400">
              <span>Hits: <span className="text-emerald-400 font-mono">{status?.short_term?.stats?.hits ?? 0}</span></span>
              <span>Misses: <span className="text-red-400 font-mono">{status?.short_term?.stats?.misses ?? 0}</span></span>
              <span>Sets: <span className="text-blue-400 font-mono">{status?.short_term?.stats?.sets ?? 0}</span></span>
            </div>
          </div>

          {/* Legend */}
          <div className="rounded-2xl p-4 bg-gradient-to-br from-white/[0.04] to-white/[0.01] border border-white/10 backdrop-blur-xl">
            <div className="flex items-center gap-2 mb-3">
              <Clock className="w-4 h-4 text-slate-400" />
              <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-300">Node Types</h2>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(TYPE_COLORS).filter(([k]) => k !== "default").map(([k, v]) => (
                <div key={k} className="flex items-center gap-2 text-xs">
                  <span className="inline-block w-3 h-3 rounded-full" style={{ background: v }} />
                  <span className="text-slate-300">{k}</span>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </main>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-xl bg-black/80 border border-white/10 backdrop-blur-xl text-sm shadow-2xl flex items-center gap-2 animate-fade-in">
          <Sparkles className="w-4 h-4 text-purple-400" />
          {toast.msg}
        </div>
      )}
    </div>
  );
}

function Stat({ icon, label, value, accent }) {
  const colors = {
    purple: "from-purple-500/20 to-purple-500/5 text-purple-300",
    pink: "from-pink-500/20 to-pink-500/5 text-pink-300",
    emerald: "from-emerald-500/20 to-emerald-500/5 text-emerald-300",
    amber: "from-amber-500/20 to-amber-500/5 text-amber-300",
  };
  return (
    <div className={`rounded-lg p-2.5 bg-gradient-to-br ${colors[accent]} border border-white/5`}>
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider opacity-80">
        {icon} {label}
      </div>
      <div className="text-lg font-bold font-mono mt-0.5">{value}</div>
    </div>
  );
}

function ResultItem({ r, onClick, kind }) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left p-2 rounded-lg bg-black/30 hover:bg-black/50 border border-white/5 transition group"
    >
      <div className="flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: TYPE_COLORS[r.type] || TYPE_COLORS.default }} />
        <span className="text-xs font-medium truncate flex-1">{r.label}</span>
        <span className={`text-[9px] px-1.5 py-0.5 rounded font-mono ${kind === "direct" ? "bg-purple-500/20 text-purple-300" : "bg-blue-500/20 text-blue-300"}`}>
          {r.score?.toFixed(2)}
        </span>
      </div>
      {kind === "neighbor" && (
        <div className="text-[10px] text-slate-500 mt-0.5">via {r.via} · depth {r.depth}</div>
      )}
    </button>
  );
}

export default App;
