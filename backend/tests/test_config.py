"""Tests for the configuration module."""
import os
import pytest
from unittest.mock import patch


class TestConfig:
    """Test configuration loading and defaults."""

    @patch.dict(os.environ, {}, clear=True)
    def test_default_config_values(self):
        """Test that default configuration values are set correctly."""
        # Force reload the config module to pick up cleared environment
        import importlib
        from app import config
        importlib.reload(config)
        
        assert config.PROJECT_ENDPOINT is None
        assert config.MODEL_DEPLOYMENT_NAME == "gpt-4o"
        assert config.AZURE_AI_PROJECT_CONNECTION_STRING is None
        assert config.AZURE_AI_AGENTS_API_KEY is None
        assert config.GITHUB_TOKEN is None
        assert config.GITHUB_API_URL == "https://api.github.com"
        assert "http://localhost:5173" in config.CORS_ORIGINS
        assert "https://gitagu.com" in config.CORS_ORIGINS

    @patch.dict(os.environ, {
        "PROJECT_ENDPOINT": "https://test.ai.azure.com",
        "MODEL_DEPLOYMENT_NAME": "gpt-3.5-turbo",
        "AZURE_AI_AGENTS_API_KEY": "test-key",
        "GITHUB_TOKEN": "github-token"
    })
    def test_config_with_environment_variables(self):
        """Test configuration with environment variables set."""
        # Force reload the config module to pick up new environment
        import importlib
        from app import config
        importlib.reload(config)
        
        assert config.PROJECT_ENDPOINT == "https://test.ai.azure.com"
        assert config.MODEL_DEPLOYMENT_NAME == "gpt-3.5-turbo"
        assert config.AZURE_AI_AGENTS_API_KEY == "test-key"
        assert config.GITHUB_TOKEN == "github-token"

    @patch.dict(os.environ, {
        "AZURE_AI_PROJECT_CONNECTION_STRING": "https://legacy.ai.azure.com"
    })
    def test_legacy_azure_endpoint_fallback(self):
        """Test that legacy Azure endpoint is used as fallback."""
        # Force reload the config module
        import importlib
        from app import config
        importlib.reload(config)
        
        assert config.AZURE_AI_PROJECT_CONNECTION_STRING == "https://legacy.ai.azure.com"

    @patch.dict(os.environ, {
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": "custom-model"
    })
    def test_azure_model_deployment_name_fallback(self):
        """Test Azure model deployment name fallback."""
        # Force reload the config module
        import importlib
        from app import config
        importlib.reload(config)
        
        assert config.MODEL_DEPLOYMENT_NAME == "custom-model"

    def test_cors_origins_configuration(self):
        """Test CORS origins configuration."""
        from app import config
        
        expected_origins = [
            "http://localhost:5173",
            "https://gitagu.com",
            "https://agunblock.com",
            "*"
        ]
        
        for origin in expected_origins:
            assert origin in config.CORS_ORIGINS