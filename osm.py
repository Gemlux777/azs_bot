import aiohttp
import math

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

async def find_fuel_stations(lat, lon, radius_km=5):
    radius_m = int(radius_km * 1000)
    query = f"""
    [out:json][timeout:25];
    (
      node(around:{radius_m},{lat},{lon})[amenity=fuel];
      way(around:{radius_m},{lat},{lon})[amenity=fuel];
    );
    out center;
    """
    async with aiohttp.ClientSession() as session:
        async with session.post(OVERPASS_URL, data={"data": query}) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

    stations = []
    for el in data.get("elements", []):
        if el["type"] == "node":
            s_lat, s_lon = el["lat"], el["lon"]
        else:
            center = el.get("center", {})
            s_lat, s_lon = center.get("lat"), center.get("lon")

        if not s_lat or not s_lon:
            continue

        name = el.get("tags", {}).get("name", "АЗС без названия")
        dist = haversine(lat, lon, s_lat, s_lon)

        if dist <= radius_km:
            stations.append({
                "osm_id": f"{el['type']}_{el['id']}",
                "name": name,
                "lat": s_lat,
                "lon": s_lon,
                "distance_km": round(dist, 1)
            })

    stations.sort(key=lambda x: x["distance_km"])
    return stations[:10]
