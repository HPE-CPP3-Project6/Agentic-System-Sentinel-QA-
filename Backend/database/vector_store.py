"""ChromaDB wrapper — persistent, on-disk vector store for the RAG Generator.

Responsibilities:
- Own the single Chroma client and shared `code_sources` collection.
- Ingest a local source tree into the collection with chunk metadata.
- Serve grounded retrieval to the Generator via MULTI-QUERY EXPANSION:
  one logical "action" → three targeted queries (Router, Pydantic schema,
  SQLAlchemy model) → one deduplicated VerticalSliceContext so the LLM
  sees the entire vertical slice of the stack before writing tests.

Embedding model: jinaai/jina-embeddings-v2-base-code (768-dim, code-native),
cached locally under `chroma_models_cache/`.
"""

from __future__ import annotations

import enum
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from bootstrap import configure_caches

_CHROMA_HOME = configure_caches()

import chromadb  # noqa: E402
from chromadb import Documents, EmbeddingFunction, Embeddings  # noqa: E402
from chromadb.config import Settings  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402


logger = logging.getLogger(__name__)


DEFAULT_PERSIST_DIR = os.getenv(
    "CHROMA_PERSIST_DIR",
    os.getenv("SENTINEL_CHROMA_DIR", "./chroma_data"),
)
DEFAULT_COLLECTION = os.getenv("CHROMA_COLLECTION_NAME", "code_sources")
EMBEDDING_MODEL = os.getenv(
    "SENTINEL_EMBEDDING_MODEL", "jinaai/jina-embeddings-v2-base-code"
)

_LANG_BY_EXT: Dict[str, str] = {
    # Source code
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".vue": "vue",
    ".go": "go",
    ".java": "java",
    # Markup / templates
    ".html": "html",
    # Config & deployment (grounds Rule 1 protocol/deployment caveat)
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".conf": "config",
    ".cfg": "config",
    ".ini": "config",
    # Database
    ".sql": "sql",
}

# Filenames (no extension or compound) that we also index.
_TRACKED_BASENAMES = {
    "Dockerfile", "dockerfile",
    "Makefile", "makefile",
    "Caddyfile", "caddyfile",
    "nginx.conf",
    ".env.example", ".env.sample", ".env.template",
}

# Files we explicitly refuse to index — secrets or pure noise.
_SKIP_BASENAMES = {
    ".env", ".env.local", ".env.production", ".env.development", ".env.prod",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock",
}

# Directories we never index — noise or binary blobs.
_SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    ".venv", "venv", "chroma_store", "chroma_data", "chroma_models_cache",
    "coverage", ".turbo", ".cache",
    ".vscode", ".idea", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".nyc_output", "htmlcov", "repo_cache",
}

_MAX_FILE_BYTES = 256 * 1024  # 256 KB — skip giant bundles / lockfiles


# --------------------------------------------------------------------------- #
# Route intent — classification of the requirement driving retrieval
# --------------------------------------------------------------------------- #

class RouteIntent(str, enum.Enum):
    """What the requirement under test is asking the route to DO.

    Used to bias the model-bucket query so that LOOKUP/auth requirements
    retrieve query-expression and handler chunks (e.g. `.filter().first()`,
    `authenticate_user`) rather than ORM column definitions. Column widths
    are irrelevant to SELECT-only flows and their presence in the prompt
    reliably triggers the "String(255) causes 401" rationale drift.
    """
    WRITE = "write"      # register, create, update, delete, submit, save
    LOOKUP = "lookup"    # login, authenticate, read, fetch, list, view
    UNKNOWN = "unknown"


# Regex detects SQLAlchemy column/mapped_column definitions. We use this to
# tag storage-layer chunks in the prompt so the LLM reads a positive role
# label ("storage only, never enforced on SELECT") instead of us telling it
# NOT to use the chunk after we've already handed it over.
_COLUMN_DEFINITION_RE = re.compile(
    r"(?:^|\b)(?:mapped_column|Column)\s*\(", re.MULTILINE
)

