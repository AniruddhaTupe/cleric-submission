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
        services = core_v1_api.list_service_for_all_namespaces()
        secrets = core_v1_api.list_secret_for_all_namespaces()
        pvcs = core_v1_api.list_persistent_volume_claim_for_all_namespaces()
        
        # Add namespace-specific pod counts
        namespace_pod_counts = {}
        for pod in pods.items:
            namespace = pod.metadata.namespace
            if namespace not in namespace_pod_counts:
                namespace_pod_counts[namespace] = 0
            namespace_pod_counts[namespace] = namespace_pod_counts.get(namespace, 0) + 1
        
        # Add debug logging
        logger.debug("Pod counts per namespace:")
        for namespace, count in namespace_pod_counts.items():
            logger.debug(f"{namespace}: {count}")
        
        # Prepare a comprehensive cluster information dictionary
        cluster_info = {
            "total_namespaces": len(namespaces.items),
            "total_nodes": len(nodes.items),
            "total_pods": len(pods.items),
            "total_deployments": len(deployments.items),
            "namespace_pod_counts": namespace_pod_counts,
            
            # Add node information
            "nodes": [
                {
                    "name": node.metadata.name,
                    "status": node.status.conditions[-1].type if node.status.conditions else "Unknown",
                    "roles": [
                        label.replace("node-role.kubernetes.io/", "")
                        for label in node.metadata.labels
                        if label.startswith("node-role.kubernetes.io/")
                    ],
                    "kubelet_version": node.status.node_info.kubelet_version if hasattr(node.status, 'node_info') else "Unknown"
                } for node in nodes.items
            ],
            
            # Update pod information to include creation timestamps
            "pods": [
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "status": pod.status.phase,
                    "creation_timestamp": pod.metadata.creation_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ") if pod.metadata.creation_timestamp else None,
                    "containers": [
                        {
                            "name": container.name,
                            "image": container.image,
                            "restart_count": next(
                                (status.restart_count 
                                 for status in (pod.status.container_statuses or [])
                                 if status.name == container.name),
                                0
                            )
                        } for container in pod.spec.containers
                    ]
                } for pod in pods.items
            ]
        }
        
        # Add namespace-specific restart counts
        namespace_restart_counts = {}
        for pod in pods.items:
            namespace = pod.metadata.namespace
            if namespace not in namespace_restart_counts:
                namespace_restart_counts[namespace] = 0
            for container_status in (pod.status.container_statuses or []):
                namespace_restart_counts[namespace] += container_status.restart_count

        cluster_info["namespace_restart_counts"] = namespace_restart_counts
        
        # Add namespace-specific pod creation times
        namespace_pod_creation_times = {}
        for pod in pods.items:
            namespace = pod.metadata.namespace
            if namespace not in namespace_pod_creation_times:
                namespace_pod_creation_times[namespace] = []
            if pod.metadata.creation_timestamp:
                namespace_pod_creation_times[namespace].append(
                    pod.metadata.creation_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
                )
        
        cluster_info["namespace_pod_creation_times"] = namespace_pod_creation_times
        
        # Add debug logging for final cluster_info
        logger.debug(f"Cluster info: {cluster_info}")
        
        return cluster_info
    
    except Exception as e:
        logger.error(f"Error collecting cluster information: {e}")
        return {
            "namespace_pod_counts": namespace_pod_counts,
            "total_pods": len(pods.items) if pods else 0,
            "nodes": [{"name": node.metadata.name} for node in nodes.items] if nodes else [],
            "namespace_restart_counts": namespace_restart_counts if 'namespace_restart_counts' in locals() else {},
            "namespace_pod_creation_times": namespace_pod_creation_times if 'namespace_pod_creation_times' in locals() else {}
        }

def generate_kubernetes_response(query, cluster_info):
    try:
        # Add debug logging
        logger.debug(f"Generating response for query: {query}")
        logger.debug(f"Using cluster info: {cluster_info}")
        
        # Comprehensive system prompt
        system_prompt = """
        You are an expert Kubernetes cluster analyst. Your task is to accurately answer queries 
        about Kubernetes cluster resources based on the provided cluster information. 
        Follow these guidelines:
        
        1. Only use the information provided in the cluster_info
        2. Keep the answers very short and precise. Give only one-word answers wherever possible.
        3. If the exact information is not available, return "Not found" or "0" as appropriate
        4. Focus on read-only information retrieval
        5. Prioritize direct, factual responses
        6. When listing single items, return just the name without brackets or quotes
        7. Only use list format when there are multiple items to display
        8. Return numbers directly without any prefix or labels
        9. Do not include words like "Answer:" or similar prefixes in your response
        
        Available cluster information includes:
        - Total resource counts (namespaces, nodes, pods, deployments)
        - Pod counts per namespace
        - Node information including names, status, and roles
        - Detailed pod information including:
          * Container details (ports, environment variables, volume mounts)
          * Container restart counts per namespace
          * Pod creation timestamps
          * Readiness probes
          * Volume configurations
        - Service details (ports, selectors, types)
        - Secret information
        - Persistent Volume Claims
        
        For questions about pod creation times, use the namespace_pod_creation_times field.
        For the production namespace, list all creation timestamps.
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