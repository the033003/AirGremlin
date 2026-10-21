# AirGremlin

**AirLLM-powered local AI agent with swappable Hugging Face models and REA MCP integration.**

AirGremlin is an experimental local AI agent built by adapting Gremlin to use AirLLM instead of an Ollama-based inference backend. It is designed to explore local inference with large language models, tool execution, and integration with REA (Reverse Engineering Agent) through the Model Context Protocol (MCP).

The goal is to build a flexible, locally operated agent that can switch between supported models and use external analysis tools without being tied to a single inference server.

**Project status:** Early development. AirLLM inference and the initial REA MCP connection have been demonstrated. End-to-end binary-analysis workflows, broad model compatibility, and complete REA compatibility are still being developed and tested.

## Features

- **Local inference:** Run supported Hugging Face models through AirLLM.
- **Swappable models:** Configure the model used by Gremlin without redesigning the agent around a single model.
- **GPU acceleration:** Uses PyTorch and CUDA when supported by the installed software stack and model.
- **Agent tools:** Retains Gremlin's existing agent and tool-execution architecture.
- **REA integration:** Connects to REA's MCP server and discovers available tools dynamically.
- **Selective tool exposure:** Starts with a focused REA tool catalog to reduce prompt overhead.
- **Linux-first development:** Initial setup targets Arch Linux and NVIDIA GPUs.

## Architecture

```
User
 |
 v
Gremlin agent
 |
 v
AirLLM backend
 |
 v
Hugging Face model
 |
 | structured tool calls
 v
Gremlin tool dispatcher
 |
 +----------------------+
 |                      |
 v                      v
Gremlin native tools    REA MCP bridge
                        |
                        v
                   REA MCP server
                        |
                        v
               Configured analysis providers
```

AirLLM provides model inference. Gremlin manages the agent loop and tool execution. The REA bridge connects the agent to REA's MCP interface.

These are separate components: successfully connecting to the MCP server does not mean every REA analysis provider is installed or configured.

## Requirements

The initial development environment uses:

- Arch Linux
- Python 3.11
- Node.js and npm
- NVIDIA GPU with a compatible driver and CUDA-enabled PyTorch installation
- Sufficient RAM, GPU memory, and storage for the selected model and its inference requirements
- A working REA installation or an accessible REA npm package
- Any analysis providers required by the REA tools you intend to use

The original development machine uses an NVIDIA GeForce RTX 4070 SUPER with 12 GB of VRAM. Larger models may run through layer-based or offloaded inference, but speed and practical model size depend on system RAM, storage throughput, model architecture, context length, and AirLLM support.

## Installation

### 1. Install system packages

On Arch Linux:

```bash
sudo pacman -S --needed git nodejs npm
```

Install Python 3.11 and a Python environment manager if they are not already available. The development setup uses `uv` to manage Python environments.

### 2. Clone the repository

```bash
git clone https://github.com/the033003/airgremlin.git
cd airgremlin
```

### 3. Create a Python environment

```bash
uv python install 3.11
uv venv --python 3.11 .venv-airllm
```

### 4. Install PyTorch

For the original CUDA 12.8 development setup:

```bash
uv pip install --python .venv-airllm/bin/python \
  torch torchvision \
  --index-url https://download.pytorch.org/whl/cu128
```

Use a PyTorch build compatible with your NVIDIA driver and target system. CUDA-enabled PyTorch wheels bundle their relevant CUDA runtime components; a separately installed CUDA toolkit is not necessarily required for inference.

### 5. Install Python dependencies

```bash
uv pip install --python .venv-airllm/bin/python \
  -r requirements-airllm.txt
```

Dependency versions may need adjustment as AirLLM, Transformers, PyTorch, and model architectures evolve. A pinned, tested dependency set will be provided as the project matures.

### 6. Install and verify REA

The REA CLI can be run through `npx`, avoiding the need for a global npm installation:

```bash
npx --yes rea-agents@6.7.0 --help
npx --yes rea-agents@6.7.0 mcp --help
```

AirGremlin's initial bridge launches REA as an MCP subprocess and discovers its advertised tools. The REA package version can be configured using the `REA_PACKAGE` environment variable.

## Running AirGremlin

From the repository directory:

```bash
./launch-airllm.sh
```

The launcher should initialize the configured AirLLM environment, set the Gremlin workspace and model, and start the agent.

The initial development model is:

```
Qwen/Qwen2.5-3B-Instruct
```

Use a model identifier supported by AirLLM and the installed Transformers version. Model changes may require different dependencies, architecture-specific handling, memory settings, or prompt templates.

