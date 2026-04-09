const state = {
  mode: "static",
  catalog: null,
  staticScenarioId: null,
  staticBundle: null,
  dynamicRunId: null,
  dynamicBundle: null,
  currentBundle: null,
  currentLayer: "water_depth",
  currentFrameIdx: 0,
  map: null,
  overlay: null,
  contextLayers: {},
  playing: false,
  timer: null,
};

const elements = {
  healthBadge: document.getElementById("healthBadge"),
  modeBadge: document.getElementById("modeBadge"),
  scenarioSelect: document.getElementById("scenarioSelect"),
  dynamicTemplateSelect: document.getElementById("dynamicTemplateSelect"),
  layerSelect: document.getElementById("layerSelect"),
  timelineSlider: document.getElementById("timelineSlider"),
  timeLabel: document.getElementById("timeLabel"),
  rainLabel: document.getElementById("rainLabel"),
  selectedTitle: document.getElementById("selectedTitle"),
  legend: document.getElementById("legend"),
  maxDepthStat: document.getElementById("maxDepthStat"),
  floodedAreaStat: document.getElementById("floodedAreaStat"),
  floodedCellsStat: document.getElementById("floodedCellsStat"),
  peakFrameStat: document.getElementById("peakFrameStat"),
  playPauseBtn: document.getElementById("playPauseBtn"),
  prevFrameBtn: document.getElementById("prevFrameBtn"),
  nextFrameBtn: document.getElementById("nextFrameBtn"),
  staticModeBtn: document.getElementById("staticModeBtn"),
  dynamicModeBtn: document.getElementById("dynamicModeBtn"),
  liveModeBtn: document.getElementById("liveModeBtn"),
  staticPanel: document.getElementById("staticPanel"),
  dynamicPanel: document.getElementById("dynamicPanel"),
  livePanel: document.getElementById("livePanel"),
  outlineToggle: document.getElementById("outlineToggle"),
  colonyToggle: document.getElementById("colonyToggle"),
  drainageToggle: document.getElementById("drainageToggle"),
  gridToggle: document.getElementById("gridToggle"),
  hotspotToggle: document.getElementById("hotspotToggle"),
  rainfallInput: document.getElementById("rainfallInput"),
  hoursInput: document.getElementById("hoursInput"),
  runDynamicBtn: document.getElementById("runDynamicBtn"),
  liveHoursInput: document.getElementById("liveHoursInput"),
  refreshLiveBtn: document.getElementById("refreshLiveBtn"),
  runLiveBtn: document.getElementById("runLiveBtn"),
  liveSourceStat: document.getElementById("liveSourceStat"),
  livePeakRainStat: document.getElementById("livePeakRainStat"),
};

function initMap(bounds) {
  state.map = L.map("map", {
    zoomControl: true,
    attributionControl: false,
    scrollWheelZoom: false,
  });
  state.map.createPane("baseContext");
  state.map.getPane("baseContext").style.zIndex = 260;
  state.map.createPane("floodOverlay");
  state.map.getPane("floodOverlay").style.zIndex = 330;
  state.map.createPane("lineContext");
  state.map.getPane("lineContext").style.zIndex = 420;

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 16,
    attribution: "&copy; OpenStreetMap",
  }).addTo(state.map);
  state.contextLayers.grid = buildGridLayer(bounds);
  state.map.fitBounds(bounds, { padding: [12, 12] });
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function bundleForState() {
  return state.mode === "static" ? state.staticBundle : state.dynamicBundle;
}

function layerUrl() {
  if (state.mode === "static") {
    return `/api/static/scenarios/${state.staticScenarioId}/layers/${state.currentLayer}/${state.currentFrameIdx}`;
  }
  return `/api/dynamic/runs/${state.dynamicRunId}/layers/${state.currentLayer}/${state.currentFrameIdx}`;
}

function renderLegend() {
  const legends = state.catalog.layer_legends[state.currentLayer] || [];
  elements.legend.innerHTML = legends
    .map(
      (item) => `
        <div class="legend-item">
          <span class="legend-swatch" style="background:${item.color}"></span>
          <span>${item.label}</span>
        </div>
      `
    )
    .join("");
}

