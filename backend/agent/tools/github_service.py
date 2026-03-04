import os
import httpx
import tempfile
import zipfile
from pydantic import BaseModel

class GithubService:
    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN")
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self.token}" if self.token else ""
        }
        if not self.token:
            print("WARNING: GITHUB_TOKEN is not set. API calls will be severely rate-limited or fail.")

    async def get_failed_run_logs(self, repo_full_name: str, run_id: int) -> str:
        """
        Downloads and extracts the exact string logs for a failed GitHub action run.
        """
        # 1. Fetch the jobs for the run
        url = f"https://api.github.com/repos/{repo_full_name}/actions/runs/{run_id}/jobs"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            
            # Find the failed job
            failed_job = next((job for job in data.get("jobs", []) if job.get("conclusion") == "failure"), None)
            
            if not failed_job:
                return "No failed jobs found in this run."
                
            job_id = failed_job["id"]
            
            # 2. Download the logs for that specific job
            log_url = f"https://api.github.com/repos/{repo_full_name}/actions/jobs/{job_id}/logs"
            log_response = await client.get(log_url, headers=self.headers, follow_redirects=True)
            log_response.raise_for_status()
            
            return log_response.text

    async def get_file_content(self, repo_full_name: str, file_path: str, ref: str = "main") -> str:
        """
        Fetches the raw content of a specific file from the repository at a given commit/branch.
        """
        url = f"https://raw.githubusercontent.com/{repo_full_name}/{ref}/{file_path}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers={"Authorization": f"token {self.token}"} if self.token else {})
            if response.status_code == 200:
                return response.text
            else:
                return f"Failed to fetch file: HTTP {response.status_code}"

github_service = GithubService()
