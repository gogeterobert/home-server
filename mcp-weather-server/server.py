from fastmcp import FastMCP
import httpx
from typing import Optional

mcp = FastMCP("weather-service")

# Open-Meteo API base URL (no API key required)
OPEN_METEO_BASE = "https://api.open-meteo.com/v1"
GEOCODING_API = "https://geocoding-api.open-meteo.com/v1"


async def get_coordinates(city: str) -> tuple[float, float]:
    """Get latitude and longitude for a city using Open-Meteo Geocoding API"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GEOCODING_API}/search",
            params={"name": city, "count": 1, "language": "en", "format": "json"}
        )
        data = response.json()
        
        if not data.get("results"):
            raise ValueError(f"City '{city}' not found")
        
        result = data["results"][0]
        return result["latitude"], result["longitude"]


@mcp.tool()
async def get_current_weather(city: str, temperature_unit: str = "celsius") -> dict:
    """
    Fetch current weather for a city using Open-Meteo API.
    
    Args:
        city: Name of the city (e.g., "London", "New York", "Tokyo")
        temperature_unit: Temperature unit - "celsius" or "fahrenheit" (default: celsius)
    
    Returns:
        Dictionary containing current weather data including temperature, humidity, wind speed, etc.
    """
    try:
        # Get coordinates for the city
        lat, lon = await get_coordinates(city)
        
        # Determine temperature unit parameter
        temp_unit = "fahrenheit" if temperature_unit.lower() == "fahrenheit" else "celsius"
        
        # Fetch current weather
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{OPEN_METEO_BASE}/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m",
                    "temperature_unit": temp_unit,
                    "wind_speed_unit": "kmh",
                    "precipitation_unit": "mm"
                }
            )
            weather_data = response.json()
            
            current = weather_data.get("current", {})
            
            return {
                "city": city,
                "latitude": lat,
                "longitude": lon,
                "temperature": current.get("temperature_2m"),
                "temperature_unit": weather_data.get("current_units", {}).get("temperature_2m", "°C"),
                "apparent_temperature": current.get("apparent_temperature"),
                "humidity": current.get("relative_humidity_2m"),
                "precipitation": current.get("precipitation"),
                "weather_code": current.get("weather_code"),
                "cloud_cover": current.get("cloud_cover"),
                "wind_speed": current.get("wind_speed_10m"),
                "wind_direction": current.get("wind_direction_10m"),
                "time": current.get("time"),
                "timezone": weather_data.get("timezone")
            }
    except Exception as e:
        return {"error": str(e), "city": city}


@mcp.tool()
async def get_forecast(city: str, days: int = 7, temperature_unit: str = "celsius") -> dict:
    """
    Get weather forecast for a city.
    
    Args:
        city: Name of the city (e.g., "London", "New York", "Tokyo")
        days: Number of forecast days (1-16, default: 7)
        temperature_unit: Temperature unit - "celsius" or "fahrenheit" (default: celsius)
    
    Returns:
        Dictionary containing daily forecast data
    """
    try:
        # Get coordinates for the city
        lat, lon = await get_coordinates(city)
        
        # Limit days to valid range
        days = max(1, min(days, 16))
        
        # Determine temperature unit parameter
        temp_unit = "fahrenheit" if temperature_unit.lower() == "fahrenheit" else "celsius"
        
        # Fetch forecast
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{OPEN_METEO_BASE}/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_direction_10m_dominant",
                    "temperature_unit": temp_unit,
                    "wind_speed_unit": "kmh",
                    "precipitation_unit": "mm",
                    "forecast_days": days
                }
            )
            forecast_data = response.json()
            
            daily = forecast_data.get("daily", {})
            
            # Format the forecast data
            forecast_days = []
            for i in range(len(daily.get("time", []))):
                forecast_days.append({
                    "date": daily["time"][i],
                    "temperature_max": daily["temperature_2m_max"][i],
                    "temperature_min": daily["temperature_2m_min"][i],
                    "precipitation_sum": daily["precipitation_sum"][i],
                    "precipitation_probability": daily["precipitation_probability_max"][i],
                    "weather_code": daily["weather_code"][i],
                    "wind_speed_max": daily["wind_speed_10m_max"][i],
                    "wind_direction": daily["wind_direction_10m_dominant"][i]
                })
            
            return {
                "city": city,
                "latitude": lat,
                "longitude": lon,
                "timezone": forecast_data.get("timezone"),
                "temperature_unit": forecast_data.get("daily_units", {}).get("temperature_2m_max", "°C"),
                "forecast": forecast_days
            }
    except Exception as e:
        return {"error": str(e), "city": city}


@mcp.resource("weather://current/{city}")
async def current_weather_resource(city: str) -> str:
    """Get current weather as a formatted resource"""
    weather = await get_current_weather(city)
    
    if "error" in weather:
        return f"Error fetching weather for {city}: {weather['error']}"
    
    return f"""Current Weather for {weather['city']}
Location: {weather['latitude']:.2f}°N, {weather['longitude']:.2f}°E
Time: {weather['time']} ({weather['timezone']})

Temperature: {weather['temperature']}{weather['temperature_unit']}
Feels like: {weather['apparent_temperature']}{weather['temperature_unit']}
Humidity: {weather['humidity']}%
Cloud Cover: {weather['cloud_cover']}%
Precipitation: {weather['precipitation']} mm
Wind: {weather['wind_speed']} km/h at {weather['wind_direction']}°
Weather Code: {weather['weather_code']}
"""


@mcp.resource("weather://forecast/{city}")
async def forecast_resource(city: str) -> str:
    """Get 7-day forecast as a formatted resource"""
    forecast = await get_forecast(city, days=7)
    
    if "error" in forecast:
        return f"Error fetching forecast for {city}: {forecast['error']}"
    
    output = f"""7-Day Weather Forecast for {forecast['city']}
Location: {forecast['latitude']:.2f}°N, {forecast['longitude']:.2f}°E
Timezone: {forecast['timezone']}

"""
    
    for day in forecast['forecast']:
        output += f"""
Date: {day['date']}
  Temperature: {day['temperature_min']}{forecast['temperature_unit']} - {day['temperature_max']}{forecast['temperature_unit']}
  Precipitation: {day['precipitation_sum']} mm (probability: {day['precipitation_probability']}%)
  Wind: {day['wind_speed_max']} km/h at {day['wind_direction']}°
  Weather Code: {day['weather_code']}
"""
    
    return output


if __name__ == "__main__":
    # Run the MCP server with streamable HTTP transport
    # Bind to 0.0.0.0 to allow connections from other pods
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
