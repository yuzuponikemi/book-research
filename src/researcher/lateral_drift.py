"""Lateral Vector Drifter (LVD) — discover structurally similar but semantically
orthogonal knowledge from external sources.

Pipeline node: enrich → lateral_drift → generate_reading_material

Flow:
1. Extract concepts from concept_graph
2. LLM generates lateral search queries (using book config domain_hints)
3. Web search + arXiv API search for candidates
4. Embed concepts + candidates with OllamaEmbeddings (nomic-embed-text)
5. Cosine similarity filter (0.2–0.5 "orthogonal zone") + familiarity penalty
6. Return top-N results as lateral_drifts
"""

import json
import re
import time
import xml.etree.ElementTree as ET

import httpx
import numpy as np
from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json
from src.researcher.web_search import search_batch


# ── arXiv search (by query, not by ID) ──────────────────────────────

ARXIV_SEARCH_URL = "https://export.arxiv.org/api/query"


def _search_arxiv_by_query(queries: list[str], max_results: int = 3) -> list[dict]:
    """Search arXiv API by free-text query.  Returns list of {query, title, url, snippet, source_type}."""
    results = []
    for query in queries:
        try:
            resp = httpx.get(
                ARXIV_SEARCH_URL,
                params={"search_query": f"all:{query}", "max_results": str(max_results)},
                follow_redirects=True,
                timeout=30,
            )
            resp.raise_for_status()

            ns = {"atom": "http://www.w3.org/2005/Atom"}
            root = ET.fromstring(resp.text)
            for entry in root.findall("atom:entry", ns):
                title = re.sub(r"\s+", " ", entry.findtext("atom:title", "", ns).strip())
                abstract = re.sub(r"\s+", " ", entry.findtext("atom:summary", "", ns).strip())
                link = ""
                for lnk in entry.findall("atom:link", ns):
                    if lnk.get("rel") == "alternate":
                        link = lnk.get("href", "")
                        break
                if title:
                    results.append({
                        "query": query,
                        "title": title,
                        "url": link,
                        "snippet": abstract[:500],
                        "source_type": "arxiv",
                    })
        except Exception as e:
            print(f"      [lateral/arxiv] Query failed: '{query}': {e}")

        if query != queries[-1]:
            time.sleep(0.5)

    return results


# ── Embedding helpers ────────────────────────────────────────────────

def _get_embeddings(texts: list[str], model: str = "nomic-embed-text") -> np.ndarray | None:
    """Embed texts using OllamaEmbeddings.  Returns (N, D) array or None on failure."""
    try:
        from langchain_ollama import OllamaEmbeddings
    except ImportError:
        print("      [lateral] langchain_ollama not available for embeddings")
        return None

    try:
        embedder = OllamaEmbeddings(model=model)
        vectors = embedder.embed_documents(texts)
        return np.array(vectors, dtype=np.float32)
    except Exception as e:
        print(f"      [lateral] Embedding failed (model={model}): {e}")
        print(f"      [lateral] Try: ollama pull {model}")
        return None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ── LLM lateral query generation ────────────────────────────────────

LATERAL_QUERY_PROMPT = """\
You are a creative research assistant specializing in lateral thinking and \
cross-disciplinary connections.

Given the following concepts from "{book_title}" by {author}, generate \
lateral search queries that find knowledge from DIFFERENT domains that share \
STRUCTURAL or FORMAL similarities with these concepts — but are NOT about \
the same topic.

The goal is to find surprising, non-obvious parallels. For example:
- A philosophical concept about doubt → search for fault-tolerance in distributed systems
- An argument about mind-body dualism → search for wave-particle duality in quantum physics
- A method of systematic decomposition → search for divide-and-conquer algorithms

CONCEPTS:
{concepts_text}

DOMAIN HINTS (prefer searching in these domains):
{domain_hints_text}

Generate exactly {n_queries} search queries. Each query should:
1. Target a DIFFERENT domain from the original text
2. Seek structural/formal parallels, not topical overlap
3. Be specific enough to find relevant academic or technical content

Respond in JSON format:
{{
  "queries": [
    {{"concept_id": "...", "concept_name": "...", "query": "...", "target_domain": "..."}}
  ]
}}
"""