Follow the launcher's existing configuration mechanism when selecting a different model. Model swapping is an intended project capability, but not every Hugging Face model is guaranteed to work.

## REA MCP integration

The initial implementation consists of:

- `rea_bridge.py` — starts the REA MCP process, discovers tools, and invokes selected tools.
- `airllm_backend.py` — provides AirLLM inference and adapts model tool-call output.
- `gremlin.py` — runs the Gremlin agent and dispatches tool calls.

By default, the bridge exposes a focused set of REA tools for opening binaries and examining available analysis documents, procedures, strings, and segments.

To expose all tools advertised by REA, set:

```bash
REA_MCP_TOOLS=all ./launch-airllm.sh
```

To use a custom comma-separated selection:

```bash
REA_MCP_TOOLS=list_documents,open_binary,procedure_info \
  ./launch-airllm.sh
```

Tool availability depends on the REA version, its active providers, and their configuration.

## Binary analysis

An REA binary-analysis request generally requires a target binary and a suitable configured provider.

For example, after starting Gremlin, request:

```
Use REA to open /usr/bin/ls for analysis.
Report the raw result from the open_binary tool.
```

Then request:

```
Use REA to list the available analysis documents and report the results.
```

These requests are intended to exercise the integration. Successful execution depends on the configured analysis environment; an MCP connection alone does not guarantee that a binary can be opened.

## Configuration

The following environment variables are used by the initial implementation:

| Variable          | Purpose                                      |
|-------------------|----------------------------------------------|
| `GREMLIN_WORKSPACE` | Gremlin workspace path                     |
| `GREMLIN_MODEL`     | Model selected by the launcher             |
| `REA_PACKAGE`       | REA npm package specifier; defaults to `rea-agents@6.7.0` |
| `REA_MCP_TOOLS`     | Optional REA tool selection, or `all`      |

Use a local `.env` or an untracked shell configuration for private settings. Do not commit credentials, access tokens, private MCP configuration, or machine-specific paths.

## Troubleshooting

### PyTorch cannot detect CUDA

```bash
.venv-airllm/bin/python -c \
  "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CUDA unavailable')"
```

Verify the NVIDIA driver and install a compatible CUDA-enabled PyTorch build if necessary.

### REA tools are not discovered

```bash
npx --yes rea-agents@6.7.0 mcp --help
```

Check that Node.js and npm are available, the package can run, and the Python environment contains the MCP SDK.

### REA reports that no application is open

Open a supported binary through the appropriate REA tool and ensure the relevant analysis provider is configured. This is a provider or target-state issue, not necessarily a model inference problem.

### The model prints tool schemas instead of calling tools

Check the model's native tool-call support, the chat template, prompt length, and Gremlin's tool-call parser. Small models may be less reliable at structured tool selection, especially when presented with many lengthy tool definitions.

### A model fails to load

Confirm that AirLLM supports the model architecture and that the installed Transformers version is compatible. Model swapping is not equivalent to universal architecture support.

## Development

Run Python syntax checks:

```bash
.venv-airllm/bin/python -m py_compile \
  gremlin.py airllm_backend.py rea_bridge.py
```

Test the REA MCP handshake independently:

```bash
.venv-airllm/bin/python test_rea_mcp.py
```

The second command requires the standalone `test_rea_mcp.py` development test to be present. It is not required for normal startup.

Contributions should preserve Gremlin's existing behavior while keeping model inference, agent orchestration, and MCP communication as independent components.

## Roadmap

- Demonstrate AirLLM inference on an NVIDIA GPU.
- Connect to REA through MCP.
- Discover REA's advertised tool catalog.
- Execute an initial REA tool call from Gremlin.
- Make structured tool calling reliable across supported models.
- Add automated integration tests for tool discovery, arguments, execution, and errors.
- Establish reproducible, pinned dependency versions.
- Improve model selection and model-specific inference configuration.
- Test larger models and document RAM, VRAM, and storage requirements.
- Validate end-to-end binary-analysis workflows across REA providers.
- Expand platform support and document provider-specific setup.
- Publish a stable release with a defined compatibility matrix.

## Upstream projects

AirGremlin builds on or integrates with the following projects:

- **Gremlin** — original agent project.
- **AirLLM** — layer-based large-model inference.
- **REA** — reverse engineering agent and MCP tools.
- **PyTorch** — tensor computation and GPU inference.
- **Hugging Face Transformers** — model and tokenizer interfaces.
- **Model Context Protocol** — tool-server communication protocol.
