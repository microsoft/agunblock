"""Tests for the constants module."""
from app.constants import (
    AGENT_ID_GITHUB_COPILOT_COMPLETIONS,
    AGENT_ID_GITHUB_COPILOT_AGENT,
    AGENT_ID_DEVIN,
    AGENT_ID_CODEX_CLI,
    AGENT_ID_SREAGENT,
    LEGACY_AGENT_ID_MAP,
    DEPENDENCY_FILES,
    LANGUAGE_MAP,
)


class TestConstants:
    """Test application constants."""

    def test_agent_ids(self):
        """Test that agent ID constants are defined correctly."""
        assert AGENT_ID_GITHUB_COPILOT_COMPLETIONS == 'github-copilot-completions'
        assert AGENT_ID_GITHUB_COPILOT_AGENT == 'github-copilot-agent'
        assert AGENT_ID_DEVIN == 'devin'
        assert AGENT_ID_CODEX_CLI == 'codex-cli'
        assert AGENT_ID_SREAGENT == 'sreagent'

    def test_legacy_agent_id_mapping(self):
        """Test legacy agent ID mapping."""
        assert 'github-copilot' in LEGACY_AGENT_ID_MAP
        assert LEGACY_AGENT_ID_MAP['github-copilot'] == AGENT_ID_GITHUB_COPILOT_COMPLETIONS

    def test_dependency_files(self):
        """Test dependency files list."""
        expected_files = ["requirements.txt", "package.json", "pom.xml", "build.gradle"]
        assert DEPENDENCY_FILES == expected_files
        assert len(DEPENDENCY_FILES) == 4

    def test_language_mapping(self):
        """Test language mapping for dependency files."""
        expected_mappings = {
            "requirements.txt": "Python",
            "package.json": "JavaScript/TypeScript",
            "pom.xml": "Java",
            "build.gradle": "Java/Kotlin",
        }
        assert LANGUAGE_MAP == expected_mappings
        
        # Test that all dependency files have language mappings
        for dep_file in DEPENDENCY_FILES:
            assert dep_file in LANGUAGE_MAP

    def test_language_map_completeness(self):
        """Test that all dependency files have corresponding language mappings."""
        for dependency_file in DEPENDENCY_FILES:
            assert dependency_file in LANGUAGE_MAP, f"Missing language mapping for {dependency_file}"