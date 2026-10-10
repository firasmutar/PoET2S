"""Check the quantitative claims of the revised manuscript against the CSVs in results/.

Each check recomputes one number quoted in the paper (means, differences, seed counts, p-values, table cells) and
compares it with the value printed in the paper, within its rounding. Run from anywhere:

    python scripts/verify_claims.py
"""
import os
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results"))
import csv, numpy as np, collections
L=lambda f: list(csv.DictReader(open(f)))
M=L('main_per_seed.csv')
def c(rows,key,val,m): return np.array([float(r[m]) for r in sorted([r for r in rows if r[key]==val],key=lambda r:int(r['seed']))])
mm=lambda s,m: c(M,'scheme',s,m)
out=[]
def chk(name, got, want, tol):
    ok = abs(got-want) <= tol
    out.append(ok); print(('PASS ' if ok else 'FAIL ')+f"{name}: computed {got:.4g}, paper {want}")
# 8.1
chk('PoET2S latency', mm('PoET2S','latency_ms').mean(), 30.2, .05)
chk('vs PoS +ms', (mm('PoET2S','latency_ms')-mm('PoS','latency_ms')).mean(), 9.4, .05)
chk('vs DPoS +ms', (mm('PoET2S','latency_ms')-mm('DPoS','latency_ms')).mean(), 11.3, .05)
chk('vs PBFT -ms', (mm('PBFT','latency_ms')-mm('PoET2S','latency_ms')).mean(), 8.7, .05)
chk('DPoS latency', mm('DPoS','latency_ms').mean(), 19.0, .05)
chk('PoET2S caught', mm('PoET2S','caught_pct').mean(), 91.0, .05)
chk('PoET2S FP/c', mm('PoET2S','fp_per_caught').mean(), 13.9, .05)
chk('baseline FP min', min(mm(s,'false_pos').mean() for s in ['PoS','DPoS','PBFT','PoS+Twin','DPoS+Twin','PBFT+Twin']), 3889, .5)
chk('baseline FP max', max(mm(s,'false_pos').mean() for s in ['PoS','DPoS','PBFT','PoS+Twin','DPoS+Twin','PBFT+Twin']), 5091, .5)
chk('baseline FPc max', max(mm(s,'fp_per_caught').mean() for s in ['PoS','DPoS','PBFT','PoS+Twin','DPoS+Twin','PBFT+Twin']), 67.9, .05)
chk('PoET2S infil', mm('PoET2S','infiltration_pct').mean(), 2.6, .05)
chk('PoET2S infil sd', mm('PoET2S','infiltration_pct').std(ddof=1), 1.9, .05)
# 8.3
chk('veto caught', mm('PoMonitor','caught_pct').mean(), 91.7, .05)
chk('veto FPc', mm('PoMonitor','fp_per_caught').mean(), 9.7, .05)
chk('additive FPc', mm('EACM','fp_per_caught').mean(), 6.0, .05)
chk('additive caught', mm('EACM','caught_pct').mean(), 75.0, .05)
chk('PoET higher caught seeds', (mm('PoET2S','caught_pct')>mm('PoMonitor','caught_pct')).sum(), 10, 0)
for s,v in [('PoMonitor',10.8),('EACM',9.4),('RepStake',3.8)]: chk(f'{s} infil', mm(s,'infiltration_pct').mean(), v, .05)
d=mm('PoET2S','infiltration_pct')-mm('PoMonitor','infiltration_pct'); chk('vs veto lower seeds',(d<0).sum(),30,0)
chk('vs veto rel %', 100*(1-mm('PoET2S','infiltration_pct').mean()/mm('PoMonitor','infiltration_pct').mean()), 76, .5)
d=mm('PoET2S','infiltration_pct')-mm('EACM','infiltration_pct'); chk('vs additive lower seeds',(d<0).sum(),28,0)
chk('vs additive rel %', 100*(1-mm('PoET2S','infiltration_pct').mean()/mm('EACM','infiltration_pct').mean()), 72, .5)
d=mm('PoET2S','infiltration_pct')-mm('RepStake','infiltration_pct')
chk('vs linear lower',(d<0).sum(),18,0); chk('vs linear higher',(d>0).sum(),11,0); chk('vs linear tied',(d==0).sum(),1,0)
chk('vs linear rel %', 100*(1-mm('PoET2S','infiltration_pct').mean()/mm('RepStake','infiltration_pct').mean()), 31, .5)
chk('vs linear diff', d.mean(), -1.21, .005)
for s,v in [('PoMonitor',10.2),('EACM',8.7),('RepStake',4.4),('PoET2S',2.7)]: chk(f'{s} proposer', mm(s,'proposer_capture_pct').mean(), v, .05)
S=L('seeds100.csv'); s100=lambda s,m: c(S,'scheme',s,m)
a,b=s100('PoET2S','infiltration_pct'),s100('RepStake','infiltration_pct')
chk('100 PoET',a.mean(),3.15,.005); chk('100 lin',b.mean(),4.99,.005); chk('100 rel',100*(1-a.mean()/b.mean()),37,.5)
chk('100 lower',((a-b)<0).sum(),70,0); chk('100 tied',((a-b)==0).sum(),4,0); chk('100 higher',((a-b)>0).sum(),26,0)
chk('100 veto lower',((a-s100('PoMonitor','infiltration_pct'))<0).sum(),98,0)
# 8.5 Byzantine
B=L('byzantine_sweep.csv')
bz=lambda f,s,m: np.mean([float(r[m]) for r in B if r['fraction']==f and r['scheme']==s])
for f,s,m,v in [('0.1','PoET2S','infiltration_pct',3.2),('0.1','PoMonitor','infiltration_pct',7.2),('0.1','EACM','infiltration_pct',7.0),('0.1','RepStake','infiltration_pct',4.7),
                ('0.45','PoET2S','infiltration_pct',13.7),('0.45','PoMonitor','infiltration_pct',35.0),('0.45','EACM','infiltration_pct',31.2),('0.45','RepStake','infiltration_pct',18.7),
                ('0.3','PoET2S','safety_violation_pct',.33),('0.45','PoET2S','safety_violation_pct',2.4),('0.3','PoMonitor','safety_violation_pct',12.3),('0.45','PoMonitor','safety_violation_pct',64.4),
                ('0.3','EACM','safety_violation_pct',18.3),('0.45','EACM','safety_violation_pct',47.1),('0.3','RepStake','safety_violation_pct',2.0),('0.45','RepStake','safety_violation_pct',10.7),('0.2','EACM','safety_violation_pct',4.4)]:
    chk(f'byz {f} {s} {m}', bz(f,s,m), v, .05 if v>=1 else .005)
