#!/usr/bin/env python3
"""FB4/FB1/FB3: actual installed/linked UI, paired ports, drafts, translations and layout."""
import importlib
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from playwright.sync_api import sync_playwright, expect
from block_test_artifacts import artifact_path
from block_test_packages import install_test_package, surface_payload
from ui_smoke_common import (isolated_server, graph_payload, create_project_api, project_editor_url,
    attach_console_guards, assert_no_blocking_console_errors)

KIND = "audio_mixer"
Block = getattr(importlib.import_module("blocs." + KIND + ".block"), "AudioMixerBlock" if KIND == "audio_mixer" else "AudioMergeStreamBlock")


def main():
    """Use real framework CSS/module mounting, never a standalone mock modal."""
    for origin in ("managed", "linked"):
        with isolated_server() as server, sync_playwright() as playwright:
            model = install_test_package(server, KIND, origin=origin)
            candidate = Block().build_node_payload(node_id="audio", position={"x": 340, "y": 180})
            candidate["block_version"] = model["version"]
            for surface in ("modal", "inspector_panel"):
                surface_payload(server, model, candidate, surface=surface)
            project = create_project_api(server, document=graph_payload("Audio UI", [candidate], []))["project"]
            url = project_editor_url(server.base_url, project["project_id"], workspace_project_id=project["workspace_project_id"])
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 960})
                page.add_init_script("window.localStorage.setItem('bloxsmith.inspectorPinned','true')")
                errors = attach_console_guards(page)
                page.goto(url)
                card = page.locator('.canvas-node[data-node-id="audio"]')
                expect(card.locator('.am-node-card')).to_be_visible()
                page.screenshot(path=artifact_path(KIND + "-" + origin + "-card.png"))
                card.locator('h3').dblclick()
                modal = page.locator('.am-modal')
                expect(modal).to_be_visible()
                expect(modal.locator('.am-source')).to_have_count(2)
                expect(modal.locator('[data-save-sources]')).to_be_disabled()
                modal.locator('[data-add-source]').click()
                expect(modal.locator('.am-source')).to_have_count(3)
                modal.locator('[data-source-id="3"] [data-source-field="label"]').fill("Phone")
                if KIND == "audio_mixer":
                    modal.locator('[data-source-id="3"] [data-source-field="gain_db"]').fill("-9")
                    modal.locator('[data-source-id="2"] [data-source-field="muted"]').check()
                expect(modal.locator('[data-save-sources]')).to_be_enabled()
                for width, height, name in ((1440, 960, "desktop"), (768, 720, "tablet"), (390, 740, "mobile"), (320, 568, "small")):
                    page.set_viewport_size({"width": width, "height": height})
                    page.wait_for_timeout(180)
                    bounds = modal.evaluate("""panel => {
                      const box=panel.getBoundingClientRect(), save=panel.querySelector('[data-save-sources]').getBoundingClientRect();
                      return {inside:box.left>=-1&&box.top>=-1&&box.right<=innerWidth+1&&box.bottom<=innerHeight+1,
                        save:save.top>=0&&save.bottom<=innerHeight, overflow:panel.scrollWidth>panel.clientWidth+1,
                        background:getComputedStyle(panel).backgroundColor};
                    }""")
                    page.screenshot(path=artifact_path(KIND + "-" + origin + "-" + name + ".png"))
                    assert bounds["inside"] and bounds["save"] and not bounds["overflow"], bounds
                    assert bounds["background"] not in {"transparent", "rgba(0, 0, 0, 0)"}
                page.set_viewport_size({"width": 1440, "height": 960})
                with page.expect_response(lambda r: r.url.endswith('/ui-action') and r.request.method == 'POST') as applied:
                    modal.locator('[data-save-sources]').click()
                assert not applied.value.json().get("error"), applied.value.json()
                modal.locator('[data-close-block-modal]').click()
                page.reload()
                card.locator('h3').dblclick()
                expect(modal.locator('.am-source')).to_have_count(3)
                expect(modal.locator('[data-source-id="3"] [data-source-field="label"]')).to_have_value("Phone")
                if KIND == "audio_mixer":
                    expect(modal.locator('[data-source-id="3"] [data-source-field="gain_db"]')).to_have_value("-9")
                    expect(modal.locator('[data-source-id="2"] [data-source-field="muted"]')).to_be_checked()
                # Cancel closes only the local draft, including source count and gain.
                modal.locator('[data-add-source]').click()
                modal.locator('[data-close-block-modal]').click()
                card.locator('h3').dblclick()
                expect(modal.locator('.am-source')).to_have_count(3)
                modal.locator('[data-editor-title]').fill("")
                modal.locator('[data-save-sources]').click()
                expect(modal.locator('[data-editor-title]')).to_be_focused()
                modal.locator('[data-reset-sources]').click()
                expect(modal.locator('[data-save-sources]')).to_be_disabled()
                modal.locator('[data-remove-source="3"]').click()
                with page.expect_response(lambda r: r.url.endswith('/ui-action') and r.request.method == 'POST') as removed:
                    modal.locator('[data-save-sources]').click()
                assert not removed.value.json().get("error"), removed.value.json()
                modal.locator('[data-close-block-modal]').click()
                card.click(position={"x": 25, "y": 20})
                inspector = page.locator('.am-inspector:visible')
                expect(inspector).to_be_visible()
                expect(inspector.locator('.am-source')).to_have_count(2)
                inspector.locator('[data-source-id="1"] [data-source-field="label"]').fill("Microphone")
                with page.expect_response(lambda r: r.url.endswith('/ui-action') and r.request.method == 'POST') as renamed:
                    inspector.locator('[data-save-sources]').click()
                assert not renamed.value.json().get("error"), renamed.value.json()
                page.screenshot(path=artifact_path(KIND + "-" + origin + "-inspector.png"))
                # Language change uses this package's catalogs, not legacy globals.
                page.goto(server.base_url + "/")
                page.locator("#homeApplicationSettingsButton").click()
                page.locator("#applicationLanguageSelect").select_option("fr")
                page.wait_for_function("window.CWMessages.getLanguage() === 'fr'")
                page.goto(url)
                card.locator('h3').dblclick()
                expect(modal.locator('[data-add-source]')).to_have_text("Ajouter une source")
                expect(modal.locator('[data-source-id="1"] .am-field > span').first).to_have_text("Nom de la source")
                expect(modal.locator('[data-source-id="1"] .am-command-port > span')).to_have_text("Commandes")
                if KIND == "audio_mixer":
                    expect(modal.locator('[data-source-id="1"] .am-check > span')).to_have_text("Rendre cette source muette")
                expect(modal.locator('[data-source-id="1"] [data-source-field="label"]')).to_have_value("Microphone")
                modal.locator('summary').click()
                page.screenshot(path=artifact_path(KIND + "-" + origin + "-french.png"))
                assert page.evaluate("!window.CWBlockUiBlocks?." + KIND)
                assert_no_blocking_console_errors(errors)
            finally:
                browser.close()
        print("[ok] " + KIND + " " + origin + " UI", flush=True)


if __name__ == "__main__":
    main()
