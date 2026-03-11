import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

import main


FAKE_SAVE = b"\x00\xFF" * 64  # 128 bytes of fake save data


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_paths(tmp_path, monkeypatch):
    """Redirect config and backup paths into a temp directory for every test."""
    monkeypatch.setattr(main, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(main, "BACKUP_DIR", tmp_path / "backups")


@pytest.fixture
def client():
    return TestClient(main.app, follow_redirects=True)


@pytest.fixture
def srm_file(tmp_path):
    """A real .srm file on disk."""
    path = tmp_path / "TestGame.srm"
    path.write_bytes(FAKE_SAVE)
    return path


@pytest.fixture
def one_game(tmp_path, srm_file):
    """Config pre-loaded with one game."""
    config = {
        "games": [
            {
                "name": "Test Game",
                "retroarch_path": str(srm_file),
                "delta_name": "Test Game Delta",
            }
        ]
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    main.CONFIG_PATH = config_path
    return config


# ── Page routes ────────────────────────────────────────────────────────────────

class TestPages:
    def test_index_empty(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert "No games added yet" in res.text

    def test_index_shows_games(self, client, one_game):
        res = client.get("/")
        assert res.status_code == 200
        assert "Test Game" in res.text

    def test_settings_page(self, client):
        res = client.get("/settings")
        assert res.status_code == 200
        assert "Add game" in res.text


# ── Settings actions ───────────────────────────────────────────────────────────

class TestSettingsAdd:
    def test_add_game(self, client, srm_file):
        res = client.post("/settings/add", data={
            "name": "My Game",
            "retroarch_path": str(srm_file),
            "delta_name": "My Game Delta",
        })
        assert res.status_code == 200  # followed redirect to /settings
        config = main.load_config()
        assert len(config["games"]) == 1
        game = config["games"][0]
        assert game["name"] == "My Game"
        assert game["retroarch_path"] == str(srm_file)
        assert game["delta_name"] == "My Game Delta"

    def test_add_game_strips_whitespace(self, client, srm_file):
        client.post("/settings/add", data={
            "name": "My Game",
            "retroarch_path": f"  {srm_file}  ",
            "delta_name": "  Delta Name  ",
        })
        game = main.load_config()["games"][0]
        assert game["retroarch_path"] == str(srm_file)
        assert game["delta_name"] == "Delta Name"

    def test_add_game_without_delta_name(self, client, srm_file):
        client.post("/settings/add", data={
            "name": "My Game",
            "retroarch_path": str(srm_file),
        })
        game = main.load_config()["games"][0]
        assert game["delta_name"] == ""


class TestSettingsUpdate:
    def test_update_game(self, client, one_game, srm_file):
        res = client.post("/settings/update/0", data={
            "name": "Updated Name",
            "retroarch_path": str(srm_file),
            "delta_name": "Updated Delta",
        })
        assert res.status_code == 200
        game = main.load_config()["games"][0]
        assert game["name"] == "Updated Name"
        assert game["delta_name"] == "Updated Delta"


class TestSettingsDelete:
    def test_delete_game(self, client, one_game):
        res = client.post("/settings/delete/0")
        assert res.status_code == 200
        assert main.load_config()["games"] == []

    def test_delete_nonexistent_game(self, client):
        with pytest.raises(IndexError):
            client.post("/settings/delete/99")


# ── Download ───────────────────────────────────────────────────────────────────

class TestDownload:
    def test_download_uses_delta_name(self, client, one_game):
        res = client.get("/game/0/download")
        assert res.status_code == 200
        assert res.headers["content-disposition"] == 'attachment; filename="Test Game Delta.sav"'
        assert res.content == FAKE_SAVE

    def test_download_falls_back_to_srm_stem(self, client, tmp_path, srm_file):
        config = {"games": [{"name": "X", "retroarch_path": str(srm_file), "delta_name": ""}]}
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(config))
        main.CONFIG_PATH = cfg

        res = client.get("/game/0/download")
        assert res.status_code == 200
        assert 'filename="TestGame.sav"' in res.headers["content-disposition"]

    def test_download_missing_save_file(self, client, tmp_path):
        config = {"games": [{"name": "X", "retroarch_path": "/nonexistent/path/game.srm", "delta_name": ""}]}
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(config))
        main.CONFIG_PATH = cfg

        res = client.get("/game/0/download")
        assert res.status_code == 404
        assert "Save file not found" in res.json()["error"]

    def test_download_game_not_found(self, client):
        res = client.get("/game/99/download")
        assert res.status_code == 404
        assert res.json()["error"] == "Game not found"


# ── Upload ─────────────────────────────────────────────────────────────────────

class TestUpload:
    def test_upload_writes_srm(self, client, one_game, srm_file):
        new_save = b"\xAB\xCD" * 64
        res = client.post(
            "/game/0/upload",
            files={"file": ("save.sav", new_save, "application/octet-stream")},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
        assert srm_file.read_bytes() == new_save

    def test_upload_creates_backup(self, client, one_game, srm_file, tmp_path):
        original = srm_file.read_bytes()
        client.post(
            "/game/0/upload",
            files={"file": ("save.sav", b"\xAB" * 128, "application/octet-stream")},
        )
        backup_dir = tmp_path / "backups"
        backups = list(backup_dir.glob("*.srm.bak"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original

    def test_upload_game_not_found(self, client):
        res = client.post(
            "/game/99/upload",
            files={"file": ("save.sav", b"\x00" * 128, "application/octet-stream")},
        )
        assert res.status_code == 404
        assert res.json()["error"] == "Game not found"

    def test_upload_no_backup_when_srm_missing(self, client, tmp_path):
        """If no existing save, upload should succeed without creating a backup."""
        srm_path = tmp_path / "saves" / "NewGame.srm"
        config = {"games": [{"name": "X", "retroarch_path": str(srm_path), "delta_name": ""}]}
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(config))
        main.CONFIG_PATH = cfg

        res = client.post(
            "/game/0/upload",
            files={"file": ("save.sav", FAKE_SAVE, "application/octet-stream")},
        )
        assert res.status_code == 200
        assert srm_path.read_bytes() == FAKE_SAVE
        assert not (tmp_path / "backups").exists()