function preferredFrameIndex(bundle) {
  if (!bundle) return 0;
  if (bundle.summary && Number.isInteger(bundle.summary.peak_frame)) {
    return Math.max(0, Math.min(bundle.summary.peak_frame, bundle.timeline.length - 1));
  }
  if (bundle.meta && Number.isInteger(bundle.meta.default_timestep)) {
    return Math.max(0, Math.min(bundle.meta.default_timestep, bundle.timeline.length - 1));
  }
  return Math.max(0, bundle.timeline.length - 1);
}

function firstWetFrameIndex(bundle) {
  if (!bundle || !bundle.timeline.length) return 0;
  const index = bundle.timeline.findIndex((frame) => frame.max_depth_m > 0.02 || frame.flooded_cells > 0);
  return index >= 0 ? index : 0;
}

function updateSummary() {
  const bundle = bundleForState();
  if (!bundle) return;
  const frame = bundle.timeline[state.currentFrameIdx];
  elements.maxDepthStat.textContent = `${frame.max_depth_m.toFixed(2)} m`;
  elements.floodedAreaStat.textContent = `${frame.flooded_area_km2.toFixed(2)} km²`;
  elements.floodedCellsStat.textContent = `${frame.flooded_cells.toLocaleString()}`;
  elements.peakFrameStat.textContent = bundle.summary.peak_label;
  elements.timeLabel.textContent = frame.label;
  elements.rainLabel.textContent = `${frame.rainfall_mm_hr.toFixed(1)} mm/hr`;
}

function updateOverlay() {
  const bundle = bundleForState();
  if (!bundle || !state.map) return;
  const bounds = bundle.meta.bounds;
  const url = `${layerUrl()}?v=${Date.now()}`;
  const frame = bundle.timeline[state.currentFrameIdx];
  const peakDepth = Math.max(bundle.summary.peak_depth_m || 0, 0.01);
  const depthRatio = Math.max(0, Math.min(frame.max_depth_m / peakDepth, 1));
  const opacity = state.currentLayer === "water_depth" ? 0.35 + depthRatio * 0.55 : 0.78;
  if (state.overlay) {
    state.overlay.setUrl(url);
    state.overlay.setOpacity(opacity);
  } else {
    state.overlay = L.imageOverlay(url, bounds, { opacity, pane: "floodOverlay" }).addTo(state.map);
  }
  updateSummary();
}

function syncOutlineVisibility() {
  if (!state.map) return;
  const boundaryUnderlay = state.contextLayers.boundaryUnderlay;
  const boundaryStroke = state.contextLayers.boundaryStroke;
  if (elements.outlineToggle.checked) {
    if (boundaryUnderlay && !state.map.hasLayer(boundaryUnderlay)) {
      boundaryUnderlay.addTo(state.map);
    }
    if (boundaryStroke && !state.map.hasLayer(boundaryStroke)) {
      boundaryStroke.addTo(state.map);
    }
  } else {
    if (boundaryUnderlay && state.map.hasLayer(boundaryUnderlay)) {
      state.map.removeLayer(boundaryUnderlay);
    }
    if (boundaryStroke && state.map.hasLayer(boundaryStroke)) {
      state.map.removeLayer(boundaryStroke);
    }
  }
}

