"""Published closed JSON Schema and bounded, deterministic world preflight.

Only data crosses this boundary. No code, expressions, paths or network are accepted.
The small schema interpreter is shared by Blender and the MCP provider process.
"""
import copy
import inspect
import json
import math
import random
import re
from ..nature import GENERATORS as NATURE
from .heroes import GENERATORS as HEROES

LIMITS={'instances':20000,'placements':256,'triangles':400000,'vertices':1200000,
        'objects':1200,'lights':16,'volumes':2,'animation_keys':200000}
GENERATORS={**NATURE,**HEROES}
LOOKS=['none','golden_hour','sunset','misty_morning','blue_hour','night','overcast_soft','dreamy','epic','studio_film']
PROPS=['chair','desk','table','microphone','laptop','plant','lamp','screen','bookshelf','sofa',
       'whiteboard','bench','stool','cup','phone','book','handheld_microphone']


def num(lo,hi,integer=False):return {'type':'integer' if integer else 'number','minimum':lo,'maximum':hi}
def enum(*values):return {'enum':list(values)}
def arr(item,lo=0,hi=128):return {'type':'array','items':item,'minItems':lo,'maxItems':hi}
def obj(props,required=()):return {'type':'object','properties':props,'required':list(required),'additionalProperties':False}
def vec(lo=-1000,hi=1000,n=3):return arr(num(lo,hi),n,n)
RGB=vec(0,1)
SEED=num(0,2147483647,True)
ID={'type':'string','pattern':r'^[A-Za-z][A-Za-z0-9_-]{0,63}$','maxLength':64}
TRANSFORM=obj({'location':vec(),'rotation_deg':vec(-36000,36000),'scale':vec(.001,100)})
CIRCLES=arr({**arr(num(-1000,1000),3,3),'prefixItems':[num(-1000,1000),num(-1000,1000),num(0,1000)]},0,64)
POINTS=arr(vec(),2,64)
RANGES={
 'tree':{'height':(.3,40),'detail':(.25,1)},'bush':{'height':(.1,5),'detail':(.25,1)},
 'hedge':{'length':(.2,100),'height':(.1,5)},'grass_field':{'height':(.02,2),'density':(0,200)},
 'flowers':{'height':(.05,2),'density':(0,200)},'reeds':{'height':(.1,4),'density':(0,200)},
 'rice_paddies':{'terraces':(1,16),'height':(0,20),'density':(0,40)},
 'hills':{'height':(0,80),'roughness':(0,1)},'mountains_backdrop':{'layers':(1,6),'height':(1,150)},
 'rocks':{'count':(0,300),'height':(.05,15)},'cliff':{'height':(.2,80),'width':(.2,100)},
 'path':{'width':(.1,20)},'river':{'width':(.1,20)},'sea':{'height':(0,.6)},
 'waterfall':{'height':(.2,60),'width':(.1,15)},'clouds':{'cover':(0,1),'height':(5,150)},
 'falling_petals':{'count':(0,500),'height':(.5,30)},'birds_flock':{'count':(0,60)},
 'butterflies':{'count':(0,80),'height':(.1,5)},'fireflies':{'count':(0,500),'height':(.2,10)},
 'fence':{'length':(.5,100),'height':(.2,3)},'lantern':{'height':(.3,5)},
 'wooden_bridge':{'length':(1,30),'width':(.8,8),'height':(0,2)},
 'gazebo':{'width':(1.6,10),'height':(2,8)},'village_house':{'width':(2,15),'depth':(2,15),'height':(2,8)},
 'serpent':{'length':(2,100),'radius':(.1,2),'segments':(24,160),'taper':(.2,.98),'coil':(0,1),'emission':(0,3)},
 'whale_like':{'length':(2,40),'motion':(.2,2.5)},'bird_like':{'wingspan':(1,30)},
 'floating_island':{'radius':(1,18),'depth':(1,30),'orbiting_rocks':(0,12)},'lantern_swarm':{'count':(0,100),'height':(2,40),'size':(.1,2),'rise':(0,2)},
 'hot_air_balloons':{'count':(0,12),'height':(5,80),'size':(.5,6)},
 'crystal_cluster':{'count':(1,40),'height':(.2,12)},'arch_gate':{'width':(2,20),'height':(2,20)},
 'pagoda_like':{'width':(2,15),'height':(3,30),'tiers':(1,5)},'banner_cloth':{'width':(.3,5),'height':(1,12)},
}
ENUMS={('tree','kind'):enum('broadleaf','pine','palm','blossom','maple','banana','bamboo','dead'),
 ('path','material'):enum('gravel','earth','stone','wood'),('clouds','style'):enum('wisps','cumulus'),
 ('falling_petals','kind'):enum('petals','leaves'),('arch_gate','style'):enum('arch','beam')}


