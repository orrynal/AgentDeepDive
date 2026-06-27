"""API routes for managing Open Policy Agent (OPA) Rego safety policies."""

import os
import re
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
import structlog

from src.api.security import verify_api_key
from src.core.governance.guardrails import GuardrailEngine

logger = structlog.get_logger()
router = APIRouter()

# Get policy path relative to this routing file
# src/api/routes/opa.py -> src/core/governance/policies/guardrails.rego
POLICY_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "core",
        "governance",
        "policies",
        "guardrails.rego"
    )
)


class PolicyUpdate(BaseModel):
    policy_content: str


class PolicyTestRequest(BaseModel):
    policy_content: str
    mock_input: dict


@router.get("/opa/policy", dependencies=[Depends(verify_api_key)])
async def get_opa_policy():
    """Retrieve the current content of the Rego guardrails policy."""
    if not os.path.exists(POLICY_PATH):
        raise HTTPException(
            status_code=404,
            detail="OPA Rego policy file not found on server."
        )
    try:
        with open(POLICY_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return {"policy_content": content, "file_path": POLICY_PATH}
    except Exception as e:
        logger.error("Failed to read Rego policy file", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Error reading Rego policy file: {str(e)}"
        )


@router.put("/opa/policy", dependencies=[Depends(verify_api_key)])
async def update_opa_policy(update: PolicyUpdate):
    """Update the Rego policy on disk and upload/push it to the running OPA engine."""
    if not os.path.exists(POLICY_PATH):
        # Create directory if missing
        os.makedirs(os.path.dirname(POLICY_PATH), exist_ok=True)

    try:
        # 1. Write updated content to disk
        with open(POLICY_PATH, "w", encoding="utf-8") as f:
            f.write(update.policy_content)
        
        # 2. Re-trigger upload to OPA via GuardrailEngine
        engine = GuardrailEngine()
        upload_success = engine._upload_policy_to_opa()

        return {
            "success": True,
            "uploaded_to_opa": upload_success,
            "message": "Policy updated successfully on disk and pushed to OPA engine." if upload_success else "Policy updated on disk, but failed to push to OPA (is OPA running?)."
        }
    except Exception as e:
        logger.error("Failed to update Rego policy", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Error updating Rego policy: {str(e)}"
        )


@router.post("/opa/test", dependencies=[Depends(verify_api_key)])
async def test_opa_policy(request: PolicyTestRequest):
    """Test a draft Rego policy against a mock input, without modifying the production policy on disk."""
    from src.config import settings
    if not settings.opa_enabled:
        raise HTTPException(
            status_code=400,
            detail="OPA engine is disabled in config."
        )

    # 1. Modify package name to isolate the test policy
    test_rego = request.policy_content
    test_rego = re.sub(r"\bpackage\s+guardrails\b", "package guardrails_test", test_rego)

    import urllib.request
    import json

    # 2. Upload test policy to OPA
    opa_url = settings.opa_url.rstrip("/")
    put_url = f"{opa_url}/v1/policies/guardrails_test"
    eval_url = f"{opa_url}/v1/data/guardrails_test/risk_level"

    if not (put_url.startswith("http://") or put_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid OPA URL protocol scheme")
    if not (eval_url.startswith("http://") or eval_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid OPA URL protocol scheme")

    try:
        req = urllib.request.Request(
            put_url,
            data=test_rego.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            method="PUT"
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:  # nosec B310
            if resp.status not in [200, 201]:
                raise Exception(f"OPA returned HTTP {resp.status} on policy upload")
    except Exception as e:
        logger.error("Failed to upload test policy to OPA", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload test policy to OPA: {str(e)}"
        )

    # 3. Evaluate mock input against test policy
    decision = None
    eval_error = None
    try:
        # Wrap the mock input in a {"input": ...} wrapper if not already wrapped
        input_body = request.mock_input
        if "input" not in input_body:
            input_body = {"input": input_body}

        req = urllib.request.Request(
            eval_url,
            data=json.dumps(input_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:  # nosec B310
            if resp.status == 200:
                result = json.loads(resp.read().decode("utf-8"))
                decision = result.get("result")
    except Exception as e:
        logger.error("Failed to evaluate test policy in OPA", error=str(e))
        eval_error = str(e)
    finally:
        # 4. Clean up test policy
        try:
            req = urllib.request.Request(put_url, method="DELETE")
            with urllib.request.urlopen(req, timeout=2.0):  # nosec B310
                pass
        except Exception as e:
            logger.warning("Failed to clean up OPA test policy", error=str(e))

    if eval_error:
        raise HTTPException(
            status_code=500,
            detail=f"Evaluation failed: {eval_error}"
        )

    return {
        "success": True,
        "risk_level": decision or "L1",
    }
