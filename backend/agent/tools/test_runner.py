import os
import shutil
import tempfile
import asyncio
import subprocess
from typing import Tuple, Dict

async def extract_files_from_patch(patch: str) -> Dict[str, str]:
    """
    Parses the markdown code blocks from the Solver's patch to extract file paths and contents.
    Expects format:
    ```python
    # path/to/file.py
    def code()...
    ```
    """
    files_to_write = {}
    lines = patch.split('\n')
    
    in_block = False
    current_file = None
    current_content = []
    
    for line in lines:
        if line.strip().startswith('```'):
            if not in_block:
                in_block = True
                current_file = None
                current_content = []
            else:
                in_block = False
                if current_file:
                    files_to_write[current_file] = '\n'.join(current_content)
        elif in_block:
            # First line of the block might be the path
            if current_file is None and line.strip().startswith('#'):
                current_file = line.strip().lstrip('#').strip()
            elif current_file is not None:
                current_content.append(line)
                
    return files_to_write

async def run_integration_tests(repo: str, commit_sha: str, files_to_write: Dict[str, str]) -> Tuple[bool, str]:
    """
    Clones the repository locally in a temp directory, applies the dict of file changes,
    and runs pytest. Returns (is_success, test_output).
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return False, "Error: GITHUB_TOKEN not found for cloning."
        
    clone_url = f"https://{token}@github.com/{repo}.git"
    test_dir = tempfile.mkdtemp(prefix="opalite_sandbox_")
    
    try:
        print(f"  [Sandbox] Cloning {repo} into {test_dir}...")
        
        # 1. Clone the repo
        def run_cmd(cmd: str, cwd: str):
            return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)

        res = await asyncio.to_thread(run_cmd, f"git clone {clone_url} .", test_dir)
        if res.returncode != 0:
            return False, f"Git clone failed:\n{res.stderr}"

        # 2. Checkout the broken commit
        res = await asyncio.to_thread(run_cmd, f"git checkout {commit_sha}", test_dir)
        if res.returncode != 0:
            return False, f"Git checkout failed:\n{res.stderr}"
        
        # 3. Apply the patch
        if not files_to_write:
            return False, "Error: Could not extract any valid files from the proposed patch."
            
        for filepath, content in files_to_write.items():
            full_path = os.path.join(test_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"  [Sandbox] Overwrote {filepath} with proposed fix.")
            
        # 4. Run tests (e.g., pytest)
        print("  [Sandbox] Executing local tests (pytest)...")
        # Ensure we run tests in an isolated way if needed.
        # We will assume a simple `pytest` command is sufficient for python repos.
        res = await asyncio.to_thread(run_cmd, "pytest", test_dir)
        
        output = res.stdout + "\n" + res.stderr
        is_success = res.returncode == 0
        
        if is_success:
            print("  [Sandbox] Tests PASSED!")
        else:
            print("  [Sandbox] Tests FAILED!")
            
        return is_success, output
        
    finally:
        # Cleanup temp directory
        shutil.rmtree(test_dir, ignore_errors=True)