def parameter_schema(name,fn):
    props={}
    for key,p in inspect.signature(fn).parameters.items():
        if key=='seed':continue
        default=p.default
        if (name,key) in ENUMS:s=ENUMS[name,key]
        elif key=='season':s=enum('spring','summer','autumn','dry','wet','winter')
        elif key in ('area','shape'):s=vec(.1,400,2)
        elif key=='color':s=copy.deepcopy(RGB)
        elif key=='palette':s=arr(RGB,1,8)
        elif key=='exclude':s=copy.deepcopy(CIRCLES)
        elif key in ('path','points'):s=copy.deepcopy(POINTS)
        elif isinstance(default,bool):s={'type':'boolean'}
        elif key in RANGES.get(name,{}):s=num(*RANGES[name][key],isinstance(default,int))
        else:raise RuntimeError(f'Missing published parameter schema: {name}.{key}')
        props[key]={**s,'default':json.loads(json.dumps(default))}
    return obj(props)

PARAMS={name:parameter_schema(name,fn) for name,fn in GENERATORS.items()}
PARAMS['primitive']=obj({'shape':enum('cube','sphere','cylinder','cone','plane','torus'),
    'size':vec(.01,200),'color':RGB,'walkable':{'type':'boolean'}})
PARAMS['prop']=obj({'kind':enum(*PROPS)},['kind'])
ANIMATION=obj({'kind':enum('orbit','follow_path','bob','sway','rise','drift','spin','flap','swim','flicker'),
    'speed':num(.01,10),'phase':num(-100,100),'seed':SEED,'amplitude':num(0,20),
    'radius':num(.1,100),'path':POINTS,'axis':enum('x','y','z')},['kind'])
MATERIAL=obj({'color':{'anyOf':[RGB,ID]},'roughness':num(0,1),'metallic':num(0,1),
    'emission':num(0,10),'transparency':enum('opaque','glass','mist')})
LOOK=obj({'preset':enum(*LOOKS),'intensity':num(0,1),'haze':num(0,.1),'god_rays':num(0,1),
    'bloom':num(0,1),'dof':enum('auto','off'),'sun':obj({'elevation':num(-90,90),'azimuth':num(-360,360)})},['preset'])
CAMERA=obj({'location':vec(),'target':vec(),'lens':num(12,120),'f_stop':num(1.2,32)},['location','target'])
STAGE=obj({'location':vec(),'area':vec(1,60,2),'standing':arr(vec(),0,4),'seats':arr(ID,0,4),
    'floor':{'type':'boolean'},'surface':enum('wood','stone','grass','sand'),'color':RGB})
COMMON={'id':ID,'transform':TRANSFORM,'instances':arr(TRANSFORM,1,64),
    'scatter':obj({'area':vec(.1,200,2),'count':num(1,128,True),'seed':SEED,
        'min_distance':num(0,30),'avoid':CIRCLES},['area','count']),
    'material':ID,'material_overrides':{'type':'object','maxProperties':32,'propertyNames':ID,'additionalProperties':ID},
    'animation':arr(ANIMATION,0,3)}
