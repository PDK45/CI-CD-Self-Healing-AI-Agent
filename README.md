# 🤖 Opalite OS — Autonomous CI/CD Self-Healing Agent

An AI-powered SaaS platform that doesn't just notify you about bugs—it **heals** them. Opalite OS autonomously detects, diagnoses, and fixes failing CI/CD pipelines across multiple repositories. It features a cross-repository **Memory Crystal (RAG)** to learn from past fixes, **Multi-Repo Federation** via GitHub Auth, and **Emergency Rollbacks** to preserve production uptime.

> **AI Engine:** Groq · Llama 3.3-70B · Ultra-Low Latency

---

## 🎯 The Autonomous Healing Workflow

1.  **Detection:** A GitHub Webhook signals a failing build.
2.  **Memory Crystal (RAG):** The agent cross-references the error against its codebase-wide memory (ChromaDB-lite) to retrieve similar past fixes.
3.  **Diagnosis:** The *Diagnostician* analyzes truncated logs to find the root cause (Syntax, IaC, or Logic).
4.  **Sandbox Solve:** The *Solver* drafts a repair, which the *Verifier* tests in a secure sandbox.
5.  **Deployment:** Upon approval, the agent creates a branch, opens a PR, auto-merges, and triggers the deployment.
6.  **Fail-Safe:** If the live server crashes post-deploy, the **Emergency Rollback** instants reverts the Git tree to its last stable state.

---

## ✅ Project Status (Production Ready)

| Phase | Status |
|---|---|
| LangGraph Multi-Agent State Machine | ✅ Complete |
| RAG Memory Crystal (Cross-Repo Learning) | ✅ Complete |
| Multi-Repo GitHub Auth & Federation | ✅ Complete |
| Emergency Git Rollbacks (Zero Downtime) | ✅ Complete |
| Sandbox Verification & Integration Testing | ✅ Complete |
| SaaS Dashboard (Glassmorphic UI) | ✅ Complete |

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.x, FastAPI, Uvicorn |
| AI Model | Groq — Llama 3.3-70B (free) |
| AI Orchestration | LangChain, LangGraph |
| GitHub Integration | GitHub REST API (HTTPX) |
| Frontend | Tailwind CSS, Vanilla JS, Jinja2 |

---

## ⚙️ Setup & Run

### 1. Clone the repo
```bash
git clone https://github.com/PDK45/CI-CD-Self-Healing-AI-Agent.git
cd CI-CD-Self-Healing-AI-Agent/backend
```

### 2. Create virtual environment & install dependencies
```bash
python -m venv venv
.\venv\Scripts\Activate.ps1        # Windows
# source venv/bin/activate         # Mac/Linux
pip install -r requirements.txt
```

### 3. Configure environment variables
Create a `.env` file inside the `backend/` folder:
```env
GROQ_API_KEY=your_groq_api_key_here
GITHUB_TOKEN=your_github_personal_access_token_here
PORT=8000
```

Get your **free Groq API key** at: [console.groq.com](https://console.groq.com) (takes 30 seconds)

### 4. Run the server
```bash
python main.py
```

Open **[http://localhost:8000](http://localhost:8000)** — the dashboard will load with a live AI chat.

---

## 📁 Project Structure

```
backend/
├── main.py                    # FastAPI server — /chat (streaming) and /webhook endpoints
├── requirements.txt
├── .env                       # API keys (not committed)
├── templates/
│   └── index.html             # SaaS Dashboard UI
└── agent/
    ├── graph.py               # LangGraph state machine wiring
    ├── nodes.py               # AI agents: Diagnostician, Researcher, Solver, Critic
    ├── state.py               # Shared agent state schema
    ├── context_builder.py     # CI log parser — extracts exact error traces
    └── tools/
        └── github_service.py  # GitHub API: fetch logs, create branches, open PRs
```

---

## 🔗 Connect a Real GitHub Repository

1. Run the server with a public URL (e.g. via [ngrok](https://ngrok.com): `ngrok http 8000`)
2. Go to your GitHub repo → **Settings → Webhooks → Add webhook**
3. Set Payload URL to: `https://your-ngrok-url/webhook`
4. Content type: `application/json`
5. Select event: **Workflow runs**

When a CI build fails, the agent loop triggers automatically and opens a PR with the fix.
