import unittest,sys,io
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import fire_pipeline as m
class PipelineIOTests(unittest.TestCase):
    def test_point_csv_needs_no_scan_track(self):
        csv="latitude,longitude,acq_date,acq_time\n8,100,2026-08-15,1800\n"
        rows=m.parse_csv(csv,"MODIS_NRT")
        self.assertEqual(rows[0]["local_date"],"2026-08-16");self.assertIsNone(rows[0]["scan_km"])
        self.assertEqual(len(m.parse_csv(csv+csv.splitlines()[1]+"\n","MODIS_NRT")),1)
    def test_bad_response_rejected(self):
        with self.assertRaises(ValueError):m.parse_csv("Invalid MAP_KEY","MODIS_NRT")
    def test_network_error_is_sanitized(self):
        def fail(*a,**kw):raise m.URLError("https://example/secret-key")
        with self.assertRaises(RuntimeError) as r:m.fetch_source("secret-key","MODIS_NRT",[99,7,101,9],opener=fail,sleeper=lambda _:None)
        self.assertNotIn("secret-key",str(r.exception))
if __name__=="__main__":unittest.main()
