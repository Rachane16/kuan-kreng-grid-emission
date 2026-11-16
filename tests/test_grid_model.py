"""Full-grid scenario: unique cells, clipped AOI, point inclusion, connectivity and emission conservation."""
import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import fire_pipeline as m
from grid_model import GridModel,TO_WGS
from shapely.geometry import box,MultiPolygon
P=m.load_json(m.ROOT/"config/emission_parameters.json")
X,Y=600000,870000
def obs(x,y,uid="a",source="MODIS_NRT",day="2026-08-15"):
    lon,lat=TO_WGS.transform(x,y)
    return {"id":uid,"source":source,"longitude":lon,"latitude":lat,"local_date":day,
        "acquired_utc":day+"T06:00:00+00:00","scan_km":.1,"track_km":.1}
def inputs(boundary):
    return {k:boundary for k in ("GRASS","LEPIRONIA","M_CAJU","PADDY","PEAT")}
class GridTests(unittest.TestCase):
    def setUp(self):
        self.boundary=box(X,Y,X+3000,Y+3000)
        self.model=GridModel(self.boundary,inputs(self.boundary),P)
    def test_single_point_activates_full_100_ha(self):
        r=self.model.summarize([obs(X+100,Y+100)])
        self.assertEqual(r["grid_count"],1);self.assertAlmostEqual(r["ground_area_ha"],100)
        self.assertAlmostEqual(r["peat_emission_kg"],100*210*.54*3.02)
        self.assertEqual(len(r["fuels"]),6)
        self.assertAlmostEqual(r["emission_kg"],sum(f["emission_kg"] for f in r["fuels"]))
    def test_repeated_points_and_sensors_do_not_increase_area(self):
        a=obs(X+100,Y+100);b=obs(X+200,Y+200,"b","VIIRS_NOAA20_NRT")
        r=self.model.summarize([a,b,a])
        self.assertEqual(r["observation_count"],2);self.assertEqual(r["grid_count"],1)
        self.assertAlmostEqual(r["ground_area_ha"],100)
    def test_scan_track_is_not_used_for_area(self):
        a=obs(X+100,Y+100)
        b={**a,"scan_km":10,"track_km":10}
        self.assertEqual(self.model.summarize([a])["ground_area_ha"],self.model.summarize([b])["ground_area_ha"])
    def test_edge_cells_are_clipped(self):
        boundary=box(X+500,Y,X+1500,Y+1000)
        model=GridModel(boundary,inputs(boundary),P)
        r=model.summarize([obs(X+600,Y+100)])
        self.assertAlmostEqual(r["ground_area_ha"],50)
    def test_point_outside_AOI_does_not_activate_same_cell(self):
        boundary=box(X+500,Y,X+1500,Y+1000)
        model=GridModel(boundary,inputs(boundary),P)
        self.assertEqual(model.summarize([obs(X+100,Y+100)])["grid_count"],0)
    def test_positive_edge_groups_and_no_hole_filling(self):
        points=[obs(X+100,Y+100),obs(X+1100,Y+100,"b"),obs(X+1100,Y+1100,"c")]
        r=self.model.summarize(points)
        self.assertEqual(r["cluster_count"],1);self.assertEqual(r["grid_count"],3)
        self.assertAlmostEqual(r["ground_area_ha"],300)
        group=r["clusters"]["features"][0]["properties"]
        self.assertEqual(group["grid_count"],3);self.assertAlmostEqual(group["emission_kg"],r["emission_kg"])
        self.assertAlmostEqual(sum(f["properties"]["ground_area_ha"] for f in r["cells"]["features"]),300)
    def test_diagonal_cells_stay_separate(self):
        r=self.model.summarize([obs(X+100,Y+100),obs(X+1100,Y+1100,"b")])
        self.assertEqual(r["cluster_count"],2)
    def test_gap_in_study_area_does_not_join_adjacent_indices(self):
        boundary=MultiPolygon([box(X,Y,X+950,Y+1000),box(X+1050,Y,X+2000,Y+1000)])
        model=GridModel(boundary,inputs(boundary),P)
        self.assertEqual(model.summarize([obs(X+100,Y+100),obs(X+1100,Y+100,"b")])["cluster_count"],2)
    def test_gridline_point_assigned_once(self):
        r=self.model.summarize([obs(X+1000,Y+1500)])
        self.assertEqual(r["grid_count"],1)
        self.assertEqual(r["cells"]["features"][0]["properties"]["column"],601)
    def test_independent_days_repeat_starting_fuel(self):
        a=self.model.summarize([obs(X+100,Y+100)])
        b=self.model.summarize([obs(X+100,Y+100,day="2026-08-16")])
        self.assertEqual(a["emission_kg"],b["emission_kg"])
        with self.assertRaises(ValueError):self.model.summarize([obs(X+100,Y+100),obs(X+100,Y+100,"b",day="2026-08-16")])
    def test_point_geojson_and_stable_ids(self):
        a=obs(X+100,Y+100)
        points=self.model.hotspots([a])
        self.assertEqual(points["features"][0]["geometry"]["type"],"Point")
        self.assertEqual(points["features"][0]["properties"]["grid_id"],"KK47_E600_N870")
        self.assertEqual(len(self.model.grid_features()["features"]),9)
if __name__=="__main__":unittest.main()
