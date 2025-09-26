from fastapi import FastAPI, Response, Query
import requests, html
from urllib.parse import quote
from fastapi.responses import JSONResponse
import json

app = FastAPI(title="parcel-ut")

# --- diagnostics: quick feature count per county ---
def _parse_bbox_params(bboxWest, bboxSouth, bboxEast, bboxNorth, BBOX, bbox):
    def to_float(v):
        try:
            return float(v)
        except Exception:
            return None
    w = to_float(bboxWest); s = to_float(bboxSouth)
    e = to_float(bboxEast); n = to_float(bboxNorth)

    combo = BBOX or bbox
    if None in (w, s, e, n) and combo:
        try:
            w2, s2, e2, n2 = [float(x) for x in combo.split(",")]
            w, s, e, n = w2, s2, e2, n2
        except Exception:
            pass
    return w, s, e, n

def _arcgis_count(layer_url: str, env_4326: dict) -> dict:
    params = {
        "f": "json",
        "where": "1=1",
        "geometry": json.dumps(env_4326),
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnCountOnly": "true",
    }
    try:
        r = requests.get(f"{layer_url}/query", params=params, timeout=20)
        data = r.json()
        if "error" in data:
            return {"count": 0, "error": data["error"].get("message", "arcgis error")}
        return {"count": int(data.get("count", 0))}
    except Exception as ex:
        return {"count": 0, "error": str(ex)}

@app.get("/diag")
def diag(
    bboxWest: str | None = Query(None),
    bboxSouth: str | None = Query(None),
    bboxEast: str | None = Query(None),
    bboxNorth: str | None = Query(None),
    BBOX: str | None = Query(None, alias="BBOX"),
    bbox: str | None = Query(None, alias="bbox"),
    county: str | None = Query(None),
):
    w, s, e, n = _parse_bbox_params(bboxWest, bboxSouth, bboxEast, bboxNorth, BBOX, bbox)
    if None in (w, s, e, n):
        return JSONResponse({"ok": False, "reason": "no bbox parsed"})

    env = {"xmin": w, "ymin": s, "xmax": e, "ymax": n, "spatialReference": {"wkid": 4326}}
    if county:
        wanted = {c.strip().lower() for c in county.split(",")}
        sources = [src for src in COUNTY_SOURCES if src["name"].lower() in wanted]
    else:
        sources = COUNTY_SOURCES

    out = {}
    for src in sources:
        out[src["name"]] = _arcgis_count(src["layer_url"], env)

    spanx, spany = abs(e - w), abs(n - s)
    return JSONResponse({
        "ok": True,
        "bbox": [w, s, e, n],
        "span_deg": {"x": spanx, "y": spany},
        "counts": out
    })


# ---- Settings ----
EYE_ALT_MAX_FT = 15000
MAX_VIEW_SPAN_DEG = 0.065  # ~5–7 km window at your latitude
FOLDER_ID = "active-parcels"  # stable container so GE replaces it on refresh
MAX_FEATURES = 5000  # cap per request (tune later)
COUNT_TOO_LARGE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Too many parcels</name>
    <ScreenOverlay>
      <name>Zoom in</name>
      <overlayXY x="0" y="1" xunits="fraction" yunits="fraction"/>
      <screenXY x="0.02" y="0.98" xunits="fraction" yunits="fraction"/>
      <size x="0" y="0" xunits="pixels" yunits="pixels"/>
      <Icon><href>http://maps.google.com/mapfiles/kml/shapes/forbidden.png</href></Icon>
    </ScreenOverlay>
    <Placemark>
      <name>Parcel query too large</name>
      <description><![CDATA[
        Your current view would return <b>{count}</b> parcels (max {max}).<br/>
        Please zoom in or select fewer counties.
      ]]></description>
      <Point><coordinates>0,0,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""

