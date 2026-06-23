import csv, glob, os, statistics, time, sys
sys.stdout.reconfigure(encoding='utf-8')
F=lambda r,k: float(r[k]); I=lambda r,k: int(float(r[k]))
files=[p for p in glob.glob('**/*.csv',recursive=True) if 'brno' in p.lower()]
files.sort(key=os.path.getmtime)
print("Brno-логів:", len(files), "\n")
for p in files:
    rows=list(csv.DictReader(open(p,encoding='utf-8')))
    if not rows: continue
    from collections import OrderedDict
    laps=OrderedDict()
    for r in rows: laps.setdefault(int(r['lap']),[]).append(r)
    clean=[]; spins=0
    for lp,rs in laps.items():
        d=F(rs[-1],'t')-F(rs[0],'t'); prr=max(F(r,'pos')for r in rs)-min(F(r,'pos')for r in rs)
        if not(prr>0.9 and 50<d<200): continue
        mrs=max((F(r,'slip_rl')+F(r,'slip_rr'))/2 for r in rs)
        if mrs>5: spins+=1
        else: clean.append(d)
    drv=[r for r in rows if F(r,'speed_kmh')>30 and I(r,'inpit')==0]
    if not drv: continue
    a=lambda k: sum(F(r,k) for r in drv)/len(drv)
    pf=(a('press_fl')+a('press_fr'))/2; pr=(a('press_rl')+a('press_rr'))/2
    tf=(a('ttemp_fl')+a('ttemp_fr'))/2; tr=(a('ttemp_rl')+a('ttemp_rr'))/2
    corn=[r for r in drv if abs(F(r,'gx'))>1.0]
    fs=sum(F(r,'slip_fl')+F(r,'slip_fr') for r in corn)/(2*len(corn)) if corn else 0
    rs2=sum(F(r,'slip_rl')+F(r,'slip_rr') for r in corn)/(2*len(corn)) if corn else 0
    bal="OS" if rs2>fs*1.08 else "US" if fs>rs2*1.08 else "ok"
    best=min(clean) if clean else 0
    sd=statistics.pstdev(clean) if len(clean)>1 else 0
    bm="%d:%05.2f"%(int(best)//60,best-(int(best)//60)*60) if best else "  -  "
    lbl=time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(p)))
    print("%s | %2dкл | best %s | розкид %4.1fс | спінів %d | тиск %2.0f/%2.0f | темп %2.0f/%2.0f | баланс %.2f/%.2f %s | maxRPM %d | vmax %.0f"
          %(lbl,len(clean),bm,sd,spins,pf,pr,tf,tr,fs,rs2,bal,max(I(r,'rpm')for r in drv),max(F(r,'speed_kmh')for r in drv)))
