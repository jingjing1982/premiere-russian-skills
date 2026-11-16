"""Synthetic project + evidence tests, no Premiere or external media required."""
import copy,gzip,json,tempfile,unittest,shutil,subprocess
from pathlib import Path
import xml.etree.ElementTree as E
import track_sort as ts
from review import validate_review
from task_setup import setup
from saved_audit import audit,load,records
from media_samples import samples,render
from prepare_preview import prepare


def fixture():
    root=E.Element('PremiereData');ticks=254016000000//25
    def node(tag,id=None,uid=None):return E.SubElement(root,tag,{'ObjectID':id} if id else {'ObjectUID':uid})
    def child(p,path,text=None,**attrs):
        for name in path.split('/'):
            e=p.find(name)
            if e is None:e=E.SubElement(p,name)
            p=e
        if text is not None:p.text=str(text)
        p.attrib.update(attrs);return p
    seq=node('Sequence',uid='test-seq');child(seq,'Name','Offline synthetic lecture')
    for n,(tag,uid) in enumerate([('VideoTrackGroup','v'),('AudioTrackGroup','a'),('CaptionTrackGroup','c')],1):
        ref=E.SubElement(child(seq,'TrackGroups'),'TrackGroup');E.SubElement(ref,'Second',ObjectRef=str(n))
        group=node(tag,str(n));child(group,'TrackGroup/FrameRate',ticks);child(group,'TrackGroup/Tracks/Track',ObjectURef=uid,Index='0')
        track=node('ClipTrack',uid=uid)
        if uid=='c':child(track,'CaptionContent','Do not change');continue
        child(track,'TrackVolume','1.0');objid='item'+uid
        child(track,'ClipTrack/ClipItems/TrackItems/TrackItem',ObjectRef=objid)
        ob=node('VideoClipTrackItem' if uid=='v' else 'AudioClipTrackItem',objid)
        child(ob,'ClipTrackItem/TrackItem/Start',0);child(ob,'ClipTrackItem/TrackItem/End',100*ticks)
        child(ob,'ClipTrackItem/SubClip',ObjectRef='sub'+uid);child(ob,'ClipTrackItem/ComponentOwner/Components/Volume','1.0')
        sub=node('SubClip','sub'+uid);child(sub,'Clip',ObjectRef='clip'+uid)
        clip=node('VideoClip' if uid=='v' else 'AudioClip','clip'+uid)
        child(clip,'Clip/InPoint',200*ticks);child(clip,'Clip/OutPoint',300*ticks);child(clip,'Clip/Source',ObjectRef='src'+uid)
        source=node('Source','src'+uid);child(source,'MediaSource/Media',ObjectURef='media')
        if uid=='v':
            E.SubElement(group.find('./TrackGroup/Tracks'),'Track',ObjectURef='v2',Index='1')
            extra=node('ClipTrack',uid='v2');child(extra,'TrackVolume','1.0');child(extra,'ClipTrack/ClipItems/TrackItems')
    media=node('Media',uid='media');child(media,'ActualMediaFilePath','synthetic.mp4')
    child(seq,'PersistentGroupContainer/LinkContainer/Links/Link',ObjectRef='link');link=node('Link','link')
    E.SubElement(link,'TrackItem',ObjectRef='itemv');E.SubElement(link,'TrackItem',ObjectRef='itema')
    return root


class PublicWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.d=Path(self.temp.name)
        self.source=self.d/'source.prproj';self.root=fixture();self.source.write_bytes(gzip.compress(E.tostring(self.root)))
        setup(self.source,'test-seq',25,self.d/'task')
        self.cfg=ts.read(self.d/'task/config.json');self.review=ts.read(self.cfg['review'])
        self.review['spans'][0].update(label='audience',reviewed=True,visual_evidence=['Viewed first/middle/last: seated listeners'])
        self.cfg['moves']=[{'start':0,'end':100,'video_track':0,'audio_track':0,'target_track':1}]
        self.save()

    def save(self):
        ts.write(self.cfg['review'],self.review);ts.write(self.d/'task/config.json',self.cfg)

    def test_setup_build_and_vertical_move_saved_audit(self):
        ts.build(self.d/'task/config.json',self.d/'plan')
        p=ts.read(self.d/'plan/plan.json');self.assertEqual(len(p['ops']),1)
        altered=copy.deepcopy(self.root)
        old=altered.find(".//*[@ObjectUID='v']/ClipTrack/ClipItems/TrackItems")
        dest=altered.find(".//*[@ObjectUID='v2']/ClipTrack/ClipItems/TrackItems")
        item=old[0];old.remove(item);dest.append(item)
        Path(self.cfg['preview']).write_bytes(gzip.compress(E.tostring(altered)))
        result=audit(self.cfg['source_snapshot'],self.cfg['preview'],'test-seq',self.cfg['tpf'],p['ops'][0]['after'])
        self.assertEqual(result['av_link_pairs'],1)
        self.assertEqual(ts.digest(self.source),self.review['source_sha256'])

    def test_saved_metadata_change_is_rejected(self):
        for query in [".//*[@ObjectUID='a']/TrackVolume",".//*[@ObjectUID='c']/CaptionContent",".//*[@ObjectUID='test-seq']/Name"]:
            altered=copy.deepcopy(self.root);altered.find(query).text='changed'
            Path(self.cfg['preview']).write_bytes(gzip.compress(E.tostring(altered)))
            with self.assertRaises(ValueError):audit(self.cfg['source_snapshot'],self.cfg['preview'],'test-seq',self.cfg['tpf'],self.cfg['baseline'])

    def test_stale_source_evidence_rejected(self):
        self.review['source_sha256']='wrong';self.save()
        with self.assertRaises(ValueError):ts.build(self.d/'task/config.json',self.d/'bad')
        self.assertFalse((self.d/'bad').exists())

    @unittest.skipUnless(__import__('os').name == 'nt', 'Native request preparation requires Windows absolute paths')
    def test_prepare_requests_checks_frozen_review(self):
        ts.build(self.d/'task/config.json',self.d/'plan')
        result=prepare([self.d/'plan'],self.d/'requests')
        self.assertEqual(len(result['requests']),4)
        self.assertFalse(result['premiere_contacted'])
        (self.d/'plan/review.json').write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):prepare([self.d/'plan'],self.d/'badrequests')
        self.assertFalse((self.d/'badrequests').exists())

    def test_unreviewed_or_partial_coverage_rejected(self):
        self.review['spans'][0]['reviewed']=False;self.save()
        with self.assertRaises(ValueError):validate_review(self.cfg,self.cfg['baseline'])
        self.review['spans'][0]['reviewed']=True;self.review['spans'][0]['end']=99;self.save()
        with self.assertRaises(ValueError):validate_review(self.cfg,self.cfg['baseline'])

    def test_audience_with_interpreter_voice_cannot_move_v3(self):
        self.review['spans'][0]['audio_role']='interpreter';self.review['spans'][0]['audio_evidence']=['Heard off-camera interpreter']
        self.cfg['moves'][0]['target_track']=2;self.save()
        with self.assertRaises(ValueError):validate_review(self.cfg,self.cfg['baseline'])
        self.cfg['moves'][0]['target_track']=1;self.save()
        self.assertEqual(validate_review(self.cfg,self.cfg['baseline'])['mode'],'audience_only')

    def test_interpreter_requires_audio_and_no_protected_overlap(self):
        self.review['mode']='audience_and_interpreter';s=self.review['spans'][0];s['label']='interpreter'
        self.cfg['moves'][0]['target_track']=2;self.save()
        with self.assertRaises(ValueError):validate_review(self.cfg,self.cfg['baseline'])
        s.update(audio_role='interpreter',audio_evidence=['ASR plus context reviewed 0-100'],overlapping_protected_speech=True);self.save()
        with self.assertRaises(ValueError):validate_review(self.cfg,self.cfg['baseline'])
        s['overlapping_protected_speech']=False;self.save();validate_review(self.cfg,self.cfg['baseline'])

    def test_unneeded_cuts_and_missing_cut_review_rejected(self):
        self.cfg['cuts']=[{'frame':40,'video_track':0,'audio_track':0}];self.save()
        with self.assertRaises(ValueError):validate_review(self.cfg,self.cfg['baseline'])
        self.review['cut_reviews']=[dict(self.cfg['cuts'][0],reviewed=True,evidence=['frame checked'])];self.save()
        with self.assertRaises(ValueError):validate_review(self.cfg,self.cfg['baseline'])

    def test_keep_uncertain_is_zero_action_supported(self):
        self.review['spans'][0]['label']='uncertain';self.cfg['moves']=[];self.save()
        ts.build(self.d/'task/config.json',self.d/'zero')
        self.assertEqual(ts.read(self.d/'zero/plan.json')['ops'],[])

    def test_preview_cannot_be_main(self):
        self.cfg['preview']=self.cfg['main_project'];self.save()
        with self.assertRaises(ValueError):ts.build(self.d/'task/config.json',self.d/'bad')

    def test_sampling_respects_source_offset(self):
        first=samples(self.cfg,'screen');candidate=samples(self.cfg,'candidate')
        self.assertEqual(first[0]['sequence_frame'],49);self.assertEqual(first[0]['source_seconds'],249/25)
        self.assertEqual([s['sequence_frame'] for s in candidate],[0,49,99])
        with self.assertRaises(ValueError):samples(self.cfg,'candidate',['not-a-clip'])

    @unittest.skipUnless(shutil.which('ffmpeg'),'Optional ffmpeg integration test')
    def test_real_frame_extraction_and_cache(self):
        media=self.d/'synthetic.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=blue:s=160x90:r=25',
                        '-t','1','-c:v','mpeg4',str(media)],check=True,capture_output=True,timeout=30)
        cfg=dict(self.cfg,baseline=[[0,0,0,25,0,25,str(media)],[1,0,0,25,0,25,str(media)]])
        ts.write(self.d/'samples-config.json',cfg)
        a=render(self.d/'samples-config.json',self.d/'first',self.d/'cache','candidate')
        b=render(self.d/'samples-config.json',self.d/'second',self.d/'cache','candidate')
        self.assertEqual(a['images'],3);self.assertEqual(b['cache_hits'],3)
        manifest=ts.read(self.d/'first/samples.json')
        self.assertFalse(manifest['visual_review_completed']);self.assertFalse(manifest['audio_review_completed'])

if __name__=='__main__':unittest.main()
