"""
Tests for Pydantic V2 Input Validation (Phase 3.1)

Validates that all MCP tools reject malicious/malformed inputs before execution.
"""

import pytest
from pydantic import ValidationError
from src.models import (
    StartKernelArgs,
    StopKernelArgs,
    RunCellArgs,
    InstallPackageArgs,
    GetVariableInfoArgs,
    InspectVariableArgs,
    SetWorkingDirectoryArgs,
    QueryDataframesArgs,
    SwitchKernelEnvironmentArgs,
)


class TestPathTraversalPrevention:
    """Test that path traversal attacks are blocked."""

    def test_start_kernel_blocks_path_traversal(self):
        """StartKernelArgs should reject paths with .."""
        with pytest.raises(ValidationError) as exc_info:
            StartKernelArgs(notebook_path="/home/user/../etc/passwd.ipynb")

        assert "Path traversal detected" in str(exc_info.value)

    def test_start_kernel_requires_ipynb_extension(self):
        """StartKernelArgs should require .ipynb extension."""
        with pytest.raises(ValidationError) as exc_info:
            StartKernelArgs(notebook_path="/home/user/notebook.txt")

        assert ".ipynb extension" in str(exc_info.value)

    def test_stop_kernel_blocks_path_traversal(self):
        """StopKernelArgs should reject paths with .."""
        with pytest.raises(ValidationError) as exc_info:
            StopKernelArgs(notebook_path="../../etc/passwd")

        assert "Path traversal detected" in str(exc_info.value)


class TestShellInjectionPrevention:
    """Test that shell metacharacters are blocked."""

    def test_install_package_blocks_semicolons(self):
        """InstallPackageArgs should reject semicolons."""
        with pytest.raises(ValidationError) as exc_info:
            InstallPackageArgs(
                notebook_path="/home/test.ipynb", package="pandas; rm -rf /"
            )

        assert "Shell metacharacters not allowed" in str(exc_info.value)

    def test_install_package_blocks_pipes(self):
        """InstallPackageArgs should reject pipes."""
        with pytest.raises(ValidationError) as exc_info:
            InstallPackageArgs(
                notebook_path="/home/test.ipynb", package="pandas | cat /etc/passwd"
            )

        assert "Shell metacharacters not allowed" in str(exc_info.value)

    def test_install_package_blocks_backticks(self):
        """InstallPackageArgs should reject backticks."""
        with pytest.raises(ValidationError) as exc_info:
            InstallPackageArgs(
                notebook_path="/home/test.ipynb", package="pandas `whoami`"
            )

        assert "Shell metacharacters not allowed" in str(exc_info.value)

    def test_install_package_blocks_dollar_signs(self):
        """InstallPackageArgs should reject dollar signs (command substitution)."""
        with pytest.raises(ValidationError) as exc_info:
            InstallPackageArgs(
                notebook_path="/home/test.ipynb", package="pandas $(rm -rf /)"
            )

        assert "Shell metacharacters not allowed" in str(exc_info.value)

    def test_install_package_blocks_ampersands(self):
        """InstallPackageArgs should reject ampersands."""
        with pytest.raises(ValidationError) as exc_info:
            InstallPackageArgs(
                notebook_path="/home/test.ipynb", package="pandas && rm -rf /"
            )

        assert "Shell metacharacters not allowed" in str(
            exc_info.value
        ) or "Command chaining not allowed" in str(exc_info.value)

    def test_set_working_directory_blocks_shell_chars(self):
        """SetWorkingDirectoryArgs should reject shell metacharacters."""
        with pytest.raises(ValidationError) as exc_info:
            SetWorkingDirectoryArgs(
                notebook_path="/home/test.ipynb", path="/home/user; rm -rf /"
            )

        assert "Suspicious characters" in str(exc_info.value)

    def test_switch_kernel_environment_blocks_shell_chars(self):
        """SwitchKernelEnvironmentArgs should reject shell metacharacters."""
        with pytest.raises(ValidationError) as exc_info:
            SwitchKernelEnvironmentArgs(
                notebook_path="/home/test.ipynb", venv_path="/venv`whoami`"
            )

        assert "Shell metacharacters not allowed" in str(exc_info.value)


