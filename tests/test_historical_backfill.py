"""Historical dates must be fetched explicitly, with correct product and UTC coverage."""
import sys, tempfile, unittest, io
from pathlib import Path
from datetime import datetime, date
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import fire_pipeline as m
import backfill_firms as b
from shapely.geometry import box
PARAMS=m.load_json(m.ROOT/"config"/"emission_parameters.json")
def observation(day,clock,product="MODIS_SP"):
    return m.normalize({"latitude":"8","longitude":"100","acq_date":day,"acq_time":clock,
        "scan":".1","track":".1","satellite":"Terra"},product)
class HistoricalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        m.write_json(self.root/"config"/"emission_parameters.json",PARAMS)
        m.write_json(self.root/"config"/"spatial_dataset.json",{"bbox_wgs84":[99,7,101,9]})
        m.write_json(self.root/"outputs"/"tables"/"spatial_dataset_audit.json",{"study_area_ha":5,"surface_unclassified_ha":0})
        self.now=datetime(2026,11,13,10,tzinfo=m.UTC)
        self.av={s:{"min_date":"2026-08-01","max_date":"2026-11-13"} for s in m.SOURCES}
        self.av["MODIS_NRT"]["min_date"]="2026-09-01"
        self.av["MODIS_SP"]={"min_date":"2000-11-01","max_date":"2026-08-31"}
        x,y=m.TO_METRIC.transform(100,8)
        pixel=box(x-50,y-50,x+50,y+50)
        self.spatial=(pixel.buffer(100),{k:pixel for k in ("GRASS","LEPIRONIA","M_CAJU","PADDY","PEAT")},{})
    def test_product_by_date_and_sp_normalization(self):
        self.assertEqual(b.product_for("MODIS_NRT","2026-08-15",self.av),"MODIS_SP")
        self.assertEqual(b.product_for("MODIS_NRT","2026-11-13",self.av),"MODIS_NRT")
        self.assertIsNone(b.product_for("MODIS_NRT","1999-01-01",self.av))
        o=observation("2026-08-15","600")
        self.assertEqual(o["source"],"MODIS_NRT")
        self.assertEqual(o["api_product"],"MODIS_SP")
    def test_window_includes_previous_utc_day(self):
        _,_,lo,hi=b.calendar_window("2026-08-15","2026-08-15",date(2026,11,13))
        self.assertEqual(lo.isoformat(),"2026-08-14T17:00:00+00:00")
        self.assertEqual(hi.isoformat(),"2026-08-15T17:00:00+00:00")
        for first,last in [("2026-08-16","2026-08-15"),("2026-01-01","2026-02-02"),("2027-01-01","2027-01-01")]:
            with self.assertRaises(ValueError): b.calendar_window(first,last,date(2026,11,13))
    def test_historical_url_has_start_date_and_response_tag(self):
        seen=[]
        def opener(req,**kw):
            seen.append(req.full_url)
            return io.BytesIO(b"latitude,longitude,acq_date,acq_time,scan,track\n8,100,2026-08-15,600,.1,.1\n")
        records,_=m.fetch_source("test-key","MODIS_SP",[99,7,101,9],2,opener=opener,start_date="2026-08-14")
        self.assertTrue(seen[0].endswith("/2/2026-08-14"))
        self.assertEqual(records[0]["source"],"MODIS_NRT")
    def test_repeat_import_local_day_clipping_and_live_status_retained(self):
        m.bootstrap(self.root)
        target=self.root/"web"/"data"
        m.write_json(target/"status.json",{"state":"ok","sentinel":"live"})
        m.write_json(target/"index.json",{"dates":["2026-11-13"],"daily":[{"date":"2026-11-13","observations":0}]})
        m.write_json(target/"history"/"2026-11-13.json",{"observations":[]})
        status=(target/"status.json").read_bytes()
        records=[observation("2026-08-14","1659"),observation("2026-08-14","1700"),
            observation("2026-08-15","1659"),observation("2026-08-15","1700")]
        def fetch(key,product,*a,**kw): return (records if product=="MODIS_SP" else [],"CSV")
        with patch.object(m,"fetch_availability",return_value=self.av),patch.object(m,"spatial_inputs",return_value=self.spatial),patch.object(m,"fetch_source",side_effect=fetch) as f:
            for _ in range(2): b.backfill("2026-08-15","2026-08-15",self.root,"test",self.now)
            self.assertEqual(f.call_args_list[0].kwargs["start_date"],"2026-08-14")
            day=m.load_json(target/"daily"/"2026-08-15.json")
            self.assertEqual(day["by_source"]["ALL"]["observation_count"],2)
            self.assertEqual(day["data_state"],"ok")
            self.assertEqual((target/"status.json").read_bytes(),status)
            self.assertEqual(m.load_json(target/"index.json")["dates"],["2026-08-15","2026-11-13"])
            historical=(target/"daily"/"2026-08-15.json").read_bytes()
            with patch.object(m,"fetch_source",return_value=([],"CSV")):
                m.collect(self.root,"test",now=self.now)
            self.assertEqual((target/"daily"/"2026-08-15.json").read_bytes(),historical)
    def test_failure_preserves_prior_observations_and_marks_partial(self):
        target=self.root/"web"/"data"
        old=observation("2026-08-15","600")
        m.write_json(target/"history"/"2026-08-15.json",{"observations":[old]})
        def fetch(key,product,*a,**kw):
            if product=="MODIS_SP": raise RuntimeError("service down")
            return [],"CSV"
        with patch.object(m,"fetch_availability",return_value=self.av),patch.object(m,"spatial_inputs",return_value=self.spatial),patch.object(m,"fetch_source",side_effect=fetch):
            b.backfill("2026-08-15","2026-08-15",self.root,"test",self.now)
            day=m.load_json(target/"daily"/"2026-08-15.json")
            self.assertEqual(day["by_source"]["ALL"]["observation_count"],1)
            self.assertEqual(day["source_status"]["MODIS_NRT"]["state"],"error")
            self.assertEqual(day["data_state"],"partial")
    def test_all_fail_does_not_create_empty_day(self):
        m.bootstrap(self.root); target=self.root/"web"/"data"
        before=(target/"index.json").read_bytes()
        with patch.object(m,"fetch_availability",return_value=self.av),patch.object(m,"fetch_source",side_effect=RuntimeError("down")):
            with self.assertRaises(RuntimeError): b.backfill("2026-08-15","2026-08-15",self.root,"test",self.now)
        self.assertEqual((target/"index.json").read_bytes(),before)
        self.assertFalse((target/"daily"/"2026-08-15.json").exists())
if __name__=="__main__": unittest.main()