def _generate_lateral_queries(
    concepts: list[dict],
    book_title: str,
    author: str,
    domain_hints: list[str],
    llm: ChatOllama,
    max_queries: int = 10,
) -> list[dict]:
    """Use LLM to generate lateral search queries for each concept."""
    if not concepts:
        return []

    # Limit to top concepts to avoid huge prompts
    top_concepts = concepts[:7]

    concepts_text = "\n".join(
        f"- {c.get('name', '?')} ({c.get('id', '?')}): {c.get('description', '')[:200]}"
        for c in top_concepts
    )

    domain_hints_text = ", ".join(domain_hints) if domain_hints else "any scientific or technical domain"

    n_queries = min(max_queries, len(top_concepts) * 2)

    prompt = LATERAL_QUERY_PROMPT.format(
        book_title=book_title,
        author=author,
        concepts_text=concepts_text,
        domain_hints_text=domain_hints_text,
        n_queries=n_queries,
    )

    try:
        response = llm.invoke(prompt)
        data = extract_json(response.content)
        queries = data.get("queries", [])
        # Validate structure
        valid = []
        for q in queries:
            if isinstance(q, dict) and q.get("query"):
                valid.append({
                    "concept_id": q.get("concept_id", ""),
                    "concept_name": q.get("concept_name", ""),
                    "query": q["query"],
                    "target_domain": q.get("target_domain", ""),
                })
        return valid[:max_queries]
    except Exception as e:
        print(f"      [lateral] LLM query generation failed: {e}")
        return []


# ── Scoring and filtering ───────────────────────────────────────────

def _score_and_filter(
    candidates: list[dict],
    concept_embeddings: np.ndarray,
    concept_names: list[str],
    chunk_embeddings: np.ndarray | None,
    embedding_model: str,
    sim_low: float = 0.2,
    sim_high: float = 0.5,
) -> list[dict]:
    """Score candidates against concept embeddings, filter by orthogonal zone.

    Each candidate gets:
    - similarity: cosine sim to its source concept embedding
    - familiarity: max cosine sim to any chunk embedding (penalty)
    - drift_score: similarity * (1 - familiarity) — higher = better lateral drift
    """
    if len(candidates) == 0:
        return []

    # Embed candidate snippets
    candidate_texts = [
        f"{c.get('title', '')}. {c.get('snippet', '')}" for c in candidates
    ]
    candidate_vecs = _get_embeddings(candidate_texts, model=embedding_model)
    if candidate_vecs is None:
        return []

    # Build concept name → index map
    concept_idx = {name: i for i, name in enumerate(concept_names)}

    scored = []
    for i, cand in enumerate(candidates):
        # Find the concept this candidate was queried for
        cname = cand.get("concept_name", "")
        cidx = concept_idx.get(cname)
        if cidx is None:
            # Fall back to closest concept
            sims = [_cosine_similarity(candidate_vecs[i], concept_embeddings[j])
                    for j in range(len(concept_embeddings))]
            cidx = int(np.argmax(sims))

        similarity = _cosine_similarity(candidate_vecs[i], concept_embeddings[cidx])

        # Familiarity penalty: how close is this to the original text chunks?
        familiarity = 0.0
        if chunk_embeddings is not None and len(chunk_embeddings) > 0:
            chunk_sims = [_cosine_similarity(candidate_vecs[i], chunk_embeddings[j])
                          for j in range(len(chunk_embeddings))]
            familiarity = max(chunk_sims)

        # Filter: keep candidates in the "orthogonal zone"
        if similarity < sim_low or similarity > sim_high:
            continue

        # Penalize candidates too similar to source text
        if familiarity > 0.7:
            continue

        drift_score = similarity * (1 - familiarity)

        scored.append({
            **cand,
            "similarity": round(similarity, 4),
            "familiarity": round(familiarity, 4),
            "drift_score": round(drift_score, 4),
        })

    # Sort by drift_score descending
    scored.sort(key=lambda x: x["drift_score"], reverse=True)
    return scored


# ── Pipeline node ────────────────────────────────────────────────────

