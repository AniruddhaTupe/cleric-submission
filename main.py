import logging
import os
import subprocess
from flask import Flask, request, jsonify
from pydantic import BaseModel, ValidationError
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

class QueryResponse(BaseModel):
    query: str
    answer: str

def get_kubectl_command(query):
    """Translate natural language query to kubectl command using GPT-4"""
    try:
        system_prompt = """You are a Kubernetes expert. Convert the user's natural language query into 
        the appropriate kubectl command. Only return the exact command without any explanation or additional text. 
        The command should be read-only (no modifications to the cluster). Examples:
        - "How many pods are running?" -> "kubectl get pods --all-namespaces"
        - "What's the status of deployment nginx?" -> "kubectl get deployment nginx -o wide"
        - "Show me all nodes" -> "kubectl get nodes"
        """

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            temperature=0,
            max_tokens=100
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Error generating kubectl command: {str(e)}")
        raise

def execute_kubectl_command(command):
    """Execute the kubectl command and return the output"""
    try:
        # Remove any surrounding quotes that might cause issues
        command = command.strip('"\'')
        result = subprocess.run(
            command.split(),
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode != 0:
            raise Exception(f"Command failed: {result.stderr}")
        return result.stdout.strip()
    except Exception as e:
        logging.error(f"Error executing kubectl command: {str(e)}")
        raise

def format_response(query, command_output):
    """Format the kubectl output into a user-friendly response using GPT-4"""
    try:
        system_prompt = """You are a Kubernetes cluster assistant. Format the provided command output 
        into a clear, concise answer. Remove any technical identifiers (use 'mongodb' instead of 
        'mongodb-56c598c8fc'). Only return the direct answer without any explanations. 
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
        """

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Query: {query}\nCommand output: {command_output}"}
            ],
            temperature=0,
            max_tokens=100
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Error formatting response: {str(e)}")
        raise

@app.route('/query', methods=['POST'])
def create_query():
    try:
        # Extract the question from the request data
        request_data = request.json
        query = request_data.get('query')
        
        # Log the question
        logging.info(f"Received query: {query}")
        
        # Get kubectl command
        kubectl_command = get_kubectl_command(query)
        logging.info(f"Generated kubectl command: {kubectl_command}")
        
        # Execute kubectl command
        command_output = execute_kubectl_command(kubectl_command)
        logging.info(f"Command output: {command_output}")
        
        # Format the response
        answer = format_response(query, command_output)
        logging.info(f"Generated answer: {answer}")
        
        # Create the response model
        response = QueryResponse(query=query, answer=answer)
        
        return jsonify(response.dict())
    
    except ValidationError as e:
        logging.error(f"Validation error: {str(e)}")
        return jsonify({"error": e.errors()}), 400
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
