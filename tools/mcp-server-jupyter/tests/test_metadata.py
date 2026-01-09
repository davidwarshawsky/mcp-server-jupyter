"""
Tests for metadata operations.
"""

import pytest
import json
import nbformat
from src.notebook import (
    get_notebook_metadata, set_notebook_metadata, update_kernelspec,
    get_cell_metadata, set_cell_metadata, add_cell_tags, remove_cell_tags
)
from tests.test_helpers import (
    assert_notebook_valid,
    assert_metadata_contains,
    assert_cell_has_tag
)


class TestNotebookMetadata:
    """Tests for notebook-level metadata operations."""
    
    def test_get_notebook_metadata(self, create_test_notebook):
        """Test getting notebook metadata."""
        nb_path = create_test_notebook("test.ipynb")
        
        metadata = get_notebook_metadata(nb_path)
        
        assert isinstance(metadata, dict)
        assert 'kernelspec' in metadata
        assert 'language_info' in metadata
    
    def test_set_notebook_metadata(self, create_test_notebook):
        """Test setting notebook metadata."""
        nb_path = create_test_notebook("test.ipynb")
        
        new_metadata = {
            'custom_field': 'custom_value',
            'author': 'Test Author'
        }
        
        result = set_notebook_metadata(nb_path, new_metadata)
        
        assert "updated" in result.lower()
        
        # Verify metadata was set
        metadata = get_notebook_metadata(nb_path)
        assert metadata['custom_field'] == 'custom_value'
        assert metadata['author'] == 'Test Author'
        
        # Original metadata should still exist
        assert 'kernelspec' in metadata
    
    def test_set_notebook_metadata_overwrites(self, create_test_notebook):
        """Test that set_notebook_metadata updates existing fields."""
        nb_path = create_test_notebook("test.ipynb")
        
        # Set initial metadata
        set_notebook_metadata(nb_path, {'field1': 'value1'})
        
        # Update with new value
        set_notebook_metadata(nb_path, {'field1': 'new_value'})
        
        metadata = get_notebook_metadata(nb_path)
        assert metadata['field1'] == 'new_value'
    
    def test_update_kernelspec(self, create_test_notebook):
        """Test updating kernelspec."""
        nb_path = create_test_notebook("test.ipynb")
        
        result = update_kernelspec(
            nb_path,
            kernel_name='conda-py39',
            display_name='Conda Python 3.9',
            language='python'
        )
        
        assert "updated" in result.lower()
        
        metadata = get_notebook_metadata(nb_path)
        assert metadata['kernelspec']['name'] == 'conda-py39'
        assert metadata['kernelspec']['display_name'] == 'Conda Python 3.9'
        assert metadata['kernelspec']['language'] == 'python'
    
    def test_update_kernelspec_partial(self, create_test_notebook):
        """Test updating only kernel name."""
        nb_path = create_test_notebook("test.ipynb")
        
        # Get original display name
        original_metadata = get_notebook_metadata(nb_path)
        original_display = original_metadata['kernelspec'].get('display_name')
        
        # Update only name
        update_kernelspec(nb_path, kernel_name='newkernel')
        
        metadata = get_notebook_metadata(nb_path)
        assert metadata['kernelspec']['name'] == 'newkernel'
        # Display name should be unchanged if not None
        if original_display:
            assert metadata['kernelspec']['display_name'] == original_display


class TestCellMetadata:
    """Tests for cell-level metadata operations."""
    
    def test_get_cell_metadata(self, create_test_notebook):
        """Test getting cell metadata."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1", "metadata": {"custom": "value"}}
        ])
        
        metadata = get_cell_metadata(nb_path, 0)
        
        assert isinstance(metadata, dict)
        assert metadata.get('custom') == 'value'
    
    def test_get_cell_metadata_empty(self, create_test_notebook):
        """Test getting metadata from cell with no metadata."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"}
        ])
        
        metadata = get_cell_metadata(nb_path, 0)
        
        assert isinstance(metadata, dict)
    
    def test_set_cell_metadata(self, create_test_notebook):
        """Test setting cell metadata."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"}
        ])
        
        new_metadata = {
            'important': True,
            'note': 'This is a test'
        }
        
        result = set_cell_metadata(nb_path, 0, new_metadata)
        
        assert "updated" in result.lower()
        
        metadata = get_cell_metadata(nb_path, 0)
        assert metadata['important'] is True
        assert metadata['note'] == 'This is a test'
    
    def test_set_cell_metadata_negative_index(self, create_test_notebook):
        """Test setting metadata using negative index."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"},
            {"type": "code", "source": "y = 2"}
        ])
        
        set_cell_metadata(nb_path, -1, {'last_cell': True})
        
        metadata = get_cell_metadata(nb_path, 1)
        assert metadata['last_cell'] is True


