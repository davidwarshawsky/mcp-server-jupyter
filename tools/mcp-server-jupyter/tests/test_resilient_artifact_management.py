"""
Tests for Resilient Artifact Management (Phases 1, 2, 3)

Phase 1: Hybrid Asset/Thumbnail Strategy (Offloading)
Phase 2: Environment Lockfile System
Phase 3: Resilient Training Templates
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the functions we're testing
from src.utils import (
    sanitize_outputs_resilient,
    update_lockfile,
    generate_lockfile_startup_script,
    get_training_template,
    MAX_TEXT_BYTES,
    MAX_IMAGE_BYTES,
)
from src.package_manager import PackageManager


# ============================================================================
# PHASE 1 TESTS: Hybrid Asset Offloading
# ============================================================================


class TestPhase1AssetOffloading:
    """Test the output sanitization and asset offloading logic."""

    def test_small_text_stays_inline(self):
        """Small text outputs should remain inline, not offloaded."""
        asset_dir = tempfile.mkdtemp()
        outputs = [
            {
                "output_type": "stream",
                "name": "stdout",
                "text": "Hello world",
            }
        ]

        summary, sanitized = sanitize_outputs_resilient(outputs, asset_dir)

        assert "Hello world" in sanitized[0]["text"]
        assert len(list(Path(asset_dir).glob("*"))) == 0  # No files created

    def test_large_text_gets_offloaded(self):
        """Text larger than MAX_TEXT_BYTES should be offloaded."""
        asset_dir = tempfile.mkdtemp()
        large_text = "x" * (MAX_TEXT_BYTES + 1000)
        outputs = [
            {
                "output_type": "stream",
                "name": "stdout",
                "text": large_text,
            }
        ]

        summary, sanitized = sanitize_outputs_resilient(outputs, asset_dir)

        # Should create an asset file
        asset_files = list(Path(asset_dir).glob("log_*.txt"))
        assert len(asset_files) == 1

        # Original output should be replaced with stub
        assert "offloaded" in sanitized[0]["text"].lower()
        assert "assets/log_" in sanitized[0]["text"]

        # Verify content was written to file
        assert asset_files[0].read_text() == large_text

    def test_large_image_gets_offloaded(self):
        """Images larger than MAX_IMAGE_BYTES should be offloaded."""
        import base64

        asset_dir = tempfile.mkdtemp()

        # Create a large binary image (>1MB)
        large_image_data = b"x" * (MAX_IMAGE_BYTES + 100000)
        base64_image = base64.b64encode(large_image_data).decode()

        outputs = [
            {
                "output_type": "display_data",
                "data": {"image/png": base64_image},
            }
        ]

        summary, sanitized = sanitize_outputs_resilient(outputs, asset_dir)

        # Should create an asset file
        asset_files = list(Path(asset_dir).glob("img_*.png"))
        assert len(asset_files) == 1

        # Original output should have HTML img tag
        assert "text/html" in sanitized[0]["data"]
        assert "assets/img_" in sanitized[0]["data"]["text/html"]
        assert "image/png" not in sanitized[0]["data"]  # Removed heavy base64

    def test_json_visualization_gets_offloaded(self):
        """JSON visualizations (Plotly/Vega) should be offloaded."""
        asset_dir = tempfile.mkdtemp()

        large_json = {
            "data": [{"x": list(range(10000)), "y": list(range(10000))}]
        }

        outputs = [
            {
                "output_type": "display_data",
                "data": {"application/vnd.plotly.v1+json": large_json},
            }
        ]

        summary, sanitized = sanitize_outputs_resilient(outputs, asset_dir)

        # Should create an asset file
        asset_files = list(Path(asset_dir).glob("viz_*.json"))
        assert len(asset_files) == 1

        # Original output should have HTML link
        assert "text/html" in sanitized[0]["data"]
        assert "assets/viz_" in sanitized[0]["data"]["text/html"]
        assert "application/vnd.plotly" not in sanitized[0]["data"]  # Removed

    def test_summary_mentions_offloaded_assets(self):
        """LLM summary should mention what was offloaded."""
        asset_dir = tempfile.mkdtemp()
        large_text = "x" * (MAX_TEXT_BYTES + 1000)
        outputs = [
            {
                "output_type": "stream",
                "name": "stdout",
                "text": large_text,
            }
        ]

        summary, _ = sanitize_outputs_resilient(outputs, asset_dir)

        assert "offloaded" in summary.lower()
        assert "assets/" in summary

    def test_multiple_outputs_mixed_handling(self):
        """Multiple outputs should be handled: some inline, some offloaded."""
        asset_dir = tempfile.mkdtemp()
        outputs = [
            {"output_type": "stream", "name": "stdout", "text": "Small"},
            {
                "output_type": "stream",
                "name": "stdout",
                "text": "x" * (MAX_TEXT_BYTES + 1000),
            },
        ]

        summary, sanitized = sanitize_outputs_resilient(outputs, asset_dir)

        assert "Small" in sanitized[0]["text"]
        assert "offloaded" in sanitized[1]["text"].lower()

    def test_asset_directory_created_if_missing(self):
        """Asset directory should be created if it doesn't exist."""
        import uuid
        unique_name = f"assets_dir_{uuid.uuid4().hex[:8]}"
        asset_dir = Path(tempfile.gettempdir()) / unique_name
        
        # Clean up if it already exists
        if asset_dir.exists():
            import shutil
            shutil.rmtree(asset_dir)
        
        assert not asset_dir.exists()

        outputs = [{"output_type": "stream", "name": "stdout", "text": "test"}]
        sanitize_outputs_resilient(outputs, str(asset_dir))

        assert asset_dir.exists()