async function loadGeoJson(url, options = {}) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load ${url}`);
  }
  const data = await response.json();
  return L.geoJSON(data, options);
}

function latLonAt(bounds, xFrac, yFrac) {
  const [[minLat, minLon], [maxLat, maxLon]] = bounds;
  return [
    minLat + (maxLat - minLat) * yFrac,
    minLon + (maxLon - minLon) * xFrac,
  ];
}

function buildGridLayer(bounds) {
  const group = L.layerGroup();
  const cols = 5;
  const rows = 4;
  for (let col = 1; col < cols; col += 1) {
    const start = latLonAt(bounds, col / cols, 0);
    const end = latLonAt(bounds, col / cols, 1);
    L.polyline([start, end], {
      pane: "lineContext",
      color: "#64748b",
      weight: 1,
      opacity: 0.3,
      interactive: false,
    }).addTo(group);
  }
  for (let row = 1; row < rows; row += 1) {
    const start = latLonAt(bounds, 0, row / rows);
    const end = latLonAt(bounds, 1, row / rows);
    L.polyline([start, end], {
      pane: "lineContext",
      color: "#64748b",
      weight: 1,
      opacity: 0.3,
      interactive: false,
    }).addTo(group);
  }
  return group;
}

async function loadContextLayers() {
  const [boundaryUnderlay, boundaryStroke, colonies, drainageSwd, drainageNatural, hotspots] = await Promise.all([
    loadGeoJson("/assets/context/boundary.geojson", {
      pane: "lineContext",
      interactive: false,
      style: {
        color: "#ffffff",
        weight: 6,
        opacity: 0.92,
        fill: false,
      },
    }),
    loadGeoJson("/assets/context/boundary.geojson", {
      pane: "lineContext",
      interactive: false,
      style: {
        color: "#111827",
        weight: 2.2,
        opacity: 1.0,
        fill: false,
      },
    }),
    loadGeoJson("/assets/context/colonies.geojson", {
      pane: "lineContext",
      interactive: false,
      style: {
        color: "#111111",
        weight: 1,
        opacity: 0.78,
        fill: false,
      },
    }),
    loadGeoJson("/assets/context/drainage_swd.geojson", {
      pane: "lineContext",
      interactive: false,
      style: {
        color: "#38bdf8",
        weight: 2,
        opacity: 0.9,
      },
    }),
    loadGeoJson("/assets/context/drainage_natural_vector.geojson", {
      pane: "lineContext",
      interactive: false,
      style: {
        color: "#67e8f9",
        weight: 1.4,
        opacity: 0.85,
        dashArray: "4 4",
      },
    }),
    loadGeoJson("/assets/context/hotspots.geojson", {
      pane: "lineContext",
      interactive: false,
      pointToLayer: (_, latlng) =>
        L.circleMarker(latlng, {
          radius: 4,
          color: "#f43f5e",
          weight: 1.2,
          fillColor: "#fb7185",
          fillOpacity: 0.75,
        }),
    }),
  ]);

  state.contextLayers.boundaryUnderlay = boundaryUnderlay;
  state.contextLayers.boundaryStroke = boundaryStroke;
  state.contextLayers.colonies = colonies;
  state.contextLayers.drainage = L.layerGroup([drainageSwd, drainageNatural]);
  state.contextLayers.hotspots = hotspots;
}

function syncContextLayers() {
  const toggles = [
    ["colonyToggle", "colonies"],
    ["drainageToggle", "drainage"],
    ["gridToggle", "grid"],
    ["hotspotToggle", "hotspots"],
  ];
  toggles.forEach(([toggleKey, layerKey]) => {
    const toggle = elements[toggleKey];
    const layer = state.contextLayers[layerKey];
    if (!toggle || !layer || !state.map) return;
    if (toggle.checked) {
      if (!state.map.hasLayer(layer)) {
        layer.addTo(state.map);
      }
    } else if (state.map.hasLayer(layer)) {
      state.map.removeLayer(layer);
    }
  });
}

function updateTitle() {
  const bundle = bundleForState();
  if (!bundle) return;
  elements.selectedTitle.textContent = bundle.meta.title || bundle.meta.source_id;
}

function setBundle(bundle, options = {}) {
  const { preserveFrame = false } = options;
  state.currentBundle = bundle;
  state.currentFrameIdx = preserveFrame
    ? Math.min(state.currentFrameIdx, bundle.timeline.length - 1)
    : preferredFrameIndex(bundle);
  elements.timelineSlider.max = Math.max(bundle.timeline.length - 1, 0);
  elements.timelineSlider.value = state.currentFrameIdx;
  updateTitle();
  renderLegend();
  updateOverlay();
}

async function loadStaticScenario(scenarioId) {
  state.staticScenarioId = scenarioId;
  state.staticBundle = await fetchJSON(`/api/static/scenarios/${scenarioId}/bundle`);
  setBundle(state.staticBundle);
}

async function loadDynamicRun(runId) {
  state.dynamicRunId = runId;
  state.dynamicBundle = await fetchJSON(`/api/dynamic/runs/${runId}/bundle`);
  setBundle(state.dynamicBundle);
}

function stopPlayback() {
  state.playing = false;
  elements.playPauseBtn.textContent = "Play";
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

function startPlayback() {
  stopPlayback();
  const bundle = bundleForState();
  if (bundle && state.currentFrameIdx >= preferredFrameIndex(bundle)) {
    state.currentFrameIdx = firstWetFrameIndex(bundle);
    elements.timelineSlider.value = state.currentFrameIdx;
    updateOverlay();
  }
  state.playing = true;
  elements.playPauseBtn.textContent = "Pause";
  state.timer = setInterval(() => {
    const activeBundle = bundleForState();
    if (!activeBundle) return;
    state.currentFrameIdx = (state.currentFrameIdx + 1) % activeBundle.timeline.length;
    elements.timelineSlider.value = state.currentFrameIdx;
    updateOverlay();
  }, 700);
}

function setMode(mode) {
  state.mode = mode;
  elements.modeBadge.textContent = mode === "static" ? "Static" : mode === "live" ? "Live" : "Dynamic";
  elements.staticModeBtn.classList.toggle("active", mode === "static");
  elements.dynamicModeBtn.classList.toggle("active", mode === "dynamic");
  elements.liveModeBtn.classList.toggle("active", mode === "live");
  elements.staticPanel.classList.toggle("hidden", mode !== "static");
  elements.dynamicPanel.classList.toggle("hidden", mode !== "dynamic");
  elements.livePanel.classList.toggle("hidden", mode !== "live");
  state.currentFrameIdx = 0;
  stopPlayback();
  if (mode === "static" && state.staticBundle) {
    setBundle(state.staticBundle);
  }
  if ((mode === "dynamic" || mode === "live") && state.dynamicBundle) {
    setBundle(state.dynamicBundle);
  }
}

async function refreshLiveWeather() {
  const hours = Number(elements.liveHoursInput.value || 12);
  const weather = await fetchJSON(`/api/live/weather?hours=${hours}`);
  elements.liveSourceStat.textContent = weather.source.replaceAll("_", " ");
  elements.livePeakRainStat.textContent = `${weather.peak_intensity_mm_hr.toFixed(1)} mm/hr`;
  elements.rainfallInput.value = weather.hourly_mm.map((value) => value.toFixed(2)).join(", ");
  elements.hoursInput.value = weather.duration_hours;
  return weather;
}

async function init() {
  const health = await fetchJSON("/api/health");
  elements.healthBadge.textContent = health.predictor_loaded ? "Model ready" : "Model unavailable";
  elements.healthBadge.classList.toggle("secondary", !health.predictor_loaded);

  state.catalog = await fetchJSON("/api/static/catalog");
  initMap(state.catalog.bounds);
  await loadContextLayers();

  state.catalog.scenarios.forEach((scenario) => {
    const option = document.createElement("option");
    option.value = scenario.scenario_id;
    option.textContent = scenario.title;
    elements.scenarioSelect.appendChild(option);

    const dynamicOption = document.createElement("option");
    dynamicOption.value = scenario.scenario_id;
    dynamicOption.textContent = scenario.title;
    elements.dynamicTemplateSelect.appendChild(dynamicOption);
  });

  state.catalog.scenarios[0].available_layers.forEach((layer) => {
    const option = document.createElement("option");
    option.value = layer;
    option.textContent = layer.replaceAll("_", " ");
    elements.layerSelect.appendChild(option);
  });
  elements.layerSelect.value = state.currentLayer;

  const defaultScenario = state.catalog.default_scenario || state.catalog.scenarios[0].scenario_id;
  elements.scenarioSelect.value = defaultScenario;
  elements.dynamicTemplateSelect.value = defaultScenario;
  await loadStaticScenario(defaultScenario);
  populateDynamicTemplate(defaultScenario);
  syncOutlineVisibility();
  syncContextLayers();
}

function populateDynamicTemplate(scenarioId) {
  const scenario = state.catalog.scenarios.find((item) => item.scenario_id === scenarioId);
  if (!scenario) return;
  elements.hoursInput.value = scenario.duration_hours;
  fetch(`/api/static/scenarios/${scenarioId}/bundle`)
    .then((res) => res.json())
    .then((bundle) => {
      const rainfall = bundle.timeline.map((frame) => frame.rainfall_mm_hr.toFixed(2));
      elements.rainfallInput.value = rainfall.join(", ");
    })
    .catch(() => {});
}

elements.scenarioSelect.addEventListener("change", async (event) => {
  stopPlayback();
  state.currentFrameIdx = 0;
  await loadStaticScenario(event.target.value);
});

elements.dynamicTemplateSelect.addEventListener("change", (event) => {
  populateDynamicTemplate(event.target.value);
});

elements.layerSelect.addEventListener("change", (event) => {
  state.currentLayer = event.target.value;
  renderLegend();
  updateOverlay();
});

elements.outlineToggle.addEventListener("change", () => {
  syncOutlineVisibility();
});

elements.colonyToggle.addEventListener("change", () => {
  syncContextLayers();
});

elements.drainageToggle.addEventListener("change", () => {
  syncContextLayers();
});

elements.gridToggle.addEventListener("change", () => {
  syncContextLayers();
});

elements.hotspotToggle.addEventListener("change", () => {
  syncContextLayers();
});

elements.timelineSlider.addEventListener("input", (event) => {
  state.currentFrameIdx = Number(event.target.value);
  updateOverlay();
});

elements.playPauseBtn.addEventListener("click", () => {
  if (state.playing) stopPlayback();
  else startPlayback();
});

elements.prevFrameBtn.addEventListener("click", () => {
  const bundle = bundleForState();
  if (!bundle) return;
  state.currentFrameIdx = (state.currentFrameIdx - 1 + bundle.timeline.length) % bundle.timeline.length;
  elements.timelineSlider.value = state.currentFrameIdx;
  updateOverlay();
});

elements.nextFrameBtn.addEventListener("click", () => {
  const bundle = bundleForState();
  if (!bundle) return;
  state.currentFrameIdx = (state.currentFrameIdx + 1) % bundle.timeline.length;
  elements.timelineSlider.value = state.currentFrameIdx;
  updateOverlay();
});

elements.staticModeBtn.addEventListener("click", () => setMode("static"));
elements.dynamicModeBtn.addEventListener("click", () => setMode("dynamic"));
elements.liveModeBtn.addEventListener("click", async () => {
  setMode("live");
  await refreshLiveWeather();
});

elements.runDynamicBtn.addEventListener("click", async () => {
  const rainfall = elements.rainfallInput.value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));
  const hours = Number(elements.hoursInput.value);
  const payload = {
    rainfall_hourly: rainfall,
    hours,
    timestep_minutes: 15,
    run_label: "Dynamic forecast",
  };
  const response = await fetchJSON("/api/dynamic/predict", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  setMode("dynamic");
  await loadDynamicRun(response.run_id);
});

elements.refreshLiveBtn.addEventListener("click", async () => {
  await refreshLiveWeather();
});

elements.runLiveBtn.addEventListener("click", async () => {
  const hours = Number(elements.liveHoursInput.value || 12);
  const response = await fetchJSON("/api/live/predict", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      hours,
      timestep_minutes: 15,
    }),
  });
  elements.liveSourceStat.textContent = response.weather.source.replaceAll("_", " ");
  elements.livePeakRainStat.textContent = `${response.weather.peak_intensity_mm_hr.toFixed(1)} mm/hr`;
  setMode("live");
  await loadDynamicRun(response.run_id);
});

init().catch((error) => {
  console.error(error);
  elements.selectedTitle.textContent = "Dashboard unavailable";
});
