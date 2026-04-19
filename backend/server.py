from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import math
import logging
import asyncio
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone
from collections import OrderedDict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="PMLL Memory Graph")
api_router = APIRouter(prefix="/api")

# ---------------- In-Memory Short-Term Silo ----------------
# Per-session KV store (LRU) + Q-promise chain registry
SESSIONS: Dict[str, Dict[str, Any]] = {}
DECAY_LAMBDA = 0.05  # per hour decay rate
AUTO_LINK_THRESHOLD = 0.72


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_session(session_id: str, silo_size: int = 256):
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "silo": OrderedDict(),
            "silo_size": silo_size,
            "promises": {},
            "created_at": _now_iso(),
            "stats": {"peeks": 0, "hits": 0, "misses": 0, "sets": 0},
        }
    return SESSIONS[session_id]


def _silo_set(session_id: str, key: str, value: str):
    s = _ensure_session(session_id)
    silo = s["silo"]
    if key in silo:
        silo.move_to_end(key)
    silo[key] = {"value": value, "ts": _now_iso(), "access": 1}
    while len(silo) > s["silo_size"]:
        silo.popitem(last=False)
    s["stats"]["sets"] += 1


def _silo_peek(session_id: str, key: str):
    s = _ensure_session(session_id)
    s["stats"]["peeks"] += 1
    if key in s["silo"]:
        s["silo"][key]["access"] += 1
        s["silo"].move_to_end(key)
        s["stats"]["hits"] += 1
        return s["silo"][key]
    s["stats"]["misses"] += 1
    return None


# ---------------- TF-IDF Embedding Layer ----------------
class TfIdfIndex:
    """Recomputes TF-IDF matrix on demand. Cheap for small N."""

    def __init__(self):
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.matrix = None
        self.node_ids: List[str] = []

    def fit(self, nodes: List[Dict[str, Any]]):
        if not nodes:
            self.vectorizer = None
            self.matrix = None
            self.node_ids = []
            return
        texts = [f"{n.get('label','')} {n.get('content','')}" for n in nodes]
        self.vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), max_features=4096, stop_words="english")
        try:
            self.matrix = self.vectorizer.fit_transform(texts)
        except ValueError:
            # Empty vocab fallback
            self.vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 1), max_features=4096)
            self.matrix = self.vectorizer.fit_transform(texts)
        self.node_ids = [n["id"] for n in nodes]

    def query(self, text: str, top_k: int = 5):
        if self.vectorizer is None or self.matrix is None or not self.node_ids:
            return []
        vec = self.vectorizer.transform([text])
        sims = cosine_similarity(vec, self.matrix)[0]
        order = np.argsort(-sims)[:top_k]
        return [(self.node_ids[i], float(sims[i])) for i in order if sims[i] > 0]

    def pairwise(self):
        if self.matrix is None:
            return None
        return cosine_similarity(self.matrix)


async def _load_nodes(session_id: str) -> List[Dict[str, Any]]:
    cursor = db.memory_nodes.find({"session_id": session_id}, {"_id": 0})
    return await cursor.to_list(length=10000)


async def _load_edges(session_id: str) -> List[Dict[str, Any]]:
    cursor = db.memory_edges.find({"session_id": session_id}, {"_id": 0})
    return await cursor.to_list(length=50000)


async def _build_index(session_id: str) -> (TfIdfIndex, List[Dict[str, Any]]):
    nodes = await _load_nodes(session_id)
    idx = TfIdfIndex()
    idx.fit(nodes)
    return idx, nodes


