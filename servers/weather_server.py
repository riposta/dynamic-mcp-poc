"""Standalone Weather MCP Server with JWT auth via Keycloak -- uses Open-Meteo API"""
import os
import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token

load_dotenv()

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "mcp-poc")

verifier = JWTVerifier(
    jwks_uri=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs",
    issuer=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
    audience="mcp-weather",
    algorithm="RS256",
)

mcp = FastMCP("Weather Server", auth=verifier)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather interpretation codes -> human-readable conditions
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


async def geocode(location: str) -> dict | None:
    """Resolve location name to lat/lon using Open-Meteo Geocoding API.
    Tries multiple language variants to handle local names (e.g. 'Warszawa')."""
    best = None
    async with httpx.AsyncClient() as http:
        for lang in [None, "en", "pl", "de", "fr", "es"]:
            params = {"name": location, "count": 5}
            if lang:
                params["language"] = lang
            resp = await http.get(GEOCODING_URL, params=params)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            for r in results:
                if best is None or r.get("population", 0) > best.get("population", 0):
                    best = r
            if best and best.get("population", 0) > 100_000:
                break  # found a major city, no need to try more languages
    if not best:
        return None
    return {"name": best["name"], "country": best.get("country", ""), "lat": best["latitude"], "lon": best["longitude"]}


@mcp.tool()
async def get_weather(location: str) -> dict:
    """Get current weather for a location"""
    token = get_access_token()
    user = token.claims.get("preferred_username", "unknown") if token else "anonymous"
    print(f"get_weather called by {user} for {location}")

    geo = await geocode(location)
    if not geo:
        return {"error": f"Location '{location}' not found", "requested_by": user}

    async with httpx.AsyncClient() as http:
        resp = await http.get(FORECAST_URL, params={
            "latitude": geo["lat"],
            "longitude": geo["lon"],
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        })
        resp.raise_for_status()
        current = resp.json()["current"]

    return {
        "location": f"{geo['name']}, {geo['country']}",
        "temperature": current["temperature_2m"],
        "unit": "celsius",
        "condition": WMO_CODES.get(current["weather_code"], "Unknown"),
        "humidity": current["relative_humidity_2m"],
        "wind_speed_kmh": current["wind_speed_10m"],
        "requested_by": user,
    }


@mcp.tool()
async def get_forecast(location: str, days: int = 3) -> dict:
    """Get weather forecast for a location"""
    token = get_access_token()
    user = token.claims.get("preferred_username", "unknown") if token else "anonymous"
    print(f"get_forecast called by {user} for {location}, {days} days")

    geo = await geocode(location)
    if not geo:
        return {"error": f"Location '{location}' not found", "requested_by": user}

    days = min(days, 16)  # Open-Meteo max is 16 days

    async with httpx.AsyncClient() as http:
        resp = await http.get(FORECAST_URL, params={
            "latitude": geo["lat"],
            "longitude": geo["lon"],
            "daily": "temperature_2m_max,temperature_2m_min,weather_code",
            "forecast_days": days,
        })
        resp.raise_for_status()
        daily = resp.json()["daily"]

    forecast = []
    for i in range(len(daily["time"])):
        forecast.append({
            "date": daily["time"][i],
            "temp_max": daily["temperature_2m_max"][i],
            "temp_min": daily["temperature_2m_min"][i],
            "condition": WMO_CODES.get(daily["weather_code"][i], "Unknown"),
        })

    return {
        "location": f"{geo['name']}, {geo['country']}",
        "days": len(forecast),
        "forecast": forecast,
        "requested_by": user,
    }


if __name__ == "__main__":
    port = int(os.getenv("WEATHER_PORT", "8011"))
    print(f"Starting Weather MCP Server on http://localhost:{port}")
    mcp.run(transport="streamable-http", port=port)
