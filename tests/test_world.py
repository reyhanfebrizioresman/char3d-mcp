"""Pure world contracts and fully mocked online director transports. No Blender/network."""
import copy
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine.world import world_schema,validate_recipe
from engine.world.schema import check,SCHEMA,placements
from engine.world.heroes import GENERATORS
from engine.script_plan import parse_script
from providers.director.world import offline,direct_world,ARCHETYPES,contract
from providers.director import claude,claude_cli

IDEAS=[words[0] for _,words in ARCHETYPES]+['phoenix over crystal arch','pemandangan mimpi bersama sahabat','rice terraces at dawn','snowy pine valley']


class WorldTests(unittest.TestCase):
    def test_volumetric_heroes_and_articulation(self):
        from engine.world.creatures import serpent,whale_like
        from engine.nature.core import dot,sub,norm
        asset=serpent(length=65,radius=1.15,segments=144,seed=17)
        body=asset.parts[0];stride=33
        centers=[tuple(sum(p[k] for p in body.vertices[j:j+32])/32 for k in range(3))
                 for j in range(0,len(body.vertices),stride)]
        # Cross sections remain circular and perpendicular through every bend.
        for j in range(1,144):
            ring=body.vertices[j*stride:j*stride+32];center=centers[j]
            distances=[math.dist(p,center) for p in ring]
            self.assertLess(max(distances)-min(distances),1e-8)
            tangent=norm(sub(centers[j+1],centers[j-1]))
            self.assertLess(max(abs(dot(sub(p,center),tangent)) for p in ring),1e-8)
        self.assertGreater(max(p[1] for p in centers)-min(p[1] for p in centers),10)
        self.assertEqual(len(body.uvs),len(body.vertices))
        self.assertEqual({v[1] for v in body.uvs},{i/32 for i in range(33)})
        self.assertTrue(any(p.motion.get('kind')=='hero_jaw' for p in asset.parts))
        hinges=[p for p in whale_like().parts if p.motion.get('kind')=='hero_hinge']
        self.assertEqual(len(hinges),4)
        self.assertTrue(all('swim_length' in p.motion for p in hinges))

    def test_showcase_layers_portraits_and_budgets(self):
        for idea in ('lantern lake','serpent gateway','whale sunset','floating islands'):
            recipe=offline(idea,17)['recipe'];report=validate_recipe(recipe)
            self.assertLess(report['cost']['triangles'],320000)
            self.assertLessEqual(report['cost']['lights'],5)
            self.assertLessEqual(report['cost']['volumes'],1)
            self.assertIn('f_stop',recipe['camera_hints']['medium'])
            self.assertIn('f_stop',recipe['camera_hints']['close'])
        whale=offline('whale sunset',17)['recipe']
        self.assertFalse(any(e['generator']=='mountains_backdrop' for e in whale['elements']))
        self.assertTrue(any(e['id']=='sun_disk' for e in whale['elements']))
        for generator,params in [('serpent',{'coil':1.1}),('whale_like',{'motion':3}),('floating_island',{'orbiting_rocks':13})]:
            with self.assertRaises(ValueError):
                validate_recipe({'version':1,'elements':[{'id':'hero','generator':generator,'params':params}]})

    def test_cloud_skin_is_closed_and_layers_lift_into_haze(self):
        from collections import Counter
        from engine.nature import clouds
        asset=clouds(cover=.2,seed=4)
        self.assertEqual(len(asset.parts),3)
        for mesh in asset.parts:
            edges=Counter(tuple(sorted((f[i],f[(i+1)%len(f)])))
                          for f in mesh.faces for i in range(len(f)))
            self.assertEqual(set(edges.values()),{2})
            self.assertTrue(mesh.smooth)
        self.assertGreater(sum(asset.parts[-1].materials[0].color),sum(asset.parts[0].materials[0].color))

    def test_catalog_and_all_heroes(self):
        from engine.world.heroes import serpent,whale_like,floating_island
        from engine.nature import clouds
        # New art controls remain keyword-only: old positional seed/color calls
        # must retain their meaning for agents using the pure library API.
        for asset in (serpent(14,.65,80,.85,True,True,True,True,(.1,.3,.2),7),
                      whale_like(12,(.1,.3,.4),7),floating_island(1,1,False,False,7),
                      clouds(.2,35,'wisps',7)):
            self.assertEqual(asset.metadata['seed'],7)
        catalog=world_schema()
        self.assertEqual(len(catalog['generators']),38)
        for name,fn in GENERATORS.items():
            a=fn(seed=7);b=fn(seed=7)
            self.assertEqual(a,b)
            self.assertTrue(a.parts)
            r=validate_recipe({'version':1,'elements':[{'id':'hero','generator':name}]})
            self.assertGreater(r['cost']['triangles'],0)
        check({'version':1,'elements':[]},catalog['schema'])

    def test_published_schema_independent_validator(self):
        from jsonschema import Draft202012Validator
        Draft202012Validator.check_schema(SCHEMA)
        validator=Draft202012Validator(SCHEMA)
        for _,words in ARCHETYPES:validator.validate(offline(words[0],17)['recipe'])
        for recipe in ({'version':1,'elements':[{'id':'a','generator':'prop'}]},
                       {'version':1,'elements':[{'id':'a','generator':'tree','params':{'python':'x'}}]}):
            self.assertTrue(list(validator.iter_errors(recipe)))
            with self.assertRaises(ValueError):validate_recipe(recipe)

    def test_offline_diversity_and_determinism(self):
        state=random.getstate();names=set()
        for i,idea in enumerate(IDEAS):
            a=direct_world(idea,generator='offline',seed=i)
            self.assertEqual(a,direct_world(idea,generator='offline',seed=i))
            check(a['recipe'],SCHEMA);validate_recipe(a['recipe']);names.add(a['recipe']['name'])
        self.assertEqual(len(names),10)
        self.assertEqual(state,random.getstate())
        self.assertNotEqual(offline('lantern',1),offline('lantern',2))
        a=validate_recipe(offline('whale',17)['recipe'])
        self.assertEqual(a,validate_recipe(a['recipe']))

    def test_reject_code_unknown_types_ranges(self):
        base={'version':1,'elements':[{'id':'a','generator':'serpent'}]}
        bad=[{**base,'python':'import os'}, {**base,'seed':True}, {**base,'seed':float('nan')},
             {**base,'elements':[{'id':'a','generator':'eval','params':{}}]},
             {**base,'elements':[{'id':'a','generator':'serpent','params':{'segments':100000}}]},
             {**base,'elements':[{'id':'a','generator':'serpent','params':{'horns':'yes'}}]},
             {**base,'elements':[{'id':'a','generator':'serpent','params':{'radius':-1}}]},
             {**base,'elements':[{'id':'a','generator':'serpent','animation':[{'kind':'bob','expression':'__import__'}]}]},
             {**base,'stage':{'standing':[[50,0,0]]}},
             {**base,'camera_hints':{'hero':{'location':[1,2,3],'target':[0,0,0],'script':'x'}}},
             {**base,'elements':base['elements']*2}]
        for recipe in bad:
            with self.subTest(recipe=recipe),self.assertRaises(ValueError):validate_recipe(recipe)

    def test_hard_budgets(self):
        cases=[{'id':'a','generator':'lantern','scatter':{'area':[30,30],'count':18}},
               {'id':'a','generator':'tree','instances':[{}]*64},
               {'id':'a','generator':'grass_field','params':{'area':[100,100],'density':200},'instances':[{},{}]}]
        for e in cases:
            with self.assertRaisesRegex(ValueError,'budget'):validate_recipe({'version':1,'elements':[e]})
        with self.assertRaisesRegex(ValueError,'placements'):
            validate_recipe({'version':1,'elements':[{'id':f'a{i}','generator':'primitive','instances':[{}]*64} for i in range(5)]})

    def test_scatter_and_materials(self):
        e={'id':'grove','generator':'tree','params':{'height':2,'detail':.25},
           'scatter':{'area':[12,12],'count':8,'min_distance':1,'avoid':[[0,0,3]]}}
        poses=placements(e,17)
        self.assertEqual(poses,placements(e,17))
        self.assertTrue(all(p['location'][0]**2+p['location'][1]**2>=9 for p in poses))
        r={'version':1,'elements':[e],'palette':{'jade':[.1,.3,.2]},'materials':{'moss':{'color':'jade','roughness':.7}}}
        r['elements'][0]['material']='moss';validate_recipe(r)
        r['materials']['moss']['color']='missing'
        with self.assertRaisesRegex(ValueError,'unknown palette'):validate_recipe(r)
        e['scatter']['min_distance']=30
        with self.assertRaisesRegex(ValueError,'cannot fit'):placements(e,17)

    def test_script_world(self):
        for header in ('DUNIA','WORLD'):
            plan=parse_script(f'{header}: lake-demo\nANA: Halo.')
            self.assertEqual(plan['world'],'lake-demo');self.assertEqual(len(plan['characters']),1)
        plan=parse_script({'world':offline('whale')['recipe'],'characters':[{'id':'Ana'}],'beats':[{'say':'Ana','text':'Halo.'}]})
        self.assertEqual(plan['world']['version'],1)
        with self.assertRaises(ValueError):parse_script('DUNIA: ../../outside\nANA: Hi.')


