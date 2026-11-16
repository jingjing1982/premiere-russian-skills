"""Read-only dependency check; never installs or contacts Premiere."""
import importlib.util,json,platform,shutil,sys

def inspect():
    return {'python_ok':sys.version_info>=(3,11),'platform':platform.system(),
            'pillow':importlib.util.find_spec('PIL') is not None,
            'ffmpeg':shutil.which('ffmpeg'),'ffprobe':shutil.which('ffprobe'),'node_for_tests':shutil.which('node'),
            'native_runner_platform_supported':platform.system()=='Windows',
            'premiere_connection':'not_checked','premiere_write_ready':False,
            'note':'Offline planning is portable; native execution targets Windows and requires an existing authorized bridge.'}
if __name__=='__main__':
    r=inspect();print(json.dumps(r,ensure_ascii=False,indent=2));sys.exit(0 if r['python_ok'] and r['pillow'] and r['ffmpeg'] else 2)
