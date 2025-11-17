"""
Database Schemas for Healthcare Staff Scheduling & Care Management System

Each Pydantic model represents a collection. Collection name = lowercase class name.

Use these models for validation before writing to MongoDB.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal, Dict
from datetime import datetime

# -----------------------------
# Core Entities
# -----------------------------

class ResidentContact(BaseModel):
    name: str
    relationship: str
    phone: Optional[str] = None
    email: Optional[EmailStr] = None

class Resident(BaseModel):
    first_name: str
    last_name: str
    dob: datetime
    room: Optional[str] = None
    care_level: Literal["independent", "assisted", "memory_care", "skilled_nursing"] = "assisted"
    conditions: List[str] = []
    allergies: List[str] = []
    physician: Optional[str] = None
    contacts: List[ResidentContact] = []
    notes: Optional[str] = None
    is_active: bool = True

class StaffAvailability(BaseModel):
    day: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    start: str  # HH:MM 24h
    end: str    # HH:MM 24h

class Staff(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str] = None
    role: Literal["rn", "lpn", "cna", "caregiver", "med_tech", "housekeeping"]
    skills: List[str] = []
    max_hours_per_week: int = Field(40, ge=1, le=80)
    preferred_shift: Optional[Literal["day", "evening", "night"]] = None
    availability: List[StaffAvailability] = []
    is_active: bool = True

# -----------------------------
# Scheduling
# -----------------------------

class Shift(BaseModel):
    facility: str = "Main"
    date: datetime  # date portion used
    type: Literal["day", "evening", "night"]
    start_time: str  # HH:MM
    end_time: str    # HH:MM
    required_role: Literal["rn", "lpn", "cna", "caregiver", "med_tech", "housekeeping"]
    required_count: int = Field(1, ge=1, le=20)
    assigned_staff_ids: List[str] = []
    status: Literal["planned", "published", "in_progress", "completed", "cancelled"] = "planned"

class Schedule(BaseModel):
    name: str
    start_date: datetime
    end_date: datetime
    status: Literal["draft", "published", "archived"] = "draft"
    notes: Optional[str] = None

# -----------------------------
# Care Tasks/Plans
# -----------------------------

class CareTask(BaseModel):
    resident_id: str
    title: str
    description: Optional[str] = None
    category: Literal["medication", "hygiene", "mobility", "nutrition", "vitals", "checkin", "other"] = "other"
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    due_at: Optional[datetime] = None
    frequency: Optional[Literal["once", "hourly", "daily", "weekly"]] = "once"
    assigned_to_staff_id: Optional[str] = None
    status: Literal["pending", "in_progress", "completed", "missed", "cancelled"] = "pending"
    metadata: Dict[str, str] = {}

class CarePlanItem(BaseModel):
    resident_id: str
    goal: str
    instructions: Optional[str] = None
    category: Optional[str] = None
    active: bool = True

# -----------------------------
# Operational/Events
# -----------------------------

class Event(BaseModel):
    title: str
    description: Optional[str] = None
    start_time: datetime
    end_time: datetime
    location: Optional[str] = None
    type: Literal["activity", "maintenance", "medical", "meeting"] = "activity"
    related_resident_ids: List[str] = []

# Note: The Flames database viewer can introspect these schemas from GET /schema
