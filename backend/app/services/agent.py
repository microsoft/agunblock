import asyncio
import time
from typing import Dict, List, Optional, Any, Union, Callable, Awaitable

from azure.ai.agents.aio import AgentsClient
from azure.ai.agents.models import (
    AgentThreadCreationOptions,
    ThreadMessageOptions,
    MessageTextContent,
    ListSortOrder,
)
from azure.core.credentials import AzureKeyCredential
from azure.identity.aio import DefaultAzureCredential

from ..config import PROJECT_ENDPOINT, MODEL_DEPLOYMENT_NAME, AZURE_AI_PROJECT_CONNECTION_STRING, AZURE_AI_AGENTS_API_KEY
from ..models.schemas import AnalysisProgressUpdate
from ..logging_config import get_agent_logger
from ..constants import (
    AGENT_ID_GITHUB_COPILOT_COMPLETIONS,
    AGENT_ID_GITHUB_COPILOT_AGENT,
    AGENT_ID_DEVIN,
    AGENT_ID_CODEX_CLI,
    AGENT_ID_SREAGENT,
    LEGACY_AGENT_ID_MAP,
    DEPENDENCY_FILES,
    LANGUAGE_MAP,
)


class AzureAgentService:
    """Service for interacting with Azure AI Agents."""
    
    def __init__(self) -> None:
        """Initialize the Azure Agent Service with credentials."""
        self.logger = get_agent_logger()
        # Use the new PROJECT_ENDPOINT format (following official samples)
        self.endpoint = PROJECT_ENDPOINT or AZURE_AI_PROJECT_CONNECTION_STRING
        self.model_deployment = MODEL_DEPLOYMENT_NAME
        
        if not self.endpoint:
            raise ValueError("PROJECT_ENDPOINT environment variable is required. Set it to your Azure AI Project endpoint (e.g., https://your-project.services.ai.azure.com/api/projects/your-project-id)")
        
        # Ensure the endpoint uses HTTPS and fix common formatting issues
        if self.endpoint and not self.endpoint.startswith('https://'):
            if self.endpoint.startswith('http://'):
                self.endpoint = self.endpoint.replace('http://', 'https://')
            elif not self.endpoint.startswith('http'):
                # If no protocol is specified, add https://
                self.endpoint = f'https://{self.endpoint}'
        
        # Use DefaultAzureCredential as recommended, fall back to API key if available
        try:
            self.credential = DefaultAzureCredential()
        except Exception:
            # Fall back to API key authentication if DefaultAzureCredential fails
            self.credential = None if not AZURE_AI_AGENTS_API_KEY or AZURE_AI_AGENTS_API_KEY == "your_api_key" else AzureKeyCredential(AZURE_AI_AGENTS_API_KEY)
    
    async def identify_config_files(self, repo_name: str, files: List[Dict[str, Any]]) -> List[str]:
        """
        First step of the two-phase analysis: Identify configuration and dependency files.
        
        Args:
            repo_name: The repository name in owner/repo format
            files: List of files in the repository
            
        Returns:
            List of file paths that are relevant for configuration
        """
        print(f"[CONFIG] Identifying configuration files for {repo_name}...")
        start_time = time.time()
        
        if not self.endpoint or self.endpoint == "your_endpoint":
            raise ValueError("Azure AI Project endpoint is not configured. Please set AZURE_AI_PROJECT_CONNECTION_STRING in your environment.")
        
        if not self.credential:
            raise ValueError("Azure AI Agents credentials are not configured. Please run 'az login' for DefaultAzureCredential or set AZURE_AI_AGENTS_API_KEY in your environment.")
        
        try:
            print(f"[CONFIG] Connecting to Azure AI Agents service...")
            
            # Use DefaultAzureCredential as async context manager if available
            credential_context = self.credential if isinstance(self.credential, DefaultAzureCredential) else None
            
            if credential_context:
                async with credential_context:
                    async with AgentsClient(self.endpoint, credential_context) as client:
                        return await self._process_config_identification(client, repo_name, files, start_time)
            else:
                async with AgentsClient(self.endpoint, self.credential) as client:
                    return await self._process_config_identification(client, repo_name, files, start_time)
        except asyncio.TimeoutError:
            print(f"[CONFIG] Timeout during config file identification after {time.time() - start_time:.2f} seconds")
            raise RuntimeError("Config file identification timed out")
        except Exception as e:
            print(f"[CONFIG] Error during config file identification: {str(e)}")
            print(f"[CONFIG] Error type: {type(e).__name__}")
            raise RuntimeError(f"Error identifying configuration files: {str(e)}")

    async def _process_config_identification(self, client: AgentsClient, repo_name: str, files: List[Dict[str, Any]], start_time: float) -> List[str]:
        """Process config file identification using the new Azure AI Agents API."""
        print(f"[CONFIG] Creating agent for config file identification...")
        agent_instructions = """
        You are an AI assistant that helps identify configuration and dependency files in a GitHub repository.
        Your task is to analyze the list of files in a repository and identify the most important files for understanding:
        1. How to install dependencies
        2. How to configure the development environment
        3. How to run the application
        4. How to run tests and linting
        
        Focus on files like:
        - Package management files (requirements.txt, package.json, Pipfile, pyproject.toml, Cargo.toml, go.mod, pom.xml, build.gradle)
        - Configuration files (.env.example, docker-compose.yml, tsconfig.json, webpack.config.js, vite.config.js)
        - Documentation files (README.md, INSTALL.md, CONTRIBUTING.md)
        - Build configuration files (Makefile, CMakeLists.txt, Dockerfile)
        - Testing configuration (jest.config.js, pytest.ini, tox.ini, .github/workflows/*.yml)
        
        IMPORTANT: Return only the file paths, one per line, with the most important files first.
        Use backticks around each file path like `filename.ext` for easy extraction.
        Limit to maximum 10 files.
        
        Example response:
        `README.md`
        `package.json`
        `Dockerfile`
        `tsconfig.json`
        """
        
        agent = await client.create_agent(
            model=self.model_deployment,
            name="config-file-identifier",
            instructions=agent_instructions,
        )
        
        print(f"[CONFIG] Preparing file list for analysis ({len(files)} files)...")
        file_list = "\n".join([f"{file['path']} ({file['type']})" for file in files[:100]])  # Limit to first 100 files
        
        content = f"Repository: {repo_name}\n\n"
        content += "Files in repository:\n```\n" + file_list + "\n```\n\n"
        content += "Please identify the most important configuration and dependency files from this list."
        
        print(f"[CONFIG] Starting config file identification with create_thread_and_process_run...")
        run = await client.create_thread_and_process_run(
            agent_id=agent.id,
            thread=AgentThreadCreationOptions(
                messages=[ThreadMessageOptions(role="user", content=content)]
            ),
        )
        
        if run.status == "failed":
            error_msg = f"Config identification failed: {run.last_error if run.last_error else 'Unknown error'}"
            print(f"[CONFIG] {error_msg}")
            raise RuntimeError(error_msg)
        
        print(f"[CONFIG] Config file identification completed after {time.time() - start_time:.2f} seconds")
        print(f"[CONFIG] Retrieving config file identification results...")
        
        # List all messages in the thread, in ascending order of creation
        messages = client.messages.list(
            thread_id=run.thread_id,
            order=ListSortOrder.ASCENDING,
        )
        
        response = ""
        async for msg in messages:
            if msg.role == "assistant":
                last_part = msg.content[-1]
                if isinstance(last_part, MessageTextContent):
                    response = last_part.text.value
                    break
        
        if response:
            import re
            file_paths = re.findall(r'`([^`]+)`|"([^"]+)"|\'([^\']+)\'', response)
            file_paths = [path[0] or path[1] or path[2] for path in file_paths if any(path)]
            
            # Filter to ensure they exist in the repository
            repo_files = [file["path"] for file in files]
            valid_files = [path for path in file_paths if path in repo_files]
            
            # Clean up the agent
            try:
                await client.delete_agent(agent.id)
                print(f"[CONFIG] Deleted agent {agent.id}")
            except Exception as e:
                print(f"[CONFIG] Warning: Could not delete agent {agent.id}: {str(e)}")
            
            if valid_files:
                valid_files = valid_files[:10]  # Limit to 10 most important files
                print(f"[CONFIG] Identified {len(valid_files)} config files in {time.time() - start_time:.2f} seconds: {', '.join(valid_files[:5])}" + ("..." if len(valid_files) > 5 else ""))
                return valid_files
        
        print(f"[CONFIG] No valid configuration files identified after {time.time() - start_time:.2f} seconds")
        raise RuntimeError("No valid configuration files identified by the agent")
        
    async def extract_setup_instructions(self, agent_id: str, repo_name: str, file_contents: Dict[str, str]) -> Dict[str, str]:
        """
        Second step of the two-phase analysis: Extract setup instructions from config files.
        
        Args:
            agent_id: The type of AI agent ("github-copilot", "devin", etc.)
            repo_name: The repository name in owner/repo format
            file_contents: Dictionary mapping file paths to their contents
            
        Returns:
            Dictionary of setup commands for Devin
        """
        print(f"[SETUP] Extracting setup instructions for {repo_name} with agent: {agent_id}...")
        start_time = time.time()
        
        if not self.endpoint or self.endpoint == "your_endpoint":
            raise ValueError("Azure AI Project endpoint is not configured. Please set AZURE_AI_PROJECT_CONNECTION_STRING in your environment.")
        
        if not self.credential:
            raise ValueError("Azure AI Agents credentials are not configured. Please run 'az login' for DefaultAzureCredential or set AZURE_AI_AGENTS_API_KEY in your environment.")
        
        try:
            print(f"[SETUP] Connecting to Azure AI Agents service...")
            
            # Use DefaultAzureCredential as async context manager if available
            credential_context = self.credential if isinstance(self.credential, DefaultAzureCredential) else None
            
            if credential_context:
                async with credential_context:
                    async with AgentsClient(self.endpoint, credential_context) as client:
                        return await self._process_setup_extraction(client, agent_id, repo_name, file_contents, start_time)
            else:
                async with AgentsClient(self.endpoint, self.credential) as client:
                    return await self._process_setup_extraction(client, agent_id, repo_name, file_contents, start_time)
        except asyncio.TimeoutError:
            print(f"[SETUP] Timeout during setup instruction extraction after {time.time() - start_time:.2f} seconds")
            raise RuntimeError("Setup instruction extraction timed out")
        except Exception as e:
            print(f"[SETUP] Error during setup instruction extraction: {str(e)}")
            print(f"[SETUP] Error type: {type(e).__name__}")
            if hasattr(e, '__traceback__'):
                import traceback
                print(f"[SETUP] Traceback: {traceback.format_exc()}")
            raise RuntimeError(f"Error extracting setup instructions: {str(e)}")

    async def _process_setup_extraction(self, client: AgentsClient, agent_id: str, repo_name: str, file_contents: Dict[str, str], start_time: float) -> Dict[str, str]:
        """Process setup instruction extraction using the new Azure AI Agents API."""
        print(f"[SETUP] Creating agent for setup instruction extraction...")
        agent_instructions = """
        You are an AI assistant that helps extract setup instructions from repository configuration files.
        Your task is to analyze the content of configuration files and extract commands for:
        
        1. Prerequisites: What software needs to be installed before working with this repo
        2. Dependencies: How to install project dependencies
        3. Run App: How to run the application locally
        4. Linting: How to run linters or code quality checks
        5. Testing: How to run tests
        
        IMPORTANT: You MUST respond with a valid JSON object in this exact format:
        
        ```json
        {
            "prerequisites": "Commands to install prerequisites (e.g., 'Install Node.js 16+, Python 3.8+')",
            "dependencies": "Commands to install dependencies (e.g., 'npm install' or 'pip install -r requirements.txt')",
            "run_app": "Commands to run the app (e.g., 'npm start' or 'python app.py')",
            "linting": "Commands to run linters (e.g., 'npm run lint' or 'flake8 .')",
            "testing": "Commands to run tests (e.g., 'npm test' or 'pytest')"
        }
        ```
        
        Rules:
        - Always include ALL five keys in your JSON response
        - Use actual terminal commands where possible
        - If no command is found for a category, use "No [category] commands found"
        - Be specific and provide exact commands that would work in a terminal
        - Do not include any text outside the JSON object
        """
        
        agent = await client.create_agent(
            model=self.model_deployment,
            name="setup-instruction-extractor",
            instructions=agent_instructions,
        )
        
        print(f"[SETUP] Preparing configuration files for analysis ({len(file_contents)} files)...")
        content = f"Repository: {repo_name}\n\n"
        content += "Configuration Files:\n\n"
        
        for file_path, file_content in file_contents.items():
            content += f"File: {file_path}\n```\n{file_content[:5000]}\n```\n\n"  # Limit file content to 5000 chars
        
        content += "Please extract setup instructions from these files in the format specified."
        
        print(f"[SETUP] Starting setup instruction extraction with create_thread_and_process_run...")
        run = await client.create_thread_and_process_run(
            agent_id=agent.id,
            thread=AgentThreadCreationOptions(
                messages=[ThreadMessageOptions(role="user", content=content)]
            ),
        )
        
        if run.status == "failed":
            error_msg = f"Setup extraction failed: {run.last_error if run.last_error else 'Unknown error'}"
            print(f"[SETUP] {error_msg}")
            raise RuntimeError(error_msg)
        
        print(f"[SETUP] Setup instruction extraction completed after {time.time() - start_time:.2f} seconds")
        print(f"[SETUP] Retrieving setup instruction extraction results...")
        
        # List all messages in the thread, in ascending order of creation
        messages = client.messages.list(
            thread_id=run.thread_id,
            order=ListSortOrder.ASCENDING,
        )
        
        response = ""
        async for msg in messages:
            if msg.role == "assistant":
                last_part = msg.content[-1]
                if isinstance(last_part, MessageTextContent):
                    response = last_part.text.value
                    break
        
        if response:
            import json
            import re
            
            print(f"[SETUP] Parsing JSON response (length: {len(response)} chars)...")
            print(f"[SETUP] Raw response preview: {response[:500]}{'...' if len(response) > 500 else ''}")
            
            # Try multiple extraction strategies
            json_extraction_attempts = []
            
            # Strategy 1: Look for JSON code blocks
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1).strip()
                json_extraction_attempts.append(("JSON code block", json_str))
                print(f"[SETUP] Found JSON code block: {json_str[:200]}{'...' if len(json_str) > 200 else ''}")
            
            # Strategy 2: Look for any JSON object
            json_match = re.search(r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1).strip()
                json_extraction_attempts.append(("JSON object pattern", json_str))
                print(f"[SETUP] Found JSON object pattern: {json_str[:200]}{'...' if len(json_str) > 200 else ''}")
            
            # Strategy 3: Look for more complex nested JSON
            json_match = re.search(r'(\{.*?\})', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1).strip()
                json_extraction_attempts.append(("Complex JSON pattern", json_str))
                print(f"[SETUP] Found complex JSON pattern: {json_str[:200]}{'...' if len(json_str) > 200 else ''}")
            
            # Strategy 4: Try the entire response as JSON
            json_extraction_attempts.append(("Full response", response.strip()))
            
            setup_instructions = None
            parsing_errors = []
            
            for strategy_name, json_candidate in json_extraction_attempts:
                if not json_candidate:
                    continue
                    
                try:
                    print(f"[SETUP] Attempting to parse JSON using strategy: {strategy_name}")
                    parsed = json.loads(json_candidate)
                    
                    # Validate that it has the expected structure
                    if isinstance(parsed, dict):
                        # Check if it has at least one of the expected keys
                        expected_keys = {'prerequisites', 'dependencies', 'run_app', 'linting', 'testing'}
                        if any(key in parsed for key in expected_keys):
                            setup_instructions = parsed
                            print(f"[SETUP] Successfully parsed JSON using strategy: {strategy_name}")
                            print(f"[SETUP] Extracted keys: {list(parsed.keys())}")
                            break
                        else:
                            print(f"[SETUP] Parsed JSON but missing expected keys. Found keys: {list(parsed.keys())}")
                            # Still use it as a fallback if we have any dict
                            if setup_instructions is None:
                                setup_instructions = parsed
                    else:
                        print(f"[SETUP] Parsed JSON is not a dictionary: {type(parsed)}")
                        
                except json.JSONDecodeError as e:
                    error_msg = f"Strategy '{strategy_name}' failed: {str(e)}"
                    parsing_errors.append(error_msg)
                    print(f"[SETUP] {error_msg}")
                except Exception as e:
                    error_msg = f"Strategy '{strategy_name}' failed with unexpected error: {str(e)}"
                    parsing_errors.append(error_msg)
                    print(f"[SETUP] {error_msg}")
            
            # Clean up the agent
            try:
                await client.delete_agent(agent.id)
                print(f"[SETUP] Deleted agent {agent.id}")
            except Exception as e:
                print(f"[SETUP] Warning: Could not delete agent {agent.id}: {str(e)}")
            
            if setup_instructions:
                print(f"[SETUP] Successfully extracted setup instructions in {time.time() - start_time:.2f} seconds: {', '.join(setup_instructions.keys())}")
                
                # Ensure we have the expected structure with fallbacks
                final_instructions = {
                    "prerequisites": setup_instructions.get("prerequisites", "No specific prerequisites identified"),
                    "dependencies": setup_instructions.get("dependencies", "Dependency installation commands not found"),
                    "run_app": setup_instructions.get("run_app", "Run application commands not found"),
                    "linting": setup_instructions.get("linting", "No linting commands identified"),
                    "testing": setup_instructions.get("testing", "No testing commands identified")
                }
                
                print(f"[SETUP] Final instructions structure: {', '.join(final_instructions.keys())}")
                return final_instructions
            else:
                print(f"[SETUP] Failed to parse JSON from response after {time.time() - start_time:.2f} seconds")
                print(f"[SETUP] All parsing attempts failed:")
                for error in parsing_errors:
                    print(f"[SETUP]   - {error}")
                
                # Return a fallback response instead of failing
                fallback_instructions = {
                    "prerequisites": "Unable to automatically extract prerequisites. Please check the repository's README and documentation.",
                    "dependencies": "Unable to automatically extract dependency installation commands. Please check package.json, requirements.txt, or similar files.",
                    "run_app": "Unable to automatically extract run commands. Please check the repository's README for startup instructions.",
                    "linting": "Unable to automatically extract linting commands. Check package.json scripts or similar configuration.",
                    "testing": "Unable to automatically extract testing commands. Check package.json scripts, pytest configuration, or similar."
                }
                
                print(f"[SETUP] Returning fallback instructions due to parsing failures")
                return fallback_instructions
        
        print(f"[SETUP] No setup instructions found in agent response after {time.time() - start_time:.2f} seconds")
        raise RuntimeError("No setup instructions found in agent response")
            
    async def analyze_repository(self, agent_id: str, repo_name: str, readme_content: str, dependencies: Dict[str, str], files: Optional[List[Dict[str, Any]]] = None, progress_callback: Optional[Callable[[AnalysisProgressUpdate], Awaitable[None]]] = None) -> Dict[str, Any]:
        """
        Analyze a repository using Azure AI Agents with a two-step process.
        
        Args:
            agent_id: The type of AI agent ("github-copilot", "devin", etc.)
            repo_name: The repository name in owner/repo format
            readme_content: The README content of the repository
            dependencies: Dictionary of dependency files and their contents
            files: List of files in the repository (optional)
            
        Returns:
            Dictionary with analysis results and setup commands
        """
        print(f"[ANALYSIS] Starting analysis for repository: {repo_name} with agent: {agent_id}")
        print(f"[ANALYSIS] Azure AI Agents endpoint configured: {self.endpoint != 'your_endpoint'}, Credentials available: {self.credential is not None}")
        
        if not self.endpoint or self.endpoint == "your_endpoint":
            raise ValueError("Azure AI Project endpoint is not configured. Please set AZURE_AI_PROJECT_CONNECTION_STRING in your environment.")
        
        if not self.credential:
            raise ValueError("Azure AI Agents credentials are not configured. Please run 'az login' for DefaultAzureCredential or set AZURE_AI_AGENTS_API_KEY in your environment.")
        
        # Send initial progress update
        if progress_callback:
            await progress_callback(AnalysisProgressUpdate(
                step=1,
                step_name="Analyzing Repository Content",
                status="starting",
                message=f"Starting analysis for {repo_name} with {agent_id}",
                progress_percentage=0
            ))
        
        print(f"[ANALYSIS] Step 1/3: Analyzing repository content for {repo_name}...")
        analysis_start_time = time.time()
        
        if progress_callback:
            await progress_callback(AnalysisProgressUpdate(
                step=1,
                step_name="Analyzing Repository Content",
                status="in_progress",
                message="Azure AI Agents is analyzing the repository structure and README",
                progress_percentage=10
            ))
        
        try:
            analysis = await self._analyze_with_azure_agents(agent_id, repo_name, readme_content, dependencies)
            analysis_duration = time.time() - analysis_start_time
            print(f"[ANALYSIS] Step 1/3 completed in {analysis_duration:.2f} seconds. Generated analysis length: {len(analysis)}")
            
            if progress_callback:
                await progress_callback(AnalysisProgressUpdate(
                    step=1,
                    step_name="Analyzing Repository Content",
                    status="completed",
                    message=f"Repository analysis completed in {analysis_duration:.1f} seconds",
                    progress_percentage=33,
                    elapsed_time=analysis_duration,
                    details={"analysis_length": len(analysis)}
                ))
        except Exception as e:
            analysis_duration = time.time() - analysis_start_time
            print(f"[ANALYSIS] Step 1/3 failed in {analysis_duration:.2f} seconds: {str(e)}")
            print(f"[ANALYSIS] Using fallback analysis")
            
            # Provide a fallback analysis
            analysis = f"""
# GitHub Copilot Setup Analysis for {repo_name}

**Note**: Automated analysis failed, providing general setup guidance.

## Repository Overview
Repository: {repo_name}

## GitHub Copilot (Code Completions) Setup

### Installation Steps:
1. **Install GitHub Copilot Extension**
   - For VS Code: Install from the marketplace
   - For JetBrains IDEs: Install from the plugin marketplace

2. **Authentication**
   - Sign in with your GitHub account when prompted
   - Ensure you have an active Copilot subscription (free plan available)

3. **Configuration**
   - Enable code completions in your IDE settings
   - Consider enabling Next Edit Suggestions for predictive editing
   - For VS Code 1.99+: Enable Agent Mode for multi-file editing

### Language Support
GitHub Copilot supports this repository's programming languages and can provide:
- Real-time code suggestions as you type
- Context-aware completions based on your codebase
- Multi-file editing with Agent Mode
- Comment-to-code generation

### Best Practices
- Keep related files open for better context
- Use descriptive comments to guide suggestions
- Leverage Agent Mode for complex multi-file tasks
- Review and customize suggestions to match your coding style

**Error**: Automated analysis encountered an issue. Please refer to the repository's documentation for specific setup requirements.
"""
            
            if progress_callback:
                await progress_callback(AnalysisProgressUpdate(
                    step=1,
                    step_name="Analyzing Repository Content",
                    status="completed",
                    message=f"Used fallback analysis due to processing error",
                    progress_percentage=33,
                    elapsed_time=analysis_duration,
                    details={"analysis_length": len(analysis), "fallback_used": True, "error": str(e)}
                ))
        
        # Step 2: If files are provided, perform the two-step analysis for setup commands
        if files:
            # Step 2: Identify configuration files
            if progress_callback:
                await progress_callback(AnalysisProgressUpdate(
                    step=2,
                    step_name="Identifying Configuration Files",
                    status="starting",
                    message="Scanning repository files to identify configuration and dependency files",
                    progress_percentage=35
                ))
            
            print(f"[ANALYSIS] Step 2/3: Identifying configuration files for {repo_name}...")
            config_start_time = time.time()
            
            if progress_callback:
                await progress_callback(AnalysisProgressUpdate(
                    step=2,
                    step_name="Identifying Configuration Files",
                    status="in_progress",
                    message=f"Azure AI Agents is analyzing {len(files)} files to identify important configuration files",
                    progress_percentage=45
                ))
            
            try:
                config_files = await self.identify_config_files(repo_name, files)
                config_duration = time.time() - config_start_time
                print(f"[ANALYSIS] Step 2/3 completed in {config_duration:.2f} seconds. Identified {len(config_files)} configuration files: {', '.join(config_files[:5])}" + ("..." if len(config_files) > 5 else ""))
                
                if progress_callback:
                    await progress_callback(AnalysisProgressUpdate(
                        step=2,
                        step_name="Identifying Configuration Files",
                        status="completed",
                        message=f"Identified {len(config_files)} configuration files in {config_duration:.1f} seconds",
                        progress_percentage=66,
                        elapsed_time=config_duration,
                        details={"config_files_count": len(config_files), "config_files": config_files[:5]}
                    ))
            except Exception as e:
                config_duration = time.time() - config_start_time
                print(f"[ANALYSIS] Step 2/3 failed in {config_duration:.2f} seconds: {str(e)}")
                print(f"[ANALYSIS] Using fallback config file identification")
                
                # Fallback: Use common config file patterns
                all_file_paths = [file["path"] for file in files]
                config_files = []
                
                # Common config files to look for
                common_configs = [
                    "README.md", "readme.md", "README.rst",
                    "package.json", "requirements.txt", "pyproject.toml", "Pipfile",
                    "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
                    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
                    ".gitignore", "Makefile", "CMakeLists.txt",
                    "tsconfig.json", "webpack.config.js", "vite.config.js",
                    ".env.example", ".env.template", "config.json",
                    "jest.config.js", "pytest.ini", "tox.ini"
                ]
                
                for config_file in common_configs:
                    if config_file in all_file_paths:
                        config_files.append(config_file)
                
                print(f"[ANALYSIS] Fallback identified {len(config_files)} configuration files: {', '.join(config_files[:5])}" + ("..." if len(config_files) > 5 else ""))
                
                if progress_callback:
                    await progress_callback(AnalysisProgressUpdate(
                        step=2,
                        step_name="Identifying Configuration Files",
                        status="completed",
                        message=f"Used fallback method to identify {len(config_files)} configuration files",
                        progress_percentage=66,
                        elapsed_time=config_duration,
                        details={"config_files_count": len(config_files), "config_files": config_files[:5], "fallback_used": True}
                    ))
            
            # Step 3: Extract setup instructions
            if progress_callback:
                await progress_callback(AnalysisProgressUpdate(
                    step=3,
                    step_name="Extracting Setup Instructions",
                    status="starting",
                    message="Extracting detailed setup instructions from configuration files",
                    progress_percentage=70
                ))
            
            print(f"[ANALYSIS] Step 3/3: Extracting setup instructions from configuration files...")
            setup_start_time = time.time()
            file_contents = {file_path: dependencies.get(file_path, "") for file_path in config_files if file_path in dependencies}
            
            if readme_content:
                file_contents["README.md"] = readme_content
            
            if progress_callback:
                await progress_callback(AnalysisProgressUpdate(
                    step=3,
                    step_name="Extracting Setup Instructions",
                    status="in_progress",
                    message=f"Azure AI Agents is extracting setup commands from {len(file_contents)} configuration files",
                    progress_percentage=85
                ))
            
            try:
                setup_commands = await self.extract_setup_instructions(agent_id, repo_name, file_contents)
                setup_duration = time.time() - setup_start_time
                print(f"[ANALYSIS] Step 3/3 completed in {setup_duration:.2f} seconds. Extracted setup commands for: {', '.join(setup_commands.keys())}")
                
                total_duration = time.time() - analysis_start_time
                print(f"[ANALYSIS] Total analysis completed in {total_duration:.2f} seconds for {repo_name}")
                
                if progress_callback:
                    await progress_callback(AnalysisProgressUpdate(
                        step=3,
                        step_name="Extracting Setup Instructions",
                        status="completed",
                        message=f"Setup instructions extracted successfully in {setup_duration:.1f} seconds",
                        progress_percentage=100,
                        elapsed_time=total_duration,
                        details={"setup_commands": list(setup_commands.keys()), "total_duration": total_duration}
                    ))
                
                return {
                    "analysis": analysis,
                    "setup_commands": setup_commands
                }
            except Exception as e:
                setup_duration = time.time() - setup_start_time
                total_duration = time.time() - analysis_start_time
                print(f"[ANALYSIS] Step 3/3 failed in {setup_duration:.2f} seconds: {str(e)}")
                print(f"[ANALYSIS] Continuing with analysis only (without setup commands) after {total_duration:.2f} seconds")
                
                if progress_callback:
                    await progress_callback(AnalysisProgressUpdate(
                        step=3,
                        step_name="Extracting Setup Instructions",
                        status="failed",
                        message=f"Setup instruction extraction failed, continuing with analysis only",
                        progress_percentage=100,
                        elapsed_time=total_duration,
                        details={"error": str(e), "total_duration": total_duration}
                    ))
                
                # Return analysis without setup commands if extraction fails
                return {
                    "analysis": analysis,
                    "setup_commands": {
                        "prerequisites": "Setup instruction extraction failed. Please check the repository documentation.",
                        "dependencies": "Setup instruction extraction failed. Please check package.json, requirements.txt, or similar files.",
                        "run_app": "Setup instruction extraction failed. Please check the repository's README for startup instructions.",
                        "linting": "Setup instruction extraction failed. Check for linting configuration files.",
                        "testing": "Setup instruction extraction failed. Check for testing configuration files."
                    }
                }
        
        print(f"[ANALYSIS] Analysis completed for {repo_name} (without setup commands)")
        
        if progress_callback:
            total_duration = time.time() - analysis_start_time
            await progress_callback(AnalysisProgressUpdate(
                step=1,
                step_name="Analysis Complete",
                status="completed",
                message="Repository analysis completed successfully",
                progress_percentage=100,
                elapsed_time=total_duration,
                details={"analysis_length": len(analysis)}
            ))
        
        return {
            "analysis": analysis
        }
    
    async def _analyze_with_azure_agents(self, agent_id: str, repo_name: str, readme_content: str, dependencies: Dict[str, str]) -> str:
        """
        Analyze a repository using Azure AI Agents.
        
        Args:
            agent_id: The type of AI agent
            repo_name: The repository name in owner/repo format
            readme_content: The README content of the repository
            dependencies: Dictionary of dependency files and their contents
            
        Returns:
            Analysis results as a string
        """
        try:
            print(f"[ANALYSIS] Connecting to Azure AI Agents service...")
            start_time = time.time()
            
            # Use DefaultAzureCredential as async context manager if available
            credential_context = self.credential if isinstance(self.credential, DefaultAzureCredential) else None
            
            if credential_context:
                async with credential_context:
                    async with AgentsClient(self.endpoint, credential_context) as client:
                        return await self._process_analysis(client, agent_id, repo_name, readme_content, dependencies, start_time)
            else:
                async with AgentsClient(self.endpoint, self.credential) as client:
                    return await self._process_analysis(client, agent_id, repo_name, readme_content, dependencies, start_time)
                    
        except asyncio.TimeoutError:
            print(f"[ANALYSIS] Timeout during analysis after {time.time() - start_time:.2f} seconds")
            raise RuntimeError("Analysis timed out")
        except Exception as e:
            print(f"[ANALYSIS] Error during analysis: {str(e)}")
            print(f"[ANALYSIS] Error type: {type(e).__name__}")
            raise RuntimeError(f"Error connecting to Azure AI Agents: {str(e)}")

    async def _process_analysis(self, client: AgentsClient, agent_id: str, repo_name: str, readme_content: str, dependencies: Dict[str, str], start_time: float) -> str:
        """Process the analysis using the new Azure AI Agents API."""
        print(f"[ANALYSIS] Creating agent with ID: {agent_id}...")
        agent_instructions = self._get_agent_instructions(agent_id)
        agent = await client.create_agent(
            model=self.model_deployment,
            name=f"{agent_id}-analyzer",
            instructions=agent_instructions,
        )
        
        print(f"[ANALYSIS] Preparing repository content for analysis...")
        content = f"Repository: {repo_name}\n\n"
        content += "README:\n```\n" + (readme_content or "No README found") + "\n```\n\n"
        
        if dependencies:
            content += f"Dependencies ({len(dependencies)} files):\n"
            for file_name, file_content in dependencies.items():
                content += f"{file_name}:\n```\n{file_content}\n```\n\n"
        
        print(f"[ANALYSIS] Starting analysis with create_thread_and_process_run...")
        run = await client.create_thread_and_process_run(
            agent_id=agent.id,
            thread=AgentThreadCreationOptions(
                messages=[ThreadMessageOptions(role="user", content=content)]
            ),
        )
        
        if run.status == "failed":
            error_msg = f"Analysis failed: {run.last_error if run.last_error else 'Unknown error'}"
            print(f"[ANALYSIS] {error_msg}")
            raise RuntimeError(error_msg)
        
        print(f"[ANALYSIS] Analysis completed after {time.time() - start_time:.2f} seconds")
        print(f"[ANALYSIS] Retrieving analysis results...")
        
        # List all messages in the thread, in ascending order of creation
        messages = client.messages.list(
            thread_id=run.thread_id,
            order=ListSortOrder.ASCENDING,
        )
        
        result_content = ""
        async for msg in messages:
            if msg.role == "assistant":
                last_part = msg.content[-1]
                if isinstance(last_part, MessageTextContent):
                    result_content = last_part.text.value
                    break
        
        if result_content:
            print(f"[ANALYSIS] Analysis completed successfully in {time.time() - start_time:.2f} seconds (result length: {len(result_content)} chars)")
            
            # Clean up the agent
            try:
                await client.delete_agent(agent.id)
                print(f"[ANALYSIS] Deleted agent {agent.id}")
            except Exception as e:
                print(f"[ANALYSIS] Warning: Could not delete agent {agent.id}: {str(e)}")
            
            return result_content
        
        print(f"[ANALYSIS] No analysis results found after {time.time() - start_time:.2f} seconds")
        raise RuntimeError("No analysis results found")
    

    def _get_agent_instructions(self, agent_id: str) -> str:
        """
        Get agent-specific instructions for analysis.
        
        Args:
            agent_id: The type of AI agent
            
        Returns:
            Instructions string for the agent
        """
        base_instructions = (
            "You are an AI assistant that analyzes GitHub repositories and provides detailed setup "
            "instructions for different AI agents. Your job is to analyze the repository README and "
            "dependency files to understand the project structure and requirements."
        )
        agent_specific_instructions = {
            AGENT_ID_GITHUB_COPILOT_COMPLETIONS: (
                "Focus on how to set up GitHub Copilot (Code Completions) for this repository. Explain how to "
                "install the GitHub Copilot extension in VS Code, JetBrains IDEs, or other supported editors, "
                "including authentication setup and enabling features like Next Edit Suggestions (NES) and "
                "Agent Mode for multi-file editing. Provide tips for getting the best code suggestions based on "
                "this repository's structure, languages, and how to leverage context from open files. Include "
                "guidance on using Agent Mode for complex tasks like 'Add social media sharing functionality' "
                "or 'Replace current auth with OAuth' that span multiple files."
            ),
            AGENT_ID_GITHUB_COPILOT_AGENT: (
                "Focus on how to set up GitHub Copilot Coding Agent for this repository. Explain how to enable "
                "the agent in organization and repository settings, create well-scoped issues with clear acceptance "
                "criteria, and assign issues to Copilot. Describe how it uses GitHub Actions compute environment "
                "to autonomously fix bugs, implement features, improve test coverage, and update documentation. "
                "Mention the secure workflow with branch protections, session logs for progress tracking, and "
                "iteration via PR review comments. Include guidance on .github/copilot-instructions.md for "
                "custom repository guidelines and best practices for low-to-medium complexity tasks."
            ),
            AGENT_ID_DEVIN: (
                "You are **Devin-Repo-Setup-Assistant**.\n"
                "Your job is to fill out Devin's eight-step \"Set up <repo>\" wizard for the current repository.\n\n"
                "GLOBAL GUIDELINES\n"
                "- Never use an em dash. Use a plain hyphen instead.\n"
                "- Treat the working copy of the repo as read-only. Generate commands, files, and notes – do not edit code directly.\n"
                "- Assume the repo is cloned into ~/repos/<repo-dir>.\n"
                "  Always cd into that folder before you run any command.\n"
                "- When choosing commands, prefer deterministic ones (npm ci, pip install -r).\n"
                "  Avoid anything interactive.\n"
                "- All commands must succeed inside the default Ubuntu 22.04 image that Devin uses.\n"
                "- If a step is optional but clearly useful (lint, tests), do not skip it.\n"
                "  Otherwise leave the step blank and explain why in **Additional Notes**.\n"
                "- If a required file (README, requirements.txt, package.json, pom.xml, bicep, Dockerfile, etc.) is missing, say so in **Additional Notes** and suggest follow-ups.\n\n"
                "STEP-BY-STEP OUTPUT SPECIFICATION\n"
                "1. **Git Pull**\n"
                "   - Always output\n"
                "     `cd ~/repos/<repo-dir> && git pull && git submodule update --init --recursive`\n"
                "   - Replace <repo-dir> with the actual folder name.\n\n"
                "2. **Configure Secrets**\n"
                "   - Scan the codebase for:\n"
                "     - .env.example, .envrc, or any getenv/EnvironmentVariable look-ups.\n"
                "     - Keys used by Azure SDKs, OpenAI, PostgreSQL, etc.\n"
                "   - Produce a `.env` template listing every variable that appears optional=false.\n"
                "     For each Azure credential, explain how to create it by scripting:\n\n"
                "     ```\n"
                "     # login to Azure\n"
                "     az login\n\n"
                "     # create a service principal scoped to the resource group your Bicep files deploy to\n"
                "     az ad sp create-for-rbac \\\n"
                "       --name \"<repo>-devin-sp\" \\\n"
                "       --role Contributor \\\n"
                "       --scopes /subscriptions/<subId>/resourceGroups/<rgName> \\\n"
                "       --sdk-auth > .azure.sp.json\n"
                "     ```\n\n"
                "     - Tell the user to copy these fields into .env\n"
                "       AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET, AZURE_SUBSCRIPTION_ID\n"
                "     - If you detect Bicep modules that deploy Container Apps, AKS, Key Vault, Cosmos DB, or other resources that require narrower roles, add extra\n"
                "       `az role assignment create` commands with the proper built-in role names.\n\n"
                "3. **Install Dependencies**\n"
                "   Choose ONE shell command block that installs everything:\n\n"
                "   | Signals found in repo            | Install command                             |\n"
                "   |----------------------------------|---------------------------------------------|\n"
                "   | requirements.txt / pyproject     | `python -m pip install -r requirements.txt` |\n"
                "   | Pipfile                           | `pip install pipenv && pipenv sync`         |\n"
                "   | package.json + yarn.lock         | `corepack enable && yarn install --immutable`|\n"
                "   | package.json + package-lock.json | `npm ci`                                    |\n"
                "   | poetry.lock                       | `pip install poetry && poetry install`      |\n"
                "   | maven pom.xml                    | `mvn -B package -DskipTests`                |\n"
                "   | gradle build.gradle              | `./gradlew build -x test`                   |\n\n"
                "   Include any compiler or linter the README calls out (gcc, make, ruff, eslint, etc.).\n\n"
                "4. **Maintain Dependencies**\n"
                "   Re-run the same command you chose in Step 3.\n\n"
                "5. **Setup Lint**\n"
                "   - If package.json has a \"lint\" script → `npm run lint`.\n"
                "   - If a Python project has ruff, flake8, or pylint config → `ruff check .` or `flake8 .`.\n"
                "   - Otherwise, leave blank and explain in Additional Notes.\n\n"
                "6. **Setup Tests**\n"
                "   - If package.json has a \"test\" script → `npm test`.\n"
                "   - If pytest directory exists → `pytest -q`.\n"
                "   - If Maven/Gradle → `mvn -B test` or `./gradlew test`.\n"
                "   - Skip only if the repo truly contains no tests.\n\n"
                "7. **Setup Local App**\n"
                "   Derive the dev-server command from common markers:\n"
                "   - Next.js → `npm run dev`\n"
                "   - React Vite → `npm run dev`\n"
                "   - FastAPI → `uvicorn <module>:app --port 8000 --reload`\n"
                "   - Django → `python manage.py runserver 8000`\n"
                "   - Spring Boot → `mvn spring-boot:run`\n"
                "   - Document the expected local URL (default http://localhost:3000 or 8000).\n\n"
                "8. **Additional Notes**\n"
                "   - Summarize anything that could trip Devin up: polyglot repo, sub-repos, proprietary build tools, enormous datasets, etc.\n"
                "   - List any manual steps that cannot be scripted yet (VPN, hardware tokens, private package registries).\n"
                "   - Mention any long-running tasks that exceed the wizard's 5-minute limit so the user can cache artifacts first.\n\n"
                "PREREQUISITE CHECKLIST FOR THE HUMAN USER\n"
                "- They must have Devin installed and linked to GitHub (https://aka.ms/devin).\n"
                "- After installing, they must add the repo inside **https://app.devin.ai/workspace**.\n"
                "- Follow the GitHub integration guide if the repo is missing – https://docs.devin.ai/integrations/gh.\n"
                "- A quick video walkthrough is here: https://www.youtube.com/watch?v=fgSzneNlpZs.\n"
                "- Once those steps are done, run the wizard and paste the sections you generated."
            ),
            AGENT_ID_CODEX_CLI: (
                "Focus on how to set up Codex CLI for this repository. Explain how to install "
                "and configure Codex CLI with Azure OpenAI or OpenAI, how to use it effectively with this "
                "repository, and provide example commands tailored to this repository's structure."
            ),
            AGENT_ID_SREAGENT: (
                "Focus on how to set up SREAgent for this repository. Explain how to configure "
                "SREAgent in an Azure environment, how to connect it with this repository, "
                "and recommend monitoring metrics and alert policies based on this repository's "
                "structure and purpose."
            )
        }
        
        # Support legacy IDs for backward compatibility
        lookup_id = LEGACY_AGENT_ID_MAP.get(agent_id, agent_id)
        if lookup_id in agent_specific_instructions:
            return base_instructions + "\n\n" + agent_specific_instructions[lookup_id]
        return base_instructions

    async def breakdown_user_request(self, user_request: str) -> Dict[str, Any]:
        """
        Break down a user request into multiple manageable tasks for Devin sessions.
        
        Args:
            user_request: The user's description of work they want done
            
        Returns:
            Dictionary containing a list of tasks with titles and descriptions
        """
        print(f"[BREAKDOWN] Breaking down user request: {user_request[:100]}...")
        start_time = time.time()
        
        if not self.endpoint or self.endpoint == "your_endpoint":
            raise ValueError("Azure AI Project endpoint is not configured. Please set AZURE_AI_PROJECT_CONNECTION_STRING in your environment.")
        
        if not self.credential:
            raise ValueError("Azure AI Agents credentials are not configured. Please run 'az login' for DefaultAzureCredential or set AZURE_AI_AGENTS_API_KEY in your environment.")
        
        try:
            async with AgentsClient(endpoint=self.endpoint, credential=self.credential) as client:
                return await self._process_task_breakdown(client, user_request, start_time)
        except Exception as e:
            print(f"[BREAKDOWN] Error during task breakdown: {str(e)}")
            raise RuntimeError(f"Task breakdown failed: {str(e)}")

    async def _process_task_breakdown(self, client: AgentsClient, user_request: str, start_time: float) -> Dict[str, Any]:
        """Process the task breakdown using Azure AI Agents API."""
        print(f"[BREAKDOWN] Creating task breakdown agent...")
        
        breakdown_instructions = (
            "You are a Task Breakdown Assistant. Your job is to take a user's high-level request "
            "and break it down into 3-6 smaller, manageable tasks that can each be completed independently "
            "by an AI coding assistant like Devin.\n\n"
            "Guidelines:\n"
            "- Each task should be specific and actionable\n"
            "- Tasks should be independent of each other when possible\n"
            "- Each task should be completable in a reasonable amount of time (1-3 hours)\n"
            "- Include enough detail so each task is clear\n"
            "- Focus on coding, development, and technical implementation tasks\n\n"
            "Output format:\n"
            "Return a JSON object with a 'tasks' array containing objects with 'title' and 'description' fields.\n"
            "Example:\n"
            "{\n"
            "  \"tasks\": [\n"
            "    {\n"
            "      \"title\": \"Create user authentication API\",\n"
            "      \"description\": \"Implement login and registration endpoints with JWT token generation\"\n"
            "    },\n"
            "    {\n"
            "      \"title\": \"Add user profile management\",\n"
            "      \"description\": \"Create endpoints for users to view and update their profile information\"\n"
            "    }\n"
            "  ]\n"
            "}"
        )
        
        agent = await client.create_agent(
            model=self.model_deployment,
            name="task-breakdown-assistant",
            instructions=breakdown_instructions,
        )
        
        print(f"[BREAKDOWN] Processing user request...")
        content = f"Please break down this user request into manageable tasks:\n\n{user_request}"
        
        run = await client.create_thread_and_process_run(
            agent_id=agent.id,
            thread=AgentThreadCreationOptions(
                messages=[ThreadMessageOptions(role="user", content=content)]
            ),
        )
        
        if run.status == "failed":
            error_msg = f"Task breakdown failed: {run.last_error if run.last_error else 'Unknown error'}"
            print(f"[BREAKDOWN] {error_msg}")
            raise RuntimeError(error_msg)
        
        print(f"[BREAKDOWN] Retrieving breakdown results...")
        
        # List all messages in the thread, in ascending order of creation
        messages = client.messages.list(
            thread_id=run.thread_id,
            order=ListSortOrder.ASCENDING,
        )
        
        result_content = ""
        async for msg in messages:
            if msg.role == "assistant":
                last_part = msg.content[-1]
                if isinstance(last_part, MessageTextContent):
                    result_content = last_part.text.value
                    break
        
        # Clean up the agent
        try:
            await client.delete_agent(agent.id)
            print(f"[BREAKDOWN] Deleted agent {agent.id}")
        except Exception as e:
            print(f"[BREAKDOWN] Warning: Could not delete agent {agent.id}: {str(e)}")
        
        if not result_content:
            print(f"[BREAKDOWN] No breakdown results found after {time.time() - start_time:.2f} seconds")
            raise RuntimeError("No breakdown results found")
        
        try:
            # Parse the JSON response
            import json
            # Try to extract JSON from the response
            if "```json" in result_content:
                # Extract JSON from code block
                json_start = result_content.find("```json") + 7
                json_end = result_content.find("```", json_start)
                json_content = result_content[json_start:json_end].strip()
            elif "{" in result_content and "}" in result_content:
                # Try to find JSON in the response
                json_start = result_content.find("{")
                json_end = result_content.rfind("}") + 1
                json_content = result_content[json_start:json_end]
            else:
                # If no JSON found, create a default structure
                raise ValueError("No JSON found in response")
            
            breakdown_result = json.loads(json_content)
            
            # Validate the structure
            if "tasks" not in breakdown_result or not isinstance(breakdown_result["tasks"], list):
                raise ValueError("Invalid response structure")
            
            for task in breakdown_result["tasks"]:
                if "title" not in task or "description" not in task:
                    raise ValueError("Task missing required fields")
            
            print(f"[BREAKDOWN] Successfully parsed {len(breakdown_result['tasks'])} tasks in {time.time() - start_time:.2f} seconds")
            return breakdown_result
            
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[BREAKDOWN] Failed to parse JSON response: {str(e)}")
            print(f"[BREAKDOWN] Raw response: {result_content}")
            
            # Fallback: create a single task from the original request
            fallback_result = {
                "tasks": [
                    {
                        "title": "Complete the requested work",
                        "description": user_request
                    }
                ]
            }
            print(f"[BREAKDOWN] Using fallback task breakdown")
            return fallback_result