class TestCodeInjectionPrevention:
    """Test that code injection attempts are blocked."""

    def test_run_cell_enforces_max_code_length(self):
        """RunCellArgs should enforce 100KB code limit."""
        large_code = "x = 1\n" * 50000  # ~300KB
        with pytest.raises(ValidationError) as exc_info:
            RunCellArgs(
                notebook_path="/home/test.ipynb", index=0, code_override=large_code
            )

        assert "too long" in str(exc_info.value).lower() or "100000 characters" in str(
            exc_info.value
        )

    def test_query_dataframes_blocks_dangerous_sql(self):
        """QueryDataframesArgs should block dangerous SQL keywords."""
        dangerous_queries = [
            "DROP TABLE users",
            "DELETE FROM customers",
            "TRUNCATE logs",
            "ALTER TABLE users ADD COLUMN",
            "CREATE TABLE hacked",
            "INSERT INTO users VALUES",
            "UPDATE users SET password",
        ]

        for sql in dangerous_queries:
            with pytest.raises(ValidationError) as exc_info:
                QueryDataframesArgs(notebook_path="/home/test.ipynb", sql_query=sql)

            assert (
                "dangerous" in str(exc_info.value).lower()
                and "sql" in str(exc_info.value).lower()
            )

    def test_query_dataframes_enforces_max_length(self):
        """QueryDataframesArgs should enforce 50KB SQL limit."""
        # Generate a query over 50KB (50,000 chars)
        large_query = (
            "SELECT * FROM table WHERE id IN ("
            + ",".join(str(i) for i in range(15000))
            + ")"
        )
        with pytest.raises(ValidationError) as exc_info:
            QueryDataframesArgs(notebook_path="/home/test.ipynb", sql_query=large_query)

        assert "too long" in str(exc_info.value).lower() or "50000 characters" in str(
            exc_info.value
        )

    @pytest.mark.asyncio
    async def test_query_dataframes_uses_base64_transport(self):
        """Verify that query_dataframes encodes SQL as Base64 before injecting into kernel."""

        class DummyManager:
            def __init__(self):
                self.last_code = None

            def get_session(self, path):
                return object()

            async def execute_cell_async(self, notebook_path, cell_index, code):
                # Store the injected code and act like an execution was scheduled
                self.last_code = code
                return "exec-id"

            def get_execution_status(self, notebook_path, exec_id):
                # Simulate an immediate successful execution
                return {
                    "status": "completed",
                    "outputs": [{"output_type": "stream", "text": "Query returned 0 rows."}],
                }

        manager = DummyManager()

        malicious_query = 'SELECT * FROM df' + chr(34) * 3 + " + __import__('os').system('echo HACKED > /tmp/hacked.txt') + " + chr(34) * 3

        # Run the tool. Avoid importing heavy src.session (it may import config) by
        # injecting a lightweight dummy module into sys.modules.
        import asyncio
        import sys
        import types

        fake_session_mod = types.SimpleNamespace(SessionManager=object)
        sys.modules["src.session"] = fake_session_mod

        try:
            # Use `await` since this test is async; avoid run_until_complete inside a running loop.
            result = await __import__("src.data_tools", fromlist=["query_dataframes"]).query_dataframes(
                manager, "/home/test.ipynb", malicious_query
            )
        finally:
            # Clean up injected module to avoid leaking into other tests
            try:
                del sys.modules["src.session"]
            except Exception:
                pass

        # Assert server-side code used Base64 transport
        assert manager.last_code is not None
        assert "base64.b64decode" in manager.last_code or "query_b64" in manager.last_code
        # Ensure raw malicious triple-quote string was not embedded verbatim in the injected code
        assert '"""' not in manager.last_code


class TestPythonIdentifierValidation:
    """Test that Python identifiers are validated."""

    def test_get_variable_info_validates_identifier(self):
        """GetVariableInfoArgs should validate Python identifiers."""
        invalid_names = [
            "123abc",  # Starts with number
            "my-var",  # Contains hyphen
            "var name",  # Contains space
            # Note: We don't validate reserved keywords, only syntactic validity
        ]

        for name in invalid_names:
            with pytest.raises(ValidationError) as exc_info:
                GetVariableInfoArgs(notebook_path="/home/test.ipynb", var_name=name)

            assert "Invalid Python identifier" in str(
                exc_info.value
            ) or "cannot be empty" in str(exc_info.value)

    def test_inspect_variable_validates_identifier(self):
        """InspectVariableArgs should validate Python identifiers."""
        with pytest.raises(ValidationError) as exc_info:
            InspectVariableArgs(
                notebook_path="/home/test.ipynb", variable_name="my-var"
            )

        assert "Invalid Python identifier" in str(exc_info.value)

    def test_valid_python_identifiers_accepted(self):
        """Valid Python identifiers should be accepted."""
        valid_names = ["df", "my_variable", "_private", "var123", "__dunder__"]

        for name in valid_names:
            # Should not raise
            args = GetVariableInfoArgs(notebook_path="/home/test.ipynb", var_name=name)
            assert args.var_name == name


class TestRangeLimits:
    """Test that numeric ranges are enforced."""

    def test_start_kernel_timeout_min_limit(self):
        """StartKernelArgs should enforce minimum timeout of 10s."""
        with pytest.raises(ValidationError) as exc_info:
            StartKernelArgs(notebook_path="/home/test.ipynb", timeout=5)

        assert "greater than or equal to 10" in str(exc_info.value).lower()

    def test_start_kernel_timeout_max_limit(self):
        """StartKernelArgs should enforce maximum timeout of 3600s."""
        with pytest.raises(ValidationError) as exc_info:
            StartKernelArgs(notebook_path="/home/test.ipynb", timeout=5000)

        assert "less than or equal to 3600" in str(exc_info.value).lower()

    def test_run_cell_index_non_negative(self):
        """RunCellArgs should require non-negative cell index."""
        with pytest.raises(ValidationError) as exc_info:
            RunCellArgs(notebook_path="/home/test.ipynb", index=-1)

        assert "greater than or equal to 0" in str(exc_info.value).lower()