class TestCellTags:
    """Tests for cell tag operations."""
    
    def test_add_cell_tags(self, create_test_notebook):
        """Test adding tags to a cell."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"}
        ])
        
        result = add_cell_tags(nb_path, 0, ['important', 'todo'])
        
        assert "added" in result.lower()
        assert_cell_has_tag(nb_path, 0, 'important')
        assert_cell_has_tag(nb_path, 0, 'todo')
    
    def test_add_tags_to_existing_tags(self, create_test_notebook):
        """Test adding tags when cell already has tags."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1", "metadata": {"tags": ["existing"]}}
        ])
        
        add_cell_tags(nb_path, 0, ['new_tag'])
        
        metadata = get_cell_metadata(nb_path, 0)
        tags = metadata.get('tags', [])
        assert 'existing' in tags
        assert 'new_tag' in tags
    
    def test_add_duplicate_tag(self, create_test_notebook):
        """Test that adding duplicate tags doesn't create duplicates."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1", "metadata": {"tags": ["tag1"]}}
        ])
        
        add_cell_tags(nb_path, 0, ['tag1', 'tag2'])
        
        metadata = get_cell_metadata(nb_path, 0)
        tags = metadata.get('tags', [])
        assert tags.count('tag1') == 1
        assert 'tag2' in tags
    
    def test_remove_cell_tags(self, create_test_notebook):
        """Test removing tags from a cell."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1", "metadata": {"tags": ["tag1", "tag2", "tag3"]}}
        ])
        
        result = remove_cell_tags(nb_path, 0, ['tag2'])
        
        assert "removed" in result.lower()
        
        metadata = get_cell_metadata(nb_path, 0)
        tags = metadata.get('tags', [])
        assert 'tag1' in tags
        assert 'tag2' not in tags
        assert 'tag3' in tags
    
    def test_remove_multiple_tags(self, create_test_notebook):
        """Test removing multiple tags at once."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1", "metadata": {"tags": ["a", "b", "c", "d"]}}
        ])
        
        remove_cell_tags(nb_path, 0, ['b', 'd'])
        
        metadata = get_cell_metadata(nb_path, 0)
        tags = metadata.get('tags', [])
        assert tags == ['a', 'c']
    
    def test_remove_nonexistent_tag(self, create_test_notebook):
        """Test removing a tag that doesn't exist."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1", "metadata": {"tags": ["tag1"]}}
        ])
        
        # Should not raise error
        result = remove_cell_tags(nb_path, 0, ['nonexistent'])
        
        # Original tags should remain
        metadata = get_cell_metadata(nb_path, 0)
        tags = metadata.get('tags', [])
        assert 'tag1' in tags
    
    def test_remove_tags_from_cell_without_tags(self, create_test_notebook):
        """Test removing tags from cell that has no tags."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"}
        ])
        
        result = remove_cell_tags(nb_path, 0, ['tag1'])
        
        assert "no tags" in result.lower()
    
    def test_tags_with_special_characters(self, create_test_notebook):
        """Test tags with special characters."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"}
        ])
        
        special_tags = ['tag-with-dash', 'tag_with_underscore', 'tag.with.dots']
        add_cell_tags(nb_path, 0, special_tags)
        
        metadata = get_cell_metadata(nb_path, 0)
        tags = metadata.get('tags', [])
        
        for tag in special_tags:
            assert tag in tags


class TestMetadataEdgeCases:
    """Edge case tests for metadata operations."""
    
    def test_metadata_with_nested_objects(self, create_test_notebook):
        """Test setting metadata with nested objects."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"}
        ])
        
        complex_metadata = {
            'config': {
                'level1': {
                    'level2': 'value'
                }
            },
            'list_field': [1, 2, 3]
        }
        
        set_cell_metadata(nb_path, 0, complex_metadata)
        
        metadata = get_cell_metadata(nb_path, 0)
        assert metadata['config']['level1']['level2'] == 'value'
        assert metadata['list_field'] == [1, 2, 3]
    
    def test_metadata_preserves_existing_fields(self, create_test_notebook):
        """Test that setting metadata preserves other fields."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1", "metadata": {"field1": "value1", "field2": "value2"}}
        ])
        
        # Update only field1
        set_cell_metadata(nb_path, 0, {'field1': 'new_value'})
        
        metadata = get_cell_metadata(nb_path, 0)
        assert metadata['field1'] == 'new_value'
        assert metadata['field2'] == 'value2'
    
    def test_empty_tag_list(self, create_test_notebook):
        """Test adding/removing empty tag list."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"}
        ])
        
        # Add empty list (should be no-op)
        add_cell_tags(nb_path, 0, [])
        
        metadata = get_cell_metadata(nb_path, 0)
        # Tags field might not exist or be empty
        tags = metadata.get('tags', [])
        assert len(tags) == 0
    
    def test_unicode_in_metadata(self, create_test_notebook):
        """Test metadata with unicode characters."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"}
        ])
        
        unicode_metadata = {
            'author': '作者',
            'description': 'Тест',
            'emoji': '🚀'
        }
        
        set_cell_metadata(nb_path, 0, unicode_metadata)
        
        metadata = get_cell_metadata(nb_path, 0)
        assert metadata['author'] == '作者'
        assert metadata['description'] == 'Тест'
        assert metadata['emoji'] == '🚀'
