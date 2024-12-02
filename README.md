# cleric-submission

# Kubernetes Query and Analysis Service

## Overview

This project is a Flask-based web application designed to interact with a Kubernetes cluster, retrieve its resources, and provide detailed insights to users based on their queries. It combines the Kubernetes Python client for cluster operations with OpenAI's API to deliver intelligent and concise responses tailored to the cluster's current state.

## Key Features

1. **Kubernetes Integration**:
   - Retrieves real-time cluster information, including namespaces, nodes, pods, and deployments.
   - Provides detailed summaries of resource states, including pod and node statuses.

2. **OpenAI Integration**:
   - Leverages OpenAI's GPT model to interpret and respond to user queries about the Kubernetes cluster.
   - Ensures responses are precise, factual, and strictly based on the provided cluster information.

3. **Flask API**:
   - Offers a simple endpoint for receiving and processing user queries.
   - Handles requests and responses in a structured JSON format.

4. **Robust Error Handling**:
   - Logs errors and unexpected events to ensure system stability.
   - Captures issues with Kubernetes configuration, API calls, and OpenAI processing.

## Approach

### Step 1: Kubernetes Cluster Interaction
The application initializes the Kubernetes Python client to connect with a cluster using the default kubeconfig file. It performs the following read-only operations:
- Lists all namespaces, nodes, pods, and deployments in the cluster.
- Constructs a structured summary of the cluster's state for downstream processing.

### Step 2: Query Processing
User queries are handled in a multi-step process:
1. The query and cluster summary are passed to the OpenAI GPT model.
2. A carefully crafted system prompt ensures that the responses remain relevant and concise.
3. The GPT model generates an answer tailored to the query, based solely on the provided cluster data.

### Step 3: API Endpoint
A single API endpoint (`/query`) accepts POST requests with the following structure:
```
{
  "query": "How many namespaces are in the cluster?"
}
```

The endpoint:

- Extracts the query from the request.
- Fetches the current cluster state.
- Processes the query through OpenAI to generate a response.
- Returns the response in JSON format: 
```
{
  "query": "How many namespaces are in the cluster?",
  "answer": "5"
}
```

### Step 4: Logging
All operations are logged to `agent.log` for monitoring and debugging purposes. Logs include incoming queries, generated answers, and errors.


## Setup and Usage

### Prerequisites
- Python 3.x
- Kubernetes cluster with access to kubeconfig
- OpenAI API key

### Installation
1. Clone the Repository:
```
git clone <repository-url>
cd <repository-dir>
```

2. Install Dependencies:
```
pip install -r requirements.txt
```

3. Set Environment Variables: Configure the OpenAI API key:
```
export OPENAI_API_KEY='your_openai_api_key'
```

### Running the Application

Start the Flask application:
```
python main.py
```
The service will run on `http://127.0.0.1:8000`.

### API Usage
Send POST requests to the `/query` endpoint with your query in JSON format. 
For example:
```
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How many pods are running?"}'

```

## Logs
Operational logs are stored in `agent.log` for tracking queries, responses, and errors.