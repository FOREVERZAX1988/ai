import numpy as np
for r in ['00000071','00000072']:
    X=np.load(f'/tmp/rows_{r}.npy')
    zl=X[:,5].astype(int)  # bus2 zl (src==2)
    print(f"route {r}: bus2 zl 分布 -> 3:{100*np.mean(zl==3):.1f}% 4:{100*np.mean(zl==4):.1f}% 其他:{100*np.mean(~np.isin(zl,[3,4])):.1f}% (n={len(zl)})")