def lateral_drift(state: dict) -> dict:
    """Pipeline node: generate lateral drift candidates from concept graph.

    Reads: concept_graph, raw_chunks, book_config, reader_model
    Writes: lateral_drifts, thinking_log
    """
    steps = list(state.get("thinking_log", []))
    book_config = state.get("book_config", {})
    concept_graph = state.get("concept_graph", {})
    raw_chunks = state.get("raw_chunks", [])

    book = book_config.get("book", {})
    book_title = book.get("title", state.get("book_title", ""))
    author = book.get("author", "")

    lateral_config = book_config.get("lateral", {})
    domain_hints = lateral_config.get("domain_hints", [])
    max_per_concept = lateral_config.get("max_results_per_concept", 3)
    sim_low = lateral_config.get("sim_low", 0.2)
    sim_high = lateral_config.get("sim_high", 0.5)
    embedding_model = lateral_config.get("embedding_model", "nomic-embed-text")
    include_arxiv = lateral_config.get("include_arxiv", True)

    concepts = concept_graph.get("concepts", [])
    if not concepts:
        print("      [lateral] No concepts found, skipping")
        return {"lateral_drifts": [], "thinking_log": steps}

    model = state.get("reader_model", "llama3")
    num_ctx = 32768 if "qwen3" in model or "command-r" in model else 8192
    llm = ChatOllama(model=model, temperature=0.7, format="json", num_ctx=num_ctx)

    # Step 1: Generate lateral queries
    print(f"      Generating lateral queries for {len(concepts)} concepts...")
    queries = _generate_lateral_queries(
        concepts, book_title, author, domain_hints, llm,
        max_queries=len(concepts[:7]) * 2,
    )

    steps.append(create_step(
        layer="researcher",
        node="lateral_drift",
        action="generate_queries",
        input_summary=f"{len(concepts)} concepts → {len(queries)} lateral queries",
        parsed_output={"queries": queries},
    ))

    if not queries:
        print("      [lateral] No queries generated, skipping")
        return {"lateral_drifts": [], "thinking_log": steps}

    print(f"      Generated {len(queries)} lateral queries")

    # Step 2: Search web + arXiv
    query_strings = [q["query"] for q in queries]
    print(f"      Searching web for {len(query_strings)} queries...")
    web_results = search_batch(query_strings, max_results=max_per_concept)

    # Map web results to candidates with concept info
    query_to_concept = {q["query"]: q for q in queries}
    candidates = []
    for wr in web_results:
        q_info = query_to_concept.get(wr["query"], {})
        candidates.append({
            "concept_id": q_info.get("concept_id", ""),
            "concept_name": q_info.get("concept_name", ""),
            "query": wr["query"],
            "title": wr["title"],
            "snippet": wr["body"][:500],
            "url": wr["url"],
            "source_type": "web",
            "domain": q_info.get("target_domain", ""),
        })

    # arXiv search
    if include_arxiv:
        print(f"      Searching arXiv for {len(query_strings)} queries...")
        arxiv_results = _search_arxiv_by_query(query_strings, max_results=2)
        for ar in arxiv_results:
            q_info = query_to_concept.get(ar["query"], {})
            candidates.append({
                "concept_id": q_info.get("concept_id", ""),
                "concept_name": q_info.get("concept_name", ""),
                "query": ar["query"],
                "title": ar["title"],
                "snippet": ar["snippet"],
                "url": ar["url"],
                "source_type": "arxiv",
                "domain": q_info.get("target_domain", ""),
            })

    print(f"      Found {len(candidates)} candidates total")

    steps.append(create_step(
        layer="researcher",
        node="lateral_drift",
        action="search",
        input_summary=f"{len(query_strings)} queries → {len(candidates)} candidates ({len(web_results)} web, {len(candidates) - len(web_results)} arxiv)",
        parsed_output={"candidate_count": len(candidates)},
    ))

    if not candidates:
        return {"lateral_drifts": [], "thinking_log": steps}

    # Step 3: Embed concepts
    print(f"      Embedding {len(concepts[:7])} concepts + {len(candidates)} candidates...")
    concept_texts = [
        f"{c.get('name', '')}. {c.get('description', '')}"
        for c in concepts[:7]
    ]
    concept_names = [c.get("name", "") for c in concepts[:7]]
    concept_vecs = _get_embeddings(concept_texts, model=embedding_model)

    if concept_vecs is None:
        # Graceful degradation: return unscored candidates (top N by position)
        print("      [lateral] Embedding unavailable, returning top candidates unscored")
        unscored = candidates[:max_per_concept * len(concepts[:7])]
        for c in unscored:
            c["similarity"] = 0.0
            c["familiarity"] = 0.0
            c["drift_score"] = 0.0
        return {"lateral_drifts": unscored, "thinking_log": steps}

    # Step 4: Embed chunks for familiarity penalty
    chunk_vecs = None
    if raw_chunks:
        # Embed first 500 chars of each chunk
        chunk_previews = [ch[:500] for ch in raw_chunks]
        chunk_vecs = _get_embeddings(chunk_previews, model=embedding_model)

    # Step 5: Score and filter
    print(f"      Scoring and filtering (sim range: {sim_low}-{sim_high})...")
    scored = _score_and_filter(
        candidates, concept_vecs, concept_names, chunk_vecs,
        embedding_model=embedding_model,
        sim_low=sim_low,
        sim_high=sim_high,
    )

    # Limit to max_per_concept per concept
    concept_counts: dict[str, int] = {}
    final = []
    for s in scored:
        cid = s.get("concept_id", "unknown")
        count = concept_counts.get(cid, 0)
        if count < max_per_concept:
            final.append(s)
            concept_counts[cid] = count + 1

    print(f"      Lateral drift: {len(final)} results (from {len(scored)} scored)")

    steps.append(create_step(
        layer="researcher",
        node="lateral_drift",
        action="score_and_filter",
        input_summary=f"{len(candidates)} candidates → {len(scored)} scored → {len(final)} final",
        parsed_output={
            "scored_count": len(scored),
            "final_count": len(final),
            "top_drift_scores": [s["drift_score"] for s in final[:5]],
        },
    ))

    return {
        "lateral_drifts": final,
        "thinking_log": steps,
    }
