import os
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

# Ensure we actually find the .env file located in backend/
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

from agent.graph import app as agent_workflow

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage

app = FastAPI(
    title="CI/CD Auto-Healer API",
    description="Backend for the AI-powered CI/CD automatic healing agent.",
    version="1.0.0"
)

# Setup basic Jinja2 template rendering for the frontend
templates = Jinja2Templates(directory="templates")

# Shared LLM for chat — Groq (Llama 3.3 70B) is free-tier with high daily limits
groq_api_key = os.getenv("GROQ_API_KEY")
if not groq_api_key:
    print("CRITICAL ERROR: GROQ_API_KEY environment variable is missing!")

llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.7, groq_api_key=groq_api_key)

# Basic model for standard Webhook responses
class WebhookResponse(BaseModel):
    status: str
    message: str
    run_id: int | None = None

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default_session"

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Standard conversational LLM endpoint for general "Gemini-style" prompting.
    Streams the response back to the client token by token.
    """
    SYSTEM_PROMPT = """You are Neoverse OS — the AI brain of the Neoverse CI/CD Self-Healing Agent.

Your purpose is to autonomously monitor, diagnose, and fix failing CI/CD pipelines on GitHub without human intervention.

You are part of a multi-agent system built with LangGraph and LangChain, consisting of:
- Diagnostician Agent: Analyzes raw CI/CD logs to identify the exact root cause of build failures
- Researcher Agent: Fetches the relevant source code files from GitHub based on the error trace
- Solver Agent: Generates a precise code patch (diff) to fix the identified issue
- Critic Agent: Reviews the patch for correctness and security, looping back to the Solver if needed
- Once approved, the system creates a Git branch and opens a Pull Request automatically

You can also assist developers directly through this chat interface — answering questions about failed builds, explaining errors, writing code fixes, reviewing CI/CD configurations (GitHub Actions, Dockerfiles, YAML), and advising on best practices.

Always respond as Neoverse OS. Be precise, technical, and helpful. When discussing your capabilities, refer to the specific agents and tools in the Neoverse system."""

    async def generate():
        try:
            from langchain_core.messages import SystemMessage
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=request.message)
            ]
            async for chunk in llm.astream(messages):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            yield f"\n\n[Agent Error]: {str(e)}"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Serves the main frontend dashboard."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/favicon.ico")
async def favicon():
    return {}

@app.post("/webhook", response_model=WebhookResponse)
async def github_webhook(request: Request):
    """
    Receives webhook events from GitHub Actions.
    We are primarily interested in 'workflow_run' events that have a status of 'completed' and conclusion of 'failure'.
    """
    # Verify GitHub signature here in production!
    
    # Get the GitHub event type from headers
    event_type = request.headers.get("X-GitHub-Event")
    
    if event_type == "ping":
        return WebhookResponse(status="success", message="Pong! Webhook received.")
        
    if event_type != "workflow_run":
        return WebhookResponse(status="ignored", message=f"Ignoring event type: {event_type}")
        
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    action = payload.get("action")
    workflow_run = payload.get("workflow_run", {})
    
    # We only care when a workflow run completes
    if action != "completed":
        return WebhookResponse(status="ignored", message="Workflow run is not complete.")
        
    # We only care if it failed
    conclusion = workflow_run.get("conclusion")
    if conclusion != "failure":
        return WebhookResponse(status="ignored", message=f"Workflow conclusion is {conclusion}, ignoring.")
        
    # Extract fields from the payload
    repo_full_name = payload.get("repository", {}).get("full_name", "unknown/repo")
    run_id = workflow_run.get("id", 0)
    commit_sha = workflow_run.get("head_sha", "unknown")

    try:
        # 1. Fetch the raw failing logs (using our github service)
        from agent.tools.github_service import github_service
        raw_logs = await github_service.get_failed_run_logs(repo_full_name, run_id)
        
        # 2. Kick off the LangGraph Agent workflow asynchronously!
        initial_state = {
            "repository": repo_full_name,
            "run_id": run_id,
            "commit_sha": commit_sha,
            "raw_logs": raw_logs,
            "messages": []
        }
        
        # We need a thread_id so the checkpointer can save the state of this specific fix loop
        thread = {"configurable": {"thread_id": f"run_{run_id}"}}
        
        # Warning: For a true production SaaS, this `astream` call should be pushed to 
        # a background queue (like Celery/RabbitMQ) so we don't block the webhook response.
        # For the MVP, we will print the live streaming output to the console.
        
        print("\n=== STARTING AGENT WORKFLOW ===")
        # Using `.stream` allows us to yield updates as each node finishes
        async for output in agent_workflow.astream(initial_state, thread):
             # output is a dict where key is the node name, value is the state delta
             for node_name, state_update in output.items():
                 print(f"[{node_name}] State Update Detected")
        print("=== END AGENT WORKFLOW ===\n")

    except Exception as e:
         print(f"Error kicking off workflow: {e}")
         return WebhookResponse(status="error", message=str(e), run_id=run_id)

    return WebhookResponse(
        status="processing", 
        message=f"Failure detected. LangGraph agent successfully initiated for Run ID {run_id}",
        run_id=run_id
    )

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
