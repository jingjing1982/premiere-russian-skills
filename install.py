"""Install selected standalone skills without replacing existing user skills."""
import argparse, hashlib, json, os, shutil
from pathlib import Path

def install(package,destination,names=None):
    package=Path(package).resolve();destination=Path(destination).expanduser().resolve()
    manifest=json.loads((package/'package-manifest.json').read_text(encoding='utf-8'))
    available=manifest['skills'];chosen=names or available
    if not chosen or len(chosen)!=len(set(chosen)) or any(n not in available for n in chosen):raise ValueError('Unknown/duplicate skill selection')
    # Validate every selected source and every destination before copying anything.
    jobs=[];skipped=[]
    for name in chosen:
        src=package/'skills'/name;dst=destination/name
        if not src.is_dir() or src==dst or src in dst.parents or dst in src.parents:raise ValueError('Invalid installation destination')
        files={k:v for k,v in manifest['files'].items() if k.startswith('skills/'+name+'/')}
        for rel,digest in files.items():
            path=package/rel
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Package checksum mismatch: '+rel)
        actual={p.relative_to(package).as_posix() for p in src.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
        if actual!=set(files):raise ValueError('Unlisted/missing package file')
        if dst.exists():
            same=True
            for rel,digest in files.items():
                target=dst/Path(rel).relative_to('skills/'+name)
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:same=False;break
            existing={p.relative_to(dst).as_posix() for p in dst.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
            desired={Path(k).relative_to('skills/'+name).as_posix() for k in files}
            if not same or existing!=desired:raise ValueError('Existing different skill left untouched: '+str(dst))
            skipped.append(name)
        else:jobs.append((src,dst))
    destination.mkdir(parents=True,exist_ok=True)
    for src,dst in jobs:
        shutil.copytree(src,dst,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    return {'installed':[p.name for s,p in jobs],'already_identical':skipped,'destination':str(destination),'premiere_modified':False}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destination',default=str(Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'skills'))
    p.add_argument('--skills',nargs='+');a=p.parse_args()
    print(json.dumps(install(Path(__file__).resolve().parent,a.destination,a.skills),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
