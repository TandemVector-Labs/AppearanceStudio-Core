"""Pure, bounded Linux telemetry and menu model for Appearance Studio Monitor.

No subprocesses, D-Bus, global settings, network requests, or service mutations.
Missing readings remain None; diagnostic export uses a strict data allowlist.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import json, math, re, time

INTERVALS=(5,10,30)
DEFAULTS={'schema':1,'interval':5,'sensor':'auto','interface':'auto','alerts':False,
          'cpu_high':90,'memory_high':90,'temperature_high':90,'battery_low':15}
NAME=re.compile(r'^[A-Za-z0-9_.:-]{1,64}$')
SENSOR=re.compile(r'^(thermal_zone[0-9]+|hwmon[0-9]+_temp[0-9]+)$')
HEX=re.compile(r'^#[0-9a-fA-F]{6}$')

def text(path:Path,limit:int=65536)->str:
    try:
        with path.open('r',encoding='utf8',errors='strict') as f:
            value=f.read(limit+1)
        return value.strip() if len(value)<=limit else ''
    except (OSError,UnicodeError):return ''

def integer(path:Path):
    s=text(path,128)
    try:return int(s)
    except ValueError:return None

def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def clean_label(v):return ''.join(c for c in str(v) if c.isprintable())[:64]
def validate_settings(d):
    if not isinstance(d,dict) or set(d)-set(DEFAULTS):raise ValueError('unknown monitor settings')
    result={**DEFAULTS,**d}
    if type(result['schema']) is not int or result['schema']!=1:raise ValueError('schema')
    if type(result['interval']) is not int or result['interval'] not in INTERVALS:raise ValueError('interval')
    if type(result['alerts']) is not bool:raise ValueError('alerts')
    if not isinstance(result['sensor'],str) or (result['sensor']!='auto' and not SENSOR.fullmatch(result['sensor'])):raise ValueError('sensor')
    if not isinstance(result['interface'],str) or (result['interface']!='auto' and not NAME.fullmatch(result['interface'])):raise ValueError('interface')
    for key,low,high in [('cpu_high',50,100),('memory_high',50,100),('temperature_high',50,120),('battery_low',5,40)]:
        if type(result[key]) is not int or not low<=result[key]<=high:raise ValueError(key)
    return result

def cpu_ticks(raw):
    line=raw.splitlines()[0].split() if raw else []
    if len(line)<5 or line[0]!='cpu':return None
    try:values=[int(v) for v in line[1:9]]
    except ValueError:return None
    if any(v<0 for v in values):return None
    # user/nice already include guest/guest_nice. Sum only first eight fields.
    idle=values[3]+(values[4] if len(values)>4 else 0)
    return sum(values),idle

def cpu_percent(previous,current):
    if previous is None or current is None:return None
    dt,di=current[0]-previous[0],current[1]-previous[1]
    if dt<=0 or di<0 or di>dt:return None
    return round(100*(dt-di)/dt)

def memory_percent(raw):
    values={}
    for line in raw.splitlines():
        parts=line.split()
        if len(parts)>=2:
            try:values[parts[0].rstrip(':')]=int(parts[1])
            except ValueError:pass
    total=values.get('MemTotal',0)
    if total<=0:return None
    available=values.get('MemAvailable')
    if available is None:
        if 'MemFree' not in values:return None
        available=sum(values.get(k,0) for k in ('MemFree','Buffers','Cached','SReclaimable'))-values.get('Shmem',0)
    return round(100*(1-max(0,min(total,available))/total))

def discover_temperatures(sys:Path):
    result=[]
    for p in sorted((sys/'class/thermal').glob('thermal_zone*'))[:64]:
        if not SENSOR.fullmatch(p.name):continue
        v=integer(p/'temp')
        result.append({'id':p.name,'label':clean_label(text(p/'type',256) or p.name),'c':round(v/1000,1) if v is not None and -40000<=v<=150000 else None,'priority':2})
    for h in sorted((sys/'class/hwmon').glob('hwmon*'))[:32]:
        name=clean_label(text(h/'name',256))
        for p in sorted(h.glob('temp*_input'))[:16]:
            ident=h.name+'_'+p.name.replace('_input','')
            if not SENSOR.fullmatch(ident):continue
            v=integer(p); label=clean_label(text(p.with_name(p.name.replace('_input','_label')),256) or p.name[:-6])
            result.append({'id':ident,'label':f'{name} {label}'.strip(),'c':round(v/1000,1) if v is not None and -40000<=v<=150000 else None,'priority':0 if name in ('k10temp','coretemp','zenpower') else 1 if 'CPU' in label.upper() else 3})
    return result[:128]

def choose_temperature(sensors,selected):
    valid=[s for s in sensors if finite(s.get('c'))]
    if selected!='auto':return next((s for s in sensors if s['id']==selected),{'id':selected,'label':'Selected sensor unavailable','c':None})
    return min(valid,key=lambda s:(s['priority'],-s['c'],s['id'])) if valid else {'id':'auto','label':'No temperature sensor','c':None}

def batteries(sys):
    readings=[]
    for p in sorted((sys/'class/power_supply').glob('*'))[:32]:
        if text(p/'type',64)!='Battery' or integer(p/'present')==0:continue
        cap=integer(p/'capacity');cap=cap if cap is not None and 0<=cap<=100 else None;capacity_reported=cap is not None
        full,now=integer(p/'energy_full'),integer(p/'energy_now')
        if not (full and full>0 and now is not None and 0<=now<=full*1.2):
            qf,qn,voltage=integer(p/'charge_full'),integer(p/'charge_now'),integer(p/'voltage_min_design')
            if qf and qf>0 and qn is not None and 0<=qn<=qf*1.2 and voltage and voltage>0:full,now=qf*voltage/1e6,qn*voltage/1e6
            else:full,now=None,None
        if cap is None and full:cap=round(max(0,min(100,100*now/full)))
        readings.append({'id':clean_label(p.name),'percent':cap,'state':clean_label(text(p/'status',64)) or 'Unknown','energy_now':now,'energy_full':full,'capacity_reported':capacity_reported})
    if len(readings)==1 and readings[0]['percent'] is not None:
        # Match the kernel's displayed capacity on a single battery. Energy
        # aggregation is needed for multiple packs, not to introduce rounding
        # disagreement with the system battery indicator.
        pct=readings[0]['percent'];method='capacity-single' if readings[0]['capacity_reported'] else 'energy-derived-single'
    elif readings and all(r['energy_full'] for r in readings):
        pct=round(max(0,min(100,100*sum(r['energy_now'] for r in readings)/sum(r['energy_full'] for r in readings))))
        method='energy-weighted'
    else:
        caps=[r['percent'] for r in readings if r['percent'] is not None]
        pct=round(sum(caps)/len(caps)) if caps else None;method='capacity-mean' if caps else 'unavailable'
    return {'percent':pct,'method':method,'items':readings}

def route_candidates(ipv4,ipv6):
    routes=[]
    for line in ipv4.splitlines()[1:]:
        p=line.split()
        if len(p)<8 or not NAME.fullmatch(p[0]):continue
        try:
            if p[1]=='00000000' and p[7]=='00000000' and int(p[3],16)&1:routes.append((int(p[6]),p[0]))
        except ValueError:continue
    for line in ipv6.splitlines():
        p=line.split()
        if len(p)<10 or not NAME.fullmatch(p[-1]):continue
        try:
            if p[0]=='0'*32 and p[1]=='00' and int(p[8],16)&1:routes.append((int(p[5],16),p[-1]))
        except ValueError:continue
    return sorted(set(routes))

def interfaces(sys):
    result=[]
    for p in sorted((sys/'class/net').glob('*'))[:64]:
        if p.name=='lo' or not NAME.fullmatch(p.name):continue
        state=text(p/'operstate',64)
        # Tunnels often report unknown while a default route proves usability.
        result.append({'id':p.name,'state':state,'usable':state in ('up','unknown') or integer(p/'carrier')==1})
    return result

def choose_interface(items,routes,selected):
    valid={r['id'] for r in items if r['usable']}
    if selected!='auto':return selected if selected in valid else ''
    for metric,name in routes:
        if name in valid:return name
    return sorted(valid)[0] if valid else ''

def network_counters(sys,iface):
    if not iface or not NAME.fullmatch(iface):return None
    p=sys/'class/net'/iface/'statistics';a,b=integer(p/'rx_bytes'),integer(p/'tx_bytes')
    return (a,b) if a is not None and b is not None and a>=0 and b>=0 else None

def network_rates(previous,current,elapsed):
    if previous is None or current is None or elapsed<=0:return None,None
    if current[0]<previous[0] or current[1]<previous[1]:return None,None
    return round((current[0]-previous[0])/elapsed),round((current[1]-previous[1])/elapsed)

def disk_counters(proc,sys):
    # Aggregate top-level physical block devices only. Partitions and mapper
    # devices are excluded to avoid double-counting the same I/O.
    devices=set()
    for dev in sorted((sys/'block').glob('*'))[:64]:
        name=dev.name
        if name.startswith(('loop','ram','zram','dm-','md')):
            continue
        ident=text(dev/'dev',64)
        if re.fullmatch(r'[0-9]+:[0-9]+',ident):
            devices.add(ident)
    read_sectors=write_sectors=0
    matched=0
    for line in text(proc/'diskstats',262144).splitlines():
        fields=line.split()
        if len(fields)<10:
            continue
        ident=fields[0]+':'+fields[1]
        if ident not in devices:
            continue
        try:
            read_sectors+=int(fields[5]);write_sectors+=int(fields[9]);matched+=1
        except ValueError:
            continue
    return (read_sectors*512,write_sectors*512) if matched else None

def disk_rates(previous,current,elapsed):
    return network_rates(previous,current,elapsed)

def percentage(x):return f'{int(round(x))}%' if finite(x) else '—'
def rate(x):
    if not finite(x) or x<0:return '—'
    if x>=1024**2:return f'{x/1024**2:.1f}M'
    if x>=1024:return f'{x/1024:.0f}K'
    return f'{x:.0f}B'
def spark(values,limit=24):
    chars='▁▂▃▄▅▆▇█'
    return ''.join(chars[max(0,min(7,int(float(v)*7/100)))] if finite(v) else '·' for v in list(values)[-limit:]) or '·'

def rate_spark(values,limit=18):
    chars='▁▂▃▄▅▆▇█'
    rows=list(values)[-limit:]
    good=[float(v) for v in rows if finite(v) and v>=0]
    peak=max(good) if good else 0.0
    if peak<=0:
        return ''.join('▁' if finite(v) and v>=0 else '·' for v in rows) or '·'
    return ''.join(chars[max(0,min(7,int(float(v)*7/peak)))] if finite(v) and v>=0 else '·' for v in rows) or '·'

def palette(slug,catalog,runtime,last):
    spec=catalog.get(slug,{})
    a,b=spec.get('accent'),spec.get('accent2')
    if isinstance(runtime,dict) and runtime.get('theme')==slug:
        a,b=runtime.get('accent',a),runtime.get('accent2',b)
    if not isinstance(a,str) or not HEX.fullmatch(a):return dict(last)
    if not isinstance(b,str) or not HEX.fullmatch(b):b=a
    return {'theme':slug,'accent':a.lower(),'accent2':b.lower()}

class AlertLatch:
    def __init__(self):self.active={};self.last={}
    def evaluate(self,snapshot,settings,now):
        if not settings['alerts'] or snapshot.get('stale'):
            self.active.clear();return []
        alerts=[]
        for metric,key,direction,gap in [('cpu_percent','cpu_high','high',5),('memory_percent','memory_high','high',5),('temperature_c','temperature_high','high',5),('battery_percent','battery_low','low',5)]:
            value=snapshot.get(metric)
            if not finite(value):continue
            limit=settings[key];hot=value>=limit if direction=='high' else value<=limit
            clear=value<=limit-gap if direction=='high' else value>=limit+gap
            if clear:self.active[metric]=False
            if hot and not self.active.get(metric,False):
                self.active[metric]=True
                if now-self.last.get(metric,-1e9)>=60:
                    self.last[metric]=now;alerts.append({'metric':metric,'value':value,'threshold':limit})
        return alerts

class Collector:
    def __init__(self,proc=Path('/proc'),sys=Path('/sys'),clock=time.monotonic):
        self.proc=proc;self.sys=sys;self.clock=clock
        self.previous_cpu=None;self.previous_net=None;self.previous_disk=None
        self.previous_time=None;self.iface='';self.last_success=None
        self.cpu_history=deque(maxlen=60);self.memory_history=deque(maxlen=60)
        self.network_history=deque(maxlen=60);self.disk_history=deque(maxlen=60)
    def collect(self,settings):
        now=self.clock()
        ticks=cpu_ticks(text(self.proc/'stat'));cpu=cpu_percent(self.previous_cpu,ticks);self.previous_cpu=ticks
        memory=memory_percent(text(self.proc/'meminfo'))
        sensors=discover_temperatures(self.sys);temp=choose_temperature(sensors,settings['sensor']);bat=batteries(self.sys)
        nets=interfaces(self.sys);routes=route_candidates(text(self.proc/'net/route'),text(self.proc/'net/ipv6_route'))
        iface=choose_interface(nets,routes,settings['interface']);current_net=network_counters(self.sys,iface)
        elapsed=now-self.previous_time if self.previous_time is not None else 0
        previous_net=self.previous_net if iface==self.iface else None
        rx,tx=network_rates(previous_net,current_net,elapsed)
        current_disk=disk_counters(self.proc,self.sys)
        disk_read,disk_write=disk_rates(self.previous_disk,current_disk,elapsed)
        self.iface=iface;self.previous_net=current_net;self.previous_disk=current_disk;self.previous_time=now
        good=ticks is not None and memory is not None
        if good:self.last_success=now
        age=None if self.last_success is None else max(0,now-self.last_success)
        stale=age is None or age>max(15,settings['interval']*2.5)
        self.cpu_history.append(cpu);self.memory_history.append(memory)
        self.network_history.append(max(v for v in (rx,tx) if finite(v)) if any(finite(v) for v in (rx,tx)) else None)
        self.disk_history.append(max(v for v in (disk_read,disk_write) if finite(v)) if any(finite(v) for v in (disk_read,disk_write)) else None)
        return {
            'cpu_percent':cpu,'memory_percent':memory,'temperature_c':temp['c'],
            'sensor':temp['id'],'sensor_label':temp['label'],'sensors':sensors,
            'battery_percent':bat['percent'],'battery_method':bat['method'],'batteries':bat['items'],
            'iface':iface,'interfaces':nets,'rx_bytes_s':rx,'tx_bytes_s':tx,
            'disk_read_bytes_s':disk_read,'disk_write_bytes_s':disk_write,
            'sample_age_s':None if age is None else round(age,1),'stale':stale,'source_ok':good,
            'cpu_graph':spark(self.cpu_history),'memory_graph':spark(self.memory_history),
            'network_graph':rate_spark(self.network_history),'disk_graph':rate_spark(self.disk_history),
            'history_samples':len(self.cpu_history)
        }

def label(snapshot):
    prefix='STALE · ' if snapshot.get('stale') else ''
    temp=snapshot.get('temperature_c');temp=f'{round(temp)}°' if finite(temp) else '—°'
    battery=snapshot.get('battery_percent');tail=' '+percentage(battery) if finite(battery) else ''
    net='N↓'+rate(snapshot.get('rx_bytes_s'))+' ↑'+rate(snapshot.get('tx_bytes_s'))
    disk='D↓'+rate(snapshot.get('disk_read_bytes_s'))+' ↑'+rate(snapshot.get('disk_write_bytes_s'))
    return f"{prefix}{temp} {percentage(snapshot.get('cpu_percent'))} {percentage(snapshot.get('memory_percent'))} {net} {disk}{tail}"

def diagnostic(snapshot,settings):
    allowed=(
        'theme','accent','cpu_percent','memory_percent','temperature_c','battery_percent','battery_method',
        'rx_bytes_s','tx_bytes_s','disk_read_bytes_s','disk_write_bytes_s',
        'stale','source_ok','sample_age_s','interval','registered','build_id',
        'cpu_graph','memory_graph','network_graph','disk_graph','history_samples'
    )
    return {
        'schema':1,
        'privacy':'No username, host, IP, MAC, serial, process list, file paths, interface names or disk device names',
        'metrics':{k:snapshot.get(k) for k in allowed},
        'battery_count':len(snapshot.get('batteries',[])),
        'available_temperature_count':len(snapshot.get('sensors',[])),
        'alert_enabled':settings['alerts'],
        'sample_time_unix':snapshot.get('updated_at'),'exported_at':int(time.time()),
        'units':{
            'cpu_percent':'percent','memory_percent':'percent','temperature_c':'celsius','battery_percent':'percent',
            'rx_bytes_s':'bytes/second','tx_bytes_s':'bytes/second',
            'disk_read_bytes_s':'bytes/second','disk_write_bytes_s':'bytes/second','sample_age_s':'seconds'
        },
        'sources':{
            'cpu':'proc-stat','memory':'proc-meminfo',
            'temperature':clean_label(snapshot.get('sensor_label','unavailable')),
            'battery':snapshot.get('battery_method','unavailable'),
            'network':'selected-route-interface','disk':'proc-diskstats-top-level-physical'
        }
    }

@dataclass
class Entry:
    id:int
    label:str=''
    enabled:bool=False
    kind:str='standard'
    radio:bool|None=None

def menu_entries(snapshot,settings,registered,exported=False):
    d=snapshot
    entries=[
        Entry(1,'Appearance Studio · '+d.get('theme','—')),
        Entry(2,'CPU   '+percentage(d.get('cpu_percent'))),Entry(3,d.get('cpu_graph','·')),
        Entry(4,'RAM   '+percentage(d.get('memory_percent'))),Entry(5,d.get('memory_graph','·'))
    ]
    tc=d.get('temperature_c');entries.append(Entry(6,'Temperature   '+(f'{tc:.1f} °C' if finite(tc) else 'Unavailable')))
    entries.append(Entry(7,'Sensor   '+d.get('sensor_label','—')))
    entries += [
        Entry(8,'Network   '+(d.get('iface') or 'Offline')),
        Entry(9,'↓ '+rate(d.get('rx_bytes_s'))+'/s     ↑ '+rate(d.get('tx_bytes_s'))+'/s'),
        Entry(13,'Network   '+d.get('network_graph','·')),
        Entry(14,'Disk I/O   ↓ '+rate(d.get('disk_read_bytes_s'))+'/s     ↑ '+rate(d.get('disk_write_bytes_s'))+'/s'),
        Entry(15,'Disk I/O   '+d.get('disk_graph','·')),
        Entry(10,'Battery   '+percentage(d.get('battery_percent'))+' · '+d.get('battery_method','unavailable'))
    ]
    for i,battery in enumerate(d.get('batteries',[])[:8]):
        entries.append(Entry(20+i,battery['id']+'   '+percentage(battery['percent'])+' · '+battery['state']))
    age=d.get('sample_age_s');fresh='STALE' if d.get('stale') else 'Fresh' if d.get('source_ok') else 'Source temporarily unavailable'
    entries += [Entry(11,f'{fresh} · age {age if age is not None else "?"} s'),Entry(12,'Panel registration   '+('connected' if registered else 'waiting')),Entry(90,kind='separator')]
    for ident,sec in [(101,5),(102,10),(103,30)]:
        entries.append(Entry(ident,f'{sec}s refresh'+(' · low power' if sec==30 else ''),True,radio=settings['interval']==sec))
    entries += [
        Entry(110,'Threshold alerts '+('on' if settings['alerts'] else 'off'),True),
        Entry(111,'CPU '+str(settings['cpu_high'])+'% · RAM '+str(settings['memory_high'])+'% · '+str(settings['temperature_high'])+'°C'),
        Entry(112,'Export private diagnostic'+(' · saved' if exported else ''),True),
        Entry(113,'Refresh now',True)
    ]
    return entries