# Prepended to the model section whenever any retrieved chunk is a column
# definition. Written as evidence, not as an adversarial rule.
_STORAGE_ROLE_NOTE = (
    "# SEMANTIC NOTE — STORAGE CONSTRAINTS ONLY (read this before using the\n"
    "# chunks below). The SQLAlchemy `Column(...)` / `mapped_column(...)`\n"
    "# declarations in this section define how values are PERSISTED. They are\n"
    "# enforced ONLY when the ORM actually INSERTs or UPDATEs that column.\n"
    "# They are NOT enforced on:\n"
    "#   - SELECT / filter queries (login lookups, reads, auth)\n"
    "#   - Form / JSON request validation (that is the Pydantic layer)\n"
    "#   - Any route that does not write the column in question\n"
    "# Therefore: a request value that 'exceeds' a `String(N)` column does NOT\n"
    "# cause a 401 / 404 / 422 on lookup routes. On lookup routes the outcome\n"
    "# is driven by the SELECT result (match → 200, no match → 401), not by\n"
    "# the column width. Cite these columns ONLY when the route under test\n"
    "# actually INSERTs or UPDATEs that column."
)

# Regex detects Pydantic *write-side* validators whose constraints apply only
# on routes that explicitly use the owning schema as a request body.
# `EmailStr(` / `constr(` / `conint(` / `@field_validator` / `@validator` /
# `Field(...` with max_length. Matching any of these on a chunk whose owner
# is NOT consumed by the route under test (common case: login uses
# OAuth2PasswordRequestForm, not UserCreate) triggers the schema-role note.
_SCHEMA_VALIDATOR_RE = re.compile(
    r"\b(?:EmailStr\s*\(|constr\s*\(|conint\s*\(|confloat\s*\(|"
    r"@field_validator|@validator|@root_validator|model_validator\s*\()",
    re.MULTILINE,
)

# Prepended to the schema section when the route intent is LOOKUP and any
# retrieved chunk contains a request-body validator. Tells the LLM these
# validators apply only to the routes that USE them — login's form dep does
# NOT pick them up.
_SCHEMA_ROLE_NOTE_LOOKUP = (
    "# SEMANTIC NOTE — REQUEST-BODY VALIDATORS ONLY (read this before using\n"
    "# the chunks below). The current requirement is a LOOKUP / AUTH route\n"
    "# (login, fetch, read). The Pydantic validators below (`EmailStr`,\n"
    "# `constr`, `field_validator`, `Field(max_length=...)`) are enforced\n"
    "# ONLY on routes that declare the owning schema as a request body\n"
    "# (typically WRITE routes like POST /register).\n"
    "# They are NOT enforced on:\n"
    "#   - Login routes backed by `OAuth2PasswordRequestForm` — the form\n"
    "#     dependency accepts raw `username` + `password` strings with NO\n"
    "#     EmailStr / regex / length validation applied by FastAPI.\n"
    "#   - Any endpoint whose signature does not reference these schemas.\n"
    "# Therefore: do NOT assert `422 \"not a valid email\"` or\n"
    "# `422 \"string too long\"` on a login route just because `EmailStr` or\n"
    "# `constr(max_length=...)` appears in a neighbouring schema. On\n"
    "# lookup/auth routes the outcome is 401 (miss) or 200 (match), never\n"
    "# 422 derived from a body validator the route does not use."
)


