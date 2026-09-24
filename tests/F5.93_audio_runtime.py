#!/usr/bin/env python3
"""FB1/FB2/FB3: managed/linked Run listeners, HTTP commands, real audio WebSockets and Save Audio."""
import base64
import importlib
from pathlib import Path
import runpy
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from playwright.sync_api import sync_playwright
from block_test_packages import install_test_package, prepare_release_run
from blocs.microphone_stream.block import MicrophoneStreamBlock
from blocs.save_audio.block import SaveAudioBlock
from ui_smoke_common import (isolated_server, graph_payload, data_edge, create_project_api, project_editor_url,
    create_run_api, wait_for_run_terminal, wait_for_run_predicate, stop_run_api, http_json)

KIND = "audio_mixer"
MIXER = KIND == "audio_mixer"
Block = getattr(importlib.import_module("blocs." + KIND + ".block"), "AudioMixerBlock" if MIXER else "AudioMergeStreamBlock")
FIXTURE = runpy.run_path(str(Path(__file__).with_name("F5.92_audio_engine.py")))


def main():
    """No provider, device or live instance: all traffic belongs to a disposable server."""
    a = FIXTURE["encoded"](440, .5)
    b = FIXTURE["encoded"](880, .9, "webm", 2)
    for origin in ("managed", "linked"):
        with isolated_server() as server, sync_playwright() as playwright:
            model = install_test_package(server, KIND, origin=origin)
            directory = server.root_dir / "recordings"
            sources = [MicrophoneStreamBlock().build_node_payload(node_id="source" + str(index)) for index in (1, 2)]
            target = Block().build_node_payload(node_id="target")
            target["block_version"] = model["version"]
            target["inputs"].reverse()
            sink = SaveAudioBlock().build_node_payload(node_id="save", config_overrides={"output_dir": str(directory)})
            links = [data_edge("a1", "source1", 1, "target", 1), data_edge("c1", "source1", 2, "target", 2),
                     data_edge("a2", "source2", 1, "target", 3), data_edge("c2", "source2", 2, "target", 4),
                     data_edge("mixed", "target", 1, "save", 1), data_edge("lifecycle", "target", 2, "save", 2)]
            document = graph_payload("Audio source integration", [*sources, target, sink], links)
            simulation = create_run_api(server, document, runtime_mode="centralized")
            completed = wait_for_run_terminal(server, simulation["run_id"], timeout_sec=20)
            assert completed["status"] == "success", completed.get("logs")
            assert not list(directory.glob("*"))
            assert not completed.get("output_values", {}).get("target:2")
            project = create_project_api(server, document=document)["project"]
            prepared = prepare_release_run(server, project["project_id"], document)
            run_id = prepared["run_id"]
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(project_editor_url(server.base_url, project["project_id"], workspace_project_id=project["workspace_project_id"]))
                page.wait_for_function("typeof window.CWBlockUi?.createRuntimeAudioStreamsApi === 'function'")
                scope = {"available": True, "workspaceProjectId": project["workspace_project_id"],
                         "graphId": project["project_id"], "instanceId": "1", "runId": run_id}
                descriptors = page.evaluate("""async ({scope,sources}) => {
                  window.testPublishers = await Promise.all(sources.map((node,index) => {
                    const api=window.CWBlockUi.createRuntimeAudioStreamsApi({
                      actions:{getRuntimeAudioStreamContext:()=>({...scope,nodeId:node.id})}},()=>node);
                    return api.openOutput({outputPort:"audio_out",codec:"opus",sampleRateHz:48000,channels:index+1});
                  }));
                  return testPublishers.map(p=>p.descriptor);
                }""", {"scope": scope, "sources": sources})
                def publish(index, command):
                    """Use the application's public data-plane control, not private queues."""
                    response = http_json(server.base_url, f"/api/runs/{run_id}/active/control", method="POST",
                        payload={"action": "publish_output", "node_id": "source" + str(index + 1),
                                 "port_id": 2, "port_name": "command_out", "value": __import__("json").dumps(command),
                                 "content_type": "application/json"})
                    assert not response.get("error"), response
                for index, item in enumerate(descriptors):
                    publish(index, {"action": "start", "stream_id": item["stream_id"]})
                counts = page.evaluate("""({recordings}) => {
                  return recordings.map((recording,index) => {
                    const bytes=Uint8Array.from(atob(recording),c=>c.charCodeAt(0));
                    let count=0;
                    for(let offset=0;offset<bytes.length;offset+=997) {
                      if(!testPublishers[index].sendFrame(bytes.slice(offset,offset+997))) throw Error("Fixture queue saturated");
                      count++;
                    }
                    testPublishers[index].close();
                    return count;
                  });
                }""", {"recordings": [base64.b64encode(a).decode(), base64.b64encode(b).decode()]})
                for index, data in enumerate((a, b)):
                    publish(index, {"action": "stop", "stream_id": descriptors[index]["stream_id"],
                                    "frame_count": counts[index], "byte_count": len(data), "aborted": False})
                expected = 1 if MIXER else 2
                run = wait_for_run_predicate(server, run_id,
                    lambda state: len(state.get("results", {}).get("save", {}).get("save_audio", {}).get("saved_files", [])) == expected
                    or any(state.get("node_statuses", {}).get(node) == "failed" for node in ("target", "save")),
                    "Stream output did not reach Save Audio", timeout_sec=25)
                assert run.get("node_statuses", {}).get("target") != "failed", run.get("logs")
                assert run.get("node_statuses", {}).get("save") != "failed", run.get("logs")
                files = list(directory.glob("*.ogg")) + list(directory.glob("*.webm"))
                assert len(files) == expected, run.get("logs")
                if MIXER:
                    samples = FIXTURE["decoded"](files[0].read_bytes())
                    assert FIXTURE["level"](samples, 440) > .025
                    assert FIXTURE["level"](samples, 880) > .025
                    assert .88 <= len(samples) / 48000 < 1.5
                else:
                    assert sorted(path.read_bytes() for path in files) == sorted((a, b))
                assert not list(directory.glob(".*.part"))
                assert not any("saturat" in line.lower() for line in run.get("logs", [])), run.get("logs")
            finally:
                browser.close()
                stopped = stop_run_api(server, run_id)
                assert "shutdown_timeout" not in str(stopped)
        print("[ok] " + KIND + " " + origin + " simulation + Active Run → Save Audio", flush=True)


if __name__ == "__main__":
    main()
