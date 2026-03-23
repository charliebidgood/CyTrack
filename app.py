import base64
import csv
import os
import threading
import uuid
from datetime import datetime
import dash
from dash import dcc, html, Input, Output, State, callback, no_update, ALL, ctx
import plotly.graph_objects as go
import storage
import analysis

seg_jobs = {}  # job_id -> {status, progress, total, message}


def run_seg_folder(job_id, input_dir, output_dir, method):
    """Background thread: segment every image in input_dir and write results.csv."""
    exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
    try:
        images = sorted(
            f for f in os.listdir(input_dir)
            if os.path.splitext(f.lower())[1] in exts
        )
    except Exception as exc:
        seg_jobs[job_id].update(status="error", message=f"Cannot read directory: {exc}")
        return

    if not images:
        seg_jobs[job_id].update(status="error", message="No image files found in that directory.")
        return

    os.makedirs(output_dir, exist_ok=True)
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    total = len(images)
    seg_jobs[job_id].update(total=total, status="running")

    results = []
    for i, fname in enumerate(images):
        img_path = os.path.join(input_dir, fname)
        seg_jobs[job_id]["message"] = f"Processing {i + 1}/{total}: {fname}"
        try:
            r = analysis.analyse_image(img_path, images_dir, method=method)
            results.append({"img_name": fname, "method": r["method"],
                            "confluency": round(r["confluency"], 2)})
        except Exception as exc:
            results.append({"img_name": fname, "method": method, "confluency": "error"})
        seg_jobs[job_id]["progress"] = i + 1

    csv_path = os.path.join(output_dir, "results.csv")
    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["img_name", "method", "confluency"])
        writer.writeheader()
        writer.writerows(results)

    seg_jobs[job_id].update(
        status="done",
        message=f"Done — {total} image(s) processed. results.csv saved to output folder.",
    )

VERSION = "1.1"

# App setup
app = dash.Dash(__name__, suppress_callback_exceptions=True)
app.title = f"CyTrack v{VERSION}"
server = app.server

# Serve images from cultures/ folder
from flask import send_from_directory

@server.route("/cultures/<path:filepath>")
def serve_culture_file(filepath):
    return send_from_directory(storage.CULTURES_DIR, filepath)



# Colour helpers
def confluency_class(val):
    if val < 30:
        return "conf-low"
    if val < 50:
        return "conf-mid"
    if val < 80:
        return "conf-high"
    return "conf-over"