# --------------------------------------------------------------------------- #
# Snippet + Vertical Slice data types
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SourceSnippet:
    text: str
    path: str
    language: str
    start_line: int
    end_line: int

    def header(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def as_prompt_block(self) -> str:
        return (
            f"[{self.path}:{self.start_line}-{self.end_line} ({self.language})]\n"
            f"{self.text}"
        )


@dataclass
class VerticalSliceContext:
    """Mega-context assembled from four targeted ChromaDB queries.

    Instantiated by `query_source_context(...)`. Carries Router, Schema,
    Model, and Frontend snippets as separate buckets so the prompt can
    label each section explicitly. Deduplicated across buckets: if the same
    chunk is retrieved by multiple queries, it appears once
    (priority: router > schema > model > frontend).

    The frontend bucket exists because UI-layer behavior (e.g. a React
    component rendering `{user?.email}` or persisting auth state in
    localStorage) frequently grounds ACs that the backend response schema
    does NOT — "show the user's email on the dashboard" is testable via DOM
    assertions even if the `/login` response only returns an access token.

    Backward-compatible with callers (e.g. the Healer in executor.py) that
    treat it as a sequence of prompt-ready strings:
        snippets = query_source_context(q)            # VerticalSliceContext
        "\\n\\n---\\n\\n".join(snippets)              # works via __iter__
        if snippets: ...                              # works via __bool__
    """

    action: str
    router_snippets: List[SourceSnippet] = field(default_factory=list)
    schema_snippets: List[SourceSnippet] = field(default_factory=list)
    model_snippets: List[SourceSnippet] = field(default_factory=list)
    frontend_snippets: List[SourceSnippet] = field(default_factory=list)
    # 5th bucket: frontend API client / HTTP transport (axios, fetch, baseURL).
    # Separate from `frontend_snippets` because UI-render retrieval and
    # API-client-config retrieval target different files (Dashboard.jsx vs
    # api/axios.js) and need different token sets in the query.
    api_client_snippets: List[SourceSnippet] = field(default_factory=list)
    # Carried so `as_mega_context()` can make intent-dependent decisions
    # (e.g. prepend the LOOKUP schema-role note when request-body validators
    # appear in the schema bucket on a LOOKUP requirement).
    route_intent: "RouteIntent" = field(default_factory=lambda: RouteIntent.UNKNOWN)

    @property
    def all_snippets(self) -> List[SourceSnippet]:
        return (
            list(self.router_snippets)
            + list(self.schema_snippets)
            + list(self.model_snippets)
            + list(self.frontend_snippets)
            + list(self.api_client_snippets)
        )

    @property
    def source_refs(self) -> List[str]:
        return [s.header() for s in self.all_snippets]

    def as_mega_context(self) -> str:
        """Sectioned, LLM-friendly rendering of the full vertical slice."""
        if not self.all_snippets:
            return (
                "(no indexed source retrieved for this action — "
                "DO NOT invent fields, routes, or schemas; emit coverage_gaps instead)"
            )

        sections: List[str] = []

        if self.router_snippets:
            sections.append(
                "===== ROUTER & API ENDPOINT DEFINITION =====\n"
                + "\n\n".join(s.as_prompt_block() for s in self.router_snippets)
            )
        else:
            sections.append(
                "===== ROUTER & API ENDPOINT DEFINITION =====\n"
                "(no router snippet retrieved — endpoint path / method / dependency "
                "signature is UNKNOWN; treat the endpoint contract as unverified)"
            )

        if self.schema_snippets:
            has_validator = any(
                _SCHEMA_VALIDATOR_RE.search(s.text) for s in self.schema_snippets
            )
            body = "\n\n".join(s.as_prompt_block() for s in self.schema_snippets)
            if has_validator and self.route_intent is RouteIntent.LOOKUP:
                sections.append(
                    "===== PYDANTIC REQUEST / RESPONSE SCHEMAS =====\n"
                    f"{_SCHEMA_ROLE_NOTE_LOOKUP}\n\n"
                    f"{body}"
                )
            else:
                sections.append(
                    "===== PYDANTIC REQUEST / RESPONSE SCHEMAS =====\n"
                    f"{body}"
                )
        else:
            sections.append(
                "===== PYDANTIC REQUEST / RESPONSE SCHEMAS =====\n"
                "(no schema snippet retrieved — request field set is UNKNOWN; "
                "you MUST NOT invent fields like full_name / phone / etc.)"
            )

        if self.model_snippets:
            has_column_chunk = any(
                _COLUMN_DEFINITION_RE.search(s.text) for s in self.model_snippets
            )
            body = "\n\n".join(s.as_prompt_block() for s in self.model_snippets)
            if has_column_chunk:
                sections.append(
                    "===== DATABASE / SQLALCHEMY MODELS =====\n"
                    f"{_STORAGE_ROLE_NOTE}\n\n"
                    f"{body}"
                )
            else:
                sections.append(
                    "===== DATABASE / SQLALCHEMY MODELS =====\n"
                    f"{body}"
                )
        else:
            sections.append(
                "===== DATABASE / SQLALCHEMY MODELS =====\n"
                "(no ORM model snippet retrieved — DB columns / constraints "
                "are UNKNOWN; do not assert against fields you cannot see)"
            )

        if self.frontend_snippets:
            sections.append(
                "===== FRONTEND RENDERING (React JSX/TSX) =====\n"
                + "\n\n".join(s.as_prompt_block() for s in self.frontend_snippets)
            )
        else:
            sections.append(
                "===== FRONTEND RENDERING (React JSX/TSX) =====\n"
                "(no frontend snippet retrieved — UI rendering for this "
                "action is UNKNOWN; do not assert DOM contents you cannot see)"
            )

        if self.api_client_snippets:
            sections.append(
                "===== FRONTEND API CLIENT CONFIG (axios / fetch / baseURL) =====\n"
                + "\n\n".join(s.as_prompt_block() for s in self.api_client_snippets)
            )
        else:
            sections.append(
                "===== FRONTEND API CLIENT CONFIG (axios / fetch / baseURL) =====\n"
                "(no api-client snippet retrieved — the browser's outbound "
                "request scheme is UNKNOWN; do NOT assert `http://` vs "
                "`https://` on API transport unless a snippet from axios / "
                "fetch / HttpLink config is present in this section)"
            )

        return "\n\n".join(sections)

    # Backward-compat: behave like a list of prompt blocks for existing callers.
    def __iter__(self) -> Iterator[str]:
        for s in self.all_snippets:
            yield s.as_prompt_block()

    def __len__(self) -> int:
        return len(self.all_snippets)

    def __bool__(self) -> bool:
        return len(self.all_snippets) > 0


# --------------------------------------------------------------------------- #
# Chroma client / collection
# --------------------------------------------------------------------------- #

class JinaCodeEmbeddingFunction(EmbeddingFunction):
    """Chroma-compatible wrapper for `jinaai/jina-embeddings-v2-base-code`.

    Code-native embedding model (768-dim) that outperforms generic MiniLM on
    retrieval of Python / TS / JSX source chunks. Requires `trust_remote_code=True`
    which Chroma's default `SentenceTransformerEmbeddingFunction` does not
    forward cleanly — hence the custom class.

    The underlying SentenceTransformer is cached at the class level so repeated
    instantiations (e.g. one per `get_collection` call) do NOT reload the model.
    """

    _model: "SentenceTransformer | None" = None

    def __init__(self) -> None:
        os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", _CHROMA_HOME)
        os.environ.setdefault("HF_HOME", _CHROMA_HOME)
        if JinaCodeEmbeddingFunction._model is None:
            logger.info("Loading SentenceTransformer: %s", EMBEDDING_MODEL)
            JinaCodeEmbeddingFunction._model = SentenceTransformer(
                EMBEDDING_MODEL,
                trust_remote_code=True,
                cache_folder=_CHROMA_HOME,
            )
        self.model = JinaCodeEmbeddingFunction._model

    def __call__(self, input: Documents) -> Embeddings:
        return self.model.encode(input, convert_to_numpy=True).tolist()


def get_chroma_client(persist_dir: str = DEFAULT_PERSIST_DIR) -> chromadb.PersistentClient:
    os.makedirs(persist_dir, exist_ok=True)
    return chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(
            chroma_home=_CHROMA_HOME,
            anonymized_telemetry=False,
            is_persistent=True
        ),
    )