class OnlineWorldTests(unittest.TestCase):
    def test_consent_no_side_effect(self):
        with patch.object(claude.Backend,'generate') as api,patch.object(claude_cli.Backend,'generate') as cli:
            for generator in ('claude','claude_cli'):
                with self.assertRaisesRegex(ValueError,'Persetujuan'):direct_world('whale',generator=generator)
            self.assertEqual(direct_world('whale')['generator'],'offline')
            api.assert_not_called();cli.assert_not_called()

    def test_repair_and_fallback_for_both_registry_backends(self):
        for backend,name in ((claude.Backend,'claude'),(claude_cli.Backend,'claude_cli')):
            with patch.object(backend,'available',return_value=True),patch.object(backend,'generate',side_effect=[{'python':'bad'},offline('whale')]) as generate:
                r=direct_world('whale',generator=name,consent=True)
                self.assertEqual(r['generator'],name);self.assertEqual(generate.call_count,2)
                self.assertTrue(generate.call_args.kwargs['feedback'])
            with patch.object(backend,'available',return_value=True),patch.object(backend,'generate',return_value={'python':'bad'}):
                r=direct_world('whale',generator=name,consent=True)
                self.assertEqual(r['generator'],'offline');self.assertIn('fallback_reason',r)
            with patch.object(backend,'available',return_value=True),patch.object(backend,'generate',side_effect=RuntimeError('RAW SECRET')):
                self.assertNotIn('RAW SECRET',str(direct_world('whale',generator=name,consent=True)))

    def test_wire_recipe_decoding_and_repair(self):
        original=offline('whale')
        wire={**original,'recipe':json.dumps(original['recipe'])}
        with patch.object(claude.Backend,'available',return_value=True),patch.object(claude.Backend,'generate',side_effect=[{**wire,'recipe':'{invalid'},wire]) as generate:
            result=direct_world('whale',generator='claude',consent=True)
            self.assertEqual(result['recipe'],original['recipe'])
            self.assertEqual(generate.call_count,2)
        sent,prompt=contract()
        self.assertEqual(sent['properties']['recipe']['type'],'string')
        self.assertIn('canonical recipe',prompt)
        self.assertLess(len(json.dumps(sent)),4096)

    def test_cli_structured_output_isolation(self):
        payload=offline('whale')
        completed=NS(stdout=json.dumps({'structured_output':payload}),stderr='',returncode=0)
        with patch('providers.director.claude_cli.discover',return_value='/mock/claude'),patch('subprocess.run',return_value=completed) as run:
            r=claude_cli.Backend().generate({'task':'world','idea':'whale','seed':17})
            self.assertEqual(r,payload);args,kwargs=run.call_args
            self.assertIn('recipe',json.loads(args[0][args[0].index('--json-schema')+1])['properties'])
            self.assertIn('--safe-mode',args[0]);self.assertIn('--strict-mcp-config',args[0])
            self.assertEqual(args[0][args[0].index('--tools')+1],'')
            self.assertIn('foreground',contract()[1].lower())
            self.assertEqual(kwargs['timeout'],300)

    def test_api_contract_and_usage(self):
        payload=offline('serpent');response=NS(model='mock-model',stop_reason='end_turn',
            usage=NS(model_dump=lambda:{'input_tokens':100,'output_tokens':50}),
            content=[NS(type='text',text=json.dumps(payload))])
        with patch('anthropic.Anthropic') as client:
            transport=client.return_value.__enter__.return_value
            transport.messages.create.return_value=response
            b=claude.Backend();self.assertEqual(b.generate({'task':'world','idea':'serpent'}),payload)
            kwargs=transport.messages.create.call_args.kwargs
            self.assertIn('recipe',kwargs['output_config']['format']['schema']['properties'])
            self.assertIn('foreground',kwargs['system'][0]['text'].lower())
            self.assertGreater(b.metadata()['cost_usd_estimate'],0)


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():sys.exit(1)
    print('WORLD UNIT OK')
