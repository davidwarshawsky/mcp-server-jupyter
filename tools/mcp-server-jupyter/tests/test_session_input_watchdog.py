from src.session import SessionManager
from src.notebook import create_notebook


def test_submit_input_clears_watchdog(tmp_path):
    nb_path = tmp_path / "test.ipynb"
    create_notebook(str(nb_path), initial_cells=[{"type": "code", "content": "x=1"}])

    sm = SessionManager()
    # Simulate session data
    abs_path = str(nb_path.resolve())
    sm.sessions[abs_path] = {
        "waiting_for_input": True,
        "kc": None,
    }

    # Call submit_input (should clear flag even if kc is None)
    import asyncio

    asyncio.run(sm.submit_input(str(nb_path), "test"))

    assert sm.sessions[abs_path]["waiting_for_input"] is False