SCHEMA={
 '$schema':'https://json-schema.org/draft/2020-12/schema',
 **obj({'version':enum(1),'name':{'type':'string','minLength':1,'maxLength':120},'seed':SEED,
 'duration_s':num(1,180),'elements':arr({'oneOf':[obj({**COMMON,'generator':enum(name),'params':params},
    ['id','generator']) for name,params in PARAMS.items()]},0,128),
 'palette':{'type':'object','maxProperties':32,'propertyNames':ID,'additionalProperties':RGB},
 'materials':{'type':'object','maxProperties':32,'propertyNames':ID,'additionalProperties':MATERIAL},
 'lights':arr(obj({'kind':enum('point','spot','area'),'location':vec(),'target':vec(),
    'color':RGB,'energy':num(0,3000),'size':num(.01,20),'angle':num(5,120)},['kind','location']),0,16),
 'sky':obj({'preset':enum('noon','sunset','overcast','night'),'strength':num(.05,2),'rotate':num(-360,360)}),
 'look':{'anyOf':[enum(*LOOKS),LOOK]},
 'weather':obj({'kind':enum('clear','rain','snow','fog','wind'),'intensity':num(0,1),'seed':SEED,'wind':vec(-100,100)}),
 'camera_hints':obj({'hero':CAMERA,'medium':CAMERA,'close':CAMERA,'establishing_path':arr(vec(),2,16)}),
 'stage':STAGE},['version','elements'])}


# Factor conditional parameter schemas once; avoids the OS argument-size limit
# for Claude Code's structured-output flag and keeps the published contract readable.
ELEMENT_SCHEMA=obj({**COMMON,'generator':enum(*PARAMS),'params':{'type':'object','additionalProperties':True}},['id','generator'])
ELEMENT_SCHEMA['allOf']=[{'if':{'properties':{'generator':enum(name)}},
    'then':{'properties':{'params':params},**({'required':['params']} if params.get('required') else {})}} for name,params in PARAMS.items()]
SCHEMA['properties']['elements']['items']=ELEMENT_SCHEMA


def check(value,schema,path='$'):
    """Strict subset used by SCHEMA. Paths are suitable for inline editor errors."""
    for union in ('oneOf','anyOf'):
        if union in schema:
            successes=0;errors=[]
            for branch in schema[union]:
                try:check(value,branch,path);successes+=1
                except ValueError as exc:errors.append(str(exc))
            if not successes or union=='oneOf' and successes!=1:
                # Element generator selects the useful error, not 37 enum mismatches.
                if isinstance(value,dict) and 'generator' in value:
                    for branch in schema[union]:
                        if value['generator'] in branch.get('properties',{}).get('generator',{}).get('enum',[]):
                            check(value,branch,path)
                raise ValueError(f'{path}: does not match allowed schema ({errors[0]})')
            return
    for branch in schema.get('allOf',[]):
        check(value,branch,path)
    if 'if' in schema:
        try:check(value,schema['if'],path)
        except ValueError:pass
        else:check(value,schema['then'],path)
    kind=schema.get('type') or ('object' if 'properties' in schema else None)
    valid={'object':isinstance(value,dict),'array':isinstance(value,(list,tuple)),
        'number':type(value) is int or type(value) is float and math.isfinite(value),
        'integer':type(value) is int,'string':isinstance(value,str),'boolean':type(value) is bool}
    if kind and not valid[kind]:raise ValueError(f'{path}: expected {kind}')
    if 'enum' in schema and (type(value) is bool or value not in schema['enum']):raise ValueError(f'{path}: expected one of {schema["enum"]}')
    if kind in ('number','integer'):
        if not schema['minimum']<=value<=schema['maximum']:raise ValueError(f'{path}: range {schema["minimum"]}..{schema["maximum"]}')
    if kind=='string':
        if not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',1000):raise ValueError(f'{path}: invalid text length')
        if 'pattern' in schema and not re.fullmatch(schema['pattern'],value):raise ValueError(f'{path}: use letters, digits, underscore or hyphen')
    if kind=='array':
        if not schema['minItems']<=len(value)<=schema['maxItems']:raise ValueError(f'{path}: count {schema["minItems"]}..{schema["maxItems"]}')
        for i,item in enumerate(value):
            check(item,schema['items'],f'{path}[{i}]')
            if i<len(schema.get('prefixItems',[])):check(item,schema['prefixItems'][i],f'{path}[{i}]')
    if kind=='object':
        if len(value)>schema.get('maxProperties',200):raise ValueError(f'{path}: too many keys')
        for key in schema.get('required',[]):
            if key not in value:raise ValueError(f'{path}.{key}: required')
        props=schema.get('properties',{});additional=schema.get('additionalProperties',True)
        for key,item in value.items():
            if key in props:check(item,props[key],f'{path}.{key}')
            elif isinstance(additional,dict):
                check(key,ID,f'{path} key');check(item,additional,f'{path}.{key}')
            elif additional is not True:raise ValueError(f'{path}.{key}: unknown key')


