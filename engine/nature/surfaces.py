"""Smooth analytic surfaces shared by authored generators; no Blender dependency."""
import math
from .core import add, sub, mul, norm, cross, dot


def ellipsoid(mesh, p, radii, rings=12, sides=24, mat=0, phase=0., displacement=0.):
    start=len(mesh.vertices)
    for j in range(rings+1):
        t=.001+(math.pi-.002)*j/rings
        for i in range(sides):
            a=i*math.tau/sides
            # Low frequencies deform the silhouette without noisy vertex normals.
            d=1+displacement*(.55*math.sin(3*a+phase)*math.sin(t)**2+
                .30*math.cos(5*t+phase)+.15*math.sin(5*a-2*t+phase))
            mesh.vertices.append(add(p,(radii[0]*math.sin(t)*math.cos(a)*d,
                radii[1]*math.sin(t)*math.sin(a)*d,radii[2]*math.cos(t)*d)))
    for j in range(rings):
        for i in range(sides):
            k=start+j*sides+i;q=start+j*sides+(i+1)%sides
            mesh.faces.append((k,k+sides,q+sides,q));mesh.indices.append(mat)


def frames(points):
    """Parallel-transport frames prevent a round body shearing on a 3D bend."""
    right=(1,0,0);result=[]
    for i,p in enumerate(points):
        tangent=norm(sub(points[min(i+1,len(points)-1)],points[max(0,i-1)]))
        right=norm(sub(right,mul(tangent,dot(right,tangent))))
        up=norm(cross(right,tangent))
        result.append((right,tangent,up))
    return result


def sweep(mesh,points,radii,sides=12,mat=0,belly=None,uv=False):
    fs=frames(points);start=len(mesh.vertices);stride=sides+1
    for j,(p,r,(right,_,up)) in enumerate(zip(points,radii,fs)):
        for k in range(stride):
            a=k*math.tau/sides
            mesh.vertices.append(add(p,add(mul(right,r*math.cos(a)),mul(up,r*math.sin(a)))))
            if uv:mesh.uvs.append((j/(len(points)-1),k/sides))
        if j:
            for k in range(sides):
                b=start+(j-1)*stride+k
                mesh.faces.append((b,b+stride,b+stride+1,b+1))
                mesh.indices.append(belly if belly is not None and math.sin((k+.5)*math.tau/sides)<-.42 else mat)
    mesh.faces.extend((tuple(start+i for i in reversed(range(sides))),
        tuple(start+(len(points)-1)*stride+i for i in range(sides))))
    mesh.indices.extend((mat,mat))
    return fs


def tendril(mesh,points,radius,mat=0,sides=8):
    sweep(mesh,points,[radius*(1-i/(len(points)-.5)) for i in range(len(points))],sides,mat)


def cloud_union(mesh,lobes,origin,steps=(24,18,18)):
    """Bounded marching tetrahedra of a smooth Gaussian union; shared edge vertices.

    All sampling is deterministic and preflight counts the actual triangles.
    A single continuous skin avoids intersecting sphere seams inside billows.
    """
    lo=[min(p[k]-r[k]*1.25 for p,r in lobes) for k in range(3)]
    hi=[max(p[k]+r[k]*1.25 for p,r in lobes) for k in range(3)]
    nx,ny,nz=steps;sx=nx+1;sy=ny+1
    positions=[];values=[];iso=.62
    for z in range(nz+1):
        for y in range(ny+1):
            for x in range(nx+1):
                p=tuple(lo[k]+(hi[k]-lo[k])*v/n for k,(v,n) in enumerate(zip((x,y,z),steps)))
                positions.append(p)
                values.append(sum(math.exp(-2*sum(((p[k]-c[k])/r[k])**2 for k in range(3))) for c,r in lobes))
    edges={}
    def edge(a,b):
        key=(min(a,b),max(a,b))
        if key not in edges:
            t=(iso-values[a])/(values[b]-values[a]);pa,pb=positions[a],positions[b]
            edges[key]=len(mesh.vertices);mesh.vertices.append(add(origin,tuple(u+(v-u)*t for u,v in zip(pa,pb))))
        return edges[key]
    def face(indices,inside):
        a,b,c=(mesh.vertices[i] for i in indices);center=mul(add(add(a,b),c),1/3)
        if dot(cross(sub(b,a),sub(c,a)),sub(center,add(origin,inside)))<0:indices=tuple(reversed(indices))
        mesh.faces.append(indices);mesh.indices.append(0)
    tets=((0,5,1,6),(0,1,2,6),(0,2,3,6),(0,3,7,6),(0,7,4,6),(0,4,5,6))
    for z in range(nz):
        for y in range(ny):
            for x in range(nx):
                a=z*sx*sy+y*sx+x
                corners=(a,a+1,a+sx+1,a+sx,a+sx*sy,a+sx*sy+1,a+sx*sy+sx+1,a+sx*sy+sx)
                vs=[values[i] for i in corners]
                if min(vs)>iso or max(vs)<iso:continue
                for tet in tets:
                    ids=[corners[k] for k in tet];inner=[i for i in ids if values[i]>iso];outer=[i for i in ids if values[i]<=iso]
                    if not inner or not outer:continue
                    inside=positions[inner[0]]
                    if len(inner)==1:
                        face(tuple(edge(inner[0],b) for b in outer),inside)
                    elif len(inner)==3:
                        face(tuple(edge(outer[0],b) for b in inner),inside)
                    else:
                        a,b=inner;c,d=outer
                        ac,ad,bc,bd=edge(a,c),edge(a,d),edge(b,c),edge(b,d)
                        face((ac,bc,bd),inside);face((ac,bd,ad),inside)
