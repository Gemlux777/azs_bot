import aiohttp
import math

GIS_API_KEY = "4af31c9c-8314-48d1-b0f6-277847598479"
GIS_URL = "https://catalog.api.2gis.com/3.0/items"
GIS_BYID_URL = "https://catalog.api.2gis.com/3.0/items/byid"
FUEL_RUBRIC_ID = "18547"

GDEBENZ_URL = "https://gdebenz.ru/api/nearby"

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


async def _fetch_gdebenz(session, lat, lon, radius_km):
    try:
        params = {"lat": lat, "lon": lon, "radius_km": radius_km}
        async with session.get(GDEBENZ_URL, params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("stations", [])
    except Exception as e:
        print(f"gdebenz error: {e}")
        return []


def _find_match(station, g_list):
    if not g_list:
        return None
    best, best_dist = None, float("inf")
    for g in g_list:
        try:
            g_lat = float(g.get("lat"))
            g_lon = float(g.get("lon"))
        except (TypeError, ValueError):
            continue
        dist = haversine(station["lat"], station["lon"], g_lat, g_lon)
        if dist < best_dist:
            best_dist, best = dist, g
    return best if best_dist < 0.3 else None


async def _get_point_by_id(session, item_id):
    """Запрашивает координаты АЗС по её id, если в основном ответе их нет."""
    try:
        params = {"id": item_id, "fields": "items.point", "key": GIS_API_KEY}
        async with session.get(GIS_BYID_URL, params=params) as resp:
            if resp.status != 200:
                return None, None
            data = await resp.json()
            if data.get("meta", {}).get("code") != 200:
                return None, None
            items = data.get("result", {}).get("items", [])
            if not items:
                return None, None
            point = items[0].get("point")
            if not point:
                return None, None
            if isinstance(point, dict):
                return float(point["lat"]), float(point["lon"])
            parts = point.split()
            return float(parts[1]), float(parts[0])
    except Exception as e:
        print(f"byid error for {item_id}: {e}")
        return None, None


async def find_fuel_stations(lat, lon, radius_km=10):
    try:
        return await _find_fuel_stations_internal(lat, lon, radius_km)
    except Exception as e:
        print(f"FATAL find_fuel_stations: {e}")
        return []


async def _find_fuel_stations_internal(lat, lon, radius_km):
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
        try:
            async with session.get(GIS_URL, params=params) as resp:
                if resp.status != 200:
                    print(f"2GIS HTTP {resp.status}")
                    return []
                data = await resp.json()
        except Exception as e:
            print(f"2GIS request error: {e}")
            return []

        if data.get("meta", {}).get("code") != 200:
            print(f"2GIS meta error: {data.get('meta')}")
            return []

        items = data.get("result", {}).get("items", [])
        print(f"2GIS: {len(items)} items")
        if not items:
            return []

        # Для каждого item без point — запрашиваем координаты отдельно
        stations = []
        for item in items:
            try:
                point = item.get("point") or item.get("geometry", {}).get("centroid")
                if not point:
                    item_id = item.get("id")
                    if item_id:
                        s_lat, s_lon = await _get_point_by_id(session, item_id)
                        if s_lat is None:
                            continue
                    else:
                        continue
                else:
                    if isinstance(point, dict):
                        s_lat, s_lon = float(point["lat"]), float(point["lon"])
                    else:
                        parts = point.split()
                        s_lon, s_lat = float(parts[0]), float(parts[1])
            except Exception as e:
                print(f"parse point error: {e}")
                continue

            stations.append({
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
            })

        # gdebenz
        g_list = await _fetch_gdebenz(session, lat, lon, radius_km)
        for s in stations:
            m = _find_match(s, g_list)
            if m:
                s["fuel_status"] = m.get("status", "unknown") or "unknown"
                s["fuels_now"] = m.get("fuels_now", "") or ""
                s["detail"] = m.get("detail", "") or ""
                try:
                    s["confirmations"] = int(m.get("confirmations", 0) or 0)
                except (TypeError, ValueError):
                    s["confirmations"] = 0

    stations.sort(key=lambda x: x["distance_km"])
    return stations[:15]
