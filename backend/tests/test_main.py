"""Tests for FastAPI endpoints."""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app, get_github_service, get_agent_service


class TestBasicEndpoints:
    """Test basic API endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_root_endpoint(self):
        """Test the root endpoint."""
        response = self.client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "gitagu Backend API"
        assert data["status"] == "healthy"

    def test_health_endpoint(self):
        """Test the health check endpoint."""
        response = self.client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "gitagu Backend"
        assert "timestamp" in data

    def test_cors_headers(self):
        """Test that CORS headers are properly set."""
        response = self.client.get("/", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200
        # Note: TestClient doesn't automatically add CORS headers, 
        # but we verify the endpoint responds correctly

    def test_nonexistent_endpoint(self):
        """Test that nonexistent endpoints return 404."""
        response = self.client.get("/nonexistent")
        assert response.status_code == 404


class TestAnalysisEndpoints:
    """Test repository analysis endpoints."""

    def setup_method(self):
        """Set up test client with mocked dependencies."""
        # Create mock services
        self.mock_github_service = Mock()
        self.mock_agent_service = Mock()
        
        # Override dependencies
        app.dependency_overrides[get_github_service] = lambda: self.mock_github_service
        app.dependency_overrides[get_agent_service] = lambda: self.mock_agent_service
        
        self.client = TestClient(app)

    def teardown_method(self):
        """Clean up dependency overrides."""
        app.dependency_overrides.clear()

    def test_analyze_repository_success(self):
        """Test successful repository analysis."""
        # Set up async mock returns
        self.mock_github_service.get_repository_info = AsyncMock(return_value={
            "name": "gitagu", "full_name": "microsoft/gitagu"
        })
        self.mock_github_service.get_readme_content = AsyncMock(return_value="# Test README")
        self.mock_github_service.get_requirements = AsyncMock(return_value={"requirements.txt": "fastapi"})
        self.mock_github_service.get_repository_files = AsyncMock(return_value=[])
        self.mock_agent_service.analyze_repository = AsyncMock(return_value={
            "analysis": "This is a test analysis.",
            "setup_commands": {"install": "pip install -r requirements.txt"}
        })

        # Make request
        request_data = {
            "owner": "microsoft",
            "repo": "gitagu",
            "agent_id": "github-copilot"
        }
        response = self.client.post("/api/analyze", json=request_data)

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "github-copilot"
        assert data["repo_name"] == "microsoft/gitagu"
        assert data["analysis"] == "This is a test analysis."
        assert data["setup_commands"]["install"] == "pip install -r requirements.txt"
        assert data["error"] is None

    def test_analyze_repository_invalid_request(self):
        """Test repository analysis with invalid request data."""
        # Missing required fields
        request_data = {
            "owner": "microsoft"
            # Missing "repo" and "agent_id"
        }
        response = self.client.post("/api/analyze", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_analyze_repository_with_error(self):
        """Test repository analysis when an error occurs."""
        # Mock GitHub service to raise an exception
        self.mock_github_service.get_repository_info = AsyncMock(side_effect=Exception("API error"))

        # Make request
        request_data = {
            "owner": "microsoft",
            "repo": "gitagu",
            "agent_id": "github-copilot"
        }
        response = self.client.post("/api/analyze", json=request_data)

        # Verify response handles error gracefully
        assert response.status_code == 200  # Should not raise, but return error in response
        data = response.json()
        assert data["agent_id"] == "github-copilot"
        assert data["repo_name"] == "microsoft/gitagu"
        assert "Error analyzing repository" in data["analysis"]
        assert data["error"] is not None


class TestRepositoryInfoEndpoint:
    """Test repository info endpoint."""

    def setup_method(self):
        """Set up test client with mocked dependencies."""
        self.mock_github_service = Mock()
        app.dependency_overrides[get_github_service] = lambda: self.mock_github_service
        self.client = TestClient(app)

    def teardown_method(self):
        """Clean up dependency overrides."""
        app.dependency_overrides.clear()

    def test_get_repository_info_success(self):
        """Test successful repository info retrieval."""
        # Mock service response
        self.mock_github_service.get_repository_snapshot = AsyncMock(return_value={
            "full_name": "microsoft/gitagu",
            "description": "Test repository",
            "language": "Python",
            "stars": 100,
            "default_branch": "main",
            "readme": "# Test README",
            "files": []
        })

        response = self.client.get("/api/repo-info/microsoft/gitagu")

        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "microsoft/gitagu"
        assert data["description"] == "Test repository"
        assert data["language"] == "Python"
        assert data["stars"] == 100

    def test_get_repository_info_not_found(self):
        """Test repository info when repository is not found."""
        # Mock service to return None (repository not found)
        self.mock_github_service.get_repository_snapshot = AsyncMock(return_value=None)

        response = self.client.get("/api/repo-info/microsoft/nonexistent")

        assert response.status_code == 404

    def test_get_repository_info_error(self):
        """Test repository info when an error occurs."""
        # Mock service to raise an exception
        self.mock_github_service.get_repository_snapshot = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        response = self.client.get("/api/repo-info/microsoft/gitagu")

        assert response.status_code == 500


class TestTaskBreakdownEndpoint:
    """Test task breakdown endpoint."""

    def setup_method(self):
        """Set up test client with mocked dependencies."""
        self.mock_agent_service = Mock()
        app.dependency_overrides[get_agent_service] = lambda: self.mock_agent_service
        self.client = TestClient(app)

    def teardown_method(self):
        """Clean up dependency overrides."""
        app.dependency_overrides.clear()

    def test_breakdown_tasks_success(self):
        """Test successful task breakdown."""
        # Mock service response
        self.mock_agent_service.breakdown_user_request = AsyncMock(return_value={
            "tasks": [
                {"title": "Fix login bug", "description": "Fix the login button issue"},
                {"title": "Add feature", "description": "Add new user dashboard"}
            ]
        })

        request_data = {
            "request": "Fix the login bug and add new user dashboard"
        }
        response = self.client.post("/api/breakdown-tasks", json=request_data)

        assert response.status_code == 200
        data = response.json()
        assert len(data["tasks"]) == 2
        assert data["tasks"][0]["title"] == "Fix login bug"
        assert data["tasks"][1]["title"] == "Add feature"

    def test_breakdown_tasks_invalid_request(self):
        """Test task breakdown with invalid request."""
        # Empty request
        request_data = {}
        response = self.client.post("/api/breakdown-tasks", json=request_data)
        assert response.status_code == 422

    def test_breakdown_tasks_error(self):
        """Test task breakdown when an error occurs."""
        # Mock service to raise an exception
        self.mock_agent_service.breakdown_user_request = AsyncMock(
            side_effect=Exception("Service error")
        )

        request_data = {
            "request": "Fix the login bug"
        }
        response = self.client.post("/api/breakdown-tasks", json=request_data)

        assert response.status_code == 500


class TestDevinSessionEndpoint:
    """Test Devin session endpoint."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_create_devin_session_invalid_request(self):
        """Test Devin session creation with invalid request."""
        # Missing required fields
        request_data = {
            "prompt": "Fix this bug"
            # Missing "api_key"
        }
        response = self.client.post("/api/create-devin-session", json=request_data)
        assert response.status_code == 422

    def test_create_devin_session_valid_request_structure(self):
        """Test that valid request structure is accepted (will fail on external call)."""
        request_data = {
            "api_key": "test-api-key",
            "prompt": "Fix this bug in the code",
            "snapshot_id": "snap-123",
            "playbook_id": "play-456"
        }
        # This will fail on the external HTTP call, but we test the structure
        response = self.client.post("/api/create-devin-session", json=request_data)
        # Should get past validation but fail on HTTP call
        assert response.status_code == 503  # Network error expected


class TestDependencyInjection:
    """Test dependency injection functions."""

    def test_get_github_service(self):
        """Test GitHub service dependency injection."""
        from app.main import get_github_service
        from app.services.github import GitHubService
        
        service = get_github_service()
        assert isinstance(service, GitHubService)

    def test_get_agent_service_creation(self):
        """Test agent service dependency injection function exists."""
        from app.main import get_agent_service
        
        # Just test that the function exists and can be called
        # It will likely fail due to missing Azure config, but that's expected
        assert callable(get_agent_service)