def primitive(shape='cube',size=(1,1,1),color=(.3,.4,.4),walkable=False,seed=0):
    from ..nature.core import Asset,Material,Mesh
    from ..nature.props import _box
    from .heroes import _ellipsoid
    m=Mesh('primitive',materials=[Material('surface',tuple(color))],solid=not walkable,walkable=walkable)
    if shape in ('cube','plane'):_box(m,(0,0,0),(size[0],size[1],.02 if shape=='plane' else size[2]))
    elif shape=='sphere':_ellipsoid(m,(0,0,0),tuple(v/2 for v in size));m.smooth=True
    elif shape in ('cylinder','cone'):m.tube((0,0,-size[2]/2),(0,0,size[2]/2),.5,0 if shape=='cone' else .5,32);m.vertices=[(x*size[0],y*size[1],z) for x,y,z in m.vertices]
    else:
        for i in range(48):
            for j in range(12):
                a=i*math.tau/48;b=j*math.tau/12
                m.vertices.append(((.4+.1*math.cos(b))*math.cos(a)*size[0],(.4+.1*math.cos(b))*math.sin(a)*size[1],.1*math.sin(b)*size[2]))
                k=i*12+j;m.faces.append((k,((i+1)%48)*12+j,((i+1)%48)*12+(j+1)%12,i*12+(j+1)%12));m.indices.append(0)
    return Asset('primitive',[m],{'seed':seed})


def placements(element,seed):
    """Deterministic bounded rejection scatter. Never silently loses requested count."""
    if 'instances' in element and 'scatter' in element:raise ValueError(f'{element["id"]}: instances and scatter are mutually exclusive')
    if 'instances' in element:return element['instances']
    if 'scatter' not in element:return [{}]
    spec=element['scatter'];r=random.Random(spec.get('seed',seed));w,h=spec['area'];out=[]
    avoid=spec.get('avoid',[]);distance=spec.get('min_distance',0)
    for _ in range(spec['count']*200):
        p=[r.uniform(-w/2,w/2),r.uniform(-h/2,h/2),0]
        if any(math.hypot(p[0]-x,p[1]-y)<rad for x,y,rad in avoid):continue
        if any(math.dist(p,q['location'])<distance for q in out):continue
        out.append({'location':p,'rotation_deg':[0,0,r.uniform(-180,180)]})
        if len(out)==spec['count']:return out
    raise ValueError(f'{element["id"]}.scatter: cannot fit count with min_distance/avoid; reduce count or spacing')


def instance_cost(name,p):
    defaults={k:v['default'] for k,v in PARAMS[name].get('properties',{}).items() if 'default' in v}
    p={**defaults,**p}
    if name in ('grass_field','flowers','reeds','rice_paddies'):
        w,h=p['area'];limit={'grass_field':18000,'flowers':3000,'reeds':20000,'rice_paddies':9000}[name]
        return max(1,min(limit,round(w*h*p['density'])))
    if name=='clouds':return max(1,round(p['cover']*5)*27)
    if name=='floating_island':return 110+p['orbiting_rocks']+(24 if p['vines'] else 0)+(8 if p['vegetation'] else 0)+(22 if p['waterfall'] else 0)+(13 if p['waterfall'] and p['mist'] else 0)
    if name in ('rocks','falling_petals','birds_flock','butterflies','fireflies','lantern_swarm','hot_air_balloons','crystal_cluster'):return max(1,p['count'])
    if name=='hedge':return min(160,max(1,math.ceil(p['length']/p['height'])))
    return 1


