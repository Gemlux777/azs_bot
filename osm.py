async def find_fuel_stations(lat, lon, radius_km=5):
    # 2GIS ждёт "lon,lat"
    location = f"{lon},{lat}"
    params = {
        "q": "АЗС",
        "location": location,
        "radius": int(radius_km * 1000),
        "page_size": 10,
        "key": GIS_API_KEY,
    }
    url = "https://catalog.api.2gis.com/3.0/items"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
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

    stations = []
    for item in data.get("result", {}).get("items", []):
        # У /3.0/items координаты в item.point
        point = item.get("point") or item.get("geometry", {}).get("centroid")
        if not point:
            continue
        # point может быть {"lat":..., "lon":...} или строкой "lon lat"
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
