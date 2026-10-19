import aiohttp
import math

GIS_API_KEY = "4af31c9c-8314-48d1-b0f6-277847598479"
GIS_URL = "https://catalog.api.2gis.com/3.0/items"
FUEL_RUBRIC_ID = "18547"  # "Заправочные станции" (проверено для Москвы)

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
                print(f"2GIS HTTP error: status={resp.status}, body={await resp.text()[:300]}")
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
        print("2GIS returned 0 items for rubric 18547")
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

        name = item.get("name", "АЗС без названия")
        address = item.get("address_name", "")
        if not address and isinstance(item.get("address"), dict):
            address = item["address"].get("name", "")
        dist = haversine(lat, lon, s_lat, s_lon)

        stations.append({
            "osm_id": str(item.get("id")),
            "name": name,
            "lat": s_lat,
            "lon": s_lon,
            "address": address,
            "distance_km": round(dist, 1),
        })

    stations.sort(key=lambda x: x["distance_km"])
    return stations[:10]
