import numpy as np, pandas as pd
import level2 as L
all_t=[f["time"] for fl in L.fills.values() for f in fl]
END=pd.to_datetime(max(all_t),unit="ms"); T0=END-pd.Timedelta(days=90)
H=[1,4,24,72,168]
btc=L.candles["BTC"].close; sma=btc.rolling(50*24).mean()
def fwd(sig):
    rows=[]
    for _,s in sig.iterrows():
        c=L.candles[s.coin].close; base=s.px*(1+s.dir*L.SLIP)
        r={"coin":s.coin,"dir":s.dir,"t":s.t}
        for h in H:
            x=c[c.index>=s.t+pd.Timedelta(hours=h)]
            r[f"{h}h"]=s.dir*(x.iloc[0]/base-1) if len(x) else np.nan
        b=btc[btc.index<=s.t]; sm=sma[sma.index<=s.t]
        r["btc_up"]= bool(len(sm) and not np.isnan(sm.iloc[-1]) and b.iloc[-1]>sm.iloc[-1])
        rows.append(r)
    return pd.DataFrame(rows)
picked=[];allsig=[]
for w in (0,15,30):
    s0,s1=T0+pd.Timedelta(days=w),T0+pd.Timedelta(days=w+30); t1=min(s1+pd.Timedelta(days=30),END)
    d=L.select(s0,s1)
    top=d[d.passed].nlargest(10,"profit_factor").trader
    picked.append(fwd(L.signals(list(top),s1,t1,L.MAJORS)).assign(win=w//15+1))
    allsig.append(fwd(L.signals(list(d.trader),s1,t1,L.MAJORS)).assign(win=w//15+1))
P=pd.concat(picked); A=pd.concat(allsig)
def show(df,name):
    print(f"\n{name}: {len(df)} trades")
    out={}
    for h in H:
        x=df[f"{h}h"].dropna()
        out[f"{h}h"]={"avg move in trade direction":f"{x.mean():+.3%}","went their way":f"{(x>0).mean():.0%}","t-stat":f"{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}"}
    print(pd.DataFrame(out).to_string())
show(P,"SAFE ENGINE traders' new BTC/ETH/SOL trades")
show(A,"ALL scored traders' new BTC/ETH/SOL trades (bigger sample)")
for name,df in (("Safe Engine",P),("All traders",A)):
    print(f"\n{name} — split (24h and 72h move in trade direction):")
    for lab,sub in (("longs",df[df.dir==1]),("shorts",df[df.dir==-1]),
                    ("longs when BTC uptrend",df[(df.dir==1)&df.btc_up]),("shorts when BTC downtrend",df[(df.dir==-1)&~df.btc_up]),
                    ("against the trend",df[((df.dir==1)&~df.btc_up)|((df.dir==-1)&df.btc_up)])):
        print(f"  {lab:28} n={len(sub):4}  24h {sub['24h'].mean():+.2%} ({(sub['24h']>0).mean():.0%} right)   72h {sub['72h'].mean():+.2%} ({(sub['72h']>0).mean():.0%} right)")
print("\nBy window (All traders, 24h):", {w:f"{g['24h'].mean():+.2%}" for w,g in A.groupby('win')})