def _get_embedding_function() -> JinaCodeEmbeddingFunction:
    return JinaCodeEmbeddingFunction()


def get_or_create_collection(name: str = DEFAULT_COLLECTION):
    client = get_chroma_client()
    emb_fn = _get_embedding_function()
    return client.get_or_create_collection(
        name=name,
        embedding_function=emb_fn,
    )


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #

def _chunk_lines(
    lines: List[str],
    chunk_size: int = 80,
    overlap: int = 10,
) -> Iterable[Tuple[int, int, str]]:
    """Yield (start_line, end_line, text) with 1-based inclusive line numbers."""
    if not lines:
        return
    step = max(1, chunk_size - overlap)
    i = 0
    n = len(lines)
    while i < n:
        j = min(n, i + chunk_size)
        yield i + 1, j, "".join(lines[i:j])
        if j == n:
            break
        i += step


def _language_for(filename: str) -> Optional[str]:
    """Return a language label for `filename`, or None if it should be skipped."""
    if filename in _SKIP_BASENAMES:
        return None
    if filename in _TRACKED_BASENAMES:
        base = filename.lower()
        if base == "dockerfile":
            return "dockerfile"
        if base == "makefile":
            return "makefile"
        if base == "caddyfile":
            return "caddy"
        if base == "nginx.conf":
            return "nginx"
        if base.startswith(".env."):
            return "env"
        return "text"
    ext = os.path.splitext(filename)[1].lower()
    return _LANG_BY_EXT.get(ext)


