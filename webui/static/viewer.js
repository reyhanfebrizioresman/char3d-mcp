import * as THREE from "./vendor/three/three.module.js";
import { GLTFLoader } from "./vendor/three/GLTFLoader.js";
import { OrbitControls } from "./vendor/three/OrbitControls.js";
export async function show(container, url) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  container.prepend(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 1000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xf0f2ff, 0x6b5c45, 3));
  for (const [position, intensity] of [
    [[3, -4, 5], 4],
    [[-3, 2, 3], 2],
  ]) {
    const light = new THREE.DirectionalLight(0xffffff, intensity);
    light.position.set(...position);
    scene.add(light);
  }
  const manager = new THREE.LoadingManager();
  manager.setURLModifier((path) => {
    if (path.startsWith("blob:") || path.startsWith("data:")) return path;
    const parsed = new URL(path, location.href);
    if (
      parsed.origin !== location.origin ||
      !parsed.pathname.startsWith("/api/files/")
    )
      throw new Error("Model merujuk aset di luar workspace");
    return parsed.href;
  });
  let model,
    raf,
    closed = false;
  const resize = () => {
    const w = container.clientWidth,
      h = container.clientHeight;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(container);
  resize();
  const cleanup = () => {
    closed = true;
    cancelAnimationFrame(raf);
    observer.disconnect();
    controls.dispose();
    scene.traverse((obj) => {
      obj.geometry?.dispose();
      const materials = Array.isArray(obj.material)
        ? obj.material
        : [obj.material];
      for (const mat of materials) {
        if (!mat) continue;
        for (const value of Object.values(mat))
          if (value?.isTexture) value.dispose();
        mat.dispose();
      }
    });
    renderer.dispose();
    renderer.domElement.remove();
  };
  // glTF is Y-up. Display it in the studio's Z-up world.
  try {
    const gltf = await new GLTFLoader(manager).loadAsync(url);
    if (!container.isConnected) {
      cleanup();
      return cleanup;
    }
    model = gltf.scene;
    model.rotation.x = Math.PI / 2;
    scene.add(model);
    model.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(model);
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const extent = Math.max(size.x, size.y, size.z, 0.1);
    const radius = bounds.getBoundingSphere(new THREE.Sphere()).radius;
    const halfFov = Math.atan(
      Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) *
        Math.min(1, camera.aspect),
    );
    const distance = (radius / Math.sin(halfFov)) * 1.15;
    camera.position
      .copy(center)
      .add(
        new THREE.Vector3(1.3, -1.8, 0.8).normalize().multiplyScalar(distance),
      );
    controls.target.copy(center);
    camera.far = extent * 100;
    camera.updateProjectionMatrix();
    const grid = new THREE.GridHelper(extent * 4, 20, 0x56634c, 0x30362a);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = bounds.min.z - 0.01;
    scene.add(grid);
    // Imported files can contain unrelated rig/helper clips. Open in the saved
    // pose instead of automatically selecting an arbitrary first animation.
    container.querySelector(".model-message").textContent =
      "3D lokal · seret untuk memutar";
    const tick = () => {
      if (closed) return;
      raf = requestAnimationFrame(tick);
      controls.update();
      renderer.render(scene, camera);
    };
    tick();
    return cleanup;
  } catch (e) {
    cleanup();
    throw e;
  }
}
