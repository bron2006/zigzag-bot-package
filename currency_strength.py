"""Relative-currency graph, not independent predictions for correlated pairs."""
import math
import numpy as np

VERSION='currency-strength-hour-v1'


def select(returns):
    """Fit r(BASE/QUOTE)=strength(BASE)-strength(QUOTE), sum strengths=0.

    Strongest2 vs weakest2; choose ONE available pair with greatest fitted
    difference. Fixed rule, never chooses by future outcome or past pair wins.
    A disconnected graph cannot give a valid cross-component ranking.
    """
    if not returns:
        return None
    for pair,value in returns.items():
        if len(pair)!=6 or not pair.isascii() or not pair.isalpha() or pair!=pair.upper() or pair[:3]==pair[3:]:
            raise ValueError('invalid_currency_pair')
        if not math.isfinite(value):
            raise ValueError('invalid_return')
    pairs=sorted(returns)
    currencies=sorted({p[:3] for p in pairs}|{p[3:] for p in pairs})
    indices={c:i for i,c in enumerate(currencies)}
    matrix=np.zeros((len(pairs),len(currencies)))
    for i,p in enumerate(pairs):
        matrix[i,indices[p[:3]]]=1
        matrix[i,indices[p[3:]]]=-1
    if np.linalg.matrix_rank(matrix)!=len(currencies)-1:
        raise ValueError('disconnected_currency_graph')
    values=np.array([returns[p] for p in pairs])
    strength=np.linalg.lstsq(np.vstack([matrix,np.ones(len(currencies))]),np.append(values,0),rcond=None)[0]
    scores=dict(zip(currencies,map(float,strength)))
    ranked=sorted(currencies,key=lambda c:(scores[c],c))
    weak,strong=set(ranked[:2]),set(ranked[-2:])
    candidates=[]
    for p in pairs:
        difference=scores[p[:3]]-scores[p[3:]]
        direction=1 if p[:3] in strong and p[3:] in weak and difference>0 else -1 if p[:3] in weak and p[3:] in strong and difference<0 else 0
        if direction:
            candidates.append((abs(difference),p,direction))
    if not candidates:
        return None
    magnitude,pair,direction=sorted(candidates,key=lambda c:(-c[0],c[1]))[0]
    return dict(pair=pair,direction=direction,strengths=scores,difference=magnitude,
                residual_rms=float(np.sqrt(np.mean((matrix@strength-values)**2))))
