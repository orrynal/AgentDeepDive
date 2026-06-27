import pytest
from src.core.memory.rag_manager import RAGManager, MockMilvusClient
from pymilvus import DataType

@pytest.fixture(autouse=True)
def isolate_rag_storage(monkeypatch, tmp_path):
    storage_dir = tmp_path / ".memory"
    storage_file = storage_dir / "rag_storage.json"
    
    # Isolate global singleton
    from src.core.memory.rag_manager import rag_manager
    monkeypatch.setattr(rag_manager, "storage_dir", storage_dir)
    monkeypatch.setattr(rag_manager, "storage_file", storage_file)
    rag_manager.local_kb = []
    rag_manager.local_em = []
    rag_manager.local_skills = []
    
    # Isolate any new instances
    original_init = RAGManager.__init__
    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.storage_dir = storage_dir
        self.storage_file = storage_file
        self.local_kb = []
        self.local_em = []
        self.local_skills = []
    monkeypatch.setattr(RAGManager, "__init__", patched_init)


def test_rag_manager_local_mode(monkeypatch):
    # Mock Milvus connection to raise an exception to trigger the local mock fallback
    def mock_connect_fail(*args, **kwargs):
        raise Exception("Connection refused")
    monkeypatch.setattr("src.core.memory.rag_manager.connections.connect", mock_connect_fail)

    manager = RAGManager()
    assert manager.connected is False
    assert isinstance(manager.client, MockMilvusClient)
    
    # 1. Index document (Local KB)
    doc_text = "This is a document about lock managers in Python. It handles concurrency."
    manager.index_document(doc_text, "docs/lock_manager.md")
    
    assert len(manager.local_kb) > 0
    assert manager.local_kb[0]["source"] == "docs/lock_manager.md"
    assert "lock managers" in manager.local_kb[0]["text"]

    # 2. Query Knowledge Base
    res = manager.query_knowledge_base("lock concurrency", limit=1)
    assert "docs/lock_manager.md" in res
    assert "Similarity Score" in res

    # 3. Save and query Episodic Memory
    manager.save_episodic_memory(
        task_id="task-1",
        prompt="Write a lock manager",
        error_stack="FileExistsError: lock file exists",
        patch="Use acquire with priority preemption"
    )
    
    assert len(manager.local_em) == 1
    assert manager.local_em[0]["task_id"] == "task-1"
    
    episodes = manager.query_episodic_memory("FileExistsError", limit=1)
    assert len(episodes) == 1
    assert episodes[0]["task_id"] == "task-1"
    assert episodes[0]["patch"] == "Use acquire with priority preemption"

    # 4. Upsert skill and verify MockMilvusClient search
    manager.upsert_skill(
        skill_id="skill-lock",
        name="Lock Manager Skill",
        description="Manages concurrent file locks"
    )
    assert len(manager.local_skills) == 1
    assert manager.local_skills[0]["skill_id"] == "skill-lock"

    # Test MockMilvusClient local search
    mock_vector = [0.1] * 384
    search_results = manager.client.search(
        collection_name="skill_embeddings",
        data=[mock_vector],
        limit=1,
        output_fields=["skill_id", "name"]
    )
    assert len(search_results) == 1
    assert len(search_results[0]) == 1
    assert search_results[0][0]["entity"]["skill_id"] == "skill-lock"