def format_date(iso_str):
    """Parse ISO date and return a readable, cross-platform string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        day = str(dt.day)
        month = dt.strftime("%b")
        year = dt.strftime("%Y")
        return f"{day} {month} {year}"
    except Exception:
        return iso_str


# Layout
def make_layout():
    return html.Div(id="app-container", children=[
        # --- Stores ---
        dcc.Store(id="current-view", data="dashboard"),   # dashboard | culture
        dcc.Store(id="selected-culture", data=None),
        dcc.Store(id="refresh-trigger", data=0),
        dcc.Store(id="overlay-data", data=None),
        dcc.Store(id="editing-entry", data=None),  # entry id being edited
        dcc.Store(id="seg-folder-job-id", data=None),
        dcc.Interval(id="seg-folder-poll", interval=500, n_intervals=0, disabled=True),

        # --- Sidebar ---
        html.Div(id="sidebar", children=[
            html.Div(f"CyTrack v{VERSION}", id="sidebar-brand"),
            html.Div(id="sidebar-nav", children=[
                html.Button("Dashboard", id="nav-dashboard", className="sidebar-nav-btn active", n_clicks=0),
            ]),
            html.Div(id="sidebar-cultures"),
            html.Button("+ New Culture", id="sidebar-add-btn", n_clicks=0),
            html.Button("Segment Folder", id="btn-seg-folder", n_clicks=0),
        ]),

        # --- Main area ---
        html.Div(id="main-content", children=[
            html.Div(id="page-content"),
        ]),

        # --- Modals ---
        html.Div(id="modal-container"),
        html.Div(id="edit-modal-container"),
        html.Div(id="culture-edit-modal"),
        html.Div(id="seg-folder-modal-container"),
    ])


app.layout = make_layout


# Helper renderers
def render_dashboard(cultures):
    all_entries = sum(len(storage.get_entries(c["id"])) for c in cultures)
    active_count = sum(1 for c in cultures if c.get("status") == "active")

    cards = []
    for c in cultures:
        entries = storage.get_entries(c["id"])
        latest_conf = f"{entries[-1]['confluency']:.1f}%" if entries else "—"
        status = c.get("status", "active")
        cards.append(
            html.Div(className="culture-card", id={"type": "culture-card", "index": c["id"]}, children=[
                html.Div(className="culture-card-header", children=[
                    html.Div([
                        html.Div(c["name"], className="culture-card-name"),
                        html.Div(c.get("cell_line", "") or "—", className="culture-card-cellline"),
                    ]),
                    html.Span(status, className=f"status-tag {status}"),
                ]),
                html.Div(className="culture-card-meta-row", children=[
                    html.Span(c.get("medium", "") or "—",
                              style={"fontSize": "12px", "color": "var(--text-sec)"}),
                ]) if c.get("medium") else html.Div(),
                html.Div(className="culture-card-stats", children=[
                    html.Div([
                        html.Div("Passage", className="card-stat-label"),
                        html.Div(f"P{c.get('current_passage', 0)}", className="card-stat-value"),
                    ]),
                    html.Div([
                        html.Div("Measurements", className="card-stat-label"),
                        html.Div(str(len(entries)), className="card-stat-value"),
                    ]),
                    html.Div([
                        html.Div("Confluency", className="card-stat-label"),
                        html.Div(latest_conf, className="card-stat-value"),
                    ]),
                ]),
            ])
        )

    return html.Div(className="fade-in", children=[
        html.H1("Dashboard", className="page-title"),
        html.Div(className="stat-pills", children=[
            html.Div(className="stat-pill", children=[
                html.Span(str(active_count), className="stat-val"),
                html.Span("Active Cultures", className="stat-label"),
            ]),
            html.Div(className="stat-pill", children=[
                html.Span(str(all_entries), className="stat-val"),
                html.Span("Total Measurements", className="stat-label"),
            ]),
        ]),
        html.Div(className="card-grid", children=cards) if cards else html.Div(className="empty-state", children=[
            html.Div("No cultures yet", className="empty-state-title"),
            html.Div("Click '+ New Culture' in the sidebar to get started."),
        ]),
    ])


def render_culture_detail(culture_id, overlay_data=None):
    culture = storage.get_culture(culture_id)
    if not culture:
        return html.Div("Culture not found.", className="empty-state")

    entries = storage.get_entries(culture_id)
    status = culture.get("status", "active")

    # --- Breadcrumb + title ---
    header = [
        html.Div(className="breadcrumb", children=[
            html.Span("Dashboard", className="bc-link", id="bc-dashboard", n_clicks=0),
            html.Span(" / "),
            html.Span(culture["name"], style={"color": "var(--text-heading)"}),
        ]),
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "12px"}, children=[
            html.H1(culture["name"], className="detail-title", style={"marginBottom": "0"}),
            html.Button("Edit", id="btn-edit-culture", className="btn-ghost", n_clicks=0,
                        style={"fontSize": "12px", "color": "var(--text-sec)"}),
        ]),
    ]

    # --- Meta row ---
    meta = html.Div(className="meta-row", children=[
        html.Div(className="meta-tag", children=[
            html.Span("Cell Line", className="meta-tag-label"),
            html.Span(culture.get("cell_line", "—"), className="meta-tag-value"),
        ]),
        html.Div(className="meta-tag", children=[
            html.Span("Passage", className="meta-tag-label"),
            html.Span(f"P{culture.get('current_passage', 0)}", className="meta-tag-value"),
        ]),
        html.Div(className="meta-tag", children=[
            html.Span("Medium", className="meta-tag-label"),
            html.Span(culture.get("medium", "—") or "—", className="meta-tag-value"),
        ]),
        html.Div(className="meta-tag", children=[
            html.Span("Status", className="meta-tag-label"),
            html.Span(status, className=f"status-tag {status}", style={"marginLeft": "4px"}),
        ]),
    ])

    # --- Action row ---
    today_str = datetime.now().strftime("%Y-%m-%d")
    actions = html.Div(className="action-row", children=[
        dcc.Dropdown(
            id="status-dropdown",
            options=[
                {"label": "Active", "value": "active"},
                {"label": "Frozen", "value": "frozen"},
                {"label": "Terminated", "value": "terminated"},
            ],
            value=status,
            clearable=False,
            className="status-select",
            style={"width": "140px"},
        ),
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "4px"}, children=[
            html.Span("P", style={"color": "var(--text-sec)", "fontFamily": "var(--font-mono)", "fontSize": "13px"}),
            dcc.Input(
                id="passage-input", className="form-input",
                type="number", value=culture.get("current_passage", 0), min=0,
                style={"width": "70px"},
                debounce=True,
            ),
        ]),
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "4px"}, children=[
            dcc.Input(
                id="upload-date", className="form-input",
                type="text", value=today_str, placeholder="YYYY-MM-DD",
                style={"width": "120px"},
            ),
        ]),
        dcc.Dropdown(
            id="method-dropdown",
            options=[
                {"label": "Otsu", "value": "otsu"},
                {"label": "Cellpose", "value": "cellpose"},
            ],
            value="cellpose",
            clearable=False,
            className="status-select",
            style={"width": "130px"},
        ),
        dcc.Upload(
            id="image-upload",
            accept="image/*",
            children=html.Button("Upload Image", className="btn-primary"),
            style={"display": "inline-block"},
        ),
        dcc.Loading(
            id="upload-loading",
            type="dot",
            color="#00e5a0",
            children=html.Div(id="upload-status"),
        ),
    ])

    # --- Confluency timeline ---
    if entries:
        passage_colours = ["#00e5a0", "#5b8def"]
        passage_fills = ["rgba(0,229,160,0.08)", "rgba(91,141,239,0.08)"]

        fig = go.Figure()

        # Split entries into segments by passage number
        segments = []
        current_seg = [entries[0]]
        for i in range(1, len(entries)):
            if entries[i]["passage"] != entries[i - 1]["passage"]:
                segments.append(current_seg)
                # Start new segment — include the last point of the previous
                # segment so the line is continuous across the passage change
                current_seg = [entries[i - 1], entries[i]]
            else:
                current_seg.append(entries[i])
        segments.append(current_seg)

        # Draw each segment with alternating colours
        seen_passages = []
        for seg in segments:
            p = seg[-1]["passage"]
            if p not in seen_passages:
                seen_passages.append(p)
            colour_idx = seen_passages.index(p) % len(passage_colours)
            colour = passage_colours[colour_idx]
            fill = passage_fills[colour_idx]

            fig.add_trace(go.Scatter(
                x=[e["created_at"][:10] for e in seg],
                y=[e["confluency"] for e in seg],
                mode="lines+markers",
                line=dict(color=colour, width=2),
                marker=dict(size=6, color=colour),
                fill="tozeroy",
                fillcolor=fill,
                showlegend=False,
            ))

        # Add vertical lines and annotations where passage changes
        for i in range(1, len(entries)):
            if entries[i]["passage"] != entries[i - 1]["passage"]:
                date_str = entries[i]["created_at"][:10]
                new_p = entries[i]["passage"]
                fig.add_vline(
                    x=date_str, line_dash="dot", line_color="#4a5568", line_width=1,
                )
                fig.add_annotation(
                    x=date_str, y=98,
                    text=f"P{new_p}",
                    showarrow=False,
                    font=dict(size=10, color="#8b9dc3", family="JetBrains Mono"),
                    bgcolor="#111820",
                    borderpad=3,
                    bordercolor="#1a2332",
                    borderwidth=1,
                )

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#c8d6e5",
            font_family="DM Sans",
            yaxis=dict(range=[0, 100], title="Confluency %", gridcolor="#1a2332", zeroline=False),
            xaxis=dict(gridcolor="#1a2332", zeroline=False, tickformat="%d %b %Y", dtick="D1"),
            margin=dict(l=50, r=20, t=20, b=40),
            height=280,
            showlegend=False,
        )
        chart = html.Div(className="chart-panel", children=[
            html.Div("Confluency Timeline", className="chart-panel-title"),
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ])
    else:
        chart = html.Div(className="chart-panel", children=[
            html.Div("Confluency Timeline", className="chart-panel-title"),
            html.Div("No measurements yet. Upload an image to begin.", className="empty-state"),
        ])

    # --- Overlay preview ---
    overlay_section = html.Div()
    if overlay_data:
        overlay_url = overlay_data.get("overlay_url", "")
        raw_url = overlay_data.get("raw_url", "")
        outline_url = overlay_data.get("outline_url", "")
        toggle_style = {"padding": "4px 12px", "fontSize": "12px"}
        overlay_section = html.Div(className="overlay-preview", children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}, children=[
                html.Div([
                    html.Div("Segmentation Result", className="chart-panel-title", style={"margin": "0"}),
                    html.Span(f"{overlay_data['confluency']:.1f}%", className="overlay-confluency"),
                ]),
                html.Div(style={"display": "flex", "alignItems": "center", "gap": "6px"}, children=[
                    html.Button("Raw", id="btn-show-raw", className="btn-secondary toggle-btn",
                                n_clicks=0, style=toggle_style),
                    html.Button("Mask", id="btn-show-overlay", className="btn-primary toggle-btn",
                                n_clicks=0, style=toggle_style),
                    html.Button("Outline", id="btn-show-outline", className="btn-secondary toggle-btn",
                                n_clicks=0, style=toggle_style),
                    html.Button("Dismiss", id="btn-dismiss-overlay", className="btn-ghost", n_clicks=0),
                ]),
            ]),
            html.Img(id="preview-image", src=overlay_url),
            dcc.Store(id="preview-overlay-url", data=overlay_url),
            dcc.Store(id="preview-raw-url", data=raw_url),
            dcc.Store(id="preview-outline-url", data=outline_url),
        ])

    # --- Passage history ---
    passage_groups = {}
    for e in entries:
        p = e["passage"]
        passage_groups.setdefault(p, []).append(e)

    passage_cards_list = []
    for p in sorted(passage_groups.keys()):
        group = passage_groups[p]
        confs_g = [e["confluency"] for e in group]
        avg_c = sum(confs_g) / len(confs_g)
        passage_cards_list.append(html.Div(className="passage-card", children=[
            html.Div(f"Passage {p}", className="passage-card-title"),
            html.Div(className="passage-card-stat", children=[
                html.Span("Measurements"), html.Span(str(len(group)))
            ]),
            html.Div(className="passage-card-stat", children=[
                html.Span("Avg Confluency"), html.Span(f"{avg_c:.1f}%")
            ]),
            html.Div(className="passage-card-stat", children=[
                html.Span("Latest"), html.Span(f"{confs_g[-1]:.1f}%")
            ]),
        ]))

    passage_section = html.Div()
    if passage_cards_list:
        passage_section = html.Div([
            html.Div("Passage History", className="section-title"),
            html.Div(className="passage-cards", children=passage_cards_list),
        ])

    # --- Measurement log ---
    table_section = html.Div()
    if entries:
        rows = []
        for i, e in enumerate(entries):
            conf = e["confluency"]
            delta = conf - entries[i - 1]["confluency"] if i > 0 else 0
            if delta > 0:
                delta_el = html.Span(f"+{delta:.1f}%", className="delta-pos")
            elif delta < 0:
                delta_el = html.Span(f"{delta:.1f}%", className="delta-neg")
            else:
                delta_el = html.Span("—", className="delta-zero")

            # View overlay link (only if an overlay exists for this entry)
            if e.get("overlay_path"):
                view_el = html.Span(
                    "View", className="btn-ghost",
                    id={"type": "view-overlay", "index": e["id"]},
                    n_clicks=0,
                    style={"color": "var(--accent)", "cursor": "pointer", "fontSize": "12px"},
                )
            else:
                view_el = html.Span("—", className="delta-zero")

            edit_el = html.Span(
                "Edit", className="btn-ghost",
                id={"type": "edit-entry", "index": e["id"]},
                n_clicks=0,
                style={"color": "var(--text-sec)", "cursor": "pointer", "fontSize": "12px"},
            )

            method_label = e.get("method", "—")
            method_el = html.Span(
                method_label,
                className="passage-pill",
                style={"background": "#1a2332",
                       "color": "#00e5a0" if method_label == "cellpose" else "#f5c542"},
            )

            rows.append(html.Tr([
                html.Td(format_date(e["created_at"])),
                html.Td(html.Span(f"P{e['passage']}", className="passage-pill")),
                html.Td(html.Span(f"{conf:.1f}%", className=f"conf-value {confluency_class(conf)}")),
                html.Td(delta_el),
                html.Td(method_el),
                html.Td(view_el),
                html.Td(edit_el),
            ]))

        table_section = html.Div([
            html.Div("Measurement Log", className="section-title"),
            html.Table(className="measurement-table", children=[
                html.Thead(html.Tr([
                    html.Th("Date"), html.Th("Passage"), html.Th("Confluency"),
                    html.Th("Delta"), html.Th("Method"), html.Th("Overlay"), html.Th(""),
                ])),
                html.Tbody(rows[::-1]),  # newest first
            ]),
        ])

    return html.Div(className="fade-in", children=[
        *header, meta, actions, chart, overlay_section,
        passage_section, table_section,
    ])


def render_sidebar_cultures(cultures, selected_id):
    items = []
    for c in cultures:
        status = c.get("status", "active")
        active = "active" if c["id"] == selected_id else ""
        entries = storage.get_entries(c["id"])
        items.append(html.Div(
            className=f"sidebar-culture-item {active}",
            id={"type": "sidebar-item", "index": c["id"]},
            n_clicks=0,
            children=[
                html.Div(className=f"status-dot {status}"),
                html.Div([
                    html.Div(c["name"], className="sidebar-culture-name"),
                    html.Div(f"P{c.get('current_passage', 0)} · {len(entries)} meas.", className="sidebar-culture-meta"),
                ], style={"flex": "1", "minWidth": "0"}),
                html.Button(
                    "×", className="sidebar-delete-btn",
                    id={"type": "delete-culture", "index": c["id"]},
                    n_clicks=0,
                ),
            ],
        ))
    return items



# Callbacks

# --- Sidebar culture list ---
@callback(
    Output("sidebar-cultures", "children"),
    Input("refresh-trigger", "data"),
    Input("selected-culture", "data"),
)
def update_sidebar(_, selected):
    cultures = storage.list_cultures()
    return render_sidebar_cultures(cultures, selected)


# --- Nav button active state ---
@callback(
    Output("nav-dashboard", "className"),
    Input("current-view", "data"),
)
def update_nav_classes(view):
    base = "sidebar-nav-btn"
    if view == "dashboard":
        return f"{base} active"
    return base


# --- Navigate to dashboard ---
@callback(
    Output("current-view", "data", allow_duplicate=True),
    Output("selected-culture", "data", allow_duplicate=True),
    Input("nav-dashboard", "n_clicks"),
    prevent_initial_call=True,
)
def nav_to_dashboard(n):
    if n:
        return "dashboard", None
    return no_update, no_update


# --- Click sidebar culture item ---
@callback(
    Output("current-view", "data", allow_duplicate=True),
    Output("selected-culture", "data", allow_duplicate=True),
    Input({"type": "sidebar-item", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def sidebar_culture_click(n_clicks_list):
    if not ctx.triggered_id or not any(n_clicks_list):
        return no_update, no_update
    culture_id = ctx.triggered_id["index"]
    return "culture", culture_id


# --- Delete culture from sidebar ---
@callback(
    Output("refresh-trigger", "data", allow_duplicate=True),
    Output("current-view", "data", allow_duplicate=True),
    Output("selected-culture", "data", allow_duplicate=True),
    Input({"type": "delete-culture", "index": ALL}, "n_clicks"),
    State("selected-culture", "data"),
    State("refresh-trigger", "data"),
    prevent_initial_call=True,
)
def delete_culture_click(n_clicks_list, current_sel, trigger):
    if not ctx.triggered_id or not any(n for n in n_clicks_list if n):
        return no_update, no_update, no_update
    culture_id = ctx.triggered_id["index"]
    storage.delete_culture(culture_id)
    new_trigger = (trigger or 0) + 1
    # If we deleted the currently viewed culture, go back to dashboard
    if current_sel == culture_id:
        return new_trigger, "dashboard", None
    return new_trigger, no_update, no_update


# --- Click dashboard card ---
@callback(
    Output("current-view", "data", allow_duplicate=True),
    Output("selected-culture", "data", allow_duplicate=True),
    Input({"type": "culture-card", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def card_click(n_clicks_list):
    if not ctx.triggered_id or not any(n for n in n_clicks_list if n):
        return no_update, no_update
    culture_id = ctx.triggered_id["index"]
    return "culture", culture_id


# --- Breadcrumb back ---
@callback(
    Output("current-view", "data", allow_duplicate=True),
    Output("selected-culture", "data", allow_duplicate=True),
    Input("bc-dashboard", "n_clicks"),
    prevent_initial_call=True,
)
def breadcrumb_back(n):
    if n:
        return "dashboard", None
    return no_update, no_update


# --- Page content render ---
@callback(
    Output("page-content", "children"),
    Input("current-view", "data"),
    Input("selected-culture", "data"),
    Input("refresh-trigger", "data"),
    Input("overlay-data", "data"),
)
def render_page(view, culture_id, _, overlay_data):
    cultures = storage.list_cultures()
    if view == "culture" and culture_id:
        return render_culture_detail(culture_id, overlay_data)
    return render_dashboard(cultures)


# --- Modal: open ---
@callback(
    Output("modal-container", "children"),
    Input("sidebar-add-btn", "n_clicks"),
    prevent_initial_call=True,
)
def open_modal(n):
    if not n:
        return no_update
    return html.Div(className="modal-backdrop", id="modal-backdrop", children=[
        html.Div(className="modal-card", children=[
            html.Div("New Culture", className="modal-title"),
            html.Div(className="form-group", children=[
                html.Label("Name", className="form-label"),
                dcc.Input(id="form-name", className="form-input", placeholder="e.g. HeLa Batch 12"),
            ]),
            html.Div(className="form-group", children=[
                html.Label("Cell Line", className="form-label"),
                dcc.Input(id="form-cellline", className="form-input", placeholder="e.g. HeLa"),
            ]),
            html.Div(className="form-group", children=[
                html.Label("Starting Passage", className="form-label"),
                dcc.Input(id="form-passage", className="form-input", type="number", value=0, min=0),
            ]),
            html.Div(className="form-group", children=[
                html.Label("Medium", className="form-label"),
                dcc.Input(id="form-medium", className="form-input", placeholder="e.g. DMEM + 10% FBS"),
            ]),
            html.Div(className="form-group", children=[
                html.Label("Notes", className="form-label"),
                dcc.Textarea(id="form-notes", className="form-textarea", placeholder="Optional notes…"),
            ]),
            html.Div(className="modal-actions", children=[
                html.Button("Cancel", id="btn-cancel-modal", className="btn-secondary", n_clicks=0),
                html.Button("Create Culture", id="btn-create-culture", className="btn-primary", n_clicks=0),
            ]),
        ]),
    ])


# --- Modal: create culture ---
@callback(
    Output("modal-container", "children", allow_duplicate=True),
    Output("refresh-trigger", "data", allow_duplicate=True),
    Output("current-view", "data", allow_duplicate=True),
    Output("selected-culture", "data", allow_duplicate=True),
    Input("btn-create-culture", "n_clicks"),
    State("form-name", "value"),
    State("form-cellline", "value"),
    State("form-passage", "value"),
    State("form-medium", "value"),
    State("form-notes", "value"),
    State("refresh-trigger", "data"),
    prevent_initial_call=True,
)
def create_culture(n, name, cell_line, passage, medium, notes, trigger):
    if not n or not name:
        return no_update, no_update, no_update, no_update
    culture = storage.create_culture(
        name=name.strip(),
        cell_line=(cell_line or "").strip(),
        starting_passage=passage or 0,
        medium=(medium or "").strip(),
        notes=(notes or "").strip(),
    )
    return None, (trigger or 0) + 1, "culture", culture["id"]


# --- Modal: cancel ---
@callback(
    Output("modal-container", "children", allow_duplicate=True),
    Input("btn-cancel-modal", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_modal(n):
    if n:
        return None
    return no_update


# --- Status dropdown ---
@callback(
    Output("refresh-trigger", "data", allow_duplicate=True),
    Input("status-dropdown", "value"),
    State("selected-culture", "data"),
    State("refresh-trigger", "data"),
    prevent_initial_call=True,
)
def change_status(new_status, culture_id, trigger):
    if not culture_id or not new_status:
        return no_update
    storage.update_culture(culture_id, {"status": new_status})
    return (trigger or 0) + 1


# --- Passage number change ---
@callback(
    Output("refresh-trigger", "data", allow_duplicate=True),
    Input("passage-input", "value"),
    State("selected-culture", "data"),
    State("refresh-trigger", "data"),
    prevent_initial_call=True,
)
def update_passage(value, culture_id, trigger):
    if value is None or not culture_id:
        return no_update
    storage.update_culture(culture_id, {"current_passage": int(value)})
    return (trigger or 0) + 1




# --- Upload status hint (fires immediately on file select, before analysis runs) ---
app.clientside_callback(
    """
    function(contents, method) {
        if (!contents) return "";
        if (method === "cellpose") {
            return "Analysing — Cellpose may take some time…";
        }
        return "Analysing…";
    }
    """,
    Output("upload-status", "children", allow_duplicate=True),
    Input("image-upload", "contents"),
    State("method-dropdown", "value"),
    prevent_initial_call=True,
)


# --- Image upload → analysis ---
@callback(
    Output("refresh-trigger", "data", allow_duplicate=True),
    Output("overlay-data", "data", allow_duplicate=True),
    Output("upload-status", "children"),
    Input("image-upload", "contents"),
    State("image-upload", "filename"),
    State("selected-culture", "data"),
    State("upload-date", "value"),
    State("method-dropdown", "value"),
    State("refresh-trigger", "data"),
    prevent_initial_call=True,
)
def handle_upload(contents, filename, culture_id, upload_date, method, trigger):
    if not contents or not culture_id:
        return no_update, no_update, no_update

    culture = storage.get_culture(culture_id)
    if not culture:
        return no_update, no_update, no_update

    # Decode and save the uploaded image
    img_dir = storage.get_image_dir(culture_id)
    _, ext = os.path.splitext(filename or "image.png")
    uid = str(uuid.uuid4())[:8]
    img_filename = f"{uid}{ext}"
    img_path = os.path.join(img_dir, img_filename)

    content_string = contents.split(",")[1]
    with open(img_path, "wb") as f:
        f.write(base64.b64decode(content_string))

    # Run analysis with selected method
    result = analysis.analyse_image(img_path, img_dir, method=method or "auto")

    # Relative paths for storage and serving
    rel_img = f"{culture_id}/images/{img_filename}"
    overlay_basename = os.path.basename(result["overlay_path"])
    rel_overlay = f"{culture_id}/images/{overlay_basename}"
    outline_basename = os.path.basename(result["outline_path"])
    rel_outline = f"{culture_id}/images/{outline_basename}"
    raw_png_basename = os.path.basename(result["raw_png_path"])
    rel_raw_png = f"{culture_id}/images/{raw_png_basename}"

    # Use the date from the input field, fall back to today
    entry_date = upload_date or datetime.now().strftime("%Y-%m-%d")

    # Add entry
    storage.add_entry(
        culture_id=culture_id,
        passage=culture.get("current_passage", 0),
        confluency=result["confluency"],
        image_path=rel_img,
        overlay_path=rel_overlay,
        outline_path=rel_outline,
        raw_png_path=rel_raw_png,
        method=result["method"],
        created_at=entry_date,
    )

    overlay_data = {
        "confluency": result["confluency"],
        "overlay_url": f"/cultures/{rel_overlay}",
        "outline_url": f"/cultures/{rel_outline}",
        "raw_url": f"/cultures/{rel_raw_png}",
    }

    return (trigger or 0) + 1, overlay_data, ""


# --- Dismiss overlay ---
@callback(
    Output("overlay-data", "data", allow_duplicate=True),
    Input("btn-dismiss-overlay", "n_clicks"),
    prevent_initial_call=True,
)
def dismiss_overlay(n):
    if n:
        return None
    return no_update


# --- Toggle raw / mask / outline image ---
@callback(
    Output("preview-image", "src"),
    Output("btn-show-raw", "className"),
    Output("btn-show-overlay", "className"),
    Output("btn-show-outline", "className"),
    Input("btn-show-raw", "n_clicks"),
    Input("btn-show-overlay", "n_clicks"),
    Input("btn-show-outline", "n_clicks"),
    State("preview-overlay-url", "data"),
    State("preview-raw-url", "data"),
    State("preview-outline-url", "data"),
    prevent_initial_call=True,
)
def toggle_preview_image(n_raw, n_overlay, n_outline, overlay_url, raw_url, outline_url):
    on = "btn-primary toggle-btn"
    off = "btn-secondary toggle-btn"
    triggered = ctx.triggered_id
    if triggered == "btn-show-raw":
        return raw_url or "", on, off, off
    if triggered == "btn-show-outline":
        return outline_url or "", off, off, on
    return overlay_url or "", off, on, off


# --- View historical overlay from measurement log ---
@callback(
    Output("overlay-data", "data", allow_duplicate=True),
    Input({"type": "view-overlay", "index": ALL}, "n_clicks"),
    State("selected-culture", "data"),
    prevent_initial_call=True,
)
def view_historical_overlay(n_clicks_list, culture_id):
    if not ctx.triggered_id or not any(n for n in n_clicks_list if n):
        return no_update
    entry_id = ctx.triggered_id["index"]
    entries = storage.get_entries(culture_id)
    entry = next((e for e in entries if e["id"] == entry_id), None)
    if not entry or not entry.get("overlay_path"):
        return no_update
    raw_path = entry.get("raw_png_path") or entry.get("image_path", "")
    outline_path = entry.get("outline_path", "")
    return {
        "confluency": entry["confluency"],
        "overlay_url": f"/cultures/{entry['overlay_path']}",
        "outline_url": f"/cultures/{outline_path}" if outline_path else "",
        "raw_url": f"/cultures/{raw_path}",
    }


# --- Edit entry: open modal ---
@callback(
    Output("edit-modal-container", "children"),
    Output("editing-entry", "data"),
    Input({"type": "edit-entry", "index": ALL}, "n_clicks"),
    State("selected-culture", "data"),
    prevent_initial_call=True,
)
def open_edit_modal(n_clicks_list, culture_id):
    if not ctx.triggered_id or not any(n for n in n_clicks_list if n):
        return no_update, no_update
    entry_id = ctx.triggered_id["index"]
    entries = storage.get_entries(culture_id)
    entry = next((e for e in entries if e["id"] == entry_id), None)
    if not entry:
        return no_update, no_update

    # Parse date and time for separate input fields
    try:
        dt = datetime.fromisoformat(entry["created_at"])
        date_val = dt.strftime("%Y-%m-%d")
    except Exception:
        date_val = ""

    modal = html.Div(className="modal-backdrop", children=[
        html.Div(className="modal-card", children=[
            html.Div("Edit Measurement", className="modal-title"),
            html.Div(className="form-group", children=[
                html.Label("Date (YYYY-MM-DD)", className="form-label"),
                dcc.Input(
                    id="edit-date", className="form-input",
                    type="text", value=date_val, placeholder="2025-03-22",
                ),
            ]),
            html.Div(className="form-group", children=[
                html.Label("Passage", className="form-label"),
                dcc.Input(
                    id="edit-passage", className="form-input",
                    type="number", value=entry["passage"], min=0,
                ),
            ]),
            html.Div(className="form-group", children=[
                html.Label("Replace Image", className="form-label"),
                html.Div(
                    "Click to select a new image (optional)",
                    style={"fontSize": "11px", "color": "var(--text-muted)", "marginBottom": "6px"},
                ),
                dcc.Upload(
                    id="edit-image-upload",
                    accept="image/*",
                    children=html.Button("Choose New Image", className="btn-secondary"),
                    style={"display": "inline-block"},
                ),
                html.Div(id="edit-upload-status", style={"marginTop": "6px", "fontSize": "12px", "color": "var(--accent)"}),
            ]),
            html.Div(className="modal-actions", children=[
                html.Button(
                    "Delete Measurement", id="btn-delete-entry",
                    className="btn-ghost", n_clicks=0,
                    style={"color": "var(--status-terminated)", "marginRight": "auto"},
                ),
                html.Button("Cancel", id="btn-cancel-edit", className="btn-secondary", n_clicks=0),
                html.Button("Save Changes", id="btn-save-edit", className="btn-primary", n_clicks=0),
            ]),
        ]),
    ])
    return modal, entry_id




# --- Edit entry: show filename when image selected ---
@callback(
    Output("edit-upload-status", "children"),
    Input("edit-image-upload", "filename"),
    prevent_initial_call=True,
)
def edit_upload_status(filename):
    if filename:
        return f"Selected: {filename}"
    return ""


# --- Edit entry: save changes ---
@callback(
    Output("edit-modal-container", "children", allow_duplicate=True),
    Output("refresh-trigger", "data", allow_duplicate=True),
    Input("btn-save-edit", "n_clicks"),
    State("editing-entry", "data"),
    State("selected-culture", "data"),
    State("edit-date", "value"),
    State("edit-passage", "value"),
    State("edit-image-upload", "contents"),
    State("edit-image-upload", "filename"),
    State("refresh-trigger", "data"),
    prevent_initial_call=True,
)
def save_edit(n, entry_id, culture_id, date_val, passage, img_contents, img_filename, trigger):
    if not n or not entry_id or not culture_id:
        return no_update, no_update

    updates = {}

    # Update date
    if date_val:
        try:
            dt = datetime.fromisoformat(date_val)
            updates["created_at"] = dt.date().isoformat()
        except Exception:
            pass

    # Update passage
    if passage is not None:
        updates["passage"] = int(passage)

    # Replace image and re-run analysis
    if img_contents:
        img_dir = storage.get_image_dir(culture_id)
        _, ext = os.path.splitext(img_filename or "image.png")
        uid = str(uuid.uuid4())[:8]
        img_filename_new = f"{uid}{ext}"
        img_path = os.path.join(img_dir, img_filename_new)

        content_string = img_contents.split(",")[1]
        with open(img_path, "wb") as f:
            f.write(base64.b64decode(content_string))

        result = analysis.analyse_image(img_path, img_dir)
        rel_img = f"{culture_id}/images/{img_filename_new}"
        overlay_basename = os.path.basename(result["overlay_path"])
        rel_overlay = f"{culture_id}/images/{overlay_basename}"
        outline_basename = os.path.basename(result["outline_path"])
        rel_outline = f"{culture_id}/images/{outline_basename}"
        raw_png_basename = os.path.basename(result["raw_png_path"])
        rel_raw_png = f"{culture_id}/images/{raw_png_basename}"

        updates["image_path"] = rel_img
        updates["overlay_path"] = rel_overlay
        updates["outline_path"] = rel_outline
        updates["raw_png_path"] = rel_raw_png
        updates["confluency"] = result["confluency"]

    storage.update_entry(culture_id, entry_id, updates)
    return None, (trigger or 0) + 1


# --- Edit entry: cancel ---
@callback(
    Output("edit-modal-container", "children", allow_duplicate=True),
    Input("btn-cancel-edit", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_edit(n):
    if n:
        return None
    return no_update


# --- Edit entry: delete ---
@callback(
    Output("edit-modal-container", "children", allow_duplicate=True),
    Output("refresh-trigger", "data", allow_duplicate=True),
    Input("btn-delete-entry", "n_clicks"),
    State("editing-entry", "data"),
    State("selected-culture", "data"),
    State("refresh-trigger", "data"),
    prevent_initial_call=True,
)
def delete_entry(n, entry_id, culture_id, trigger):
    if not n or not entry_id or not culture_id:
        return no_update, no_update
    storage.delete_entry(culture_id, entry_id)
    return None, (trigger or 0) + 1


# --- Edit culture: open modal ---
@callback(
    Output("culture-edit-modal", "children"),
    Input("btn-edit-culture", "n_clicks"),
    State("selected-culture", "data"),
    prevent_initial_call=True,
)
def open_culture_edit(n, culture_id):
    if not n or not culture_id:
        return no_update
    culture = storage.get_culture(culture_id)
    if not culture:
        return no_update
    return html.Div(className="modal-backdrop", children=[
        html.Div(className="modal-card", children=[
            html.Div("Edit Culture", className="modal-title"),
            html.Div(className="form-group", children=[
                html.Label("Name", className="form-label"),
                dcc.Input(id="edit-culture-name", className="form-input",
                          value=culture.get("name", "")),
            ]),
            html.Div(className="form-group", children=[
                html.Label("Cell Line", className="form-label"),
                dcc.Input(id="edit-culture-cellline", className="form-input",
                          value=culture.get("cell_line", "")),
            ]),
            html.Div(className="form-group", children=[
                html.Label("Medium", className="form-label"),
                dcc.Input(id="edit-culture-medium", className="form-input",
                          value=culture.get("medium", "")),
            ]),
            html.Div(className="form-group", children=[
                html.Label("Notes", className="form-label"),
                dcc.Textarea(id="edit-culture-notes", className="form-textarea",
                             value=culture.get("notes", "")),
            ]),
            html.Div(className="modal-actions", children=[
                html.Button("Cancel", id="btn-cancel-culture-edit",
                            className="btn-secondary", n_clicks=0),
                html.Button("Save", id="btn-save-culture-edit",
                            className="btn-primary", n_clicks=0),
            ]),
        ]),
    ])


# --- Edit culture: save ---
@callback(
    Output("culture-edit-modal", "children", allow_duplicate=True),
    Output("refresh-trigger", "data", allow_duplicate=True),
    Input("btn-save-culture-edit", "n_clicks"),
    State("selected-culture", "data"),
    State("edit-culture-name", "value"),
    State("edit-culture-cellline", "value"),
    State("edit-culture-medium", "value"),
    State("edit-culture-notes", "value"),
    State("refresh-trigger", "data"),
    prevent_initial_call=True,
)
def save_culture_edit(n, culture_id, name, cell_line, medium, notes, trigger):
    if not n or not culture_id:
        return no_update, no_update
    updates = {
        "name": (name or "").strip(),
        "cell_line": (cell_line or "").strip(),
        "medium": (medium or "").strip(),
        "notes": (notes or "").strip(),
    }
    storage.update_culture(culture_id, updates)
    return None, (trigger or 0) + 1


# --- Edit culture: cancel ---
@callback(
    Output("culture-edit-modal", "children", allow_duplicate=True),
    Input("btn-cancel-culture-edit", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_culture_edit(n):
    if n:
        return None
    return no_update


# ---------------------------------------------------------------------------
# Segment-folder modal helpers
# ---------------------------------------------------------------------------

def seg_folder_form(input_dir="", output_dir="", method="cellpose", error=""):
    browse_style = {
        "padding": "8px 14px", "fontSize": "12px", "fontWeight": "600",
        "background": "#7c3aed", "color": "#fff", "border": "none",
        "borderRadius": "8px", "cursor": "pointer", "whiteSpace": "nowrap",
    }
    return html.Div(className="modal-backdrop", children=[
        html.Div(className="modal-card", children=[
            html.Div("Segment Folder", className="modal-title"),
            html.Div(className="form-group", children=[
                html.Label("Input Directory", className="form-label"),
                html.Div(style={"display": "flex", "gap": "6px"}, children=[
                    dcc.Input(id="seg-input-dir", className="form-input",
                              placeholder="C:\\path\\to\\images", value=input_dir,
                              style={"flex": "1"}),
                    html.Button("Browse", id="btn-browse-input", n_clicks=0,
                                style=browse_style),
                ]),
            ]),
            html.Div(className="form-group", children=[
                html.Label("Output Directory", className="form-label"),
                html.Div(style={"display": "flex", "gap": "6px"}, children=[
                    dcc.Input(id="seg-output-dir", className="form-input",
                              placeholder="C:\\path\\to\\output", value=output_dir,
                              style={"flex": "1"}),
                    html.Button("Browse", id="btn-browse-output", n_clicks=0,
                                style=browse_style),
                ]),
            ]),
            html.Div(className="form-group", children=[
                html.Label("Method", className="form-label"),
                dcc.Dropdown(
                    id="seg-method",
                    options=[
                        {"label": "Otsu", "value": "otsu"},
                        {"label": "Cellpose", "value": "cellpose"},
                    ],
                    value=method,
                    clearable=False,
                    className="status-select",
                ),
            ]),
            html.Div(error, style={
                "color": "var(--status-terminated)", "fontSize": "12px",
                "marginBottom": "8px", "minHeight": "16px",
            }),
            html.Div(className="modal-actions", children=[
                html.Button("Cancel", id="btn-seg-cancel", className="btn-secondary", n_clicks=0),
                html.Button("Start", id="btn-seg-start", className="btn-primary", n_clicks=0),
            ]),
        ]),
    ])


def seg_folder_progress(job):
    total = max(job.get("total", 1), 1)
    progress = job.get("progress", 0)
    pct = int(progress / total * 100)
    status = job.get("status", "running")
    message = job.get("message", "Starting…")
    is_done = status == "done"
    is_error = status == "error"
    bar_color = "#00e5a0" if is_done else ("#e05555" if is_error else "#5b8def")

    return html.Div(className="modal-backdrop", children=[
        html.Div(className="modal-card", children=[
            html.Div("Segment Folder", className="modal-title"),
            html.Div(style={"marginBottom": "20px"}, children=[
                html.Div(
                    style={
                        "display": "flex", "justifyContent": "space-between",
                        "marginBottom": "8px", "fontSize": "12px",
                        "color": "var(--text-sec)",
                    },
                    children=[html.Span(message), html.Span(f"{pct}%")],
                ),
                html.Div(
                    style={
                        "background": "#1a2332", "borderRadius": "4px",
                        "height": "8px", "overflow": "hidden",
                    },
                    children=[
                        html.Div(style={
                            "width": f"{pct}%", "height": "100%",
                            "background": bar_color, "borderRadius": "4px",
                            "transition": "width 0.4s ease",
                        }),
                    ],
                ),
            ]),
            html.Div(className="modal-actions", children=[
                html.Button(
                    "Close" if (is_done or is_error) else "Running…",
                    id="btn-seg-close",
                    className="btn-primary" if (is_done or is_error) else "btn-secondary",
                    n_clicks=0,
                    disabled=not (is_done or is_error),
                ),
            ]),
        ]),
    ])


# ---------------------------------------------------------------------------
# Segment-folder callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("seg-folder-modal-container", "children"),
    Input("btn-seg-folder", "n_clicks"),
    prevent_initial_call=True,
)
def open_seg_folder_modal(n):
    if not n:
        return no_update
    return seg_folder_form()


def open_folder_dialog():
    """Open a native Windows Explorer folder picker and return the chosen path."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="Select Folder")
    root.destroy()
    return folder or ""


