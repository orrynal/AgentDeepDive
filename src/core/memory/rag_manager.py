import os
os.environ["HF_HUB_OFFLINE"] = "1"
import json
import structlog
from pymilvus import connections, utility, Collection, FieldSchema, DataType, CollectionSchema, MilvusClient
from sentence_transformers import SentenceTransformer
from src.config import settings

logger = structlog.get_logger()


class MockMilvusClient:
    """Mock Milvus client for local fallback of skill semantic routing."""
    def __init__(self, local_skills_fn):
        self.local_skills_fn = local_skills_fn

    def search(self, collection_name: str, data: list, limit: int, output_fields: list[str]):
        import numpy as np
        if not data:
            return [[]]
        query_vector = data[0]
        results = []
        q_vec = np.array(query_vector)
        
        # Resolve tenant_suffix from collection_name
        tenant_suffix = "default"
        if "_" in collection_name:
            parts = collection_name.rsplit("_", 1)
            if len(parts) > 1:
                candidate = parts[1]
                import re
                if candidate == "default" or (len(candidate) == 32 and re.match(r"^[0-9a-fA-F]{32}$", candidate)):
                    tenant_suffix = candidate
                
        try:
            local_skills = self.local_skills_fn(tenant_suffix)
        except TypeError:
            local_skills = self.local_skills_fn()
        
        for item in local_skills:
            i_vec = np.array(item["vector"])
            dot = np.dot(q_vec, i_vec)
            norm_q = np.linalg.norm(q_vec)
            norm_i = np.linalg.norm(i_vec)
            sim = dot / (norm_q * norm_i) if norm_q > 0 and norm_i > 0 else 0.0
            results.append({
                "id": 1,
                "distance": float(sim),
                "entity": {
                    "skill_id": item["skill_id"],
                    "name": item["name"],
                    "description": item["description"]
                }
            })
        
        results.sort(key=lambda x: x["distance"], reverse=True)
        return [results[:limit]]


