import sys, unittest, tempfile, json, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from shorttrip.source_identity import language_aliases, verify_historical_identity


class SourceNames(unittest.TestCase):
    def test_branch_alias_is_literal_and_brand_is_ignored(self):
        row = {'names': {'primary': '某某餐厅南京店', 'rules': [
            {'variant': 'language', 'language': 'en', 'value': 'A Nanjing Branch'}]},
            'brand': {'names': {'primary': 'A'}}}
        aliases = language_aliases(row)
        self.assertIn('ananjingbranch', aliases)
        self.assertNotIn('a', aliases)
        self.assertNotIn('某某餐厅', aliases)

    def test_qualified_and_nonlanguage_aliases_are_excluded(self):
        rules = [dict(variant='language', language='en', value='Old', between=['2020','2021']),
                 dict(variant='language', language='en', value='Regional', perspectives=['US']),
                 dict(variant='alternate', value='Informal'),
                 dict(variant='language', language='en', value='Current', perspectives=None)]
        self.assertEqual(set(language_aliases({'names': {'rules': rules}})), {'current'})

    def fixture(self):
        return ({'name':'A Branch','real_city':'Nanjing','longitude':'118.78','latitude':'32.04'},
                {'record_id':'overture:id','name':'A Branch','city_slug':'nanjing','data':{'lon':118.78,'lat':32.04}})

    def test_numeric_namespace_or_unknown_method_never_bypasses_checks(self):
        row, record = self.fixture()
        for method in ('numeric_id_and_near_coordinate_candidate_namespace_not_verified','unknown',None):
            with self.assertRaisesRegex(ValueError,'Unapproved historical identity'):
                verify_historical_identity(row,record,{'method':method},Path('.'))

    def test_exact_name_requires_city_and_nearby_finite_coordinates(self):
        row, record = self.fixture(); basis={'method':'exact_name_city_unique_near_coordinate_candidate'}
        self.assertFalse(verify_historical_identity(row,record,basis,Path('.'))['entity_verified'])
        for change in ({'name':'Other'}, {'real_city':'Shanghai'}, {'longitude':'120'}, {'latitude':'nan'}):
            with self.assertRaises(ValueError): verify_historical_identity({**row,**change},record,basis,Path('.'))

    def test_alias_requires_retained_same_entity_row_and_exact_literal_value(self):
        row, record = self.fixture(); record['name']='某某南京店'
        original={'id':'id','names':{'primary':record['name'],'rules':[{'variant':'language','language':'en','value':row['name']}]}}
        raw=json.dumps(original,ensure_ascii=False).encode(); digest=hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'results/p17_continuous/name.json';path.parent.mkdir(parents=True);path.write_bytes(raw)
            record['source_locator']={'raw_sha256':digest}
            basis={'method':'literal_source_language_alias_city_unique_near_coordinate_candidate',
                   'alias_evidence_file':'results/p17_continuous/name.json','alias_evidence_sha256':digest,
                   'source_alias':language_aliases(original)['abranch']}
            self.assertFalse(verify_historical_identity(row,record,basis,folder)['entity_verified'])
            basis['source_alias']={'value':'invented','locator':'/brand/names/primary'}
            with self.assertRaisesRegex(ValueError,'not a literal'):verify_historical_identity(row,record,basis,folder)
            basis['alias_evidence_file']='../outside.json'
            with self.assertRaisesRegex(ValueError,'outside retained'):verify_historical_identity(row,record,basis,folder)


if __name__ == '__main__': unittest.main()
