from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import json
import asyncio
import os
from .models.schemas import RepositoryAnalysisRequest, RepositoryAnalysisResponse, RepositoryInfoResponse, AnalysisProgressUpdate, TaskBreakdownRequest, TaskBreakdownResponse, Task, DevinSessionRequest, DevinSessionResponse
from .services.github import GitHubService
from .services.agent import AzureAgentService
from .config import CORS_ORIGINS
from .logging_config import setup_logging, get_api_logger

# Set up logging
log_level = os.getenv("LOG_LEVEL", "INFO")
setup_logging(level=log_level, format_style="detailed")
logger = get_api_logger()

app = FastAPI(title="gitagu Backend", description="Backend API for gitagu")

logger.info("Starting gitagu Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_github_service():
    return GitHubService()

def get_agent_service():
    return AzureAgentService()

@app.get("/")
async def root():
    logger.info("Root endpoint accessed")
    return {"message": "gitagu Backend API", "status": "healthy"}

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    try:
        # Basic health check - could be extended to check dependencies
        return {
            "status": "healthy",
            "service": "gitagu Backend",
            "timestamp": "2025-01-27T08:00:00Z"
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Service unavailable")

@app.post("/api/analyze", response_model=RepositoryAnalysisResponse)
async def analyze_repository(
    request: RepositoryAnalysisRequest,
    github_service: GitHubService = Depends(get_github_service),
    agent_service: AzureAgentService = Depends(get_agent_service)
):
    try:
        logger.info(f"Starting analysis for repository: {request.owner}/{request.repo} with agent: {request.agent_id}")
        print(f"Analyzing repository: {request.owner}/{request.repo} with agent: {request.agent_id}")
        
        repo_info = await github_service.get_repository_info(request.owner, request.repo)
        if not repo_info:
            print(f"Repository not found: {request.owner}/{request.repo}")
            repo_info = {"name": request.repo, "full_name": f"{request.owner}/{request.repo}"}
        
        readme_content = await github_service.get_readme_content(request.owner, request.repo)
        print(f"README content found: {readme_content is not None}")
        
        dependencies = await github_service.get_requirements(request.owner, request.repo)
        print(f"Dependencies found: {len(dependencies)}")
        
        files = await github_service.get_repository_files(request.owner, request.repo)
        print(f"Repository files found: {len(files)}")
        
        files_dict = [{"path": file.path, "type": file.type, "size": file.size} for file in files]
        
        analysis_result = await agent_service.analyze_repository(
            request.agent_id,
            f"{request.owner}/{request.repo}",
            readme_content or "No README found",  # Provide default if None
            dependencies or {},  # Provide empty dict if None
            files_dict
        )
        
        analysis = analysis_result.get("analysis", "")
        setup_commands = analysis_result.get("setup_commands", {})
        
        print(f"Analysis result length: {len(analysis)}")
        print(f"Setup commands found: {len(setup_commands)}")
        
        logger.info(f"Analysis completed successfully for {request.owner}/{request.repo}")
        return RepositoryAnalysisResponse(
            agent_id=request.agent_id,
            repo_name=f"{request.owner}/{request.repo}",
            analysis=analysis,
            setup_commands=setup_commands
        )
    except Exception as e:
        logger.error(f"Error analyzing repository {request.owner}/{request.repo}: {str(e)}", exc_info=True)
        print(f"Error analyzing repository: {str(e)}")
        return RepositoryAnalysisResponse(
            agent_id=request.agent_id,
            repo_name=f"{request.owner}/{request.repo}",
            analysis=f"Error analyzing repository: {str(e)}",
            error=str(e)
        )

@app.post("/api/analyze-stream")
async def analyze_repository_stream(
    request: RepositoryAnalysisRequest,
    github_service: GitHubService = Depends(get_github_service),
    agent_service: AzureAgentService = Depends(get_agent_service)
):
    """Stream real-time progress updates during repository analysis."""
    
    async def generate_progress_stream():
        try:
            print(f"Starting streaming analysis for repository: {request.owner}/{request.repo} with agent: {request.agent_id}")
            
            # Create a queue to collect progress updates
            import asyncio
            progress_queue = asyncio.Queue()
            analysis_complete = False
            
            async def progress_callback(update: AnalysisProgressUpdate):
                await progress_queue.put(update)
            
            # Start the analysis in a background task
            async def run_analysis():
                nonlocal analysis_complete
                try:
                    # Fetch repository data
                    repo_info = await github_service.get_repository_info(request.owner, request.repo)
                    if not repo_info:
                        print(f"Repository not found: {request.owner}/{request.repo}")
                        repo_info = {"name": request.repo, "full_name": f"{request.owner}/{request.repo}"}
                    
                    readme_content = await github_service.get_readme_content(request.owner, request.repo)
                    dependencies = await github_service.get_requirements(request.owner, request.repo)
                    files = await github_service.get_repository_files(request.owner, request.repo)
                    
                    files_dict = [{"path": file.path, "type": file.type, "size": file.size} for file in files]
                    
                    # Perform analysis with progress callback
                    analysis_result = await agent_service.analyze_repository(
                        request.agent_id,
                        f"{request.owner}/{request.repo}",
                        readme_content or "No README found",
                        dependencies or {},
                        files_dict,
                        progress_callback=progress_callback
                    )
                    
                    # Send final result to queue
                    final_response = RepositoryAnalysisResponse(
                        agent_id=request.agent_id,
                        repo_name=f"{request.owner}/{request.repo}",
                        analysis=analysis_result.get("analysis", ""),
                        setup_commands=analysis_result.get("setup_commands", {})
                    )
                    
                    await progress_queue.put({"type": "final_result", "data": final_response.model_dump()})
                    await progress_queue.put({"type": "complete"})
                    
                except Exception as e:
                    print(f"Error in analysis task: {str(e)}")
                    await progress_queue.put({
                        "type": "error",
                        "error": str(e),
                        "agent_id": request.agent_id,
                        "repo_name": f"{request.owner}/{request.repo}"
                    })
                finally:
                    analysis_complete = True
            
            # Start the analysis task
            analysis_task = asyncio.create_task(run_analysis())
            
            # Stream progress updates as they come in
            while not analysis_complete or not progress_queue.empty():
                try:
                    # Wait for next update with timeout
                    update = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                    
                    if hasattr(update, 'model_dump'):  # It's an AnalysisProgressUpdate
                        yield f"data: {json.dumps(update.model_dump())}\n\n"
                    else:  # It's a dict (final result, error, etc.)
                        yield f"data: {json.dumps(update)}\n\n"
                        
                        if update.get("type") in ["complete", "error"]:
                            break
                            
                except asyncio.TimeoutError:
                    # Check if analysis is still running
                    if analysis_complete:
                        break
                    continue
            
            # Ensure the analysis task completes
            if not analysis_task.done():
                await analysis_task
            
        except Exception as e:
            print(f"Error in streaming analysis: {str(e)}")
            error_response = {
                "type": "error",
                "error": str(e),
                "agent_id": request.agent_id,
                "repo_name": f"{request.owner}/{request.repo}"
            }
            yield f"data: {json.dumps(error_response)}\n\n"
    
    return StreamingResponse(
        generate_progress_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        }
    )

@app.get("/api/repo-info/{owner}/{repo}", response_model=RepositoryInfoResponse)
async def get_repository_info(
    owner: str,
    repo: str,
    github_service: GitHubService = Depends(get_github_service)
):
    try:
        print(f"Fetching repository data for {owner}/{repo}...")
        repo_data = await github_service.get_repository_snapshot(owner, repo)
        if not repo_data:
            print(f"Repository not found: {owner}/{repo}")
            raise HTTPException(status_code=404, detail="Repository not found")
        
        return RepositoryInfoResponse(**repo_data)
    except HTTPException:
        # Re-raise HTTPException without modification
        raise
    except RuntimeError as e:
        error_msg = f"Error fetching repository info: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/api/breakdown-tasks", response_model=TaskBreakdownResponse)
