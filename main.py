import os
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from schemas import Resident, Staff, Shift, CareTask, CarePlanItem, Event
from database import create_document, get_documents, db

try:
    from bson import ObjectId
except Exception:  # pragma: no cover
    ObjectId = None

app = FastAPI(title="Healthcare Staff Scheduling & Care Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Helpers
# -----------------------------

def oid(id_str: str):
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


def serialize(doc: Dict[str, Any]):
    if not doc:
        return doc
    d = doc.copy()
    if d.get("_id") is not None:
        d["id"] = str(d.pop("_id"))
    # convert datetimes
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


# -----------------------------
# Root & Health
# -----------------------------

@app.get("/")
def read_root():
    return {"message": "Healthcare Scheduling & Care Management API running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:20]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"

    return response


# -----------------------------
# Schema Introspection Endpoint
# -----------------------------

@app.get("/schema")
def get_schema():
    # Expose Pydantic model schemas for the viewer
    models = {
        "resident": Resident.model_json_schema(),
        "staff": Staff.model_json_schema(),
        "shift": Shift.model_json_schema(),
        "caretask": CareTask.model_json_schema(),
        "careplanitem": CarePlanItem.model_json_schema(),
        "event": Event.model_json_schema(),
    }
    return {"models": models}


# -----------------------------
# Residents
# -----------------------------

@app.post("/residents")
def create_resident(payload: Resident):
    resident_id = create_document("resident", payload)
    doc = db["resident"].find_one({"_id": oid(resident_id)})
    return serialize(doc)


@app.get("/residents")
def list_residents():
    docs = get_documents("resident")
    return [serialize(d) for d in docs]


# -----------------------------
# Staff
# -----------------------------

@app.post("/staff")
def create_staff(payload: Staff):
    staff_id = create_document("staff", payload)
    doc = db["staff"].find_one({"_id": oid(staff_id)})
    return serialize(doc)


@app.get("/staff")
def list_staff():
    docs = get_documents("staff")
    return [serialize(d) for d in docs]


# -----------------------------
# Shifts
# -----------------------------

@app.post("/shifts")
def create_shift(payload: Shift):
    shift_id = create_document("shift", payload)
    doc = db["shift"].find_one({"_id": oid(shift_id)})
    return serialize(doc)


@app.get("/shifts")
def list_shifts():
    docs = get_documents("shift")
    return [serialize(d) for d in docs]


# -----------------------------
# Care Tasks
# -----------------------------

@app.post("/tasks")
def create_task(payload: CareTask):
    task_id = create_document("caretask", payload)
    doc = db["caretask"].find_one({"_id": oid(task_id)})
    return serialize(doc)


@app.get("/tasks")
def list_tasks(resident_id: Optional[str] = None, staff_id: Optional[str] = None):
    filt: Dict[str, Any] = {}
    if resident_id:
        filt["resident_id"] = resident_id
    if staff_id:
        filt["assigned_to_staff_id"] = staff_id
    docs = get_documents("caretask", filt)
    return [serialize(d) for d in docs]


class TaskStatusUpdate(BaseModel):
    status: str


@app.patch("/tasks/{task_id}/status")
def update_task_status(task_id: str, payload: TaskStatusUpdate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    res = db["caretask"].update_one({"_id": oid(task_id)}, {"$set": {"status": payload.status, "updated_at": datetime.utcnow()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    doc = db["caretask"].find_one({"_id": oid(task_id)})
    return serialize(doc)


# -----------------------------
# Intelligent Auto-Assignment
# -----------------------------

class AutoAssignRequest(BaseModel):
    date: Optional[str] = None  # YYYY-MM-DD, if None, use all planned shifts


def time_overlap(s1: str, e1: str, s2: str, e2: str) -> bool:
    return not (e1 <= s2 or e2 <= s1)


@app.post("/assign/auto")
def auto_assign(req: AutoAssignRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")

    # Fetch planned/published shifts for the date (if provided)
    shift_filter: Dict[str, Any] = {"status": {"$in": ["planned", "published"]}}
    if req.date:
        # Assuming 'date' is stored as datetime; match on date portion
        start_day = datetime.fromisoformat(req.date)
        end_day = start_day.replace(hour=23, minute=59, second=59, microsecond=999999)
        shift_filter["date"] = {"$gte": start_day, "$lte": end_day}

    shifts = list(db["shift"].find(shift_filter))
    staff = list(db["staff"].find({"is_active": True}))

    # Compute current hours for each staff in the week (simple count by shift duration)
    staff_hours: Dict[str, float] = {str(s["_id"]): 0.0 for s in staff}

    def shift_duration_hours(sh: Dict[str, Any]) -> float:
        fmt = "%H:%M"
        try:
            st = datetime.strptime(sh.get("start_time"), fmt)
            en = datetime.strptime(sh.get("end_time"), fmt)
            diff = (en - st).seconds / 3600
            if diff <= 0:
                diff += 24  # handle overnight
            return diff
        except Exception:
            return 8.0

    # Prevent double booking by tracking assignments by time window
    assignments: Dict[str, List[Dict[str, Any]]] = {}

    # Preload existing assignments to avoid overlaps
    existing_assigned = [s for s in shifts if s.get("assigned_staff_ids")]
    for sh in existing_assigned:
        for sid in sh.get("assigned_staff_ids", []):
            assignments.setdefault(sid, []).append({
                "date": sh.get("date"),
                "start": sh.get("start_time"),
                "end": sh.get("end_time"),
            })
            staff_hours[sid] = staff_hours.get(sid, 0.0) + shift_duration_hours(sh)

    # Helper to check availability
    def is_available(staff_doc: Dict[str, Any], sh: Dict[str, Any]) -> bool:
        preferred_ok = (staff_doc.get("preferred_shift") in (None, sh.get("type"))) or (staff_doc.get("preferred_shift") is None)
        day_key = sh.get("date").strftime("%a").lower()[:3]
        for a in staff_doc.get("availability", []):
            if a.get("day") == day_key:
                if a.get("start") <= sh.get("start_time") and a.get("end") >= sh.get("end_time"):
                    return preferred_ok
        return False

    # Build a candidate pool per role
    staff_by_role: Dict[str, List[Dict[str, Any]]] = {}
    for s in staff:
        staff_by_role.setdefault(s.get("role"), []).append(s)

    updates = []
    for sh in shifts:
        needed = int(sh.get("required_count", 1))
        role = sh.get("required_role")
        assigned = sh.get("assigned_staff_ids", [])
        if len(assigned) >= needed:
            continue

        candidates = staff_by_role.get(role, [])
        # Score candidates based on availability, hours left, preferred shift match, skills count
        scored: List[tuple] = []
        for s in candidates:
            sid = str(s["_id"])
            if not is_available(s, sh):
                continue
            # Prevent overlap
            has_overlap = False
            for slot in assignments.get(sid, []):
                if slot.get("date").date() == sh.get("date").date() and time_overlap(slot["start"], slot["end"], sh.get("start_time"), sh.get("end_time")):
                    has_overlap = True
                    break
            if has_overlap:
                continue
            hours = staff_hours.get(sid, 0.0)
            hours_left = max(0.0, float(s.get("max_hours_per_week", 40)) - hours)
            preferred_bonus = 1.0 if s.get("preferred_shift") == sh.get("type") else 0.0
            skill_bonus = min(2.0, len(s.get("skills", [])) * 0.1)
            score = hours_left + preferred_bonus + skill_bonus
            scored.append((score, s))
        # Sort by highest score (more hours left first)
        scored.sort(key=lambda x: x[0], reverse=True)

        for _, s in scored:
            if len(assigned) >= needed:
                break
            sid = str(s["_id"])
            # Assign
            assigned.append(sid)
            assignments.setdefault(sid, []).append({
                "date": sh.get("date"),
                "start": sh.get("start_time"),
                "end": sh.get("end_time"),
            })
            staff_hours[sid] = staff_hours.get(sid, 0.0) + shift_duration_hours(sh)
        if assigned != sh.get("assigned_staff_ids", []):
            res = db["shift"].update_one({"_id": sh["_id"]}, {"$set": {"assigned_staff_ids": assigned, "status": "published", "updated_at": datetime.utcnow()}})
            if res.modified_count:
                updates.append(str(sh["_id"]))

    updated_shifts = [serialize(db["shift"].find_one({"_id": oid(i)})) for i in updates]
    return {"updated": len(updates), "shifts": updated_shifts}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
