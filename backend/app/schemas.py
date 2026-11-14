"""Контракт API в коде (README плана, раздел 5 + уточнения в docs/meeting-stage0.md).

FastAPI проверяет каждый ответ по этим моделям: бэкенд не может незаметно отойти
от контракта. Схема выгружается в backend/openapi.json (python -m app.export_openapi).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

VisualCategory = Literal["no_visible_issues", "check_recommended", "possible_defect", "not_analyzed"]
ResourceStatus = Literal["ok", "approaching", "due", "insufficient_data"]
ParameterStatus = Literal["normal", "deviation", "no_data"]
AttentionLevel = Literal["defect", "check", "none", "unknown"]
InspectionType = Literal["checked", "defect", "remark", "maintenance", "replacement"]
MatchKind = Literal["matched", "ambiguous", "not_in_card"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Characteristic(Strict):
    name: str
    value: str | None
    unit: str | None


class Normative(Strict):
    life_years: float | None
    life_hours: float | None
    life_cycles: float | None
    maintenance_interval_days: int | None


class Usage(Strict):
    operating_hours: float | None
    cycles: float | None


class Remaining(Strict):
    years: float | None
    hours: float | None
    cycles: float | None


class Maintenance(Strict):
    next_due_date: str
    status: Literal["ok", "approaching", "due"]
    overdue_days: int | None = None
    days_left: int | None = None


class Resource(Strict):
    status: ResourceStatus
    used_percent: int | None
    remaining: Remaining
    estimated_end_date: str | None
    basis: str
    missing_data: list[str]
    maintenance: Maintenance | None
    message: str


class Visual(Strict):
    category: VisualCategory
    signs: list[str]
    explanation: str | None
    recommendation: str | None
    detection_confidence: float | None
    assessment_confidence: float | None
    analyzed_at: str | None
    disclaimer: str | None
    note: str | None = None


class Attention(Strict):
    level: AttentionLevel
    reasons: list[str]
    recommended_action: str


class Parameter(Strict):
    id: str
    equipment_id: str
    component_id: str | None
    name: str
    value: float | None
    unit: str | None
    setpoint_min: float | None
    setpoint_max: float | None
    measured_at: str | None
    status: ParameterStatus
    message: str


class HistoryItem(Strict):
    id: int
    component_id: str | None
    type: InspectionType
    comment: str | None
    performed_by: str | None
    performed_at: str
    visual: Visual | None
    recommendation: str | None


class Component(Strict):
    id: str
    parent_id: str | None
    kind: Literal["node", "part"]
    name: str
    type: str
    type_name: str
    order: int | None
    characteristics: list[Characteristic]
    installed_at: str | None
    last_replaced_at: str | None
    last_maintenance_at: str | None
    normative: Normative
    usage: Usage
    resource: Resource
    visual: Visual
    attention: Attention
    parameters: list[str]
    previous_results: list[HistoryItem]


class EquipmentCard(Strict):
    id: str
    name: str
    model: str | None
    manufacturer: str | None
    serial_number: str | None
    marking: str | None
    qr_code: str | None
    location: str | None
    commissioned_at: str | None
    characteristics: list[Characteristic]
    normative: Normative
    usage: Usage
    resource: Resource
    parameters: list[Parameter]
    deviations_count: int
    components: list[Component]
    history: list[HistoryItem]


class EquipmentShort(Strict):
    id: str
    name: str
    model: str | None
    serial_number: str | None
    marking: str | None
    location: str | None


class EquipmentList(Strict):
    items: list[EquipmentShort]


class Suggestion(Strict):
    equipment_id: str
    name: str
    score: float


class LookupResult(Strict):
    found: bool
    equipment_id: str | None = None
    matched_by: Literal["qr", "serial", "marking"] | None = None
    match_confidence: float | None = None
    suggestions: list[Suggestion] | None = None


class IdentifyCandidate(Strict):
    equipment_id: str
    name: str
    confidence: float


class IdentifyResult(Strict):
    recognized: bool
    candidates: list[IdentifyCandidate]


class AttentionItem(Strict):
    component_id: str
    name: str
    level: AttentionLevel
    reasons: list[str]
    recommended_action: str
    hint: str
    detectable: bool


class AttentionList(Strict):
    items: list[AttentionItem]


class Detection(Strict):
    bbox: list[float]
    cv_class: str
    detection_confidence: float
    match: MatchKind
    component_id: str | None
    candidates: list[str] | None
    label: str
    attention_level: AttentionLevel
    resource_status: ResourceStatus | None
    visual_category: VisualCategory | None
    reason: str | None
    recommended_action: str | None


class DetectResult(Strict):
    detections: list[Detection]
    not_in_frame: list[str]


class InspectionIn(Strict):
    component_id: str | None = None
    type: InspectionType
    comment: str | None = None
    performed_by: str | None = None
    attach_last_visual: bool = False


class InspectionResult(Strict):
    inspection: HistoryItem
    component: Component | None


class History(Strict):
    items: list[HistoryItem]


class AiHealth(Strict):
    mode: Literal["stub", "real"]
    status: Literal["ok", "unavailable"]


class Health(Strict):
    status: Literal["ok"]
    mode: Literal["stub", "real"]
    ai: AiHealth
    time: str


# ---------- вход, роли, учётные записи ----------

Role = Literal["engineer", "master", "admin"]
Permission = Literal["view", "inspect", "report", "users"]


class User(Strict):
    id: int
    email: str
    name: str
    role: Role
    role_name: str
    active: bool
    permissions: list[Permission]


class LoginIn(Strict):
    email: str
    password: str


class LoginResult(Strict):
    token: str
    expires_at: str
    user: User


class UserList(Strict):
    items: list[User]


class UserCreate(Strict):
    email: str
    name: str
    role: Role
    password: str


class UserUpdate(Strict):
    name: str | None = None
    role: Role | None = None
    active: bool | None = None
    password: str | None = None


class ErrorBody(Strict):
    code: str
    message: str


class Error(Strict):
    error: ErrorBody
