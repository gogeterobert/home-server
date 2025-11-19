# MCP Weather Server

A streamable HTTP MCP (Model Context Protocol) server that provides weather data using the Open-Meteo API. This server can be integrated with Open WebUI to give LLMs access to current weather and forecast data.

## Features

- **Current Weather**: Get real-time weather data for any city
- **Weather Forecast**: Get up to 16-day weather forecasts
- **No API Key Required**: Uses the free Open-Meteo API
- **MCP Resources**: Formatted weather data as resources
- **MCP Tools**: Callable tools for weather queries

## Tools

### `get_current_weather`
Fetch current weather for a city.

**Parameters:**
- `city` (str): Name of the city (e.g., "London", "New York", "Tokyo")
- `temperature_unit` (str, optional): "celsius" or "fahrenheit" (default: celsius)

**Returns:** Current weather data including temperature, humidity, wind speed, precipitation, etc.

### `get_forecast`
Get weather forecast for a city.

**Parameters:**
- `city` (str): Name of the city
- `days` (int, optional): Number of forecast days (1-16, default: 7)
- `temperature_unit` (str, optional): "celsius" or "fahrenheit" (default: celsius)

**Returns:** Daily forecast data with temperature ranges, precipitation, and wind information.

## Resources

- `weather://current/{city}` - Get current weather as a formatted resource
- `weather://forecast/{city}` - Get 7-day forecast as a formatted resource

## Building the Docker Image

### Local Build
```bash
cd mcp-weather-server
docker build -t mcp-weather:latest .
```

### Build and Push to Your Registry
```bash
# Build the image
docker build -t your-registry.com/mcp-weather:latest .

# Push to registry
docker push your-registry.com/mcp-weather:latest
```

### Build for K3s Registry
If you're using the local registry in your K3s cluster:

```bash
# Build the image
docker build -t localhost:5000/mcp-weather:latest .

# Push to local registry
docker push localhost:5000/mcp-weather:latest
```

## Running Locally

### Using Python
```bash
cd mcp-weather-server
pip install -r requirements.txt
python server.py
```

The server will start on `http://localhost:8000`

### Using Docker
```bash
docker run -p 8000:8000 mcp-weather:latest
```

## Kubernetes Deployment

The Kubernetes manifest is located at `k3s-manifests/mcp-weather.yml.j2` and will be deployed with your other manifests.

The service will be available at: `http://weather-mcp.ai.svc.cluster.local:8000`

## Integrating with Open WebUI

1. Access your Open WebUI admin settings
2. Navigate to the MCP Settings or External Tools section
3. Add a new MCP server with the following configuration:
   - **Name**: Weather Service
   - **Type**: HTTP Streamable MCP
   - **URL**: `http://weather-mcp.ai.svc.cluster.local:8000` (or your service URL)
   - **Transport**: streamable-http

4. Save the configuration and test the connection

## API Endpoints

Once running, the MCP server exposes:
- MCP protocol endpoints for tool discovery and invocation
- Resources for weather data

## Example Usage in Chat

Once integrated with Open WebUI, you can ask the LLM:
- "What's the current weather in London?"
- "Give me a 7-day forecast for Tokyo"
- "What's the temperature in New York in Fahrenheit?"

The LLM will use the MCP tools to fetch real-time weather data.

## Data Source

This server uses the [Open-Meteo API](https://open-meteo.com/), which provides:
- Free weather data with no API key required
- High-quality data from multiple national weather services
- Global coverage
- Up to 16-day forecasts

## Technical Details

- **Framework**: FastMCP
- **HTTP Client**: httpx (async)
- **Transport**: Streamable HTTP
- **Port**: 8000
- **Python Version**: 3.11
