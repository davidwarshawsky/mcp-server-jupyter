# SERVER REMEDIATION: Critical RCE Vulnerability

**Vulnerability:** P0 - Unsandboxed Agent Execution via `install_package` Tool

**Risk:** Remote Code Execution (RCE). The AI agent has a tool that allows it to execute `pip install` commands on behalf of the user. A malicious actor can use prompt injection to trick the agent into installing a compromised package, leading to a full compromise of the user's machine.

**Remediation Steps:**

1.  **Immediately remove the `install_package` tool** from the list of tools available to the AI agent. There is no safe way to expose this functionality to an LLM.

2.  **Update the agent's system prompt** to instruct it *not* to offer to install packages. If a user asks for a package to be installed, the agent should respond with a message explaining that it cannot do this and that the user should use the `!pip install <package-name>` command in a notebook cell.

3.  **Audit all other agent tools** for similar vulnerabilities. Any tool that executes shell commands, interacts with the filesystem, or makes network requests must be considered a potential security risk and should be hardened accordingly.

**Example of Unsafe Code (to be removed from the server):**

```python
# This is an example of what the vulnerable tool might look like.
# This ENTIRE tool must be removed.

@tool
def install_package(package_name: str):
    """Installs a Python package using pip."""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        return f"Successfully installed {package_name}."
    except subprocess.CalledProcessError as e:
        return f"Failed to install {package_name}: {e}"

# The agent should NOT have access to this tool.
agent = initialize_agent(
    tools=[install_package, ...],
    ...
)
```
