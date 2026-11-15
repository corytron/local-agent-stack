title: Introduction

# Introduction

## Overview

This document describes the software and procedures required to deploy the stack.

- A single TrueNAS SCALE server with one NVIDIA GPU
- A Linux workstation running the coding agent

!!! note
    Many PDF viewers add a line break to the end of each line of text in a PDF.

    To address this, do one of the following:

    - Paste into a text editor.
    - Use the HTML version.

## Terminology

Table: Terminology

| Term | Definition |
|---|---|
| GGUF | A file format for quantized model weights used by llama.cpp. |
| MCP | Model Context Protocol. |

### Run the deployment script

#### Prerequisites

Ensure that the GPU is visible:

```
sudo nvidia-smi
```

#### Steps

1. Open **Apps** > **Configuration**.

    !!! caution
        This parameter should never be set to **true** for this release.

2. Click **Save**.

!!! warning
    It is critical that you keep the key.
