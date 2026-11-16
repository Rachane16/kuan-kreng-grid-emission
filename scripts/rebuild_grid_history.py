"""Recalculate every saved day using the full-grid model; no footprint outputs are retained."""
import gzip,json,hashlib
from datetime import datetime
import fire_pipeline as m

def rebuild(root=m.ROOT):
    m.bootstrap(root)
    boundary,layers,indices=m.spatial_inputs(root)
    parameters=m.load_json(root/"config/emission_parameters.json")
    model=m.grid_model(boundary,layers,parameters,indices)
    target=root/"web/data";rows=[];total_obs=0
    parameter_hash=hashlib.sha256(json.dumps(parameters,sort_keys=True).encode()).hexdigest()
    index=m.load_json(target/"index.json")
    for day in sorted(index["dates"]):
        old=m.load_json(target/"daily"/(day+".json"))
        records=m.load_json(target/"history"/(day+".json"))["observations"]
        selections={source:m.summarize(records if source=="ALL" else [o for o in records if o["source"]==source],
            boundary,layers,parameters,indices) for source in ("ALL",)+m.SOURCES}
        payload={k:v for k,v in old.items() if k not in
            ("footprints","pixel_calculation","by_source","geometry_method","parameter_hash")}
        payload.update(model_id=m.MODEL_ID,full_grid_scenario=True,geometry_method=m.GEOMETRY_METHOD,
            recalculated_utc=datetime.now(m.UTC).isoformat(),parameter_hash=parameter_hash,
            by_source=selections,hotspots=m.point_features(records,boundary,layers,parameters,indices))
        m.write_json(target/"daily"/(day+".json"),payload)
        rows.append(m.index_row(day,selections,payload["data_state"],payload["source_status"]))
        total_obs+=selections["ALL"]["observation_count"]
    m.write_json(target/"index.json",{**index,"schema_version":2,"model_id":m.MODEL_ID,
        "daily":[r for r in rows],"dates":[r["date"] for r in rows]})
    grid=model.grid_features()
    with gzip.GzipFile(str(target/"study_grid.geojson.gz"),"wb",mtime=0) as f:
        f.write(json.dumps(grid,separators=(",",":")).encode())
    area=sum(g.area for g in model.geometry.values())/10000
    union=m.unary_union(list(model.geometry.values()))
    audit={"model_id":m.MODEL_ID,"grid_size_m":1000,"metric_crs":"EPSG:32647","origin":[0,0],
        "connectivity":4,"total_cells":len(model.geometry),"study_area_ha":boundary.area/10000,
        "grid_area_ha":area,"symmetric_difference_m2":union.symmetric_difference(boundary).area,
        "cell_area_sum_minus_union_m2":sum(g.area for g in model.geometry.values())-union.area,
        "calendar_days":len(rows),"observations_in_AOI":total_obs,"first_day":rows[0]["date"],"last_day":rows[-1]["date"]}
    assert abs(audit["grid_area_ha"]-audit["study_area_ha"])<1e-6
    assert audit["symmetric_difference_m2"]<.01
    m.write_json(root/"outputs/tables/grid_model_audit.json",audit)
    project=m.load_json(target/"project.json");project["total_grid_cells"]=len(model.geometry)
    m.write_json(target/"project.json",project)
    print(json.dumps(audit),flush=True)
    for day in ("2026-08-15","2026-09-07"):
        summary=m.load_json(target/"daily"/(day+".json"))["by_source"]["ALL"]
        print(day,json.dumps({k:summary[k] for k in ("observation_count","grid_count","cluster_count","ground_area_ha","emission_kg")}))
if __name__=="__main__":rebuild()
