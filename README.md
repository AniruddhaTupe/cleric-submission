# Kubernetes Query Agent

## Overview

The Kubernetes Query Agent is an intelligent, AI-powered tool designed to provide comprehensive insights into your Kubernetes cluster. By leveraging the power of OpenAI's GPT-4 and the Kubernetes Python client, this agent collects detailed cluster information and generates precise, context-aware responses to user queries.

## Key Features

- **Comprehensive Cluster Scanning**: 
  - Automatically collects detailed information across all namespaces
  - Captures rich metadata about pods, deployments, services, and secrets
  - Provides a 360-degree view of your Kubernetes cluster

- **AI-Powered Querying**:
  - Uses OpenAI's GPT-4 to interpret complex queries
  - Generates accurate, context-based responses
  - Handles a wide range of cluster-related questions

- **Flexible and Adaptable**:
  - Works across different cluster configurations
  - No hard-coded assumptions about service names or structures
  - Easily extensible for various Kubernetes environments

## How It Works

1. **Information Collection**
   - Scans entire Kubernetes cluster using the Kubernetes Python client
   - Gathers comprehensive information about:
     * Namespaces
     * Pods (status, containers, ports, environment variables)
     * Deployments
     * Services
     * Secrets

2. **AI-Powered Query Processing**
   - Sends complete cluster context to OpenAI's GPT-4
   - AI interprets the context and user query
   - Generates precise, contextually relevant answers

## Prerequisites

- Python 3.10+
- Kubernetes cluster
- OpenAI API Key
- Kubernetes configuration file (`~/.kube/config`)

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/kubernetes-query-agent.git
   cd kubernetes-query-agent
   ```

2. Create and activate a virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up OpenAI API Key:
   ```bash
   export OPENAI_API_KEY=your_openai_api_key
   ```

## Usage

Start the Flask server:
```bash
python main.py
```

Send queries via POST request to `http://localhost:8000/query`:

### Example Query
```bash
curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{"query": "How many pods are in the default namespace?"}'
```

### Supported Query Types
- Namespace information
- Pod counts and details
- Deployment status
- Service configurations
- Secret information
- Resource-specific queries

## Logging

All queries and interactions are logged in `agent.log` for debugging and tracking purposes.