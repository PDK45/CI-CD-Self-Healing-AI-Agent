import os
from dotenv import load_dotenv

# Ensure we actually find the .env file located one directory up (in backend/)
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(dotenv_path)

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from agent.state import AgentState
from agent.context_builder import log_analyzer
from agent.tools.github_service import github_service

import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agent.state import AgentState
from agent.context_builder import log_analyzer
from agent.tools.github_service import github_service

# Initialize the real LLM
gemini_api_key = os.getenv("GEMINI_API_KEY")
if not gemini_api_key:
    print("CRITICAL ERROR: GEMINI_API_KEY environment variable is missing! The AI workflows will fail.")
else:
    os.environ["GOOGLE_API_KEY"] = gemini_api_key
    
# Using gemini-1.5-flash as it is extremely fast, has a massive context window for logs, and offers a generous free tier
llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.1, api_key=gemini_api_key)

async def diagnostician_node(state: AgentState):
    """
    Node 1: Receives the raw logs, extracting the summary and the specific files 
    that need to be downloaded from GitHub to write the fix.
    """
    print(f"--- [DIAGNOSTICIAN] Analyzing Logs for Run {state['run_id']} ---")
    
    # 1. Shrink massively long logs down to the actual error trace
    trimmed_logs = log_analyzer.extract_error_trace(state["raw_logs"])
    
    # 2. Ask the LLM to identify the error and the files involved
    prompt = f"""
    You are an expert CI/CD DevOps Engineer. A build pipeline just failed.
    Here is the exact error trace:
    
    <error_trace>
    {trimmed_logs}
    </error_trace>
    
    Your job is to:
    1. Briefly summarize why the build failed.
    2. Identify the exact file paths within the repository that likely need to be modified or inspected to fix this bug.
    
    Return your response EXTRACTLY as a JSON object with two keys:
    "summary": "String",
    "files": ["file1.py", "src/file2.js"]
    """
    
    response = llm.invoke([HumanMessage(content=prompt)])
    
    try:
        # Very rough JSON parsing; in prod, use LangChain's StructuredOutputParser
        json_str = response.content.strip().lstrip('```json').rstrip('```')
        result_dict = json.loads(json_str)
        
        summary = result_dict.get("summary", "Failed to parse summary")
        files_to_fetch = result_dict.get("files", [])
        
    except Exception as e:
        print(f"JSON Parse error in Diagnostician: {e}")
        summary = response.content
        files_to_fetch = []

    print(f"  -> Summary: {summary}")
    print(f"  -> Files to fetch: {files_to_fetch}")

    return {
        "error_summary": summary,
        "files_to_fetch": files_to_fetch
    }


async def researcher_node(state: AgentState):
    """
    Node 2: Takes the files identified by the diagnostician and fetches 
    their actual raw content from GitHub APIs.
    """
    print(f"--- [RESEARCHER] Fetching {len(state['files_to_fetch'])} files from GitHub ---")
    
    file_contents = {}
    repo = state["repository"]
    commit = state["commit_sha"]
    
    for file_path in state["files_to_fetch"]:
        print(f"  -> Fetching: {file_path}")
        content = await github_service.get_file_content(repo, file_path, commit)
        file_contents[file_path] = content
        
    return {"file_contents": file_contents}


async def solver_node(state: AgentState):
    """
    Node 3: Takes the error summary and the raw files, and writes a proposed patch.
    """
    print("--- [SOLVER] Drafting Code Patch ---")
    
    context = ""
    for path, code in state["file_contents"].items():
        context += f"\\n\\n--- START OF FILE: {path} ---\\n{code}\\n--- END OF FILE ---"
        
    prompt = f"""
    You are a Senior Software Engineer resolving a CI/CD failure.
    
    Failure reason: {state['error_summary']}
    
    Here is the relevant code structure:
    {context}
    
    If the Critic previously rejected your code, here is their feedback: 
    {state.get('critic_feedback', 'N/A')}
    
    Write the updated file(s) to fix the issue. 
    Wrap each patched file in a markdown codeblock specifically mentioning the filepath on the first line. For example:
    
    ```python
    # filename/path.py
    def patched_code():
        pass
    ```
    """
    
    response = llm.invoke([HumanMessage(content=prompt)])
    print("  -> Patch drafted.")
    return {"proposed_patch": response.content}


async def critic_node(state: AgentState):
    """
    Node 4: Reviews the Solver's proposed patch to ensure it actually 
    resolves the CI failure and doesn't introduce syntax errors.
    """
    print("--- [CRITIC] Reviewing Solver's Patch ---")
    
    prompt = f"""
    You are a Staff Level Code Reviewer. 
    A junior engineer has proposed a fix for a CI/CD pipeline failure.
    
    Original Error: {state['error_summary']}
    
    Proposed Fix:
    {state['proposed_patch']}
    
    Review this code. If it perfectly fixes the bug and contains zero syntax errors, 
    reply with exactly the string "APPROVE".
    
    If it is wrong, hallucinated, or introduces new bugs, reply with detailed feedback 
    on what they did wrong so they can rewrite it. Do not just say REJECT. Tell them why.
    """
    
    response = llm.invoke([HumanMessage(content=prompt)])
    content = response.content.strip()
    
    if content == "APPROVE":
         print("  -> Verdict: APPROVED")
         return {"is_patch_approved": True, "critic_feedback": None}
    else:
         print(f"  -> Verdict: REJECTED.\\n  -> Feedback: {content[:100]}...")
         return {"is_patch_approved": False, "critic_feedback": content}
