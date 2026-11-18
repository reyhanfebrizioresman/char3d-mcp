"""World director: ten local archetypes, or the existing consent-gated registry.

No Blender, file reads or network in offline mode. Online results get one repair;
provider failures visibly fall back to local templates, never to another provider.
"""
import json
import random

from engine.world import validate_recipe, world_schema
from engine.world.schema import SCHEMA, check, LOOKS, num, obj, arr
from .common import DirectorError, safe_result

ART_DIRECTION='''Compose an original bespoke world, never reproduce a named film, game, brand or landmark.
Return JSON only: recipe, brief, warnings. No code, expressions, external files, tools or downloads.
Use foreground framing, one readable midground hero, layered background silhouettes.
Leave the stage center clear for human characters. Describe motivated light, scale cues,
a harmonious limited palette matching the chosen cinematic look, negative space and readable motion.
Use meters, Z up, character front -Y. Place scenic heroes behind stage (+Y), camera toward +Y.
A hero camera must show both stage and hero. Keep floor/standing heights consistent.
Prefer 8–18 elements, sparse detail and a single main motion. Schema ranges and budgets are hard limits.
Named material overrides affect all materials of that element; preserve eye/belly detail with material_overrides.
Only supported parameters. No known franchises even if requested: reinterpret broad natural motifs.
'''
OUTPUT_SCHEMA=obj({'recipe':SCHEMA,'brief':{'type':'string','minLength':1,'maxLength':12000},
                   'warnings':arr({'type':'string','maxLength':1000},0,32)},['recipe','brief','warnings'])
# $schema is a dialect declaration, not a provider-specific extension.
OUTPUT_SCHEMA['properties']['recipe']={k:v for k,v in SCHEMA.items() if k!='$schema'}


def contract():
    # The provider grammar cannot express numeric budgets, conditional params or
    # arbitrary named palettes. Keep a small strict envelope and carry the full
    # canonical JSON recipe as data; local validation remains authoritative.
    # https://platform.claude.com/docs/en/build-with-claude/structured-outputs
    wire=obj({'recipe':{'type':'string','description':'JSON-encoded world recipe conforming to the full canonical schema in the system prompt'},
        'brief':{'type':'string'},'warnings':{'type':'array','items':{'type':'string'}}},['recipe','brief','warnings'])
    prompt=ART_DIRECTION+'\nCatalog and canonical recipe contract:\n'+json.dumps(world_schema(),ensure_ascii=False)
    prompt+='\nTRANSPORT: structured output recipe is a JSON STRING containing the complete canonical recipe object. Escape JSON quotes. brief is text and warnings is an array. After decoding, the full closed recipe schema and budgets are enforced locally; one repair is available. Never put Python or expressions in recipe.'
    return wire,prompt


def element(name,generator,location=(0,0,0),params=None,rotation=0,animation=None,scale=1):
    e={'id':name,'generator':generator,'params':params or {},'transform':{
        'location':list(location),'rotation_deg':[0,0,rotation],'scale':[scale]*3}}
    if animation:e['animation']=animation
    return e


ARCHETYPES=[
 ('lake_lanterns',('lantern','lentera','danau','lake','lampion')),
 ('mountain_gateway',('serpent','dragon','naga','temple','gateway','kuil','gerbang')),
 ('sky_whale',('whale','paus','balloon','balon','sky','langit')),
 ('floating_islands',('floating','island','pulau','terapung','waterfall','air terjun')),
 ('blossom_valley',('blossom','bunga','sakura','mekar','valley')),
 ('rice_dawn',('rice','sawah','terrace','padi')),
 ('night_market',('market','pasar','street','jalan')),
 ('beach_fire',('beach','pantai','bonfire','api unggun')),
 ('desert_ruins',('desert','gurun','ruins','reruntuhan','crystal','kristal')),
 ('snow_pines',('snow','salju','pine','pinus','winter')),
]


