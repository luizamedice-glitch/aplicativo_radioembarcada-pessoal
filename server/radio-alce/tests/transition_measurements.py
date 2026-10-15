"""Measure decoded Icecast PCM, not HTTP callbacks, in deterministic tone fixtures."""
import array
import math
import subprocess
import sys


def check_transitions(path):
    raw = subprocess.run(['ffmpeg','-v','error','-i',str(path),'-ac','1','-ar','8000',
                          '-f','s16le','-'],capture_output=True,check=True).stdout
    samples=array.array('h'); samples.frombytes(raw)
    if sys.byteorder!='little': samples.byteswap()
    width=80  # 10 ms measurement resolution
    weights={f:[complex(math.cos(2*math.pi*f*n/8000),math.sin(2*math.pi*f*n/8000))
                for n in range(width)] for f in (440,880,1320)}
    rms=[]; labels=[]
    for start in range(0,len(samples)-width,width):
        block=samples[start:start+width]
        level=math.sqrt(sum(x*x for x in block)/width)/32768
        rms.append(level)
        power={f:abs(sum(x*w for x,w in zip(block,weights[f]))) for f in weights}
        winner=max(power, key=power.get)
        labels.append(winner if level>1e-4 and power[winner]>power[440]*2 else 440)
    groups=[]; start=None
    for n,label in enumerate(labels+[440]):
        if label!=440 and start is None: start=n
        if label==440 and start is not None:
            if n-start>50: groups.append((start,n))
            start=None
    assert len(groups)>=3, ('Need three full MUSIC → INSERT → MUSIC boundaries', groups)
    drops=[]
    for start,end in groups[:3]:
        expected = 1.1 if labels[start]==880 else 1.3
        assert abs((end-start)*.01-expected)<.1, ('Insert truncated or padding remained',start,end)
        def level_before(seconds):
            p=start-int(seconds*100)
            assert p>=0
            return sum(rms[p-5:p+5])/10
        early,middle,late=[level_before(t) for t in (16,7,1)]
        assert early>middle>late>1e-5, ('Fade envelope not continuous/audible',early,middle,late)
        assert level_before(.15)>1e-5, 'MUSIC reached silence before its actual end'
        drop=20*math.log10(early/late)
        assert drop>12, ('Missing progressive MUSIC fade',drop)
        assert sum(rms[end+20:end+40])/20 > early*.7, 'Next MUSIC gain not restored'
        drops.append(round(drop,2))
    longest=current=0
    for level in rms[100:-100]:
        current=current+1 if level<=1e-4 else 0
        longest=max(longest,current)
    assert longest<=5, ('Perceived gap >50 ms at -80 dB',longest*10)
    return {'pcm_boundaries_checked':len(groups[:3]),'music_fade_drop_db':drops,
            'max_silence_ms_at_minus80db':longest*10,'insert_complete':True,
            'insert_to_music_gain_restored':True}
