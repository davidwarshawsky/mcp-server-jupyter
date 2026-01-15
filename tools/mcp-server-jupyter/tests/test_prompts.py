import pytest
from src.main import jupyter_expert, autonomous_researcher

def test_jupyter_expert_prompt_loads():
    """Verify the Jupyter Expert prompt loads from disk."""
    messages = jupyter_expert()
    assert len(messages) == 1
    text = messages[0].content.text
    assert "Jupyter Expert" in text
    assert "detect_sync_needed" in text
    assert "search_notebook" in text
    assert "inspect_variable" in text

def test_autonomous_researcher_prompt_loads():
    """Verify the Autonomous Researcher prompt loads from disk."""
    messages = autonomous_researcher()
    assert len(messages) == 1
    text = messages[0].content.text
    assert "Autonomous Jupyter Researcher" in text
    assert "OODA" in text
    assert "OBSERVE" in text
    assert "ORIENT" in text
    assert "DECIDE" in text
    assert "ACT" in text

def test_prompts_contain_tool_references():
    """Verify prompts reference the new agent-ready tools."""
    expert_text = jupyter_expert()[0].content.text
    researcher_text = autonomous_researcher()[0].content.text
    
    # Both should mention the new tools
    for text in [expert_text, researcher_text]:
        assert "install_package" in text
        assert "inspect_variable" in text
        assert "search_notebook" in text

def test_prompt_structure():
    """Verify prompts have proper MCP message structure."""
    for prompt_func in [jupyter_expert, autonomous_researcher]:
        messages = prompt_func()
        assert isinstance(messages, list)
        assert len(messages) == 1
        
        msg = messages[0]
        assert msg.role == "user"
        assert hasattr(msg.content, 'text')
        assert len(msg.content.text) > 100  # Non-trivial content
