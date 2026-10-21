import asyncio
import json
import os
import threading
from concurrent.futures import TimeoutError as FutureTimeout

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REA_PACKAGE = os.environ.get("REA_PACKAGE", "rea-agents@6.7.0")

DEFAULT_TOOLS = {
    "binary_session",
    "open_binary",
    "list_documents",
    "list_procedures",
    "list_strings",
    "list_segments",
    "procedure_info",
    "procedure_assembly",
}

_loop = None
_session = None
_tools = {}
_ready = threading.Event()
_error = None
_lock = threading.Lock()


def _tool_definition(item):
    return {
        "type": "function",
        "function": {
            "name": "rea__" + item.name,
            "description": (item.description or "REA analysis tool")[:240],
            "parameters": item.inputSchema or {
                "type": "object",
                "properties": {},
            },
        },
    }


async def _serve():
    global _loop, _session, _tools, _error

    server = StdioServerParameters(
        command="npx",
        args=["--yes", REA_PACKAGE, "mcp"],
        env=os.environ.copy(),
    )

    try:
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                catalog = await session.list_tools()

                requested = os.environ.get("REA_MCP_TOOLS", "").strip()
                if requested.lower() == "all":
                    selected = {item.name for item in catalog.tools}
                elif requested:
                    selected = {name.strip() for name in requested.split(",") if name.strip()}
                else:
                    selected = DEFAULT_TOOLS

                _tools = {
                    "rea__" + item.name: item
                    for item in catalog.tools
                    if item.name in selected
                }
                _session = session
                _loop = asyncio.get_running_loop()
                _ready.set()

                print(
                    f"[REA] Connected to {REA_PACKAGE}; "
                    f"{len(catalog.tools)} discovered, "
                    f"{len(_tools)} enabled.",
                    flush=True,
                )

                await asyncio.Event().wait()
    except Exception as exc:
        _error = exc
        _ready.set()


def start():
    thread = threading.Thread(
        target=lambda: asyncio.run(_serve()),
        name="rea-mcp",
        daemon=True,
    )
    thread.start()

    if not _ready.wait(timeout=90):
        raise RuntimeError("Timed out starting the REA MCP server.")

    if _error:
        raise RuntimeError(f"Could not start REA MCP: {_error}") from _error

    return list_tools()


def list_tools():
    return [_tool_definition(item) for item in _tools.values()]


def is_rea_tool(name):
    return name in _tools


def call_tool(name, arguments, timeout=180):
    if name not in _tools:
        return f"ERROR: unknown REA tool: {name}"

    if not isinstance(arguments, dict):
        return "ERROR: REA tool arguments must be an object."

    future = asyncio.run_coroutine_threadsafe(
        _session.call_tool(_tools[name].name, arguments),
        _loop,
    )

    try:
        result = future.result(timeout=timeout)
    except FutureTimeout:
        future.cancel()
        return f"ERROR: REA tool {name} timed out."
    except Exception as exc:
        return f"ERROR calling REA tool {name}: {exc}"

    blocks = []
    for item in result.content or []:
        if getattr(item, "text", None) is not None:
            blocks.append(item.text)
        else:
            blocks.append(str(item))

    output = "\n".join(blocks)
    if getattr(result, "isError", False):
        return "REA tool error:\n" + output

    return output or json.dumps(
        {"result": "Tool completed without text output."}
    )


# Explicit initialization is called by Gremlin after its local
# tool definitions have been created.
