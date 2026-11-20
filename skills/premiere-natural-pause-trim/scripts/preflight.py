"""Read-only local dependency report; does not connect to Premiere or install anything."""
import importlib.util, json, platform, shutil, sys
from pathlib import Path

def inspect(skill):
    required={'heygen-bilingual-upload':['openpyxl'],'premiere-ru-caption-layout':['PIL']}.get(skill,[])
    modules={m:importlib.util.find_spec(m) is not None for m in required}
    pr=skill!='heygen-bilingual-upload'
    ffmpeg=shutil.which('ffmpeg')
    ffprobe=shutil.which('ffprobe')
    audio_tools_required=skill=='premiere-natural-pause-trim'
    return {'skill':skill,'python':platform.python_version(),'python_ok':sys.version_info>=(3,11),
      'platform':platform.system(),'required_modules':modules,'ffmpeg':ffmpeg,
      'ffprobe':ffprobe,'audio_tools_required':audio_tools_required,
      'offline_ready':sys.version_info>=(3,11) and all(modules.values()) and (not audio_tools_required or bool(ffmpeg and ffprobe)),
      'premiere_required':pr,'premiere_connection':'not_checked','live_caption_editing':'not_checked',
      'premiere_write_ready':False,'note':'Offline readiness is not proof of Premiere connection, permissions or rendering. Agent must perform the task-specific live checks.'}
if __name__=='__main__':
    result=inspect(Path(__file__).resolve().parents[1].name)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    sys.exit(0 if result['offline_ready'] else 2)
