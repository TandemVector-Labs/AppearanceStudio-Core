#!/usr/bin/env python3
"""Appearance Studio Monitor: accurate telemetry, functional DBusMenu, bounded reconnect.

Runtime is one user-owned process. Does not modify GNOME themes/extensions,
networking, power settings, application processes, or global sound settings.
"""
from __future__ import annotations
import argparse,json,os,signal,sys,time
from pathlib import Path
import dbus,dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from .system_monitor_model import (DEFAULTS,INTERVALS,Collector,AlertLatch,Entry,validate_settings,
    menu_entries,diagnostic,label,text,NAME,SENSOR,percentage)
from .paths import runtime_state
from .engine import all_themes
BUILD_ID='APPEARANCE-STUDIO-MONITOR-1'
BUS_NAME='org.kde.StatusNotifierItem.AppearanceStudioSystemMonitor';WATCHER='org.kde.StatusNotifierWatcher'
ITEM_PATH='/StatusNotifierItem';MENU_PATH='/Menu'
SNI='org.kde.StatusNotifierItem';MENU='com.canonical.dbusmenu';PROPS='org.freedesktop.DBus.Properties'
class UnknownProperty(dbus.DBusException):_dbus_error_name='org.freedesktop.DBus.Error.UnknownProperty'
class ReadOnly(dbus.DBusException):_dbus_error_name='org.freedesktop.DBus.Error.PropertyReadOnly'

def load_json(path,default):
    try:
        raw=text(path,262144)
        return json.loads(raw) if raw else default
    except (ValueError,RecursionError):return default