def _iter_source_files(root: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if _language_for(fn) is None:
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield full


def _doc_id(rel_path: str, start: int, end: int) -> str:
    h = hashlib.sha1(f"{rel_path}:{start}-{end}".encode("utf-8")).hexdigest()[:16]
    return f"{rel_path}:{start}-{end}:{h}"


def ingest_source_tree(
    root: str,
    collection_name: str = DEFAULT_COLLECTION,
    reset: bool = False,
) -> Dict[str, int]:
    """Walk `root`, chunk every source file, and upsert into the collection.

    Returns a summary dict: files_indexed, chunks_written.
    """
    root = os.path.abspath(root)
    client = get_chroma_client()
    if reset:
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
    collection = get_or_create_collection(collection_name)

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict[str, str]] = []
    files_indexed = 0

    for abs_path in _iter_source_files(root):
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        if not lines:
            continue

        rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
        language = _language_for(os.path.basename(abs_path)) or "text"
        files_indexed += 1

        for start, end, text in _chunk_lines(lines):
            ids.append(_doc_id(rel_path, start, end))
            docs.append(text)
            metas.append(
                {
                    "path": rel_path,
                    "language": language,
                    "start_line": start,
                    "end_line": end,
                }
            )

        if len(ids) >= 256:
            collection.upsert(ids=ids, documents=docs, metadatas=metas)
            ids.clear(); docs.clear(); metas.clear()

    if ids:
        collection.upsert(ids=ids, documents=docs, metadatas=metas)

    return {"files_indexed": files_indexed, "chunks_written": collection.count()}


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #

def query_source_snippets(
    query: str,
    n_results: int = 5,
    collection_name: str = DEFAULT_COLLECTION,
    rerank: Optional[bool] = None,
) -> List[SourceSnippet]:
    """Single-query semantic search. Returns raw SourceSnippet objects.

    When the cross-encoder reranker is enabled
    (`SENTINEL_RERANKER_ENABLED=1`) and `rerank` is not explicitly set to
    False, this over-fetches from ChromaDB and returns the top `n_results`
    after reranking. Over-fetch ratio is tunable via
    `SENTINEL_RERANKER_OVERFETCH` (default 3).

    Passing `rerank=False` explicitly disables reranking for this call
    regardless of env flag — useful for tests / snapshots that want a
    deterministic retriever-only ordering.
    """
    from .reranker import (  # local import: reranker module is optional
        DEFAULT_OVERFETCH_RATIO,
        is_reranker_enabled,
        maybe_rerank_snippets,
    )

    rerank_active = is_reranker_enabled() if rerank is None else bool(rerank)
    fetch_n = n_results * DEFAULT_OVERFETCH_RATIO if rerank_active else n_results

    client = get_chroma_client()
    emb_fn = _get_embedding_function()

    try:
        collection = client.get_collection(
            name=collection_name,
            embedding_function=emb_fn,
        )
    except ValueError as exc:
        logger.warning(
            "Collection '%s' embedding config mismatch (%s). Falling back to persisted config.",
            collection_name,
            exc,
        )
        try:
            collection = client.get_collection(name=collection_name)
        except Exception:
            return []
    except Exception:
        return []

    if collection.count() == 0:
        return []

    try:
        result = collection.query(query_texts=[query], n_results=fetch_n)
    except Exception:
        return []

    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]

    snippets: List[SourceSnippet] = []
    for text, meta in zip(docs, metas):
        meta = meta or {}
        path = str(meta.get("path") or meta.get("file_path") or "unknown")

        start_line = meta.get("start_line")
        end_line = meta.get("end_line")
        if start_line is None and meta.get("chunk_index") is not None:
            start_line = int(meta.get("chunk_index", 0)) + 1
        if end_line is None:
            end_line = start_line or 0

        snippets.append(
            SourceSnippet(
                text=text,
                path=path,
                language=str(meta.get("language", "text")),
                start_line=int(start_line or 0),
                end_line=int(end_line or 0),
            )
        )

    if rerank_active:
        snippets = maybe_rerank_snippets(query, snippets, top_k=n_results)

    return snippets


