"""Release-owned source editor: explicit Apply, stable ports, no framework mutation."""
from html import escape
import json
from bloxsmith_app.block_api import render_node_card_template
from .config import normalize, source_ports


class AudioUI:
    """Keep modal, inspector and source pair editing consistent and self-contained."""

    def text(self, key, fallback):
        """Render a catalog-owned text marker, never user-authored content."""
        name = f"block.{self.kind}.{key}"
        return f'<span data-i18n="{name}">{escape(self.translate(name, fallback=fallback))}</span>'

    def render_editor(self, node, *, modal):
        """Render an opaque panel, bounded scroll body and reachable draft actions."""
        config = normalize(node.get("config"), mixer=self.mixer)
        replacements = {
            "node_id": escape(str(node.get("id", "")), quote=True),
            "node_title": escape(str(node.get("title") or self.default_title())),
            "title_value": escape(str(node.get("title") or self.default_title()), quote=True),
            "editor_config": escape(json.dumps(config), quote=True),
            "mixer": "true" if self.mixer else "false",
        }
        html = (self.directory / ("block_modal.html" if modal else "inspector_panel.html")).read_text(encoding="utf-8")
        for key, value in replacements.items():
            html = html.replace("{{ " + key + " }}", value)
        return {"html": html, "context": {"node_id": node.get("id"), "node_kind": self.kind, "full_panel": not modal}}

    def render_modal(self, *, node, payload=None):
        """A real dialog with internal scrolling; closing never persists a draft."""
        return self.render_editor(node, modal=True)

    def render_inspector_panel(self, *, node, payload=None):
        """The same source editor fits the narrow inspector; paired ports are block-owned."""
        return self.render_editor(node, modal=False)

    def render_node_card(self, *, node, payload=None):
        """Show the role, source count and a compact audio format hint."""
        config = normalize(node.get("config"), mixer=self.mixer)
        names = " · ".join(row["label"] for row in config["sources"])
        return render_node_card_template(block=self, node=node, node_classes=[self.kind.replace("_", "-") + "-node"],
            replacements={"title": node.get("title") or self.default_title(), "sources": names,
                          "count": str(len(config["sources"])), "role": "MIX" if self.mixer else "MERGE"})

    def handle_ui_action(self, *, node, action, values, payload=None):
        """Save pairs atomically via public operations; never delete connected links."""
        if action != "save_sources":
            return super().handle_ui_action(node=node, action=action, values=values, payload=payload)
        try:
            config = normalize(values.get("config"), mixer=self.mixer)
            title = str(values.get("title", "")).strip()
            if not title or len(title) > 120:
                raise ValueError("Block name must contain 1–120 characters.")
            before = normalize(node.get("config"), mixer=self.mixer)
            existing = {p["id"]: p for p in node.get("inputs", [])}
            expected_before = {p["id"] for row in before["sources"] for p in source_ports(row)}
            if set(existing) != expected_before:
                raise ValueError("Source pairs were edited outside this form; restore them before applying.")
            desired = {p["id"]: p for row in config["sources"] for p in source_ports(row)}
            operations = []
            for port_id in existing.keys() - desired.keys():
                operations.append({"op": "delete_port", "node_id": node["id"], "direction": "input",
                                   "port_id": port_id, "cascade": False})
            for port_id, port in desired.items():
                if port_id not in existing:
                    operations.append({"op": "create_port", "node_id": node["id"], "direction": "input",
                                       "port_id": port_id, **port})
                elif port["title"] != existing[port_id].get("title"):
                    operations.append({"op": "update_port", "node_id": node["id"], "direction": "input",
                                       "port_id": port_id, "title": port["title"]})
            return {"node_patch": {"title": title, "config": {**(node.get("config") or {}), **config}},
                    "graph_operations": operations, "rerender_inspector": True, "close_modal": False}
        except (ValueError, TypeError) as error:
            return {"error": self.translate(f"block.{self.kind}.invalid",
                params={"detail": str(error)}, fallback="Invalid settings: {detail}")}
