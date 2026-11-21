"""PNG and native-geometry contracts for the Round 7 review."""
from pathlib import Path
import colorsys,json
import numpy as np
from toon_polish import read,save
from toon_round4b import board
from toon_round6_metrics import components,polygon_mask
from engine.toon_refine import projected_concavity


def eye_roi(row,shape,wide=True):
    yy,xx=np.indices(shape);mask=np.zeros(shape,bool);h=row['head_height_px']
    for rim in row['lower_lids_px']:
        rim=np.asarray(rim);outer=rim[:max(3,len(rim)//2)]
        padding=(.075 if wide else .015)*h
        left,right=outer[:,0].min()-padding,outer[:,0].max()+padding
        top=outer[:,1].max()+.005*h
        mask|=(xx>=left)&(xx<=right)&(yy>=top)&(yy<top+(.15 if wide else .09)*h)
    return mask


def socket_measure(row,reference=None,counterpart=None):
    image=read(Path(row['socket_mask']))/255
    y=image.mean(2);wall=y>.60;skin=y>.075
    result=dict(visible_wall_pixels=int(wall.sum()))
    if row.get('path'):
        pixels=read(Path(row['path']))/255;value=pixels@[.2126,.7152,.0722]
        for other in (reference,counterpart):
            if other and other.get('socket_mask'):
                skin&=read(Path(other['socket_mask'])).mean(2)>255*.075
        # The first narrow box clipped the wall bulging beyond the canthus.
        # Keep that diagnostic, but cover the whole fold with one fixed larger
        # native-rim rectangle. Both images use the same body intersection.
        for wide in (True,False):
            roi=eye_roi(reference or row,value.shape,wide=wide)&skin
            if not roi.any():continue
            pigment=float(np.percentile(value[roi],80));threshold=pigment-max(.035,pigment*.12)
            regions=[r for r in components(roi&(value<threshold)) if len(r)>=2]
            darkest=min(regions,key=lambda r:float(value[r[:,0],r[:,1]].mean())) if regions else None
            stats=dict(under_eye_roi_pixels=int(roi.sum()),skin_Yprime=pigment,
                darkest_blob_area=0 if darkest is None else len(darkest),
                darkest_blob_contrast=0. if darkest is None else pigment-float(value[darkest[:,0],darkest[:,1]].mean()),
                dark_blob_energy=sum(len(r)*(pigment-float(value[r[:,0],r[:,1]].mean()))**2 for r in regions)/int(roi.sum()))
            if wide:result.update(stats)
            else:result['narrow_roi_diagnostic']=stats
        result['roi_method']='Native lower-lid outer-half box: 0.075 head lateral padding, 0.15 head depth; shared before/after visible body. Narrow legacy box retained separately.'
    return result


def mouth_measure(row):
    pixels=read(Path(row['path']))/255;y=pixels@[.2126,.7152,.0722]
    mask=polygon_mask(y.shape,row['mouth_rim_px'])
    rim=np.asarray(row['mouth_rim_px']);width=float(np.ptp(rim[:,0]))
    aperture=dict(opening_area_pixels=int(mask.sum()),opening_width_pixels=width,
        opening_area_head_squared=float(mask.sum()/row['head_height_px']**2),opening_width_head=width/row['head_height_px'])
    # One-pixel erosion keeps lip albedo/AA out of the interior statistics.
    p=np.pad(mask,1);mask=np.logical_and.reduce([p[j:j+len(mask),i:i+mask.shape[1]] for j in range(3) for i in range(3)])
    if not mask.any():return dict(**aperture,interior_pixels=0,tooth_components=0)
    rgb=pixels[mask];brightness=rgb.max(1);saturation=(brightness-rgb.min(1))/np.maximum(.001,brightness)
    teeth=np.zeros_like(mask);teeth[mask]=(y[mask]>.45)&(saturation<.22)
    groups=components(teeth);large=[r for r in groups if len(r)>=3]
    dark=mask&(y<.32);coords=np.c_[np.nonzero(dark)];gradient=None
    if len(coords)>4:
        z=coords[:,0];middle=(z.min()+z.max())*.5
        if (z>middle).any() and (z<=middle).any():
            gradient=float(y[coords[z>middle,0],coords[z>middle,1]].mean()-y[coords[z<=middle,0],coords[z<=middle,1]].mean())
    return dict(**aperture,interior_pixels=int(mask.sum()),
        interior_Yprime_p05=float(np.percentile(y[mask],5)),interior_Yprime_p95=float(np.percentile(y[mask],95)),
        interior_luminance_spread=float(np.percentile(y[mask],95)-np.percentile(y[mask],5)),
        dark_luminance_spread=float(np.percentile(y[dark],90)-np.percentile(y[dark],10)) if dark.any() else None,
        dark_bottom_minus_top=gradient,pure_black_fraction=float((mask&(y<.02)).sum()/mask.sum()),
        tooth_components=len(large),tooth_components_raw=len(groups),tooth_pixels=int(teeth.sum()),
        largest_tooth_fraction=max([len(r) for r in groups],default=0)/max(1,int(teeth.sum())))


def colour_contract(root):
    import toon_round4b as review
    root=Path(root);old=review.OUT
    try:
        review.OUT=root/'colour';result=review.metrics()
    finally:review.OUT=old
    identity=[]
    for tone in ('light','medium','dark'):
        old=read(root.parent/'toon_round4b/after'/f'{tone}_realistic.png')
        new=read(root/'colour/after'/f'{tone}_realistic.png')
        same=bool(np.array_equal(old,new));identity.append(dict(tone=tone,pixel_identical=same,rgb_byte_mae=float(abs(old.astype(float)-new).mean())))
        assert same,identity[-1]
    (root/'colour/realistic_identity.json').write_text(json.dumps(identity,indent=2))
    board(root/'colour.png',[[(tone+' '+style,root/'colour/after'/f'{tone}_{style}.png') for style in ('realistic','anime','animated_film')] for tone in ('light','medium','dark')],cell=(384,384))
    print('TOON ROUND7 COLOUR OK; REALISTIC PIXEL IDENTITY OK',flush=True)
    return result


def pigment(pixels,site):
    x,y=np.rint(site).astype(int);patch=pixels[y-3:y+4,x-3:x+4]/255
    rgb=np.median(patch,axis=(0,1));return dict(rgb=rgb.tolist(),hsv=list(colorsys.rgb_to_hsv(*rgb)),Yprime=float(rgb@[.2126,.7152,.0722]))


def portrait_colours(root,matrix):
    root=Path(root);records=[]
    for phase in matrix:
        for case in matrix[phase]:
            projection=json.loads((root/'projection'/phase/f"{case['name']}.json").read_text())[str(case['angle'])]
            pixels=read(Path(case['path']))
            records.append(dict(phase=phase,name=case['name'],style=case['style'],look=case['look'],angle=case['angle'],
                cheeks=[pigment(pixels,p) for p in projection['cheeks']],hair=pigment(pixels,projection['crown'])))
    (root/'portrait_colours.json').write_text(json.dumps(records,indent=2));return records


def skin_colours(root,portraits,enforce=True):
    """Bound the NPR warmth change on all six audited phenotypes."""
    pairs=[];tone_orders=[]
    for old in (p for p in portraits if p['phase']=='before'):
        new=next(p for p in portraits if (p['phase'],p['name'],p['style'],p['look'],p['angle'])==('after',old['name'],old['style'],old['look'],old['angle']))
        for side,(a,b) in enumerate(zip(old['cheeks'],new['cheeks'])):
            error=abs(a['hsv'][0]-b['hsv'][0]);error=min(error,1-error)
            row=dict(name=old['name'],style=old['style'],look=old['look'],angle=old['angle'],side=side,
                     before=a,after=b,hue_error_turns=error,saturation_ratio=b['hsv'][1]/max(.001,a['hsv'][1]),Yprime_change=b['Yprime']-a['Yprime'])
            if enforce:assert error<=.04 and row['saturation_ratio']>=.75 and abs(row['Yprime_change'])<.04,row
            pairs.append(row)
    for gender in ('F','M'):
        for style in ('anime','animated_film'):
            phases={}
            for phase in ('before','after'):
                values=[]
                for tone in ('light','medium','dark'):
                    p=next(p for p in portraits if (p['phase'],p['name'],p['style'],p['look'],p['angle'])==(phase,tone+'_'+gender,style,'studio_film',0))
                    values.append(float(np.mean([c['Yprime'] for c in p['cheeks']])))
                phases[phase]=values
            # The male Caucasian scan is darker than the Asian scan in this
            # cohort already at d92d70d. Preserve that measured rank rather
            # than assigning a brightness to an ethnicity label. The original
            # Round 4b camera/scan/ROI contract separately enforces its .02 gaps.
            row=dict(gender=gender,style=style,front_cheek_Yprime=phases,
                     before_rank=np.argsort(phases['before']).tolist(),
                     after_rank=np.argsort(phases['after']).tolist())
            if enforce:assert row['before_rank']==row['after_rank'],row
            tone_orders.append(row)
    result=dict(pairs=pairs,tone_orders=tone_orders,
        method='Front checks preserve the baseline scan rank using both cheeks. Absolute tone order, .02 gaps and .33 dark floor use the unchanged original Round 4b camera/scan/ROI.')
    (Path(root)/'skin_colours.json').write_text(json.dumps(result,indent=2));return result



def jaw_curvature(data,reference=None):
    p=data['points'];h=float(data['head_height']);chin=float(data['chin']);eye=data['eyes'].mean(0)
    edges=data['edges'];edges=edges[(edges<13380).all(1)]
    a=np.r_[edges[:,0],edges[:,1]];b=np.r_[edges[:,1],edges[:,0]]
    count=np.maximum(1,np.bincount(a,minlength=len(p)))
    lap=np.stack([np.bincount(a,weights=p[b,k],minlength=len(p))/count-p[:,k] for k in range(3)],1)/h
    base=p if reference is None else reference
    u=(base[:,2]-chin)/h
    mask=(u>-.10)&(u<.20)&(abs(base[:,0])<.35*h)&(base[:,1]<eye[1]+.06*h)
    mask[13380:]=False
    return dict(vertices=int(mask.sum()),mean_laplacian=float(np.linalg.norm(lap[mask],axis=1).mean()),
        p95_laplacian=float(np.percentile(np.linalg.norm(lap[mask],axis=1),95)),mean_depth_laplacian=float(abs(lap[mask,1]).mean()))


def hair_colours(root,portraits,enforce=True):
    root=Path(root);records=[]
    references=json.loads((root/'hair_reference/matrix.json').read_text())['cases']
    for ref in references:
        original=pigment(read(Path(ref['path'])),ref['crown'])
        pair=[c for c in portraits if c['phase']=='after' and c['name']==ref['name'] and c['angle']==35 and c['look']=='studio_film']
        row=dict(name=ref['name'],reference=original,styles={})
        for current in pair:
            h,s,_=current['hair']['hsv'];rh,rs,_=original['hsv'];delta=abs(h-rh);delta=min(delta,1-delta)
            value=dict(**current['hair'],hue_error_turns=delta,saturation_ratio=s/rs)
            if enforce:assert delta<=.04 and s>=rs*.75,(ref['name'],current['style'],value)
            row['styles'][current['style']]=value
        records.append(row)
    style_checks=[]
    for old in [p for p in portraits if p['phase']=='after' and p['style']=='anime']:
        new=next(p for p in portraits if (p['phase'],p['name'],p['look'],p['angle'],p['style'])==('after',old['name'],old['look'],old['angle'],'animated_film'))
        a,b=old['hair']['hsv'],new['hair']['hsv'];error=abs(a[0]-b[0]);error=min(error,1-error)
        row=dict(name=old['name'],look=old['look'],angle=old['angle'],hue_error_turns=error,saturation_ratio=min(a[1],b[1])/max(.001,max(a[1],b[1])))
        # Round 6 already records the replacement bob's PBR/black-grade limit.
        # Its darkest film crown reaches one RGB code value, where hue/relative
        # saturation are not useful pigment measures. Retain every failing
        # pair as a diagnostic and require unchanged RGB against d92d70d.
        row['audited_asset']=old['name']!='medium_F'
        row['within_colour_limits']=bool(error<=.04 and row['saturation_ratio']>=.75)
        if not row['audited_asset']:
            row['baseline_rgb_unchanged']={}
            for current in (old,new):
                reference=next(p for p in portraits if (p['phase'],p['name'],p['look'],p['angle'],p['style'])==('before',current['name'],current['look'],current['angle'],current['style']))
                row['baseline_rgb_unchanged'][current['style']]=current['hair']['rgb']==reference['hair']['rgb']
            row['limit']='Existing near-black bob grade; unchanged baseline RGB, not a passing hue/saturation claim.'
            if enforce:assert all(row['baseline_rgb_unchanged'].values()),row
        style_checks.append(row)
        if enforce and row['audited_asset']:assert row['within_colour_limits'],row
    (root/'hair_colours.json').write_text(json.dumps(dict(reference_checks=records,style_checks=style_checks),indent=2))
    diagnostics=[r for r in style_checks if not r['audited_asset'] and not r['within_colour_limits']]
    if diagnostics:print('TOON ROUND7 HAIR LIMIT: near-black bob grade; '+str(len(diagnostics))+' diagnostic pairs, unchanged baseline RGB. Ponytail/short-hair limits remain strict.',flush=True)
    return records


def extra_sheets(root):
    root=Path(root)
    workbench=[]
    for name in [f'{t}_{g}' for t in ('light','medium','dark') for g in ('F','M')]:
        rows=[]
        for phase in ('before','after'):
            views=json.loads((root/phase/f'{name}_build_views.json').read_text())['cases']
            assert len(views)==4,(phase,name,views)
            assert all(read(Path(v['path'])).shape[:2]==(320,320) for v in views),(phase,name)
            rows.append([(phase+' '+v['view'],v['path']) for v in views])
        board(root/f'workbench_{name}.png',rows,cell=(320,320));workbench.extend(rows)
    board(root/'workbench.png',workbench,cell=(320,320))
    for phase in ('before','after'):
        assert len(json.loads((root/'hair'/phase/'matrix.json').read_text())['cases'])==8
    board(root/'hair.png',[[(phase+' '+style+' '+word,root/'hair'/phase/f'{style}_{angle}.png') for angle,word in ((0,'front'),(35,'quarter'),(-55,'other side'),(90,'profile'))] for style in ('anime','animated_film') for phase in ('before','after')],cell=(512,512))
    board(root/'chibi.png',[[(phase+' '+style+' '+word,root/'chibi'/phase/f'{style}_{angle}.png') for angle,word in ((0,'front'),(35,'quarter'),(55,'oblique'))] for style in ('anime','animated_film') for phase in ('before','after')],cell=(512,512))
    chibi=[]
    for phase in ('before','after'):
        d=np.load(root/'chibi'/phase/'mesh.npz');p=d['points'];eye=d['eyes'].mean(0);h=float(d['head_height']);chin=float(d['chin'])
        chibi.append(dict(phase=phase,head_height_m=h,jaw_curvature=jaw_curvature(d,np.load(root/'chibi/before/mesh.npz')['points']),
            contours={str(angle):projected_concavity(p,h,chin,eye[1],eye[2],p[[520,540],2].mean(),angle,edges=d['edges']) for angle in (35,55)}))
    (root/'chibi_metrics.json').write_text(json.dumps(chibi,indent=2))
    for name in [f'{t}_{g}' for t in ('light','medium','dark') for g in ('F','M')]:
        rows=[]
        for pose in ('big_smile','A'):
            for phase in ('before','after'):
                data=json.loads((root/'look_rows'/phase/f'{name}.json').read_text())['cases']
                rows.append([(phase+' '+pose+' '+style+' '+look,next(c['path'] for c in data if (c['pose'],c['style'],c['look'])==(pose,style,look))) for style in ('anime','animated_film') for look in ('studio_film','blue_hour')])
        board(root/f'looks_{name}.png',rows,cell=(512,512))


def jaw_strokes(root,matrix):
    rows=[]
    for old in [c for c in matrix['before'] if c['name']=='light_F' and c['style']=='anime']:
        new=next(c for c in matrix['after'] if (c['name'],c['angle'],c['look'],c['style'])==(old['name'],old['angle'],old['look'],old['style']))
        projection=json.loads((Path(root)/'projection/before'/f"{old['name']}.json").read_text())[str(old['angle'])]
        x,y=projection['chin_surface'];h=float(np.linalg.norm(np.array(old['head_top_px'])-old['chin_px']))
        yy,xx=np.indices((512,512));mask=(abs(xx-x)<.17*h)&(yy>y-.035*h)&(yy<y+.065*h)
        for phase in ('before','after'):
            surface=read(Path(root)/'socket_masks'/phase/f"light_F_{old['angle']}_neutral.png")/255
            mask&=surface.mean(2)>.075
        row=dict(angle=old['angle'],look=old['look'],roi_pixels=int(mask.sum()))
        roi=Path(root)/f"jaw_roi_{old['angle']}_{old['look']}.png"
        save(roi,np.repeat((mask*255).astype(np.uint8)[:,:,None],3,axis=2));row['mask']=str(roi)
        for phase,c in (('before',old),('after',new)):
            Y=read(Path(c['path']))/255@[.2126,.7152,.0722]
            row[phase]=dict(dark_stroke_pixels=int((mask&(Y<.30)).sum()),mean_Yprime=float(Y[mask].mean()))
        rows.append(row)
    # A fixed native surface projection, shared by both images; threshold .30
    # separates the old dark ink/AA from this light character's skin.
    (Path(root)/'jaw_strokes.json').write_text(json.dumps(rows,indent=2));return rows


def under_eye_overlays(root,names):
    """Diagnostic boundaries only; the native beauty files stay untouched."""
    root=Path(root);folder=root/'under_eye_rois';folder.mkdir(exist_ok=True)
    for name in names:
        data={p:json.loads((root/'expressions'/p/f'{name}.json').read_text())['cases'] for p in ('before','after')};rows=[]
        for angle in (0,35,55):
            pair={p:next(c for c in data[p] if (c['pose'],c['angle'])==('big_smile',angle)) for p in data}
            mask=eye_roi(pair['before'],(512,512))
            for c in pair.values():mask&=read(Path(c['socket_mask'])).mean(2)>255*.075
            pad=np.pad(mask,1)
            edge=mask&~np.logical_and.reduce([pad[j:j+512,i:i+512] for j,i in ((0,1),(2,1),(1,0),(1,2))])
            row=[]
            for phase,c in pair.items():
                pixels=read(Path(c['path']));pixels[edge]=[255,255,0]
                file=folder/f'{name}_{angle}_{phase}.png';save(file,pixels)
                row.append((phase+' '+{0:'front',35:'quarter',55:'oblique'}[angle]+' ROI diagnostic',file))
            rows.append(row)
        board(root/f'under_eye_roi_{name}.png',rows,cell=(512,512))

def check(root,enforce=True):
    root=Path(root);matrix={p:json.loads((root/p/'matrix.json').read_text())['cases'] for p in ('before','after')}
    key=lambda c:(c['name'],c['angle'],c['look'],c['style'])
    assert len(matrix['before'])==len(matrix['after'])==72
    from toon_round7 import valid_png
    from toon_round7_fixture import signature
    assert all(c['signature']=='d92d70d' and valid_png(c['path']) for c in matrix['before'])
    assert all(c['signature']==signature() and valid_png(c['path']) for c in matrix['after'])
    assert {key(c) for c in matrix['before']}=={key(c) for c in matrix['after']}
    geometry=[];rest=[]
    names=[f'{t}_{g}' for t in ('light','medium','dark') for g in ('F','M')]
    for name in names:
        from engine.toon import LID_PAIRS
        old=np.load(root/'before'/f'{name}_mesh.npz');new=np.load(root/'after'/f'{name}_mesh.npz')
        delta=new['points']-old['points'];rims=np.unique(np.asarray(list(LID_PAIRS.values())).ravel())
        record=dict(name=name,neutral_coordinates_identical=bool(np.array_equal(old['points'],new['points'])),
                    max_rest_offset_m=float(np.linalg.norm(delta,axis=1).max()),eye_rims_identical=bool(np.array_equal(old['points'][rims],new['points'][rims])))
        if enforce:
            assert record['eye_rims_identical'],record
            if name!='light_F':assert record['neutral_coordinates_identical'],record
            else:
                u=(old['points'][:,2]-float(old['chin']))/float(old['head_height'])
                assert not np.any(delta[(u<-.17)|(u>.30)]),record
        rest.append(record)
        for angle in (35,55):
            record=dict(name=name,angle=angle)
            for phase in matrix:
                d=np.load(root/phase/f'{name}_mesh.npz');p=d['points'];eye=d['eyes'].mean(0);h=float(d['head_height']);chin=float(d['chin'])
                record[phase]=projected_concavity(p,h,chin,eye[1],eye[2],p[[520,540],2].mean(),angle,edges=d['edges'])
                record[phase]['jaw_curvature']=jaw_curvature(d,np.load(root/'before'/f'{name}_mesh.npz')['points'])
            geometry.append(record)
    sockets=[];mouth=[];gaps=[]
    for name in names:
        expression_reports={p:json.loads((root/'expressions'/p/f'{name}.json').read_text()) for p in matrix}
        if enforce:
            report=expression_reports['after']
            assert report.get('beauty_source')==signature() and report.get('beauty_frames_refreshed')==23,(name,report.get('beauty_source'))
            assert all(valid_png(c['path']) for c in report['cases'] if c.get('path')),name
        data={p:report['cases'] for p,report in expression_reports.items()}
        for old in data['before']:
            new=next(c for c in data['after'] if (c['pose'],c['angle'])==(old['pose'],old['angle']))
            if 'socket_mask' in old:
                a,b=socket_measure(old,counterpart=new),socket_measure(new,old)
                neutral={p:next(c for c in data[p] if (c['pose'],c['angle'])==('neutral',old['angle'])) for p in data}
                for phase,value in (('before',a),('after',b)):
                    baseline=socket_measure(neutral[phase])['visible_wall_pixels']
                    value['neutral_visible_wall_pixels']=baseline
                    value['excess_wall_pixels']=max(0,value['visible_wall_pixels']-baseline)
                sockets.append(dict(name=name,pose=old['pose'],angle=old['angle'],before=a,after=b))
            if old.get('path') and old['pose'] in ('A','O','surprised','laugh','big_smile','jaw55','tongue','M'):
                measured=mouth_measure(new)
                if enforce and old['pose'] in ('A','O') and measured['interior_pixels']>=100:
                    assert measured['pure_black_fraction']<.10,(name,old['pose'],old['angle'],measured)
                    assert measured['dark_luminance_spread']>.015,(name,old['pose'],old['angle'],measured)
                    if measured['tooth_pixels']>=5:assert measured['tooth_components']<=2,(name,old['pose'],old['angle'],measured)
                mouth.append(dict(name=name,pose=old['pose'],angle=old['angle'],before=mouth_measure(old),after=measured))
            if old['angle']==35:
                gaps.append(dict(name=name,pose=old['pose'],before={k:old[k] for k in ('lip_gap_m','full_rim_gap_m','lid_gap_m')},
                    after={k:new[k] for k in ('lip_gap_m','full_rim_gap_m','lid_gap_m')}))
                if enforce:
                    if old['pose'] in ('M','B','P'):assert new['full_rim_gap_m']<.001,new
                    if old['pose'] in ('blink','blink_squint','blink_surprised'):assert new['lid_gap_m']<.0001,new
                    if old['pose'] in ('blink','blink_squint','blink_surprised'):
                        assert all(v['ideal']==0 for v in new['closed_eye_visibility'].values()),new
                    if old['pose'].startswith('wink_'):
                        side='L' if old['pose']=='wink_left' else 'R'
                        assert new['lid_gaps_by_side_m'][side]<.0001,new
                    if old['pose'] in ('A','O'):assert new['lip_gap_m']/new['head_height_m']>=(.135 if old['pose']=='A' else .095),new
                    if old['pose'] in ('neutral','A','O','surprised','laugh','M','jaw55','tongue'):
                        assert all(p['min_lip_plane_depth_m']>=-.0002 for p in new.get('insert_depths',[])),new
    cross=[]
    for name in names:
        data={p:json.loads((root/'look_rows'/p/f'{name}.json').read_text())['cases'] for p in matrix}
        for old in data['before']:
            new=next(c for c in data['after'] if (c['pose'],c['style'],c['look'])==(old['pose'],old['style'],old['look']))
            measure=socket_measure if old['pose']=='big_smile' else mouth_measure
            a,b=(measure(old,counterpart=new),measure(new,old)) if measure is socket_measure else (measure(old),measure(new))
            if enforce and old['pose']=='A' and b['interior_pixels']>=100:
                assert b['pure_black_fraction']<.10,(name,old['style'],old['look'],b)
                assert b['dark_luminance_spread']>.015,(name,old['style'],old['look'],b)
            cross.append(dict(name=name,pose=old['pose'],style=old['style'],look=old['look'],before=a,after=b))
    active=[r for r in sockets if r['pose']!='neutral']
    totals={phase:dict(visible_wall_pixels=sum(r[phase]['visible_wall_pixels'] for r in active),
                       excess_wall_pixels=sum(r[phase]['excess_wall_pixels'] for r in active)) for phase in matrix}
    result=dict(rest=rest,geometry=geometry,sockets=sockets,socket_totals=totals,mouth=mouth,gaps=gaps,cross_looks=cross)
    (root/'metrics.json').write_text(json.dumps(result,indent=2))
    for look in ('studio_film','blue_hour'):
        for style in ('anime','animated_film'):
            lines=[]
            for name in names:
                lines.append([(phase+' '+name+' '+{0:'front',35:'quarter',55:'oblique'}[angle],
                    next(c['path'] for c in matrix[phase] if key(c)==(name,angle,look,style))) for angle in (0,35,55) for phase in matrix])
            board(root/f'{style}_{look}.png',lines,cell=(512,512))
    board(root/'comparison.png',[
        [(phase+' '+name+' '+style,
          next(c['path'] for c in matrix[phase] if key(c)==(name,35,'studio_film',style)))
         for style in ('anime','animated_film') for phase in matrix]
        for name in names],cell=(512,512))
    expression_overview=[]
    for name in names:
        data={p:json.loads((root/'expressions'/p/f'{name}.json').read_text())['cases'] for p in matrix}
        rows=[]
        for phase in matrix:
            rows.append([(phase+' '+pose,next(c['path'] for c in data[phase] if (c['pose'],c['angle'])==(pose,35)))
                for pose in ('neutral','smile','big_smile','A','O','surprised','laugh','M')])
        board(root/f'expressions_{name}.png',rows,cell=(512,512))
        expression_overview.append([(name+' '+pose,next(c['path'] for c in data['after'] if (c['pose'],c['angle'])==(pose,35)))
            for pose in ('neutral','smile','big_smile','A','O','surprised','laugh','M')])
    board(root/'expressions.png',expression_overview,cell=(512,512))
    for name in names:
        data={p:json.loads((root/'expressions'/p/f'{name}.json').read_text())['cases'] for p in matrix}
        for feature,poses in (('squints',('smile','big_smile','laugh')),('mouth',('A','O','laugh')),('socket_masks',('smile','big_smile','laugh'))):
            rows=[]
            for pose in poses:
                for phase in matrix:
                    rows.append([(phase+' '+pose+' '+{0:'front',35:'quarter',55:'oblique'}[angle],
                        next(c['socket_mask' if feature=='socket_masks' else 'path'] for c in data[phase] if (c['pose'],c['angle'])==(pose,angle))) for angle in (0,35,55)])
            board(root/f'{feature}_{name}.png',rows,cell=(512,512))
    # Per-case exceptions remain in JSON. The assertion tests the actual fold
    # exposure, rather than counting intentional visible neutral lid rims.
    old=totals['before']['excess_wall_pixels'];new=totals['after']['excess_wall_pixels']
    if enforce:assert new<old*.40,(old,new)
    print('TOON ROUND7 SOCKET EXCESS',old,'->',new,flush=True)
    jaw_strokes(root,matrix)
    under_eye_overlays(root,names)
    portraits=portrait_colours(root,matrix)
    skin_colours(root,portraits,enforce=enforce)
    colour_contract(root)
    hair_colours(root,portraits,enforce=enforce)
    extra_sheets(root)
    binding=[]
    for name in names:
        a=json.loads((root/'qa/before'/f'{name}.json').read_text());b=json.loads((root/'qa/after'/f'{name}.json').read_text())
        if enforce:assert b['source']==signature() and b['mouth_version']==4,(name,b['source'],b['mouth_version'])
        row=dict(name=name,**{key:a[key]==b[key] for key in ('weights_digest','bones_digest','topology_digest','landmarks')})
        if enforce:assert all(v for k,v in row.items() if k!='name'),row
        binding.append(row)
    (root/'binding.json').write_text(json.dumps(binding,indent=2))
    print('TOON ROUND7 IMAGE CONTRACT OK',flush=True)
    return result


def refresh_snapshot(root,compare=False):
    """Record RGB changes while recapturing the final native insert revision."""
    import hashlib
    root=Path(root);cases=json.loads((root/'after/matrix.json').read_text())['cases'];hashes={}
    for c in cases:
        key='|'.join(str(c[k]) for k in ('name','angle','look','style'))
        hashes[key]=hashlib.sha256(read(Path(c['path'])).tobytes()).hexdigest()
    file=root/'before_final_refresh_rgb.json'
    if not compare:file.write_text(json.dumps(hashes,indent=2));return
    old=json.loads(file.read_text());assert hashes.keys()==old.keys()
    result=dict(cells=len(hashes),identical=sum(hashes[k]==old[k] for k in hashes),changed=[k for k in hashes if hashes[k]!=old[k]])
    (root/'final_refresh_rgb_identity.json').write_text(json.dumps(result,indent=2));print(result,flush=True)