chk('PoET max safety', max(bz(f,'PoET2S','safety_violation_pct') for f in {r['fraction'] for r in B}), 2.44, .05)
# 8.6 adaptive
A_=L('adaptive.csv'); ad=lambda s,m: c(A_,'scheme',s,m).mean()
for s,m,v in [('PoET2S-recover','infiltration_pct',2.9),('PoMonitor-recover','infiltration_pct',10.8),('PoET2S-stealth','infiltration_pct',3.4),('PoMonitor-stealth','infiltration_pct',11.1),
              ('PoET2S-recover','extracted_profit',2.8),('PoMonitor-recover','extracted_profit',70.0),('PoET2S-stealth','extracted_profit',4.2),('PoMonitor-stealth','extracted_profit',64.9),
              ('PoMonitor-recover','caught_pct',92.0),('PoMonitor-stealth','caught_pct',90.9),('PoET2S-recover','caught_pct',91.1),('PoET2S-stealth','caught_pct',90.7)]:
    chk(f'adaptive {s} {m}', ad(s,m), v, .05)
# 8.8 hybrid
H=L('hybrid_ablation.csv'); chk('hybrid caught', c(H,'variant','PoET2S-hybrid','caught_pct').mean(), 94.0,.05); chk('hybrid FPc', c(H,'variant','PoET2S-hybrid','fp_per_caught').mean(), 16.9,.05)
chk('hybrid > veto seeds', (c(H,'variant','PoET2S-hybrid','caught_pct')>c(H,'variant','PoMonitor','caught_pct')).sum(), 28, 0)
# fast path
F=L('fastpath_main.csv'); fp=lambda s,m: c(F,'scheme',s,m)
chk('fast latency', fp('PoET2S-fast','latency_ms').mean(), 26.8,.05); chk('fast sd', fp('PoET2S-fast','latency_ms').std(ddof=1), 1.1,.05)
chk('fast faster all seeds', (fp('PoET2S-fast','latency_ms')<fp('PoET2S','latency_ms')).sum(), 30, 0)
chk('fast first commit', fp('PoET2S-fast','first_commit_ms').mean(), 21.2,.05)
chk('PoS lower first-commit seeds', (fp('PoS','first_commit_ms')<fp('PoET2S-fast','first_commit_ms')).sum(), 21, 0)
chk('withhold PoET', fp('PoET2S-withhold','latency_ms').mean(), 31.0,.05); chk('withhold veto', fp('PoMonitor-withhold','latency_ms').mean(), 34.6,.05)
chk('veto fast', fp('PoMonitor-fast','latency_ms').mean(), 36.1,.05); chk('linear fast', fp('RepStake-fast','latency_ms').mean(), 27.8,.05)
FS=L('fastpath_sweep.csv'); fs=lambda f,s,m: np.mean([float(r[m]) for r in FS if r['fraction']==f and r['scheme']==s])
chk('fast pct 30', fs('0.3','PoET2S-fast','fast_path_pct'), 98.8,.05); chk('fast pct 45', fs('0.45','PoET2S-fast','fast_path_pct'), 85.2,.05)
chk('fast lat 45', fs('0.45','PoET2S-fast','latency_ms'), 42.9,.05); chk('veto fail 15', 100-fs('0.15','PoMonitor-fast','fast_path_pct'), 3.9,.05)
chk('veto fail 30', 100-fs('0.3','PoMonitor-fast','fast_path_pct'), 46.8,.05)
# hardening
HD=L('hardened.csv'); hd=lambda s: c(HD,'scheme',s,'infiltration_pct')
chk('H infil', hd('PoET2S-H').mean(), 2.9,.05); chk('HS infil', hd('PoET2S-HS').mean(), 7.7,.05); chk('veto HS', hd('PoMonitor-HS').mean(), 10.0,.05); chk('lin HS', hd('RepStake-HS').mean(), 10.7,.05)
# honest TTS
T=L('sybil_honest_tts.csv'); chk('honest TTS', np.mean([float(r['honest_tts_mean']) for r in T]), .71, .005)
chk('honest q1', np.mean([float(r['honest_tts_q1']) for r in T]), .66, .005); chk('honest q3', np.mean([float(r['honest_tts_q3']) for r in T]), .78, .005)
# review pass additions
import pandas as _pd
_t=_pd.read_csv('latency_tail.csv').set_index('scheme')
chk('p95 three-phase', _t.loc['PoET2S','p95'], 33.2,.05); chk('p99 three-phase', _t.loc['PoET2S','p99'], 35.2,.05)
chk('p95 fast', _t.loc['PoET2S-fast','p95'], 33.8,.05); chk('p99 fast', _t.loc['PoET2S-fast','p99'], 39.8,.05)
_s=_pd.read_csv('stats_tests.csv'); _v=_pd.read_csv('stats_v19.csv')
_g=lambda d,c,m: float(d[(d.comparison==c)&(d.metric==m)].p_holm.iloc[0])
chk('holm linear infil', _g(_s,'PoET2S vs RepStake','infiltration_pct'), 0.032, .0005)
chk('holm linear prop', _g(_s,'PoET2S vs RepStake','proposer_capture_pct'), 0.50, .005)
chk('holm 100 infil e9', _g(_v,'PoET2S vs RepStake','infiltration_pct')*1e9, 7.2, .05)
chk('holm 100 prop e4', _g(_v,'PoET2S vs RepStake','proposer_capture_pct')*1e4, 3.3, .05)
chk('max holm linear safety >=35%', max(_g(_v,f'PoET2S vs RepStake @ {f}','safety_violation_pct') for f in (0.35,0.4,0.45)) < 0.03, 1, 0)
_w=_pd.read_csv('weight_trajectory.csv')
chk('poet2s rel @1.5', _w[(_w.lie==1.5)&(_w.slot>=36)].poet2s_rel.mean(), 0.85,.005)

print(f"\n{sum(out)}/{len(out)} claims verified")
import sys; sys.exit(0 if all(out) else 1)