def offline(idea,seed=0,look=None):
    randomizer=random.Random(seed);text=idea.casefold()
    scores=[sum(word in text for word in words) for _,words in ARCHETYPES]
    chosen=max(range(len(scores)),key=lambda i:scores[i]) if max(scores) else randomizer.randrange(len(scores))
    name=ARCHETYPES[chosen][0];els=[]
    def add(*args,**kwargs):els.append(element(*args,**kwargs))
    recipe={'version':1,'name':name.replace('_',' ').title(),'seed':seed,'duration_s':4,'elements':els,
        'stage':{'location':[0,0,0],'area':[7,6],'surface':'wood','color':[.22,.12,.06],
                 'standing':[[-.85,0,0],[.85,0,0]]},
        'camera_hints':{'hero':{'location':[20,-32,14],'target':[0,10,5],'lens':42}},
        'lights':[{'kind':'area','location':[0,-4,5],'target':[0,0,1],'energy':400,'color':[1,.78,.54],'size':5}],
        'sky':{'preset':'sunset'},'look':{'preset':'golden_hour','haze':.003,'bloom':.25},
        'weather':{'kind':'clear','seed':seed}}
    # Scale cues and a distant landscape connect heroes with the acting platform.
    add('distant_ridges','mountains_backdrop',[0,38,-2],{'area':[140,50],'layers':3,'height':20})
    if name=='lake_lanterns':
        recipe['look']={'preset':'blue_hour','haze':.003,'bloom':.4};recipe['sky']['preset']='night'
        add('water','lake',[0,16,-.22],{'shape':[65,58]})
        add('pier','wooden_bridge',[0,3,-.08],{'length':12,'width':3.6,'height':0})
        add('rising_lanterns','lantern_swarm',[0,15,0],{'count':38,'area':[30,20],'height':15,'size':.65,'reflection':True,'rise':.45})
        add('left_pine','tree',[-12,6,-.25],{'kind':'broadleaf','height':11,'detail':.35})
        add('right_pine','tree',[13,12,-.25],{'kind':'broadleaf','height':13,'detail':.35})
        for i,x in enumerate((-2.2,2.2)):add(f'bank_lamp{i}','lantern',[x,2,0],{'height':1.9})
        add('reeds','reeds',[-9,10,-.25],{'area':[6,3],'density':4,'height':1.5})
        recipe['camera_hints']['hero']={'location':[18,-27,11],'target':[0,11,5],'lens':43}
    elif name=='mountain_gateway':
        recipe['look']={'preset':'misty_morning','haze':.007,'bloom':.2,'sun':{'elevation':12,'azimuth':155}}
        add('ridge_floor','hills',[0,19,-1],{'area':[45,40],'height':2})
        add('gateway','arch_gate',[0,13,1],{'width':6,'height':7,'style':'beam'})
        add('pavilion','pagoda_like',[-10,21,2],{'width':5,'height':10,'tiers':3})
        add('sky_serpent','serpent',[1,15,11],{'length':19,'radius':.7},rotation=-65,
            animation=[{'kind':'orbit','radius':4,'speed':.8,'amplitude':.3}])
        add('left_frame','tree',[-10,1,0],{'kind':'pine','height':12,'detail':.35})
        add('right_frame','tree',[13,18,0],{'kind':'pine','height':10,'detail':.35})
        add('banners','banner_cloth',[5,11,1],{'height':5,'width':1.8})
        add('approach','path',[0,0,0],{'points':[[0,0,0],[0,9,.2],[0,13,1]],'width':3,'material':'stone'})
        recipe['camera_hints']['hero']={'location':[22,-30,15],'target':[0,11,6],'lens':36}
    elif name=='sky_whale':
        recipe['look']={'preset':'sunset','haze':.002,'bloom':.3}
        add('sky_swimmer','whale_like',[0,16,13],{'length':17},rotation=-65,
            animation=[{'kind':'drift','speed':.9,'amplitude':.35}])
        add('balloons','hot_air_balloons',[-4,30,0],{'count':4,'area':[32,18],'height':16,'size':1.6})
        add('cloud_sea','clouds',[0,-5,-2],{'cover':.8,'height':8,'style':'cumulus'})
        add('stage_island','floating_island',[0,0,-.1],{'radius':5,'depth':8,'vegetation':False,'waterfall':False})
        add('crystals','crystal_cluster',[-5,3,0],{'count':6,'height':2})
        recipe['camera_hints']['hero']={'location':[22,-32,16],'target':[0,10,7],'lens':34}
    elif name=='floating_islands':
        add('near_island','floating_island',[-8,13,8],{'radius':5,'depth':8})
        add('far_island','floating_island',[10,27,13],{'radius':6,'depth':10})
        add('tiny_island','floating_island',[-5,36,18],{'radius':2.8,'depth':5})
        add('stage_island','floating_island',[0,0,-.1],{'radius':5,'depth':9,'vegetation':False,'waterfall':False})
        add('cloud_sea','clouds',[0,-5,-5],{'cover':.65,'height':8,'style':'wisps'})
        add('bird','bird_like',[0,16,15],{'wingspan':5,'glowing':False},rotation=-70,
            animation=[{'kind':'drift','amplitude':.3}])
        recipe['camera_hints']['hero']={'location':[24,-34,17],'target':[0,13,6],'lens':34}
    elif name=='blossom_valley':
        recipe['look']={'preset':'dreamy','haze':.004,'bloom':.3}
        for i,(x,y,h) in enumerate([(-8,5,8),(9,9,10),(-11,18,9),(10,25,8)]):
            add(f'blossom{i}','tree',[x,y,0],{'kind':'blossom','height':h,'season':'spring','detail':.35})
        add('meadow','flowers',[0,12,0],{'area':[16,14],'density':1.2,'palette':[[.9,.42,.5],[1,.78,.68]],'exclude':[[0,-5,4]]})
        add('petals','falling_petals',[0,9,0],{'area':[16,12],'height':7,'count':60})
        add('stream','river',[0,0,0],{'points':[[-15,20,0],[0,17,0],[18,24,0]],'width':3})
    elif name=='rice_dawn':
        recipe['look']={'preset':'misty_morning','haze':.004,'sun':{'elevation':8,'azimuth':150}}
        add('terraces','rice_paddies',[0,8,0],{'terraces':7,'area':[42,35],'height':6,'density':1.5})
        add('hut','village_house',[-10,12,1],{'width':4,'depth':3,'height':3})
        add('palm','tree',[10,7,0],{'kind':'palm','height':9})
        add('birds','birds_flock',[0,20,4],{'count':7})
    elif name=='night_market':
        recipe['look']={'preset':'night','haze':.003,'bloom':.35};recipe['sky']['preset']='night'
        for i,(x,y) in enumerate([(-7,7),(7,7),(-8,18),(8,18)]):
            add(f'shop{i}','village_house',[x,y,0],{'width':4,'height':4})
        add('lanterns','lantern_swarm',[0,14,0],{'count':22,'area':[12,25],'height':8,'size':.65})
        add('street','path',[0,0,0],{'points':[[0,-4,0],[0,28,0]],'width':6,'material':'stone'})
        add('seat','prop',[-2,2,0],{'kind':'bench'});recipe['stage']['seats']=['seat']
    elif name=='beach_fire':
        recipe['look']={'preset':'blue_hour','haze':.002,'bloom':.25}
        add('ocean','sea',[0,8,-.12],{'area':[180,150],'height':.12})
        add('sand','primitive',[0,0,-.25],{'shape':'cube','size':[80,22,.3],'color':[.52,.37,.20],'walkable':True})
        for i,x in enumerate((-9,11)):add(f'palm{i}','tree',[x,5,0],{'kind':'palm','height':10})
        add('ember_stones','crystal_cluster',[4,5,0],{'height':.8,'count':10,'color':[1,.22,.035]})
        add('embers','fireflies',[4,5,.3],{'area':[1.4,1.4],'count':30,'height':2})
        recipe['lights'].append({'kind':'point','location':[4,5,1],'color':[1,.26,.05],'energy':350})
    elif name=='desert_ruins':
        recipe['look']={'preset':'epic','haze':.003,'sun':{'elevation':12,'azimuth':140}}
        add('dunes','hills',[0,18,-1],{'area':[80,60],'height':5,'roughness':.25})
        add('arch','arch_gate',[0,17,2],{'width':8,'height':9})
        add('crystals','crystal_cluster',[-8,8,0],{'height':4.5,'count':12})
        add('stones','rocks',[12,21,0],{'count':8,'area':[12,16],'height':3})
        add('banner','banner_cloth',[6,14,1],{'height':6,'color':[.28,.12,.06]})
    else:
        recipe['look']={'preset':'overcast_soft','haze':.004};recipe['sky']['preset']='overcast'
        recipe['weather']={'kind':'snow','intensity':.2,'seed':seed}
        for i,(x,y,h) in enumerate([(-7,6,9),(9,12,12),(-12,18,11),(14,27,14)]):
            add(f'pine{i}','tree',[x,y,0],{'kind':'pine','height':h,'season':'winter','detail':.4})
        add('snow_ground','primitive',[0,15,-.15],{'size':[70,70,.2],'color':[.72,.8,.84],'walkable':True})
        add('cabin','village_house',[0,19,0],{'width':5,'height':4})
        add('lantern','lantern',[-3,3,0],{'height':2})
    if any(word in text for word in ('phoenix','feniks','firebird')):
        add('ember_bird','bird_like',[0,15,12],{'wingspan':9,'glowing':True},rotation=-65)
    if name == 'desert_ruins':
        recipe['palette']={'sand':[.56,.35,.14],'stone':[.42,.27,.16]}
        recipe['materials']={'sand':{'color':'sand','roughness':.95},'stone':{'color':'stone','roughness':.8}}
        recipe['stage'].update(surface='sand',color=[.56,.35,.14])
        for e in els:
            if e['id']=='dunes':e['material']='sand'
            if e['id'] in ('arch','stones'):e['material']='stone'
    if name == 'beach_fire':
        recipe['materials']={'embers':{'color':[1,.24,.025],'emission':4}}
        next(e for e in els if e['id']=='embers')['material']='embers'
    if name in ('sky_whale', 'floating_islands'):
        els[0]['params'].update(height=12,area=[170,60])
        els[0]['transform']['location']=[0,70,-9]
        add('low_cloud_bed','clouds',[0,-60,-18],{'cover':.9,'height':5,'style':'cumulus'})
    if name in ('mountain_gateway', 'sky_whale', 'floating_islands'):
        recipe['lights'].append({'kind':'area','location':[3,4,23],'target':[0,16,10],
            'energy':2200,'color':[1,.78,.54],'size':10})
        recipe['lights'].append({'kind':'area','location':[-12,18,18],'target':[0,16,10],
            'energy':1200,'color':[.48,.72,1],'size':8})
    if look:recipe['look']['preset']=look
    # Seed affects not just generated geometry but a subtle, stable art choice.
    recipe['lights'][0]['color']=[1,.72+randomizer.random()*.12,.50+randomizer.random()*.08]
    validated=validate_recipe(recipe)
    return {'recipe':validated['recipe'],'brief':f'{recipe["name"]}\n\nForeground: open timber acting platform and sparse framing. '
        'Midground: one clear hero silhouette. Background: layered atmospheric ridges. '
        'Warm motivated practicals balance cool distance; human figures supply scale. '
        'Motion is saved and deterministic. Review wide and face coverage before final render.',
        'warnings':['Offline uses ten seeded archetypes; edit the recipe for bespoke art direction.']}


