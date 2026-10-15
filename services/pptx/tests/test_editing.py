import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent.deckspec import structure_errors
from app.config import Settings
from app.services import jobs
from app.services.jobs import JobManager

FIXTURE = Path(__file__).parent / "fixtures" / "sample_deck.json"


def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def client(tmp_path: Path, synthetic_template: Path, monkeypatch: pytest.MonkeyPatch):
    manager = JobManager(Settings(pptx_data_dir=tmp_path / "data"))
    monkeypatch.setattr(main, "manager", manager)
    monkeypatch.setattr(jobs, "render_previews", lambda deck, spec, output: [])
    job = manager.create("Make a deck", "", [], 0)
    workspace = manager.workspace(job)
    workspace.mkdir(parents=True)
    shutil.copy(synthetic_template, workspace / "template.pptx")
    (workspace / "deck.json").write_text(json.dumps(sample()), encoding="utf-8")
    job.status = "complete"
    return TestClient(main.app), manager, job


def test_manual_edits_skip_writer_conventions_but_not_layout_rules() -> None:
    deck = sample()
    deck["slides"] = deck["slides"][1:]
    deck["slides"][0]["headline"] = "A deliberately long headline " * 6
    assert structure_errors(deck, editorial=False) == []
    assert structure_errors(deck)

    content = next(slide for slide in deck["slides"] if slide["type"] not in {"agenda", "section"})
    content["section"] = "Not a section"
    assert any("section must exactly match" in error for error in structure_errors(deck, editorial=False))


def test_get_and_save_deck_rebuilds_the_presentation(client) -> None:
    http, manager, job = client
    loaded = http.get(f"/api/jobs/{job.id}/deck").json()
    assert loaded["deck"]["cover"]["title"] == sample()["cover"]["title"]
    assert "kpis" in loaded["schema"]["types"] and loaded["schema"]["header"]["headline"]["limit"] == 125

    deck = loaded["deck"]
    deck["cover"]["title"] = "Edited title"
    deck["slides"] = list(reversed(deck["slides"][2:5])) + deck["slides"][5:]
    response = http.put(f"/api/jobs/{job.id}/deck", json={"deck": deck})

    assert response.status_code == 200, response.text
    assert isinstance(response.json()["warnings"], list)
    assert manager.deck(job)["cover"]["title"] == "Edited title"
    assert job.status == "complete" and job.spec is not None
    assert job.spec.slides[0].title == "Edited title"
    assert manager.deck_path(job).exists()


def test_save_rejects_decks_that_cannot_render(client) -> None:
    http, manager, job = client
    deck = sample()
    deck["slides"][4]["rows"][0] = ["only one cell"]
    response = http.put(f"/api/jobs/{job.id}/deck", json={"deck": deck})

    assert response.status_code == 422
    assert any("row 1 has 1 cells" in error for error in response.json()["detail"]["errors"])
    assert manager.deck(job) == sample()


def test_save_is_blocked_while_a_run_is_in_progress(client) -> None:
    http, _manager, job = client
    job.status = "building"
    assert http.put(f"/api/jobs/{job.id}/deck", json={"deck": sample()}).status_code == 409


def _resolve(document, path):
    for key in path:
        document = document[key]
    return document


def test_text_regions_point_at_the_deck_fields_they_draw(client) -> None:
    http, _manager, job = client
    loaded = http.get(f"/api/jobs/{job.id}/deck").json()
    deck, regions = loaded["deck"], loaded["regions"]

    assert {region["slide"] for region in regions} >= set(range(1, len(deck["slides"]) + 1)) - {
        index + 1 for index, slide in enumerate(deck["slides"]) if slide["type"] == "section"
    }
    for region in regions:
        if region["title"]:
            continue
        for para in region["paras"]:
            assert str(_resolve(deck, para["path"])).strip() == para["text"].strip()
    assert any(region["paras"][0]["path"] == ["cover", "title"] for region in regions)
    lists = [region for region in regions if region["items"]]
    assert lists and all(region["items"]["low"] <= region["items"]["end"] - region["items"]["start"] for region in lists)


def test_edits_saved_while_previews_refresh_are_accepted_and_rendered(client, monkeypatch: pytest.MonkeyPatch) -> None:
    http, manager, job = client
    job.status = "rendering"
    deck = sample()
    deck["cover"]["title"] = "Saved during a refresh"
    response = http.put(f"/api/jobs/{job.id}/deck", json={"deck": deck})
    assert response.status_code == 200, response.text
    assert any(region["paras"][0]["text"] == "Saved during a refresh" for region in response.json()["regions"])

    published = []

    def publish(target):
        published.append(target.edits)
        if len(published) == 1:
            target.edits += 1

    monkeypatch.setattr(manager, "publish", publish)
    manager.render_edit(job)
    assert len(published) == 2 and job.status == "complete"
