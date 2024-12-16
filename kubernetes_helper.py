import json
import subprocess
import logging
import os
from openai import OpenAI
from typing import Dict
from pathlib import Path
from llama_index.core import SimpleDirectoryReader
from llama_index.core import VectorStoreIndex, ServiceContext, Settings
from llama_index.llms.openai import OpenAI as LlamaOpenAI
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.core import StorageContext

# Get API key from environment and initialize OpenAI client
if not os.environ.get('OPENAI_API_KEY'):
    raise ValueError("OPENAI_API_KEY environment variable is not set")

class KubernetesHelper:
    def __init__(self):
        # Initialize OpenAI settings
        Settings.llm = LlamaOpenAI(model="gpt-4", temperature=0.3)
        
        # Initialize settings
        Settings.embed_model = OpenAIEmbedding(model="text-embedding-ada-002")
        Settings.chunk_size = 1024
        
        self.commands = {
            "namespaces": "kubectl get namespaces -o json",
            "pods": "kubectl get pods --all-namespaces -o json",
            "services": "kubectl get svc --all-namespaces -o json",
            "secrets": "kubectl get secrets --all-namespaces -o json", 
            "pvcs": "kubectl get pvc --all-namespaces -o json",
            "configmaps": "kubectl get configmaps --all-namespaces -o json",
            "deployments": "kubectl get deployments --all-namespaces -o json",
            "nodes": "kubectl get nodes -o json",
            "events": "kubectl get events --all-namespaces -o json"
        }
        
        # Create k8s_data directory if it doesn't exist
        self.data_dir = Path('k8s_data')
        self.data_dir.mkdir(exist_ok=True)
        self.index_path = 'k8s_index.json'
        self.index = None
        
    def refresh_cluster_data(self):
        """Execute kubectl commands and store results in JSON files"""
        logging.info("Starting cluster data refresh...")
        
        # Clear existing data
        for file in self.data_dir.glob('*.json'):
            file.unlink()
        
        for resource, command in self.commands.items():
            logging.info(f"Fetching {resource}...")
            try:
                result = subprocess.run(command.split(), capture_output=True, text=True)
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    
                    # Log the content summary
                    if resource == 'pods':
                        if 'items' in data:
                            pod_count = len(data['items'])
                            logging.info(f"Found {pod_count} pods in the cluster")
                            running_pods = sum(1 for pod in data['items'] 
                                            if pod.get('status', {}).get('phase') == 'Running')
                            logging.info(f"Of which {running_pods} pods are in Running state")
                    
                    # Save raw data
                    file_path = self.data_dir / f"{resource}.json"
                    with open(file_path, 'w') as f:
                        json.dump(data, f, indent=2)
                    
                    logging.info(f"Saved {resource} data to {file_path}")
                else:
                    logging.error(f"Error executing {command}: {result.stderr}")
            except Exception as e:
                logging.error(f"Failed to execute {command}: {str(e)}")
        
        # Create index from the JSON files
        try:
            logging.info("Creating vector store index...")
            documents = SimpleDirectoryReader(str(self.data_dir)).load_data()
            storage_context = StorageContext.from_defaults()
            self.index = VectorStoreIndex.from_documents(
                documents,
                storage_context=storage_context
            )
            # Save the index
            storage_context.persist(persist_dir=self.index_path)
            logging.info("Vector store index created and saved successfully")
        except Exception as e:
            logging.error(f"Failed to create index: {str(e)}")
            raise
                
    def search_resources(self, query: str) -> str:
        """Search through cluster data using LlamaIndex"""
        try:
            # Special handling for pod count query
            if query.lower().strip() in ["how many pods are running in the cluster?", "how many pods are running?"]:
                # Load and parse pods.json directly
                pods_file = self.data_dir / "pods.json"
                if pods_file.exists():
                    with open(pods_file) as f:
                        data = json.load(f)
                        if 'items' in data:
                            running_pods = sum(1 for pod in data['items'] 
                                            if pod.get('status', {}).get('phase') == 'Running')
                            return str(running_pods)
            
            # Regular vector search for other queries
            if not self.index:
                if os.path.exists(self.index_path):
                    storage_context = StorageContext.from_defaults(persist_dir=self.index_path)
                    self.index = VectorStoreIndex.from_storage(storage_context)
                else:
                    logging.error("No index found. Please refresh cluster data first.")
                    return "Error: No cluster data available. Please refresh first."
            
            logging.info(f"Querying index with: {query}")
            
            system_prompt = """
            You are a Kubernetes cluster information assistant. Follow these rules strictly:
            1. For counting pods, return ONLY the number of pods where status.phase is "Running"
            2. For pod names, remove the hash (e.g., 'snowflake-76b5665475-jzmwq' → 'snowflake')
            3. For counts, return only the number without any text
            4. For status queries, return only the status word
            5. For namespace queries, list only the namespace names separated by commas
            6. Never include explanations or additional context
            7. Never use quotes or brackets in the response
            """
            
            query_engine = self.index.as_query_engine(
                system_prompt=system_prompt,
                temperature=0.1
            )
            
            response = query_engine.query(query)
            answer = str(response).strip()
            
            logging.info(f"Generated answer: {answer}")
            return answer
            
        except Exception as e:
            logging.error(f"Search error: {str(e)}")
            return f"Error performing search: {str(e)}"