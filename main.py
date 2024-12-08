import logging
import os
import subprocess
from typing import Optional
from flask import Flask, request, jsonify
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

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

# Define kubectl commands list
KUBECTL_COMMANDS = [
    "kubectl cluster-info",
    "kubectl get nodes -o wide",
    "kubectl describe nodes",
    "kubectl get namespaces",
    "kubectl get all --all-namespaces -o wide",
    "kubectl describe all --all-namespaces",
    "kubectl get configmaps --all-namespaces -o wide",
    "kubectl get secrets --all-namespaces -o wide",
    "kubectl get networkpolicies --all-namespaces",
    "kubectl get resourcequotas --all-namespaces",
    "kubectl get limitranges --all-namespaces",
    "kubectl get pv -o wide",
    "kubectl get pvc --all-namespaces -o wide",
    "kubectl get events --all-namespaces",
    "kubectl get svc --all-namespaces -o wide",
    "kubectl get ingress --all-namespaces -o wide",
    "kubectl get endpoints --all-namespaces",
    "kubectl get crd",
    "kubectl get config",
    "kubectl top nodes",
    "kubectl top pods --all-namespaces",
    "kubectl api-resources -o wide",
    "kubectl api-versions",
]

class QueryResponse(BaseModel):
    query: str
    answer: str

def get_appropriate_command(query: str) -> str:
    """Get the appropriate kubectl command for the query"""
    try:
        system_prompt = """You are a Kubernetes expert. Given a user query and a list of available kubectl commands, 
        either select the most appropriate command from the list or generate a new kubectl command if none fit. 
        Only return the exact command without any explanation. The command must be read-only (no modifications to the cluster).
        If multiple commands could work, choose the most specific one."""

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Available commands:\n{chr(10).join(KUBECTL_COMMANDS)}\n\nQuery: {query}"}
            ],
            temperature=0,
            max_tokens=100
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Error getting appropriate command: {str(e)}")
        raise

def execute_kubectl_command(command: str) -> tuple[str, Optional[str]]:
    """Execute a kubectl command and return output and error"""
    try:
        command = command.strip('"\'')
        result = subprocess.run(
            command.split(),
            capture_output=True,
            text=True,
            check=False
        )
        
        return result.stdout.strip(), result.stderr if result.returncode != 0 else None
    except Exception as e:
        logging.error(f"Error executing kubectl command: {str(e)}")
        return "", str(e)

def process_output(query: str, command: str, output: str) -> str:
    """Process command output using GPT-4"""
    try:
        system_prompt = """You are a Kubernetes cluster assistant. Format the command output into a clear, 
        concise answer to the user's query. Keep answers factual and to the point. Only give the required answer in 1 or 2 words.
        Don't use sentence structure.
        No need to write explanatory response. If the output indicates 
        an error or doesn't contain relevant information, respond with "Information not available"."""

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Query: {query}\nCommand: {command}\nOutput: {output}"}
            ],
            temperature=0,
            max_tokens=150
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Error processing output: {str(e)}")
        raise

@app.route('/query', methods=['POST'])
def query_cluster():
    """Process a query about the cluster"""
    try:
        request_data = request.json
        query = request_data.get('query')
        
        if not query:
            return jsonify({"error": "Query is required"}), 400

        logging.info(f"Processing query: {query}")
        
        # Get appropriate command for the query
        command = get_appropriate_command(query)
        logging.info(f"Selected command: {command}")
        
        # Execute the command
        output, error = execute_kubectl_command(command)
        if error:
            logging.error(f"Command execution error: {error}")
            return jsonify({"error": f"Command execution failed: {error}"}), 500
            
        # Process the output
        answer = process_output(query, command, output)
        
        response = QueryResponse(
            query=query,
            answer=answer,
            command_used=command
        )
        return jsonify(response.dict())
    
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
