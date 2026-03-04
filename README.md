# CI/CD Self-Healing AI Agent — Neoverse

An intelligent AI-powered SaaS platform that autonomously monitors and self-heals failing CI/CD pipelines using **Google Gemini**, **LangChain**, and **LangGraph**.

## 🚀 Features

- **Autonomous Pipeline Healing** — Monitors GitHub webhook events, analyzes failures, and auto-generates fixes
- **Multi-Agent AI Debate** — A LangGraph loop of Diagnostician → Researcher → Solver ↔ Critic agents
- **Live Gemini Chat** — Conversational AI interface for developers to query the agent directly
- **SaaS Dashboard** — Premium dark-mode UI showing pipeline statuses and agent thought processes
- **GitHub Integration** — Automatically creates branches and opens Pull Requests with AI-generated fixes

## 🏗️ Architecture

```
GitHub Webhook (failure)
        ↓
  Diagnostician  →  Identifies root cause from CI logs
        ↓
   Researcher    →  Fetches failing source files via GitHub API
        ↓
    Solver       →  Generates a code patch (diff)
        ↓
    Critic       →  Reviews the patch for quality/security
        ↓
  [APPROVE] ──→  Creates Branch → Opens PR on GitHub
  [REJECT]  ──→  Back to Solver (max 3 loops)
```

## 🛠️ Tech Stack

- **Backend**: Python, FastAPI, Uvicorn
- **AI**: Google Gemini 2.0 Flash via LangChain
- **Orchestration**: LangGraph (multi-agent state machine)
- **Frontend**: Tailwind CSS, Vanilla JS (served via Jinja2)
- **GitHub API**: HTTPX

## ⚙️ Setup

### 1. Install dependencies
```bash
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt
```

### 2. Configure environment
Create a `.env` file in the `backend/` directory:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GITHUB_TOKEN=your_github_personal_access_token_here
PORT=8000
```

Get your free **Gemini API key** from: [aistudio.google.com](https://aistudio.google.com)

### 3. Run the server
```bash
python main.py
```

Open **[http://localhost:8000](http://localhost:8000)** in your browser.

## 📁 Project Structure

```
backend/
├── main.py                    # FastAPI server, /chat and /webhook endpoints
├── requirements.txt           # Python dependencies
├── .env                       # API keys (not committed to git)
├── templates/
│   └── index.html             # SaaS Dashboard UI
└── agent/
    ├── graph.py               # LangGraph state machine wiring
    ├── nodes.py               # AI agent nodes (Diagnostician, Solver, Critic)
    ├── state.py               # Shared state schema
    ├── context_builder.py     # Log parser — extracts error traces
    └── tools/
        └── github_service.py  # GitHub API wrapper
```

## 🔗 GitHub Webhook Setup

To connect a real repository:
1. Go to your GitHub repo → **Settings** → **Webhooks** → **Add webhook**
2. Set Payload URL to: `https://your-server-url/webhook`
3. Content type: `application/json`
4. Events: Select **Workflow runs**
