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

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

app = FastAPI(
    title="CI/CD Auto-Healer API",
    description="Backend for the AI-powered CI/CD automatic healing agent.",
    version="1.0.0"
)

# Setup basic Jinja2 template rendering for the frontend
templates = Jinja2Templates(directory="templates")

# Shared basic LLM for chat
gemini_api_key = os.getenv("GEMINI_API_KEY")
if not gemini_api_key:
    print("CRITICAL ERROR: GEMINI_API_KEY environment variable is missing! The Chat API will fail.")
else:
    os.environ["GOOGLE_API_KEY"] = gemini_api_key

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.7, api_key=gemini_api_key)

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
    async def generate():
        try:
            async for chunk in llm.astream([HumanMessage(content=request.message)]):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            # Surface the error gracefully to the UI instead of dropping the connection
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
        
    try:
        # 1. Fetch the raw failing logs (using our github service)
        from agent.tools.github_service import github_service
        raw_logs = await github_service.get_failed_run_logs(repo_full_name, run_id)
        
        # 2. Kick off the LangGraph Agent workflow asynchronously!
        # Define the initial state the graph starts with
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
