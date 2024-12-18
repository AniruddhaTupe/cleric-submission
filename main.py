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
            # Track both total and running pods
            cluster_info['total_pod_count'] = len(all_pods.items)
            cluster_info['running_pod_count'] = len([pod for pod in all_pods.items if pod.status.phase == "Running"])
            
            # Create pod status mapping
            cluster_info['pod_status'] = {
                pod.metadata.name.split('-')[0]: pod.status.phase 
                for pod in all_pods.items
            }
            
            for pod in all_pods.items:
                # Extract base name and ensure consistent naming for special cases
                pod_base_name = pod.metadata.name.split('-')[0]
                
                # Special handling for harbor-core
                if 'harbor' in pod.metadata.name and 'core' in pod.metadata.name:
                    pod_base_name = 'harbor-core'
                
                for container in pod.spec.containers:
                    container_details = {
                        'name': container.name,
                        'image': container.image,
                        'ports': [],
                        'env': {},
                        'readiness_probe': None
                    }

                    # Collect ports with more details
                    if container.ports:
                        container_details['ports'] = [
                            {
                                'name': getattr(port, 'name', None),
                                'container_port': port.container_port,
                                'protocol': port.protocol,
                                'host_port': getattr(port, 'host_port', None)
                            } for port in container.ports
                        ]
                        # Store primary container port for quick access
                        if container_details['ports']:
                            container_details['primary_port'] = container_details['ports'][0]['container_port']

                    # Collect environment variables with better handling
                    if container.env:
                        container_details['env'] = {}
                        for env in container.env:
                            if env.value is not None:
                                container_details['env'][env.name] = env.value
                            elif env.value_from:
                                # Handle environment variables from various sources
                                if env.value_from.config_map_key_ref:
                                    container_details['env'][env.name] = f"configmap:{env.value_from.config_map_key_ref.key}"
                                elif env.value_from.secret_key_ref:
                                    container_details['env'][env.name] = f"secret:{env.value_from.secret_key_ref.key}"

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
                        # Store both original and lowercase service names for better matching
                        service_name = svc.metadata.name
                        service_name_lower = service_name.lower()
                        cluster_info['service_to_namespace'][service_name] = namespace
                        cluster_info['service_to_namespace'][service_name_lower] = namespace
                        
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
                            1. For pod counts:
                               - Use running_pod_count for running pods only
                               - Use total_pod_count for all pods
                            2. For Harbor service namespace:
                               - Check service_to_namespace map using both "harbor" and "Harbor"
                            3. For container ports:
                               - Check pod_details[pod_name/container_name]['ports']
                               - For harbor-core, use primary_port if available
                            4. For readiness probes:
                               - Extract path directly from pod_details[pod_name/container_name]['readiness_probe']['path']
                            5. For environment variables:
                               - Look up exact variable name in pod_details[pod_name/container_name]['env']
                            6. Return values without any formatting:
                               - No quotes, brackets, or explanatory text
                               - For missing data, return None
                               - For numeric values, return just the number
                               - For paths, return just the path
                            7. Special handling for Harbor components:
                               - Use exact matches for harbor-core
                               - Check both original and lowercase names
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
        request_data = request.json
        query = request_data.get('query')
        logging.info(f"Received query: {query}")
        
        answer = kubernetes_query_agent.query_openai(query)
        logging.info(f"Generated answer: {answer}")
        
        response = QueryResponse(query=query, answer=answer)
        return jsonify(response.dict())
    
    except ValidationError as e:
        return jsonify({"error": e.errors()}), 400
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)