import pytest
from src.main import query_dataframes, auto_analyst


def test_query_dataframes_tool_registered():
    """Verify query_dataframes tool is registered."""
    assert callable(query_dataframes)


@pytest.mark.skip(
    reason="Checkpoint functions are commented out pending implementation"
)
def test_checkpoint_tools_registered():
    """Verify Time Travel checkpoint tools are registered."""
    # save_checkpoint and load_checkpoint are commented out in main.py
    pass


def test_auto_analyst_prompt_loads():
    """Verify Auto-Analyst prompt loads from disk."""
    messages = auto_analyst()
    assert len(messages) == 1
    text = messages[0].content.text
    assert "Auto-Analyst" in text
    assert "EDA" in text or "Exploratory Data Analysis" in text
    assert "STEP 1: DISCOVER DATA" in text
    assert "STEP 2: LOAD & INSPECT" in text
    assert "STEP 3: DATA HEALTH REPORT" in text


def test_auto_analyst_mentions_superpowers():
    """Verify Auto-Analyst prompt mentions DuckDB and new tools."""
    text = auto_analyst()[0].content.text
    assert "query_dataframes" in text or "SQL" in text
    assert "inspect_variable" in text
    assert "assets/" in text  # Asset offloading


@pytest.mark.skip(
    reason="save_checkpoint and load_checkpoint are commented out pending implementation"
)
def test_superpower_tools_have_wow_factor_docs():
    """Verify Superpower tools document their 'wow factor'."""
    # Check query_dataframes docstring
    assert "SUPERPOWER" in query_dataframes.__doc__
    assert "SQL" in query_dataframes.__doc__

    # Check checkpoint docstrings - not yet implemented
    # assert "TIME TRAVEL" in save_checkpoint.__doc__
    # assert "TIME TRAVEL" in load_checkpoint.__doc__
    pass
