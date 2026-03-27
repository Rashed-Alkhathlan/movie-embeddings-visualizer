import { fetchPoster, escHtml } from '../utils.js';

const input = document.getElementById('search-input');
const button = document.getElementById('search-btn');
const acList = document.getElementById('autocomplete-list');
const message = document.getElementById('message');
const space = document.getElementById('space');
const meta = document.getElementById('meta');

let acTimeout;
let engine = null;
let isBusy = false;
let lastPayload = null;

// Uniform visualization scale: preserves geometry and distance ratios.
const WORLD_SCALE = 1200;
const PAD_BASE = 260;
const PAD_STEP = 34;

function normalizeVector(x, y, z) {
    const mag = Math.sqrt(x * x + y * y + z * z);
    if (mag < 1e-12) {
        return { x: 1, y: 0, z: 0 };
    }
    return { x: x / mag, y: y / mag, z: z / mag };
}

function toGraphNodes(payload) {
    const center = {
        id: payload.center.title,
        title: payload.center.title,
        genre: payload.center.genre,
        score: payload.center.score,
        release_date: payload.center.release_date,
        overview: payload.center.overview,
        x: 0,
        y: 0,
        z: 0,
        radius: 7,
        center: true,
        color: 0x38e0b8,
        coord: { x: 0, y: 0, z: 0 },
    };

    const neighbors = payload.neighbors.map((n) => ({
        id: n.title,
        title: n.title,
        genre: n.genre,
        score: n.score,
        release_date: n.release_date,
        overview: n.overview,
        rank: Number(n.rank) || 999,
        primary: Boolean(n.is_primary),
        distance: Number(n.distance),
        radius: n.is_primary ? 4.8 : 3.1,
        center: false,
        color: n.is_primary ? 0x57b3ff : 0x2d466a,
        coord: {
            x: Number(n.rel.x),
            y: Number(n.rel.y),
            z: Number(n.rel.z),
        },
    }));

    // Preserve true direction only and add rank-based padding for readability.
    neighbors.forEach((node, idx) => {
        const unit = normalizeVector(node.coord.x, node.coord.y, node.coord.z);
        const rank = Number.isFinite(node.rank) ? node.rank : idx + 1;
        const paddedRadius = (PAD_BASE + rank * PAD_STEP) * (WORLD_SCALE / 1200);
        node.x = unit.x * paddedRadius;
        node.y = unit.y * paddedRadius;
        node.z = unit.z * paddedRadius;
    });

    return {
        nodes: [center, ...neighbors],
        centerId: center.id,
    };
}

function clearSpaceElement() {
    while (space.firstChild) {
        space.removeChild(space.firstChild);
    }
}

function setMeta(movie, prefix) {
    const score = movie.score === null || movie.score === undefined ? '-' : Number(movie.score).toFixed(1);
    const year = movie.release_date ? String(movie.release_date).trim().split('/').pop() : 'Unknown Year';
    const overview = (movie.overview || '').slice(0, 500);
    const cx = movie.xyz && Number.isFinite(movie.xyz.x) ? movie.xyz.x.toFixed(4) : '0.0000';
    const cy = movie.xyz && Number.isFinite(movie.xyz.y) ? movie.xyz.y.toFixed(4) : '0.0000';
    const cz = movie.xyz && Number.isFinite(movie.xyz.z) ? movie.xyz.z.toFixed(4) : '0.0000';
    const distLine = Number.isFinite(movie.distance) ? ` | d=${movie.distance.toFixed(4)}` : '';
    const rankLine = Number.isFinite(movie.rank) ? ` | rank ${movie.rank}` : '';

    meta.innerHTML = `
        <div class="meta-container">

            <div class="meta-poster">
                <img id="meta-poster-img" src="/static/images/no_poster.png"/>
            </div>

            <div class="meta-info">
                <div class="meta-title">${escHtml(prefix)} ${escHtml(movie.title)}</div>
                <div class="meta-sub"><span class="chip">${escHtml(movie.genre || 'Unknown')}</span>Score ${score} | ${escHtml(year)}${distLine}${rankLine}</div>
                <div class="meta-sub">true rel xyz: (${cx}, ${cy}, ${cz}) | render scale x${WORLD_SCALE}</div>
                <div class="meta-sub">${escHtml(overview || 'No overview available.')}${(movie.overview || '').length > 500 ? '...' : ''}</div>
            </div>
        </div>
    `;

    fetchPoster(movie.title).then((poster) => {
        if (!poster) return;

        const img = document.getElementById("meta-poster-img");
        if (img) {
            img.src = poster;
        }
    });
}

