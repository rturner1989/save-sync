import json
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

CONFIG_PATH = Path.home() / ".config" / "save-sync" / "config.json"
BACKUP_DIR = Path.home() / ".config" / "save-sync" / "backups"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {"games": [], "port": 8080}


def write_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    config = load_config()
    return templates.TemplateResponse(
        "index.html", {"request": request, "games": config["games"]}
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    config = load_config()
    return templates.TemplateResponse(
        "settings.html", {"request": request, "games": config["games"]}
    )


# ── Settings actions ───────────────────────────────────────────────────────────

@app.post("/settings/add")
async def add_game(
    name: str = Form(...),
    retroarch_path: str = Form(...),
    delta_name: str = Form(""),
):
    config = load_config()
    config["games"].append({"name": name, "retroarch_path": retroarch_path.strip(), "delta_name": delta_name.strip()})
    write_config(config)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/delete/{game_id}")
async def delete_game(game_id: int):
    config = load_config()
    config["games"].pop(game_id)
    write_config(config)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/update/{game_id}")
async def update_game(
    game_id: int,
    name: str = Form(...),
    retroarch_path: str = Form(...),
    delta_name: str = Form(""),
):
    config = load_config()
    config["games"][game_id] = {"name": name, "retroarch_path": retroarch_path.strip(), "delta_name": delta_name.strip()}
    write_config(config)
    return RedirectResponse("/settings", status_code=303)


# ── Sync actions ───────────────────────────────────────────────────────────────

@app.get("/game/{game_id}/download")
async def download_save(game_id: int):
    """Send the RetroArch .srm to the iPhone as a .sav file."""
    config = load_config()
    try:
        game = config["games"][game_id]
    except IndexError:
        return JSONResponse({"error": "Game not found"}, status_code=404)

    srm_path = Path(game["retroarch_path"])
    if not srm_path.exists():
        return JSONResponse(
            {"error": f"Save file not found. Check the path in Settings: {srm_path}"},
            status_code=404,
        )

    # Copy to a temp file with .sav extension so the browser names it correctly
    tmp = tempfile.NamedTemporaryFile(suffix=".sav", delete=False)
    shutil.copy2(srm_path, tmp.name)

    delta_name = game.get("delta_name", "").strip()
    sav_name = (delta_name if delta_name else srm_path.stem) + ".sav"
    return FileResponse(
        tmp.name,
        filename=sav_name,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{sav_name}"'},
    )


@app.post("/game/{game_id}/upload")
async def upload_save(game_id: int, file: UploadFile = File(...)):
    """Receive a .sav from the iPhone and save it as the RetroArch .srm."""
    config = load_config()
    try:
        game = config["games"][game_id]
    except IndexError:
        return JSONResponse({"error": "Game not found"}, status_code=404)

    srm_path = Path(game["retroarch_path"])

    # Back up existing save before overwriting
    if srm_path.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        import time
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"{srm_path.stem}_{timestamp}.srm.bak"
        shutil.copy2(srm_path, backup_path)

    contents = await file.read()
    srm_path.parent.mkdir(parents=True, exist_ok=True)
    srm_path.write_bytes(contents)

    return JSONResponse({"status": "ok", "saved_to": str(srm_path)})
