import json
import os
import re
import uuid
from datetime import datetime, timezone

CULTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cultures")

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def slugify(name):
    """Turn a culture name into a filesystem-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug or "culture"


def unique_slug(name):
    """Return a slug that doesn't collide with existing culture folders."""
    base = slugify(name)
    slug = base
    counter = 2
    while os.path.exists(os.path.join(CULTURES_DIR, slug)):
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def culture_dir(culture_id):
    return os.path.join(CULTURES_DIR, culture_id)


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def list_cultures():
    """Return a list of all culture metadata dicts, sorted by created_at."""
    ensure_dir(CULTURES_DIR)
    cultures = []
    for name in os.listdir(CULTURES_DIR):
        meta_path = os.path.join(CULTURES_DIR, name, "culture.json")
        meta = read_json(meta_path)
        if meta:
            cultures.append(meta)
    cultures.sort(key=lambda c: c.get("created_at", ""))
    return cultures


def get_culture(culture_id):
    """Return culture metadata dict or None."""
    path = os.path.join(culture_dir(culture_id), "culture.json")
    return read_json(path)


def create_culture(name, cell_line="", starting_passage=0, medium="", notes=""):
    """Create a new culture folder and return its metadata."""
    slug = unique_slug(name)
    culture = {
        "id": slug,
        "name": name,
        "cell_line": cell_line,
        "medium": medium,
        "current_passage": int(starting_passage),
        "status": "active",
        "notes": notes,
        "created_at": now_iso(),
    }
    cdir = ensure_dir(culture_dir(slug))
    write_json(os.path.join(cdir, "culture.json"), culture)
    write_json(os.path.join(cdir, "entries.json"), [])
    ensure_dir(os.path.join(cdir, "images"))
    return culture


def update_culture(culture_id, updates):
    """Merge *updates* into culture metadata and persist."""
    path = os.path.join(culture_dir(culture_id), "culture.json")
    culture = read_json(path)
    if culture is None:
        return None
    culture.update(updates)
    write_json(path, culture)
    return culture


def delete_culture(culture_id):
    """Remove the entire culture folder."""
    import shutil
    cdir = culture_dir(culture_id)
    if os.path.exists(cdir):
        shutil.rmtree(cdir)
        return True
    return False


def increment_passage(culture_id):
    """Bump current_passage by 1 and return updated culture."""
    culture = get_culture(culture_id)
    if culture is None:
        return None
    culture["current_passage"] = culture.get("current_passage", 0) + 1
    write_json(os.path.join(culture_dir(culture_id), "culture.json"), culture)
    return culture

def get_entries(culture_id):
    """Return list of measurement entries for a culture."""
    path = os.path.join(culture_dir(culture_id), "entries.json")
    return read_json(path, default=[])


def add_entry(culture_id, passage, confluency, image_path="", overlay_path="",
              outline_path="", raw_png_path="", method="", created_at=None):
    """Append a measurement entry and return it."""
    entries_path = os.path.join(culture_dir(culture_id), "entries.json")
    entries = read_json(entries_path, default=[])
    entry = {
        "id": str(uuid.uuid4())[:8],
        "passage": int(passage),
        "confluency": round(float(confluency), 2),
        "image_path": image_path,
        "overlay_path": overlay_path,
        "outline_path": outline_path,
        "raw_png_path": raw_png_path,
        "method": method,
        "created_at": created_at or now_iso(),
    }
    entries.append(entry)
    write_json(entries_path, entries)
    return entry


def update_entry(culture_id, entry_id, updates):
    """Update fields on a specific entry and persist."""
    entries_path = os.path.join(culture_dir(culture_id), "entries.json")
    entries = read_json(entries_path, default=[])
    for entry in entries:
        if entry["id"] == entry_id:
            entry.update(updates)
            write_json(entries_path, entries)
            return entry
    return None


def delete_entry(culture_id, entry_id):
    """Remove an entry by id. Returns True if found and removed."""
    entries_path = os.path.join(culture_dir(culture_id), "entries.json")
    entries = read_json(entries_path, default=[])
    new_entries = [e for e in entries if e["id"] != entry_id]
    if len(new_entries) < len(entries):
        write_json(entries_path, new_entries)
        return True
    return False

def get_image_dir(culture_id):
    """Return (and ensure) the images directory for a culture."""
    return ensure_dir(os.path.join(culture_dir(culture_id), "images"))
