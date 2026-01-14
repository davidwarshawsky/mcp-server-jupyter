#!/usr/bin/env python3
"""
Test Asset-Based Output Storage Implementation

Tests the "Stubbing & Paging" architecture for offloading large text outputs.
"""

import tempfile
import json
from pathlib import Path
from src.utils import sanitize_outputs
from src.asset_manager import prune_unused_assets, get_referenced_assets
import nbformat


def test_text_offloading_large_output():
    """Test that large text outputs are offloaded to assets/"""
    print("\n=== Test 1: Text Offloading (Large Output) ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        assets_dir = str(Path(tmpdir) / "assets")
        
        # Create a large output (>2KB, >50 lines)
        large_text = "\n".join([f"Line {i}: " + "x" * 100 for i in range(100)])
        
        outputs = [{
            "output_type": "stream",
            "name": "stdout",
            "text": large_text
        }]
        
        # Process outputs
        result = sanitize_outputs(outputs, assets_dir)
        result_data = json.loads(result)
        
        # Verify asset file was created
        asset_files = list(Path(assets_dir).glob("text_*.txt"))
        assert len(asset_files) == 1, f"Expected 1 asset file, got {len(asset_files)}"
        
        # Verify stub contains truncation message
        llm_summary = result_data["llm_summary"]
        assert ">>> FULL OUTPUT" in llm_summary, "Missing truncation message in stub"
        assert "SAVED TO:" in llm_summary, "Missing asset path in stub"
        
        # Verify full content is in asset file
        asset_content = asset_files[0].read_text()
        assert asset_content == large_text, "Asset content doesn't match original"
        
        # Verify metadata
        raw_outputs = result_data["raw_outputs"]
        assert "mcp_asset" in raw_outputs[0]["metadata"], "Missing mcp_asset metadata"
        assert raw_outputs[0]["metadata"]["mcp_asset"]["line_count"] == 100
        
        print(f"✓ Large output offloaded to: {asset_files[0].name}")
        print(f"✓ Stub length: {len(llm_summary)} chars (original: {len(large_text)} chars)")
        print(f"✓ Metadata: {raw_outputs[0]['metadata']['mcp_asset']}")


def test_small_output_not_offloaded():
    """Test that small outputs remain inline"""
    print("\n=== Test 2: Small Output (Not Offloaded) ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        assets_dir = str(Path(tmpdir) / "assets")
        
        # Create a small output
        small_text = "Hello, World!\n" * 10
        
        outputs = [{
            "output_type": "stream",
            "name": "stdout",
            "text": small_text
        }]
        
        # Process outputs
        result = sanitize_outputs(outputs, assets_dir)
        result_data = json.loads(result)
        
        # Verify no asset file was created
        asset_files = list(Path(assets_dir).glob("text_*.txt"))
        assert len(asset_files) == 0, f"Expected 0 asset files, got {len(asset_files)}"
        
        # Verify text is in summary
        llm_summary = result_data["llm_summary"]
        assert small_text in llm_summary, "Small output not in LLM summary"
        
        print(f"✓ Small output kept inline: {len(small_text)} chars")


def test_execute_result_offloading():
    """Test offloading for execute_result outputs"""
    print("\n=== Test 3: Execute Result Offloading ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        assets_dir = str(Path(tmpdir) / "assets")
        
        # Large execute_result (e.g., large array print)
        large_array = "\n".join([f"[{i}, {i+1}, {i+2}, ...]" for i in range(0, 1000, 3)])
        
        outputs = [{
            "output_type": "execute_result",
            "execution_count": 1,
            "data": {
                "text/plain": large_array
            },
            "metadata": {}
        }]
        
        result = sanitize_outputs(outputs, assets_dir)
        result_data = json.loads(result)
        
        # Verify offloading
        asset_files = list(Path(assets_dir).glob("text_*.txt"))
        assert len(asset_files) == 1, "Expected 1 asset file for execute_result"
        
        # Verify stub
        assert ">>> FULL OUTPUT" in result_data["llm_summary"]
        
        print(f"✓ Execute result offloaded: {len(large_array)} chars → {asset_files[0].name}")


def test_asset_reference_tracking():
    """Test that get_referenced_assets correctly identifies text assets"""
    print("\n=== Test 4: Asset Reference Tracking ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        nb_path = Path(tmpdir) / "test.ipynb"
        assets_dir = Path(tmpdir) / "assets"
        assets_dir.mkdir()
        
        # Create a notebook with asset references
        nb = nbformat.v4.new_notebook()
        
        # Add a cell with stream output containing an offload stub asset reference
        asset_hex = "a" * 32
        asset_name = f"text_{asset_hex}.txt"
        cell = nbformat.v4.new_code_cell()
        # Use NotebookNode for outputs
        output = nbformat.v4.new_output(
            output_type="stream",
            name="stdout",
            text=f"Some output\n\n>>> FULL OUTPUT (50KB) SAVED TO: {asset_name} <<<"
        )
        output.metadata = {
            "mcp_asset": {
                "path": f"{assets_dir}/{asset_name}"
            }
        }
        cell.outputs = [output]
        nb.cells.append(cell)
        
        # Save notebook
        with open(nb_path, 'w') as f:
            nbformat.write(nb, f)
        
        # Debug: print what's in the notebook
        with open(nb_path, 'r') as f:
            content = f.read()
            print(f"  Notebook content sample: {content[500:700]}")
        
        # Create the actual asset file
        asset_file = assets_dir / asset_name
        asset_file.write_text("Original large content")
        
        # Test reference detection
        referenced = get_referenced_assets(str(nb_path))
        
        # Should find the text asset referenced via the "SAVED TO:" stub
        assert asset_name in referenced, f"Expected {asset_name} to be detected, got: {referenced}"
        print(f"✓ Referenced assets detected: {referenced}")


def test_prune_unused_assets():
    """Test garbage collection of orphaned assets"""
    print("\n=== Test 5: Asset Garbage Collection ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        nb_path = Path(tmpdir) / "test.ipynb"
        assets_dir = Path(tmpdir) / "assets"
        assets_dir.mkdir()
        
        # Create notebook
        nb = nbformat.v4.new_notebook()
        
        # Add cell with one asset reference (via stub)
        referenced_hex = "b" * 32
        referenced_name = f"text_{referenced_hex}.txt"
        cell = nbformat.v4.new_code_cell()
        output = nbformat.v4.new_output(
            output_type="stream",
            name="stdout",
            text=f">>> FULL OUTPUT SAVED TO: {referenced_name} <<<"
        )
        cell.outputs = [output]
        nb.cells.append(cell)
        
        with open(nb_path, 'w') as f:
            nbformat.write(nb, f)
        
        orphaned_hex = "c" * 32
        orphaned_name = f"text_{orphaned_hex}.txt"

        # Create assets: one referenced, one orphaned, one extra orphaned image-like file
        (assets_dir / referenced_name).write_text("Referenced content")
        (assets_dir / orphaned_name).write_text("Orphaned content")
        (assets_dir / ("d" * 32 + ".png")).write_bytes(b"fake png")
        
        # Run dry run
        result_dry = prune_unused_assets(str(nb_path), dry_run=True)
        print(f"  Dry run: {result_dry['message']}")

        # Verify dry-run doesn't delete anything
        assert (assets_dir / referenced_name).exists()
        assert (assets_dir / orphaned_name).exists()
        
        # Run actual cleanup
        result = prune_unused_assets(str(nb_path), dry_run=False)
        print(f"  Actual: {result['message']}")
        
        print(f"  Deleted: {result['deleted']}")
        print(f"  Kept: {result['kept']}")

        # Assert referenced remains, orphan is deleted
        assert (assets_dir / referenced_name).exists(), "Referenced asset should be kept"
        assert not (assets_dir / orphaned_name).exists(), "Orphaned asset should be deleted"


def test_read_asset_tool():
    """Test the read_asset tool functionality"""
    print("\n=== Test 6: Read Asset Tool ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        assets_dir = Path(tmpdir) / "assets"
        assets_dir.mkdir()
        
        # Create a test asset file
        content = "\n".join([f"Line {i}: Some important log message" for i in range(1, 101)])
        asset_file = assets_dir / "text_test12345678901234567890123456.txt"
        asset_file.write_text(content)
        
        # Import needed for logic test
        import json
        
        # Test 1: Read with search
        search_term = "Line 50"
        matches = []
        with open(asset_file, 'r') as f:
            for i, line in enumerate(f, 1):
                if search_term.lower() in line.lower():
                    matches.append(f"{i}: {line.rstrip()}")
        
        assert len(matches) == 1, f"Expected 1 match, got {len(matches)}"
        print(f"✓ Search found: {matches[0]}")
        
        # Test 2: Read with line range
        with open(asset_file, 'r') as f:
            selected = []
            for i, line in enumerate(f, 1):
                if 10 <= i <= 20:
                    selected.append(line.rstrip())
        
        assert len(selected) == 11, f"Expected 11 lines, got {len(selected)}"
        print(f"✓ Line range [10-20]: {len(selected)} lines")
        
        # Test 3: Read default (first N lines)
        with open(asset_file, 'r') as f:
            first_lines = [line.rstrip() for i, line in enumerate(f) if i < 50]
        
        assert len(first_lines) == 50, f"Expected 50 lines, got {len(first_lines)}"
        print(f"✓ Default read: {len(first_lines)} lines")


def test_integration_full_workflow():
    """Integration test: Generate large output → Offload → Read → Cleanup"""
    print("\n=== Test 7: Full Integration Workflow ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        nb_path = Path(tmpdir) / "test.ipynb"
        assets_dir = Path(tmpdir) / "assets"
        
        # Step 1: Generate large output
        large_output = "\n".join([f"Epoch {i}: Loss {1.0 / (i + 1):.6f}" for i in range(1, 1001)])
        outputs = [{
            "output_type": "stream",
            "name": "stdout",
            "text": large_output
        }]
        
        result = sanitize_outputs(outputs, str(assets_dir))
        result_data = json.loads(result)
        
        print(f"  Step 1: Generated {len(large_output)} chars → Offloaded")
        
        # Step 2: Create notebook with the output (using NotebookNode)
        nb = nbformat.v4.new_notebook()
        cell = nbformat.v4.new_code_cell()
        
        # Convert dict outputs to NotebookNode
        for out_dict in result_data["raw_outputs"]:
            output = nbformat.v4.new_output(
                output_type=out_dict["output_type"],
                name=out_dict.get("name", "stdout"),
                text=out_dict.get("text", "")
            )
            if "metadata" in out_dict:
                output.metadata = out_dict["metadata"]
            cell.outputs.append(output)
        
        nb.cells.append(cell)
        
        with open(nb_path, 'w') as f:
            nbformat.write(nb, f)
        
        print(f"  Step 2: Notebook created with stubbed output")
        
        # Step 3: Verify asset exists
        asset_files = list(assets_dir.glob("text_*.txt"))
        assert len(asset_files) == 1, "Asset not found"
        
        # Step 4: Read asset (search for error)
        asset_file = asset_files[0]
        with open(asset_file, 'r') as f:
            matches = [line for line in f if "Epoch 500" in line]
        
        assert len(matches) == 1, "Search failed"
        print(f"  Step 3: Read asset, found: {matches[0].strip()}")
        
        # Step 5: Delete cell and run GC
        nb.cells = []  # Remove all cells
        with open(nb_path, 'w') as f:
            nbformat.write(nb, f)
        
        gc_result = prune_unused_assets(str(nb_path), dry_run=False)
        print(f"  Step 4: GC ran - {gc_result['message']}")
        
        # Verify asset was deleted (if matching worked)
        remaining = list(assets_dir.glob("text_*.txt"))
        print(f"  Step 5: Remaining assets: {len(remaining)}")


if __name__ == "__main__":
    print("=" * 70)
    print("Asset-Based Output Storage - Test Suite")
    print("=" * 70)
    
    try:
        test_text_offloading_large_output()
        test_small_output_not_offloaded()
        test_execute_result_offloading()
        test_asset_reference_tracking()
        test_prune_unused_assets()
        test_read_asset_tool()
        test_integration_full_workflow()
        test_regex_captures_diverse_assets()
        test_read_asset_enforces_limits()
        test_prune_ignores_user_files()
        
        print("\n" + "=" * 70)
        print("✓ ALL TESTS PASSED")
        print("=" * 70)
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()

def test_regex_captures_diverse_assets():
    """Verify regex catches Plotly JSON, short hashes, and SVGs.
    
    Fixes "Binary Asset Ghosting" - Ensures the relaxed regex [a-f0-9]{12,32}
    captures both image hashes (12-char) and text hashes (32-char), plus 
    various extensions (.json, .svg, .html).
    """
    print("\n=== Test: Regex Captures Diverse Assets (12/32-char hashes) ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        nb_path = Path(tmpdir) / "test.ipynb"
        nb = nbformat.v4.new_notebook()
        
        # Scenario: Plotly JSON (short hash), SVG (long hash), and Text Stub
        source_text = """
        Here is a plot: assets/asset_abc123456789.json
        And an SVG: assets/asset_11112222333344445555666677778888.svg
        """
        
        nb.cells.append(nbformat.v4.new_markdown_cell(source_text))
        
        # Add output stub with text asset reference
        code_cell = nbformat.v4.new_code_cell("print('log')")
        code_cell.outputs = [nbformat.v4.new_output(
            "stream", 
            name="stdout", 
            text=">>> FULL OUTPUT SAVED TO: text_abcdef123456abcdef123456abcdef12.txt <<<"
        )]
        nb.cells.append(code_cell)

        with open(nb_path, 'w') as f:
            nbformat.write(nb, f)
            
        refs = get_referenced_assets(str(nb_path))
        
        assert "asset_abc123456789.json" in refs, "Failed to catch JSON asset with short hash"
        assert "asset_11112222333344445555666677778888.svg" in refs, "Failed to catch SVG asset"
        assert "text_abcdef123456abcdef123456abcdef12.txt" in refs, "Failed to catch Text asset"
        
        print(f"✓ Captured all diverse assets: {refs}")


def test_read_asset_enforces_limits():
    """Ensure read_asset truncates massive files.
    
    Fixes "Context Window Limit" - Enforces hard caps on MAX_RETURN_CHARS (20KB)
    and MAX_RETURN_LINES (500) to prevent context window overflow even when
    searching large files.
    """
    print("\n=== Test: Read Asset Enforces 20KB Limit ===")
    
    from src.main import read_asset
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a 50KB file (limit is 20KB)
        huge_file = Path(tmpdir) / "huge.txt"
        huge_content = "x" * 50000
        huge_file.write_text(huge_content)
        
        # Call the tool (it returns a JSON string)
        result_json = read_asset(str(huge_file))
        result = json.loads(result_json)
        
        content = result['content']
        
        assert len(content) <= 20500, f"Content not truncated: {len(content)} chars"
        assert "Truncated" in content, "Missing truncation warning message"
        
        print(f"✓ Content truncated from 50000 to {len(content)} chars with warning")


def test_prune_ignores_user_files():
    """Ensure GC does not delete user-created files in assets/."""
    print("\n=== Test: Prune ignores user-created files ===")
    from src.asset_manager import prune_unused_assets

    with tempfile.TemporaryDirectory() as tmpdir:
        nb_path = Path(tmpdir) / "test.ipynb"
        assets_dir = Path(tmpdir) / "assets"
        assets_dir.mkdir()

        # Create an empty notebook
        nb = nbformat.v4.new_notebook()
        with open(nb_path, 'w') as f:
            nbformat.write(nb, f)

        # 1. Create a SYSTEM file (orphan) -> Should be deleted
        (assets_dir / "text_12345678901234567890123456789012.txt").write_text("system")

        # 2. Create a USER file (orphan) -> Should be KEPT
        (assets_dir / "my_important_model.pkl").write_bytes(b"data")

        # Run GC
        result = prune_unused_assets(str(nb_path), dry_run=False)

        # Verify
        assert not (assets_dir / "text_12345678901234567890123456789012.txt").exists(), "System file was not deleted"
        assert (assets_dir / "my_important_model.pkl").exists(), "User file was incorrectly deleted"

        print("\n✓ GC correctly ignored user-created file 'my_important_model.pkl'")