class TestValidInputsAccepted:
    """Test that valid inputs are accepted."""

    def test_start_kernel_valid_inputs(self):
        """StartKernelArgs should accept valid inputs."""
        args = StartKernelArgs(
            notebook_path="/home/user/notebook.ipynb",
            venv_path="/home/user/.venv",
            docker_image="python:3.10",
            timeout=300,
            agent_id="test-agent",
        )
        assert args.notebook_path == "/home/user/notebook.ipynb"
        assert args.timeout == 300

    def test_run_cell_valid_inputs(self):
        """RunCellArgs should accept valid inputs."""
        args = RunCellArgs(
            notebook_path="/home/test.ipynb",
            index=5,
            code_override="import pandas as pd\ndf = pd.DataFrame()",
            task_id_override="exec-123",
        )
        assert args.index == 5
        assert "pandas" in args.code_override

    def test_install_package_valid_inputs(self):
        """InstallPackageArgs should accept valid pip specifiers."""
        valid_packages = [
            "pandas",
            "numpy==1.24.0",
            "matplotlib>=3.0.0",
            "scikit-learn[extra]",
            "torch==2.0.0+cpu",
        ]

        for package in valid_packages:
            args = InstallPackageArgs(notebook_path="/home/test.ipynb", package=package)
            assert args.package == package

    def test_query_dataframes_valid_inputs(self):
        """QueryDataframesArgs should accept valid SQL queries."""
        valid_queries = [
            "SELECT * FROM df",
            "SELECT name, age FROM users WHERE age > 18",
            "SELECT region, SUM(revenue) as total FROM sales GROUP BY region",
            "SELECT * FROM df LIMIT 100",
        ]

        for query in valid_queries:
            args = QueryDataframesArgs(
                notebook_path="/home/test.ipynb", sql_query=query
            )
            assert args.sql_query == query


class TestEmptyInputRejection:
    """Test that empty inputs are rejected."""

    def test_install_package_rejects_empty_package(self):
        """InstallPackageArgs should reject empty package names."""
        with pytest.raises(ValidationError) as exc_info:
            InstallPackageArgs(notebook_path="/home/test.ipynb", package="")

        assert "cannot be empty" in str(exc_info.value).lower()

    def test_install_package_rejects_whitespace_only(self):
        """InstallPackageArgs should reject whitespace-only package names."""
        with pytest.raises(ValidationError) as exc_info:
            InstallPackageArgs(notebook_path="/home/test.ipynb", package="   ")

        assert "cannot be empty" in str(exc_info.value).lower()

    def test_query_dataframes_rejects_empty_sql(self):
        """QueryDataframesArgs should reject empty SQL queries."""
        with pytest.raises(ValidationError) as exc_info:
            QueryDataframesArgs(notebook_path="/home/test.ipynb", sql_query="")

        assert "cannot be empty" in str(exc_info.value).lower()


class TestExtraFieldsRejected:
    """Test that extra='forbid' prevents unknown fields."""

    def test_start_kernel_rejects_extra_fields(self):
        """StartKernelArgs should reject unknown fields."""
        with pytest.raises(ValidationError) as exc_info:
            StartKernelArgs(notebook_path="/home/test.ipynb", unknown_field="malicious")

        assert "Extra inputs are not permitted" in str(exc_info.value)

    def test_run_cell_rejects_extra_fields(self):
        """RunCellArgs should reject unknown fields."""
        with pytest.raises(ValidationError) as exc_info:
            RunCellArgs(
                notebook_path="/home/test.ipynb", index=0, malicious_param="value"
            )

        assert "Extra inputs are not permitted" in str(exc_info.value)


class TestDockerImageValidation:
    """Test Docker image validation."""

    def test_start_kernel_accepts_valid_docker_images(self):
        """StartKernelArgs should accept valid Docker image names."""
        valid_images = [
            "python:3.10",
            "jupyter/scipy-notebook",
            "registry.example.com/my-image:latest",
            "gcr.io/project/image:v1.0",
        ]

        for image in valid_images:
            args = StartKernelArgs(notebook_path="/home/test.ipynb", docker_image=image)
            assert args.docker_image == image

    def test_start_kernel_blocks_shell_chars_in_docker_image(self):
        """StartKernelArgs should reject shell metacharacters in Docker image."""
        with pytest.raises(ValidationError) as exc_info:
            StartKernelArgs(
                notebook_path="/home/test.ipynb", docker_image="python:3.10; rm -rf /"
            )

        assert "Shell metacharacters not allowed" in str(exc_info.value)

    def test_start_kernel_enforces_docker_image_length(self):
        """StartKernelArgs should enforce max length for Docker image."""
        long_image = "a" * 300
        with pytest.raises(ValidationError) as exc_info:
            StartKernelArgs(notebook_path="/home/test.ipynb", docker_image=long_image)

        assert "too long" in str(exc_info.value).lower()
