FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the server code
COPY server.py .

# Expose the port the MCP server runs on
EXPOSE 8000

# Run the MCP server
CMD ["python", "server.py"]