def validate_recipe(recipe,assets=False):
    """Validate/normalize/preflight without bpy, files, network or global RNG changes.

    Geometry is evaluated once per element, never unbounded per placement. Exact
    triangle/vertex counts (before render modifiers) form conservative hard budgets.
    """
    try:
        if len(json.dumps(recipe,allow_nan=False))>262144:raise ValueError('recipe exceeds 256 KiB')
    except (TypeError,OverflowError):raise ValueError('recipe must contain JSON data only') from None
    check(recipe,SCHEMA)
    r=copy.deepcopy(recipe);r.setdefault('seed',0);r.setdefault('name','Untitled world');r.setdefault('duration_s',4)
    r.setdefault('stage',{});s=r['stage'];s.setdefault('location',[0,0,0]);s.setdefault('area',[7,5]);s.setdefault('floor',True)
    if not s.get('standing'):
        x=min(.85,s['area'][0]*.25);y=min(1,s['area'][1]*.25)
        s['standing']=[[-x,0,0],[x,0,0],[-x,y,0],[x,y,0]]
    costs={key:0 for key in LIMITS};costs['objects']=3+(1 if s['floor'] else 0)+len(r.get('lights',[]))
    costs['objects']+=sum(k in r.get('camera_hints',{}) for k in ('medium','close'))
    costs['lights']=1+len(r.get('lights',[]));costs['animation_keys']=6*len(r.get('camera_hints',{}).get('establishing_path',[]));notes=[];prepared=[];ids=set()
    for i,e in enumerate(r['elements']):
        path=f'$.elements[{i}]'
        if e['id'] in ids:raise ValueError(f'{path}.id: duplicate {e["id"]}')
        ids.add(e['id']);e.setdefault('params',{});e.setdefault('transform',{})
        e['transform']={**{'location':[0,0,0],'rotation_deg':[0,0,0],'scale':[1,1,1]},**e['transform']}
        for label in ('material',):
            if label in e and e[label] not in r.get('materials',{}):raise ValueError(f'{path}.{label}: unknown material')
        for material in e.get('material_overrides',{}).values():
            if material not in r.get('materials',{}):raise ValueError(f'{path}: unknown material {material}')
        if any(circle[2]<0 for circle in e.get('scatter',{}).get('avoid',[])):raise ValueError(f'{path}.scatter.avoid: radius must be nonnegative')
        poses=placements(e,(r['seed']+i*101)%2147483648);n=len(poses);name=e['generator']
        costs['placements']+=n;costs['instances']+=n*instance_cost(name,e['params'])
        for a in e.get('animation',[]):
            if a['kind']=='follow_path' and 'path' not in a:raise ValueError(f'{path}.animation: follow_path requires path')
        costs['objects']+=n*sum(a['kind'] not in ('swim','flap','flicker') for a in e.get('animation',[]))
        costs['animation_keys']+=n*sum(6*(math.ceil(r['duration_s']*24/2)+1) for a in e.get('animation',[])
            if a['kind'] not in ('swim','flap','flicker'))
        _budget(costs)
        if name=='prop':
            unknown=set(e.get('material_overrides',{}))-{'wood','metal','white','floor','leaf','pot','screen','wall','accent','fabric','glow','bulb'}
            if unknown:raise ValueError(f'{path}.material_overrides: unknown prop material {sorted(unknown)}')
            asset=None;costs['objects']+=1+n*40;costs['triangles']+=n*8000;costs['vertices']+=n*16000
            costs['lights']+=n*(e['params']['kind']=='lamp')
        else:
            try:asset=(primitive if name=='primitive' else GENERATORS[name])(**e['params'],seed=(r['seed']+i*101)%2147483648)
            except (TypeError,ValueError) as exc:raise ValueError(f'{path}.params: {exc}') from None
            available_materials={m.name for part in asset.parts for m in part.materials}
            unknown=set(e.get('material_overrides',{}))-available_materials
            if unknown:raise ValueError(f'{path}.material_overrides: unknown source material {sorted(unknown)}')
            costs['objects']+=1+n*(1+len(asset.parts)+len(asset.metadata.get('lights',[]))+sum(p.motion.get('kind') in ('bird','butterfly') for p in asset.parts))
            costs['triangles']+=n*sum(sum(max(1,len(f)-2) for f in part.faces) for part in asset.parts)
            costs['vertices']+=n*sum(len(part.vertices) for part in asset.parts)
            costs['lights']+=n*len(asset.metadata.get('lights',[]))
        _budget(costs);prepared.append((e,asset,poses))
    costs['triangles']+=12 if s['floor'] else 0;costs['vertices']+=8 if s['floor'] else 0
    look=r.get('look','none');preset=look if isinstance(look,str) else look['preset']
    haze=(look.get('haze',None) if isinstance(look,dict) else None)
    costs['volumes']=int((preset!='none' and haze!=0) or r.get('weather',{}).get('kind')=='fog')
    for name,m in r.get('materials',{}).items():
        if isinstance(m.get('color'),str) and m['color'] not in r.get('palette',{}):raise ValueError(f'$.materials.{name}.color: unknown palette color')
    for seat in s.get('seats',[]):
        e=next((e for e in r['elements'] if e['id']==seat),None)
        if e is None or e['generator']!='prop' or e['params']['kind'] not in ('chair','sofa','bench','stool'):raise ValueError(f'$.stage.seats: {seat} must reference a seating prop')
    for p in s['standing']:
        if abs(p[0])>s['area'][0]/2 or abs(p[1])>s['area'][1]/2:raise ValueError('$.stage.standing: position outside stage floor')
    weather=r.get('weather',{})
    kind=weather.get('kind','clear');intensity=weather.get('intensity',.5)
    particle_count=round(350+1850*intensity) if kind=='rain' else round(200+1000*intensity) if kind=='snow' else 0
    costs['instances']+=particle_count+(100 if preset=='dreamy' else 0)
    costs['triangles']+=particle_count*12+(1200 if preset=='dreamy' else 0)
    costs['vertices']+=particle_count*12+(1200 if preset=='dreamy' else 0)
    costs['objects']+=3 if particle_count else 0
    _budget(costs)
    for key,limit in LIMITS.items():
        if costs[key]>.7*limit:notes.append(f'{key}: {costs[key]}/{limit}; near budget, consider fewer details')
    if not s['floor']:notes.append('Stage floor disabled; author must provide walkable geometry beneath characters.')
    notes.append('Stylized geometry; no dynamic cloth/fluid/collision solver. Inspect hero and character cameras.')
    result={'recipe':r,'warnings':notes,'cost':costs,'limits':dict(LIMITS)}
    if assets:result['_assets']=prepared
    return result


