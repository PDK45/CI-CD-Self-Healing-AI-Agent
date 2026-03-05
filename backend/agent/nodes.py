import os
import json
from dotenv import load_dotenv

# Ensure we find the .env file in the backend/ directory
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(dotenv_path)

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from agent.state import AgentState
from agent.context_builder import log_analyzer
from agent.tools.github_service import github_service

# Initialize Groq LLM — Llama 3.3-70B: excellent at code analysis and fixing
groq_api_key = os.getenv("GROQ_API_KEY")
if not groq_api_key:
    print("CRITICAL ERROR: GROQ_API_KEY is missing! The AI workflows will fail.")

llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.1, groq_api_key=groq_api_key)


async def diagnostician_node(state: AgentState):
    """
    Node 1: Receives the raw CI logs, extracts the error trace,
    and asks the LLM to identify the root cause and which files need to be fixed.
    """
    print(f"--- [DIAGNOSTICIAN] Analyzing Logs for Run {state['run_id']} ---")

    # Shrink massive logs down to the actual error trace
    trimmed_logs = log_analyzer.extract_error_trace(state["raw_logs"])

    prompt = f"""
    You are an expert CI/CD DevOps Engineer. A build pipeline just failed.
    Here is the exact error trace:

    <error_trace>
    {trimmed_logs}
    </error_trace>

    Your job is to:
    1. Briefly summarize why the build failed (1-2 sentences).
    2. Identify the exact file paths within the repository that likely need to be modified to fix this bug.

    Return your response EXACTLY as a JSON object with two keys:
    {{
        "summary": "Short explanation of the error",
        "files": ["path/to/file1.py", "path/to/file2.js"]
    }}
    Return ONLY the JSON object. No extra text.
    """

    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        # Strip markdown code fences if the model wraps the JSON
        json_str = response.content.strip()
        if json_str.startswith("```"):
            json_str = json_str.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
        result_dict = json.loads(json_str.strip())
        summary = result_dict.get("summary", "Failed to parse summary")
        files_to_fetch = result_dict.get("files", [])
    except Exception as e:
        print(f"  -> JSON Parse error in Diagnostician: {e}")
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
    Node 2: Takes the files identified by the Diagnostician and fetches
    their actual raw content from the GitHub repository.
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
    Node 3: Takes the error summary and raw file contents, then writes a
    corrected version of each file to fix the bug.
    """
    print("--- [SOLVER] Drafting Code Patch ---")

    context = ""
    for path, code in state["file_contents"].items():
        context += f"\n\n--- START OF FILE: {path} ---\n{code}\n--- END OF FILE ---"

    critic_feedback = state.get("critic_feedback") or "N/A"

    prompt = f"""
    You are a Senior Software Engineer resolving a CI/CD build failure.

    Failure reason: {state['error_summary']}

    Here is the relevant source code:
    {context}

    Critic's previous feedback (if any): {critic_feedback}

    Write the corrected version of each file that fixes the issue.
    Wrap each file in a markdown code block with the file path on the first line as a comment. Example:

    ```python
    # path/to/filename.py
    def fixed_function():
        pass
    ```
    """

    response = llm.invoke([HumanMessage(content=prompt)])
    print("  -> Patch drafted.")
    return {"proposed_patch": response.content}


async def critic_node(state: AgentState):
    """
    Node 4: Reviews the Solver's proposed patch. Returns APPROVE or
    detailed feedback so the Solver can try again.
    """
    print("--- [CRITIC] Reviewing Solver's Patch ---")

    prompt = f"""
    You are a Staff Engineer doing a code review.
    A junior engineer proposed this fix for a CI/CD failure.

    Original Error: {state['error_summary']}

    Proposed Fix:
    {state['proposed_patch']}

    If the fix correctly resolves the error and has zero syntax issues, reply with exactly:
    APPROVE

    If it is wrong, introduces new bugs, or is incomplete, reply with specific feedback
    explaining what is wrong so the engineer can correct it. Do NOT just say REJECT.
    """

    response = llm.invoke([HumanMessage(content=prompt)])
    content = response.content.strip()

    if "APPROVE" in content:
        print("  -> Verdict: APPROVED ✅")
        return {"is_patch_approved": True, "critic_feedback": None}
    else:
        print(f"  -> Verdict: REJECTED ❌\n  -> Feedback: {content[:120]}...")
        return {"is_patch_approved": False, "critic_feedback": content}
