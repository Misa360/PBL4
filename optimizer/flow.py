"""Synthetic packet arrivals and causal Mbps forecasts; no access to future samples."""
import hashlib
import math
import random
from collections import deque
from .models import finite


class TrafficSource:
    def __init__(self, seed, key, base_mbps, pattern):
        self.rng=random.Random(int.from_bytes(hashlib.sha256(f'{seed}:{key}'.encode()).digest()[:8],'big'))
        self.base=base_mbps
        self.pattern=pattern
        self.phase=self.rng.uniform(0,2*math.pi)
        self.burst=False
        self.tick=0

    def sample(self):
        self.tick+=1
        if self.pattern=='steady':return self.base
        if self.pattern=='periodic':
            factor=1+.65*math.sin(self.phase+2*math.pi*self.tick/40)
        elif self.pattern=='trend':
            phase=(self.tick%80)/80
            factor=.35+1.3*(1-abs(2*phase-1))
        else:
            if self.rng.random()<.12:self.burst=not self.burst
            factor=1.8 if self.burst else .35
        # Poisson packet arrivals, 64 KiB/packet. Independent of the predictor.
        expected=max(0.,self.base*factor/0.524288)
        if expected==0:return 0.
        limit=math.exp(-expected);product=1.;count=0
        while product>limit:
            count+=1;product*=self.rng.random()
        return max(0,count-1)*.524288


class FlowForecaster:
    """Online AR(6), damped Holt and persistence; score before learning each sample."""
    def __init__(self, initial, horizon=6):
        finite(initial,'initial Mbps',0,1e9)
        if type(horizon) is not int or not 1 <= horizon <= 6:
            raise ValueError('Flow horizon must be an integer in [1,6]')
        self.level=initial;self.trend=0.;self.horizon=horizon;self.tick=0
        self.last=initial
        self.rows=deque(maxlen=60)
        self.pending={}
        self.errors={h:deque(maxlen=60) for h in range(1,horizon+1)}
        self.holt_errors={h:deque(maxlen=12) for h in range(1,horizon+1)}
        self.naive_errors={h:deque(maxlen=12) for h in range(1,horizon+1)}
        self.ar_errors={h:deque(maxlen=12) for h in range(1,horizon+1)}
        self.scale=max(1.,initial)
        self.lags=[initial/self.scale]*6
        self.weights=[0.,1.,0.,0.,0.,0.,0.]
        self.covariance=[[10. if i==j else 0. for j in range(7)] for i in range(7)]
        self._issue()

    def raw(self):
        return [max(0.,self.level+self.trend*sum(.9**j for j in range(1,h+1))) for h in range(1,self.horizon+1)]

    def _issue(self):
        raw=self.raw()
        ar=self._ar_forecast()
        self.strategies=[]
        for h in range(1,self.horizon+1):
            errors={'holt':sum(self.holt_errors[h]),'persistence':sum(self.naive_errors[h]),'ar':sum(self.ar_errors[h])}
            self.strategies.append(min(errors,key=errors.get) if len(self.holt_errors[h])>=6 else 'holt')
        self.strategy=self.strategies[0]
        candidates={'holt':raw,'ar':ar,'persistence':[self.last]*self.horizon}
        self.predictions=[candidates[name][i] for i,name in enumerate(self.strategies)]
        for h,predicted in enumerate(self.predictions,1):
            self.pending.setdefault(self.tick+h,[]).append((h,predicted,self.last,raw[h-1],ar[h-1]))

    def _ar_forecast(self):
        lags=self.lags[:];predictions=[]
        bound=max(1.,max(lags)*3)
        for _ in range(self.horizon):
            value=max(0.,min(bound,sum(a*b for a,b in zip(self.weights,[1.]+lags))))
            predictions.append(value*self.scale);lags=[value]+lags[:-1]
        return predictions

    def _learn_ar(self,actual):
        # Recursive least squares, six past samples; O(lags²) per observation.
        x=[1.]+self.lags
        px=[sum(a*b for a,b in zip(row,x)) for row in self.covariance]
        denominator=.98+sum(a*b for a,b in zip(x,px))
        gain=[v/denominator for v in px]
        error=actual/self.scale-sum(a*b for a,b in zip(self.weights,x))
        self.weights=[w+k*error for w,k in zip(self.weights,gain)]
        self.covariance=[[(self.covariance[i][j]-gain[i]*px[j])/.98 for j in range(7)] for i in range(7)]
        self.lags=[actual/self.scale]+self.lags[:-1]

    def observe(self, actual):
        finite(actual,'observed Mbps',0,1e9)
        self.tick+=1
        verified={}
        for h,predicted,naive,holt,ar in self.pending.pop(self.tick,[]):
            self.errors[h].append((abs(predicted-actual),abs(naive-actual)))
            verified[f'predicted_h{h}']=predicted
            self.holt_errors[h].append(abs(holt-actual));self.naive_errors[h].append(abs(naive-actual))
            self.ar_errors[h].append(abs(ar-actual))
        self.rows.append(dict(sample=self.tick,actual_mbps=actual,**verified))
        previous=self.level
        self.level=.6*actual+.4*(self.level+.9*self.trend)
        self.trend=.2*(self.level-previous)+.8*.9*self.trend
        self.last=actual
        self._learn_ar(actual)
        self._issue()

    def snapshot(self):
        metrics={str(h):dict(samples=len(values),mae_mbps=sum(a for a,b in values)/len(values) if values else None,
                            persistence_mae_mbps=sum(b for a,b in values)/len(values) if values else None)
                 for h,values in self.errors.items()}
        return dict(unit='Mbps',horizon_s=self.horizon,history=list(self.rows),forecast_mbps=list(self.predictions),
                    strategy=self.strategy,strategies=list(self.strategies),metrics=metrics,sample=self.tick,
                    source='synthetic packet arrivals; forecast uses past observations only')