# ---- County sources ----
# Notes on external links:
# - Davis dashboard supports /dashboard/parcel/{PARCEL_ID} (numeric/undashed).
# - Utah County supports property.asp?av_serial={SERIAL} and ParcelMap.html?serial={SERIAL}.
# - Morgan County’s TaxRoll portal accepts ?parcel={PARCEL_ID} and their public ownership map is an ArcGIS web app.
COUNTY_SOURCES = [
    {
        "name": "Salt Lake County",
        "layer_url": "https://services1.arcgis.com/99lidPhWCzftIe9K/arcgis/rest/services/Parcels_SaltLake_LIR/FeatureServer/0",
        "valuation_tmpl": "https://apps.saltlakecounty.gov/assessor/new/valuationInfoExpanded.cfm?parcel_id={pid}&link_id=0",
        "gis_link_tmpl": "https://apps.saltlakecountyutah.gov/assessor/new/javaapi2/parcelviewext.cfm?parcel_ID={pid}&query=Y",
    },
    {
        "name": "Weber County",
        "layer_url": "https://services1.arcgis.com/99lidPhWCzftIe9K/arcgis/rest/services/Parcels_Weber_LIR/FeatureServer/0",
        "valuation_tmpl": None,  # (no direct parcel-detail URL handy)
        "gis_link_tmpl": "https://www.webercountyutah.gov/GIS/gizmo2/index.html",
    },
    {
        "name": "Davis County",
        "layer_url": "https://services1.arcgis.com/99lidPhWCzftIe9K/arcgis/rest/services/Parcels_Davis_LIR/FeatureServer/0",
        # Dashboard deep link takes the numeric parcel id; we pass the raw digits
        "valuation_tmpl": "https://webportal.daviscountyutah.gov/App/PropertySearch/dashboard/parcel/{pid}",
        # Generic GIS map landing page
        "gis_link_tmpl": "https://webportal.daviscountyutah.gov/App/PropertySearch/esri/map",
    },
    {
        "name": "Morgan County",
        "layer_url": "https://services1.arcgis.com/99lidPhWCzftIe9K/arcgis/rest/services/Parcels_Morgan_LIR/FeatureServer/0",
        # Public tax roll portal accepts ?parcel= with dashed or undashed parcel numbers
        "valuation_tmpl": "https://taxroll.cloudapput.com/?parcel={pid}",
        # Public ownership map (ArcGIS web app)
        "gis_link_tmpl": "https://www.arcgis.com/apps/View/index.html?appid=7a38029a0fe449fdba1ed228152d7ede",
    },
    {
        "name": "Utah County",
        "layer_url": "https://services1.arcgis.com/99lidPhWCzftIe9K/arcgis/rest/services/Parcels_Utah_LIR/FeatureServer/0",
        # Utah County property page (works with av_serial=)
        "valuation_tmpl": "https://www.utahcounty.gov/LandRecords/property.asp?av_serial={pid}",
        # Utah County parcel map supports ?serial=
        "gis_link_tmpl": "https://maps.utahcounty.gov/ParcelMap/ParcelMap.html?serial={pid}",
    },
]

# ---- KML Styles (cyan outlines; bold on hover/click) ----
KML_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
    '<name>Parcel-UT (live)</name>'
    '<Style id="parcel-normal">'
      '<LineStyle><color>ffffff00</color><width>2</width></LineStyle>'
      '<PolyStyle><color>00000000</color></PolyStyle>'
    '</Style>'
    '<Style id="parcel-highlight">'
      '<LineStyle><color>ffffff00</color><width>4</width></LineStyle>'
      '<PolyStyle><color>00000000</color></PolyStyle>'
    '</Style>'
    '<StyleMap id="parcel-map">'
      '<Pair><key>normal</key><styleUrl>#parcel-normal</styleUrl></Pair>'
      '<Pair><key>highlight</key><styleUrl>#parcel-highlight</styleUrl></Pair>'
    '</StyleMap>'
# Hide children in Places tree for speed
'<Style id="container-hide-children">'
      '<ListStyle><listItemType>checkHideChildren</listItemType></ListStyle>'
    '</Style>'
)
KML_FOOTER = '</Document></kml>'

# ---- Helpers ----
def ring_to_kml_coords(coords):
    return " ".join(f"{c[0]},{c[1]},0" for c in coords)

