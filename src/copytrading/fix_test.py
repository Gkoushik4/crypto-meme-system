"""Pre-declared fixes (decided BEFORE looking at results):
 A: copy LONGS only, only while BTC is above its 50-day average, our exits (3R TP, BE, trail)
 B: same filter, but let winners run: no 3R cap, trailing stop only, max 7 days
Chosen on windows 1-2, judged on window 3. Control: same number of longs at the same times on a RANDOM major."""
import numpy as np, pandas as pd
import level2 as L
all_t=[f["time"] for fl in L.fills.values() for f in fl]
END=pd.to_datetime(max(all_t),unit="ms"); T0=END-pd.Timedelta(days=90)
btc=L.candles["BTC"].close; sma=btc.rolling(50*24).mean()
def up(t):
    b=btc[btc.index<=t]; s=sma[sma.index<=t]
    return bool(len(s) and not np.isnan(s.iloc[-1]) and b.iloc[-1]>s.iloc[-1])
res=[]
for w in (0,15,30):
    s0,s1=T0+pd.Timedelta(days=w),T0+pd.Timedelta(days=w+30); t1=min(s1+pd.Timedelta(days=30),END)
    d=L.select(s0,s1); top=list(d[d.passed].nlargest(10,"profit_factor").trader)
    sig=L.signals(top,s1,t1,L.MAJORS)
    if len(sig): sig=sig[(sig.dir==1)&sig.t.apply(up)].reset_index(drop=True)
    row={"window":w//15+1,"signals":len(sig)}
    for name,tp in (("A",3.0),("B",99.0)):
        L.TP_R=tp
        end,log=L.run_book(sig,85.0,"ours") if len(sig) else (85.0,pd.DataFrame())
        rnd=[]
        for k in range(30):
            rng=np.random.default_rng(k); s2=sig.copy()
            s2["coin"]=[rng.choice(L.MAJORS) for _ in range(len(s2))]
            s2["px"]=[L.candles[c].close[L.candles[c].index<=t].iloc[-1] for c,t in zip(s2.coin,s2.t)]
            rnd.append(L.run_book(s2,85.0,"ours")[0] if len(s2) else 85.0)
        row[f"{name} $end"]=round(end,2); row[f"{name} trades"]=len(log)
        row[f"{name} wins"]=int((log.pnl>0).sum()) if len(log) else 0
        row[f"{name} random-coin median"]=round(float(np.median(rnd)),2)
    b=btc[(btc.index>=s1)&(btc.index<=t1)]; row["hold BTC"]=round(85*b.iloc[-1]/b.iloc[0],2)
    res.append(row)
L.TP_R=3.0
R=pd.DataFrame(res); print(R.to_string(index=False))
