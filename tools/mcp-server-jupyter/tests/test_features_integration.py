import pytest
import asyncio
from pathlib import Path
from .harness import MCPServerHarness

# NOTE: These integration tests were designed to test broadcaster notifications
# (notebook/output messages) through a stdio harness, which doesn't work.
# Broadcaster notifications are WebSocket-only. Use test_comprehensive_async.py
# or other test suites for integration tests that don't rely on stdio harness.
# Keeping this file for future WebSocket-based integration tests.

pytestmark = pytest.mark.skip(reason="Stdio harness cannot receive broadcaster notifications. Use WebSocket integration tests instead.")