def _hours_since(iso_ts: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return delta.total_seconds() / 3600.0
    except Exception:
        return 0.0


def _decay(weight: float, iso_ts: str) -> float:
    h = _hours_since(iso_ts)
    return float(weight) * math.exp(-DECAY_LAMBDA * h)


# ---------------- Pydantic Schemas ----------------
class InitReq(BaseModel):
    session_id: str
    silo_size: int = 256


class PeekReq(BaseModel):
    session_id: str
    key: str


class SetReq(BaseModel):
    session_id: str
    key: str
    value: str


class ResolveReq(BaseModel):
    session_id: str
    promise_id: str


class FlushReq(BaseModel):
    session_id: str


class GraphQLReq(BaseModel):
    query: str
    variables: Optional[Dict[str, Any]] = None
    operationName: Optional[str] = None


class UpsertNodeReq(BaseModel):
    session_id: str
    type: str
    label: str
    content: str
    metadata: Optional[Dict[str, Any]] = None
    id: Optional[str] = None


class RelationReq(BaseModel):
    session_id: str
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0
    metadata: Optional[Dict[str, Any]] = None


class SearchReq(BaseModel):
    session_id: str
    query: str
    max_depth: int = 1
    top_k: int = 5
    edge_filter: Optional[str] = None


class PruneReq(BaseModel):
    session_id: str
    threshold: float = 0.1


class BulkItem(BaseModel):
    type: str
    label: str
    content: str
    metadata: Optional[Dict[str, Any]] = None


class BulkReq(BaseModel):
    session_id: str
    items: List[BulkItem]
    auto_link: bool = True


class TraverseReq(BaseModel):
    session_id: str
    start_node_id: str
    max_depth: int = 2
    edge_filter: Optional[str] = None


class ResolveCtxReq(BaseModel):
    session_id: str
    key: str


class PromoteReq(BaseModel):
    session_id: str
    key: str
    value: Optional[str] = None
    node_type: str = "memory"
    metadata: Optional[Dict[str, Any]] = None


class StatusReq(BaseModel):
    session_id: str


VALID_RELATIONS = {"relates_to", "depends_on", "implements", "references", "similar_to", "contains"}


# ---------------- Endpoints ----------------
@api_router.get("/")
async def root():
    return {"service": "pmll-memory-graph", "ok": True}


@api_router.post("/init")
async def mcp_init(req: InitReq):
    s = _ensure_session(req.session_id, req.silo_size)
    return {
        "session_id": req.session_id,
        "silo_size": s["silo_size"],
        "created_at": s["created_at"],
        "status": "initialized",
    }


@api_router.post("/peek")
async def mcp_peek(req: PeekReq):
    entry = _silo_peek(req.session_id, req.key)
    if entry is None:
        return {"hit": False, "key": req.key}
    return {"hit": True, "key": req.key, "value": entry["value"], "ts": entry["ts"], "access": entry["access"]}


@api_router.post("/set")
async def mcp_set(req: SetReq):
    _silo_set(req.session_id, req.key, req.value)
    return {"ok": True, "key": req.key}


@api_router.post("/resolve")
async def mcp_resolve(req: ResolveReq):
    s = _ensure_session(req.session_id)
    p = s["promises"].get(req.promise_id)
    if not p:
        # lazily create
        p = {"id": req.promise_id, "status": "pending", "created_at": _now_iso()}
        s["promises"][req.promise_id] = p
    return p


@api_router.post("/flush")
async def mcp_flush(req: FlushReq):
    if req.session_id in SESSIONS:
        SESSIONS[req.session_id]["silo"].clear()
        SESSIONS[req.session_id]["promises"].clear()
    return {"ok": True, "flushed": True}


@api_router.post("/upsert_memory_node")
async def upsert_node(req: UpsertNodeReq):
    nid = req.id or str(uuid.uuid4())
    doc = {
        "id": nid,
        "session_id": req.session_id,
        "type": req.type,
        "label": req.label,
        "content": req.content,
        "metadata": req.metadata or {},
        "updated_at": _now_iso(),
        "access_count": 1,
    }
    existing = await db.memory_nodes.find_one({"id": nid, "session_id": req.session_id})
    if existing:
        doc["created_at"] = existing.get("created_at", _now_iso())
        doc["access_count"] = existing.get("access_count", 0) + 1
        await db.memory_nodes.update_one({"id": nid, "session_id": req.session_id}, {"$set": doc})
    else:
        doc["created_at"] = _now_iso()
        await db.memory_nodes.insert_one(doc.copy())
    return {"id": nid, "label": req.label, "type": req.type}


@api_router.post("/create_relation")
async def create_relation(req: RelationReq):
    if req.relation not in VALID_RELATIONS:
        raise HTTPException(400, f"relation must be one of {sorted(VALID_RELATIONS)}")
    eid = str(uuid.uuid4())
    doc = {
        "id": eid,
        "session_id": req.session_id,
        "source_id": req.source_id,
        "target_id": req.target_id,
        "relation": req.relation,
        "weight": float(req.weight),
        "metadata": req.metadata or {},
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.memory_edges.insert_one(doc.copy())
    return {"id": eid, "source_id": req.source_id, "target_id": req.target_id, "relation": req.relation, "weight": doc["weight"]}


@api_router.post("/search_memory_graph")
async def search_graph(req: SearchReq):
    idx, nodes = await _build_index(req.session_id)
    matches = idx.query(req.query, top_k=req.top_k)
    node_map = {n["id"]: n for n in nodes}
    edges = await _load_edges(req.session_id)
    if req.edge_filter:
        edges = [e for e in edges if e["relation"] == req.edge_filter]

    # adjacency
    adj: Dict[str, List[Dict[str, Any]]] = {}
    for e in edges:
        adj.setdefault(e["source_id"], []).append(e)
        adj.setdefault(e["target_id"], []).append(e)

    direct = []
    visited = set()
    neighbors = []
    for nid, score in matches:
        if nid not in node_map:
            continue
        direct.append({**node_map[nid], "score": score, "source": "semantic"})
        visited.add(nid)

    # BFS walk
    frontier = [(nid, 0) for nid, _ in matches]
    while frontier:
        cur, depth = frontier.pop(0)
        if depth >= req.max_depth:
            continue
        for e in adj.get(cur, []):
            other = e["target_id"] if e["source_id"] == cur else e["source_id"]
            if other in visited or other not in node_map:
                continue
            visited.add(other)
            decayed = _decay(e["weight"], e.get("updated_at", e.get("created_at", _now_iso())))
            neighbors.append({
                **node_map[other],
                "score": decayed / (depth + 1),
                "source": "graph",
                "depth": depth + 1,
                "via": e["relation"],
            })
            frontier.append((other, depth + 1))

    return {"direct": direct, "neighbors": neighbors, "total": len(direct) + len(neighbors)}


@api_router.post("/prune_stale_links")
async def prune_links(req: PruneReq):
    edges = await _load_edges(req.session_id)
    to_remove = []
    kept = 0
    for e in edges:
        decayed = _decay(e["weight"], e.get("updated_at", e.get("created_at", _now_iso())))
        if decayed < req.threshold:
            to_remove.append(e["id"])
        else:
            kept += 1
    if to_remove:
        await db.memory_edges.delete_many({"id": {"$in": to_remove}, "session_id": req.session_id})

    # orphan pruning: nodes with access_count<=1 and no edges
    nodes = await _load_nodes(req.session_id)
    remaining_edges = await _load_edges(req.session_id)
    connected = set()
    for e in remaining_edges:
        connected.add(e["source_id"])
        connected.add(e["target_id"])
    orphans = [n["id"] for n in nodes if n["id"] not in connected and n.get("access_count", 1) <= 1]
    if orphans:
        await db.memory_nodes.delete_many({"id": {"$in": orphans}, "session_id": req.session_id})
    return {"edges_pruned": len(to_remove), "edges_kept": kept, "orphans_removed": len(orphans)}


@api_router.post("/add_interlinked_context")
async def add_bulk(req: BulkReq):
    # insert all first
    inserted_ids = []
    for it in req.items:
        nid = str(uuid.uuid4())
        doc = {
            "id": nid,
            "session_id": req.session_id,
            "type": it.type,
            "label": it.label,
            "content": it.content,
            "metadata": it.metadata or {},
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "access_count": 1,
        }
        await db.memory_nodes.insert_one(doc.copy())
        inserted_ids.append(nid)

    auto_edges = 0
    if req.auto_link and len(inserted_ids) >= 2:
        # Build index over ALL nodes in session
        idx, nodes = await _build_index(req.session_id)
        sim = idx.pairwise()
        if sim is not None:
            id_to_pos = {nid: i for i, nid in enumerate(idx.node_ids)}
            for nid in inserted_ids:
                if nid not in id_to_pos:
                    continue
                i = id_to_pos[nid]
                for j, other_id in enumerate(idx.node_ids):
                    if other_id == nid:
                        continue
                    s = float(sim[i][j])
                    if s >= AUTO_LINK_THRESHOLD:
                        # avoid dup edges between same pair same relation
                        existing = await db.memory_edges.find_one({
                            "session_id": req.session_id,
                            "source_id": nid,
                            "target_id": other_id,
                            "relation": "similar_to",
                        })
                        if existing:
                            continue
                        eid = str(uuid.uuid4())
                        edoc = {
                            "id": eid,
                            "session_id": req.session_id,
                            "source_id": nid,
                            "target_id": other_id,
                            "relation": "similar_to",
                            "weight": round(s, 4),
                            "metadata": {"auto": True},
                            "created_at": _now_iso(),
                            "updated_at": _now_iso(),
                        }
                        await db.memory_edges.insert_one(edoc.copy())
                        auto_edges += 1
    return {"inserted": len(inserted_ids), "node_ids": inserted_ids, "auto_edges": auto_edges}


@api_router.post("/retrieve_with_traversal")
async def traverse(req: TraverseReq):
    edges = await _load_edges(req.session_id)
    if req.edge_filter:
        edges = [e for e in edges if e["relation"] == req.edge_filter]
    nodes = await _load_nodes(req.session_id)
    node_map = {n["id"]: n for n in nodes}
    adj: Dict[str, List[Dict[str, Any]]] = {}
    for e in edges:
        adj.setdefault(e["source_id"], []).append(e)
        adj.setdefault(e["target_id"], []).append(e)

    if req.start_node_id not in node_map:
        raise HTTPException(404, "start_node_id not found")

    results = []
    visited = {req.start_node_id}
    frontier = [(req.start_node_id, 0, 1.0)]
    while frontier:
        cur, depth, path_score = frontier.pop(0)
        if depth >= req.max_depth:
            continue
        for e in adj.get(cur, []):
            other = e["target_id"] if e["source_id"] == cur else e["source_id"]
            if other in visited or other not in node_map:
                continue
            visited.add(other)
            decayed = _decay(e["weight"], e.get("updated_at", e.get("created_at", _now_iso())))
            score = path_score * decayed / (depth + 1)
            results.append({**node_map[other], "depth": depth + 1, "score": score, "via": e["relation"]})
            frontier.append((other, depth + 1, score))
    results.sort(key=lambda x: -x["score"])
    return {"start": node_map[req.start_node_id], "reachable": results}


@api_router.post("/resolve_context")
async def resolve_context(req: ResolveCtxReq):
    # 1) short-term
    entry = _silo_peek(req.session_id, req.key)
    if entry is not None:
        return {"source": "short_term", "score": 1.0, "key": req.key, "value": entry["value"], "ts": entry["ts"]}
    # 2) long-term semantic
    idx, nodes = await _build_index(req.session_id)
    matches = idx.query(req.key, top_k=3)
    if matches:
        node_map = {n["id"]: n for n in nodes}
        top_id, top_score = matches[0]
        if top_score >= 0.1:
            return {"source": "long_term", "score": top_score, "node": node_map[top_id]}
    return {"source": "miss", "score": 0.0, "key": req.key}


@api_router.post("/promote_to_long_term")
async def promote(req: PromoteReq):
    value = req.value
    if value is None:
        entry = _silo_peek(req.session_id, req.key)
        if entry is None:
            raise HTTPException(404, "key not in short-term silo and no value provided")
        value = entry["value"]
    nid = str(uuid.uuid4())
    doc = {
        "id": nid,
        "session_id": req.session_id,
        "type": req.node_type,
        "label": req.key,
        "content": value,
        "metadata": {**(req.metadata or {}), "promoted_from": "short_term"},
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "access_count": 1,
    }
    await db.memory_nodes.insert_one(doc.copy())
    return {"id": nid, "label": req.key, "promoted": True}


@api_router.post("/memory_status")
async def memory_status(req: StatusReq):
    s = _ensure_session(req.session_id)
    node_count = await db.memory_nodes.count_documents({"session_id": req.session_id})
    edge_count = await db.memory_edges.count_documents({"session_id": req.session_id})
    return {
        "session_id": req.session_id,
        "short_term": {
            "size": len(s["silo"]),
            "capacity": s["silo_size"],
            "stats": s["stats"],
            "promises": len(s["promises"]),
        },
        "long_term": {
            "nodes": node_count,
            "edges": edge_count,
        },
        "created_at": s["created_at"],
    }


@api_router.get("/graph/{session_id}")
async def get_graph(session_id: str):
    nodes = await _load_nodes(session_id)
    edges = await _load_edges(session_id)
    # attach decayed weight for visualization
    for e in edges:
        e["decayed_weight"] = _decay(e["weight"], e.get("updated_at", e.get("created_at", _now_iso())))
    return {"nodes": nodes, "edges": edges}


@api_router.get("/silo/{session_id}")
async def get_silo(session_id: str):
    s = _ensure_session(session_id)
    items = [{"key": k, **v} for k, v in s["silo"].items()]
    return {"silo": items, "size": len(items), "capacity": s["silo_size"]}


# ---------------- Minimal GraphQL dispatcher ----------------
@api_router.post("/graphql")
async def graphql_handler(req: GraphQLReq):
    """Very lightweight GraphQL-ish dispatcher.
    Supports operations:
      - nodes(session_id) { id label type content }
      - edges(session_id) { id source_id target_id relation weight }
      - node(session_id, id)
      - search(session_id, query, top_k)
    """
    q = req.query.strip()
    v = req.variables or {}
    sid = v.get("session_id") or v.get("sessionId")
    if "nodes" in q and "edges" not in q:
        nodes = await _load_nodes(sid) if sid else []
        return {"data": {"nodes": nodes}}
    if "edges" in q and "nodes" not in q:
        edges = await _load_edges(sid) if sid else []
        return {"data": {"edges": edges}}
    if "graph" in q:
        nodes = await _load_nodes(sid) if sid else []
        edges = await _load_edges(sid) if sid else []
        return {"data": {"graph": {"nodes": nodes, "edges": edges}}}
    if "search" in q:
        query = v.get("query", "")
        top_k = int(v.get("top_k", 5))
        if not sid:
            return {"data": None, "errors": [{"message": "session_id required"}]}
        idx, nodes = await _build_index(sid)
        matches = idx.query(query, top_k=top_k)
        node_map = {n["id"]: n for n in nodes}
        return {"data": {"search": [{**node_map[nid], "score": s} for nid, s in matches if nid in node_map]}}
    return {"data": None, "errors": [{"message": "unsupported query (supports nodes, edges, graph, search)"}]}


# ---------------- Seed Endpoint for quick demo ----------------
@api_router.post("/seed/{session_id}")
async def seed_demo(session_id: str):
    """Populate with a rich demo graph for instant wow."""
    # clear first
    await db.memory_nodes.delete_many({"session_id": session_id})
    await db.memory_edges.delete_many({"session_id": session_id})

    demo = [
        {"type": "concept", "label": "PMLL", "content": "Persistent Memory Lookup Layer — silo for short-term key-value cache with Q-promise chains"},
        {"type": "concept", "label": "Q-Promise", "content": "Deferred continuation primitive for async lookups and pipelined MCP tool calls"},
        {"type": "concept", "label": "TF-IDF Embedding", "content": "Term frequency inverse document frequency vectorization for semantic similarity without LLM embeddings"},
        {"type": "concept", "label": "Cosine Similarity", "content": "Normalized dot product between two vectors measuring semantic closeness between documents"},
        {"type": "concept", "label": "Graph Traversal", "content": "BFS walk across typed edges depends_on implements references with temporal decay scoring"},
        {"type": "concept", "label": "Temporal Decay", "content": "Edge weight decay function e^(-lambda*t) used to prune stale memory links over time"},
        {"type": "tool", "label": "MCP Server", "content": "Model Context Protocol server exposing memory tools peek set resolve flush to LLM clients"},
        {"type": "tool", "label": "MongoDB", "content": "Document store for long-term memory nodes edges with TF-IDF embeddings metadata"},
        {"type": "tool", "label": "FastAPI", "content": "Python async web framework powering the memory graph REST API endpoints"},
        {"type": "task", "label": "Prune Stale Links", "content": "Remove edges below decay threshold and orphan nodes with low access count"},
        {"type": "task", "label": "Promote to Long Term", "content": "Transfer short-term silo entry to long-term memory graph as a typed node"},
        {"type": "task", "label": "Semantic Search", "content": "Query memory graph using TF-IDF cosine similarity and graph neighbor expansion"},
    ]
    inserted = []
    for it in demo:
        nid = str(uuid.uuid4())
        inserted.append(nid)
        doc = {
            "id": nid,
            "session_id": session_id,
            "type": it["type"],
            "label": it["label"],
            "content": it["content"],
            "metadata": {},
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "access_count": 1,
        }
        await db.memory_nodes.insert_one(doc.copy())

    # auto-link via TF-IDF
    idx, nodes = await _build_index(session_id)
    sim = idx.pairwise()
    if sim is not None:
        ids = idx.node_ids
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                s = float(sim[i][j])
                if s >= AUTO_LINK_THRESHOLD:
                    eid = str(uuid.uuid4())
                    await db.memory_edges.insert_one({
                        "id": eid,
                        "session_id": session_id,
                        "source_id": ids[i],
                        "target_id": ids[j],
                        "relation": "similar_to",
                        "weight": round(s, 4),
                        "metadata": {"auto": True},
                        "created_at": _now_iso(),
                        "updated_at": _now_iso(),
                    })

    # add a few explicit typed edges for richness
    by_label = {n["label"]: n["id"] for n in await _load_nodes(session_id)}
    explicit = [
        ("PMLL", "Q-Promise", "contains", 0.9),
        ("MCP Server", "PMLL", "implements", 0.85),
        ("Semantic Search", "TF-IDF Embedding", "depends_on", 0.88),
        ("Semantic Search", "Cosine Similarity", "depends_on", 0.86),
        ("Semantic Search", "Graph Traversal", "implements", 0.8),
        ("Prune Stale Links", "Temporal Decay", "depends_on", 0.92),
        ("Promote to Long Term", "PMLL", "references", 0.75),
        ("MCP Server", "FastAPI", "depends_on", 0.7),
        ("PMLL", "MongoDB", "depends_on", 0.7),
    ]
    added = 0
    for a, b, rel, w in explicit:
        if a in by_label and b in by_label:
            await db.memory_edges.insert_one({
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "source_id": by_label[a],
                "target_id": by_label[b],
                "relation": rel,
                "weight": w,
                "metadata": {"auto": False},
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            })
            added += 1

    return {"seeded_nodes": len(inserted), "explicit_edges": added}


# ---------------- Wire up ----------------
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
