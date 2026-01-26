from src.utils import sanitize_outputs
import json


def test_secret_redaction():
    # Setup malicious output
    data = [
        {
            "output_type": "stream",
            "name": "stdout",
            "text": "My API key is sk-1234567890abcdef1234567890abcdef\nNext line.",
        }
    ]

    result = sanitize_outputs(data, "assets")
    # Normally sanitize_outputs returns a JSON string of a list or similar structure depending on implementation
    # Let's inspect the actual implementation return type:
    # It returns a JSON List[str] usually (llm_summary) inside a string?
    # No, sanitize_outputs returns a JSON string containing {"llm_summary": [...], "raw_outputs": [...]}

    # Wait, looking at utils.py again:
    # return json.dumps({ "llm_summary": llm_summary, "raw_outputs": raw_outputs }, indent=2)

    res_dict = json.loads(result)
    text = res_dict["llm_summary"]

    assert len(text) > 0
    assert "sk-" not in text
    assert "[REDACTED_SECRET]" in text


def test_truncation():
    # Create long output
    long_text = "A" * 5000
    data = [{"output_type": "execute_result", "data": {"text/plain": long_text}}]

    result = sanitize_outputs(data, "assets")
    res_dict = json.loads(result)
    text = res_dict["llm_summary"]

    assert len(text) > 0
    assert len(text) < 5000
    # assert "[TRUNCATED - Use inspect_variable() for full output]" in text
    assert "SAVED TO" in text
    assert "FULL OUTPUT" in text
