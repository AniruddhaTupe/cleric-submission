import os
import json
import logging
from flask import Flask, request, jsonify
from pydantic import BaseModel, ValidationError
from kubernetes import client, config
from openai import OpenAI

# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s %(levelname)s - %(message)s',
                    filename='agent.log', filemode='a')

app = Flask(__name__)

class QueryResponse(BaseModel):
    query: str
    answer: str

class KubernetesQueryAgent:
    def __init__(self):
        # Load Kubernetes configuration
        try:
            config.load_kube_config()
        except Exception as e:
            logging.error(f"Error loading Kubernetes config: {e}")
            raise

        # Initialize Kubernetes API clients
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.networking_v1 = client.NetworkingV1Api()

        # Initialize OpenAI client
        self.openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

        # Collect and store comprehensive cluster information
        self.cluster_context = self.collect_comprehensive_information()
        logging.info(f"Cluster Context: {self.cluster_context}")

    def collect_comprehensive_information(self):
        """
        Collect comprehensive information about the Kubernetes cluster
        """
        cluster_info = {
            'namespaces': [],
            'total_pod_count': 0,
            'deployments': [],
            'services': [],
            'secrets': [],
            'pods': []
        }

        try:
            # Collect Namespaces
            namespaces = self.core_v1.list_namespace()
            cluster_info['namespaces'] = [
                {
                    'name': ns.metadata.name,
                    'labels': ns.metadata.labels or {}
                } for ns in namespaces.items
            ]

            # Collect Pods
            all_pods = self.core_v1.list_pod_for_all_namespaces()
            cluster_info['total_pod_count'] = len(all_pods.items)
            cluster_info['pods'] = [
                {
                    'name': pod.metadata.name,
                    'namespace': pod.metadata.namespace,
                    'status': pod.status.phase,
                    'containers': [
                        {
                            'name': container.name,
                            'image': container.image,
                            'ports': [
                                {
                                    'container_port': port.container_port,
                                    'protocol': port.protocol
                                } for port in container.ports
                            ] if container.ports else [],
                            'env': [
                                {
                                    'name': env.name,
                                    'value': env.value
                                } for env in container.env
                            ] if container.env else [],
                            'readiness_probe': {
                                'path': container.readiness_probe.http_get.path if 
                                        container.readiness_probe and 
                                        container.readiness_probe.http_get else None
                            }
                        } for container in pod.spec.containers
                    ]
                } for pod in all_pods.items
            ]

            # Collect Deployments
            for namespace in [ns['name'] for ns in cluster_info['namespaces']]:
                try:
                    deployments = self.apps_v1.list_namespaced_deployment(namespace)
                    cluster_info['deployments'].extend([
                        {
                            'name': dep.metadata.name,
                            'namespace': dep.metadata.namespace,
                            'replicas': {
                                'desired': dep.spec.replicas,
                                'available': dep.status.available_replicas
                            },
                            'volumes': [
                                {
                                    'name': vol.name,
                                    'type': 'persistent_volume_claim' if vol.persistent_volume_claim else 'other'
                                } for vol in dep.spec.template.spec.volumes
                            ] if dep.spec.template.spec.volumes else []
                        } for dep in deployments.items
                    ])
                except Exception as dep_err:
                    logging.warning(f"Error collecting deployments in namespace {namespace}: {dep_err}")

            # Collect Services
            for namespace in [ns['name'] for ns in cluster_info['namespaces']]:
                try:
                    services = self.core_v1.list_namespaced_service(namespace)
                    cluster_info['services'].extend([
                        {
                            'name': svc.metadata.name,
                            'namespace': svc.metadata.namespace,
                            'ports': [
                                {
                                    'port': port.port,
                                    'target_port': port.target_port,
                                    'protocol': port.protocol
                                } for port in svc.spec.ports
                            ] if svc.spec.ports else []
                        } for svc in services.items
                    ])
                except Exception as svc_err:
                    logging.warning(f"Error collecting services in namespace {namespace}: {svc_err}")

            # Collect Secrets
            for namespace in [ns['name'] for ns in cluster_info['namespaces']]:
                try:
                    secrets = self.core_v1.list_namespaced_secret(namespace)
                    cluster_info['secrets'].extend([
                        {
                            'name': secret.metadata.name,
                            'namespace': secret.metadata.namespace,
                            'type': secret.type
                        } for secret in secrets.items
                    ])
                except Exception as secret_err:
                    logging.warning(f"Error collecting secrets in namespace {namespace}: {secret_err}")

            return cluster_info

        except Exception as e:
            logging.error(f"Error collecting cluster information: {e}")
            return cluster_info

    def query_openai(self, query):
        """
        Send query to OpenAI with cluster context
        """
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system", 
                        "content": """
                                    You are a Kubernetes cluster information assistant. Follow these rules strictly:
                                    1. For counting pods, return ONLY the number of pods where status.phase is "Running"
                                    2. For pod names, remove the hash (e.g., 'snowflake-76b5665475-jzmwq' → 'snowflake')
                                    3. For counts, return only the number without any text
                                    4. For status queries, return only the status word
                                    5. For namespace queries, list only the namespace names separated by commas
                                    6. Never include explanations or additional context
                                    7. Never use quotes or brackets in the response
                                    """
                    },
                    {
                        "role": "user", 
                        "content": f"Comprehensive Cluster Context: {json.dumps(self.cluster_context)}\n\nQuery: {query}"
                    }
                ]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.error(f"Error querying OpenAI: {e}")
            return "Unable to process query"

# Global agent instance
kubernetes_query_agent = KubernetesQueryAgent()

@app.route('/query', methods=['POST'])
def create_query():
    try:
        # Extract the question from the request data
        request_data = request.json
        query = request_data.get('query')
        
        # Log the question
        logging.info(f"Received query: {query}")
        
        # Generate answer using the Kubernetes query agent
        answer = kubernetes_query_agent.query_openai(query)
        
        # Log the answer
        logging.info(f"Generated answer: {answer}")
        
        # Create the response model
        response = QueryResponse(query=query, answer=answer)
        
        return jsonify(response.dict())
    
    except ValidationError as e:
        return jsonify({"error": e.errors()}), 400
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)