"""FIRMS point collector and independent daily full-grid PM2.5 scenarios."""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import time
from datetime import datetime, date, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from pyproj import Transformer
from shapely.geometry import shape, mapping, box, GeometryCollection
from shapely.ops import transform, unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree
from grid_model import GridModel, in_boundary, hotspot_point, MODEL_ID

ROOT = Path(__file__).resolve().parents[1]
BANGKOK = timezone(timedelta(hours=7), "Asia/Bangkok")
UTC = timezone.utc
SOURCES = ("MODIS_NRT", "VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")
TO_METRIC = Transformer.from_crs(4326, 32647, always_xy=True)
TO_WGS = Transformer.from_crs(32647, 4326, always_xy=True)
FUEL_LAYER = {"GRASS":"GRASS", "LEPIRONIA":"LEPIRONIA",
    "M_CAJU_SURFACE_LOWLAND":"M_CAJU", "M_CAJU_LEAVES_BARK_LOWLAND":"M_CAJU",
    "PADDY":"PADDY", "PEAT":"PEAT"}
GEOMETRY_METHOD = "Fixed EPSG:32647 1000 m grid, origin (0,0); point activation, full AOI-clipped cell, 4-edge groups"
SENSOR_LABELS = {"ALL":"ทุกดาวเทียม", "MODIS_NRT":"MODIS Terra/Aqua", "VIIRS_SNPP_NRT":"VIIRS S-NPP",
                 "VIIRS_NOAA20_NRT":"VIIRS NOAA-20", "VIIRS_NOAA21_NRT":"VIIRS NOAA-21"}

def load_json(path):
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(",",":"), allow_nan=False)+"\n", encoding="utf-8")
    temp.replace(path)

def spatial_inputs(root=ROOT):
    def packed(name):
        p = root/"data"/"processed"/"spatial"/name
        return p.with_suffix(p.suffix+".gz") if p.with_suffix(p.suffix+".gz").exists() else p
    boundary_data = load_json(packed("study_area.geojson"))
    landuse_data = load_json(packed("landuse_layers.geojson"))
    project = lambda g: transform(TO_METRIC.transform, shape(g))
    boundary = unary_union([project(f["geometry"]) for f in boundary_data["features"]])
    layers = {f["properties"]["landuse_code"]: project(f["geometry"]) for f in landuse_data["features"]}
    # Index individual parts of large multipolygons for fast, exact intersections.
    indices = {}
    for code, geom in layers.items():
        parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        indices[code] = (parts, STRtree(parts))
    return boundary, layers, indices

