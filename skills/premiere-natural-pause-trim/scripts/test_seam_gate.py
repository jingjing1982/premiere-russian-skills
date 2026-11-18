import copy,unittest
from native_cut import reviewed_seams

class SeamGateTests(unittest.TestCase):
    def plan(self):
        return {'cuts':[[200,300]],'seam_review':{'fps':25,'duration':1000,'cuts':[[200,300]],'preview_sha256':'synthetic','sequence_uid':'seq','shots':[{'id':'a','start':0,'end':1000,'evidence':'synthetic visual evidence'}]}}
    def test_bound_plan_passes(self):
        self.assertTrue(reviewed_seams(self.plan(),25,1000,'synthetic','seq')['passed'])
    def test_missing_or_stale_review_blocks(self):
        for kind in ['missing','hash','uid','cuts','coverage']:
            p=self.plan()
            if kind=='missing':p.pop('seam_review')
            elif kind=='hash':p['seam_review']['preview_sha256']='changed'
            elif kind=='uid':p['seam_review']['sequence_uid']='other'
            elif kind=='cuts':p['cuts']=[[200,400]]
            else:p['seam_review']['shots'][0]['end']=100
            with self.assertRaises(ValueError):reviewed_seams(p,25,1000,'synthetic','seq')
    def test_short_residual_cannot_enter_native_queue(self):
        p=self.plan();p['seam_review']['shots']=[{'id':'a','start':0,'end':305,'evidence':'synthetic'},{'id':'b','start':305,'end':1000,'evidence':'synthetic'}]
        with self.assertRaisesRegex(ValueError,'residuals'):reviewed_seams(p,25,1000,'synthetic','seq')
if __name__=='__main__':unittest.main()
