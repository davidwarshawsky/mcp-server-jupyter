"""
Tests for Git-Awareness Features

Covers:
- Cell ID-based operations
- Provenance sidecar
- Git tools (save_notebook_clean, create_agent_branch, etc.)
- Asset management
"""

import pytest
import os
import json
import tempfile
import shutil
import subprocess
from pathlib import Path
import nbformat

from src.notebook import create_notebook, get_notebook_outline
from src.cell_id_manager import (
    ensure_cell_ids,
    edit_cell_by_id,
    delete_cell_by_id,
    insert_cell_by_id,
    StaleStateError
)
# from src.provenance import ProvenanceManager - DELETED
from src.git_tools import save_notebook_clean, create_agent_branch, setup_git_filters
from src.asset_manager import prune_unused_assets, get_assets_summary, ensure_assets_gitignored


class TestCellIDOperations:
    """Test stable Cell ID addressing"""
    
    def test_ensure_cell_ids_adds_missing_ids(self, tmp_path):
        """Cells without IDs get UUIDs assigned"""
        nb = nbformat.v4.new_notebook()
        # Create cells directly without IDs
        nb.cells.append(nbformat.v4.new_code_cell("x = 1"))
        nb.cells.append(nbformat.v4.new_code_cell("y = 2"))
        
        # nbformat 4.5+ auto-assigns IDs, so manually delete them
        # by creating a new notebook with lower version
        nb.nbformat_minor = 4  # Force old version
        for cell in nb.cells:
            cell.pop('id', None)  # Remove ID if exists
        
        was_modified, count = ensure_cell_ids(nb)
        
        assert was_modified is True
        assert count == 2
        assert all(hasattr(cell, 'id') and cell.id for cell in nb.cells)
    
    def test_edit_cell_by_id_preserves_id(self, tmp_path):
        """Editing by ID doesn't change the ID"""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path), initial_cells=[
            {"type": "code", "content": "x = 1"},
            {"type": "code", "content": "y = 2"}
        ])
        
        outline = get_notebook_outline(str(nb_path))
        cell_id = outline[0]['id']
        
        edit_cell_by_id(str(nb_path), cell_id, "x = 100", expected_index=0)
        
        outline2 = get_notebook_outline(str(nb_path))
        assert outline2[0]['id'] == cell_id  # ID unchanged
        assert outline2[0]['source_preview'] == "x = 100"
    
    def test_edit_cell_by_id_detects_stale_state(self, tmp_path):
        """StaleStateError raised if cell moved"""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path), initial_cells=[
            {"type": "code", "content": "x = 1"},
            {"type": "code", "content": "y = 2"}
        ])
        
        outline = get_notebook_outline(str(nb_path))
        cell_id = outline[0]['id']
        
        # Try to edit with wrong expected_index
        with pytest.raises(StaleStateError):
            edit_cell_by_id(str(nb_path), cell_id, "x = 100", expected_index=999)
    
    def test_delete_cell_by_id_removes_cell(self, tmp_path):
        """Deleting by ID works correctly"""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path), initial_cells=[
            {"type": "code", "content": "x = 1"},
            {"type": "code", "content": "y = 2"},
            {"type": "code", "content": "z = 3"}
        ])
        
        outline = get_notebook_outline(str(nb_path))
        # Index 0 is default empty cell, so we target index 2 (y = 2)
        cell_id = outline[2]['id']
        
        delete_cell_by_id(str(nb_path), cell_id, expected_index=2)
        
        outline2 = get_notebook_outline(str(nb_path))
        # 3 - 1 = 2 cells remain
        assert len(outline2) == 2
        assert cell_id not in [c['id'] for c in outline2]
    
    def test_insert_cell_by_id_adds_cell(self, tmp_path):
        """Inserting by ID works correctly"""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path), initial_cells=[
            {"type": "code", "content": "x = 1"},
            {"type": "code", "content": "z = 3"}
        ])
        
        outline = get_notebook_outline(str(nb_path))
        # Initial cells result in index 0 for x=1
        after_cell_id = outline[0]['id']
        
        insert_cell_by_id(str(nb_path), after_cell_id, "y = 2", "code")
        
        outline2 = get_notebook_outline(str(nb_path))
        # Original 2 cells + 1 inserted = 3
        assert len(outline2) == 3
        assert outline2[1]['source_preview'] == "y = 2"