function createFallbackEngine(onNodeClick) {
    clearSpaceElement();

    const canvas = document.createElement('canvas');
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.display = 'block';
    space.appendChild(canvas);

    const ctx = canvas.getContext('2d');
    const state = {
        nodes: [],
        animLines: [], // { aId, bId, progress, direction } direction: 1=extending, -1=retracting
        stars: [],
        incoming: null,
        transition: null,
        hovered: null,
        camera: { yaw: 0.5, pitch: 0.35, zoom: 1500 },
        dragging: false,
        lx: 0,
        ly: 0,
    };

    function resize() {
        const ratio = window.devicePixelRatio || 1;
        const w = Math.max(10, space.clientWidth);
        const h = Math.max(10, space.clientHeight);
        canvas.width = Math.floor(w * ratio);
        canvas.height = Math.floor(h * ratio);
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        state.stars = Array.from({ length: 180 }, () => ({
            x: Math.random() * w,
            y: Math.random() * h,
            s: Math.random() * 1.7 + 0.2,
            a: Math.random() * 0.8 + 0.15,
        }));
    }

    function project(node) {
        const cy = Math.cos(state.camera.yaw);
        const sy = Math.sin(state.camera.yaw);
        const cp = Math.cos(state.camera.pitch);
        const sp = Math.sin(state.camera.pitch);

        const x1 = node.x * cy - node.z * sy;
        const z1 = node.x * sy + node.z * cy;
        const y1 = node.y * cp - z1 * sp;
        const z2 = node.y * sp + z1 * cp;

        const w = canvas.clientWidth;
        const h = canvas.clientHeight;
        // Use fixed focal length and variable camera distance for stronger wheel response.
        const focal = 520;
        const camDist = Math.max(120, state.camera.zoom);
        const scale = focal / (camDist + z2 + focal);
        return {
            sx: w * 0.5 + x1 * scale,
            sy: h * 0.5 + y1 * scale,
            z: z2,
            scale,
        };
    }

    function draw(ms) {
        const t = ms * 0.001;
        const w = canvas.clientWidth;
        const h = canvas.clientHeight;
        ctx.clearRect(0, 0, w, h);

        for (const s of state.stars) {
            ctx.fillStyle = `rgba(200,220,255,${s.a})`;
            ctx.fillRect(s.x, s.y, s.s, s.s);
        }

        if (state.incoming && state.transition) {
            const progress = Math.min(1, (ms - state.transition.start) / state.transition.duration);
            const eased = progress < 0.5
                ? 4 * progress * progress * progress
                : 1 - Math.pow(-2 * progress + 2, 3) / 2;

            state.nodes = state.incoming.nodes.map((targetNode) => {
                const startNode = state.transition.startById.get(targetNode.id) || { ...targetNode, x: 0, y: 0, z: -220 };
                return {
                    ...targetNode,
                    x: startNode.x + (targetNode.x - startNode.x) * eased,
                    y: startNode.y + (targetNode.y - startNode.y) * eased,
                    z: startNode.z + (targetNode.z - startNode.z) * eased,
                };
            });

            if (progress >= 1) {
                state.nodes = state.incoming.nodes;
                // Add new extending lines (old ones are already retracting)
                for (const { aId, bId } of state.incoming.newLineIds) {
                    state.animLines.push({ aId, bId, progress: 0, direction: 1 });
                }
                const done = state.incoming.resolve;
                state.incoming = null;
                state.transition = null;
                if (done) done();
            }
        }

        const projected = state.nodes.map((n) => ({ ...n, ...project(n) })).sort((a, b) => a.z - b.z);
        const byId = new Map(projected.map((p) => [p.id, p]));
        const LINE_SPEED = 0.024; // progress units per frame

        for (const line of state.animLines) {
            const a = byId.get(line.aId);
            const b = byId.get(line.bId);
            if (!a || !b) continue;
            line.progress = Math.max(0, Math.min(1, line.progress + LINE_SPEED * line.direction));
            const tx = a.sx + (b.sx - a.sx) * line.progress;
            const ty = a.sy + (b.sy - a.sy) * line.progress;
            const alpha = 0.72 * (line.direction === 1 ? line.progress : 1 - line.progress);
            ctx.strokeStyle = `rgba(118,190,255,${alpha})`;
            ctx.lineWidth = 1.8;
            ctx.beginPath();
            ctx.moveTo(a.sx, a.sy);
            ctx.lineTo(tx, ty);
            ctx.stroke();
        }
        // Prune fully retracted lines
        state.animLines = state.animLines.filter(l => !(l.direction === -1 && l.progress <= 0));

        for (const p of projected) {
            const radius = (p.center ? 16 : 12) * p.scale;
            p._r = Math.max(3.2, radius);
            const g = ctx.createRadialGradient(p.sx, p.sy, 0, p.sx, p.sy, p._r * 2.6);
            const coreAlpha = p.center ? 0.95 : (p.primary ? 0.92 : 0.22);
            g.addColorStop(0, p.center ? `rgba(56,224,184,${coreAlpha})` : `rgba(87,179,255,${coreAlpha})`);
            g.addColorStop(1, 'rgba(87,179,255,0)');
            ctx.fillStyle = g;
            ctx.beginPath();
            ctx.arc(p.sx, p.sy, p._r * 2.6, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = p.center ? '#38e0b8' : (p.primary ? '#57b3ff' : '#3a5377');
            ctx.beginPath();
            ctx.arc(p.sx, p.sy, p._r, 0, Math.PI * 2);
            ctx.fill();

            if (p.center || p.primary || (state.hovered && state.hovered.id === p.id)) {
                ctx.font = '12px Space Grotesk, sans-serif';
                if (state.hovered && state.hovered.id === p.id) {
                    ctx.fillStyle = '#ffffff';
                } else if (p.center) {
                    ctx.fillStyle = '#dcfff7';
                } else {
                    ctx.fillStyle = '#dce8ff';
                }
                ctx.fillText(p.title, p.sx + p._r + 6, p.sy - 6);
            }
        }

        state._projected = projected;
        requestAnimationFrame(draw);
    }

    canvas.addEventListener('mousedown', (e) => {
        if (state.transition) return;
        state.dragging = true;
        state.lx = e.clientX;
        state.ly = e.clientY;
    });
    window.addEventListener('mouseup', () => { state.dragging = false; });
    window.addEventListener('mousemove', (e) => {
        if (!state.dragging) return;
        const dx = e.clientX - state.lx;
        const dy = e.clientY - state.ly;
        state.lx = e.clientX;
        state.ly = e.clientY;
        state.camera.yaw += dx * 0.006;
        state.camera.pitch = Math.max(-1.2, Math.min(1.2, state.camera.pitch + dy * 0.006));
    });
    canvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        if (state.transition) return;
        state.camera.zoom = Math.max(120, Math.min(4200, state.camera.zoom + e.deltaY * 2.2));
    }, { passive: false });

    canvas.addEventListener('mousemove', (e) => {
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        state.hovered = null;
        if (!state._projected) return;
        for (const p of state._projected) {
            const dx = mx - p.sx;
            const dy = my - p.sy;
            if (Math.sqrt(dx * dx + dy * dy) <= (p._r + 6) && !p.center) {
                state.hovered = p;
                break;
            }
        }
        canvas.style.cursor = state.hovered ? 'pointer' : (state.dragging ? 'grabbing' : 'grab');
    });

    canvas.addEventListener('click', () => {
        if (state.hovered) {
            onNodeClick(state.hovered.title, state.hovered);
        }
    });

    window.addEventListener('resize', resize);
    resize();
    requestAnimationFrame(draw);

    return {
        applyGraph(payload, animated) {
            const data = toGraphNodes(payload);
            if (!animated || !state.nodes.length) {
                state.nodes = data.nodes;
                state.animLines = data.nodes
                    .filter((n) => !n.center && Number(n.rank) <= 5)
                    .map((n) => ({ aId: data.centerId, bId: n.id, progress: 1, direction: 1 }));
                return Promise.resolve();
            }
            return new Promise((resolve) => {
                const startById = new Map(state.nodes.map((n) => [n.id, { x: n.x, y: n.y, z: n.z }]));
                // Retract existing lines
                for (const line of state.animLines) {
                    line.direction = -1;
                }
                // Queue new lines to extend once transition completes
                state.incoming = {
                    nodes: data.nodes,
                    newLineIds: data.nodes
                        .filter((n) => !n.center && Number(n.rank) <= 5)
                        .map((n) => ({ aId: data.centerId, bId: n.id })),
                    resolve,
                };
                state.transition = {
                    start: performance.now(),
                    duration: 2200,
                    startById,
                };
            });
        },
    };
}