# --------------------------------------------------------------------------- #
# Multi-query expansion
# --------------------------------------------------------------------------- #

def _router_query(action: str, context_keywords: str = "") -> str:
    return (
        f"FastAPI APIRouter @router.post @router.get @router.put @router.delete "
        f"@app.post endpoint path Depends OAuth2PasswordRequestForm Form() "
        f"response_model for {action} {context_keywords}"
    )


def _schema_query(action: str, intent: RouteIntent = RouteIntent.UNKNOWN, context_keywords: str = "") -> str:
    """Intent-aware schema bucket query.

    LOOKUP: bias toward RESPONSE models (`Token`, `response_model=`,
      `access_token`, `token_type`) and OAuth2 form dependencies. Login /
      read routes rarely validate a JSON request body; their only schema
      input is a response model. Keeping request-body validators out of the
      prompt prevents the "422 because EmailStr" drift on login tests.
    WRITE: keep current (request body + field_validator + EmailStr + constr).
    UNKNOWN: union of both (legacy behavior).
    """
    if intent is RouteIntent.LOOKUP:
        return (
            f"Pydantic BaseModel response model response_model Token "
            f"access_token token_type bearer OAuth2PasswordRequestForm "
            f"OAuth2PasswordBearer Form Depends Literal Optional for {action} {context_keywords}"
        )
    if intent is RouteIntent.WRITE:
        return (
            f"Pydantic BaseModel request body schema Field field_validator "
            f"EmailStr constr conint confloat Literal Optional "
            f"UserCreate UserUpdate max_length min_length regex for {action} {context_keywords}"
        )
    return (
        f"Pydantic BaseModel schema request body response model Field "
        f"field_validator EmailStr constr conint Literal Optional for {action} {context_keywords}"
    )


def _model_query(action: str, intent: RouteIntent = RouteIntent.UNKNOWN, context_keywords: str = "") -> str:
    """Intent-aware model bucket query.

    LOOKUP (login / read / fetch): bias toward query expressions and
      handlers — `.filter(...).first()`, `authenticate_user`, `db.query(...)`,
      `verify_password`, JWT creation. Column widths are irrelevant here; if
      any slip in, they get labeled by the storage-role note at render time.
    WRITE (register / create / update): bias toward table shape — columns,
      constraints, uniqueness — because write validation DOES depend on it.
    UNKNOWN: union of both (legacy behavior).
    """
    if intent is RouteIntent.LOOKUP:
        return (
            f"SQLAlchemy db.query filter first get session authenticate_user "
            f"verify_password pwd_context hash SELECT read lookup fetch "
            f"create_access_token jwt encode decode for {action} {context_keywords}"
        )
    if intent is RouteIntent.WRITE:
        return (
            f"SQLAlchemy declarative Base __tablename__ Column mapped_column "
            f"relationship ForeignKey primary_key nullable unique constraint "
            f"INSERT UPDATE commit add refresh for {action} {context_keywords}"
        )
    return (
        f"SQLAlchemy declarative Base ORM __tablename__ Column mapped_column "
        f"relationship ForeignKey primary_key nullable unique db.query filter "
        f"first session for {action} {context_keywords}"
    )


def _frontend_query(action: str, context_keywords: str = "") -> str:
    return (
        f"React JSX TSX component useState useEffect useContext AuthContext "
        f"onClick onSubmit render localStorage sessionStorage Dashboard Login "
        f"header rendered text user.email user?.email className for {action} {context_keywords}"
    )


def _api_client_query(action: str, context_keywords: str = "") -> str:
    """Bucket 5 — Frontend API client configuration & HTTP transport.

    Targeted at axios / fetch / HttpLink setup files that carry the EXPLICIT
    `http://` vs `https://` protocol and the base URL the browser actually
    sends requests to. Without this bucket the Generator treats every
    protocol-sensitive AC as a coverage_gap because the React JSX query
    doesn't surface `axios.js` / `apiClient.ts` / `.env.example`.

    Tokens chosen to co-occur with the explicit protocol literal in a
    frontend HTTP client module: `axios.create({ baseURL: "http://..." })`,
    `fetch("http://...")`, `VITE_API_URL=http://...`, etc.
    """
    return (
        f"axios axios.create axios.defaults baseURL interceptors "
        f"fetch Request URL HttpLink ky.create prefixUrl "
        f"VITE_API_URL REACT_APP_API_URL API_BASE_URL api_base_url "
        f"http:// https:// ws:// wss:// api client module transport "
        f"for {action} {context_keywords}"
    )


