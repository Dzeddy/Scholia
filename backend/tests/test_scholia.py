"""Automated pytest suite for Scholia backend, document ingestion, FSRS, DAG, Oral Exam, CLI runner, and FastMCP."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest
from ebooklib import epub
from fastapi.testclient import TestClient

from mcp_server import ScholiaMCPToolkit
from scholia.app import create_app
from scholia.config import StageRoute
from scholia.db import VaultDB
from scholia.fsrs import retrievability, schedule_fsrs
from scholia.services.agent_runner import AgentRunner
from scholia.services.ingestion import IngestionService
from scholia.services.vault import VaultFS
from seed_demo import generate_algorithms_sample_pdf, seed_demo_vault


def _make_sample_epub(tmp_path: Path) -> bytes:
    book = epub.EpubBook()
    book.set_identifier("scholia-test-epub")
    book.set_title("Test Systems Monograph")
    book.set_language("en")
    book.add_author("Ada Tester")

    c1 = epub.EpubHtml(title="Consensus Basics", file_name="chap_01.xhtml", lang="en")
    c1.content = "<html><body><h1>Consensus Basics</h1><p>Quorum intersection guarantees a single agreed value across replicas.</p></body></html>"
    c2 = epub.EpubHtml(title="Log Compaction", file_name="chap_02.xhtml", lang="en")
    c2.content = "<html><body><h1>Log Compaction</h1><p>Snapshots bound replay time while preserving prefix invariants.</p></body></html>"

    book.add_item(c1)
    book.add_item(c2)
    book.toc = (c1, c2)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1, c2]

    out = tmp_path / "sample.epub"
    epub.write_epub(str(out), book)
    return out.read_bytes()


def test_pdf_toc_extraction_slicing_and_oversize_chunking(tmp_path: Path):
    db = VaultDB(tmp_path)
    fs = VaultFS(tmp_path)
    svc = IngestionService(db, fs)

    pdf_bytes = generate_algorithms_sample_pdf()
    book = svc.ingest_upload("algo.pdf", pdf_bytes, topic_areas=["Algorithms"])
    assert book["source_format"] == "pdf"
    assert book["page_count"] == 10
    assert len(book["chapters"]) == 3
    assert book["chapters"][1]["start_page"] == 4
    assert book["chapters"][1]["end_page"] == 7

    # Verify per-chapter sliced PDF has exact page count (4 pages: pp. 4..7)
    ch2 = book["chapters"][1]
    sliced_pdf = fs.chapter_source_pdf(book["slug"], ch2["slug"])
    assert sliced_pdf.exists()
    with fitz.open(str(sliced_pdf)) as d:
        assert len(d) == 4

    # Verify PNG rendering works
    png = svc.render_chapter_page_png(book["slug"], ch2["slug"], 2)
    assert png.exists() and png.stat().st_size > 1000

    # Verify >20-page auto-slicing safeguard
    big_doc = fitz.open()
    for i in range(26):
        p = big_doc.new_page()
        p.insert_text((72, 72), f"Synthetic Textbook Page {i + 1}")
    big_bytes = big_doc.tobytes()
    big_doc.close()

    big_book = svc.ingest_upload("long_chapter.pdf", big_bytes)
    updated_big = svc.update_boundaries(
        big_book["id"],
        [{"title": "Single 26-Page Chapter", "start_page": 1, "end_page": 26}],
    )
    slices = svc.extract_chapter_text_and_slices(updated_big["slug"], updated_big["chapters"][0], max_pages_per_slice=15)
    assert len(slices) == 2
    assert slices[0]["local_start"] == 1 and slices[0]["local_end"] == 15
    assert slices[1]["local_start"] == 16 and slices[1]["local_end"] == 26


def test_epub_and_markdown_ingestion(tmp_path: Path):
    db = VaultDB(tmp_path)
    fs = VaultFS(tmp_path)
    svc = IngestionService(db, fs)

    epub_bytes = _make_sample_epub(tmp_path)
    ebook = svc.ingest_upload("systems.epub", epub_bytes, topic_areas=["Distributed Systems"])
    assert ebook["source_format"] == "epub"
    assert len(ebook["chapters"]) == 2
    assert "Consensus Basics" in ebook["chapters"][0]["title"]

    md_bytes = b"# First Part\n\nMechanism details.\n\n# Second Part\n\nComplexity tradeoffs.\n"
    mbook = svc.ingest_upload("notes.md", md_bytes)
    assert mbook["source_format"] == "md"
    assert len(mbook["chapters"]) == 2
    assert mbook["chapters"][1]["title"] == "Second Part"


def test_fsrs_scheduling_and_retrievability():
    s1 = schedule_fsrs(0.0, 5.0, 0, 0, None, rating=3)
    assert s1.reps == 1
    assert s1.stability > 2.0
    assert s1.scheduled_days >= 1

    # Second Good review grows stability
    s2 = schedule_fsrs(s1.stability, s1.difficulty, s1.reps, s1.lapses, s1.last_review_at, rating=3)
    assert s2.reps == 2
    assert s2.stability >= s1.stability

    # Lapse (Again) reduces stability and increments lapses
    s3 = schedule_fsrs(10.0, 5.0, 4, 0, s1.last_review_at, rating=1)
    assert s3.lapses == 1
    assert s3.stability < 10.0
    assert s3.scheduled_days == 1
    assert 0.0 < retrievability(5.0, 10.0) < 1.0


def test_multi_parent_dag_and_cycle_rejection(tmp_path: Path):
    db = VaultDB(tmp_path)
    rec = db.upsert_concept("Recursion", topic_areas=["Algorithms"])
    trees = db.upsert_concept("Trees", topic_areas=["Algorithms"])
    dp = db.upsert_concept("Dynamic Programming", topic_areas=["Algorithms"])

    ok1, _ = db.add_concept_edge(rec["id"], dp["id"])
    ok2, _ = db.add_concept_edge(trees["id"], dp["id"])
    assert ok1 and ok2

    hydrated_dp = db.get_concept(dp["id"])
    assert set(hydrated_dp["parent_ids"]) == {rec["id"], trees["id"]}

    # Cycle rejection: dp -> rec must be blocked
    ok_cycle, msg = db.add_concept_edge(dp["id"], rec["id"])
    assert not ok_cycle
    assert "cycle" in msg.lower()


def test_cli_adapter_command_construction():
    runner = AgentRunner()
    ch_dir = Path("/tmp/chapter-test")

    agy_cmd = runner.build_command(
        StageRoute(provider="agy", model="gemini-4-neon", effort="high"),
        prompt="Extract chapter notes",
        chapter_dir=ch_dir,
        schema_file_path=Path("/tmp/schema.json"),
        conversation_id="conv-123",
    )
    assert agy_cmd[1:] == [
        "-p", "Extract chapter notes",
        "--output-format", "stream-json",
        "--model", "gemini-4-neon",
        "--effort", "high",
        "--json-schema", "/tmp/schema.json",
        "--conversation", "conv-123",
        "--add-dir", str(ch_dir),
    ]

    claude_cmd = runner.build_command(
        StageRoute(provider="claude", model="opus", effort="high"),
        prompt="Grade answer",
        chapter_dir=ch_dir,
        json_schema={"type": "object"},
        conversation_id="sess-99",
    )
    assert "--output-format" in claude_cmd and "stream-json" in claude_cmd
    assert "--verbose" in claude_cmd
    assert "--effort" in claude_cmd and "high" in claude_cmd
    assert "--resume" in claude_cmd and "sess-99" in claude_cmd
    assert "--json-schema" in claude_cmd

    codex_cmd = runner.build_command(
        StageRoute(provider="codex", model="gpt-5.4", effort="medium"),
        prompt="Read chapter images",
        chapter_dir=ch_dir,
        schema_file_path=Path("/tmp/schema.json"),
        image_paths=[Path("/tmp/page-001.png")],
    )
    assert codex_cmd[1:5] == ["exec", "--json", "--skip-git-repo-check", "--sandbox"]
    assert "-c" in codex_cmd and "model_reasoning_effort=medium" in codex_cmd
    assert "--output-schema" in codex_cmd
    assert "-i" in codex_cmd and "/tmp/page-001.png" in codex_cmd


def test_oral_exam_core_bar_frontier_and_non_repeating_retakes(tmp_path: Path):
    info = seed_demo_vault(tmp_path)
    app = create_app(tmp_path)
    client = TestClient(app)

    # Set routing to demo explicitly for deterministic test
    client.put(
        "/api/settings",
        json={
            "routing": {
                "extraction_planning": {"provider": "demo", "model": "scholia-demo-v1", "effort": "high"},
                "socratic_dialogue": {"provider": "demo", "model": "scholia-demo-v1", "effort": "low"},
                "oral_exam_grading": {"provider": "demo", "model": "scholia-demo-v1", "effort": "high"},
                "note_enrichment": {"provider": "demo", "model": "scholia-demo-v1", "effort": "medium"},
            }
        },
    )

    ch_id = info["dp_chapter_id"]
    # Start fresh exam session via Test Out
    res = client.post(f"/api/chapters/{ch_id}/sessions", json={"stage": "plan", "force_new": True})
    assert res.status_code == 200
    sess_id = res.json()["id"]

    r_testout = client.post(f"/api/sessions/{sess_id}/turn", json={"action": "test_out", "message": ""})
    assert r_testout.status_code == 200
    assert "Oral examination initiated" in r_testout.text

    # Answer Q1 strongly -> clears Core Bar and enters Frontier Probe #1
    strong_ans = (
        "Because optimal substructure depends on subproblem independence, a cut-and-paste contradiction shows "
        "that substituting any better subproblem solution strictly improves the global recurrence invariant without breaking boundary feasibility."
    )
    r_q1 = client.post(f"/api/sessions/{sess_id}/turn", json={"action": "reply", "message": strong_ans})
    assert "Core Bar Cleared" in r_q1.text
    assert "Frontier Probe #1" in r_q1.text

    # Hit limit on Frontier Probe #1 -> no penalty, advances to Q2
    r_lim = client.post(f"/api/sessions/{sess_id}/turn", json={"action": "hit_limit_next_question", "message": "I do not know"})
    assert "without penalty" in r_lim.text
    assert "Question 2/5" in r_lim.text

    # Fail Q2 by hitting limit before clearing Core Bar
    r_fail = client.post(f"/api/sessions/{sess_id}/turn", json={"action": "hit_limit_next_question", "message": "pass"})
    assert "Core Bar not cleared" in r_fail.text

    # Finish Q3, Q4, Q5 via hit_limit so we can test non-repeating retake generation
    for _ in range(3):
        client.post(f"/api/sessions/{sess_id}/turn", json={"action": "hit_limit_next_question", "message": "pass"})

    sess_after = client.get(f"/api/sessions/{sess_id}").json()
    first_stems = {q["prompt"] for q in sess_after["exam_state"]["questions"]}
    assert sess_after["exam_state"]["passed"] is False
    assert len(sess_after["exam_state"]["failed_concept_ids"]) >= 1

    # Start non-repeating retake -> question stems must not repeat!
    client.post(f"/api/sessions/{sess_id}/turn", json={"action": "start_retake", "message": ""})
    retake_sess = client.get(f"/api/sessions/{sess_id}").json()
    retake_stems = {q["prompt"] for q in retake_sess["exam_state"]["questions"]}
    assert retake_sess["exam_state"]["exam_type"] == "retake"
    assert first_stems.isdisjoint(retake_stems)

    # Test Stage 4 enrichment appends to notes.md
    client.post(f"/api/sessions/{sess_id}/turn", json={"action": "complete_enrichment", "message": ""})
    ch_detail = client.get(f"/api/chapters/{ch_id}").json()
    assert "Session Appendix: Confusions, Breakthroughs, and Knowledge Frontiers" in ch_detail["notes_markdown"]


def test_fastmcp_toolkit_and_review_endpoints(tmp_path: Path):
    info = seed_demo_vault(tmp_path)
    tk = ScholiaMCPToolkit(tmp_path)

    books = tk.list_books()
    assert len(books) == 2

    notes = tk.get_chapter_notes(info["dp_chapter_id"])
    assert "Dynamic Programming" in notes["notes_markdown"]

    plan = tk.get_lesson_plan(info["dp_chapter_id"])
    assert len(plan["lesson_plan"]["concepts"]) >= 3

    memory = tk.get_learner_memory(chapter_id=info["dp_chapter_id"])
    assert len(memory["mastered_concepts"]) >= 3

    logged = tk.log_confusion_or_frontier("frontier", "Testing custom MCP frontier log.", chapter_id=info["dp_chapter_id"])
    assert logged["kind"] == "frontier"

    graph = tk.query_topic_graph(topic="Algorithms")
    assert graph["node_count"] >= 5
    dp_node = next(n for n in graph["nodes"] if n["name"] == "Dynamic Programming")
    assert len(dp_node["parent_ids"]) >= 2

    reviews = tk.get_due_reviews(topic="Algorithms")
    assert len(reviews["due_cards"]) >= 1
    first_cid = reviews["due_cards"][0]["concept"]["id"]

    updated = tk.record_concept_mastery(first_cid, mastery_state="mastered", core_passed=True, rating=4)
    assert updated["fsrs_reps"] >= 1

    # Also check REST review answer endpoint
    app = create_app(tmp_path)
    client = TestClient(app)
    due_resp = client.get("/api/review/due?topic=Distributed+Systems").json()
    assert len(due_resp["cards"]) >= 1
    card_cid = due_resp["cards"][0]["concept"]["id"]
    ans_resp = client.post(
        f"/api/review/{card_cid}/answer",
        json={"answer": "Linearizability guarantees real-time recency across reads after a write completes, requiring quorum intersection or leader leases rather than stale async followers."},
    )
    assert ans_resp.status_code == 200
    assert ans_resp.json()["passed"] is True


# ---------- v2 Test Suite ----------

def test_v2_workspaces_isolation_and_fastmcp_filtering(tmp_path: Path):
    app = create_app(tmp_path)
    client = TestClient(app)

    ws_career = client.post("/api/workspaces", json={"name": "Career", "description": "ML Perf"}).json()
    ws_found = client.post("/api/workspaces", json={"name": "Foundations", "description": "Math"}).json()

    # Upload one markdown book into each workspace
    r1 = client.post(
        "/api/books/upload",
        data={"title": "Scaling Book", "workspace_id": ws_career["id"], "topic_areas": "ML Systems"},
        files={"file": ("scaling.md", b"# Rooflines\n\nArithmetic intensity.", "text/markdown")},
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/api/books/upload",
        data={"title": "Linear Algebra", "workspace_id": ws_found["id"], "topic_areas": "Math"},
        files={"file": ("linalg.md", b"# Eigenvalues\n\nSpectral theorem.", "text/markdown")},
    )
    assert r2.status_code == 200

    career_books = client.get("/api/books?workspace=career").json()["books"]
    found_books = client.get("/api/books?workspace=foundations").json()["books"]
    assert [b["title"] for b in career_books] == ["Scaling Book"]
    assert [b["title"] for b in found_books] == ["Linear Algebra"]

    # FastMCP workspace isolation
    tk = ScholiaMCPToolkit(tmp_path)
    wss = tk.list_workspaces()
    assert any(w["slug"] == "career" for w in wss)
    assert len(tk.list_books(workspace="career")) == 1
    assert tk.list_books(workspace="foundations")[0]["title"] == "Linear Algebra"

    # Concept DAG isolation by workspace
    db = app.state.container.db
    db.upsert_concept("Rooflines", workspace_id=ws_career["id"], topic_areas=["ML Systems"])
    db.upsert_concept("Eigenvalues", workspace_id=ws_found["id"], topic_areas=["Math"])
    g_career = tk.query_topic_graph(workspace="career")
    g_found = tk.query_topic_graph(workspace="foundations")
    assert [n["name"] for n in g_career["nodes"]] == ["Rooflines"]
    assert [n["name"] for n in g_found["nodes"]] == ["Eigenvalues"]


def test_v2_markdown_zip_bundle_ingestion_and_asset_serving(tmp_path: Path):
    import io
    import zipfile

    # Tiny valid 1x1 PNG
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "scaling-book/roofline.md",
            '---\ntitle: "All About Rooflines"\nsection_number: 1\n---\n\n'
            'Arithmetic intensity is $$I = \\frac{\\text{FLOPs}}{\\text{Bytes}}$$.<d-footnote>HBM bytes moved.</d-footnote>\n\n'
            '{% include figure.liquid path="assets/img/roofline.png" caption="<b>Figure:</b> Roofline plot." %}\n\n'
            '```python\ndef ai(flops, bytes_moved):\n    return flops / bytes_moved\n```\n',
        )
        zf.writestr(
            "scaling-book/index.md",
            '---\ntitle: "How to Scale Your Model"\nsection_number: 0\nauthors:\n  - name: DeepMind Team\n---\n\nIntro prose.\n',
        )
        zf.writestr("scaling-book/README.md", "# Repo README\n")
        zf.writestr("scaling-book/assets/img/roofline.png", tiny_png)

    app = create_app(tmp_path)
    client = TestClient(app)
    res = client.post(
        "/api/books/upload",
        data={"topic_areas": "ML Systems"},
        files={"file": ("scaling-book.zip", buf.getvalue(), "application/zip")},
    )
    assert res.status_code == 200
    book = res.json()
    assert book["source_format"] == "zip"
    assert book["title"] == "How to Scale Your Model"
    # Ordered by section_number: Part 0, Part 1, then README (skipped)
    assert book["chapters"][0]["title"].startswith("Part 0:")
    assert book["chapters"][1]["title"].startswith("Part 1:")
    assert book["chapters"][2]["scope"] == "skipped"

    # Inspect cleaned source-markdown & asset serving
    ch1_id = book["chapters"][1]["id"]
    src_resp = client.get(f"/api/chapters/{ch1_id}/source-markdown")
    assert src_resp.status_code == 200
    md = src_resp.json()["source_markdown"]
    assert "$$I = \\frac{\\text{FLOPs}}{\\text{Bytes}}$$" in md
    assert "{% include" not in md
    assert "## Footnotes" in md and "HBM bytes moved." in md
    assert f"/api/books/{book['id']}/assets/img/roofline.png" in md

    asset_resp = client.get(f"/api/books/{book['id']}/assets/img/roofline.png")
    assert asset_resp.status_code == 200
    assert asset_resp.content == tiny_png


def test_v2_multilevel_pdf_toc_and_printed_toc_detection(tmp_path: Path):
    app = create_app(tmp_path)
    client = TestClient(app)

    # 1. PDF with L1 Part containers wrapping L2 numbered chapters (PMPP-style)
    doc = fitz.open()
    for i in range(12):
        p = doc.new_page()
        p.insert_text((72, 72), f"Textbook Page {i + 1}")
    doc.set_toc([
        [1, "1 Introduction", 1],
        [2, "1.1 Overview", 1],
        [1, "1 Fundamental concepts", 3],
        [2, "2 Heterogeneous computing", 3],
        [2, "3 Multidimensional grids", 5],
        [2, "4 Compute architecture", 7],
        [2, "5 Memory hierarchy", 9],
        [2, "6 Performance considerations", 11],
    ])
    pmpp_bytes = doc.tobytes()
    doc.close()

    r_pmpp = client.post(
        "/api/books/upload",
        data={"title": "PMPP Synthetic"},
        files={"file": ("pmpp.pdf", pmpp_bytes, "application/pdf")},
    )
    assert r_pmpp.status_code == 200
    b_pmpp = r_pmpp.json()
    titles = [c["title"] for c in b_pmpp["chapters"]]
    assert "1 Introduction" in titles
    assert "5 Memory hierarchy" in titles
    assert len(titles) == 6

    tree = client.get(f"/api/books/{b_pmpp['id']}/toc-tree").json()
    assert tree["levels"] == [1, 2]
    assert len(tree["entries"]) == 8

    # 2. Bookmarkless PDF with Printed TOC + page offset (+2)
    pdoc = fitz.open()
    pdoc.new_page().insert_text((72, 72), "Cover Page")
    pdoc.new_page().insert_text((72, 72), "Table of Content\n1\nOverview\n2\n2\nData Parallelism\n5\n3\nTensor Parallelism\n8\n")
    for body_p in range(1, 11):
        pg = pdoc.new_page()
        header = ""
        if body_p == 2:
            header = "1 Overview\n"
        elif body_p == 5:
            header = "2 Data Parallelism\n"
        elif body_p == 8:
            header = "3 Tensor Parallelism\n"
        pg.insert_text((72, 72), f"{header}Printed page {body_p}")
    usp_bytes = pdoc.tobytes()
    pdoc.close()

    r_usp = client.post(
        "/api/books/upload",
        data={"title": "Playbook Synthetic"},
        files={"file": ("playbook.pdf", usp_bytes, "application/pdf")},
    )
    assert r_usp.status_code == 200
    b_usp = r_usp.json()
    det = client.post(f"/api/books/{b_usp['id']}/detect-printed-toc?apply=true").json()
    assert det["offset"] == 2
    assert det["applied"] is True
    ch_map = {c["title"]: (c["start_page"], c["end_page"], c["scope"]) for c in det["book"]["chapters"]}
    assert ch_map["Front Matter"] == (1, 3, "skipped")
    assert ch_map["1. Overview"] == (4, 6, "assigned")
    assert ch_map["2. Data Parallelism"] == (7, 9, "assigned")
    assert ch_map["3. Tensor Parallelism"] == (10, 12, "assigned")


def test_v2_fidelity_epub_images_tables_code_and_frontmatter(tmp_path: Path):
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    eb = epub.EpubBook()
    eb.set_identifier("fidelity-epub-test")
    eb.set_title("Systems Performance Test")
    eb.set_language("en")
    eb.add_author("Brendan Gregg")

    img = epub.EpubImage()
    img.file_name = "Images/use_method.png"
    img.media_type = "image/png"
    img.content = tiny_png
    eb.add_item(img)

    cov = epub.EpubHtml(title="Cover", file_name="cover.xhtml", lang="en")
    cov.content = "<html><body><h1>Cover</h1><p>Publisher front cover placeholder text for book.</p></body></html>"

    ch2 = epub.EpubHtml(title="Chapter 2. Methodologies", file_name="ch02.xhtml", lang="en")
    ch2.content = (
        "<html><body><h1>Chapter 2. Methodologies</h1>"
        "<p>The USE method checks utilization, saturation, and errors.</p>"
        "<img src='Images/use_method.png' alt='USE Diagram'/>"
        "<table><tr><th>Resource</th><th>Metric</th></tr><tr><td>CPU</td><td>Run queue</td></tr></table>"
        "<pre><code class='language-bash'>mpstat -P ALL 1\n  vmstat 1</code></pre>"
        "</body></html>"
    )
    eb.add_item(cov)
    eb.add_item(ch2)
    eb.toc = (cov, ch2)
    eb.add_item(epub.EpubNcx())
    eb.add_item(epub.EpubNav())
    eb.spine = ["nav", cov, ch2]

    out = tmp_path / "sysperf.epub"
    epub.write_epub(str(out), eb)

    app = create_app(tmp_path)
    client = TestClient(app)
    res = client.post(
        "/api/books/upload",
        data={"topic_areas": "Performance Engineering"},
        files={"file": ("sysperf.epub", out.read_bytes(), "application/epub+zip")},
    )
    assert res.status_code == 200
    book = res.json()
    cov_ch = next(c for c in book["chapters"] if "cover" in c["title"].lower())
    meth_ch = next(c for c in book["chapters"] if "methodologies" in c["title"].lower())
    assert cov_ch["scope"] == "skipped"
    assert meth_ch["scope"] == "assigned"

    md = client.get(f"/api/chapters/{meth_ch['id']}/source-markdown").json()["source_markdown"]
    assert f"![USE Diagram](/api/books/{book['id']}/assets/Images/use_method.png)" in md
    assert "| Resource | Metric |" in md
    assert "```bash\nmpstat -P ALL 1\n  vmstat 1\n```" in md

    img_resp = client.get(f"/api/books/{book['id']}/assets/Images/use_method.png")
    assert img_resp.status_code == 200
    assert img_resp.content == tiny_png


def test_v2_curriculum_chapter_scoping_phase_exit_exam_and_logs(tmp_path: Path):
    app = create_app(tmp_path)
    client = TestClient(app)

    ws = client.post("/api/workspaces", json={"name": "Career", "slug": "career"}).json()
    book = client.post(
        "/api/books/upload",
        data={"title": "Perf Guide", "workspace_id": ws["id"]},
        files={"file": ("perf.md", b"# Ch1 Rooflines\n\nIntensity.\n\n# Ch2 Skipped Appendix\n\nExtra.\n", "text/markdown")},
    ).json()
    ch1_id, ch2_id = book["chapters"][0]["id"], book["chapters"][1]["id"]

    # Scope ch2 as skipped -> extract-all?assigned_only=true queues only ch1
    sc_res = client.put(f"/api/chapters/{ch2_id}/scope", json={"scope": "skipped"})
    assert sc_res.status_code == 200 and sc_res.json()["scope"] == "skipped"
    q_res = client.post(f"/api/books/{book['id']}/extract-all?assigned_only=true").json()
    assert q_res["queued_chapter_ids"] == [ch1_id]

    # Create curriculum + phase + item + running log
    db = app.state.container.db
    cur = db.create_curriculum(workspace_id=ws["id"], title="ML Perf Plan")
    ph = db.create_curriculum_phase(
        curriculum_id=cur["id"],
        track="core",
        phase_number=1,
        title="Scaling Fundamentals",
        exit_criterion="Estimate FLOPs, memory, and comms for a training step on paper.",
    )
    item = db.create_curriculum_item(
        phase_id=ph["id"],
        week_label="W1",
        kind="reading",
        title="Read Rooflines",
        linked_book_id=book["id"],
        linked_chapter_ids=[ch1_id],
    )

    # Toggle item status via API
    upd_item = client.put(f"/api/curriculum-items/{item['id']}", json={"status": "done"}).json()
    assert upd_item["status"] == "done"

    # Launch Phase Exit Oral Exam
    exit_sess = client.post(f"/api/curriculum-phases/{ph['id']}/exit-exam").json()
    assert exit_sess["stage"] == "exam"
    assert exit_sess["exam_state"]["exam_type"] == "phase_exit"
    assert "Estimate FLOPs" in exit_sess["exam_state"]["exit_criterion"]

    # Running logs CRUD & MCP append
    lg = client.post(
        "/api/logs",
        json={"workspace_id": ws["id"], "title": "Goodput Lost Log", "curriculum_id": cur["id"]},
    ).json()
    save_res = client.put(f"/api/logs/{lg['id']}", json={"content": "# Goodput Lost Log\n\n- Incident 1: 42 min lost.\n"})
    assert save_res.status_code == 200
    assert "Incident 1" in client.get(f"/api/logs/{lg['id']}").json()["content"]

    tk = ScholiaMCPToolkit(tmp_path)
    tk.append_running_log(lg["slug"], "- Incident 2: 18 min lost.")
    assert "Incident 2" in tk.get_running_log(lg["slug"])["content"]
    assert len(tk.get_curriculum(workspace="career")["curricula"]) == 1