async function createThreeEngine(onNodeClick) {
    // throw new Error('CDN blocked'); // Force fallback for testing
    clearSpaceElement();
    const THREE = await import('three');
    const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');
    const { CSS2DRenderer, CSS2DObject } = await import('three/addons/renderers/CSS2DRenderer.js');

    let hoveredMesh = null;
    const state = { objectsById: new Map(), centerId: null, pendingCenterId: null, animLines: [], transition: null };

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 9000);
    camera.position.set(0, 180, 1100);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    space.appendChild(renderer.domElement);

    const labelRenderer = new CSS2DRenderer();
    labelRenderer.domElement.style.position = 'absolute';
    labelRenderer.domElement.style.top = '0';
    labelRenderer.domElement.style.left = '0';
    labelRenderer.domElement.style.pointerEvents = 'none';
    space.appendChild(labelRenderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = false;
    controls.zoomSpeed = 2.2;
    controls.minDistance = 120;
    controls.maxDistance = 6200;
    controls.target.set(0, 0, 0);
    controls.update();

    scene.add(new THREE.AmbientLight(0x8eb8ff, 0.5));
    const keyLight = new THREE.PointLight(0x57b3ff, 1.1, 1800, 2);
    keyLight.position.set(180, 220, 240);
    scene.add(keyLight);
    const fillLight = new THREE.PointLight(0x38e0b8, 0.55, 1600, 2);
    fillLight.position.set(-220, -120, 120);
    scene.add(fillLight);

    const graphGroup = new THREE.Group();
    scene.add(graphGroup);

    const starGeo = new THREE.BufferGeometry();
    const starPos = new Float32Array(4500);
    for (let i = 0; i < 1500; i += 1) {
        starPos[i * 3 + 0] = (Math.random() - 0.5) * 10000;
        starPos[i * 3 + 1] = (Math.random() - 0.5) * 10000;
        starPos[i * 3 + 2] = (Math.random() - 0.5) * 10000;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0xd7e8ff, size: 1.25, transparent: true, opacity: 0.8 }));
    scene.add(stars);

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    function isCloseNode(node) {
        return Number(node.rank) <= 5;
    }

    function labelVisibleByDefault(node) {
        return node.center || isCloseNode(node);
    }

    function makeLabel(text, isCenter) {
        const el = document.createElement('div');
        el.className = isCenter ? 'label center' : 'label';
        el.textContent = text;
        return new CSS2DObject(el);
    }

    function buildNodeObject(node) {
        const group = new THREE.Group();
        group.position.set(node.x, node.y, node.z);

        const close = isCloseNode(node);

        const mat = new THREE.MeshStandardMaterial({
            color: node.color,
            emissive: node.center ? 0x1acfa4 : (close ? 0x295ea7 : 0x1a3a5c),
            emissiveIntensity: node.center ? 0.80 : (close ? 0.75 : 0.65),
            metalness: 0.12,
            roughness: 0.38,
            transparent: true,
            opacity: node.center ? 1 : (close ? 1 : 0.90),
        });

        const mesh = new THREE.Mesh(new THREE.SphereGeometry(node.radius * 2, 28, 28), mat);
        mesh.userData.movie = node;
        group.add(mesh);

        const halo = new THREE.Mesh(
            new THREE.SphereGeometry(node.radius * (node.center ? 3.65 : 3.45), 24, 24),
            new THREE.MeshBasicMaterial({
                color: node.center ? 0x67f5d6 : (close ? 0x7cc0ff : 0x355276),
                transparent: true,
                opacity: node.center ? 0.23 : (close ? 0.15 : 0.07),
                depthWrite: false,
            }),
        );
        group.add(halo);

        const hitRadius = node.center ? node.radius * 1.5 : Math.max(node.radius * 3.5, 18);
        const hitMesh = new THREE.Mesh(
            new THREE.SphereGeometry(hitRadius, 8, 8),
            new THREE.MeshBasicMaterial({ visible: false, depthWrite: false }),
        );
        hitMesh.userData.movie = node;
        hitMesh.userData.isHitProxy = true;
        hitMesh.userData.visualMesh = mesh;
        group.add(hitMesh);

        const label = makeLabel(node.title, node.center);
        label.position.set(0, node.radius + 6.2, 0);

        // KEY FIX: only add label to scene graph if it should always be visible.
        // Far node labels are kept detached and only added/removed on hover.
        if (labelVisibleByDefault(node)) {
            group.add(label);
        }

        group.userData = { mesh, hitMesh, label, target: new THREE.Vector3(node.x, node.y, node.z), movie: node };
        return group;
    }

    function removeNodeObject(obj) {
        // Remove label element from DOM if it was attached
        const label = obj.userData.label;
        if (label && label.element.parentNode) {
            label.element.parentNode.removeChild(label.element);
        }
        obj.traverse((child) => {
            if (child.isMesh) {
                child.geometry.dispose();
                child.material.dispose();
            }
        });
        graphGroup.remove(obj);
    }

    function getVisualMesh(hitOrVisual) {
        return hitOrVisual.userData.isHitProxy
            ? hitOrVisual.userData.visualMesh
            : hitOrVisual;
    }

    function setHoverOn(obj, hitMesh) {
        const visual = getVisualMesh(hitMesh);
        visual.material.emissiveIntensity = 0.95;
        visual.material.emissive.set(0x6ad4ff);
        visual.scale.setScalar(1.18);
        if (!labelVisibleByDefault(hitMesh.userData.movie)) {
            // Attach label to scene graph so renderer picks it up
            obj.add(obj.userData.label);
        }
    }

    function setHoverOff(obj, hitMesh) {
        const visual = getVisualMesh(hitMesh);
        const node = hitMesh.userData.movie;
        const close = isCloseNode(node);
        visual.material.emissiveIntensity = node.center ? 0.62 : (close ? 0.45 : 0.28);
        visual.material.emissive.set(node.center ? 0x1acfa4 : (close ? 0x295ea7 : 0x1a3a5c));
        visual.scale.setScalar(1);
        if (!labelVisibleByDefault(node)) {
            // Detach label from scene graph AND remove its DOM element
            obj.remove(obj.userData.label);
            if (obj.userData.label.element.parentNode) {
                obj.userData.label.element.parentNode.removeChild(obj.userData.label.element);
            }
        }
    }

    const LINE_SPEED = 0.018;

    function tickAnimLines() {
        for (const al of state.animLines) {
            al.progress = Math.max(0, Math.min(1, al.progress + LINE_SPEED * al.direction));
            const aObj = state.objectsById.get(al.aId);
            const bObj = state.objectsById.get(al.bId);
            if (!aObj || !bObj) { al.progress = 0; continue; }
            const aPos = aObj.position;
            const bPos = bObj.position;
            const tipX = aPos.x + (bPos.x - aPos.x) * al.progress;
            const tipY = aPos.y + (bPos.y - aPos.y) * al.progress;
            const tipZ = aPos.z + (bPos.z - aPos.z) * al.progress;
            al.line.material.opacity = 0.72 * (al.direction === 1 ? al.progress : (1 - al.progress));
            const arr = al.line.geometry.attributes.position.array;
            arr[0] = aPos.x; arr[1] = aPos.y; arr[2] = aPos.z;
            arr[3] = tipX;   arr[4] = tipY;   arr[5] = tipZ;
            al.line.geometry.attributes.position.needsUpdate = true;
        }
        state.animLines = state.animLines.filter((al) => {
            if (al.direction === -1 && al.progress <= 0) {
                graphGroup.remove(al.line);
                al.line.geometry.dispose();
                al.line.material.dispose();
                return false;
            }
            return true;
        });
    }

    function spawnLines(centerId, nodeIds) {
        const centerObj = state.objectsById.get(centerId);
        if (!centerObj) return;
        for (const id of nodeIds) {
            const obj = state.objectsById.get(id);
            if (!obj) continue;
            const geo = new THREE.BufferGeometry();
            const positions = new Float32Array(6);
            positions[0] = centerObj.position.x; positions[1] = centerObj.position.y; positions[2] = centerObj.position.z;
            positions[3] = centerObj.position.x; positions[4] = centerObj.position.y; positions[5] = centerObj.position.z;
            geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
            const mat = new THREE.LineBasicMaterial({ color: 0x79beff, transparent: true, opacity: 0 });
            const line = new THREE.Line(geo, mat);
            graphGroup.add(line);
            state.animLines.push({ aId: centerId, bId: id, progress: 0, direction: 1, line });
        }
    }

    function retractAllLines() {
        for (const al of state.animLines) al.direction = -1;
    }

    function onResize() {
        const w = space.clientWidth;
        const h = space.clientHeight;
        renderer.setSize(w, h);
        labelRenderer.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
    }
    window.addEventListener('resize', onResize);
    onResize();

    renderer.domElement.addEventListener('mousemove', (event) => {
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    });

    renderer.domElement.addEventListener('click', () => {
        if (!hoveredMesh || isBusy) return;
        const movie = hoveredMesh.userData.movie;
        const visual = getVisualMesh(hoveredMesh);
        visual.material.emissiveIntensity = 2.0;
        visual.material.emissive.set(0xffffff);
        visual.material.color.set(0xffffff);
        onNodeClick(movie.title, movie);
    });

    function tick(now) {
        if (state.transition) {
            const elapsed = now - state.transition.start;
            const p = Math.min(1, elapsed / state.transition.duration);
            const eased = p < 0.5
                ? 4 * p * p * p
                : 1 - Math.pow(-2 * p + 2, 3) / 2;

            state.objectsById.forEach((obj) => {
                const id = obj.userData.movie.id;
                const start = state.transition.startById.get(id) || { x: 0, y: 0, z: 0 };
                const target = obj.userData.target;
                obj.position.set(
                    start.x + (target.x - start.x) * eased,
                    start.y + (target.y - start.y) * eased,
                    start.z + (target.z - start.z) * eased,
                );
            });

            controls.enabled = false;
            if (p >= 1) {
                state.objectsById.forEach((obj) => obj.position.copy(obj.userData.target));
                if (state.pendingCenterId !== null) {
                    state.centerId = state.pendingCenterId;
                    state.pendingCenterId = null;
                }
                spawnLines(state.centerId, [...state.objectsById.keys()].filter((id) => {
                    const obj = state.objectsById.get(id);
                    return id !== state.centerId && Number(obj.userData.movie.rank) <= 5;
                }));
                state.transition.resolve();
                state.transition = null;
                controls.enabled = true;
            }
        }

        tickAnimLines();

        const hitTargets = [];
        state.objectsById.forEach((obj) => {
            if (!obj.userData.movie.center) hitTargets.push(obj.userData.hitMesh);
        });

        raycaster.setFromCamera(pointer, camera);
        const hits = raycaster.intersectObjects(hitTargets, false);
        const nextHovered = hits[0] ? hits[0].object : null;

        if (hoveredMesh !== nextHovered) {
            if (hoveredMesh) {
                const prevObj = state.objectsById.get(hoveredMesh.userData.movie.id);
                if (prevObj) setHoverOff(prevObj, hoveredMesh);
            }
            hoveredMesh = nextHovered;
            if (hoveredMesh) {
                const obj = state.objectsById.get(hoveredMesh.userData.movie.id);
                if (obj) setHoverOn(obj, hoveredMesh);
                renderer.domElement.style.cursor = 'pointer';
            } else {
                renderer.domElement.style.cursor = 'grab';
            }
        }

        renderer.render(scene, camera);
        labelRenderer.render(scene, camera);
        requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);

    return {
        applyGraph(payload, animated) {
            const data = toGraphNodes(payload);

            // Snapshot current world positions before tearing down
            const oldPositions = new Map();
            state.objectsById.forEach((obj, id) => {
                oldPositions.set(id, { x: obj.position.x, y: obj.position.y, z: obj.position.z });
            });
            const oldCenterPos = state.centerId && oldPositions.has(state.centerId)
                ? oldPositions.get(state.centerId)
                : { x: 0, y: 0, z: 0 };

            // Tear down all existing nodes cleanly
            hoveredMesh = null;
            state.objectsById.forEach((obj) => removeNodeObject(obj));
            state.objectsById.clear();
            retractAllLines();

            // Build all new nodes
            const startById = new Map();
            data.nodes.forEach((n) => {
                const obj = buildNodeObject(n);

                if (animated) {
                    const startPos = oldPositions.get(n.id) || oldCenterPos;
                    obj.position.set(startPos.x, startPos.y, startPos.z);
                    startById.set(n.id, { ...startPos });
                }

                graphGroup.add(obj);
                state.objectsById.set(n.id, obj);
            });

            state.pendingCenterId = data.centerId;

            if (!animated) {
                state.centerId = data.centerId;
                spawnLines(data.centerId, data.nodes
                    .filter((n) => !n.center && Number(n.rank) <= 5)
                    .map((n) => n.id));
                state.animLines.forEach((al) => { al.progress = 1; });
                return Promise.resolve();
            }

            return new Promise((resolve) => {
                state.transition = {
                    start: performance.now(),
                    duration: 2200,
                    startById,
                    resolve,
                };
            });
        },
    };
}

