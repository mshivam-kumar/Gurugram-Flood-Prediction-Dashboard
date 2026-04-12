# Gurugram Flood Prediction Dashboard

This repository contains the dashboard application layer used in the thesis work on PG-AR-FNO for urban flood prediction in Gurugram.

The app provides three working modes:

- `Static`: browse precomputed flood scenarios stored as dashboard assets
- `Dynamic`: generate a run from user-supplied rainfall values
- `Live`: fetch rainfall from a weather service and generate a run through the same pipeline

## What this repository contains

- FastAPI server and API routes
- dashboard frontend with map playback, layers, summaries, and mode switching
- static scenario assets used for demonstration
- GIS context layers for city boundary, colonies, drainage, and hotspots
- screenshots used for documentation and thesis integration

## Important scope note

This repository is the `/app` portion of the larger thesis workspace. It is meant to be published as the software artifact behind the thesis chapter and GitHub link.

It is **not** packaged here as a fully standalone training or deployment repository. Some runtime paths in the code still expect the broader project layout for model checkpoints and processed tensors.

## Running the app in the thesis workspace

Run it from the parent thesis workspace:

```bash
conda activate shivam
python -m uvicorn app.server:app --host 0.0.0.0 --port 8009
```

Then open:

```text
http://127.0.0.1:8009
```

## Runtime dependencies

The dashboard code depends on:

- Python 3.10+
- `fastapi`
- `uvicorn`
- `numpy`
- `pillow`
- `pydantic`
- `torch`

An example dependency file is included as `requirements.txt`.

## Optional live rainfall setup

For live rainfall mode, set:

```bash
export OPENWEATHERMAP_API_KEY=your_key_here
```

If the key is not available, the app falls back to a labelled demonstration rainfall sequence for the live mode UI.

## Repository structure

```text
app/
  api/          request and response schemas
  assets/       static dashboard assets and GIS context layers
  core/         predictor, bundling, hazard, and alert logic
  data/         city profile metadata used by the dashboard
  services/     weather service integration
  static/       frontend HTML, CSS, and JavaScript
  server.py     FastAPI entrypoint
```

## Screenshots

Reference screenshots used in the thesis are stored in:

```text
screenshots/
```

The dashboard home screen used in the thesis chapter is available at:

```text
screenshots/software_home_screen.png
```
