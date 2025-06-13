"""Tests for Pydantic models in schemas.py"""
import pytest
from typing import Dict, Any
from app.models.schemas import (
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
    RepositoryFileInfo,
    RepositoryInfoResponse,
    AnalysisProgressUpdate,
    TaskBreakdownRequest,
    TaskBreakdownResponse,
    Task,
    DevinSessionRequest,
    DevinSessionResponse,
    DevinSetupCommand,
)


class TestRepositoryAnalysisRequest:
    """Test the RepositoryAnalysisRequest model."""

    def test_valid_request(self):
        """Test creating a valid repository analysis request."""
        request = RepositoryAnalysisRequest(
            owner="microsoft",
            repo="gitagu",
            agent_id="github-copilot"
        )
        assert request.owner == "microsoft"
        assert request.repo == "gitagu"
        assert request.agent_id == "github-copilot"

    def test_invalid_request_missing_fields(self):
        """Test that missing required fields raise validation errors."""
        with pytest.raises(ValueError):
            RepositoryAnalysisRequest(owner="microsoft")


class TestRepositoryAnalysisResponse:
    """Test the RepositoryAnalysisResponse model."""

    def test_valid_response(self):
        """Test creating a valid repository analysis response."""
        response = RepositoryAnalysisResponse(
            agent_id="github-copilot",
            repo_name="microsoft/gitagu",
            analysis="This is a test analysis.",
        )
        assert response.agent_id == "github-copilot"
        assert response.repo_name == "microsoft/gitagu"
        assert response.analysis == "This is a test analysis."
        assert response.error is None
        assert response.setup_commands is None

    def test_response_with_error(self):
        """Test creating a response with an error."""
        response = RepositoryAnalysisResponse(
            agent_id="github-copilot",
            repo_name="microsoft/gitagu",
            analysis="Analysis failed",
            error="Repository not found"
        )
        assert response.error == "Repository not found"

    def test_response_with_setup_commands(self):
        """Test creating a response with setup commands."""
        setup_commands = {
            "install": "npm install",
            "test": "npm test"
        }
        response = RepositoryAnalysisResponse(
            agent_id="github-copilot",
            repo_name="microsoft/gitagu",
            analysis="Test analysis",
            setup_commands=setup_commands
        )
        assert response.setup_commands == setup_commands


class TestRepositoryFileInfo:
    """Test the RepositoryFileInfo model."""

    def test_file_info_with_size(self):
        """Test creating file info with size."""
        file_info = RepositoryFileInfo(
            path="src/main.py",
            type="blob",
            size=1024
        )
        assert file_info.path == "src/main.py"
        assert file_info.type == "blob"
        assert file_info.size == 1024

    def test_file_info_without_size(self):
        """Test creating file info without size."""
        file_info = RepositoryFileInfo(
            path="src/",
            type="tree"
        )
        assert file_info.path == "src/"
        assert file_info.type == "tree"
        assert file_info.size is None


class TestRepositoryInfoResponse:
    """Test the RepositoryInfoResponse model."""

    def test_complete_repo_info(self):
        """Test creating complete repository info."""
        files = [
            RepositoryFileInfo(path="README.md", type="blob", size=1024),
            RepositoryFileInfo(path="src/", type="tree")
        ]
        
        repo_info = RepositoryInfoResponse(
            full_name="microsoft/gitagu",
            description="A test repository",
            language="Python",
            stars=100,
            default_branch="main",
            readme="# Test README",
            files=files
        )
        
        assert repo_info.full_name == "microsoft/gitagu"
        assert repo_info.description == "A test repository"
        assert repo_info.language == "Python"
        assert repo_info.stars == 100
        assert repo_info.default_branch == "main"
        assert repo_info.readme == "# Test README"
        assert len(repo_info.files) == 2

    def test_minimal_repo_info(self):
        """Test creating minimal repository info."""
        repo_info = RepositoryInfoResponse(
            full_name="microsoft/gitagu",
            description="A test repository",
            language="Python",
            stars=0,
            default_branch="main"
        )
        
        assert repo_info.readme is None
        assert repo_info.files is None


class TestAnalysisProgressUpdate:
    """Test the AnalysisProgressUpdate model."""

    def test_progress_update(self):
        """Test creating a progress update."""
        progress = AnalysisProgressUpdate(
            step=1,
            step_name="Fetching repository data",
            status="in_progress",
            message="Downloading files...",
            progress_percentage=50
        )
        
        assert progress.step == 1
        assert progress.step_name == "Fetching repository data"
        assert progress.status == "in_progress"
        assert progress.message == "Downloading files..."
        assert progress.progress_percentage == 50
        assert progress.elapsed_time is None
        assert progress.details is None

    def test_progress_update_with_details(self):
        """Test creating a progress update with details."""
        details = {"files_processed": 10, "total_files": 20}
        progress = AnalysisProgressUpdate(
            step=2,
            step_name="Processing files",
            status="completed",
            message="All files processed",
            progress_percentage=100,
            elapsed_time=15.5,
            details=details
        )
        
        assert progress.elapsed_time == 15.5
        assert progress.details == details


class TestTaskBreakdown:
    """Test task breakdown models."""

    def test_task_breakdown_request(self):
        """Test creating a task breakdown request."""
        request = TaskBreakdownRequest(
            request="Fix the login bug and add new feature"
        )
        assert request.request == "Fix the login bug and add new feature"

    def test_task(self):
        """Test creating a task."""
        task = Task(
            title="Fix login bug",
            description="The login button is not working correctly"
        )
        assert task.title == "Fix login bug"
        assert task.description == "The login button is not working correctly"

    def test_task_breakdown_response(self):
        """Test creating a task breakdown response."""
        tasks = [
            Task(title="Fix login bug", description="Fix the login button"),
            Task(title="Add feature", description="Add new user dashboard")
        ]
        response = TaskBreakdownResponse(tasks=tasks)
        
        assert len(response.tasks) == 2
        assert response.tasks[0].title == "Fix login bug"
        assert response.tasks[1].title == "Add feature"


class TestDevinSession:
    """Test Devin session models."""

    def test_devin_session_request(self):
        """Test creating a Devin session request."""
        request = DevinSessionRequest(
            api_key="test-api-key",
            prompt="Fix the bug in the code"
        )
        assert request.api_key == "test-api-key"
        assert request.prompt == "Fix the bug in the code"
        assert request.snapshot_id is None
        assert request.playbook_id is None

    def test_devin_session_request_with_optional_fields(self):
        """Test creating a Devin session request with optional fields."""
        request = DevinSessionRequest(
            api_key="test-api-key",
            prompt="Fix the bug in the code",
            snapshot_id="snap-123",
            playbook_id="play-456"
        )
        assert request.snapshot_id == "snap-123"
        assert request.playbook_id == "play-456"

    def test_devin_session_response(self):
        """Test creating a Devin session response."""
        response = DevinSessionResponse(
            session_id="session-123",
            session_url="https://app.devin.ai/sessions/123"
        )
        assert response.session_id == "session-123"
        assert response.session_url == "https://app.devin.ai/sessions/123"


class TestDevinSetupCommand:
    """Test the DevinSetupCommand model."""

    def test_setup_command(self):
        """Test creating a setup command."""
        command = DevinSetupCommand(
            step="install",
            description="Install dependencies",
            commands=["npm install", "pip install -r requirements.txt"]
        )
        assert command.step == "install"
        assert command.description == "Install dependencies"
        assert len(command.commands) == 2
        assert command.commands[0] == "npm install"
        assert command.commands[1] == "pip install -r requirements.txt"