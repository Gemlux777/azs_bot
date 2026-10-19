import aiohttp
import math

GIS_API_KEY = "4af31c9c-8314-48d1-b0f6-277847598479"
GIS_URL = "https://catalog.api.2gis.com/3.0/items"
FUEL_RUBRIC_ID = "18547"

GDEBENZ_URL = "https://gdebenz.ru/api/nearby"

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

async def get_gdebenz_stations(session, lat, lon, radius_km=10):
    """Запрашивает станции с отметками из gdebenz."""
    params = {
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
    }
    try:
        async with session.get(GDEBENZ_URL, params=params) as resp:
            if resp.status != 200:
                print(f"gdebenz HTTP error: {resp.status}")
                return []
            try:
                data = await resp.json()
            except Exception as e:
                print(f"gdebenz JSON error: {e}")
                return []
            return data.get("stations", [])
    except Exception as e:
        print(f"gdebenz request error: {e}")
        return []

def match_gdebenz_status(station, gdebenz_list):
    """Находит ближайшую отметку gdebenz для станции 2GIS."""
    if not gdebenz_list:
        return None
    best = None
    best_dist = float("inf")
    for g in gdebenz_list:
        g_lat, g_lon = g.get("lat"), g.get("lon")
        if g_lat is None or g_lon is None:
            continue
        dist = haversine(station["lat"], station["lon"], g_lat, g_lon)
        if dist < best_dist:
            best_dist = dist
            best = g
    # Если ближайшая отметка дальше 300 м — это другая АЗС
    if best and best_dist < 0.3:
        return best
    return None

async def find_fuel_stations(lat, lon, radius_km=10):
    location = f"{lon},{lat}"
    params = {
        "rubric_id": FUEL_RUBRIC_ID,
        "location": location,
        "radius": int(radius_km * 1000),
        "page_size": 20,
        "sort": "distance",
        "fields": "items.point,items.address,items.name",
        "key": GIS_API_KEY,
    }

    async with aiohttp.ClientSession() as session:
        # 1. Получаем список АЗС из 2GIS
        async with session.get(GIS_URL, params=params) as resp:
            if resp.status != 200:
                print(f"2GIS HTTP error: status={resp.status}")
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
            print("2GIS returned 0 items")
            return []

        # 2. Получаем данные gdebenz
        gdebenz_list = await get_gdebenz_stations(session, lat, lon, radius_km)

    stations = []
    for item in items:
        point = item.get("point") or item.get("geometry", {}).get("centroid")
        if not point:
            continue
        if isinstance(point, dict):
            s_lat, s_lon = point["lat"], point["lon"]
        else:
            s_lon, s_lat = map(float, point.split())

        station = {
            "osm_id": str(item.get("id")),
            "name": item.get("name", "АЗС"),
            "lat": s_lat,
            "lon": s_lon,
            "address": item.get("address_name", ""),
            "distance_km": round(haversine(lat, lon, s_lat, s_lon), 1),
            "fuel_status": "unknown",
            "fuels_now": "",
            "detail": "",
            "confirmations": 0,
        }

        # Сопоставляем с gdebenz
        g = match_gdebenz_status(station, gdebenz_list)
        if g:
            station["fuel_status"] = g.get("status", "unknown")
            station["fuels_now"] = g.get("fuels_now", "") or g.get("detail", "")
            station["detail"] = g.get("detail", "")
            station["confirmations"] = g.get("confirmations", 0)

        stations.append(station)

    stations.sort(key=lambda x: x["distance_km"])
    return stations[:15]
