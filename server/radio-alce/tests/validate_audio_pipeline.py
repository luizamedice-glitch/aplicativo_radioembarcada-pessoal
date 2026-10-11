#!/usr/bin/env python3
"""Offline A/B isolation using the pinned Liquidsoap and actual Icecast output."""
import json
import os
from pathlib import Path
import subprocess
import sys
from audio_amplitude import require_audible


def main():
    results={}
    runtime=Path(__file__).with_name('validate_runtime.py')
    for stage in ('production','amplify','fade_out','fade_in','legacy_fades','explicit_fades'):
        print('Audio isolation: '+stage,flush=True)
        run=subprocess.run([sys.executable,str(runtime)],env=dict(os.environ,ALCE_AUDIO_STAGE=stage,ALCE_TEST_NEWS='0',ALCE_TEST_EMERGENCY='0'),
                           capture_output=True,text=True)
        print(run.stdout,flush=True)
        if run.stderr: print(run.stderr,file=sys.stderr,flush=True)
        run.check_returncode()
        report=next(json.loads(line) for line in run.stdout.splitlines() if line.startswith('{"audio_stage"'))
        results[stage]=report['icecast_volume']
    require_audible(results['production'])
    require_audible(results['amplify'])
    assert results['fade_out']['mean_volume']<=-80, results
    assert results['legacy_fades']['mean_volume']<=-80, results
    require_audible(results['fade_in'])
    require_audible(results['explicit_fades'])
    print(json.dumps({'audio_pipeline_ab':results,'production_audible':True}),flush=True)

if __name__=='__main__': main()
