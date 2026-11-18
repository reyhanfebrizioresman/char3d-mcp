"""Pure generator contracts, topology, seeds, budgets and script vocabulary. No bpy."""
from dataclasses import asdict
import json
import math
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine.nature import GENERATORS, tree, grass_field, flowers, lake, river, birds_flock
from engine.nature.presets import PRESETS, ALIASES, COMPOSITIONS, resolve_alias, cost_factor
from engine.nature.core import lod_weight
from engine.script_plan import parse_script


class NatureTests(unittest.TestCase):
    def test_compositions_and_botanical_silhouettes(self):
        self.assertEqual(len({v['landmark'] for v in COMPOSITIONS.values()}),8)
        self.assertGreater(len({v['wide_angle'] for v in COMPOSITIONS.values()}),4)
        pine=tree('pine',height=6,detail=.6).parts[1]
        deep=sum(max(pine.vertices[k][2] for k in f)-min(pine.vertices[k][2] for k in f)>.21 for f in pine.faces)
        self.assertGreater(deep/len(pine.faces),.20,'pine needs volumetric drooping crowns')
        banana=tree('banana',height=4).parts[1]
        self.assertLessEqual(len(banana.faces),200,'banana uses few continuous broad blades')
        self.assertTrue(all(len(f)==4 for f in banana.faces))
        fern=GENERATORS['ferns'](count=2)
        self.assertFalse(fern.parts[0].solid);self.assertFalse(fern.parts[0].occludes)
        log=GENERATORS['fallen_log']().parts[0]
        self.assertTrue(log.solid);self.assertEqual(len(log.seat['centers']),2)
        self.assertEqual(log.seat['kind'],'log')
        ground=GENERATORS['falling_petals'](ground=True).parts[0]
        self.assertFalse(ground.motion)
        self.assertTrue(all(.005<z<.04 for x,y,z in ground.vertices))

    def test_contoured_paddies_and_walkable_river_banks(self):
        a=GENERATORS['rice_paddies'](corridor=3.6)
        dikes=a.metadata['dikes']
        self.assertGreater(max(p[1] for p in dikes[0])-min(p[1] for p in dikes[0]),2)
        self.assertGreater(dikes[-1][0][2]-dikes[0][0][2],2)
        water=next(p for p in a.parts if p.name=='paddy_water')
        self.assertTrue(all(abs(sum(water.vertices[k][0] for k in f)/len(f))>=1.8 for f in water.faces))
        planted=GENERATORS['rice_paddies'](8,(56,42),6.4,2.8,14,corridor=3.6,
                                          exclude=[(4.8,11.6,3.2),(-4.5,8.1,1.7)])
        floor=planted.metadata['dikes'][1][0][2]+.32
        self.assertFalse(any(abs(x-4.8)<1.4 and abs(y-11.6)<1.2 and z>floor
                             for part in planted.parts if part.name.startswith('rice_')
                             for x,y,z in part.vertices),'crops must clear the raised hut floor')
        stream=river(points=[[-4,-10,-.12],[-1,0,-.12],[5,10,-.12]],banks=True)
        self.assertEqual(sum(p.walkable for p in stream.parts),2)
        for p in stream.parts[1:]:
            f=p.faces[0];vs=[p.vertices[i] for i in f]
            area=sum(x[0]*y[1]-y[0]*x[1] for x,y in zip(vs,vs[1:]+vs[:1]))
            self.assertGreater(area,0,'bank top must face up for ground queries')
        with self.assertRaises(ValueError):river(points=[[0,0,0],[1,-1,0]],banks=True)
    def test_all_generators_are_pure_and_have_valid_topology(self):
        state=random.getstate()
        for name,fn in GENERATORS.items():
            with self.subTest(name=name):
                a=fn(seed=19)
                self.assertEqual(asdict(a),asdict(fn(seed=19)))
                json.dumps(asdict(a),allow_nan=False)
                self.assertGreater(sum(len(p.faces) for p in a.parts),0)
                self.assertLess(sum(len(p.vertices) for p in a.parts),1200000)
                for p in a.parts:
                    self.assertEqual(len(p.faces),len(p.indices))
                    self.assertIn(len(p.pivots),(0,len(p.vertices)))
                    for face,index in zip(p.faces,p.indices):
                        self.assertTrue(0 <= index < len(p.materials))
                        self.assertGreaterEqual(len(set(face)),3)
                        self.assertTrue(all(0 <= v < len(p.vertices) for v in face))
        self.assertEqual(state,random.getstate())

    def test_tree_kinds_seasons_and_seed_variation(self):
        kinds=('broadleaf','pine','palm','blossom','maple','banana','bamboo','dead')
        fingerprints=set()
        for kind in kinds:
            a=tree(kind,4,31)
            self.assertTrue(a.parts[0].solid)
            self.assertEqual(a.parts[0].name,'trunk')
            self.assertGreater(max(v[2] for p in a.parts for v in p.vertices),2)
            fingerprints.add(json.dumps(asdict(a)))
        self.assertEqual(len(fingerprints),8)
        self.assertNotEqual(tree(seed=1).parts[0].vertices,tree(seed=2).parts[0].vertices)
        self.assertEqual(len(tree('maple',season='winter').parts),1)
        self.assertEqual(len(tree('dead').parts),1)
        self.assertGreater(len(tree('pine',season='winter').parts),1)
        self.assertEqual(len(tree('blossom',season='winter').parts),1)
        self.assertNotEqual(tree('bamboo',season='wet').parts[-1].materials,
                            tree('bamboo',season='dry').parts[-1].materials)
        self.assertLess(sum(len(p.faces) for p in tree(detail=.25).parts),
                        sum(len(p.faces) for p in tree(detail=1).parts))

    def test_validation_before_geometry(self):
        invalid=[('tree',dict(kind='oak')),('tree',dict(height=float('nan'))),
                 ('tree',dict(season='monsoon')),('tree',dict(detail=0)),
                 ('grass_field',dict(area=[-1,10])),('grass_field',dict(density=-1)),
                 ('flowers',dict(palette=[])),('flowers',dict(palette=[[1,2,3]])),
                 ('rice_paddies',dict(terraces=True)),('rice_paddies',dict(terraces=100)),
                 ('birds_flock',dict(count=10000)),('clouds',dict(style='volume')),
                 ('path',dict(points=[[0,0,0],[0,0,0]])),('path',dict(material='lava')),
                 ('falling_petals',dict(kind='stones'))]
        invalid.extend([('falling_petals',dict(ground=1)),('ferns',dict(count=-1)),
                        ('path',dict(crown=1)),
                        ('fallen_log',dict(radius=0)),('field_hut',dict(height=1)),
                        ('rice_paddies',dict(corridor=100)),('rice_paddies',dict(exclude=[(0,0,-1)])),
                        ('rice_paddies',dict(exclude='hut'))])
        for name,params in invalid:
            with self.subTest(name=name,params=params):
                with self.assertRaises(ValueError): GENERATORS[name](**params)
        for seed in (-1,True,1.2,2147483648):
            with self.assertRaises(ValueError): tree(seed=seed)

    def test_thin_ground_cover_and_water_are_not_colliders(self):
        for a in (grass_field(),flowers(),lake(),river(),birds_flock()):
            for part in a.parts:
                self.assertFalse(part.solid)
                self.assertFalse(part.occludes)
                self.assertFalse(part.walkable)
        self.assertTrue(GENERATORS['hills']().parts[0].walkable)
        self.assertTrue(GENERATORS['bush']().parts[0].solid)

    def test_scatter_exclusion_budget_and_zero(self):
        a=grass_field((2,2),density=10,exclude=[(0,0,10)])
        self.assertFalse(a.parts[0].vertices)
        self.assertFalse(flowers(density=0).parts[0].vertices)
        self.assertFalse(flowers(season='winter').parts[0].vertices)
        self.assertNotEqual(grass_field(season='dry').parts[0].materials,
                            grass_field(season='wet').parts[0].materials)
        self.assertEqual(asdict(tree()),asdict(tree().placed()))
        self.assertEqual(lod_weight((100,100),None),1.)
        self.assertEqual(lod_weight((0,0),[-2,-2,2,2]),1.)
        self.assertAlmostEqual(lod_weight((100,100),[-2,-2,2,2]),.35)
        self.assertGreater(lod_weight((4,0),[-2,-2,2,2]),.35)

    def test_aliases_and_parse_only(self):
        for alias,preset in ALIASES.items():
            plan=parse_script(f'LOKASI: {alias}\nANA: Indah sekali!\nBUDI: Mari bersama.')
            self.assertEqual(plan['environment'],preset)
            self.assertEqual(plan['recommended_look'],'golden_hour')
            self.assertEqual(cost_factor(alias),cost_factor(preset))
        for preset in PRESETS:
            self.assertEqual(resolve_alias(preset.upper().replace('_',' ')),preset)
            self.assertEqual(cost_factor(preset,engine='BLENDER_WORKBENCH'),1)
            self.assertGreaterEqual(cost_factor(preset),1)
            self.assertLess(cost_factor(preset,.2),cost_factor(preset,1))
            self.assertLess(cost_factor(preset,1),cost_factor(preset,2))


if __name__=='__main__':
    result=unittest.main(exit=False)
    if not result.result.wasSuccessful(): raise SystemExit(1)
    print('NATURE UNIT OK: 29 generators, topology, deterministic seeds, budgets, aliases, LOD')
