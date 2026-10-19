import aiohttp
import math

GIS_API_KEY = "4af31c9c-8314-48d1-b0f6-277847598479"
GIS_URL = "https://catalog.api.2gis.com/3.0/items"
FUEL_RUBRIC_ID = "18547"

# Публичный API gdebenz (народная карта)
GDEBENZ_URL = "https://gdebenz.ru/api/nearby"

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

async def get_fuel_status_from_gdebenz(session, lat, lon, radius_km=5):
    """Возвращает список станций с отметками топлива из gdebenz."""
    params = {
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
    }
    try:
        async with session.get(GDEBENZ_URL, params=params, timeout=10) as resp:
            if resp.status != 200:
                print(f"gdebenz HTTP error: {resp.status}")
                return []
            data = await resp.json()
            # Структура ответа gdebenz: список станций с полями fuels_now, status и т.д.
            # Точный формат зависит от API, но в gdebenz-mcp указано:
            # status: yes/queue/low/no/unknown
            stations = []
            for item in data.get("stations", data.get("items", [])):
                stations.append({
                    "lat": item.get("lat"),
                    "lon": item.get("lon"),
                    "name": item.get("name", ""),
                    "status": item.get("status", "unknown"),
                    "fuels_now": item.get("fuels_now", ""),
                })
            return stations
    except Exception as e:
        print(f"gdebenz request error: {e}")
        return []

def match_station_status(station, gdebenz_stations):
    """Находит ближайшую отметку gdebenz для станции 2GIS."""
    if not gdebenz_stations:
        return "unknown"
    best = None
    best_dist = float("inf")
    for g in gdebenz_stations:
        if g["lat"] is None or g["lon"] is None:
            continue
        dist = haversine(station["lat"], station["lon"], g["lat"], g["lon"])
        if dist < best_dist:
            best_dist = dist
            best = g
    # Если ближайшая отметка дальше 500 м — считаем, что это другая АЗС
    if best and best_dist < 0.5:
        return best["status"]
    return "unknown"

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
        # 1. Получаем список АЗС из 2GIS
        async with session.get(GIS_URL, params=params) as resp:
            if resp.status != 200:
                print(f"2GIS HTTP error: status={resp.status}")
                return []
            data = await resp.json()

        if data.get("meta", {}).get("code") != 200:
            print(f"2GIS meta error: {data.get('meta')}")
            return []

        items = data.get("result", {}).get("items", [])
        if not items:
            return []

        # 2. Параллельно запрашиваем статусы из gdebenz
        gdebenz_stations = await get_fuel_status_from_gdebenz(session, lat, lon, radius_km)

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
        dist = haversine(lat, lon, s_lat, s_lon)

        stations.append({
            "osm_id": str(item.get("id")),
            "name": name,
            "lat": s_lat,
            "lon": s_lon,
            "address": address,
            "distance_km": round(dist, 1),
            "fuel_status": "unknown",  # заполним ниже
        })

    # 3. Сопоставляем статусы
    for s in stations:
        s["fuel_status"] = match_station_status(s, gdebenz_stations)

    stations.sort(key=lambda x: x["distance_km"])
    return stations[:10]