class RAGManager:
    """Pluggable Vector Memory and RAG Manager with Global Multi-Tenant Support.
    
    Dynamically isolates knowledge base entries, episodic memories, and skills
    into separate tenant-specific collections or nested local storage schemas.
    """
    def __init__(self):
        from pathlib import Path
        self.connected = False
        self.embedder = None
        
        # Dynamic cache for collections
        self._kb_collections_cache = {}
        self._em_collections_cache = {}
        self._skills_collections_cache = set()
        
        # local_storage schema: { tenant_suffix: { "kb": [], "em": [], "skills": [] } }
        self.local_storage = {}
        self.client = MockMilvusClient(lambda tenant_suffix: self._get_local_data(tenant_suffix)["skills"])
        
        self.storage_dir = Path(".memory")
        self.storage_file = self.storage_dir / "rag_storage.json"
        
        # Load local storage
        self._load_local_storage()
        
        # Connect to Milvus
        if settings.system_mode == "lightweight":
            logger.info("Lightweight mode enabled: Skipping Milvus connection attempt")
            self.connected = False
        else:
            try:
                connections.connect(
                    alias="default", 
                    host=settings.milvus_host, 
                    port=str(settings.milvus_port),
                    timeout=5.0
                )
                self.client = MilvusClient(
                    uri=f"http://{settings.milvus_host}:{settings.milvus_port}",
                    timeout=5.0
                )
                self.connected = True
                logger.info("Successfully connected to Milvus", host=settings.milvus_host, port=settings.milvus_port)
            except Exception as e:
                logger.warning("Milvus connection failed. RAG will run in local-mock mode.", error=str(e))
                self.connected = False
                self.client = MockMilvusClient(lambda tenant_suffix: self._get_local_data(tenant_suffix)["skills"])

    def _get_tenant_suffix(self) -> str:
        """Resolve current tenant ID from global context and format it as a valid Milvus suffix."""
        from src.core.auth.context import current_tenant_id
        t_id = current_tenant_id.get()
        if not t_id:
            return "default"
        return str(t_id).replace("-", "")

    def _load_local_storage(self):
        if self.storage_file.exists():
            try:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                    # Backward compatibility fallback
                    if "kb" in raw_data or "em" in raw_data or "skills" in raw_data:
                        self.local_storage = {
                            "default": {
                                "kb": raw_data.get("kb", []),
                                "em": raw_data.get("em", []),
                                "skills": raw_data.get("skills", [])
                            }
                        }
                    else:
                        self.local_storage = raw_data
                logger.info("Loaded local RAG storage with tenant isolation", file=str(self.storage_file), tenants=list(self.local_storage.keys()))
            except Exception as e:
                logger.error("Failed to load local RAG storage", error=str(e))

    def _save_local_storage(self):
        try:
            self.storage_dir.mkdir(exist_ok=True)
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(self.local_storage, f, ensure_ascii=False, indent=2)
            logger.info("Saved local RAG storage", file=str(self.storage_file))
        except Exception as e:
            logger.error("Failed to save local RAG storage", error=str(e))

    def _get_local_data(self, tenant_suffix: str) -> dict:
        if tenant_suffix not in self.local_storage:
            self.local_storage[tenant_suffix] = {
                "kb": [],
                "em": [],
                "skills": []
            }
        return self.local_storage[tenant_suffix]

    def _get_kb_name(self, tenant_suffix: str) -> str:
        if tenant_suffix == "default":
            return "agentdeep_knowledge_base"
        return f"kb_{tenant_suffix}"

    def _get_em_name(self, tenant_suffix: str) -> str:
        if tenant_suffix == "default":
            return "agentdeep_episodic_memory"
        return f"em_{tenant_suffix}"

    def _get_skill_name(self, tenant_suffix: str) -> str:
        if tenant_suffix == "default":
            return "skill_embeddings"
        return f"skills_{tenant_suffix}"

    def _get_kb_collection(self, tenant_suffix: str):
        """Retrieve or dynamically create/load the Knowledge Base collection for a specific tenant."""
        kb_name = self._get_kb_name(tenant_suffix)
        if kb_name in self._kb_collections_cache:
            return self._kb_collections_cache[kb_name]
            
        if self.connected:
            try:
                if not utility.has_collection(kb_name):
                    fields = [
                        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=384),
                        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
                        FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=2048)
                    ]
                    schema = CollectionSchema(fields, description=f"Static knowledge base for tenant {tenant_suffix}")
                    col = Collection(name=kb_name, schema=schema)
                    index_params = {
                        "metric_type": "COSINE",
                        "index_type": "IVF_FLAT",
                        "params": {"nlist": 128}
                    }
                    col.create_index(field_name="vector", index_params=index_params)
                    logger.info("Created tenant knowledge base collection", collection=kb_name)
                else:
                    col = Collection(name=kb_name)
                
                col.load(timeout=5.0)
                self._kb_collections_cache[kb_name] = col
                return col
            except Exception as e:
                logger.error("Failed to load/create tenant Milvus collection", collection=kb_name, error=str(e))
                return None
        return None

    def _get_em_collection(self, tenant_suffix: str):
        """Retrieve or dynamically create/load the Episodic Memory collection for a specific tenant."""
        em_name = self._get_em_name(tenant_suffix)
        if em_name in self._em_collections_cache:
            return self._em_collections_cache[em_name]
            
        if self.connected:
            try:
                if not utility.has_collection(em_name):
                    fields = [
                        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=384),
                        FieldSchema(name="task_id", dtype=DataType.VARCHAR, max_length=256),
                        FieldSchema(name="prompt", dtype=DataType.VARCHAR, max_length=65535),
                        FieldSchema(name="error_stack", dtype=DataType.VARCHAR, max_length=65535),
                        FieldSchema(name="patch", dtype=DataType.VARCHAR, max_length=65535)
                    ]
                    schema = CollectionSchema(fields, description=f"Episodic memory for tenant {tenant_suffix}")
                    col = Collection(name=em_name, schema=schema)
                    index_params = {
                        "metric_type": "COSINE",
                        "index_type": "IVF_FLAT",
                        "params": {"nlist": 128}
                    }
                    col.create_index(field_name="vector", index_params=index_params)
                    logger.info("Created tenant episodic memory collection", collection=em_name)
                else:
                    col = Collection(name=em_name)
                
                col.load(timeout=5.0)
                self._em_collections_cache[em_name] = col
                return col
            except Exception as e:
                logger.error("Failed to load/create tenant Milvus collection", collection=em_name, error=str(e))
                return None
        return None

    def _get_skills_collection_name(self, tenant_suffix: str) -> str:
        """Retrieve or dynamically create/load the Skills collection name via MilvusClient."""
        skill_name = self._get_skill_name(tenant_suffix)
        if skill_name in self._skills_collections_cache:
            return skill_name
            
        if self.connected and self.client and not isinstance(self.client, MockMilvusClient):
            try:
                if not self.client.has_collection(collection_name=skill_name):
                    schema = self.client.create_schema(auto_id=True, enable_dynamic_field=False)
                    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
                    schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=384)
                    schema.add_field(field_name="skill_id", datatype=DataType.VARCHAR, max_length=128)
                    schema.add_field(field_name="name", datatype=DataType.VARCHAR, max_length=256)
                    schema.add_field(field_name="description", datatype=DataType.VARCHAR, max_length=65535)
                    
                    idx_params = self.client.prepare_index_params()
                    idx_params.add_index(
                        field_name="vector",
                        metric_type="COSINE",
                        index_type="IVF_FLAT",
                        params={"nlist": 128}
                    )
                    self.client.create_collection(
                        collection_name=skill_name,
                        schema=schema,
                        index_params=idx_params
                    )
                    logger.info("Created tenant skill collection via MilvusClient", collection=skill_name)
                else:
                    self.client.load_collection(collection_name=skill_name, timeout=5.0)
                
                self._skills_collections_cache.add(skill_name)
                return skill_name
            except Exception as e:
                logger.error("Failed to load/create tenant Milvus client collection", collection=skill_name, error=str(e))
                return "skill_embeddings"
        return skill_name

    def _get_embedder(self):
        """Lazy load the SentenceTransformer model on first use."""
        if self.embedder is None:
            try:
                logger.info("Initializing SentenceTransformer model (lazy load)...", model="all-MiniLM-L6-v2")
                self.embedder = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
                logger.info("SentenceTransformer model loaded successfully", model="all-MiniLM-L6-v2")
            except Exception as e:
                logger.error("Failed to load SentenceTransformer model", error=str(e))
        return self.embedder

    def index_document(self, text: str, source: str):
        """Chunk and index a local document or spec sheet into the static knowledge base."""
        embedder = self._get_embedder()
        if not embedder:
            logger.error("RAG error: Embedder not initialized")
            return
            
        tenant_suffix = self._get_tenant_suffix()
        
        # 500-character chunks with 100-character overlap
        chunk_size = 500
        overlap = 100
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start += chunk_size - overlap
            
        for chunk in chunks:
            if not chunk.strip():
                continue
            vector = embedder.encode(chunk).tolist()
            col = self._get_kb_collection(tenant_suffix)
            if self.connected and col:
                data = [
                    [vector],
                    [chunk],
                    [source]
                ]
                col.insert(data)
            else:
                tenant_data = self._get_local_data(tenant_suffix)
                tenant_data["kb"].append({
                    "vector": vector,
                    "text": chunk,
                    "source": source
                })
                self._save_local_storage()
                
        col = self._get_kb_collection(tenant_suffix)
        if self.connected and col:
            col.flush()
        logger.info("Indexed document chunks under tenant context", tenant=tenant_suffix, source=source, count=len(chunks))

    def query_knowledge_base(self, query: str, limit: int = 3) -> str:
        """Query semantic knowledge base and format the retrieved context snippets."""
        embedder = self._get_embedder()
        if not embedder:
            return "RAG Error: Embedder not initialized."
            
        query_vector = embedder.encode(query).tolist()
        tenant_suffix = self._get_tenant_suffix()
        col = self._get_kb_collection(tenant_suffix)
        
        if self.connected and col:
            try:
                search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
                results = col.search(
                    data=[query_vector],
                    anns_field="vector",
                    param=search_params,
                    limit=limit,
                    output_fields=["text", "source"]
                )
                
                output_parts = []
                for hit in results[0]:
                    source = hit.entity.get("source")
                    text = hit.entity.get("text")
                    score = hit.distance
                    output_parts.append(f"Source: {source} (Similarity Score: {score:.3f})\nContent: {text}")
                return "\n\n".join(output_parts) if output_parts else "No matching knowledge base entries found."
            except Exception as e:
                logger.error("Failed to query Milvus knowledge base", tenant=tenant_suffix, error=str(e))
                return "RAG query failed."
        else:
            # Local cosine similarity fallback
            import numpy as np
            results = []
            q_vec = np.array(query_vector)
            tenant_data = self._get_local_data(tenant_suffix)
            for item in tenant_data["kb"]:
                i_vec = np.array(item["vector"])
                dot = np.dot(q_vec, i_vec)
                norm_q = np.linalg.norm(q_vec)
                norm_i = np.linalg.norm(i_vec)
                sim = dot / (norm_q * norm_i) if norm_q > 0 and norm_i > 0 else 0.0
                results.append((sim, item))
                
            results.sort(key=lambda x: x[0], reverse=True)
            output_parts = []
            for sim, item in results[:limit]:
                output_parts.append(f"Source: {item['source']} (Similarity Score: {sim:.3f})\nContent: {item['text']}")
            return "\n\n".join(output_parts) if output_parts else "No matching knowledge base entries found."

    def save_episodic_memory(self, task_id: str, prompt: str, error_stack: str, patch: str, skill_id: str | None = None):
        """Store task execution details and successful patch history for episodic recall."""
        embedder = self._get_embedder()
        if not embedder:
            return
            
        indexed_text = f"Prompt: {prompt}\nError: {error_stack}"
        vector = embedder.encode(indexed_text).tolist()
        
        # Serialize skill_id into task_id to preserve schema compatibility
        stored_task_id = f"{skill_id}::{task_id}" if skill_id else task_id
        tenant_suffix = self._get_tenant_suffix()
        col = self._get_em_collection(tenant_suffix)
        
        if self.connected and col:
            data = [
                [vector],
                [stored_task_id],
                [prompt],
                [error_stack],
                [patch]
            ]
            col.insert(data)
            col.flush()
            logger.info("Saved episodic memory to Milvus under tenant context", tenant=tenant_suffix, task_id=task_id, skill_id=skill_id)
        else:
            tenant_data = self._get_local_data(tenant_suffix)
            tenant_data["em"].append({
                "vector": vector,
                "task_id": stored_task_id,
                "prompt": prompt,
                "error_stack": error_stack,
                "patch": patch
            })
            self._save_local_storage()
            logger.info("Saved episodic memory to local memory storage under tenant context", tenant=tenant_suffix, task_id=task_id, skill_id=skill_id)

    def query_episodic_memory(self, query: str, limit: int = 2, skill_id: str | None = None, min_threshold: float = 0.0) -> list[dict]:
        """Search similar historical errors and their corresponding fix patches with hybrid matching."""
        embedder = self._get_embedder()
        if not embedder:
            return []
            
        query_vector = embedder.encode(query).tolist()
        tenant_suffix = self._get_tenant_suffix()
        col = self._get_em_collection(tenant_suffix)
        
        raw_candidates = []
        if self.connected and col:
            try:
                search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
                results = col.search(
                    data=[query_vector],
                    anns_field="vector",
                    param=search_params,
                    limit=limit * 3,  # Retrieve more candidates for reranking
                    output_fields=["task_id", "prompt", "error_stack", "patch"]
                )
                
                for hit in results[0]:
                    raw_candidates.append({
                        "task_id": hit.entity.get("task_id"),
                        "prompt": hit.entity.get("prompt"),
                        "error_stack": hit.entity.get("error_stack"),
                        "patch": hit.entity.get("patch"),
                        "score": hit.distance
                    })
            except Exception as e:
                logger.error("Failed to query Milvus episodic memory", tenant=tenant_suffix, error=str(e))
                return []
        else:
            # Local cosine similarity fallback
            import numpy as np
            q_vec = np.array(query_vector)
            tenant_data = self._get_local_data(tenant_suffix)
            for item in tenant_data["em"]:
                i_vec = np.array(item["vector"])
                dot = np.dot(q_vec, i_vec)
                norm_q = np.linalg.norm(q_vec)
                norm_i = np.linalg.norm(i_vec)
                sim = dot / (norm_q * norm_i) if norm_q > 0 and norm_i > 0 else 0.0
                raw_candidates.append({
                    "task_id": item["task_id"],
                    "prompt": item["prompt"],
                    "error_stack": item["error_stack"],
                    "patch": item["patch"],
                    "score": sim
                })

        # Apply hybrid scoring and reranking
        import re
        def calc_lexical(t1: str, t2: str) -> float:
            words1 = set(re.findall(r'\w+', t1.lower()))
            words2 = set(re.findall(r'\w+', t2.lower()))
            if not words1 or not words2:
                return 0.0
            return len(words1.intersection(words2)) / len(words1.union(words2))

        exception_types = ["ModuleNotFoundError", "FileNotFoundError", "ConnectionError", "PermissionError", "KeyError", "ValueError", "TypeError", "ZeroDivisionError"]

        reranked_results = []
        for cand in raw_candidates:
            # Deserialize skill_id and task_id
            cand_task_id = cand["task_id"]
            cand_skill_id = None
            if cand_task_id and "::" in cand_task_id:
                cand_skill_id, cand_task_id = cand_task_id.split("::", 1)

            semantic_sim = cand["score"]
            lexical_sim = calc_lexical(query, cand["error_stack"] or "")
            
            # Boost calculations
            skill_boost = 0.15 if (skill_id and cand_skill_id == skill_id) else 0.0
            
            exception_boost = 0.0
            for exc in exception_types:
                if exc in query and exc in (cand["error_stack"] or ""):
                    exception_boost = 0.1
                    break

            # Calculate hybrid score
            hybrid_score = 0.5 * semantic_sim + 0.3 * lexical_sim + skill_boost + exception_boost
            hybrid_score = min(max(hybrid_score, 0.0), 1.0)

            if hybrid_score >= min_threshold:
                reranked_results.append({
                    "task_id": cand_task_id,
                    "skill_id": cand_skill_id,
                    "prompt": cand["prompt"],
                    "error_stack": cand["error_stack"],
                    "patch": cand["patch"],
                    "score": hybrid_score
                })

        # Sort by hybrid score descending
        reranked_results.sort(key=lambda x: x["score"], reverse=True)
        return reranked_results[:limit]

    def upsert_skill(self, skill_id: str, name: str, description: str):
        """Insert or update a skill embedding in Milvus or local registry."""
        embedder = self._get_embedder()
        if not embedder:
            logger.error("RAG error: Embedder not initialized")
            return

        text_to_embed = f"Skill: {name}\nDescription: {description}"
        vector = embedder.encode(text_to_embed).tolist()
        tenant_suffix = self._get_tenant_suffix()
        skill_name = self._get_skills_collection_name(tenant_suffix)

        if self.connected and self.client and not isinstance(self.client, MockMilvusClient):
            try:
                # Delete existing if present to ensure clean update
                self.client.delete(
                    collection_name=skill_name,
                    filter=f"skill_id == '{skill_id}'"
                )
                
                # Insert new embedding
                data = [{
                    "vector": vector,
                    "skill_id": skill_id,
                    "name": name,
                    "description": description
                }]
                self.client.insert(collection_name=skill_name, data=data)
                logger.info("Upserted skill embedding to Milvus under tenant context", tenant=tenant_suffix, skill_id=skill_id)
            except Exception as e:
                logger.error("Failed to upsert skill embedding in Milvus", tenant=tenant_suffix, skill_id=skill_id, error=str(e))
        
        # Always update local fallback list so MockMilvusClient can search it
        tenant_data = self._get_local_data(tenant_suffix)
        tenant_data["skills"] = [s for s in tenant_data["skills"] if s["skill_id"] != skill_id]
        tenant_data["skills"].append({
            "vector": vector,
            "skill_id": skill_id,
            "name": name,
            "description": description
        })
        self._save_local_storage()
        logger.info("Upserted skill embedding to local memory registry under tenant context", tenant=tenant_suffix, skill_id=skill_id)

    @property
    def local_kb(self) -> list:
        return self._get_local_data(self._get_tenant_suffix())["kb"]

    @local_kb.setter
    def local_kb(self, value: list):
        self._get_local_data(self._get_tenant_suffix())["kb"] = value

    @property
    def local_em(self) -> list:
        return self._get_local_data(self._get_tenant_suffix())["em"]

    @local_em.setter
    def local_em(self, value: list):
        self._get_local_data(self._get_tenant_suffix())["em"] = value

    @property
    def local_skills(self) -> list:
        return self._get_local_data(self._get_tenant_suffix())["skills"]

    @local_skills.setter
    def local_skills(self, value: list):
        self._get_local_data(self._get_tenant_suffix())["skills"] = value

    @property
    def kb_collection(self):
        return self._get_kb_collection(self._get_tenant_suffix())

    @kb_collection.setter
    def kb_collection(self, value):
        kb_name = f"kb_{self._get_tenant_suffix()}"
        self._kb_collections_cache[kb_name] = value

    @property
    def em_collection(self):
        return self._get_em_collection(self._get_tenant_suffix())

    @em_collection.setter
    def em_collection(self, value):
        em_name = f"em_{self._get_tenant_suffix()}"
        self._em_collections_cache[em_name] = value

    def __getattribute__(self, name):
        if name in ('local_kb', 'local_em', 'local_skills'):
            tenant_suffix = self._get_tenant_suffix()
            tenant_data = self._get_local_data(tenant_suffix)
            return tenant_data[name[6:]]
        if name == 'kb_collection':
            return self._get_kb_collection(self._get_tenant_suffix())
        if name == 'em_collection':
            return self._get_em_collection(self._get_tenant_suffix())
        return super().__getattribute__(name)

    def __setattr__(self, name, value):
        if name in ('local_kb', 'local_em', 'local_skills'):
            tenant_suffix = self._get_tenant_suffix()
            tenant_data = self._get_local_data(tenant_suffix)
            tenant_data[name[6:]] = value
            return
        if name == 'kb_collection':
            kb_name = self._get_kb_name(self._get_tenant_suffix())
            self._kb_collections_cache[kb_name] = value
            return
        if name == 'em_collection':
            em_name = self._get_em_name(self._get_tenant_suffix())
            self._em_collections_cache[em_name] = value
            return
        super().__setattr__(name, value)

    def close(self):
        """Release collections and disconnect from Milvus."""
        self._kb_collections_cache.clear()
        self._em_collections_cache.clear()
        self._skills_collections_cache.clear()
        if self.connected:
            try:
                connections.disconnect("default")
            except Exception:
                pass
            self.connected = False
        logger.info("RAGManager connections and collections closed")


# Global singleton
rag_manager = RAGManager()
