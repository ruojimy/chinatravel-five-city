"""Synthetic calibration only; never writes real human-rating records."""
from pathlib import Path
import unittest, tempfile, importlib.util, csv, json, contextlib, io

path=Path(__file__).resolve().parents[1]/'scripts/p7_analyze_preferences.py'
spec=importlib.util.spec_from_file_location('p7_for_calibration',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class AnalysisCalibration(unittest.TestCase):
    def run_case(self,votes,raters=3):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);module.PACKETS=root/'synthetic.csv';module.PRIVATE=root/'absent.json';module.OUT=root/'result'
            fields=['pair_id']+[f'r{i}_choice' for i in range(1,raters+1)]
            with module.PACKETS.open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
                for index,row in enumerate(votes):
                    writer.writerow(dict(pair_id=f'synthetic_{index}',**{f'r{i+1}_choice':v for i,v in enumerate(row)}))
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(module.main(),0)
            return json.loads((module.OUT/'preference_analysis.json').read_text(encoding='utf-8'))

    def test_empty_annotations_stay_empty(self):
        report=self.run_case([[],[]])
        self.assertEqual(report['coverage']['ratings_total'],0)
        self.assertIsNone(report['human_human']['fleiss_kappa'])

    def test_partial_and_complete_items_are_not_mixed(self):
        report=self.run_case([['A 更好'],['B 更好']*3])
        self.assertEqual(report['coverage']['ratings_total'],4)
        self.assertEqual(report['human_human']['n_pairs_in_kappa'],1)
        self.assertEqual(report['human_human']['observed_pairwise_agreement'],1.0)

    def test_known_balanced_kappa(self):
        report=self.run_case([['A 更好','A 更好','B 更好'],['A 更好','B 更好','B 更好'],['差不多']*3])
        # Pbar=5/9, Pe=1/3, so kappa=1/3.
        self.assertEqual(report['human_human']['fleiss_kappa'],0.3333)
        self.assertEqual(report['human_human']['n_pairs_in_kappa'],3)

    def test_single_rater_has_no_inter_rater_metric(self):
        report=self.run_case([['A 更好']],raters=1)
        self.assertIsNone(report['human_human']['observed_pairwise_agreement'])
        self.assertIsNone(report['human_human']['fleiss_kappa'])

    def test_mixed_count_table_refused(self):
        with self.assertRaises(ValueError):module.fleiss_kappa([[1,1,1,0],[1,0,0,0]])

if __name__=='__main__':unittest.main()
