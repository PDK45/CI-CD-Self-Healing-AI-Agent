import os
import sys
import shutil
import tempfile
import asyncio
import traceback
from typing import Tuple, Dict


async def extract_files_from_patch(patch: str) -> Dict[str, str]:
    """
    Parses markdown code blocks from the Solver's patch to extract file paths and contents.
    Handles multiple comment styles and fence formats.
    """
    files_to_write = {}
    if not patch:
        return files_to_write

    lines = patch.split('\n')
    in_block = False
    current_file = None
    current_content = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            if not in_block:
                in_block = True
                current_file = None
                current_content = []
                # Format: ```python:path/to/file.py  OR  ```python path/to/file.py
                if len(stripped) > 3:
                    rest = stripped[3:]
                    if ':' in rest:
                        parts = rest.split(':', 1)
                        candidate = parts[1].strip()
                        if candidate and '.' in candidate and ' ' not in candidate:
                            current_file = candidate
                    elif ' ' in rest:
                        parts = rest.split(' ', 1)
                        candidate = parts[1].strip()
                        if candidate and '.' in candidate:
                            current_file = candidate
            else:
                in_block = False
                if current_file and current_file.strip():
                    content_lines = current_content[:]
                    if content_lines and current_file.strip() in content_lines[0].strip():
                        content_lines = content_lines[1:]
                    files_to_write[current_file.strip()] = '\n'.join(content_lines)
        elif in_block:
            if current_file is None and (stripped.startswith('#') or stripped.startswith('//')):
                potential_file = stripped.lstrip('#/').strip()
                if potential_file and '.' in potential_file and ' ' not in potential_file:
                    current_file = potential_file
                    continue
            current_content.append(line)

    return files_to_write


async def run_integration_tests(repo: str, commit_sha: str, files_to_write: Dict[str, str]) -> Tuple[bool, str]:
    """
    Clones the repository into a temp sandbox, applies the proposed patch,
    installs dependencies, and runs pytest.
    Returns (is_success, detailed_output).

    Windows-compatible: uses only ASCII in print/log statements.
    Uses sys.executable so the correct Python is always used.
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return False, "ERROR: GITHUB_TOKEN not set in .env -- cannot clone repo."

    auth_clone_url = f"https://x-access-token:{token}@github.com/{repo}.git"
    test_dir = tempfile.mkdtemp(prefix="opalite_sandbox_")
    steps_log = []

    def log(msg: str):
        # ASCII-only safe logging -- no emojis that break Windows cp1252
        safe_msg = msg.encode('ascii', errors='replace').decode('ascii')
        steps_log.append(safe_msg)
        try:
            print(f"  [Sandbox] {safe_msg}")
        except Exception:
            pass  # silently ignore any remaining encoding issues

    try:
        log(f"Sandbox created at: {test_dir}")

        async def run_proc(cmd: list, cwd: str, timeout: int = 120):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return proc.returncode, stdout.decode(errors='replace'), stderr.decode(errors='replace')
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return -1, "", f"Timed out after {timeout}s"

        # STEP 1: Clone
        log(f"Cloning {repo} ...")
        retcode, stdout, stderr = await run_proc(
            ["git", "clone", "--depth=1", auth_clone_url, "."],
            test_dir,
            timeout=90
        )
        safe_err = stderr.replace(token, "***TOKEN***")
        if retcode != 0:
            log(f"Git clone FAILED (exit {retcode})")
            return False, (
                f"## Git Clone Failed\n\n"
                f"```\n{safe_err[:1500]}\n```\n\n"
                f"**Tip:** Confirm your GITHUB_TOKEN has `repo` read scope and that `{repo}` exists."
            )
        log("Clone OK")

        # STEP 2: Checkout target commit
        checkout_target = commit_sha if (commit_sha and len(commit_sha) > 7 and commit_sha != "main") else "HEAD"
        if checkout_target != "HEAD":
            log(f"Checking out {checkout_target[:8]} ...")
            retcode, _, _ = await run_proc(["git", "checkout", checkout_target], test_dir)
            if retcode != 0:
                log("Checkout failed -- staying on default branch")

        # STEP 3: Apply patch files
        if not files_to_write:
            log("No patch files provided -- verifying repo as-is")
        else:
            log(f"Applying patch: {len(files_to_write)} file(s)")
            for filepath, content in files_to_write.items():
                if not filepath or not filepath.strip():
                    continue
                clean_path = filepath.strip().replace('\\', '/')
                if clean_path.startswith('/'):
                    clean_path = clean_path[1:]
                full_path = os.path.normpath(os.path.join(test_dir, clean_path))
                if not full_path.startswith(os.path.normpath(test_dir)):
                    log(f"BLOCKED path traversal: {clean_path}")
                    continue
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                log(f"  Wrote: {clean_path}")

        # STEP 4: Install dependencies
        req_file = os.path.join(test_dir, "requirements.txt")
        if os.path.exists(req_file):
            log("Installing requirements.txt ...")
            retcode, _, stderr = await run_proc(
                [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
                test_dir,
                timeout=120
            )
            if retcode != 0:
                log(f"Dependency install had issues (non-fatal): {stderr[:200]}")
            else:
                log("Dependencies installed OK")
        else:
            log("No requirements.txt -- skipping install")

        # STEP 5: Find test files
        test_files = []
        for root, dirs, files in os.walk(test_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            for fname in files:
                if fname.startswith('test_') or fname.endswith('_test.py'):
                    test_files.append(os.path.join(root, fname))

        if not test_files:
            log("No test files found -- treating as PASS (no tests to fail)")
            patch_summary = "\n".join([f"- `{k}`" for k in files_to_write.keys()]) or "*(no files modified)*"
            return True, (
                f"## Sandbox Passed (No Tests Found)\n\n"
                f"No `test_*.py` files exist in this repo.\n"
                f"The patch was applied cleanly to:\n\n"
                f"{patch_summary}\n\n"
                f"> Add `test_*.py` files to enable automated test verification."
            )

        # STEP 6: Run pytest
        log(f"Running pytest on {len(test_files)} test file(s) ...")
        retcode, stdout, stderr = await run_proc(
            [sys.executable, "-m", "pytest", "-v", "--tb=short", "--no-header"],
            test_dir,
            timeout=120
        )

        combined = f"{stdout}\n{stderr}".strip()
        is_success = (retcode == 0)
        result_label = "PASSED" if is_success else "FAILED"
        log(f"pytest result: {result_label} (exit {retcode})")

        step_log_str = "\n".join(steps_log)
        return is_success, (
            f"## Sandbox {result_label}\n\n"
            f"### Execution Steps\n"
            f"```\n{step_log_str}\n```\n\n"
            f"### pytest Output\n"
            f"```\n{combined[:3000]}\n```"
        )

    except Exception as e:
        err_str = f"{str(e)}\n{traceback.format_exc()}"
        try:
            log(f"Exception: {str(e)}")
        except Exception:
            pass
        return False, (
            f"## Sandbox Exception\n\n"
            f"```\n{err_str[:2000]}\n```"
        )

    finally:
        try:
            log("Cleaning up sandbox ...")
        except Exception:
            pass
        shutil.rmtree(test_dir, ignore_errors=True)
