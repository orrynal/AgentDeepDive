import base64
import json
from pathlib import Path
import litellm
import structlog
from src.config import settings

logger = structlog.get_logger()

# Suppress debug logs
litellm.suppress_debug_info = True

def encode_image(image_path: Path) -> str:
    """Read image file and convert to base64 string."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

async def verify_visuals_with_vlm(dag, node, screenshot_virtual_path: str | None) -> dict:
    """Uses a vision model to verify UI correctness from screenshot.
    
    Returns a dict with {"success": bool, "details": str}.
    """
    verification_config = node.constraints.get("verification", {})
    vlm_checks = verification_config.get("vlm_checks", [])
    
    if not vlm_checks or not screenshot_virtual_path:
        return {"success": True, "details": "No VLM visual verification rules defined."}
        
    # Map virtual path to actual filesystem path in dashboard/public
    dashboard_public_dir = Path(settings.resolved_workspace_path) / "dashboard" / "public"
    actual_path = dashboard_public_dir / screenshot_virtual_path.lstrip("/")
    
    if not actual_path.exists():
        return {"success": False, "details": f"VLM Verification failed: Screenshot not found at {actual_path}."}
        
    logger.info("Starting VLM visual auditing", node_id=node.node_id, checks_count=len(vlm_checks))
    
    try:
        base64_image = encode_image(actual_path)
    except Exception as e:
        return {"success": False, "details": f"Failed to encode screenshot: {str(e)}"}
        
    # Build prompt from visual check rules
    rules_text = ""
    for idx, check in enumerate(vlm_checks):
        rules_text += f"- Rule [{idx}]: Prompt: '{check.get('prompt')}' | Expected Value: '{check.get('expect')}'\n"
        
    system_prompt = (
        "You are an expert Frontend QA Visual Auditor Agent.\n"
        "Analyze the provided screenshot of the application state and evaluate the list of visual validation rules.\n"
        "You must respond in valid JSON format with the following schema:\n"
        "{\n"
        "  \"success\": true/false,\n"
        "  \"details\": \"A detailed analysis explaining why the rules passed or failed.\"\n"
        "}"
    )
    
    user_prompt = (
        f"Please verify the following visual validation rules against the screenshot:\n\n"
        f"{rules_text}\n"
        f"Respond strictly in JSON matching the requested schema."
    )
    
    # Configure model: use configured visual model or fall back to gpt-4o/gemini
    model_name = settings.ux_visual_model or settings.fallback_model or "gpt-4o"
    
    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    }
                ]
            }
        ]
        
        logger.info("Calling vision model for audit", model=model_name)
        response = await litellm.acompletion(
            model=model_name,
            messages=messages,
            temperature=0.1,
            max_tokens=1000,
            response_format={"type": "json_object"}
        )
        
        res_text = response.choices[0].message.content
        result_data = json.loads(res_text)
        
        success = result_data.get("success", False)
        details = result_data.get("details", "No detailed audit logs returned.")
        
        logger.info("VLM Visual Audit completed", success=success, details=details)
        return {"success": success, "details": details}
        
    except Exception as api_err:
        logger.error("VLM visual audit call failed", error=str(api_err))
        return {
            "success": False,
            "details": f"VLM model call failed: {str(api_err)}. Visual state could not be verified automatically."
        }
