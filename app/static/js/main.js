import { fetchPoster } from './utils.js';

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
    clearSpaceElement();
    const THREE = await import('https://cdn.jsdelivr.net/npm/three@0.164.1/build/three.module.js');
    const { OrbitControls } = await import('https://cdn.jsdelivr.net/npm/three@0.164.1/examples/jsm/controls/OrbitControls.js');
    const { CSS2DRenderer, CSS2DObject } = await import('https://cdn.jsdelivr.net/npm/three@0.164.1/examples/jsm/renderers/CSS2DRenderer.js');

    let hoveredMesh = null;
    const state = { objectsById: new Map(), centerId: null, pendingCenterId: null, connections: [], transition: null };

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
        starPos[i * 3 + 0] = (Math.random() - 0.5) * 2000;
        starPos[i * 3 + 1] = (Math.random() - 0.5) * 1200;
        starPos[i * 3 + 2] = (Math.random() - 0.5) * 1800;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0xd7e8ff, size: 1.45, transparent: true, opacity: 0.8 }));
    scene.add(stars);

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    function makeLabel(text, isCenter) {
        const el = document.createElement('div');
        el.className = isCenter ? 'label center' : 'label';
        el.textContent = text;
        return new CSS2DObject(el);
    }

    function buildNodeObject(node) {
        const group = new THREE.Group();
        group.position.set(node.x, node.y, node.z);
        const mesh = new THREE.Mesh(
            new THREE.SphereGeometry(node.radius, 28, 28),
            new THREE.MeshStandardMaterial({
                color: node.color,
                emissive: node.center ? 0x1acfa4 : (node.primary ? 0x295ea7 : 0x16273f),
                emissiveIntensity: node.center ? 0.62 : (node.primary ? 0.32 : 0.08),
                metalness: 0.12,
                roughness: 0.38,
                transparent: !node.center && !node.primary,
                opacity: !node.center && !node.primary ? 0.28 : 1,
            }),
        );
        mesh.userData.movie = node;
        group.add(mesh);
        const halo = new THREE.Mesh(
            new THREE.SphereGeometry(node.radius * (node.center ? 1.65 : 1.45), 24, 24),
            new THREE.MeshBasicMaterial({
                color: node.center ? 0x67f5d6 : (node.primary ? 0x7cc0ff : 0x355276),
                transparent: true,
                opacity: node.center ? 0.23 : (node.primary ? 0.15 : 0.04),
                depthWrite: false,
            }),
        );
        group.add(halo);
        const label = makeLabel(node.title, node.center);
        if (!node.center && !node.primary) {
            label.element.style.display = 'none';
        }
        label.position.set(0, node.radius + 6.2, 0);
        group.add(label);
        group.userData = { mesh, label, target: new THREE.Vector3(node.x, node.y, node.z), movie: node };
        return group;
    }

    function rebuildConnections() {
        state.connections.forEach((line) => graphGroup.remove(line));
        state.connections = [];
        const centerObj = state.objectsById.get(state.centerId);
        if (!centerObj) return;
        state.objectsById.forEach((obj, id) => {
            if (id === state.centerId || Number(obj.userData.movie.rank) > 5) return;
            const geo = new THREE.BufferGeometry().setFromPoints([centerObj.position.clone(), obj.position.clone()]);
            const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0x79beff, transparent: true, opacity: 0.72 }));
            graphGroup.add(line);
            state.connections.push({ line, id });
        });
    }

    function updateConnections() {
        const centerObj = state.objectsById.get(state.centerId);
        if (!centerObj) return;
        state.connections.forEach(({ line, id }) => {
            const obj = state.objectsById.get(id);
            if (!obj) return;
            const arr = line.geometry.attributes.position.array;
            arr[0] = centerObj.position.x; arr[1] = centerObj.position.y; arr[2] = centerObj.position.z;
            arr[3] = obj.position.x; arr[4] = obj.position.y; arr[5] = obj.position.z;
            line.geometry.attributes.position.needsUpdate = true;
        });
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
        onNodeClick(movie.title, movie);
    });

    function tick(now) {

        if (state.transition) {
            const elapsed = now - state.transition.start;
            const p = Math.min(1, elapsed / state.transition.duration);
            const eased = p < 0.5
                ? 4 * p * p * p
                : 1 - Math.pow(-2 * p + 2, 3) / 2;

            state.objectsById.forEach((obj, id) => {
                const start = state.transition.startById.get(id) || { x: 0, y: 0, z: -220 };
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
                rebuildConnections();
                state.transition.resolve();
                state.transition = null;
                controls.enabled = true;
            }
        }

        updateConnections();

        raycaster.setFromCamera(pointer, camera);
        const hits = raycaster.intersectObjects(Array.from(state.objectsById.values()).map((o) => o.userData.mesh).filter((m) => !m.userData.movie.center), false);
        const nextHovered = hits[0] ? hits[0].object : null;
        if (hoveredMesh && hoveredMesh !== nextHovered) {
            hoveredMesh.material.emissiveIntensity = hoveredMesh.userData.movie.primary ? 0.32 : 0.08;
            hoveredMesh.scale.setScalar(1);
        }
        hoveredMesh = nextHovered;
        if (hoveredMesh) {
            hoveredMesh.material.emissiveIntensity = 0.95;
            hoveredMesh.scale.setScalar(1.14);
            renderer.domElement.style.cursor = 'pointer';
        } else {
            renderer.domElement.style.cursor = 'grab';
        }

        renderer.render(scene, camera);
        labelRenderer.render(scene, camera);
        requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);

    return {
        applyGraph(payload, animated) {
            const data = toGraphNodes(payload);
            if (!animated || state.objectsById.size === 0) {
                state.objectsById.forEach((obj) => graphGroup.remove(obj));
                state.objectsById.clear();
                data.nodes.forEach((n) => {
                    const obj = buildNodeObject(n);
                    graphGroup.add(obj);
                    state.objectsById.set(n.id, obj);
                });
                state.centerId = data.centerId;
                rebuildConnections();
                return Promise.resolve();
            }

            const oldMap = new Map(state.objectsById);
            const nextMap = new Map();
            data.nodes.forEach((n) => {
                let obj = oldMap.get(n.id);
                if (!obj) {
                    obj = buildNodeObject(n);
                    const centerObj = state.objectsById.get(state.centerId);
                    if (centerObj) obj.position.copy(centerObj.position);
                    graphGroup.add(obj);
                }
                obj.userData.movie = n;
                obj.userData.mesh.userData.movie = n;
                obj.userData.target = new THREE.Vector3(n.x, n.y, n.z);
                obj.userData.label.element.textContent = n.title;
                obj.userData.label.element.className = n.center ? 'label center' : 'label';
                obj.userData.label.element.style.display = (!n.center && !n.primary) ? 'none' : 'block';
                nextMap.set(n.id, obj);
            });

            oldMap.forEach((obj, id) => {
                if (!nextMap.has(id)) {
                    graphGroup.remove(obj);
                }
            });

            state.objectsById = nextMap;
            state.pendingCenterId = data.centerId;
            return new Promise((resolve) => {
                const startById = new Map();
                state.objectsById.forEach((obj, id) => {
                    startById.set(id, { x: obj.position.x, y: obj.position.y, z: obj.position.z });
                });
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

async function performSearch(query, animated) {
    const q = (query || input.value || '').trim();
    if (!q || isBusy || !engine) return;

    message.textContent = '';
    isBusy = true;

    try {
        const res = await fetch(`/graph?q=${encodeURIComponent(q)}&n=25`);
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

function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
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

async function initEngine() {
    try {
        engine = await createThreeEngine(onNodeClick);
    } catch (_err) {
        message.textContent = '3D CDN blocked here. Using built-in renderer fallback.';
        engine = createFallbackEngine(onNodeClick);
    }
    if (lastPayload) {
        await engine.applyGraph(lastPayload, false);
    } else {
        performSearch('Creed III', false);
    }
}

initEngine();