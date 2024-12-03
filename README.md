# cleric-submission

# Kubernetes Query and Analysis Service

## Overview

This project is a Flask-based web application designed to interact with a Kubernetes cluster, retrieve its resources, and provide detailed insights to users based on their queries. It combines the Kubernetes Python client for cluster operations with OpenAI's API to deliver intelligent and concise responses tailored to the cluster's current state.

## Approach

This is a natural language interface for Kubernetes cluster management that follows a three-step process:

1. **Query Translation**:
   - Translates natural language queries into kubectl commands.
   - Executes the command and retrieves the output.

2. **Command Execution**:
   - Executes the kubectl command and retrieves the output.

3. **Response Formatting**:
   - Formats the kubectl output into a concise, user-friendly response using GPT-4.

4. **Robust Error Handling**:
   - Logs errors and unexpected events to ensure system stability.
   - Captures issues with Kubernetes configuration, API calls, and OpenAI processing.


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

