import logging
import os
from flask import Flask, request, jsonify
from pydantic import BaseModel, ValidationError
from openai import OpenAI
import kubernetes
# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s %(levelname)s - %(message)s',
                    filename='agent.log', filemode='a')
logger = logging.getLogger(__name__)
# Initialize Flask and Kubernetes
app = Flask(__name__)
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
)
# Load Kubernetes configuration
try:
    kubernetes.config.load_kube_config()
except Exception as e:
    logger.error(f"Error loading Kubernetes config: {e}")
# Kubernetes API clients
core_v1_api = kubernetes.client.CoreV1Api()
apps_v1_api = kubernetes.client.AppsV1Api()
class QueryResponse(BaseModel):
    query: str
    answer: str
def execute_kubernetes_read_operations():
    try:
        # Collect various cluster resources
        namespaces = core_v1_api.list_namespace()
        nodes = core_v1_api.list_node()
        pods = core_v1_api.list_pod_for_all_namespaces()
        deployments = apps_v1_api.list_deployment_for_all_namespaces()
        
        # Prepare a structured summary of cluster resources
        cluster_info = {
            "total_namespaces": len(namespaces.items),
            "total_nodes": len(nodes.items),
            "total_pods": len(pods.items),
            "total_deployments": len(deployments.items),
            "pod_details": [
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "status": pod.status.phase
                } for pod in pods.items
            ],
            "node_details": [
                {
                    "name": node.metadata.name,
                    "status": node.status.phase if hasattr(node.status, 'phase') else 'Unknown'
                } for node in nodes.items
            ]
        }
        
        return cluster_info
    
    except Exception as e:
        logger.error(f"Error collecting cluster information: {e}")
        return {}
def generate_kubernetes_response(query, cluster_info):
    try:
        # Comprehensive system prompt
        system_prompt = """
        You are an expert Kubernetes cluster analyst. Your task is to accurately answer queries 
        about Kubernetes cluster resources based on the provided cluster information. 
        Follow these guidelines:
        
        1. Only use the information provided in the cluster_info
        2. Keep the answers very short and precise. Give only one-word answers wherever possible. No need to write full sentences.
        3. If the exact information is not available, like there aren't any pods in the mentioned namespace, then the answer is zero. Don't give full explanation.
        4. Focus on read-only information retrieval
        5. Prioritize direct, factual responses
        
        Available cluster information includes:
        - Total namespaces
        - Total nodes
        - Total pods
        - Total deployments
        - Detailed pod information (name, namespace, status)
        - Detailed node information (name, status)
        """
        
        # Prepare messages for OpenAI
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Cluster Information: {cluster_info}"},
            {"role": "user", "content": f"Query: {query}"}
        ]
        
        # Call OpenAI to generate response
        response = client.chat.completions.create(
            model='gpt-4',
            messages=messages,
            max_tokens=150
        )
        
        # Extract and return the answer
        return response.choices[0].message.content.strip()
    
    except Exception as e:
        logger.error(f"OpenAI response generation error: {e}")
        return "Unable to process query"
@app.route('/query', methods=['POST'])
def create_query():
    try:
        # Extract the question from the request data
        request_data = request.json
        query = request_data.get('query')
        
        logger.info(f"Received query: {query}")
        
        cluster_info = execute_kubernetes_read_operations()
        
        answer = generate_kubernetes_response(query, cluster_info)
        
        # Log the answer
        logger.info(f"Generated answer: {answer}")
        
        # Create the response model
        response = QueryResponse(query=query, answer=answer)
        
        return jsonify(response.dict())
    
    except ValidationError as e:
        return jsonify({"error": e.errors()}), 400
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({"error": "Internal server error"}), 500
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)