class TestGitTools:
    """Test Git-safe workflow tools"""
    
    def test_save_notebook_clean_strips_execution_count(self, tmp_path):
        """save_notebook_clean removes execution_count"""
        nb_path = tmp_path / "test.ipynb"
        
        # Create notebook with execution_count
        nb = nbformat.v4.new_notebook()
        cell = nbformat.v4.new_code_cell("print('hello')")
        cell.execution_count = 42
        cell.outputs = [nbformat.v4.new_output('stream', text='hello')]
        nb.cells.append(cell)
        
        with open(nb_path, 'w') as f:
            nbformat.write(nb, f)
        
        # Clean it
        save_notebook_clean(str(nb_path))
        
        # Verify execution_count stripped but output kept
        with open(nb_path, 'r') as f:
            nb_clean = nbformat.read(f, as_version=4)
        
        assert nb_clean.cells[0].execution_count is None
        assert len(nb_clean.cells[0].outputs) == 1  # Output preserved
    
    def test_save_notebook_clean_with_strip_outputs(self, tmp_path):
        """save_notebook_clean can strip outputs too"""
        nb_path = tmp_path / "test.ipynb"
        
        nb = nbformat.v4.new_notebook()
        cell = nbformat.v4.new_code_cell("print('hello')")
        cell.outputs = [nbformat.v4.new_output('stream', text='hello')]
        nb.cells.append(cell)
        
        with open(nb_path, 'w') as f:
            nbformat.write(nb, f)
        
        save_notebook_clean(str(nb_path), strip_outputs=True)
        
        with open(nb_path, 'r') as f:
            nb_clean = nbformat.read(f, as_version=4)
        
        assert len(nb_clean.cells[0].outputs) == 0
    
    @pytest.mark.skipif(not shutil.which('git'), reason="git not installed")
    def test_create_agent_branch_creates_branch(self, tmp_path):
        """create_agent_branch creates and checks out branch"""
        # Initialize git repo
        subprocess.run(['git', 'init'], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=str(tmp_path), check=True, capture_output=True)
        
        # Create initial commit
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        subprocess.run(['git', 'add', '.'], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'init'], cwd=str(tmp_path), check=True, capture_output=True)
        
        # Create agent branch
        result = create_agent_branch(str(tmp_path), "agent/test-branch")
        
        assert "Created and switched to branch: agent/test-branch" in result
        
        # Verify branch exists
        result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=str(tmp_path),
            capture_output=True,
            text=True
        )
        assert result.stdout.strip() == "agent/test-branch"
    
    @pytest.mark.skipif(not shutil.which('git'), reason="git not installed")
    def test_create_agent_branch_fails_with_uncommitted_changes(self, tmp_path):
        """create_agent_branch fails if dirty working tree"""
        # Initialize git repo
        subprocess.run(['git', 'init'], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=str(tmp_path), check=True, capture_output=True)
        
        # Create initial commit
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        subprocess.run(['git', 'add', '.'], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'init'], cwd=str(tmp_path), check=True, capture_output=True)
        
        # Create uncommitted change
        test_file.write_text("modified")
        
        # Try to create branch - should fail
        result = create_agent_branch(str(tmp_path), "agent/test")
        
        assert "Uncommitted changes detected" in result


class TestAssetManagement:
    """Test asset cleanup and gitignore"""
    
    def test_ensure_assets_gitignored_creates_entry(self, tmp_path):
        """Auto-creates .gitignore entry for assets/"""
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        
        was_updated = ensure_assets_gitignored(str(assets_dir))
        
        assert was_updated is True
        
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        
        content = gitignore.read_text()
        assert "assets/" in content
    
    def test_ensure_assets_gitignored_idempotent(self, tmp_path):
        """Second call doesn't duplicate entry"""
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        
        ensure_assets_gitignored(str(assets_dir))
        was_updated = ensure_assets_gitignored(str(assets_dir))
        
        assert was_updated is False
    
    def test_prune_unused_assets_removes_orphans(self, tmp_path):
        """Orphaned assets deleted, referenced kept"""
        nb_path = tmp_path / "test.ipynb"
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        
        # Create notebook with asset reference
        nb = nbformat.v4.new_notebook()
        cell = nbformat.v4.new_code_cell("print('hello')")
        cell.outputs = [nbformat.v4.new_output(
            'display_data',
            data={'text/html': 'assets/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png'}
        )]
        nb.cells.append(cell)
        
        with open(nb_path, 'w') as f:
            nbformat.write(nb, f)
        
        # Create assets
        (assets_dir / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png").write_bytes(b"kept")
        (assets_dir / "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png").write_bytes(b"orphan")
        
        # Prune
        result = prune_unused_assets(str(nb_path))
        
        assert len(result['deleted']) == 1
        assert len(result['kept']) == 1
        assert "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png" in result['deleted']
        assert not (assets_dir / "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png").exists()
        assert (assets_dir / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png").exists()
    
    def test_get_assets_summary_returns_stats(self, tmp_path):
        """get_assets_summary returns counts"""
        nb_path = tmp_path / "test.ipynb"
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        
        create_notebook(str(nb_path))
        
        (assets_dir / ("a" * 32 + ".png")).write_bytes(b"x" * 100)
        (assets_dir / ("b" * 32 + ".png")).write_bytes(b"y" * 200)
        
        summary = get_assets_summary(str(nb_path))
        
        assert summary['total_assets'] == 2
        assert summary['referenced_assets'] == 0
        assert summary['orphaned_assets'] == 2
        assert summary['total_size'] == 300


class TestGetNotebookOutline:
    """Test that outline includes Cell IDs and triggers GC"""
    
    def test_outline_includes_cell_ids(self, tmp_path):
        """get_notebook_outline returns Cell IDs"""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path), initial_cells=[
            {"type": "code", "content": "x = 1"}
        ])
        
        outline = get_notebook_outline(str(nb_path))
        
        # 1 initial cell = 1 cell
        assert len(outline) == 1
        assert 'id' in outline[0]
        assert len(outline[0]['id']) > 0  # Has a non-empty ID
