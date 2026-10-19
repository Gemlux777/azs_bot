import aiohttp
import math

GIS_API_KEY = "4af31c9c-8314-48d1-b0f6-277847598479"
GIS_URL = "https://catalog.api.2gis.com/3.0/markers"

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

async def find_fuel_stations(lat, lon, radius_km=5):
    # 2GIS ждёт "lon,lat", а не "lat,lon"
    point = f"{lon},{lat}"
    params = {
        "q": "АЗС",
        "type": "branch",
        "point": point,
        "radius": int(radius_km * 1000),
        "sort": "distance",
        "page_size": 10,
        "key": GIS_API_KEY,
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(GIS_URL, params=params) as resp:
            if resp.status != 200:
                print(f"2GIS error: status={resp.status}, body={await resp.text()[:300]}")
                return []
            try:
                data = await resp.json()
            except Exception as e:
                print(f"2GIS JSON error: {e}")
                return []

    if data.get("meta", {}).get("code") != 200:
        print(f"2GIS meta error: {data.get('meta')}")
        return []

    stations = []
    for item in data.get("result", {}).get("items", []):
        geom = item.get("geometry", {})
        centroid = geom.get("centroid") or geom.get("point")
        if not centroid:
            continue

        s_lon, s_lat = map(float, centroid.split())
        name = item.get("name", "АЗС без названия")
        address = item.get("address_name", "")
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
