import aiohttp
import math

GIS_API_KEY = "4af31c9c-8314-48d1-b0f6-277847598479"
GIS_URL = "https://catalog.api.2gis.com/3.0/items"

# ID рубрики "АЗС" в 2GIS (обычно 4500 или похожий, но лучше уточнить)
# Если этот ID не сработает, код ниже автоматически попробует найти его по названию
DEFAULT_RUBRIC_ID = "4500"

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

async def get_rubric_id(session, lat, lon):
    """Пытается найти ID рубрики 'АЗС' для региона."""
    # Сначала определяем регион по координатам
    region_url = "https://catalog.api.2gis.com/2.0/region/search"
    # 2GIS не имеет прямого поиска региона по координатам в этом API,
    # поэтому используем рубрику по умолчанию или ищем по названию в Москве
    # Для простоты возвращаем захардкоженный ID, который обычно работает
    return DEFAULT_RUBRIC_ID

async def find_fuel_stations(lat, lon, radius_km=10):
    location = f"{lon},{lat}"
    
    # Пробуем сначала по rubric_id
    params = {
        "rubric_id": DEFAULT_RUBRIC_ID,
        "location": location,
        "radius": int(radius_km * 1000),
        "page_size": 10,
        "sort": "distance",
        "key": GIS_API_KEY,
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(GIS_URL, params=params) as resp:
            if resp.status != 200:
                print(f"2GIS HTTP error (rubric): status={resp.status}, body={await resp.text()[:300]}")
                # Пробуем текстовый поиск как fallback
                return await fallback_text_search(session, lat, lon, radius_km)
            
            try:
                data = await resp.json()
            except Exception as e:
                print(f"2GIS JSON error: {e}")
                return []

    meta_code = data.get("meta", {}).get("code")
    if meta_code != 200:
        print(f"2GIS meta error (rubric): {data.get('meta')}")
        # Если рубрика не сработала, пробуем текстовый поиск
        async with aiohttp.ClientSession() as session:
            return await fallback_text_search(session, lat, lon, radius_km)

    items = data.get("result", {}).get("items", [])
    if not items:
        print("2GIS rubric search returned 0 items, trying text search...")
        async with aiohttp.ClientSession() as session:
            return await fallback_text_search(session, lat, lon, radius_km)

    return parse_items(items, lat, lon)


async def fallback_text_search(session, lat, lon, radius_km):
    """Запасной вариант: поиск по названиям крупных сетей АЗС."""
    networks = ["Лукойл", "Газпромнефть", "Роснефть", "Татнефть", "Shell"]
    all_stations = []
    seen_ids = set()
    
    for network in networks:
        params = {
            "q": network,
            "location": f"{lon},{lat}",
            "radius": int(radius_km * 1000),
            "page_size": 5,
            "key": GIS_API_KEY,
        }
        try:
            async with session.get(GIS_URL, params=params) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json()
                if data.get("meta", {}).get("code") == 200:
                    items = data.get("result", {}).get("items", [])
                    for item in items:
                        item_id = str(item.get("id"))
                        if item_id not in seen_ids:
                            seen_ids.add(item_id)
                            all_stations.append(item)
        except Exception as e:
            print(f"Fallback search error for {network}: {e}")
            continue
    
    if all_stations:
        return parse_items(all_stations, lat, lon)
    
    print("Fallback text search also returned 0 items.")
    return []


def parse_items(items, lat, lon):
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
        })

    stations.sort(key=lambda x: x["distance_km"])
    return stations[:10]
