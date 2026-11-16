"""Historical FIRMS import. Dates are Thai calendar days, NRT/SP selected by availability."""
import argparse, hashlib, json, os, sys
from datetime import date, datetime, timedelta
import fire_pipeline as m
from shapely.prepared import prep

def calendar_window(first,last,today=None):
    first,last=date.fromisoformat(str(first)),date.fromisoformat(str(last))
    today=today or datetime.now(m.BANGKOK).date()
    if not first<=last<=today or (last-first).days>30:
        raise ValueError("Choose 1..31 past/current Thai calendar days in ascending order")
    start=datetime.combine(first,datetime.min.time(),tzinfo=m.BANGKOK).astimezone(m.UTC)
    end=datetime.combine(last+timedelta(days=1),datetime.min.time(),tzinfo=m.BANGKOK).astimezone(m.UTC)
    return first,last,start,end

def product_for(source,day,available):
    for product in (source.replace("_NRT","_SP"),source):
        a=available.get(product,{})
        if a.get("min_date","9999-12-31")<=day<=a.get("max_date","0001-01-01"): return product
    return None

def backfill(first,last,root=m.ROOT,key=None,now=None):
    now=now or datetime.now(m.UTC)
    first,last,start,end=calendar_window(first,last,now.astimezone(m.BANGKOK).date())
    key=(key or os.environ.get("FIRMS_MAP_KEY") or "").strip()
    if not key: raise RuntimeError("FIRMS_MAP_KEY is not configured")
    m.bootstrap(root)
    available=m.fetch_availability(key)
    target=root/"web"/"data"
    bbox=m.load_json(root/"config"/"spatial_dataset.json")["bbox_wgs84"]
    bbox=[bbox[0]-.1,bbox[1]-.1,bbox[2]+.1,bbox[3]+.1]
    requested=[(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)]
    utc_days=[(start.date()+timedelta(days=i)).isoformat() for i in range((end.date()-start.date()).days+1)]
    existing={}
    for day in requested:
        path=target/"history"/(day+".json")
        if path.exists(): existing.update({o["id"]:o for o in m.load_json(path)["observations"]})
    coverage,fetched={},{}
    raw_path=root/"data"/"raw"/"firms"/("historical_"+now.strftime("%Y%m%dT%H%M%SZ"))
    for source in m.SOURCES:
        plan=[(day,product_for(source,day,available)) for day in utc_days]
        pos=0
        while pos<len(plan):
            day,product=plan[pos]
            if not product:
                coverage[(source,day)]={"state":"unavailable"}
                pos+=1
                continue
            group=[day]
            while pos+len(group)<len(plan) and len(group)<5 and plan[pos+len(group)][1]==product:
                group.append(plan[pos+len(group)][0])
            try:
                records,raw=m.fetch_source(key,product,bbox,len(group),start_date=day)
                raw_path.mkdir(parents=True,exist_ok=True)
                (raw_path/(product+"_"+day+".csv")).write_text(raw,encoding="utf-8")
                for d in group: coverage[(source,d)]={"state":"ok","api_product":product}
                lo=datetime.combine(date.fromisoformat(group[0]),datetime.min.time(),tzinfo=m.UTC)
                hi=datetime.combine(date.fromisoformat(group[-1])+timedelta(days=1),datetime.min.time(),tzinfo=m.UTC)
                existing={uid:o for uid,o in existing.items() if not
                    (o["source"]==source and lo<=datetime.fromisoformat(o["acquired_utc"])<hi)}
                for o in records:
                    if not lo<=datetime.fromisoformat(o["acquired_utc"])<hi: continue
                    fetched[o["id"]]=o
                    if first.isoformat()<=o["local_date"]<=last.isoformat(): existing[o["id"]]=o
            except RuntimeError as exc:
                for d in group: coverage[(source,d)]={"state":"error","api_product":product,"message":str(exc)}
            pos+=len(group)
    if not any(c["state"]=="ok" for c in coverage.values()):
        raise RuntimeError("Historical import failed for all sources; saved data retained")
    boundary,layers,indices=m.spatial_inputs(root)
    inside=prep(boundary)
    def in_aoi(o): return m.in_boundary(o,boundary)
    observations=[o for o in existing.values() if in_aoi(o)]
    parameters=m.load_json(root/"config"/"emission_parameters.json")
    parameter_hash=hashlib.sha256(json.dumps(parameters,sort_keys=True).encode()).hexdigest()
    index=m.load_json(target/"index.json")
    rows={r["date"]:r for r in index.get("daily",[])}
    written=[]
    for day in requested:
        lo=datetime.combine(date.fromisoformat(day),datetime.min.time(),tzinfo=m.BANGKOK).astimezone(m.UTC)
        hi=lo+timedelta(days=1)
        needed=[lo.date().isoformat(),hi.date().isoformat()]
        statuses={}
        for source in m.SOURCES:
            checks=[coverage[(source,d)] for d in needed]
            states=[c["state"] for c in checks]
            state="ok" if all(s=="ok" for s in states) else "partial" if "ok" in states else "error" if "error" in states else "unavailable"
            statuses[source]={"state":state,"api_products":sorted({c["api_product"] for c in checks if "api_product" in c}),
                "query_start_utc":lo.isoformat(),"query_end_utc":hi.isoformat(),
                "updated_utc":now.isoformat(),"utc_days":dict(zip(needed,checks))}
        if not any(coverage[(s,d)]["state"]=="ok" for s in m.SOURCES for d in needed): continue
        records=sorted([o for o in observations if o["local_date"]==day],key=lambda o:(o["acquired_utc"],o["source"],o["id"]))
        selections={s:m.summarize(records if s=="ALL" else [o for o in records if o["source"]==s],
            boundary,layers,parameters,indices) for s in ("ALL",)+m.SOURCES}
        complete=all(c["state"]=="ok" for c in statuses.values())
        payload={"date":day,"timezone":"Asia/Bangkok","collection_mode":"historical",
            "generated_utc":now.isoformat(),"parameter_hash":parameter_hash,"geometry_method":m.GEOMETRY_METHOD,
            "daily_policy":"independent_daily_fuel_scenario","window_start_utc":lo.isoformat(),
            "window_end_utc":hi.isoformat(),"calendar_day_fully_queried":complete,
            "source_status":statuses,"data_state":"ok" if complete else "partial",
            "model_id":m.MODEL_ID,"full_grid_scenario":True,"by_source":selections,"hotspots":m.point_features(records,boundary,layers,parameters,indices)}
        m.write_json(target/"daily"/(day+".json"),payload)
        m.write_json(target/"history"/(day+".json"),{"date":day,"observations":records})
        total=selections["ALL"]
        rows[day]=m.index_row(day,selections,payload["data_state"],statuses)
        written.append(day)
        print(f"Historical Thai day {day}: {total['observation_count']} detections; {total['ground_area_ha']:.4f} ha; {payload['data_state']}")
    m.write_json(target/"index.json",{**index,"generated_utc":now.isoformat(),"dates":sorted(rows),
        "daily":[rows[d] for d in sorted(rows)]})
    comparison=[]
    for day in utc_days:
        for source in m.SOURCES:
            batch=[o for o in fetched.values() if o["source"]==source and o["acquired_utc"][:10]==day]
            aoi=[o for o in batch if in_aoi(o)]
            comparison.append({"utc_date":day,"source":source,"api_product":coverage[(source,day)].get("api_product"),
                "state":coverage[(source,day)]["state"],"query_bbox_count":len(batch),"study_area_count":len(aoi),
                "thai_dates":sorted({o["local_date"] for o in aoi})})
    m.write_json(target/"backfill_status.json",{"state":"ok" if all(c["state"]=="ok" for c in coverage.values()) else "partial",
        "generated_utc":now.isoformat(),"requested_thai_dates":requested,"written_dates":written,
        "comparison_utc":comparison,"note":"FIRMS dates are UTC; dashboard dates are Asia/Bangkok. Only point centers inside the AOI activate full 1 km cells."})
    return 0 if written else 2

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start-date",required=True)
    p.add_argument("--end-date")
    p.add_argument("--prompt-key",action="store_true")
    a=p.parse_args()
    key=None
    if a.prompt_key:
        import getpass
        key=getpass.getpass("FIRMS MAP_KEY (hidden): ")
    try: return backfill(a.start_date,a.end_date or a.start_date,key=key)
    except (ValueError,RuntimeError) as exc:
        print(str(exc),file=sys.stderr); return 2
if __name__=="__main__": sys.exit(main())