def test_rag_manager_milvus_mode(monkeypatch):
    class MockHit:
        def __init__(self, text, source, distance=0.95):
            self.entity = {"text": text, "source": source}
            self.distance = distance

    class MockCollection:
        def __init__(self, name, schema=None):
            self.name = name
            self.inserted_data = []

        def load(self, timeout=None):
            pass

        def insert(self, data):
            self.inserted_data.append(data)

        def flush(self):
            pass

        def search(self, data, anns_field, param, limit, output_fields):
            # We mock the return structure of milvus search
            if self.name == "agentdeep_knowledge_base":
                return [[MockHit("Retrieved static knowledge", "milvus_kb_source")]]
            else:
                # episodic memory
                class MockEpisodicHit:
                    def __init__(self):
                        self.entity = {
                            "task_id": "task-milvus",
                            "prompt": "run command",
                            "error_stack": "ConnectionError",
                            "patch": "retry with backoff"
                        }
                        self.distance = 0.88
                return [[MockEpisodicHit()]]

    class MockedMilvusClient:
        def __init__(self, *args, **kwargs):
            self.upserted_data = []
            self.deleted_filters = []

        def has_collection(self, collection_name):
            return True

        def load_collection(self, collection_name, timeout=5.0):
            pass

        def delete(self, collection_name, filter):
            self.deleted_filters.append(filter)

        def insert(self, collection_name, data):
            self.upserted_data.append(data)

    # Mock all milvus module elements before initializing RAGManager
    monkeypatch.setattr("src.core.memory.rag_manager.connections.connect", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.core.memory.rag_manager.utility.has_collection", lambda name: True)
    monkeypatch.setattr("src.core.memory.rag_manager.Collection", MockCollection)
    monkeypatch.setattr("src.core.memory.rag_manager.MilvusClient", MockedMilvusClient)

    # Initialize manager under Milvus connected=True mock
    manager = RAGManager()
    assert manager.connected is True
    assert isinstance(manager.client, MockedMilvusClient)

    # 1. Index document (Milvus KB)
    manager.index_document("Milvus document text", "milvus_doc.md")
    assert len(manager.kb_collection.inserted_data) > 0

    # 2. Query Knowledge Base
    res = manager.query_knowledge_base("Milvus query")
    assert "milvus_kb_source" in res
    assert "Retrieved static knowledge" in res

    # 3. Save and query Episodic Memory (Milvus EM)
    manager.save_episodic_memory("task-milvus", "run", "ConnectionError", "retry")
    assert len(manager.em_collection.inserted_data) > 0

    episodes = manager.query_episodic_memory("ConnectionError")
    assert len(episodes) == 1
    assert episodes[0]["task_id"] == "task-milvus"
    assert episodes[0]["patch"] == "retry with backoff"

    # 4. Upsert skill (Milvus client)
    manager.upsert_skill("skill-milvus", "Milvus Skill", "Performs database operations")
    assert "skill_id == 'skill-milvus'" in manager.client.deleted_filters
    assert len(manager.client.upserted_data) == 1
    assert manager.client.upserted_data[0][0]["skill_id"] == "skill-milvus"


def test_rag_manager_lightweight_mode_persistence(monkeypatch):
    # Force system_mode to lightweight
    from src.config import settings
    monkeypatch.setattr(settings, "system_mode", "lightweight")
    
    # Initialize RAGManager
    manager = RAGManager()
    assert manager.connected is False
    
    # Index document and save episodic memory
    manager.index_document("Test persistent text", "persistent_doc.md")
    manager.save_episodic_memory("task-persistent", "run", "PersistError", "fix-persist")
    manager.upsert_skill("skill-persistent", "Persistent Skill", "Does persistent stuff")
    
    # Verify file is written
    assert manager.storage_file.exists()
    
    # Create a new manager instance and verify it loads the data back
    manager2 = RAGManager()
    manager2._load_local_storage()
    
    assert len(manager2.local_kb) > 0
    assert manager2.local_kb[0]["source"] == "persistent_doc.md"
    assert len(manager2.local_em) == 1
    assert manager2.local_em[0]["task_id"] == "task-persistent"
    assert len(manager2.local_skills) == 1
    assert manager2.local_skills[0]["skill_id"] == "skill-persistent"


def test_rag_manager_hybrid_recall(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "system_mode", "lightweight")
    
    manager = RAGManager()
    assert manager.connected is False

    # Save multiple episodic memories
    manager.save_episodic_memory(
        task_id="task-A",
        prompt="parse yaml file",
        error_stack="ModuleNotFoundError: No module named 'yaml'",
        patch="pip install pyyaml",
        skill_id="yaml_parser"
    )
    manager.save_episodic_memory(
        task_id="task-B",
        prompt="fetch user profile",
        error_stack="ModuleNotFoundError: No module named 'requests'",
        patch="pip install requests",
        skill_id="http_client"
    )
    manager.save_episodic_memory(
        task_id="task-C",
        prompt="make api call",
        error_stack="ConnectionRefusedError: failed to connect to localhost",
        patch="retry request with backoff",
        skill_id="http_client"
    )

    # 1. Test Lexical overlap ranking: "requests" error query should rank task-B first
    results = manager.query_episodic_memory("ModuleNotFoundError: No module named 'requests'", limit=2)
    assert len(results) >= 1
    assert results[0]["task_id"] == "task-B"
    assert results[0]["skill_id"] == "http_client"

    # 2. Test Skill ID boost: Querying for "ConnectionRefusedError" with skill_id="http_client"
    results_boosted = manager.query_episodic_memory(
        query="ConnectionRefusedError: connection issue",
        limit=2,
        skill_id="http_client"
    )
    assert len(results_boosted) >= 1
    assert results_boosted[0]["task_id"] == "task-C"

    # 3. Test min_threshold filtering
    # A very high threshold of 0.95 should filter out all or most candidates
    results_high_thresh = manager.query_episodic_memory(
        query="Some completely random error stack",
        limit=2,
        min_threshold=0.9
    )
    assert len(results_high_thresh) == 0

