import logging
import os
from typing import Optional, Dict, Any
from flask import Flask, request, jsonify
from pydantic import BaseModel, ValidationError
from openai import OpenAI
from dotenv import load_dotenv
from kubernetes import client, config
import json
import random
import time
import openai

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s %(levelname)s - %(message)s',
                    filename='agent.log', filemode='a')

# Initialize Flask app
app = Flask(__name__)

# Initialize OpenAI client
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Initialize Kubernetes client
try:
    config.load_incluster_config()  # Try to load in-cluster config
except config.ConfigException:
    home = os.path.expanduser("~")
    kubeconfig = os.path.join(home, '.kube', 'config')
    config.load_kube_config(config_file=kubeconfig)  # Explicitly specify kubeconfig path

# Create API clients
v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
custom_objects = client.CustomObjectsApi()

# Define available Kubernetes API endpoints
K8S_ENDPOINTS = {
    "list_node": "Get information about all nodes",
    "list_namespace": "Get all namespaces",
    "list_pod_for_all_namespaces": "Get all pods across namespaces",
    "list_service_for_all_namespaces": "Get all services",
    "list_deployment_for_all_namespaces": "Get all deployments",
    "list_persistent_volume": "Get all persistent volumes",
    "list_persistent_volume_claim_for_all_namespaces": "Get all PVCs",
    "list_config_map_for_all_namespaces": "Get all config maps",
    "list_secret_for_all_namespaces": "Get all secrets",
    "list_service_account_for_all_namespaces": "Get all service accounts",
    "list_endpoints_for_all_namespaces": "Get all endpoints",
}

class QueryResponse(BaseModel):
    query: str
    answer: str

def get_appropriate_endpoint(query: str) -> str:
    """Get the appropriate K8s API endpoint for the query"""
    try:
        system_prompt = """You are a Kubernetes API expert. Given a user query and available API endpoints, 
        select the most appropriate endpoint. Only return the exact endpoint name without any explanation. 
        If no endpoint fits, respond with "not_available"."""

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Available endpoints:\n{json.dumps(K8S_ENDPOINTS, indent=2)}\n\nQuery: {query}"}
            ],
            temperature=0,
            max_tokens=50
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Error getting appropriate endpoint: {str(e)}")
        raise

def call_k8s_api(endpoint: str) -> Dict[str, Any]:
    """Call Kubernetes API endpoint"""
    try:
        # Get the appropriate API client
        if endpoint.startswith("list_deployment"):
            api_client = apps_v1
        else:
            api_client = v1

        # Call the endpoint
        api_func = getattr(api_client, endpoint)
        response = api_func()
        
        # Convert response to dict
        return client.ApiClient().sanitize_for_serialization(response)
    except Exception as e:
        logging.error(f"Error calling K8s API: {str(e)}")
        raise

def filter_api_response(endpoint: str, response: Dict[str, Any], query: str) -> Dict[str, Any]:
    """Filter the API response to include only relevant data"""
    try:
        if endpoint == "list_pod_for_all_namespaces":
            # For pod queries, only include pod name, namespace, and status
            filtered_items = []
            for item in response.get("items", []):
                if "metadata" in item and "status" in item:
                    filtered_items.append({
                        "name": item["metadata"].get("name", ""),
                        "namespace": item["metadata"].get("namespace", ""),
                        "status": item["status"].get("phase", "")
                    })
            return {"items": filtered_items}
        
        # Add more endpoint-specific filters as needed
        return response
    except Exception as e:
        logging.error(f"Error filtering API response: {str(e)}")
        return response

def process_response(query: str, endpoint: str, api_response: Dict[str, Any]) -> str:
    """Process API response using GPT-4"""
    try:
        # Filter the response before sending to GPT-4
        filtered_response = filter_api_response(endpoint, api_response, query)
        
        system_prompt = """You are a Kubernetes cluster assistant. Format the API response into a clear, 
        concise answer to the user's query. Keep answers factual and to the point. Only give the required answer in 1 or 2 words.
        Don't use sentence structure.
        No need to write explanatory response. If the information is not available, respond with "Not available"."""

        # Implement exponential backoff for retries
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Query: {query}\nEndpoint: {endpoint}\nResponse: {json.dumps(filtered_response)}"}
                    ],
                    temperature=0,
                    max_tokens=50  # Reduced from 150 to 50
                )
                return response.choices[0].message.content.strip()
            except openai.RateLimitError as e:
                if attempt == max_retries - 1:
                    raise
                delay = (base_delay * 2 ** attempt) + random.uniform(0, 1)
                logging.info(f"Rate limit hit, retrying in {delay} seconds...")
                time.sleep(delay)
            except Exception as e:
                raise
                
    except Exception as e:
        logging.error(f"Error processing response: {str(e)}")
        raise

@app.route('/query', methods=['POST'])
def create_query():
    """Process a query about the cluster"""
    try:
        request_data = request.json
        query = request_data.get('query')
        
        if not query:
            return jsonify({"error": "Query is required"}), 400

        logging.info(f"Received query: {query}")
        
        endpoint = get_appropriate_endpoint(query)
        if endpoint == "not_available":
            return jsonify({"error": "No appropriate API endpoint found for this query"}), 400
            
        logging.info(f"Selected endpoint: {endpoint}")
        
        try:
            api_response = call_k8s_api(endpoint)
            answer = process_response(query, endpoint, api_response)

            # Log the answer
            logging.info(f"Generated answer: {answer}")
            
            response = QueryResponse(
                query=query,
                answer=answer
            )
            return jsonify(response.dict())
        except openai.RateLimitError as e:
            logging.error(f"OpenAI rate limit exceeded: {str(e)}")
            return jsonify({"error": "Service temporarily unavailable due to rate limiting. Please try again later."}), 429
        except Exception as e:
            logging.error(f"Error processing query: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    # except Exception as e:
    #     logging.error(f"Unexpected error: {str(e)}")
    #     return jsonify({"error": str(e)}), 500
    except ValidationError as e:
        return jsonify({"error": e.errors()}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