def feature_to_kml(feature, county_name: str, valuation_tmpl: str | None, gis_link_tmpl: str | None, zlabel: str | None = None):
    props = feature.get("properties") or {}
    geom  = feature.get("geometry") or {}
    gtype = geom.get("type")

    raw_val = (
        props.get("PARCEL_ID") or props.get("PARCELNO") or props.get("PARCEL")
        or props.get("SERIAL_NUM") or props.get("SERIALNUM") or props.get("OBJECTID") or ""
    )
    raw = html.escape(str(raw_val))

    def fmt_pid(pid: str) -> str:
        digits = "".join(ch for ch in str(pid) if ch.isdigit())
        return f"{digits[0:2]}-{digits[2:4]}-{digits[4:7]}-{digits[7:10]}-{digits[10:14]}" if len(digits) == 14 else pid

    def _to_num(x):
        try: return float(str(x).replace(",", ""))
        except Exception: return None

    def _fmt_money(x):
        n = _to_num(x);  return f"${n:,.0f}" if n is not None else None

    def _fmt_acres(x):
        n = _to_num(x);  return f"{n:,.2f}" if n is not None else None

    # Common LIR fields (owner varies by county; try several)
    addr = props.get("PARCEL_ADD") or props.get("SITUS_ADDR") or props.get("SITE_ADDR") or props.get("SITEADD") or props.get("SITUSADDR")
    city = props.get("PARCEL_CITY") or props.get("SITUS_CITY") or props.get("CITY")
    acres = props.get("PARCEL_ACRES") or props.get("ACRES") or props.get("GIS_ACRES")
    mv_total = props.get("TOTAL_MKT_VALUE") or props.get("TOTAL_MARKET_VALUE") or props.get("MARKET_VALUE")
    mv_land  = props.get("LAND_MKT_VALUE")  or props.get("LAND_MARKET_VALUE")

    owner = (
        props.get("OWNER") or props.get("OWNER1") or props.get("OWNER_NAME") or
        props.get("OWNERNME1") or props.get("OWNERNAM1") or props.get("TAXPAYER")
    )

    pretty = fmt_pid(raw)

    def polygon_to_kml(poly):
        outer = ring_to_kml_coords(poly[0])
        holes = "".join(
            f"<innerBoundaryIs><LinearRing><coordinates>{ring_to_kml_coords(r)}</coordinates></LinearRing></innerBoundaryIs>"
            for r in poly[1:]
        )

        parts = [f"<b>Parcel:</b> "]
        if valuation_tmpl:
            parts.append(f"<a href='{valuation_tmpl.format(pid=raw)}' target='_blank'>{pretty}</a>")
        else:
            parts.append(pretty)
        if gis_link_tmpl:
            parts.append(f"<br/><a href='{gis_link_tmpl.format(pid=raw)}' target='_blank'>{county_name} GIS</a>")

        if addr or city:
            parts.append(f"<br/><b>Address:</b> {html.escape(addr) if addr else ''}{', ' + html.escape(city) if city else ''}")
        fa = _fmt_acres(acres)
        if fa: parts.append(f"<br/><b>Acres:</b> {fa}")
        fm = _fmt_money(mv_total)
        if fm: parts.append(f"<br/><b>Assessed Total Value:</b> {fm}")
        fml = _fmt_money(mv_land)
        if fml: parts.append(f"<br/><b>Assessed Land Value:</b> {fml}")

        if owner:
            parts.append(f"<br/><b>Owner:</b> {html.escape(str(owner))}")

        if zlabel:
            parts.append(f"<br/><b>Zoning:</b> {html.escape(zlabel)}")

        return (
            f"<Placemark>"
            f"<name>{raw}</name>"
            f"<description><![CDATA[{''.join(parts)}]]></description>"
            f"<styleUrl>#parcel-map</styleUrl>"
            f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{outer}</coordinates></LinearRing></outerBoundaryIs>"
            f"{holes}</Polygon>"
            f"</Placemark>"
        )

    if gtype == "Polygon":
        return polygon_to_kml(geom["coordinates"])
    if gtype == "MultiPolygon":
        return "".join(polygon_to_kml(p) for p in geom["coordinates"])
    return ""