async def breakdown_tasks(
    request: TaskBreakdownRequest,
    agent_service: AzureAgentService = Depends(get_agent_service)
):
    """Break down a user request into multiple tasks for Devin sessions."""
    try:
        logger.info(f"Breaking down task: {request.request[:100]}...")
        print(f"Breaking down task: {request.request[:100]}...")
        
        # Use the existing agent service to break down the task
        breakdown_result = await agent_service.breakdown_user_request(request.request)
        
        # Convert the result to our Task models
        tasks = [
            Task(title=task["title"], description=task["description"])
            for task in breakdown_result["tasks"]
        ]
        
        logger.info(f"Successfully broke down request into {len(tasks)} tasks")
        return TaskBreakdownResponse(tasks=tasks)
        
    except Exception as e:
        logger.error(f"Error breaking down tasks: {str(e)}", exc_info=True)
        print(f"Error breaking down tasks: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to break down tasks: {str(e)}")

@app.post("/api/create-devin-session", response_model=DevinSessionResponse)
async def create_devin_session(request: DevinSessionRequest):
    """Proxy endpoint to create a Devin session."""
    try:
        import httpx
        
        logger.info(f"Creating Devin session with prompt: {request.prompt[:100]}...")
        print(f"Creating Devin session with prompt: {request.prompt[:100]}...")
        
        # Prepare the payload for Devin API
        payload = {
            "prompt": request.prompt
        }
        
        if request.snapshot_id:
            payload["snapshot_id"] = request.snapshot_id
            
        if request.playbook_id:
            payload["playbook_id"] = request.playbook_id
        
        # Make the request to Devin API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.devin.ai/v1/sessions",
                headers={
                    "Authorization": f"Bearer {request.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30.0
            )
            
            if response.status_code != 200:
                error_detail = f"Devin API error: {response.status_code}"
                try:
                    error_data = response.json()
                    error_detail += f" - {error_data}"
                except:
                    error_detail += f" - {response.text}"
                
                logger.error(f"Devin API error: {error_detail}")
                raise HTTPException(status_code=response.status_code, detail=error_detail)
            
            session_data = response.json()
            
            # Extract session info
            session_id = session_data.get("session_id") or session_data.get("id")
            if not session_id:
                raise HTTPException(status_code=500, detail="No session ID returned from Devin API")
            
            # Remove "devin-" prefix if present for the URL
            clean_session_id = session_id.replace("devin-", "") if session_id.startswith("devin-") else session_id
            session_url = f"https://app.devin.ai/sessions/{clean_session_id}"
            
            logger.info(f"Successfully created Devin session: {session_id}")
            return DevinSessionResponse(
                session_id=session_id,
                session_url=session_url
            )
            
    except httpx.RequestError as e:
        logger.error(f"Network error calling Devin API: {str(e)}")
        raise HTTPException(status_code=503, detail=f"Failed to connect to Devin API: {str(e)}")
    except Exception as e:
        logger.error(f"Error creating Devin session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create Devin session: {str(e)}")
