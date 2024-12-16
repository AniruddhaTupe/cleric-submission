import logging
from flask import Flask, request, jsonify
from pydantic import BaseModel, ValidationError
from kubernetes_helper import KubernetesHelper
import os

# Verify OpenAI API key is set
if not os.environ.get('OPENAI_API_KEY'):
    raise ValueError("OPENAI_API_KEY environment variable is not set")

# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s %(levelname)s - %(message)s',
                    filename='agent.log', filemode='a')

app = Flask(__name__)
k8s_helper = KubernetesHelper()


class QueryResponse(BaseModel):
    query: str
    answer: str


@app.route('/refresh', methods=['POST'])
def refresh_data():
    """Endpoint to refresh cluster data"""
    try:
        k8s_helper.refresh_cluster_data()
        return jsonify({"status": "success"})
    except Exception as e:
        logging.error(f"Refresh error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/query', methods=['POST'])
def create_query():
    try:
        # Extract the question from the request data
        request_data = request.json
        query = request_data.get('query')
        
        if not query:
            return jsonify({"error": "Query is required"}), 400
        
        # Log the question
        logging.info(f"Received query: {query}")
        
        # Search cluster data for relevant information
        answer = k8s_helper.search_resources(query)
        
        # Log the answer
        logging.info(f"Generated answer: {answer}")
        
        # Create the response model
        response = QueryResponse(query=query, answer=answer)
        
        return jsonify(response.dict())
    
    except ValidationError as e:
        return jsonify({"error": e.errors()}), 400
    except Exception as e:
        logging.error(f"Query error: {str(e)}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    try:
        # Initial data load
        logging.info("Starting application...")
        k8s_helper.refresh_cluster_data()
        logging.info("Initial data load complete. Starting Flask server...")
        app.run(host="0.0.0.0", port=8000)
    except Exception as e:
        logging.error(f"Failed to start application: {str(e)}")
        raise
