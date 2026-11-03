"""One authoritative ECEF network, shared by the 3D view and the optimizer."""
import math
import random
from dataclasses import asdict
from .models import Node, Edge, EARTH_M, MU, capacity, channel_gain, elevation, finite, line_of_sight
from .traffic import forecast_utilization, TrafficForecaster, capacity_advice
from .flow import TrafficSource, FlowForecaster

CONSTELLATIONS = {
    'compact': {'small':(4,4,6,3,3), 'full':(10,10,12,6,3)},
    'balanced': {'small':(4,8,12,6,3), 'full':(10,20,24,12,3)},
    'dense': {'small':(4,12,24,12,3), 'full':(10,30,48,18,3)},
    # Only used to reconstruct archived datasets and historical experiments.
    'legacy': {'small':(4,4,2,0,0), 'full':(10,8,12,6,3)},
}


class Network:
    def __init__(self, size='small', reserve_fraction=.2, battery_j=1000, uav_count=None, deployment='distributed',
                 battery_profile='full', load_profile='idle', state_seed=42, forecast_load=False, constellation='balanced',
                 forecast_horizon=6, traffic_pattern='steady'):
        if size not in ('small', 'full'):
            raise ValueError('size must be small or full')
        if deployment not in ('regional','distributed'):
            raise ValueError('deployment must be regional or distributed')
        if constellation not in CONSTELLATIONS:
            raise ValueError('Unknown constellation profile')
        if deployment == 'regional' and constellation != 'legacy':
            raise ValueError('Regional placement is available only for archived legacy data')
        self.constellation = constellation
        finite(reserve_fraction, 'reserve_fraction', 0, .9)
        finite(battery_j, 'battery_j', 1, 1000000)
        if battery_profile not in ('full', 'mixed', 'weak', 'medium', 'strong'):
            raise ValueError('Unknown battery profile')
        if load_profile not in ('idle', 'mixed', 'busy'):
            raise ValueError('Unknown background load profile')
        if type(state_seed) is not int or not 0 <= state_seed <= 2147483647:
            raise ValueError('state_seed must be integer in [0, 2147483647]')
        self.battery_profile, self.load_profile, self.state_seed = battery_profile, load_profile, state_seed
        if type(forecast_load) is not bool:
            raise ValueError('forecast_load must be boolean')
        self.forecast_load = forecast_load
        if type(forecast_horizon) is not int or not 1 <= forecast_horizon <= 24:
            raise ValueError('forecast_horizon must be an integer in [1,24]')
        self.forecast_horizon = forecast_horizon
        if traffic_pattern not in ('steady','periodic','trend','bursty'):
            raise ValueError('Unknown temporal traffic pattern')
        self.traffic_pattern=traffic_pattern
        self.flow_sources={};self.flow_forecasters={}
        self.offered_mbps={};self._flow_area={}
        self.traffic_sample_s = 1.0
        self.traffic_pending_s = 0.0
        self.traffic_observations = 0
        self._traffic_area = {}
        self._background_area = {}
        self.traffic_scores = {}
        self.background_scores = {}
        self.background_forecasters = {}
        self.load_history = {}
        self.forecasters: dict[str, TrafficForecaster] = {}
        self.size, self.reserve_fraction = size, reserve_fraction
        self.deployment=deployment
        self.station_names={}
        self.time_s = 0.0
        self.revision = 0
        self.nodes = {}
        ng, nu, nl, nm, ngeo = CONSTELLATIONS[constellation][size]
        if uav_count is not None:
            if type(uav_count) is not int or not 2 <= uav_count <= 32 or uav_count % 2:
                raise ValueError('uav_count must be even, in [2, 32]')
            nu = uav_count
        self.uav_count = nu
        # Synthetic demonstration sites; not measured ground-station deployments.
        sites=[('Bắc Mỹ',40.7,-74),('Châu Âu',41.9,12.5),('Đông Nam Á',16,108.2),('Đông Á',35.7,139.7),('Châu Đại Dương',-33.9,151.2)] if size=='full' else [('Vùng Tây',0,102),('Vùng Đông',0,114)]
        if size == 'small' and constellation != 'legacy':
            sites = [('Bắc Mỹ',40.7,-74),('Đông Nam Á',16,108.2)]
        for i in range(ng):
            if deployment=='distributed':
                name,lat,lon=sites[i//2]
                self.station_names[f'G{i+1}']=f'{name} {i%2+1}'
                lat+=(i%2*2-1)*.18
            else:
                lat,lon=(i % (ng//2))*.006,108 + (i//(ng//2))*.24
            self.add(Node(f'G{i+1}', 'ground', 10e6, 2, None, None,
                          lat=lat,lon=lon))
        for i in range(nu):
            if deployment=='distributed':
                _,lat,lon=sites[i%len(sites)]
            else:
                lat,lon=.006+(i % (nu//2))*.003,108+(i//(nu//2))*.24
            self.add(Node(f'U{i+1}', 'UAV', 10e6, 2, battery_j, battery_j,
                          lat=lat,lon=lon,
                          altitude_m=2000, phase=i*math.pi))
        for kind, count, altitude, factor in [('LEO', nl, 550000, 3), ('MEO', nm, 20200000, 10), ('GEO', ngeo, 35786000, 0)]:
            for i in range(count):
                # Include a local pair at t=0; remaining satellites span the globe.
                phase = math.radians(i*12) if count == 2 else 2*math.pi*i/count
                longitude, inclination = 108, 0 if i % 3 == 0 else 30
                if constellation != 'legacy' and kind != 'GEO':
                    planes = min(6 if kind == 'LEO' else 3, count)
                    plane, slot = i % planes, i // planes
                    slots = math.ceil(count/planes)
                    longitude = -180+360*plane/planes
                    phase = 2*math.pi*(slot+plane/planes)/slots
                    inclination = 53 if kind == 'LEO' else 56
                self.add(Node(f'{kind}{i+1}', kind, 20e6, 5, battery_j*factor if factor else None,
                              battery_j*factor if factor else None, lon=longitude if kind != 'GEO' else (-80+i*120 if deployment=='distributed' else 108+(i-1)*70),
                              altitude_m=altitude, phase=phase, inclination=inclination))

        rng = random.Random(state_seed)
        ranges = {'weak':(.08,.19), 'medium':(.35,.65), 'strong':(.8,1.)}
        for kind in ('UAV', 'LEO', 'MEO'):
            group = [n for n in self.nodes.values() if n.kind == kind]
            rng.shuffle(group)
            for i, node in enumerate(group):
                if battery_profile != 'full':
                    level = ('weak','medium','strong')[i % 3] if battery_profile == 'mixed' else battery_profile
                    node.battery_j = node.battery_capacity_j*rng.uniform(*ranges[level])
        load_rng = random.Random(state_seed ^ 0x51A6)
        group = list(self.nodes.values())
        load_rng.shuffle(group)
        for i, node in enumerate(group):
            fraction = 0 if load_profile == 'idle' else load_rng.uniform(.7,.95) if load_profile == 'busy' else load_rng.uniform(*((0,.1),(.25,.5),(.7,.95))[i % 3])
            node.reserved_bandwidth_hz = fraction*node.bandwidth_hz
            slope = load_rng.uniform(-.06,.06)
            history = [max(0., min(1., fraction-slope*(5-j))) for j in range(6)] if load_profile != 'idle' else [0.]*6
            self.load_history[node.id] = history
            # Build per-node forecaster seeded from synthetic history
            fc = TrafficForecaster()
            fc.seed(history)
            self.forecasters[node.id] = fc
            background=TrafficForecaster();background.seed(history)
            self.background_forecasters[node.id]=background
            # Reference spectral efficiency 2 bit/s/Hz converts offered background
            # Mbps into reserved bandwidth; it is not the end-to-end Shannon rate.
            initial_mbps=fraction*node.bandwidth_hz*2/1e6
            self.flow_sources[node.id]=TrafficSource(state_seed,node.id,initial_mbps,traffic_pattern)
            self.flow_forecasters[node.id]=FlowForecaster(initial_mbps)
            self.offered_mbps[node.id]=initial_mbps
            if traffic_pattern!='steady':
                self.offered_mbps[node.id]=self.flow_sources[node.id].sample()
                node.reserved_bandwidth_hz=min(.98,self.offered_mbps[node.id]*1e6/(2*node.bandwidth_hz))*node.bandwidth_hz
            if forecast_load:
                node.predicted_reserved_bandwidth_hz = fc.next_utilisation * node.bandwidth_hz

    def add(self, node):
        self.nodes[node.id] = node

    def update_traffic(self, node_id: str, observed_fraction: float, background_fraction=None) -> None:
        """Push a new traffic observation and refresh predicted bandwidth.

        Called after each transmission or clock advance to keep forecasters
        up-to-date.  The node's predicted_reserved_bandwidth_hz is updated
        so the next optimizer call uses the freshest forecast.
        """
        if node_id not in self.nodes or node_id not in self.forecasters:
            return
        finite(observed_fraction,'utilization',0,1)
        background_fraction=observed_fraction if background_fraction is None else finite(background_fraction,'background utilization',0,1)
        prediction=self.forecasters[node_id].next_utilisation
        previous=self.load_history.get(node_id,[0.])[-1]
        self.forecasters[node_id].update(observed_fraction)
        self._score(self.traffic_scores,node_id,prediction,previous,observed_fraction)
        background=self.background_forecasters[node_id]
        previous_bg=background.last_observation
        self._score(self.background_scores,node_id,background.next_utilisation,previous_bg,background_fraction)
        background.update(background_fraction)
        # Update load_history for snapshot display
        history = self.load_history.get(node_id, [])
        history.append(observed_fraction)
        self.load_history[node_id] = history[-12:]
        node = self.nodes[node_id]
        score=self._score_summary(self.background_scores,node_id)
        reliable=score['scored_samples']<6 or score['mae']<=score['persistence_mae']+1e-12
        predicted=background.next_utilisation if reliable else background_fraction
        node.predicted_reserved_bandwidth_hz = predicted*node.bandwidth_hz if self.forecast_load else 0.

    @staticmethod
    def _score(store,key,predicted,previous,observed):
        score=store.setdefault(key,dict(count=0,errors=[],persistence=[]))
        score['count']+=1
        score['errors']=(score['errors']+[abs(predicted-observed)])[-12:]
        score['persistence']=(score['persistence']+[abs(previous-observed)])[-12:]

    @staticmethod
    def _score_summary(store,key):
        score=store.get(key,{})
        errors=score.get('errors',[])
        return dict(scored_samples=score.get('count',0),error_window=len(errors),
                    mae=sum(errors)/len(errors) if errors else None,
                    persistence_mae=sum(score['persistence'])/len(errors) if errors else None)

    def observe_interval(self, elapsed, segments=(), evolve_background=False):
        """Integrate actual radio airtime plus background into fixed one-second samples.

        One sample per node per window, including idle nodes. Propagation consumes
        time but no Tx/Rx airtime. No future requests enter the forecaster.
        """
        cursor = 0.
        prior_samples=self.traffic_observations
        while cursor < elapsed-1e-12:
            dt = min(elapsed-cursor, self.traffic_sample_s-self.traffic_pending_s)
            for key,node in self.nodes.items():
                area = node.reserved_bandwidth_hz/node.bandwidth_hz*dt
                self._background_area[key]=self._background_area.get(key,0.)+area
                self._flow_area[key]=self._flow_area.get(key,0.)+self.offered_mbps[key]*dt
                for segment in segments:
                    if key in (segment['source'],segment['target']):
                        overlap=max(0.,min(cursor+dt,segment['end_s'])-max(cursor,segment['start_s']))
                        area += segment['bandwidth_hz']/node.bandwidth_hz*overlap
                self._traffic_area[key]=self._traffic_area.get(key,0.)+area
            cursor += dt
            self.traffic_pending_s += dt
            if self.traffic_pending_s >= self.traffic_sample_s-1e-10:
                for key in self.nodes:
                    self.update_traffic(key,min(1.,self._traffic_area[key]/self.traffic_sample_s),
                                        min(1.,self._background_area[key]/self.traffic_sample_s))
                    rate=self._flow_area[key]/self.traffic_sample_s
                    self.flow_forecasters[key].observe(rate)
                    if self.traffic_pattern!='steady':
                        node=self.nodes[key]
                        predicted=self.flow_forecasters[key].predictions[0]*1e6/(2*node.bandwidth_hz)
                        node.predicted_reserved_bandwidth_hz=min(1.,predicted)*node.bandwidth_hz if self.forecast_load else 0.
                self.traffic_observations += 1
                self.traffic_pending_s=0.
                self._traffic_area={}
                self._background_area={}
                self._flow_area={}
                if evolve_background and self.traffic_pattern!='steady':
                    self._next_background()
        # A whole-message transfer keeps its resource snapshot frozen; arrivals
        # advance after commit so the next request observes the new background.
        if not evolve_background and self.traffic_pattern!='steady':
            for _ in range(self.traffic_observations-prior_samples):self._next_background()

    def _next_background(self):
        for key,node in self.nodes.items():
            rate=self.flow_sources[key].sample()
            self.offered_mbps[key]=rate
            node.reserved_bandwidth_hz=min(.98,rate*1e6/(2*node.bandwidth_hz))*node.bandwidth_hz

    def forecast_all(self, steps: int | None = None, node_id=None) -> dict:
        """Return multi-step traffic forecast for every node.

        Parameters
        ----------
        steps : int, optional
            Forecast horizon; defaults to ``self.forecast_horizon``.

        Returns
        -------
        dict mapping node_id → forecast dict (see TrafficForecaster.forecast).
        """
        h = steps if steps is not None else self.forecast_horizon
        selected=self.forecasters.items() if node_id is None else [(node_id,self.forecasters[node_id])]
        result={}
        for key,fc in selected:
            flow=self.flow_forecasters[key].snapshot()
            result[key]={**fc.forecast(h),**self.forecast_score(key),**self.background_advice(key,flow),
                'observations':self.traffic_observations,'sample_s':self.traffic_sample_s,
                'pending_s':self.traffic_pending_s,'flow':flow,'enabled':self.forecast_load,
                'interval_kind':'heuristic residual band, not calibrated confidence',
                'source':'simulated measured airtime + background; initial history synthetic'}
        return result

    def forecast_score(self,node_id):
        return self._score_summary(self.traffic_scores,node_id)

    def background_advice(self,key,flow=None):
        node=self.nodes[key];fc=self.background_forecasters[key]
        score=self._score_summary(self.background_scores,key)
        current=node.reserved_bandwidth_hz/node.bandwidth_hz
        prediction=fc.next_utilisation
        if self.traffic_pattern!='steady':
            flow=flow if flow is not None else self.flow_forecasters[key].snapshot()
            metric=flow['metrics']['1']
            score=dict(scored_samples=metric['samples'],mae=metric['mae_mbps'],persistence_mae=metric['persistence_mae_mbps'])
            prediction=min(1.,flow['forecast_mbps'][0]*1e6/(2*node.bandwidth_hz))
        return dict(background_fraction=current,background_forecast=prediction,
                    planning_fraction=node.predicted_reserved_bandwidth_hz/node.bandwidth_hz,
                    background_score=score,
                    capacity_advice=capacity_advice(current,prediction,score['scored_samples'],
                        score['mae'],score['persistence_mae'],self.forecast_load))

    def available(self, node):
        return node.planning_bandwidth_hz > 0 and (node.battery_j is None or node.battery_fraction > self.reserve_fraction + 1e-12)

    def edges(self, time_s=None):
        time_s = self.time_s if time_s is None else time_s
        coords = {n.id: n.coordinates(time_s) for n in self.nodes.values()}
        edges = {}
        nodes = list(self.nodes.values())
        for i, a in enumerate(nodes):
            if not self.available(a):
                continue
            for b in nodes[i+1:]:
                if not self.available(b):
                    continue
                kinds = {a.kind, b.kind}
                distance = math.dist(coords[a.id], coords[b.id])
                if kinds == {'ground', 'UAV'}:
                    limit, antenna_db = (50000 if self.deployment=='distributed' else 6000), 4
                elif a.kind == b.kind == 'UAV':
                    limit, antenna_db = 10000, 4
                elif 'UAV' in kinds and kinds & {'LEO', 'MEO', 'GEO'}:
                    sat = a if a.kind != 'UAV' else b
                    uav = b if sat is a else a
                    if elevation(coords[uav.id], coords[sat.id]) < 10:
                        continue
                    limit = {'LEO': 3500000, 'MEO': 28000000, 'GEO': 43000000}[sat.kind]
                    antenna_db = 56 if self.deployment=='distributed' else 50  # aggregate Tx+Rx gain; synthetic link-budget profiles
                elif a.kind in ('LEO', 'MEO', 'GEO') and b.kind in ('LEO', 'MEO', 'GEO'):
                    limit, antenna_db = 50000000, 60
                else:
                    continue
                if distance <= limit and line_of_sight(coords[a.id], coords[b.id]):
                    gain = channel_gain(distance, antenna_db)
                    edges[a.id, b.id] = Edge(a.id, b.id, distance, gain)
                    edges[b.id, a.id] = Edge(b.id, a.id, distance, gain)
        return edges

    def snapshot(self):
        edges = self.edges()
        return {'size': self.size, 'deployment':self.deployment,'uav_count': self.uav_count, 'time_s': self.time_s, 'revision': self.revision,
                'constellation':self.constellation, 'coverage':self.coverage(edges),
                'battery_profile':self.battery_profile, 'load_profile':self.load_profile, 'state_seed':self.state_seed,
                'forecast_load':self.forecast_load,'forecast_horizon':self.forecast_horizon,
                'traffic_pattern':self.traffic_pattern, 'traffic_history':self.load_history,
                'forecast_method': 'Holt double exponential smoothing',
                'traffic_forecast': self.forecast_all(),
                'reserve_fraction': self.reserve_fraction,
                'nodes': [{**asdict(n), 'name':self.station_names.get(n.id,n.id),'position_m': n.coordinates(self.time_s),
                           'battery_fraction': n.battery_fraction, 'available': self.available(n),
                           'battery_level': n.battery_level, 'available_bandwidth_hz':n.available_bandwidth_hz,
                           'planning_bandwidth_hz':n.planning_bandwidth_hz,
                           'period_s': 2*math.pi*math.sqrt((EARTH_M+n.altitude_m)**3/MU) if n.kind in ('LEO', 'MEO') else 86164.0905 if n.kind == 'GEO' else None}
                          for n in self.nodes.values()],
                'links': [{'source': a, 'target': b, 'distance_m': e.distance_m, 'gain': e.gain,
                           'max_rate_bps': capacity(min(self.nodes[a].available_bandwidth_hz, self.nodes[b].available_bandwidth_hz), self.nodes[a].p_max_w, e.gain)}
                          for (a, b), e in edges.items()]}

    def coverage(self, edges=None):
        """Ground-pair reachability without permitting ground transit traffic."""
        edges = self.edges() if edges is None else edges
        relays = {key for key,node in self.nodes.items() if node.kind != 'ground'}
        adjacency = {key:set() for key in self.nodes}
        for a,b in edges:
            adjacency[a].add(b)
        components = {}
        for start in relays:
            if start in components:
                continue
            component = len(components)
            stack = [start]
            components[start] = component
            while stack:
                for nxt in adjacency[stack.pop()] & relays:
                    if nxt not in components:
                        components[nxt] = component
                        stack.append(nxt)
        grounds = [key for key,node in self.nodes.items() if node.kind == 'ground']
        memberships = {key:{components[n] for n in adjacency[key] if n in components} for key in grounds}
        connected = sum(bool(memberships[a] & memberships[b]) for i,a in enumerate(grounds) for b in grounds[i+1:])
        return dict(connected_pairs=connected,total_pairs=len(grounds)*(len(grounds)-1)//2,
                    uncovered_stations=[key for key in grounds if not memberships[key]],
                    note='Topology reachability only; bandwidth, battery and demand feasibility are checked separately')