async function fetchAutocomplete(q) {
    try {
        const res = await fetch(`/autocomplete?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        if (!Array.isArray(data) || data.length === 0) {
            acList.classList.remove('visible');
            return;
        }

        acList.innerHTML = '';
        data.forEach((title) => {
            const item = document.createElement('div');
            item.textContent = title;
            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
                input.value = title;
                acList.classList.remove('visible');
                performSearch(title, true);
            });
            acList.appendChild(item);
        });
        acList.classList.add('visible');
    } catch (_err) {
        acList.classList.remove('visible');
    }
}

const nSelect = document.getElementById('n-select');

async function performSearch(query, animated) {
    const q = (query || input.value || '').trim();
    if (!q || isBusy || !engine) return;

    message.textContent = '';
    isBusy = true;

    const n = nSelect ? nSelect.value : 25;

    try {
        const res = await fetch(`/graph?q=${encodeURIComponent(q)}&n=${n}`);
        const data = await res.json();
        if (!res.ok) {
            isBusy = false;
            message.textContent = data.error || 'Movie not found.';
            return;
        }

        input.value = data.center.title;
        setMeta(data.center, animated ? 'Center:' : 'Loaded:');
        lastPayload = data;
        await engine.applyGraph(data, animated);
        isBusy = false;
    } catch (_err) {
        isBusy = false;
        message.textContent = 'Could not reach the server.';
    }
}

function onNodeClick(title, movie) {
    setMeta(movie, 'Jumping To:');
    performSearch(title, true);
}

input.addEventListener('input', () => {
    clearTimeout(acTimeout);
    const q = input.value.trim();
    if (q.length < 2) {
        acList.classList.remove('visible');
        return;
    }
    acTimeout = setTimeout(() => fetchAutocomplete(q), 180);
});

input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        acList.classList.remove('visible');
        performSearch(input.value, true);
    }
    if (e.key === 'Escape') {
        acList.classList.remove('visible');
    }
});

button.addEventListener('click', () => {
    acList.classList.remove('visible');
    performSearch(input.value, true);
});

document.addEventListener('click', (e) => {
    if (!e.target.closest('.search')) {
        acList.classList.remove('visible');
    }
});

let engineMode = '3d'; // '3d' or '2d'
const engineToggle = document.getElementById('engine-toggle');

async function initEngine(mode) {
    engineMode = mode || engineMode;
    engine = null;

    if (engineMode === '3d') {
        try {
            engine = await createThreeEngine(onNodeClick);
            engineToggle.textContent = 'Switch to 2D';
            engineToggle.classList.remove('active-2d');
        } catch (_err) {
            message.textContent = '3D unavailable, falling back to 2D.';
            engineMode = '2d';
            engine = createFallbackEngine(onNodeClick);
            engineToggle.textContent = 'Switch to 3D';
            engineToggle.classList.add('active-2d');
        }
    } else {
        engine = createFallbackEngine(onNodeClick);
        engineToggle.textContent = 'Switch to 3D';
        engineToggle.classList.add('active-2d');
    }

    if (lastPayload) {
        await engine.applyGraph(lastPayload, false);
    } else {
        performSearch('The Avengers', false);
    }
}

engineToggle.addEventListener('click', () => {
    const next = engineMode === '3d' ? '2d' : '3d';
    initEngine(next);
});

initEngine();