import numpy as np
from src.core.memory.rag_manager import MockMilvusClient

def test_mock_milvus_client_reassignment():
    # 1. Create a list and pass it to MockMilvusClient via a lambda
    local_skills = [
        {
            "vector": [1.0, 0.0, 0.0],
            "skill_id": "skill-1",
            "name": "Skill 1",
            "description": "First skill"
        }
    ]
    
    client = MockMilvusClient(lambda: local_skills)
    
    # 2. Query before reassignment
    res = client.search(
        collection_name="skill_embeddings",
        data=[[1.0, 0.0, 0.0]],
        limit=2,
        output_fields=["skill_id"]
    )
    assert len(res[0]) == 1
    assert res[0][0]["entity"]["skill_id"] == "skill-1"
    assert res[0][0]["distance"] == 1.0

    # 3. Reassign local_skills list (creates new list object)
    local_skills = [
        {
            "vector": [0.0, 1.0, 0.0],
            "skill_id": "skill-2",
            "name": "Skill 2",
            "description": "Second skill"
        }
    ]

    # 4. Query after reassignment - should resolve to the new list
    res_after = client.search(
        collection_name="skill_embeddings",
        data=[[0.0, 1.0, 0.0]],
        limit=2,
        output_fields=["skill_id"]
    )
    assert len(res_after[0]) == 1
    assert res_after[0][0]["entity"]["skill_id"] == "skill-2"
    assert res_after[0][0]["distance"] == 1.0