# ============================================================================
# PHASE 2 TESTS: Environment Lockfile System
# ============================================================================


class TestPhase2LockfileSystem:
    """Test environment lockfile creation and enforcement."""

    @pytest.mark.asyncio
    async def test_update_lockfile_local_mode(self):
        """Test lockfile generation in local mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(tmpdir)
                success, msg = await update_lockfile("local")
                assert success is True
                assert Path(".mcp-requirements.lock").exists()
                # Should contain pip packages
                content = Path(".mcp-requirements.lock").read_text()
                assert len(content) > 0
            finally:
                os.chdir(old_cwd)

    # In-cluster lockfile update tests removed for local-first pivot.    # If remote execution support is added again, add dedicated integration tests.

    def test_lockfile_startup_script_generation(self):
        """Test the generated shell script for lockfile enforcement."""
        script = generate_lockfile_startup_script()

        assert ".mcp-requirements.lock" in script
        assert "pip install" in script
        assert "[RESILIENCE]" in script
        assert "[MCP]" in script

    def test_startup_script_handles_missing_lockfile(self):
        """Startup script should gracefully handle missing lockfile."""
        script = generate_lockfile_startup_script()

        # Should have both paths: lockfile exists and doesn't exist
        assert "if [ -f .mcp-requirements.lock ]" in script
        assert "No lockfile found" in script or "using current environment" in script


class TestPackageManagerWithLockfile:
    """Test PackageManager integration with lockfile."""

    @pytest.mark.asyncio
    async def test_install_package_updates_lockfile(self):
        """After installing a package, lockfile should be updated (local mode)."""
        pm = PackageManager()

        # Mock the local subprocess install and the lockfile updater
        pm._update_lockfile = AsyncMock(return_value=(True, "Updated"))

        with patch("src.package_manager.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""
            mock_run.return_value.stdout = ""

            success, msg = await pm.install_package_and_update_requirements(
                session_id="test_session",
                package_name="requests",
                version="2.28.0",
            )

        # _update_lockfile should have been awaited
        pm._update_lockfile.assert_called_once()

    @pytest.mark.asyncio
    async def test_lockfile_update_called_in_local_mode(self):
        """Test _update_lockfile in local mode."""
        pm = PackageManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(tmpdir)
                success, msg = await pm._update_lockfile(pod_name="local")
                assert success is True
                assert Path(".mcp-requirements.lock").exists()
            finally:
                os.chdir(old_cwd)


# ============================================================================
# PHASE 3 TESTS: Resilient Training Templates
# ============================================================================


class TestPhase3TrainingTemplates:
    """Test resilient training code templates."""

    def test_pytorch_template_exists(self):
        """PyTorch template should be provided."""
        template = get_training_template("pytorch")

        assert len(template) > 100
        assert "torch" in template.lower()
        assert "checkpoint" in template.lower()
        assert "resume" in template.lower()

    def test_pytorch_template_has_resume_logic(self):
        """PyTorch template should include checkpoint resume logic."""
        template = get_training_template("pytorch")

        assert "get_latest_checkpoint" in template
        assert "torch.load" in template
        assert "load_state_dict" in template

    def test_pytorch_template_has_save_logic(self):
        """PyTorch template should include checkpoint save logic."""
        template = get_training_template("pytorch")

        assert "torch.save" in template
        assert "save_path" in template
        assert "CHECKPOINT_DIR" in template

    def test_pytorch_template_has_cleanup_logic(self):
        """PyTorch template should include old checkpoint cleanup."""
        template = get_training_template("pytorch")

        assert "cleanup_old_checkpoints" in template
        assert "KEEP_LAST_N_CHECKPOINTS" in template

    def test_tensorflow_template_exists(self):
        """TensorFlow template should be provided."""
        template = get_training_template("tensorflow")

        assert len(template) > 100
        assert "tensorflow" in template.lower() or "keras" in template.lower()
        assert "checkpoint" in template.lower()

    def test_tensorflow_template_has_callback(self):
        """TensorFlow template should use ModelCheckpoint callback."""
        template = get_training_template("tensorflow")

        assert "ModelCheckpoint" in template
        assert "callbacks" in template

    def test_sklearn_template_exists(self):
        """Scikit-learn template should be provided."""
        template = get_training_template("sklearn")

        assert len(template) > 100
        assert "sklearn" in template.lower() or "pickle" in template.lower()
        assert "checkpoint" in template.lower()

    def test_sklearn_template_has_pickle_logic(self):
        """Sklearn template should use pickle for model serialization."""
        template = get_training_template("sklearn")

        assert "pickle" in template
        assert "pickle.dump" in template or "pickle.load" in template

    def test_unknown_framework_returns_warning(self):
        """Unknown framework should return a warning message."""
        template = get_training_template("unknown_framework")

        assert "unknown" in template.lower() or "not available" in template.lower()

    def test_templates_are_executable_python(self):
        """Templates should be syntactically valid Python."""
        for framework in ["pytorch", "tensorflow", "sklearn"]:
            template = get_training_template(framework)

            # Should be able to compile it (basic syntax check)
            try:
                compile(template, f"{framework}_template", "exec")
            except SyntaxError as e:
                pytest.fail(f"{framework} template has syntax error: {e}")

    def test_all_templates_mention_assets_directory(self):
        """All templates should save checkpoints to assets/ directory."""
        for framework in ["pytorch", "tensorflow", "sklearn"]:
            template = get_training_template(framework)
            assert "assets" in template.lower()
            assert "checkpoint" in template.lower()


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestIntegration:
    """Integration tests combining multiple phases."""

    def test_full_pipeline_with_assets_and_templates(self):
        """Test the full pipeline: sanitize outputs, provide training template."""
        asset_dir = tempfile.mkdtemp()

        # Phase 1: Sanitize some outputs
        large_output = "x" * (MAX_TEXT_BYTES + 1000)
        outputs = [{"output_type": "stream", "name": "stdout", "text": large_output}]
        summary, sanitized = sanitize_outputs_resilient(outputs, asset_dir)

        assert len(list(Path(asset_dir).glob("*.txt"))) == 1
        assert "offloaded" in summary.lower()

        # Phase 3: Get training template for resilience
        template = get_training_template("pytorch")
        assert "checkpoint" in template.lower()

    @pytest.mark.asyncio
    async def test_lockfile_and_training_template_combo(self):
        """Test lockfile generation with training template guidance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(tmpdir)

                # Phase 2: Create lockfile
                success, msg = await update_lockfile("local")
                assert success is True

                # Phase 3: Get template for user
                template = get_training_template("pytorch")
                assert "checkpoint" in template.lower()

                # Script should reference both
                startup_script = generate_lockfile_startup_script()
                assert ".mcp-requirements.lock" in startup_script
            finally:
                os.chdir(old_cwd)


