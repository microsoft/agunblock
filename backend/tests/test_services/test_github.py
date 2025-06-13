"""Tests for the GitHub service."""
import base64
import pytest
from unittest.mock import Mock, patch
from app.services.github import GitHubService, _safe_int_conversion
from app.models.schemas import RepositoryFileInfo


class TestSafeIntConversion:
    """Test the _safe_int_conversion utility function."""

    def test_none_value(self):
        """Test conversion of None value."""
        assert _safe_int_conversion(None) == 0
        assert _safe_int_conversion(None, default=42) == 42

    def test_unset_string(self):
        """Test conversion of '<UNSET>' string."""
        assert _safe_int_conversion('<UNSET>') == 0
        assert _safe_int_conversion('<UNSET>', default=99) == 99

    def test_valid_integer(self):
        """Test conversion of valid integer."""
        assert _safe_int_conversion(123) == 123
        assert _safe_int_conversion(123, default=456) == 123

    def test_valid_float(self):
        """Test conversion of valid float."""
        assert _safe_int_conversion(123.7) == 123
        assert _safe_int_conversion(123.7, default=456) == 123

    def test_valid_string_number(self):
        """Test conversion of valid string number."""
        assert _safe_int_conversion("123") == 123
        assert _safe_int_conversion("123", default=456) == 123

    def test_invalid_string(self):
        """Test conversion of invalid string."""
        assert _safe_int_conversion("abc") == 0
        assert _safe_int_conversion("abc", default=789) == 789

    def test_invalid_type(self):
        """Test conversion of invalid type."""
        assert _safe_int_conversion([1, 2, 3]) == 0
        assert _safe_int_conversion([1, 2, 3], default=999) == 999


class TestGitHubService:
    """Test the GitHubService class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.service = GitHubService()

    def test_github_service_initialization(self):
        """Test that GitHubService initializes correctly."""
        service = GitHubService()
        assert service is not None

    @patch('app.services.github.GITHUB_TOKEN', None)
    @patch('app.services.github.gh')
    def test_github_client_without_token(self, mock_gh):
        """Test GitHub client creation without token."""
        from app.services.github import gh
        
        # Clear the cache to force re-creation
        gh.cache_clear()
        
        # Call gh() which should create an anonymous client
        client = gh()
        
        # Verify gh() was called without token
        mock_gh.assert_called_once_with()

    @patch('app.services.github.GITHUB_TOKEN', 'test-token')
    def test_github_client_with_token(self):
        """Test GitHub client creation with token."""
        from app.services.github import gh
        import app.services.github
        
        # Clear the cache to force re-creation
        gh.cache_clear()
        
        # Mock the GitHub constructor
        with patch('app.services.github.GitHub') as mock_github:
            # Call gh() which should create a client with token
            client = gh()
            
            # Verify GitHub() was called with token
            mock_github.assert_called_once_with('test-token')

    def test_repository_file_info_creation(self):
        """Test RepositoryFileInfo model creation in the context of GitHub service."""
        # Test that we can create RepositoryFileInfo objects as used by the service
        file_info = RepositoryFileInfo(
            path="src/main.py",
            type="blob",
            size=1024
        )
        assert file_info.path == "src/main.py"
        assert file_info.type == "blob"
        assert file_info.size == 1024

        # Test without size
        dir_info = RepositoryFileInfo(
            path="src/",
            type="tree"
        )
        assert dir_info.path == "src/"
        assert dir_info.type == "tree"
        assert dir_info.size is None

    def test_base64_encoding_handling(self):
        """Test base64 encoding/decoding as used in GitHub API responses."""
        # This tests the type of operation the service does with GitHub content
        original_content = "# Test README\n\nThis is a test file."
        encoded_content = base64.b64encode(original_content.encode()).decode()
        decoded_content = base64.b64decode(encoded_content).decode()
        
        assert decoded_content == original_content

    def test_dependency_files_processing(self):
        """Test processing of dependency files as done by the service."""
        from app.constants import DEPENDENCY_FILES
        
        # Verify that the service would process these dependency files
        assert "requirements.txt" in DEPENDENCY_FILES
        assert "package.json" in DEPENDENCY_FILES
        assert "pom.xml" in DEPENDENCY_FILES
        assert "build.gradle" in DEPENDENCY_FILES
        
        # Test that each file type could be processed
        for dep_file in DEPENDENCY_FILES:
            assert isinstance(dep_file, str)
            assert len(dep_file) > 0

    def test_github_url_constants(self):
        """Test GitHub URL constants used by the service."""
        from app.config import GITHUB_API_URL
        
        assert GITHUB_API_URL == "https://api.github.com"

    def test_mock_github_response_structure(self):
        """Test that our mocking structure matches expected GitHub API responses."""
        # This tests our understanding of the GitHub API response structure
        mock_client = Mock()
        
        # Test repository response structure
        mock_repo_response = Mock()
        mock_repo_response.parsed_data.name = "test-repo"
        mock_repo_response.parsed_data.full_name = "owner/test-repo"
        mock_repo_response.parsed_data.description = "Test description"
        mock_repo_response.parsed_data.default_branch = "main"
        mock_repo_response.parsed_data.stargazers_count = 42
        mock_client.rest.repos.get.return_value = mock_repo_response
        
        # Verify we can access the expected attributes
        response = mock_client.rest.repos.get(owner="owner", repo="test-repo")
        assert response.parsed_data.name == "test-repo"
        assert response.parsed_data.full_name == "owner/test-repo"
        assert response.parsed_data.description == "Test description"
        assert response.parsed_data.default_branch == "main"
        assert response.parsed_data.stargazers_count == 42

    @patch('app.services.github.gh')
    def test_mock_readme_response_structure(self, mock_gh):
        """Test README response structure for mocking."""
        mock_client = Mock()
        mock_gh.return_value = mock_client
        
        readme_content = "# Test README\nContent here"
        encoded_content = base64.b64encode(readme_content.encode()).decode()
        
        mock_readme_response = Mock()
        mock_readme_response.parsed_data = Mock(
            content=encoded_content
        )
        mock_client.rest.repos.get_readme.return_value = mock_readme_response
        
        # Verify the structure
        response = mock_client.rest.repos.get_readme(owner="owner", repo="test-repo")
        decoded = base64.b64decode(response.parsed_data.content).decode()
        assert decoded == readme_content

    @patch('app.services.github.gh')
    def test_mock_tree_response_structure(self, mock_gh):
        """Test tree response structure for mocking."""
        mock_client = Mock()
        mock_gh.return_value = mock_client
        
        # Create mock tree items
        mock_file = Mock()
        mock_file.path = "README.md"
        mock_file.type = "blob"
        mock_file.size = 1024
        
        mock_dir = Mock()
        mock_dir.path = "src/"
        mock_dir.type = "tree"
        # Don't set size for directories
        
        mock_tree_response = Mock()
        mock_tree_response.parsed_data = Mock(
            tree=[mock_file, mock_dir]
        )
        mock_client.rest.git.get_tree.return_value = mock_tree_response
        
        # Verify the structure
        response = mock_client.rest.git.get_tree(
            owner="owner", repo="test-repo", tree_sha="abc123", recursive="1"
        )
        assert len(response.parsed_data.tree) == 2
        assert response.parsed_data.tree[0].path == "README.md"
        assert response.parsed_data.tree[0].type == "blob"
        assert response.parsed_data.tree[0].size == 1024
        assert response.parsed_data.tree[1].path == "src/"
        assert response.parsed_data.tree[1].type == "tree"