def direct_world(idea,generator='auto',consent=False,seed=0,look=None):
    from . import REGISTRY
    from . import claude,claude_cli
    if not isinstance(idea,str) or not 1<=len(idea.strip())<=8000:raise ValueError('idea: 1..8000 characters')
    check(seed,num(0,2147483647,True),'seed')
    if look is not None and look not in LOOKS:raise ValueError('look must use a cinematic preset')
    if generator!='auto' and generator not in REGISTRY:raise ValueError('generator must be auto/offline/claude/claude_cli')
    if generator=='auto':generator=('claude_cli' if consent is True and claude_cli.Backend.available() else
        'claude' if consent is True and claude.Backend.available() else 'offline')
    factory=REGISTRY[generator]
    if factory.online and consent is not True:raise ValueError('Persetujuan diperlukan: ide dan opsi dikirim ke Anthropic; consent=True atau offline.')
    requested=generator;notes=[];backend=None
    if generator=='offline':payload=offline(idea,seed,look)
    else:
        backend=factory();opts={'task':'world','idea':idea.strip(),'seed':seed,'look':look}
        try:
            if not backend.available():raise DirectorError('Generator belum tersedia; dunia offline digunakan.')
            payload=backend.generate(opts)
            for attempt in range(2):
                try:
                    if isinstance(payload,dict) and isinstance(payload.get('recipe'),str):
                        payload={**payload,'recipe':json.loads(payload['recipe'])}
                    check(payload,OUTPUT_SCHEMA);validated=validate_recipe(payload['recipe'])
                    payload['recipe']=validated['recipe'];break
                except ValueError as exc:
                    if attempt:raise DirectorError('Resep online masih tidak valid setelah satu perbaikan; dunia offline digunakan.') from None
                    notes.append('Resep menjalani satu putaran perbaikan schema.')
                    payload=backend.generate(opts,previous=payload,feedback=[str(exc)])
        except Exception as exc:
            notes.append(str(exc) if isinstance(exc,DirectorError) else 'Generasi online gagal; dunia offline digunakan.')
            generator='offline';payload=offline(idea,seed,look)
    verified=validate_recipe(payload['recipe'])
    result={**payload,'generator':generator,'cost':verified['cost'],'limits':verified['limits'],
        'warnings':list(dict.fromkeys(notes+payload['warnings']+verified['warnings']))}
    if backend:
        result.update(backend.metadata());result['requested_generator']=requested
        if generator!=requested:result['fallback_reason']=notes[-1]
    return safe_result(result)
