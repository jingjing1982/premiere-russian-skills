"""Synthetic project graph tests only; never opens or edits Premiere."""
import argparse,base64,gzip,json,struct,tempfile,unittest,hashlib
from pathlib import Path
import xml.etree.ElementTree as E
from native_cut import prepare,audit

def fixture():
    root=E.Element('PremiereData');ticks=254016000000//25
    def node(tag,id=None,uid=None):return E.SubElement(root,tag,{'ObjectID':id} if id else {'ObjectUID':uid} if uid else {})
    def child(p,path,text=None,**attrs):
        for name in path.split('/'):
            e=p.find(name)
            if e is None:e=E.SubElement(p,name)
            p=e
        if text is not None:p.text=str(text)
        p.attrib.update(attrs);return p
    seq=node('Sequence',uid='synthetic-seq');child(seq,'Name','Synthetic OFFLINE only')
    for i,(tag,uid) in enumerate([('VideoTrackGroup','v'),('AudioTrackGroup','a'),('CaptionTrackGroup','c')],1):
        ref=E.SubElement(child(seq,'TrackGroups'),'TrackGroup');E.SubElement(ref,'Second',ObjectRef=str(i))
        group=node(tag,str(i));child(group,'TrackGroup/FrameRate',ticks);child(group,'TrackGroup/Tracks/Track',ObjectURef=uid,Index='0')
        track=node('CaptionDataClipTrack' if uid=='c' else 'ClipTrack',uid=uid)
        if uid!='c':
            objid='1'+uid;child(track,'ClipTrack/ClipItems/TrackItems/TrackItem',ObjectRef=objid)
            ob=node('VideoClipTrackItem' if uid=='v' else 'AudioClipTrackItem',objid)
            child(ob,'ClipTrackItem/TrackItem/Start',0);child(ob,'ClipTrackItem/TrackItem/End',1000*ticks)
            child(ob,'ClipTrackItem/SubClip',ObjectRef='sub'+uid);child(ob,'ClipTrackItem/ComponentOwner/Components/Volume','1.0')
            sub=node('SubClip','sub'+uid);child(sub,'Clip',ObjectRef='clip'+uid)
            clip=node('VideoClip' if uid=='v' else 'AudioClip','clip'+uid)
            child(clip,'Clip/InPoint',0);child(clip,'Clip/OutPoint',1000*ticks);child(clip,'Clip/Source',ObjectRef='source'+uid)
            source=node('Source','source'+uid);child(source,'MediaSource/Media',ObjectURef='media');child(track,'TrackVolume','1.0')
        else:
            child(track,'ClipTrack/ClipItems/TrackItems/TrackItem',ObjectRef='caption1')
            ob=node('CaptionDataClip','caption1');child(ob,'TrackItem/Start',0);child(ob,'TrackItem/End',100*ticks)
            child(ob,'BlockVector/BlockVectorItem',ObjectRef='text1');ft=node('FormattedText','text1');raw='Привет.\n你好'.encode()
            child(ft,'FormattedTextData',base64.b64encode(struct.pack('<I',len(raw))+raw+b'\0').decode(),BinaryHash='hash1')
    media=node('Media',uid='media');child(media,'ActualMediaFilePath','synthetic.mp4')
    child(seq,'PersistentGroupContainer/LinkContainer/Links/Link',ObjectRef='link');link=node('Link','link')
    E.SubElement(link,'TrackItem',ObjectRef='1v');E.SubElement(link,'TrackItem',ObjectRef='1a')
    return root
class NativeTests(unittest.TestCase):
    def test_prepare_and_audit_block_unrelated_track_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);root=fixture();raw=gzip.compress(E.tostring(root));source=d/'source.prproj';preview=d/'preview.prproj'
            source.write_bytes(raw);preview.write_bytes(raw);cuts=d/'cuts.json';cuts.write_text(json.dumps({'cuts':[[200,300]],'protected':[],'review_reference':'Synthetic only','seam_review':{'fps':25,'duration':1000,'cuts':[[200,300]],'preview_sha256':hashlib.sha256(raw).hexdigest(),'sequence_uid':'synthetic-seq','shots':[{'id':'one','start':0,'end':1000,'evidence':'Synthetic offline reviewed shot'}]}}))
            job=d/'job';prepare(argparse.Namespace(source=str(source),preview=str(preview),uid='synthetic-seq',cuts=str(cuts),output=str(job)))
            a=argparse.Namespace(job=str(job/'job.json'),done=0,output=str(d/'before.json'));self.assertEqual(audit(a)['verified_steps'],0)
            root.find(".//*[@ObjectUID='a']/TrackVolume").text='0.1';preview.write_bytes(gzip.compress(E.tostring(root)))
            a.output=str(d/'bad.json')
            with self.assertRaises(ValueError):audit(a)
            self.assertFalse(Path(a.output).exists());self.assertEqual(source.read_bytes(),raw)
            jsx=(job/'cut-001.jsx').read_text(encoding='utf-8')
            self.assertLess(jsx.index('Target activation failed'),jsx.index('qs.extract()'))
            self.assertLess(jsx.index('QE sequence identity'),jsx.index('qs.extract()'))
    def test_source_cannot_be_used_as_preview(self):
        with self.assertRaises(ValueError):prepare(argparse.Namespace(source='same.prproj',preview='same.prproj',uid='x',cuts='unused',output='unused'))
if __name__=='__main__':unittest.main()
