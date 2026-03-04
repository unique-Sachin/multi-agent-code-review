import os
import subprocess
import tempfile

from langchain_core.tools import tool


@tool
def run_bandit(code: str) -> str:
    """
    Run the Bandit static security scanner on the provided Python source code.
    Returns a plain-text report of any security issues found, including severity
    level, confidence, CWE ID, and line number for each finding.
    """
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            # -l = LOW severity and above  -i = LOW confidence and above
            # No --quiet so all findings are printed
            ["bandit", "-r", tmp_path, "-f", "txt", "-l", "-i"],
            capture_output=True,
            text=True,
        )
        # Bandit exits with code 1 when issues are found — that is not an error.
        output = result.stdout.strip()
        return output if output else "No security issues found by Bandit."
    except FileNotFoundError:
        return "ERROR: Bandit is not installed. Run `pip install bandit`."
    finally:
        os.unlink(tmp_path)