def normalize(row, source):
    api_product=source
    source=source.replace("_SP","_NRT")
    if source not in SOURCES:
        raise ValueError("Unsupported source")
    lat, lon = float(row["latitude"]), float(row["longitude"])
    if not math.isfinite(lat+lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid coordinate")
    clock = str(row["acq_time"]).strip()
    # CSV clock is HHMM, frequently with leading zero omitted.
    if not clock.isdigit() or len(clock)>4:
        raise ValueError("Invalid acquisition time")
    clock = clock.zfill(4)
    timestamp = datetime.strptime(str(row["acq_date"]).strip()+clock, "%Y-%m-%d%H%M").replace(tzinfo=UTC)
    def optional_size(value):
        try:
            value=float(value)
            return value if math.isfinite(value) and value>0 else None
        except (TypeError,ValueError):return None
    scan,track=optional_size(row.get("scan")),optional_size(row.get("track"))
    satellite = str(row.get("satellite") or source).strip()
    uid = hashlib.sha256(f"{source}|{satellite}|{timestamp.isoformat()}|{lat:.6f}|{lon:.6f}".encode()).hexdigest()[:24]
    frp = row.get("frp")
    try:
        frp = float(frp) if frp not in ("",None) else None
        if frp is not None and not math.isfinite(frp): frp = None
    except (TypeError,ValueError):
        frp = None
    return {"id":uid, "source":source, "api_product":api_product, "satellite":satellite, "latitude":lat, "longitude":lon,
        "acquired_utc":timestamp.isoformat(), "local_date":timestamp.astimezone(BANGKOK).date().isoformat(),
        "scan_km":scan, "track_km":track, "confidence":str(row.get("confidence","")).strip(),
        "frp_mw":frp, "daynight":str(row.get("daynight","")), "version":str(row.get("version",""))}

def parse_csv(text, source):
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    required = {"latitude","longitude","acq_date","acq_time"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("FIRMS response has no expected CSV header")
    result, rejected = {}, 0
    for row in reader:
        if not any(row.values()): continue
        try:
            obs = normalize(row,source)
            result[obs["id"]] = obs
        except (ValueError,KeyError,TypeError):
            rejected += 1
    if rejected:
        # Do not silently replace an archive with an incompletely parsed source.
        raise ValueError(f"Invalid rows in FIRMS response: {rejected}")
    return list(result.values())

def fetch_source(key, source, bbox, days=3, opener=urlopen, sleeper=time.sleep, start_date=None):
    if days not in range(1,6): raise ValueError("day_range must be 1..5")
    area = ",".join(f"{n:.7f}" for n in bbox)
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{area}/{days}"
    if start_date is not None:
        url+="/"+date.fromisoformat(str(start_date)).isoformat()
    last = "Network error"
    for attempt in range(3):
        try:
            with opener(Request(url, headers={"User-Agent":"KuanKreng-Emission-Dashboard/1.1"}), timeout=60) as response:
                content = response.read().decode("utf-8-sig")
            return parse_csv(content, source), content
        except HTTPError as exc:
            last = f"FIRMS HTTP {exc.code}" # Never include request URLs or keys.
            if exc.code not in (429,500,502,503,504): break
        except (URLError,TimeoutError,OSError):
            last = "FIRMS network request failed"
        except (ValueError,UnicodeError):
            last = "FIRMS returned invalid CSV or a key/service error"
            break
        if attempt < 2: sleeper(2**attempt)
    raise RuntimeError(last)

def fetch_availability(key, opener=urlopen):
    """Only return service metadata; never expose request URLs or credentials."""
    url=f"https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/{key}/ALL"
    try:
        with opener(Request(url, headers={"User-Agent":"KuanKreng-Emission-Dashboard/1.1"}), timeout=45) as response:
            reader=csv.DictReader(io.StringIO(response.read().decode("utf-8-sig")))
            if not {"data_id","min_date","max_date"}.issubset(reader.fieldnames or []):
                raise ValueError("Invalid metadata")
            rows={r["data_id"]:{"min_date":date.fromisoformat(r["min_date"]).isoformat(),
                                  "max_date":date.fromisoformat(r["max_date"]).isoformat()} for r in reader}
            if not all(source in rows for source in SOURCES): raise ValueError("Missing metadata")
            return rows
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,UnicodeError,KeyError):
        raise RuntimeError("FIRMS availability check failed") from None

_MODEL_CACHE={}
def grid_model(boundary,layers,parameters,indices=None):
    key=(id(boundary),id(layers),id(parameters))
    if _MODEL_CACHE.get("key")!=key:
        _MODEL_CACHE.clear()
        _MODEL_CACHE.update(key=key,model=GridModel(boundary,layers,parameters,indices))
    return _MODEL_CACHE["model"]

def summarize(observations,boundary,layers,parameters,indices=None):
    return grid_model(boundary,layers,parameters,indices).summarize(observations)

def point_features(observations,boundary,layers=None,parameters=None,indices=None):
    if layers is None or parameters is None:raise ValueError("Grid model inputs are required")
    return grid_model(boundary,layers,parameters,indices).hotspots(observations)


def index_row(day, selections, data_state, source_status=None):
    def compact(summary):
        return {k:summary[k] for k in ("observation_count","ground_area_ha","emission_kg",
            "emission_without_peat_kg","peat_emission_kg","fuels","grid_count","cluster_count")}
    total=selections["ALL"]
    return {"date":day,"observations":total["observation_count"],"area_ha":total["ground_area_ha"],
        "emission_kg":total["emission_kg"],"emission_without_peat_kg":total["emission_without_peat_kg"],
        "peat_emission_kg":total["peat_emission_kg"],"data_state":data_state,
        "grid_count":total["grid_count"],"cluster_count":total["cluster_count"],
        "by_source":{source:compact(summary) for source,summary in selections.items()},
        "source_status":{source:info["state"] for source,info in (source_status or {}).items()}}


def bootstrap(root=ROOT):
    target=root/"web"/"data"
    if not (target/"index.json").exists():
        write_json(target/"index.json",{"schema_version":2,"model_id":MODEL_ID,"timezone":"Asia/Bangkok","dates":[],"daily":[]})
    if not (target/"status.json").exists():
        write_json(target/"status.json",{"state":"awaiting_key","last_attempt_utc":None,"last_success_utc":None,
            "message":"ยังไม่ได้เชื่อม FIRMS MAP_KEY", "sources":{s:{"state":"not_configured"} for s in SOURCES}})
    write_json(target/"parameters.json",load_json(root/"config"/"emission_parameters.json"))
    spatial=load_json(root/"config"/"spatial_dataset.json")
    audit=load_json(root/"outputs"/"tables"/"spatial_dataset_audit.json")
    write_json(target/"project.json",{"name":"Kuan Kreng 1 km Grid Fire & Emission","timezone":"Asia/Bangkok",
        "study_area_ha":audit["study_area_ha"],"bbox":spatial["bbox_wgs84"],
        "sources":SENSOR_LABELS,"geometry_method":GEOMETRY_METHOD,
        "daily_policy":"independent_daily_fuel_scenario","peat_depth_cm":10,
        "layer_overlap_policy":"intersect_each_layer_independently",
        "surface_unclassified_ha":audit["surface_unclassified_ha"],
        "model_id":MODEL_ID,"grid_size_m":1000,"grid_origin_utm":[0,0],"connectivity":4,"full_grid_scenario":True})

def collect(root=ROOT, key=None, days=3, now=None):
    bootstrap(root)
    target=root/"web"/"data"
    now = now or datetime.now(UTC)
    stamp=now.isoformat()
    previous_status=load_json(target/"status.json")
    key=(key or os.environ.get("FIRMS_MAP_KEY") or "").strip()
    if not key:
        write_json(target/"status.json",{**previous_status,"state":"awaiting_key",
            "last_attempt_utc":stamp,"message":"ยังไม่ได้ตั้งค่า FIRMS_MAP_KEY"})
        return 2
    project=load_json(root/"config"/"spatial_dataset.json")
    bbox=project["bbox_wgs84"]
    # Fetch a padded bbox, then retain only point centers inside the study boundary.
    query_bbox=[max(-180,bbox[0]-.1),max(-90,bbox[1]-.1),min(180,bbox[2]+.1),min(90,bbox[3]+.1)]
    history=target/"history"
    all_observations={}
    for path in sorted(history.glob("*.json")):
        for o in load_json(path)["observations"]: all_observations[o["id"]]=o
    start=datetime.combine(now.date()-timedelta(days=days-1),datetime.min.time(),tzinfo=UTC)
    stop=datetime.combine(now.date()+timedelta(days=1),datetime.min.time(),tzinfo=UTC)
    statuses={}
    successes=[]
    try:
        availability=fetch_availability(key)
        availability_error=None
    except RuntimeError as exc:
        availability={}
        availability_error=str(exc)
    raw_path=root/"data"/"raw"/"firms"/now.strftime("%Y%m%dT%H%M%SZ")
    for source in SOURCES:
        try:
            available=availability.get(source,{})
            if available.get("max_date","9999-12-31") < start.date().isoformat():
                statuses[source]={"state":"unavailable",**available,
                    "message":"NASA has no data within this query window","attempt_utc":stamp}
                continue
            records, raw=fetch_source(key,source,query_bbox,days)
            # Replace this successful source's full queried UTC window to handle revised/removed detections.
            all_observations={k:o for k,o in all_observations.items()
                if not (o["source"]==source and start<=datetime.fromisoformat(o["acquired_utc"])<stop)}
            for o in records:
                if start<=datetime.fromisoformat(o["acquired_utc"])<stop:
                    all_observations[o["id"]]=o
            raw_path.mkdir(parents=True,exist_ok=True)
            (raw_path/(source+".csv")).write_text(raw,encoding="utf-8")
            fresh=available.get("max_date","") >= now.date().isoformat()
            statuses[source]={"state":"ok" if fresh else "unavailable","count":len(records),
                "updated_utc":stamp,**available}
            if not available:
                statuses[source].update(state="unavailable",message=availability_error)
            successes.append(source)
        except RuntimeError as exc:
            old=previous_status.get("sources",{}).get(source,{})
            statuses[source]={**old,"state":"error","message":str(exc),"attempt_utc":stamp}
    if not successes:
        write_json(target/"status.json",{"state":"error","last_attempt_utc":stamp,
            "last_success_utc":previous_status.get("last_success_utc"),"sources":statuses,
            "message":"ดึงข้อมูลไม่สำเร็จ แสดงข้อมูลที่บันทึกไว้ล่าสุด"})
        return 2
    boundary,layers,indices=spatial_inputs(root)
    parameters=load_json(root/"config"/"emission_parameters.json")
    parameter_hash=hashlib.sha256(json.dumps(parameters,sort_keys=True).encode()).hexdigest()
    boundary_check=prep(boundary)
    grouped={}
    for o in all_observations.values():
        if in_boundary(o,boundary):
            grouped.setdefault(o["local_date"],[]).append(o)
    index=load_json(target/"index.json")
    dates=set(index.get("dates",[]))|set(grouped)
    local_day=start.astimezone(BANGKOK).date()
    while local_day<=now.astimezone(BANGKOK).date():
        dates.add(local_day.isoformat())
        local_day+=timedelta(days=1)
    previous_daily={d["date"]:d for d in index.get("daily",[])}
    all_sources_current=all(statuses.get(s,{}).get("state")=="ok" for s in SOURCES)
    for day in sorted(dates):
        # Rebuild days in current query plus any days that already have saved observations.
        if day < start.astimezone(BANGKOK).date().isoformat():
            continue
        records=sorted(grouped.get(day,[]),key=lambda o:(o["acquired_utc"],o["source"],o["id"]))
        day_start=datetime.combine(date.fromisoformat(day),datetime.min.time(),tzinfo=BANGKOK).astimezone(UTC)
        complete_window=start<=day_start
        if not records and not complete_window and day not in previous_daily:
            continue # A partial UTC window does not establish an empty Thai calendar day.
        selections={}
        for source in ("ALL",)+SOURCES:
            subset=records if source=="ALL" else [o for o in records if o["source"]==source]
            selections[source]=summarize(subset,boundary,layers,parameters,indices)
        payload={"date":day,"timezone":"Asia/Bangkok","generated_utc":stamp,"parameter_hash":parameter_hash,
            "geometry_method":GEOMETRY_METHOD,"daily_policy":"independent_daily_fuel_scenario",
            "window_start_utc":start.isoformat(),"calendar_day_fully_queried":complete_window,
            "source_status":statuses,"data_state":"ok" if all_sources_current else "partial",
            "model_id":MODEL_ID,"full_grid_scenario":True,"by_source":selections,"hotspots":point_features(records,boundary,layers,parameters,indices)}
        write_json(target/"daily"/(day+".json"),payload)
        write_json(history/(day+".json"),{"date":day,"observations":records})
        total=selections["ALL"]
        previous_daily[day]=index_row(day,selections,payload["data_state"],statuses)
    rows=[previous_daily[d] for d in sorted(previous_daily)]
    write_json(target/"index.json",{"schema_version":2,"model_id":MODEL_ID,"timezone":"Asia/Bangkok",
        "generated_utc":stamp,"dates":sorted(previous_daily),"daily":rows})
    state="ok" if all_sources_current else "partial"
    write_json(target/"status.json",{"state":state,"last_attempt_utc":stamp,
        "last_success_utc":stamp if state=="ok" else previous_status.get("last_success_utc"),
        "last_partial_success_utc":stamp,"sources":statuses,
        "message":"อัปเดตครบทุกแหล่ง" if state=="ok" else "บางแหล่งยังไม่มีข้อมูลใหม่หรือดึงไม่สำเร็จ โปรดดูสถานะแยกดาวเทียม"})
    print(f"FIRMS: {len(successes)}/{len(SOURCES)} sources; {len(rows)} daily records. No credentials logged.")
    return 0

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=("bootstrap","collect"))
    parser.add_argument("--days",type=int,choices=range(1,6),default=3)
    parser.add_argument("--prompt-key",action="store_true")
    args=parser.parse_args()
    if args.command=="bootstrap":
        bootstrap(); print("Prepared honest empty dashboard state."); return 0
    key=None
    if args.prompt_key:
        import getpass
        key=getpass.getpass("FIRMS MAP_KEY (hidden): ")
    return collect(key=key,days=args.days)

if __name__=="__main__":
    sys.exit(main())
