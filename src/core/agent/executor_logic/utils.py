import json
import re

def extract_critical_log_context(output: str, max_chars: int = 4000) -> str:
    """Smartly filter and extract critical error context (Tracebacks, compiler errors) from tool outputs if they are too long."""
    if len(output) <= max_chars:
        return output

    # Check if this is a JSON-encoded tool result
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            # Process stdout/stderr/output/error individually if present
            changed = False
            for key in ["stdout", "stderr", "output", "error"]:
                if key in data and isinstance(data[key], str) and len(data[key]) > max_chars // 2:
                    data[key] = _extract_text_error_context(data[key])
                    changed = True
            if changed:
                return json.dumps(data, ensure_ascii=False)
    except Exception:
        pass

    return _extract_text_error_context(output)


def _extract_text_error_context(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= 60:
        return text

    # Search for critical patterns (Traceback, error, fail, exception, etc.)
    error_patterns = [
        re.compile(r"traceback\s*\(most\s*recent\s*call\s*last\)", re.IGNORECASE),
        re.compile(r"error|fail|exception|failed|invalid|stderr", re.IGNORECASE),
        re.compile(r"\b(err|failed)\b", re.IGNORECASE)
    ]
    
    important_indices = set()
    for idx, line in enumerate(lines):
        for pattern in error_patterns:
            if pattern.search(line):
                # Add window of 5 lines before and 15 lines after
                for offset in range(-5, 16):
                    n_idx = idx + offset
                    if 0 <= n_idx < len(lines):
                        important_indices.add(n_idx)
                break
                
    if not important_indices:
        # Fallback: keep first 20 and last 30 lines
        return "\n".join(lines[:20]) + "\n\n... [TRUNCATED - NO CRITICAL PATTERNS FOUND] ...\n\n" + "\n".join(lines[-30:])

    # Sort indices and group into contiguous segments
    sorted_indices = sorted(list(important_indices))
    segments = []
    current_segment = []
    
    for idx in sorted_indices:
        if not current_segment or idx == current_segment[-1] + 1:
            current_segment.append(idx)
        else:
            segments.append(current_segment)
            current_segment = [idx]
    if current_segment:
        segments.append(current_segment)
        
    # Build filtered output
    result_parts = []
    if segments[0][0] > 0:
        result_parts.append(f"... [TRUNCATED {segments[0][0]} LINES] ...")
        
    for i, seg in enumerate(segments):
        seg_text = "\n".join(lines[idx] for idx in seg)
        result_parts.append(seg_text)
        if i < len(segments) - 1:
            gap = segments[i+1][0] - seg[-1] - 1
            if gap > 0:
                result_parts.append(f"\n... [TRUNCATED {gap} LINES] ...\n")
                
    if segments[-1][-1] < len(lines) - 1:
        gap = len(lines) - 1 - segments[-1][-1]
        result_parts.append(f"... [TRUNCATED {gap} LINES] ...")
        
    return "\n".join(result_parts)
