"""Fixed 1 km grid: point activation, full clipped-cell scenario, edge-connected groups."""
import math, hashlib
from collections import defaultdict
from shapely.geometry import Point, box, GeometryCollection, mapping
from shapely.ops import unary_union, transform
from pyproj import Transformer

SIZE=1000.0
MODEL_ID="full_grid_1km_v1"
FUEL_LAYER={"GRASS":"GRASS","LEPIRONIA":"LEPIRONIA","M_CAJU_SURFACE_LOWLAND":"M_CAJU",
    "M_CAJU_LEAVES_BARK_LOWLAND":"M_CAJU","PADDY":"PADDY","PEAT":"PEAT"}
TO_METRIC=Transformer.from_crs(4326,32647,always_xy=True)
TO_WGS=Transformer.from_crs(32647,4326,always_xy=True)

def hotspot_point(obs):
    return Point(*TO_METRIC.transform(obs["longitude"],obs["latitude"]))

def in_boundary(obs,boundary):
    return boundary.covers(hotspot_point(obs))

def cell_id(key):
    return f"KK47_E{key[0]}_N{key[1]}"

class GridModel:
    def __init__(self,boundary,layers,parameters,indices=None):
        self.boundary,self.layers,self.parameters=boundary,layers,parameters
        self.indices=indices or {}
        self.geometry={};self.stats={}
        lo_x,lo_y,hi_x,hi_y=boundary.bounds
        for col in range(math.floor(lo_x/SIZE),math.ceil(hi_x/SIZE)):
            for row in range(math.floor(lo_y/SIZE),math.ceil(hi_y/SIZE)):
                geom=box(col*SIZE,row*SIZE,(col+1)*SIZE,(row+1)*SIZE).intersection(boundary)
                if not geom.is_empty and geom.area>1e-6:self.geometry[(col,row)]=geom

    def key_for(self,obs):
        point=hotspot_point(obs)
        if not self.boundary.covers(point):return None
        # Fixed half-open cells: a shared edge goes east/north, never to two cells.
        col,row=math.floor(round(point.x,6)/SIZE),math.floor(round(point.y,6)/SIZE)
        preferred=(col,row)
        if preferred in self.geometry and self.geometry[preferred].distance(point)<1e-6:return preferred
        # At the outer study boundary the preferred cell can have no positive area.
        candidates=[k for k in ((col-1,row),(col,row-1),(col-1,row-1))
            if k in self.geometry and self.geometry[k].distance(point)<1e-6]
        return sorted(candidates)[0] if candidates else None

    def assigned(self,observations):
        cells=defaultdict(list);seen=set()
        for obs in observations:
            if obs["id"] in seen:continue
            seen.add(obs["id"])
            key=self.key_for(obs)
            if key is not None:cells[key].append(obs)
        return dict(cells)

    def cell_stats(self,key):
        if key in self.stats:return self.stats[key]
        geom=self.geometry[key];areas={};surface=[]
        for code,layer in self.layers.items():
            if code in self.indices:
                parts,tree=self.indices[code]
                patches=[geom.intersection(parts[int(i)]) for i in tree.query(geom,predicate="intersects")]
            else:patches=[geom.intersection(layer)]
            areas[code]=sum(g.area for g in patches)/10000
            if code!="PEAT":surface.extend(g for g in patches if not g.is_empty and g.area>0)
        fuels=[]
        for p in self.parameters["fuels"]:
            area=areas[FUEL_LAYER[p["code"]]]
            fuels.append({"code":p["code"],"area_ha":area,"rho":p["rho"],"eta":p["eta"],
                "ef_pm25":p["ef_pm25"],"emission_kg":area*p["rho"]*p["eta"]*p["ef_pm25"],
                "peat_scenario":p["code"]=="PEAT"})
        result={"ground_area_ha":geom.area/10000,
            "surface_unclassified_ha":max(0,(geom.area-unary_union(surface).area)/10000),
            "fuels":fuels,"emission_without_peat_kg":sum(f["emission_kg"] for f in fuels if not f["peat_scenario"]),
            "peat_emission_kg":sum(f["emission_kg"] for f in fuels if f["peat_scenario"]),
            "emission_kg":sum(f["emission_kg"] for f in fuels)}
        self.stats[key]=result
        return result

    def aggregate(self,keys):
        keys=list(keys);stats=[self.cell_stats(k) for k in keys]
        fuels=[]
        for p in self.parameters["fuels"]:
            parts=[next(f for f in s["fuels"] if f["code"]==p["code"]) for s in stats]
            fuels.append({"code":p["code"],"rho":p["rho"],"eta":p["eta"],"ef_pm25":p["ef_pm25"],
                "area_ha":sum(f["area_ha"] for f in parts),"emission_kg":sum(f["emission_kg"] for f in parts),
                "peat_scenario":p["code"]=="PEAT"})
        return {**{k:sum(s[k] for s in stats) for k in ("ground_area_ha","surface_unclassified_ha",
            "emission_without_peat_kg","peat_emission_kg","emission_kg")},"fuels":fuels}

    def groups(self,keys):
        remaining=set(keys);groups=[]
        while remaining:
            seed=min(remaining);remaining.remove(seed);component={seed};queue=[seed]
            while queue:
                c,r=queue.pop()
                for neighbor in ((c-1,r),(c+1,r),(c,r-1),(c,r+1)):
                    if neighbor not in remaining:continue
                    # Contact must include a positive-length edge inside the study boundary.
                    if self.geometry[(c,r)].intersection(self.geometry[neighbor]).length<=1e-6:continue
                    remaining.remove(neighbor);component.add(neighbor);queue.append(neighbor)
            groups.append(sorted(component))
        return groups

    def summarize(self,observations):
        assigned=self.assigned(observations);keys=sorted(assigned);groups=self.groups(keys)
        all_obs=[o for k in keys for o in assigned[k]]
        days=sorted({o["local_date"] for o in all_obs})
        if len(days)>1:raise ValueError("A grid summary must contain one Thai calendar day only")
        day=days[0] if days else ""
        cluster_for={};clusters=[]
        def feature(geom,properties):
            return {"type":"Feature","geometry":mapping(transform(TO_WGS.transform,geom)),"properties":properties}
        for component in groups:
            ids=[cell_id(k) for k in component]
            uid="KG-"+day.replace("-","")+"-"+hashlib.sha256("|".join(ids).encode()).hexdigest()[:8]
            for key in component:cluster_for[key]=uid
            obs=[o for key in component for o in assigned[key]]
            geometry=unary_union([self.geometry[k] for k in component])
            props={**self.aggregate(component),"cluster_id":uid,"cell_ids":ids,"grid_count":len(component),
                "observation_count":len(obs),"sources":sorted({o["source"] for o in obs}),
                "first_acquired_utc":min(o["acquired_utc"] for o in obs),
                "last_acquired_utc":max(o["acquired_utc"] for o in obs),"full_grid_scenario":True}
            clusters.append(feature(geometry,props))
        cells=[]
        for key in keys:
            obs=assigned[key]
            props={**self.cell_stats(key),"grid_id":cell_id(key),"column":key[0],"row":key[1],
                "cluster_id":cluster_for[key],"grid_count":1,"nominal_area_ha":100.0,
                "observation_count":len(obs),"sources":sorted({o["source"] for o in obs}),
                "first_acquired_utc":min(o["acquired_utc"] for o in obs),
                "last_acquired_utc":max(o["acquired_utc"] for o in obs),"full_grid_scenario":True}
            cells.append(feature(self.geometry[key],props))
        geom=unary_union([self.geometry[k] for k in keys]) if keys else GeometryCollection()
        return {**self.aggregate(keys),"observation_count":len(all_obs),"grid_count":len(keys),
            "cluster_count":len(groups),"model_id":MODEL_ID,"full_grid_scenario":True,
            "burned_geometry":mapping(transform(TO_WGS.transform,geom)) if keys else None,
            "cells":{"type":"FeatureCollection","features":cells},
            "clusters":{"type":"FeatureCollection","features":clusters}}

    def hotspots(self,observations):
        features=[]
        for key,records in sorted(self.assigned(observations).items()):
            for obs in records:
                features.append({"type":"Feature","geometry":{"type":"Point","coordinates":[obs["longitude"],obs["latitude"]]},
                    "properties":{**obs,"grid_id":cell_id(key)}})
        return {"type":"FeatureCollection","features":features}

    def grid_features(self):
        return {"type":"FeatureCollection","features":[{"type":"Feature",
            "geometry":mapping(transform(TO_WGS.transform,geom)),
            "properties":{"grid_id":cell_id(key),"column":key[0],"row":key[1],
                "nominal_area_ha":100.0,"area_ha":geom.area/10000}}
            for key,geom in sorted(self.geometry.items())]}