def _budget(cost):
    for key,value in cost.items():
        if value>LIMITS[key]:raise ValueError(f'world budget {key}: {value} exceeds {LIMITS[key]}; reduce count/detail/area')


def default_cost(name):
    if name=='prop':return {'triangles':8000,'vertices':16000,'objects':40,'lights':0,'instances':1,'note':'per prop conservative reserve; lamps add one light'}
    asset=(primitive if name=='primitive' else GENERATORS[name])()
    return {'triangles':sum(sum(len(f)-2 for f in p.faces) for p in asset.parts),
        'vertices':sum(len(p.vertices) for p in asset.parts),'objects':1+len(asset.parts)+len(asset.metadata.get('lights',[]))+sum(p.motion.get('kind') in ('bird','butterfly') for p in asset.parts),
        'lights':len(asset.metadata.get('lights',[])),'instances':instance_cost(name,{}),
        'material_slots':sorted({m.name for part in asset.parts for m in part.materials})}


from functools import lru_cache
default_cost=lru_cache(maxsize=64)(default_cost)


def world_schema():
    return {'schema':copy.deepcopy(SCHEMA),'generators':{name:{'params':copy.deepcopy(PARAMS[name]),
        'description':(GENERATORS[name].__doc__ or '').strip() if name in GENERATORS else 'Safe native primitive / procedural furniture',
        'cost':'exact preflight triangles/vertices; internal particles counted; prop <=8000 triangles, 40 objects',
        'category':'hero' if name in HEROES else 'nature' if name in NATURE else name,
        'default_cost':copy.deepcopy(default_cost(name))} for name in PARAMS},
        'limits':dict(LIMITS),'units':'meters, Z up, front -Y; rotation_deg XYZ; scale XYZ',
        'safety':'closed data schema; no code, expressions, paths, downloads or arbitrary Python',
        'motion':'saved deterministic drivers/keys; Blender-specific procedural animation'}
