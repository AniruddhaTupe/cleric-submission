import json
import subprocess
import logging
import os
from openai import OpenAI
import chromadb
from typing import Dict, List

# Get API key from environment and initialize OpenAI client
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
if not os.environ.get('OPENAI_API_KEY'):
    raise ValueError("OPENAI_API_KEY environment variable is not set")

class KubernetesHelper:
    def __init__(self):
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
        
        # Initialize ChromaDB
        self.chroma_client = chromadb.Client()
        self.collection = self.chroma_client.create_collection(
            name="kubernetes_resources",
            metadata={"description": "Kubernetes cluster resources"}
        )
        
    def get_embedding(self, text: str) -> List[float]:
        """Get embeddings using OpenAI API"""
        response = client.embeddings.create(
            input=text,
            model="text-embedding-ada-002"
        )
        return response.data[0].embedding
    
    def refresh_cluster_data(self):
        """Execute kubectl commands and store results in ChromaDB"""
        logging.info("Starting cluster data refresh...")
        
        # Clear existing data
        all_ids = self.collection.get()['ids']
        if all_ids:
            logging.info("Clearing existing data...")
            self.collection.delete(ids=all_ids)
        
        documents = []
        metadatas = []
        ids = []
        doc_id = 0
        
        # Batch size for ChromaDB insertions
        BATCH_SIZE = 100
        
        for resource, command in self.commands.items():
            logging.info(f"Fetching {resource}...")
            try:
                result = subprocess.run(command.split(), capture_output=True, text=True)
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    if 'items' in data:
                        for item in data['items']:
                            doc = (f"Resource Type: {resource}\n"
                                  f"Name: {item['metadata']['name']}\n"
                                  f"Namespace: {item['metadata'].get('namespace', 'N/A')}\n"
                                  f"Full Details: {json.dumps(item, indent=2)}")
                            
                            documents.append(doc)
                            metadatas.append({
                                "resource_type": resource,
                                "name": item['metadata']['name'],
                                "namespace": item['metadata'].get('namespace', 'N/A')
                            })
                            ids.append(f"doc_{doc_id}")
                            doc_id += 1
                            
                            # Process in batches to avoid memory issues
                            if len(documents) >= BATCH_SIZE:
                                logging.info(f"Adding batch of {BATCH_SIZE} documents to ChromaDB...")
                                self.collection.add(
                                    documents=documents,
                                    metadatas=metadatas,
                                    ids=ids
                                )
                                documents = []
                                metadatas = []
                                ids = []
                else:
                    logging.error(f"Error executing {command}: {result.stderr}")
            except Exception as e:
                logging.error(f"Failed to execute {command}: {str(e)}")
        
        # Add remaining documents
        if documents:
            logging.info(f"Adding final batch of {len(documents)} documents to ChromaDB...")
            self.collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
        
        logging.info("Cluster data refresh complete")
        
    def search_resources(self, query: str) -> str:
        """Search through cluster data using semantic search"""
        try:
            # Query ChromaDB
            results = self.collection.query(
                query_texts=[query],
                n_results=5
            )
            
            if not results['documents'][0]:
                return "No matching resources found"
            
            # Format the context from results
            context = []
            for doc, metadata in zip(results['documents'][0], results['metadatas'][0]):
                context.append(doc)
            
            # Create prompt for OpenAI
            prompt = f"""Based on the following Kubernetes cluster information and the user's query, 
            provide a clear and concise answer. Focus only on relevant information.

            User Query: {query}

            Cluster Information:
            {'\n'.join(context)}

            Please provide a focused answer to the query using only the relevant information from above.
            Keep the answers very short and precise. Give only one-word answers wherever possible.
            Prioritize direct, factual responses.
            When listing single items, return just the name without brackets or quotes.
            If the answer is something like this - snowflake-76b5665475-jzmwq, return only snowflake."""

            # Get response from OpenAI using new API syntax
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a Kubernetes cluster assistant. Provide clear, concise answers based on the cluster information provided."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logging.error(f"Search error: {str(e)}")
            return f"Error performing search: {str(e)}"