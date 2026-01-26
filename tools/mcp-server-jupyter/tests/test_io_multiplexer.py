"""
Tests for IOMultiplexer component.

Phase 2.3: Validates I/O message routing extracted from SessionManager.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.io_multiplexer import IOMultiplexer


class MockKernelClient:
    """Mock Jupyter kernel client for testing."""

    def __init__(self):
        self.messages = []
        self.stdin_channel = MagicMock()
        self.stdin_channel.is_alive.return_value = True
        self.stdin_channel.msg_ready = AsyncMock(return_value=False)

    async def get_iopub_msg(self):
        """Pop message from queue."""
        if not self.messages:
            await asyncio.sleep(0.1)  # Simulate waiting
            raise asyncio.CancelledError("No messages")
        return self.messages.pop(0)

    def add_message(self, msg_type, parent_id, content):
        """Add a message to the queue."""
        self.messages.append(
            {
                "msg_type": msg_type,
                "parent_header": {"msg_id": parent_id},
                "content": content,
                "header": {"msg_type": msg_type},
            }
        )

    def input(self, text):
        """Mock input() response."""
        pass


@pytest.mark.asyncio
class TestIOMultiplexerBasics:
    """Test IOMultiplexer initialization and basic functionality."""

    async def test_initialization(self):
        """IOMultiplexer should initialize with configurable input timeout."""
        mux = IOMultiplexer(input_request_timeout=30)
        assert mux.input_request_timeout == 30

    async def test_shutdown_signal(self):
        """IOPub listener should stop on CancelledError."""
        mux = IOMultiplexer()
        kc = MockKernelClient()

        # Empty executions dict - listener will wait forever
        executions = {}
        session_data = {"listener_healthy": True}

        # Start listener
        listener_task = asyncio.create_task(
            mux.listen_iopub("test.ipynb", kc, executions, session_data)
        )

        # Give it time to start
        await asyncio.sleep(0.01)

        # Cancel
        listener_task.cancel()

        # Should exit gracefully (no raise, task just ends)
        try:
            await listener_task
        except asyncio.CancelledError:
            pass  # Expected

        # Verify task is done
        assert listener_task.done()


@pytest.mark.asyncio
class TestMessageRouting:
    """Test message routing to correct executions."""

    async def test_route_stream_output(self):
        """Stream messages should be converted to nbformat and broadcasted."""
        mux = IOMultiplexer()
        kc = MockKernelClient()

        exec_id = "test-exec-1"
        executions = {
            exec_id: {
                "id": "task-1",
                "cell_index": 0,
                "outputs": [],
                "status": "running",
            }
        }
        session_data = {}

        # Add stream message
        kc.add_message("stream", exec_id, {"name": "stdout", "text": "Hello, world!\n"})

        # Mock broadcast
        broadcast_called = []

        async def mock_broadcast(msg):
            broadcast_called.append(msg)

        # Start listener
        listener_task = asyncio.create_task(
            mux.listen_iopub(
                "test.ipynb",
                kc,
                executions,
                session_data,
                broadcast_callback=mock_broadcast,
            )
        )

        # Wait for processing
        await asyncio.sleep(0.2)
        listener_task.cancel()

        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify output was appended
        assert len(executions[exec_id]["outputs"]) == 1
        output = executions[exec_id]["outputs"][0]
        assert output["output_type"] == "stream"
        assert output["name"] == "stdout"
        assert output["text"] == "Hello, world!\n"

        # Verify broadcast was called
        assert len(broadcast_called) == 1
        assert broadcast_called[0]["method"] == "notebook/output"

    async def test_route_error_output(self):
        """Error messages should set status to 'error' and create error output."""
        mux = IOMultiplexer()
        kc = MockKernelClient()

        exec_id = "test-exec-2"
        executions = {
            exec_id: {
                "id": "task-2",
                "cell_index": 1,
                "outputs": [],
                "status": "running",
            }
        }
        session_data = {}

        # Add error message
        kc.add_message(
            "error",
            exec_id,
            {
                "ename": "ValueError",
                "evalue": "Invalid input",
                "traceback": ["Traceback line 1", "Traceback line 2"],
            },
        )

        # Start listener
        listener_task = asyncio.create_task(
            mux.listen_iopub("test.ipynb", kc, executions, session_data)
        )

        # Wait for processing
        await asyncio.sleep(0.2)
        listener_task.cancel()

        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify error status
        assert executions[exec_id]["status"] == "error"

        # Verify error output
        assert len(executions[exec_id]["outputs"]) == 1
        output = executions[exec_id]["outputs"][0]
        assert output["output_type"] == "error"
        assert output["ename"] == "ValueError"
        assert output["evalue"] == "Invalid input"

    async def test_route_execute_result(self):
        """Execute result messages should include execution count."""
        mux = IOMultiplexer()
        kc = MockKernelClient()

        exec_id = "test-exec-3"
        executions = {
            exec_id: {
                "id": "task-3",
                "cell_index": 2,
                "outputs": [],
                "status": "running",
            }
        }
        session_data = {}

        # Add execute_result message
        kc.add_message(
            "execute_result",
            exec_id,
            {"execution_count": 5, "data": {"text/plain": "42"}, "metadata": {}},
        )

        # Start listener
        listener_task = asyncio.create_task(
            mux.listen_iopub("test.ipynb", kc, executions, session_data)
        )

        # Wait for processing
        await asyncio.sleep(0.2)
        listener_task.cancel()

        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify execution count was stored
        assert executions[exec_id]["execution_count"] == 5

        # Verify output
        assert len(executions[exec_id]["outputs"]) == 1
        output = executions[exec_id]["outputs"][0]
        assert output["output_type"] == "execute_result"
        assert output["execution_count"] == 5
        assert output["data"]["text/plain"] == "42"


@pytest.mark.asyncio
class TestStatusHandling:
    """Test kernel status message handling (idle/busy)."""

    async def test_status_idle_completes_execution(self):
        """Status 'idle' should mark execution as completed."""
        mux = IOMultiplexer()
        kc = MockKernelClient()

        exec_id = "test-exec-4"
        finalization_event = asyncio.Event()
        finalization_event.set()  # Allow immediate finalization

        executions = {
            exec_id: {
                "id": "task-4",
                "cell_index": 3,
                "outputs": [],
                "status": "running",
                "finalization_event": finalization_event,
            }
        }
        session_data = {"executed_indices": set()}

        # Add status idle message
        kc.add_message("status", exec_id, {"execution_state": "idle"})

        # Mock finalize callback
        finalize_called = []

        async def mock_finalize(nb_path, exec_data):
            finalize_called.append((nb_path, exec_data["id"]))

        # Start listener
        listener_task = asyncio.create_task(
            mux.listen_iopub(
                "test.ipynb",
                kc,
                executions,
                session_data,
                finalize_callback=mock_finalize,
            )
        )

        # Wait for processing
        await asyncio.sleep(0.2)
        listener_task.cancel()

        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify status changed to completed
        assert executions[exec_id]["status"] == "completed"

        # Verify finalize was called
        assert len(finalize_called) == 1
        assert finalize_called[0] == ("test.ipynb", "task-4")

        # Verify cell index was tracked
        assert 3 in session_data["executed_indices"]

    async def test_status_idle_preserves_error_status(self):
        """Status 'idle' should NOT override 'error' status."""
        mux = IOMultiplexer()
        kc = MockKernelClient()

        exec_id = "test-exec-5"
        finalization_event = asyncio.Event()
        finalization_event.set()

        executions = {
            exec_id: {
                "id": "task-5",
                "cell_index": 4,
                "outputs": [],
                "status": "error",  # Already marked as error
                "finalization_event": finalization_event,
            }
        }
        session_data = {}

        # Add status idle message
        kc.add_message("status", exec_id, {"execution_state": "idle"})

        # Start listener
        listener_task = asyncio.create_task(
            mux.listen_iopub("test.ipynb", kc, executions, session_data)
        )

        # Wait for processing
        await asyncio.sleep(0.2)
        listener_task.cancel()

        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify status is still 'error'
        assert executions[exec_id]["status"] == "error"


@pytest.mark.asyncio
class TestClearOutput:
    """Test clear_output message handling (for progress bars)."""

    async def test_clear_output_resets_outputs_list(self):
        """clear_output (wait=False) should reset outputs list."""
        mux = IOMultiplexer()
        kc = MockKernelClient()

        exec_id = "test-exec-6"
        executions = {
            exec_id: {
                "id": "task-6",
                "cell_index": 5,
                "outputs": [
                    {"output_type": "stream", "text": "Old output 1"},
                    {"output_type": "stream", "text": "Old output 2"},
                ],
                "status": "running",
            }
        }
        session_data = {}

        # Add clear_output message
        kc.add_message("clear_output", exec_id, {"wait": False})

        # Start listener
        listener_task = asyncio.create_task(
            mux.listen_iopub("test.ipynb", kc, executions, session_data)
        )

        # Wait for processing
        await asyncio.sleep(0.2)
        listener_task.cancel()

        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify outputs were cleared
        assert executions[exec_id]["outputs"] == []


@pytest.mark.asyncio
@pytest.mark.slow
class TestCircuitBreaker:
    """Test circuit breaker functionality for listener errors."""

    async def test_circuit_breaker_stops_after_5_errors(self):
        """Listener should exit after 5 consecutive errors."""
        mux = IOMultiplexer()
        kc = MockKernelClient()

        # Mock get_iopub_msg to always raise exception
        error_count = [0]

        async def mock_error():
            error_count[0] += 1
            raise RuntimeError("Simulated kernel error")

        kc.get_iopub_msg = mock_error

        executions = {}
        session_data = {"listener_healthy": True}

        # Start listener
        listener_task = asyncio.create_task(
            mux.listen_iopub("test.ipynb", kc, executions, session_data)
        )

        # Wait for circuit breaker to trip
        # The backoff timing is: 1s, 2s, 4s, 8s after errors 1-4, then 5th error
        # Total wait: 1 + 2 + 4 + 8 = 15 seconds + time for 5th error
        # This is a slow test, but important for validation
        await asyncio.sleep(16.5)

        # Verify circuit breaker tripped
        assert session_data["listener_healthy"] is False

        # Verify at least 5 errors occurred
        assert error_count[0] >= 5

        # Verify listener task completed on its own
        assert listener_task.done()

        # Clean up
        if not listener_task.done():
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass


@pytest.mark.asyncio
class TestStdinHandling:
    """Test input() request handling via stdin listener."""

    async def test_input_request_notification(self):
        """Input request should trigger notification callback."""
        mux = IOMultiplexer(input_request_timeout=1)
        kc = MockKernelClient()

        # Mock stdin message
        stdin_message = {
            "header": {"msg_type": "input_request"},
            "content": {"prompt": "Enter your name: ", "password": False},
        }

        # Make stdin channel return our message once
        call_count = [0]

        async def mock_msg_ready():
            call_count[0] += 1
            return call_count[0] == 1

        async def mock_get_msg(timeout):
            return stdin_message

        kc.stdin_channel.msg_ready = mock_msg_ready
        kc.stdin_channel.get_msg = mock_get_msg

        session_data = {"waiting_for_input": False}

        # Mock notification callback
        notifications = []

        async def mock_notification(method, params):
            notifications.append((method, params))
            # Simulate user providing input
            session_data["waiting_for_input"] = False

        # Start stdin listener
        listener_task = asyncio.create_task(
            mux.listen_stdin(
                "test.ipynb", kc, session_data, notification_callback=mock_notification
            )
        )

        # Wait for processing
        await asyncio.sleep(0.3)
        listener_task.cancel()

        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify notification was sent
        assert len(notifications) >= 1
        method, params = notifications[0]
        assert method == "notebook/input_request"
        assert params["prompt"] == "Enter your name: "
        assert params["password"] is False

    async def test_input_timeout_recovery(self):
        """Input timeout should send empty string to kernel."""
        mux = IOMultiplexer(input_request_timeout=0.2)
        kc = MockKernelClient()

        # Mock stdin message
        stdin_message = {
            "header": {"msg_type": "input_request"},
            "content": {"prompt": "Timeout test: ", "password": False},
        }

        # Make stdin channel return message once
        call_count = [0]

        async def mock_msg_ready():
            call_count[0] += 1
            return call_count[0] == 1

        async def mock_get_msg(timeout):
            return stdin_message

        kc.stdin_channel.msg_ready = mock_msg_ready
        kc.stdin_channel.get_msg = mock_get_msg

        session_data = {"waiting_for_input": False}

        # Track kc.input() calls
        input_calls = []

        def mock_input(text):
            input_calls.append(text)

        kc.input = mock_input

        # Start stdin listener (no notification callback - timeout guaranteed)
        listener_task = asyncio.create_task(
            mux.listen_stdin("test.ipynb", kc, session_data)
        )

        # Wait for timeout (0.2s + processing time)
        await asyncio.sleep(0.5)
        listener_task.cancel()

        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify empty string was sent to unblock kernel
        assert len(input_calls) == 1
        assert input_calls[0] == ""


@pytest.mark.asyncio
class TestNotifications:
    """Test MCP notification integration."""

    async def test_output_notification(self):
        """Output messages should trigger MCP notifications."""
        mux = IOMultiplexer()
        kc = MockKernelClient()

        exec_id = "test-exec-7"
        executions = {
            exec_id: {
                "id": "task-7",
                "cell_index": 6,
                "outputs": [],
                "status": "running",
            }
        }
        session_data = {}

        # Add stream message
        kc.add_message("stream", exec_id, {"name": "stdout", "text": "Test output\n"})

        # Mock notification callback
        notifications = []

        async def mock_notification(method, params):
            notifications.append((method, params))

        # Start listener
        listener_task = asyncio.create_task(
            mux.listen_iopub(
                "test.ipynb",
                kc,
                executions,
                session_data,
                notification_callback=mock_notification,
            )
        )

        # Wait for processing
        await asyncio.sleep(0.2)
        listener_task.cancel()

        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify notification was sent
        assert len(notifications) >= 1
        method, params = notifications[0]
        assert method == "notebook/output"
        assert params["notebook_path"] == "test.ipynb"
        assert params["exec_id"] == "task-7"
        assert params["type"] == "stream"
