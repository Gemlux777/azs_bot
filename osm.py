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
    """Запрашивает отметки из gdebenz. Никогда не бросает исключение."""
    params = {"lat": lat, "lon": lon, "radius_km": radius_km}
    try:
        async with session.get(GDEBENZ_URL, params=params) as resp:
            if resp.status != 200:
                print(f"gdebenz HTTP error: {resp.status}")
                return []
            try:
                data = await resp.json(content_type=None)
            except Exception as e:
                print(f"gdebenz JSON error: {e}")
                return []
            stations = data.get("stations", [])
            print(f"gdebenz: got {len(stations)} stations")
            return stations
    except Exception as e:
        print(f"gdebenz request error: {e}")
        return []


def match_gdebenz(station, gdebenz_list):
    """Находит ближайшую отметку gdebenz в радиусе 300 м."""
    if not gdebenz_list:
        return None
    best, best_dist = None, float("inf")
    for g in gdebenz_list:
        try:
            g_lat = float(g.get("lat"))
            g_lon = float(g.get("lon"))
        except (TypeError, ValueError):
            continue
        dist = haversine(station["lat"], station["lon"], g_lat, g_lon)
        if dist < best_dist:
            best_dist, best = dist, g
    if best and best_dist < 0.3:
        return best
    return None


async def find_fuel_stations(lat, lon, radius_km=10):
    """Главная функция. Никогда не бросает исключение — при любой ошибке вернёт []."""
    try:
        return await _find_fuel_stations(lat, lon, radius_km)
    except Exception as e:
        print(f"find_fuel_stations fatal error: {e}")
        return []


async def _find_fuel_stations(lat, lon, radius_km):
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
        # 1. 2GIS — список АЗС
        try:
            async with session.get(GIS_URL, params=params) as resp:
                if resp.status != 200:
                    print(f"2GIS HTTP error: {resp.status}")
                    return []
                data = await resp.json(content_type=None)
        except Exception as e:
            print(f"2GIS request error: {e}")
            return []

        if data.get("meta", {}).get("code") != 200:
            print(f"2GIS meta error: {data.get('meta')}")
            return []

        items = data.get("result", {}).get("items", [])
        print(f"2GIS: got {len(items)} items")
        if not items:
            return []

        # 2. gdebenz — отметки о топливе
        gdebenz_list = await get_gdebenz_stations(session, lat, lon, radius_km)

    stations = []
    for item in items:
        try:
            point = item.get("point") or item.get("geometry", {}).get("centroid")
            if not point:
                continue
            if isinstance(point, dict):
                s_lat, s_lon = float(point["lat"]), float(point["lon"])
            else:
                parts = point.split()
                s_lon, s_lat = float(parts[0]), float(parts[1])
        except Exception as e:
            print(f"parse point error: {e}")
            continue

        station = {
            "osm_id": str(item.get("id", "")),
            "name": item.get("name", "АЗС"),
            "lat": s_lat,
            "lon": s_lon,
            "address": item.get("address_name", "") or "",
            "distance_km": round(haversine(lat, lon, s_lat, s_lon), 1),
            "fuel_status": "unknown",
            "fuels_now": "",
            "detail": "",
            "confirmations": 0,
        }

        g = match_gdebenz(station, gdebenz_list)
        if g:
            station["fuel_status"] = g.get("status", "unknown") or "unknown"
            station["fuels_now"] = g.get("fuels_now", "") or ""
            station["detail"] = g.get("detail", "") or ""
            try:
                station["confirmations"] = int(g.get("confirmations", 0) or 0)
            except (TypeError, ValueError):
                station["confirmations"] = 0

        stations.append(station)

    stations.sort(key=lambda x: x["distance_km"])
    return stations[:15]
