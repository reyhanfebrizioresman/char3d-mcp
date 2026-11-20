"""Offline OpenSeeFace ONNX tensor adapter. Executed by the existing host venv.

No OpenCV, Pillow, torch, camera, tracker or network. RGB is decoded by Blender.
Tensor layout follows OpenSeeFace's BSD-2 licensed model interface:
https://github.com/emilianavt/OpenSeeFace/blob/master/tracker.py
"""
import json
from pathlib import Path
import sys

import numpy as np

INSTALL = ('Face landmark models are missing. Run scripts/install_face_landmarks.sh '
           'after recording approved SHA-256/byte sizes in scripts/toon_assets.tsv. '
           'Expected mnv3_detection_opt.onnx and lm_model0_opt.onnx in '
           'CHAR3D_FACE_MODEL_DIR or output/models/face. No runtime downloads.')


def model_files(directory):
    files = [Path(directory)/name for name in ('mnv3_detection_opt.onnx','lm_model0_opt.onnx')]
    if not all(p.is_file() for p in files):
        raise RuntimeError(INSTALL)
    return files


def resize(rgb, width, height):
    from engine.photo_fit import sample_rgb
    y,x = np.mgrid[0:height,0:width]
    p = np.c_[(x.ravel()+.5)*rgb.shape[1]/width-.5,(y.ravel()+.5)*rgb.shape[0]/height-.5]
    return sample_rgb(rgb,p).reshape(height,width,3)


def tensor(rgb):
    rgb = resize(rgb,224,224)
    return np.ascontiguousarray(((rgb-[.485,.456,.406])/[.229,.224,.225]).transpose(2,0,1)[None],dtype=np.float32)


def detect(rgb, directory, session_factory=None):
    files = model_files(directory)
    if session_factory is None:
        import onnxruntime as ort
        ort.disable_telemetry_events()
        options = ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        session_factory = lambda path:ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
    detector,landmarker = [session_factory(p) for p in files]
    output,pool = detector.run(None,{detector.get_inputs()[0].name:tensor(rgb)})
    if output.shape != (1,2,56,56):
        raise RuntimeError('Unexpected OpenSeeFace detection tensor; expected 1x2x56x56')
    scores = np.where(output[0,0]==pool[0,0],output[0,0],0)
    candidates = np.argwhere(scores>.6)
    boxes = []
    for y,x in sorted(candidates,key=lambda p:-scores[tuple(p)]):
        radius = float(output[0,1,y,x])*112
        box = np.array([x*4-radius,y*4-radius,x*4+radius,y*4+radius])
        if radius<=1 or any(np.linalg.norm(box[:2]-b[:2]) < radius for b in boxes):
            continue
        boxes.append(box)
    if len(boxes)!=1:
        raise ValueError(f'Use a frontal photo containing exactly one clear face; detected {len(boxes)}.')
    h,w = rgb.shape[:2]
    box = boxes[0]*[w/224,h/224,w/224,h/224]
    # OpenSeeFace landmarks use a 10% x / 12.5% y growth around the detector box.
    size = box[2:]-box[:2]
    box[:2] -= size*[.1,.125];box[2:] += size*[.1,.125]
    x0,y0 = np.maximum(0,np.floor(box[:2])).astype(int)
    x1,y1 = np.minimum([w,h],np.ceil(box[2:])).astype(int)
    if x1-x0<32 or y1-y0<32:
        raise ValueError('Face is too small; use a clearer frontal photo')
    values = landmarker.run(None,{landmarker.get_inputs()[0].name:tensor(rgb[y0:y1,x0:x1])})[0][0]
    if values.shape != (198,28,28):
        raise RuntimeError('Unexpected OpenSeeFace landmark tensor; expected 198x28x28')
    heat = values[:66].reshape(66,-1)
    index = heat.argmax(axis=1)
    rows = np.arange(66)
    confidence = heat[rows,index]
    offsets = [values[k:k+66].reshape(66,-1)[rows,index] for k in (66,132)]
    offsets = [np.log(np.clip(o,1e-7,1-1e-7)/(1-np.clip(o,1e-7,1-1e-7)))/16 for o in offsets]
    # Model offset planes are row then column (upstream's x/y are image y/x).
    y = y0+(y1-y0)*(223/224)*(np.floor(index/28)/27+offsets[0])
    x = x0+(x1-x0)*(223/224)*(index%28/27+offsets[1])
    if not np.isfinite([x,y]).all() or np.mean(confidence)<.6:
        raise ValueError('Face landmarks are uncertain; use an unoccluded, well-lit frontal photo')
    points = np.c_[x,y]
    eye1,eye2 = points[36:42].mean(axis=0),points[42:48].mean(axis=0)
    eye_span = max(1,np.linalg.norm(eye2-eye1))
    nose = points[30]
    if abs(nose[0]-(eye1[0]+eye2[0])/2) > eye_span*.3 or abs(eye2[1]-eye1[1])>eye_span*.25:
        raise ValueError('Photo must be frontal, level and unoccluded; turn toward the camera')
    return dict(landmarks=points.tolist(),confidence=confidence.tolist(),box=[x0,y0,x1,y1],
                dimensions=[w,h],depth='2D landmarks; MPFB prior supplies unseen 3D depth')


if __name__=='__main__':
    # NPY and JSON are transient workspace files, removed by the caller.
    try:
        rgb = np.load(sys.argv[1],allow_pickle=False)
        result = detect(rgb,sys.argv[3])
        Path(sys.argv[2]).write_text(json.dumps(result))
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}',file=sys.stderr)
        sys.exit(1)