@callback(
    Output("seg-input-dir", "value"),
    Input("btn-browse-input", "n_clicks"),
    State("seg-input-dir", "value"),
    prevent_initial_call=True,
)
def browse_input_dir(n, current):
    if not n:
        return no_update
    chosen = open_folder_dialog()
    return chosen if chosen else (current or no_update)


@callback(
    Output("seg-output-dir", "value"),
    Input("btn-browse-output", "n_clicks"),
    State("seg-output-dir", "value"),
    prevent_initial_call=True,
)
def browse_output_dir(n, current):
    if not n:
        return no_update
    chosen = open_folder_dialog()
    return chosen if chosen else (current or no_update)


@callback(
    Output("seg-folder-modal-container", "children", allow_duplicate=True),
    Output("seg-folder-job-id", "data"),
    Output("seg-folder-poll", "disabled"),
    Input("btn-seg-start", "n_clicks"),
    State("seg-input-dir", "value"),
    State("seg-output-dir", "value"),
    State("seg-method", "value"),
    prevent_initial_call=True,
)
def start_seg_folder(n, input_dir, output_dir, method):
    if not n:
        return no_update, no_update, no_update

    input_dir = (input_dir or "").strip()
    output_dir = (output_dir or "").strip()
    method = method or "cellpose"

    if not input_dir:
        return seg_folder_form(input_dir, output_dir, method, "Input directory is required."), no_update, no_update
    if not os.path.isdir(input_dir):
        return seg_folder_form(input_dir, output_dir, method, "Input directory does not exist."), no_update, no_update
    if not output_dir:
        return seg_folder_form(input_dir, output_dir, method, "Output directory is required."), no_update, no_update

    job_id = str(uuid.uuid4())[:8]
    seg_jobs[job_id] = {"status": "running", "progress": 0, "total": 0, "message": "Starting…"}

    threading.Thread(
        target=run_seg_folder,
        args=(job_id, input_dir, output_dir, method),
        daemon=True,
    ).start()

    return seg_folder_progress(seg_jobs[job_id]), job_id, False


@callback(
    Output("seg-folder-modal-container", "children", allow_duplicate=True),
    Output("seg-folder-poll", "disabled", allow_duplicate=True),
    Input("seg-folder-poll", "n_intervals"),
    State("seg-folder-job-id", "data"),
    prevent_initial_call=True,
)
def poll_seg_folder(_, job_id):
    if not job_id or job_id not in seg_jobs:
        return no_update, True
    job = seg_jobs[job_id]
    done = job["status"] in ("done", "error")
    return seg_folder_progress(job), done


@callback(
    Output("seg-folder-modal-container", "children", allow_duplicate=True),
    Output("seg-folder-poll", "disabled", allow_duplicate=True),
    Input("btn-seg-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_seg_folder(n):
    if n:
        return None, True
    return no_update, no_update


@callback(
    Output("seg-folder-modal-container", "children", allow_duplicate=True),
    Input("btn-seg-close", "n_clicks"),
    prevent_initial_call=True,
)
def close_seg_folder(n):
    if n:
        return None
    return no_update


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
