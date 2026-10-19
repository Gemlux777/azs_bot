import aiohttp
import math

GIS_API_KEY = "4af31c9c-8314-48d1-b0f6-277847598479"
GIS_URL = "https://catalog.api.2gis.com/3.0/items"
FUEL_RUBRIC_ID = "18547"

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

async def find_fuel_stations(lat, lon, radius_km=10):
    location = f"{lon},{lat}"
    params = {
        "rubric_id": FUEL_RUBRIC_ID,
        "location": location,
        "radius": int(radius_km * 1000),
        "page_size": 10,
        "sort": "distance",
        "fields": "items.point,items.address,items.name",
        "key": GIS_API_KEY,
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(GIS_URL, params=params) as resp:
            if resp.status != 200:
                print(f"2GIS HTTP error: {resp.status}")
                return []
            try:
                data = await resp.json()
            except Exception as e:
                print(f"2GIS JSON error: {e}")
                return []

    if data.get("meta", {}).get("code") != 200:
        print(f"2GIS meta error: {data.get('meta')}")
        return []

    items = data.get("result", {}).get("items", [])
    if not items:
        return []

    stations = []
    for item in items:
        point = item.get("point") or item.get("geometry", {}).get("centroid")
        if not point:
            continue
        if isinstance(point, dict):
            s_lat, s_lon = point["lat"], point["lon"]
        else:
            s_lon, s_lat = map(float, point.split())

        stations.append({
            "osm_id": str(item.get("id")),
            "name": item.get("name", "АЗС"),
            "lat": s_lat,
            "lon": s_lon,
            "address": item.get("address_name", ""),
            "distance_km": round(haversine(lat, lon, s_lat, s_lon), 1),
            "fuel_status": "unknown",  # нет данных от gdebenz
        })

    stations.sort(key=lambda x: x["distance_km"])
    return stations[:10]