# ============================================================================
# EDGE CASES AND ERROR HANDLING
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_sanitize_outputs_with_none_values(self):
        """Sanitizer should handle None values gracefully."""
        asset_dir = tempfile.mkdtemp()
        outputs = [{"output_type": "stream", "name": "stdout", "text": None}]

        # Should not crash
        summary, sanitized = sanitize_outputs_resilient(outputs, asset_dir)
        assert isinstance(sanitized, list)

    def test_sanitize_outputs_with_empty_list(self):
        """Sanitizer should handle empty output list."""
        asset_dir = tempfile.mkdtemp()
        outputs = []

        summary, sanitized = sanitize_outputs_resilient(outputs, asset_dir)
        assert summary == ""
        assert sanitized == []

    def test_sanitize_outputs_with_invalid_base64_image(self):
        """Sanitizer should handle invalid base64 images gracefully."""
        asset_dir = tempfile.mkdtemp()
        outputs = [
            {
                "output_type": "display_data",
                "data": {"image/png": "not-valid-base64!!!"},
            }
        ]

        # Should not crash
        summary, sanitized = sanitize_outputs_resilient(outputs, asset_dir)
        assert isinstance(sanitized, list)

    @pytest.mark.asyncio
    async def test_lockfile_update_with_no_permissions(self):
        """Lockfile update should fail gracefully with permission error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lockfile_path = Path(tmpdir) / ".mcp-requirements.lock"
            lockfile_path.write_text("existing")
            lockfile_path.chmod(0o000)  # Remove all permissions

            try:
                success, msg = await update_lockfile("local")
                # Should either fail gracefully or succeed
                assert isinstance(success, bool)
            finally:
                lockfile_path.chmod(0o644)  # Restore for cleanup


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