# ---- Endpoints ----
@app.get("/kml")
def kml(
    bboxWest: str | None = Query(None),
    bboxSouth: str | None = Query(None),
    bboxEast: str | None = Query(None),
    bboxNorth: str | None = Query(None),
    eyeAlt: str | None = Query(None),
    # accept both combined bbox casings
    BBOX: str | None = Query(None, alias="BBOX"),
    bbox: str | None = Query(None, alias="bbox"),
    county: str | None = Query(None),  # comma-separated county names
):
    def to_float(s):
        try:
            return float(s)
        except Exception:
            return None

    # Parse individual params (GE placeholders may be strings like "[bboxWest]")
    w = to_float(bboxWest); s = to_float(bboxSouth)
    e = to_float(bboxEast); n = to_float(bboxNorth)
    eye = to_float(eyeAlt)

    # Fall back to combined bbox
    bbox_str = BBOX or bbox
    if None in (w, s, e, n) and bbox_str:
        try:
            w2, s2, e2, n2 = [float(x) for x in bbox_str.split(",")]
            w, s, e, n = w2, s2, e2, n2
        except Exception:
            pass

    # Missing bbox → empty
    if None in (w, s, e, n):
        print("NO BBOX PARSED", {"BBOX": BBOX, "bbox": bbox})
        return Response(KML_HEADER + KML_FOOTER, media_type="application/vnd.google-earth.kml+xml")

    # Debug (optional)
    print("PARSED_BBOX", {"w": w, "s": s, "e": e, "n": n, "eye": eye})

    # LOD / span gates
    if eye is not None and eye > EYE_ALT_MAX_FT:
        return Response(KML_HEADER + KML_FOOTER, media_type="application/vnd.google-earth.kml+xml")
    if abs(e - w) > MAX_VIEW_SPAN_DEG or abs(n - s) > MAX_VIEW_SPAN_DEG:
        return Response(KML_HEADER + KML_FOOTER, media_type="application/vnd.google-earth.kml+xml")

    envelope = {
        "xmin": w, "ymin": s, "xmax": e, "ymax": n,
        "spatialReference": {"wkid": 4326}
    }

    # Filter counties if requested (accept exact names as you currently pass from /menu)
    if county:
        wanted = {c.strip().lower() for c in county.split(",")}
        sources = [src for src in COUNTY_SOURCES if src["name"].lower() in wanted]
    else:
        sources = COUNTY_SOURCES

    # --- Feature-count guard: sum counts across selected counties ---
    total_count = 0
    for src in sources:
        res = _arcgis_count(src["layer_url"], envelope)  # uses the helper from /diag
        total_count += int(res.get("count", 0))
        if total_count > MAX_FEATURES:
            msg = COUNT_TOO_LARGE_KML.format(count=total_count, max=MAX_FEATURES)
            return Response(msg, media_type="application/vnd.google-earth.kml+xml")


    placemarks = []

    for src in sources:
        params = {
            "f": "geojson",
            "where": "1=1",
            "outFields": "*",
            "geometry": json.dumps(envelope),  # important: real JSON
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "returnGeometry": "true",
            "outSR": 4326,
            "resultRecordCount": 1000,  # safer page size
            "resultOffset": 0,
        }

        features = []
        while True:
            r = requests.get(f"{src['layer_url']}/query", params=params, timeout=30)
            r.raise_for_status()
            gj = r.json()

            # If ArcGIS returns a JSON-level error, bail (prevents silent empties)
            if isinstance(gj, dict) and "error" in gj:
                print("ARC_ERROR", src["name"], gj["error"].get("message"))
                break

            batch = gj.get("features", [])
            if not batch:
                break

            features.extend(batch)

            # Page using the server’s flag; fall back to offset length
            if not gj.get("exceededTransferLimit"):
                break
            params["resultOffset"] += len(batch)

        if features:
            print(f"{src['name']} features:", len(features))

        for f in features:
            placemarks.append(
                feature_to_kml(f, src["name"], src["valuation_tmpl"], src["gis_link_tmpl"])
            )

    # Build a single, replaceable container so GE clears old items
    folder_name = sources[0]["name"] if len(sources) == 1 else "Parcels"
    kml_body = (
        f"<Folder id='{FOLDER_ID}'>"
        f"<open>0</open>"
        f"<styleUrl>#container-hide-children</styleUrl>"
        f"<name>{folder_name} — {len(placemarks)}</name>"
        f"{''.join(placemarks)}"
        f"</Folder>"
    )
    kml_doc = KML_HEADER + kml_body + KML_FOOTER

    # No-cache headers help prevent stale payloads piling up
    return Response(
        kml_doc,
        media_type="application/vnd.google-earth.kml+xml",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

from urllib.parse import quote
from fastapi import Response

@app.get("/menu")
def menu(base: str | None = None):
    base_url = (base or "http://127.0.0.1:8000").rstrip("/")
    links = []
    for src in COUNTY_SOURCES:
        name = src["name"]
        href = f"{base_url}/kml?county={quote(name)}"
        links.append(
            f"<NetworkLink>"
            f"<name>{name}</name>"
            f"<visibility>0</visibility>"
            f"<Link>"
            f"<href>{href}</href>"
            f"<viewRefreshMode>onStop</viewRefreshMode>"
            f"<viewRefreshTime>1.5</viewRefreshTime>" # refresh quickly after you stop panning
            f"<viewFormat>&amp;bbox=[bboxWest],[bboxSouth],[bboxEast],[bboxNorth]"
            f"&amp;eyeAlt=[eyeAltitude]</viewFormat>"
            f"</Link>"
            f"</NetworkLink>"
        )
    kml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        '<name>Parcel-UT Counties</name>'
        f"{''.join(links)}"
        '</Document></kml>'
    )
    return Response(kml, media_type="application/vnd.google-earth.kml+xml")
