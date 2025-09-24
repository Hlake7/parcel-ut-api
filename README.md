# parcel-ut-api

FastAPI service that returns **KML** parcels for Google Earth Pro via view-based **Network Links**.  
Counties: Salt Lake, Weber, Davis, Morgan, Utah.

## Run locally
~~~bash
python -m uvicorn main:app --reload --port 8000
~~~

## Google Earth Pro
- **Menu (toggle counties):** `http://127.0.0.1:8000/menu`  
  Refresh: **View-based → After camera stops → 0.5–1 s**
- **Direct (single link):**
  ~~~
  http://127.0.0.1:8000/kml?bbox=[bboxWest],[bboxSouth],[bboxEast],[bboxNorth]&eyeAlt=[eyeAltitude]
  ~~~
  Optional county filter, e.g. `&county=Weber%20County`

## Behavior
- LOD gates: `EYE_ALT_MAX_FT = 15000`, `MAX_VIEW_SPAN_DEG = 0.065` (tune as needed)
- Feature-count guard: `MAX_FEATURES = 5000` → shows a “Zoom in” overlay if exceeded
- Results are wrapped in a stable container so old placemarks clear on refresh
- Balloons include **Parcel link**, **GIS link**, **Address**, **Acres**, **Market Value** (if available)

## Troubleshooting
- **Empty KML:** view span too large or eye altitude above gate
- **“No symbol” overlay:** exceeded feature cap → zoom in or select fewer counties
- Server console logs `PARSED_BBOX {...}` on each refresh