def _dedup_extend(
    accumulator: List[SourceSnippet],
    seen: set,
    incoming: List[SourceSnippet],
) -> List[SourceSnippet]:
    kept: List[SourceSnippet] = []
    for s in incoming:
        key = (s.path, s.start_line, s.end_line)
        if key in seen:
            continue
        seen.add(key)
        kept.append(s)
    accumulator.extend(kept)
    return kept


def query_source_context(
    action: str,
    n_results: int = 15,
    collection_name: str = DEFAULT_COLLECTION,
    intent: RouteIntent = RouteIntent.UNKNOWN,
    context_keywords: str = "",
    rerank: Optional[bool] = None,
) -> VerticalSliceContext:
    """Multi-Query Expansion — one action → FIVE targeted retrievals.

    Performs five ChromaDB queries in a row:
      Q1 (router):       API endpoint definition / @router decorator / Form() deps
      Q2 (schema):       Pydantic request & response models + validators
      Q3 (model):        SQLAlchemy chunks, biased by `intent`:
                           LOOKUP → `.filter().first()`, authenticate_user, JWT
                           WRITE  → Column / __tablename__ / constraints
                           UNKNOWN → union
      Q4 (frontend):     React JSX/TSX rendering & local state persistence
      Q5 (api_client):   Frontend HTTP client config — axios / fetch / baseURL
                         / VITE_API_URL. Grounds `http://` vs `https://` claims
                         on API transport that JSX rendering cannot.

    Results are deduplicated across categories (router > schema > model >
    frontend > api_client) and returned as a `VerticalSliceContext` that can
    be rendered as a single sectioned mega-context via `.as_mega_context()`.

    `intent` is the caller's route-intent classification. Generator computes
    it per-requirement and passes it in so retrieval reflects what the route
    actually does. LOOKUP intent specifically avoids centering the model
    bucket on ORM column definitions whose widths would then be misread as
    route-layer causes of 401 outcomes.

    The returned object is ALSO iterable as a sequence of prompt-ready
    snippet strings, preserving compatibility with legacy callers (e.g. the
    Healer in executor.py) that treat the result as `List[str]`.

    `n_results` is the per-category retrieval budget.
    """
    action = (action or "").strip() or "the requested feature"

    seen: set = set()
    router: List[SourceSnippet] = []
    schema: List[SourceSnippet] = []
    model: List[SourceSnippet] = []
    frontend: List[SourceSnippet] = []
    api_client: List[SourceSnippet] = []

    _dedup_extend(
        router, seen,
        query_source_snippets(_router_query(action, context_keywords), n_results=n_results,
                              collection_name=collection_name, rerank=rerank),
    )
    _dedup_extend(
        schema, seen,
        query_source_snippets(_schema_query(action, intent=intent, context_keywords=context_keywords),
                              n_results=n_results,
                              collection_name=collection_name, rerank=rerank),
    )
    _dedup_extend(
        model, seen,
        query_source_snippets(_model_query(action, intent=intent, context_keywords=context_keywords),
                              n_results=n_results,
                              collection_name=collection_name, rerank=rerank),
    )
    _dedup_extend(
        frontend, seen,
        query_source_snippets(_frontend_query(action, context_keywords), n_results=n_results,
                              collection_name=collection_name, rerank=rerank),
    )
    _dedup_extend(
        api_client, seen,
        query_source_snippets(_api_client_query(action, context_keywords), n_results=n_results,
                              collection_name=collection_name, rerank=rerank),
    )

    return VerticalSliceContext(
        action=action,
        router_snippets=router,
        schema_snippets=schema,
        model_snippets=model,
        frontend_snippets=frontend,
        api_client_snippets=api_client,
        route_intent=intent,
    )
