# Kubernetes Query and Analysis Service

## Overview

This project is a Flask-based web application that provides a natural language interface to query Kubernetes cluster resources. It combines the Kubernetes Python client with OpenAI's GPT-4 model to interpret queries and provide concise, relevant information about the cluster's state.

## Architecture

The service follows a four-step process:

1. **Query Analysis**:
   - Uses GPT-4 to analyze the natural language query and select the most appropriate Kubernetes API endpoint
   - Maps queries to predefined K8s API endpoints like listing pods, services, deployments, etc.

2. **Kubernetes API Interaction**:
   - Makes calls to the Kubernetes API using the official Python client
   - Supports both in-cluster and local kubeconfig configurations
   - Handles various resource types including pods, services, deployments, PVs, PVCs, etc.

3. **Response Filtering**:
   - Filters API responses to include only relevant data
   - Implements resource-specific filtering (e.g., pods filtered to show name, namespace, and status)

4. **Response Processing**:
   - Uses GPT-4 to convert technical API responses into concise, user-friendly answers
   - Implements retry logic with exponential backoff for API rate limits
   - Provides brief, focused responses (1-2 words)

## Setup

### Prerequisites
- Python 3.x
- Access to a Kubernetes cluster (in-cluster or kubeconfig)
- OpenAI API key

### Installation
1. Clone the repository:
```bash
git clone <repository-url>
cd <repository-dir>
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
export OPENAI_API_KEY='your_openai_api_key'
```

### Running the Service
Start the Flask application:
```bash
python main.py
```
The service runs on `http://0.0.0.0:8000`

### API Usage
Send queries via POST requests to the `/query` endpoint:
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How many pods are running?"}'
```

Response format:
```json
{
  "query": "How many pods are running?",
  "answer": "<concise answer>"
}
```

## Logging
The service logs all operations to `agent.log`, including:
- Incoming queries
- Selected K8s endpoints
- Generated answers
- Errors and exceptions

## Error Handling
- Validates input queries
- Handles OpenAI rate limits with exponential backoff
- Manages Kubernetes API errors
- Returns appropriate HTTP status codes for different error scenarios