def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise RuntimeError('refusing symlink state destination')
    tmp=path.with_name('.'+path.name+'.'+str(os.getpid())+'.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

class Properties:
    @dbus.service.method(PROPS,in_signature='ss',out_signature='v')
    def Get(self,interface,name):
        props=self._props(str(interface))
        if str(name) not in props:raise UnknownProperty(str(name))
        return props[str(name)]
    @dbus.service.method(PROPS,in_signature='s',out_signature='a{sv}')
    def GetAll(self,interface):return self._props(str(interface))
    @dbus.service.method(PROPS,in_signature='ssv',out_signature='')
    def Set(self,interface,name,value):raise ReadOnly(str(name))

class MonitorMenu(Properties,dbus.service.Object):
    def __init__(self,bus,owner):
        super().__init__(bus,MENU_PATH);self.owner=owner;self.revision=0;self.nodes={};self.actions={};self.sensor_ids={};self.net_ids={};self.refresh()
    def _props(self,interface):
        if interface!=MENU:return {}
        return {'Version':dbus.UInt32(3),'TextDirection':'ltr','Status':'normal','IconThemePath':dbus.Array([],signature='s')}
    def refresh(self):
        old=self.nodes;self.nodes={0:{'props':{'children-display':'submenu'},'children':[]}};self.actions={}
        def add(entry,parent=0,action=None):
            props={'label':entry.label,'enabled':dbus.Boolean(entry.enabled),'visible':dbus.Boolean(True),'type':entry.kind}
            if entry.radio is not None:props.update({'toggle-type':'radio','toggle-state':dbus.Int32(1 if entry.radio else 0)})
            self.nodes[entry.id]={'props':props,'children':[]};self.nodes[parent]['children'].append(entry.id)
            if action:self.actions[entry.id]=action
        for entry in menu_entries(self.owner.snapshot,self.owner.settings,self.owner.registered,self.owner.exported):add(entry)
        self.actions.update({101:('interval',5),102:('interval',10),103:('interval',30),110:('alerts',None),112:('export',None),113:('refresh',None)})
        for group,label_text,base,values,selected,ids in [(200,'Temperature source',1000,self.owner.snapshot.get('sensors',[]),self.owner.settings['sensor'],self.sensor_ids),(201,'Network interface',2000,self.owner.snapshot.get('interfaces',[]),self.owner.settings['interface'],self.net_ids)]:
            add(Entry(group,label_text,True));self.nodes[group]['props']['children-display']='submenu'
            kind='sensor' if group==200 else 'interface'
            add(Entry(base,'Automatic',True,radio=selected=='auto'),group,(kind,'auto'))
            for row in values[:128 if group==200 else 64]:
                ident=row['id']
                if ident not in ids:
                    if len(ids)>=(128 if group==200 else 64):continue
                    ids[ident]=base+1+len(ids)
                value=row.get('c');desc=(row['label']+' · '+(str(value)+'°C' if value is not None else 'unavailable')) if group==200 else ident+' · '+row['state']
                add(Entry(ids[ident],desc,True,radio=selected==ident),group,(kind,ident))
        structural=not old or {k:tuple(v['children']) for k,v in old.items()}!={k:tuple(v['children']) for k,v in self.nodes.items()}
        if structural:
            self.revision=(self.revision+1)%4294967295;self.LayoutUpdated(dbus.UInt32(self.revision),dbus.Int32(0))
        else:
            changed=[dbus.Struct((dbus.Int32(k),dbus.Dictionary(v['props'],signature='sv')),signature='ia{sv}') for k,v in self.nodes.items() if v['props']!=old[k]['props']]
            if changed:self.ItemsPropertiesUpdated(dbus.Array(changed,signature='(ia{sv})'),dbus.Array([],signature='(ias)'))
        return structural
    @dbus.service.signal(MENU,signature='ui')
    def LayoutUpdated(self,revision,parent):pass
    @dbus.service.signal(MENU,signature='a(ia{sv})a(ias)')
    def ItemsPropertiesUpdated(self,updated,removed):pass
    @dbus.service.method(MENU,in_signature='iias',out_signature='u(ia{sv}av)')
    def GetLayout(self,parent_id,recursion_depth,property_names):
        parent=int(parent_id)
        if parent not in self.nodes:raise UnknownProperty('menu item')
        names=set(map(str,property_names));depth=int(recursion_depth)
        def node(ident,remaining):
            n=self.nodes[ident];props={k:v for k,v in n['props'].items() if not names or k in names}
            children=[node(c,remaining-1 if remaining>0 else -1) for c in n['children']] if remaining!=0 else []
            return dbus.Struct((dbus.Int32(ident),dbus.Dictionary(props,signature='sv'),dbus.Array(children,signature='v')),signature='ia{sv}av')
        return dbus.UInt32(self.revision),node(parent,depth)
    @dbus.service.method(MENU,in_signature='aias',out_signature='a(ia{sv})')
    def GetGroupProperties(self,ids,property_names):
        names=set(map(str,property_names));out=[]
        for ident in map(int,ids):
            if ident in self.nodes:out.append((dbus.Int32(ident),{k:v for k,v in self.nodes[ident]['props'].items() if not names or k in names}))
        return dbus.Array(out,signature='(ia{sv})')
    @dbus.service.method(MENU,in_signature='is',out_signature='v')
    def GetProperty(self,ident,name):
        try:return self.nodes[int(ident)]['props'][str(name)]
        except KeyError:raise UnknownProperty(str(name))
    @dbus.service.method(MENU,in_signature='isvu',out_signature='')
    def Event(self,ident,event_id,data,timestamp):
        if str(event_id)!='clicked':return
        action=self.actions.get(int(ident))
        if action:self.owner.action(*action)
    @dbus.service.method(MENU,in_signature='a(isvu)',out_signature='ai')
    def EventGroup(self,events):
        unknown=[]
        for event in events:
            if int(event[0]) not in self.nodes:unknown.append(int(event[0]))
            else:self.Event(*event)
        return dbus.Array(unknown,signature='i')
    @dbus.service.method(MENU,in_signature='i',out_signature='b')
    def AboutToShow(self,ident):return dbus.Boolean(self.refresh())
    @dbus.service.method(MENU,in_signature='ai',out_signature='aiai')
    def AboutToShowGroup(self,ids):
        changed=self.refresh();return dbus.Array([int(i) for i in ids if changed and int(i) in self.nodes],signature='i'),dbus.Array([int(i) for i in ids if int(i) not in self.nodes],signature='i')

class WatcherRegistration:
    """One async in-flight call, three attempts per watcher-owner generation."""
    def __init__(self,bus,changed):
        self.bus=bus;self.changed=changed;self.generation=0;self.attempts=0;self.timer=0;self.closed=False
        self.match=bus.add_signal_receiver(self.owner_changed,signal_name='NameOwnerChanged',dbus_interface='org.freedesktop.DBus',bus_name='org.freedesktop.DBus',path='/org/freedesktop/DBus',arg0=WATCHER)
        self.owner_changed(WATCHER,'','initial')
    def owner_changed(self,name,old,new):
        if self.closed:return
        self.generation+=1;self.attempts=0
        if self.timer:GLib.source_remove(self.timer);self.timer=0
        self.changed(False)
        if new:self.attempt()
    def attempt(self):
        self.timer=0
        if self.closed or self.attempts>=3:return GLib.SOURCE_REMOVE
        self.attempts+=1;generation=self.generation
        def ok():
            # An ACK can refer to a stale host object from the old owner.
            # Verify our unique connection's registration after the host's
            # delayed removal window; never report success from ACK alone.
            if not self.closed and generation==self.generation:
                self.timer=GLib.timeout_add_seconds(1,verify)
        def verify():
            self.timer=0
            if self.closed or generation!=self.generation:return GLib.SOURCE_REMOVE
            owner=self.bus.get_unique_name()
            def checked(items):
                if self.closed or generation!=self.generation:return
                if isinstance(items,(list,tuple,dbus.Array)) and any(str(i) in (owner+'@'+ITEM_PATH,owner+ITEM_PATH) for i in items):self.changed(True)
                else:fail(RuntimeError('host did not retain current unique-owner item'))
            self.bus.call_async(WATCHER,'/StatusNotifierWatcher',PROPS,'Get','ss',(WATCHER,'RegisteredStatusNotifierItems'),checked,fail,timeout=2)
            return GLib.SOURCE_REMOVE
        def fail(error):
            if self.closed or generation!=self.generation:return
            self.changed(False)
            if self.attempts<3:self.timer=GLib.timeout_add_seconds(2**(self.attempts-1),self.attempt)
        self.bus.call_async(WATCHER,'/StatusNotifierWatcher',WATCHER,'RegisterStatusNotifierItem','s',(ITEM_PATH,),ok,fail,timeout=2)
        return GLib.SOURCE_REMOVE
    def close(self):
        if self.closed:return
        self.closed=True;self.generation+=1;self.match.remove()
        if self.timer:GLib.source_remove(self.timer);self.timer=0

class Indicator(Properties,dbus.service.Object):
    def __init__(self,bus,state_root):
        super().__init__(bus,ITEM_PATH);self.bus=bus;self.state_root=state_root
        self.settings_path=state_root/'monitor-settings.json';self.state_path=state_root/'system-monitor-indicator.json';self.export_path=state_root/'monitor-diagnostic.json'
        self.settings=DEFAULTS.copy();self.settings_warning='';self.snapshot={};self.registered=False;self.exported=False;self.stopped=False;self.timer=0;self.last_refresh=-1e9;self.last_notification=0
        self.identity={'theme':'unknown','accent':'#8aa5b7','accent2':'#6f8797'}
        self.collector=Collector();self.alerts=AlertLatch();self.menu=None;self.registration=None
        self.load_settings();self.sample();self.menu=MonitorMenu(bus,self);self.registration=WatcherRegistration(bus,self.registration_changed);self.schedule()
    def load_settings(self):
        if not self.settings_path.exists():return
        try:
            raw=text(self.settings_path,4096)
            self.settings=validate_settings(json.loads(raw));self.settings_warning=''
        except (ValueError,TypeError,RecursionError):self.settings_warning='Invalid monitor settings preserved; last valid configuration retained'
    def schedule(self):
        if self.stopped:return
        if self.timer:GLib.source_remove(self.timer)
        self.timer=GLib.timeout_add_seconds(self.settings['interval'],self.tick)
    def tick(self):
        self.timer=0
        if self.stopped:return GLib.SOURCE_REMOVE
        self.load_settings();self.sample();self.schedule();return GLib.SOURCE_REMOVE
    def sample(self):
        try:
            sample=self.collector.collect(self.settings)
            receipt=load_json(runtime_state()/'last-apply.json',{})
            slug=receipt.get('theme') if isinstance(receipt,dict) else ''
            themes=all_themes()
            theme=themes.get(slug)
            if theme is not None:
                self.identity={'theme':slug,'accent':theme.accent.lower(),'accent2':theme.accent2.lower()}
            elif not self.identity.get('theme'):
                self.identity={'theme':'default','accent':'#8aa5b7','accent2':'#6f8797'}
            sample.update(self.identity);sample.update({'updated_at':int(time.time()),'interval':self.settings['interval'],'registered':self.registered,'build_id':BUILD_ID})
            sample['label']=label(sample);self.snapshot=sample
            for alert in self.alerts.evaluate(sample,self.settings,time.monotonic()):self.notify(alert)
        except Exception as exc:
            self.snapshot.update({'stale':True,'source_ok':False,'error_class':type(exc).__name__})
            self.snapshot['label']=label(self.snapshot)
        self.publish()
    def publish(self):
        self.snapshot['registered']=self.registered
        try:atomic_json(self.state_path,self.snapshot)
        except (OSError,RuntimeError):self.settings_warning='Monitor status could not be saved'
        if self.menu:self.menu.refresh()
        self.PropertiesChanged(SNI,dbus.Dictionary({k:v for k,v in self._props(SNI).items() if k in ('Title','XAyatanaLabel','IconAccessibleDesc','ToolTip')},signature='sv'),dbus.Array([],signature='s'))
        self.NewToolTip()
    def registration_changed(self,value):
        self.registered=bool(value)
        if self.menu:self.publish()
    def _props(self,interface):
        if interface!=SNI:return {}
        d=self.snapshot;title='Appearance Studio '+d.get('theme','unknown')+' • CPU '+percentage(d.get('cpu_percent'))+' • RAM '+percentage(d.get('memory_percent'))
        return {'Category':'Hardware','Id':'appearance-studio-system-monitor','Title':title,'Status':'Active','WindowId':dbus.Int32(0),'Menu':dbus.ObjectPath(MENU_PATH),'ItemIsMenu':dbus.Boolean(True),'IconName':'utilities-system-monitor-symbolic','IconThemePath':'','IconPixmap':dbus.Array([],signature='(iiay)'),'OverlayIconName':'','OverlayIconPixmap':dbus.Array([],signature='(iiay)'),'AttentionIconName':'','AttentionIconPixmap':dbus.Array([],signature='(iiay)'),'AttentionMovieName':'','XAyatanaLabel':d.get('label','Appearance Studio monitoring'),'XAyatanaLabelGuide':'88° 100% 100% ↓888.8M ↑888.8M 100%','XAyatanaOrderingIndex':dbus.UInt32(1),'IconAccessibleDesc':title,'AttentionAccessibleDesc':title,'ToolTip':dbus.Struct(('utilities-system-monitor-symbolic',dbus.Array([],signature='(iiay)'),title,'CPU '+d.get('cpu_graph','·')+'\nRAM '+d.get('memory_graph','·')+'\n'+('STALE' if d.get('stale') else 'Sample every '+str(self.settings['interval'])+' seconds')),signature='sa(iiay)ss')}
    @dbus.service.signal(PROPS,signature='sa{sv}as')
    def PropertiesChanged(self,interface,changed,invalidated):pass
    @dbus.service.signal(SNI,signature='')
    def NewToolTip(self):pass
    @dbus.service.signal(SNI,signature='')
    def NewMenu(self):pass
    def action(self,kind,value):
        if self.stopped:return
        try:
            if kind=='export':
                atomic_json(self.export_path,diagnostic(self.snapshot,self.settings));self.exported=True;self.menu.refresh();return
            if kind=='refresh':
                now=time.monotonic()
                if now-self.last_refresh<1:return
                self.last_refresh=now;self.sample();return
            updated=self.settings.copy()
            if kind=='alerts':updated['alerts']=not updated['alerts']
            elif kind in ('interval','sensor','interface'):updated[kind]=value
            else:return
            updated=validate_settings(updated);atomic_json(self.settings_path,updated);self.settings=updated
            if kind in ('interval','alerts'):
                # Configuration changes must not produce a tiny CPU/network
                # sampling interval or an artificial point in the graph.
                self.snapshot['interval']=self.settings['interval'];self.publish()
            else:self.sample()
            self.schedule()
        except (ValueError,OSError,RuntimeError):self.settings_warning='Requested monitor change rejected; previous configuration retained'
    def notify(self,alert):
        # Opt-in, no sound request, five-minute global burst limit, async timeout.
        now=time.monotonic()
        if now-self.last_notification<300:return
        self.last_notification=now
        self.bus.call_async('org.freedesktop.Notifications','/org/freedesktop/Notifications','org.freedesktop.Notifications','Notify','susssasa{sv}i',('Appearance Studio Monitor',dbus.UInt32(0),'utilities-system-monitor-symbolic','Monitor threshold',alert['metric']+': '+str(alert['value']),dbus.Array([],signature='s'),dbus.Dictionary({'suppress-sound':dbus.Boolean(True)},signature='sv'),dbus.Int32(7000)),lambda *_:None,lambda *_:None,timeout=2)
    @dbus.service.method(SNI,in_signature='ii',out_signature='')
    def ContextMenu(self,x,y):self.menu.refresh();self.NewMenu()
    @dbus.service.method(SNI,in_signature='ii',out_signature='')
    def Activate(self,x,y):self.ContextMenu(x,y)
    @dbus.service.method(SNI,in_signature='s',out_signature='')
    def ProvideXdgActivationToken(self,token):return
    @dbus.service.method(SNI,in_signature='ii',out_signature='')
    def SecondaryActivate(self,x,y):self.action('refresh',None)
    @dbus.service.method(SNI,in_signature='u',out_signature='')
    def XAyatanaSecondaryActivate(self,timestamp):self.action('refresh',None)
    @dbus.service.method(SNI,in_signature='is',out_signature='')
    def Scroll(self,delta,orientation):return
    def close(self):
        if self.stopped:return
        self.stopped=True
        if self.timer:GLib.source_remove(self.timer);self.timer=0
        if self.registration:self.registration.close()
        if self.menu:self.menu.remove_from_connection()
        self.remove_from_connection()

def main(argv=None):
    ap=argparse.ArgumentParser(description='Appearance Studio system monitor')
    ap.add_argument('--diagnostic',action='store_true')
    args=ap.parse_args(argv)
    state=runtime_state()
    if args.diagnostic:
        c=Collector();sample=c.collect(DEFAULTS);print(json.dumps(diagnostic(sample,DEFAULTS),indent=2));return
    DBusGMainLoop(set_as_default=True);bus=dbus.SessionBus()
    name=dbus.service.BusName(BUS_NAME,bus=bus,do_not_queue=True)
    item=Indicator(bus,state);loop=GLib.MainLoop()
    def stop(*_):loop.quit();return GLib.SOURCE_REMOVE
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,stop);GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGINT,stop)
    print('APPEARANCE_STUDIO_MONITOR_READY '+BUILD_ID,flush=True)
    try:loop.run()
    finally:item.close()
if __name__=='__main__':main()
