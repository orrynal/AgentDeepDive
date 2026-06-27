import os
import structlog
from pathlib import Path
from src.core.memory.rag_manager import rag_manager

logger = structlog.get_logger()

def index_project_directory(root_dir: str):
    """Scan and index all markdown documentation and python code files in the project workspace."""
    root = Path(root_dir)
    logger.info("Starting project indexing for semantic RAG database...", root_dir=root_dir)
    
    # 1. Index documentation files (*.md)
    docs_dir = root / "docs"
    doc_count = 0
    if docs_dir.exists():
        for path in docs_dir.rglob("*.md"):
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                relative_path = os.path.relpath(path, root_dir)
                rag_manager.index_document(content, source=relative_path)
                doc_count += 1
            except Exception as e:
                logger.error("Failed to index doc file", path=str(path), error=str(e))
                
    # 2. Index source files (*.py)
    src_dir = root / "src"
    py_count = 0
    if src_dir.exists():
        for path in src_dir.rglob("*.py"):
            # Skip virtual environments or cache directories
            if ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                relative_path = os.path.relpath(path, root_dir)
                rag_manager.index_document(content, source=relative_path)
                py_count += 1
            except Exception as e:
                logger.error("Failed to index source file", path=str(path), error=str(e))
                
    logger.info("Finished project indexing.", indexed_docs=doc_count, indexed_py_files=py_count)

if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    index_project_directory(project_root)
