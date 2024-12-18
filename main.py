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
            'running_pod_count': 0,
            'deployments': [],
            'services': [],
            'secrets': [],
            'pods': [],
            'service_to_namespace': {},  # New mapping for service locations
            'pod_details': {}  # New mapping for detailed pod information
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

            # Collect Pods with enhanced details
            all_pods = self.core_v1.list_pod_for_all_namespaces()
            running_pods = [pod for pod in all_pods.items if pod.status.phase == "Running"]
            cluster_info['running_pod_count'] = len(running_pods)
            
            for pod in all_pods.items:
                pod_base_name = pod.metadata.name.split('-')[0]  # Extract base name without hash
                
                for container in pod.spec.containers:
                    container_details = {
                        'name': container.name,
                        'image': container.image,
                        'ports': [],
                        'env': {},
                        'readiness_probe': None
                    }

                    # Collect ports
                    if container.ports:
                        container_details['ports'] = [
                            {
                                'container_port': port.container_port,
                                'protocol': port.protocol
                            } for port in container.ports
                        ]

                    # Collect environment variables
                    if container.env:
                        container_details['env'] = {
                            env.name: env.value for env in container.env if env.value
                        }

                    # Collect readiness probe details
                    if container.readiness_probe and container.readiness_probe.http_get:
                        container_details['readiness_probe'] = {
                            'path': container.readiness_probe.http_get.path,
                            'port': container.readiness_probe.http_get.port,
                            'scheme': container.readiness_probe.http_get.scheme
                        }

                    # Store in pod_details with hierarchical access
                    pod_key = f"{pod_base_name}/{container.name}"
                    cluster_info['pod_details'][pod_key] = container_details

                # Store basic pod information
                cluster_info['pods'].append({
                    'name': pod_base_name,
                    'full_name': pod.metadata.name,
                    'namespace': pod.metadata.namespace,
                    'status': pod.status.phase
                })

            # Collect Services with enhanced mapping
            for namespace in [ns['name'] for ns in cluster_info['namespaces']]:
                try:
                    services = self.core_v1.list_namespaced_service(namespace)
                    for svc in services.items:
                        service_name = svc.metadata.name.lower()  # Normalize service names
                        cluster_info['service_to_namespace'][service_name] = namespace
                        
                        cluster_info['services'].append({
                            'name': svc.metadata.name,
                            'namespace': namespace,
                            'ports': [
                                {
                                    'port': port.port,
                                    'target_port': port.target_port,
                                    'protocol': port.protocol
                                } for port in svc.spec.ports
                            ] if svc.spec.ports else []
                        })
                except Exception as svc_err:
                    logging.warning(f"Error collecting services in namespace {namespace}: {svc_err}")

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
        Send query to OpenAI with cluster context and improved system prompt
        """
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system", 
                        "content": """
                            You are a Kubernetes cluster information assistant. Follow these rules strictly:
                            1. For counting pods, return ONLY the number from running_pod_count
                            2. For pod names, use the base name without hash from the pods list
                            3. For service namespace queries, use the service_to_namespace mapping
                            4. For container ports, readiness probes, and env vars, check pod_details
                            5. Return only the specific value requested without any additional text
                            6. For namespace queries, return only the namespace name
                            7. For status queries, return only the status word
                            8. Never include explanations or additional context
                            9. Never use quotes or brackets in the response
                            10. For missing or not found data, return None
                            """
                    },
                    {
                        "role": "user", 
                        "content": f"Cluster Context: {json.dumps(self.cluster_context)}\n\nQuery: {query}"
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