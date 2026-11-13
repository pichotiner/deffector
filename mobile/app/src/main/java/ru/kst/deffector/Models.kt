// Создано generate_models.py из backend/openapi.json.
package ru.kst.deffector

import kotlinx.serialization.Serializable

@Serializable
data class AiHealth(
    val mode: String,
    val status: String
)

@Serializable
data class Attention(
    val level: String,
    val reasons: List<String>,
    val recommended_action: String
)

@Serializable
data class AttentionItem(
    val component_id: String,
    val name: String,
    val level: String,
    val reasons: List<String>,
    val recommended_action: String,
    val hint: String,
    val detectable: Boolean
)

@Serializable
data class AttentionList(
    val items: List<AttentionItem>
)

@Serializable
data class Characteristic(
    val name: String,
    val value: String? = null,
    val unit: String? = null
)

@Serializable
data class Component(
    val id: String,
    val parent_id: String? = null,
    val kind: String,
    val name: String,
    val type: String,
    val type_name: String,
    val order: Int? = null,
    val characteristics: List<Characteristic>,
    val installed_at: String? = null,
    val last_replaced_at: String? = null,
    val last_maintenance_at: String? = null,
    val normative: Normative,
    val usage: Usage,
    val resource: Resource,
    val visual: Visual,
    val attention: Attention,
    val parameters: List<String>,
    val previous_results: List<HistoryItem>
)

@Serializable
data class DetectResult(
    val detections: List<Detection>,
    val not_in_frame: List<String>
)

@Serializable
data class Detection(
    val bbox: List<Double>,
    val cv_class: String,
    val detection_confidence: Double,
    val match: String,
    val component_id: String? = null,
    val candidates: List<String>? = null,
    val label: String,
    val attention_level: String,
    val resource_status: String? = null,
    val visual_category: String? = null,
    val reason: String? = null,
    val recommended_action: String? = null
)

@Serializable
data class EquipmentCard(
    val id: String,
    val name: String,
    val model: String? = null,
    val manufacturer: String? = null,
    val serial_number: String? = null,
    val marking: String? = null,
    val qr_code: String? = null,
    val location: String? = null,
    val commissioned_at: String? = null,
    val characteristics: List<Characteristic>,
    val normative: Normative,
    val usage: Usage,
    val resource: Resource,
    val parameters: List<Parameter>,
    val deviations_count: Int,
    val components: List<Component>,
    val history: List<HistoryItem>
)

@Serializable
data class EquipmentList(
    val items: List<EquipmentShort>
)

@Serializable
data class EquipmentShort(
    val id: String,
    val name: String,
    val model: String? = null,
    val serial_number: String? = null,
    val marking: String? = null,
    val location: String? = null
)

@Serializable
data class Error(
    val error: ErrorBody
)

@Serializable
data class ErrorBody(
    val code: String,
    val message: String
)

@Serializable
data class Health(
    val status: String,
    val mode: String,
    val ai: AiHealth,
    val time: String
)

@Serializable
data class History(
    val items: List<HistoryItem>
)

@Serializable
data class HistoryItem(
    val id: Int,
    val component_id: String? = null,
    val type: String,
    val comment: String? = null,
    val performed_by: String? = null,
    val performed_at: String,
    val visual: Visual? = null,
    val recommendation: String? = null
)

@Serializable
data class IdentifyCandidate(
    val equipment_id: String,
    val name: String,
    val confidence: Double
)

@Serializable
data class IdentifyResult(
    val recognized: Boolean,
    val candidates: List<IdentifyCandidate>
)

@Serializable
data class InspectionIn(
    val component_id: String? = null,
    val type: String,
    val comment: String? = null,
    val performed_by: String? = null,
    val attach_last_visual: Boolean = false
)

@Serializable
data class InspectionResult(
    val inspection: HistoryItem,
    val component: Component? = null
)

@Serializable
data class LookupResult(
    val found: Boolean,
    val equipment_id: String? = null,
    val matched_by: String? = null,
    val match_confidence: Double? = null,
    val suggestions: List<Suggestion>? = null
)

@Serializable
data class Maintenance(
    val next_due_date: String,
    val status: String,
    val overdue_days: Int? = null,
    val days_left: Int? = null
)

@Serializable
data class Normative(
    val life_years: Double? = null,
    val life_hours: Double? = null,
    val life_cycles: Double? = null,
    val maintenance_interval_days: Int? = null
)

@Serializable
data class Parameter(
    val id: String,
    val equipment_id: String,
    val component_id: String? = null,
    val name: String,
    val value: Double? = null,
    val unit: String? = null,
    val setpoint_min: Double? = null,
    val setpoint_max: Double? = null,
    val measured_at: String? = null,
    val status: String,
    val message: String
)

@Serializable
data class Remaining(
    val years: Double? = null,
    val hours: Double? = null,
    val cycles: Double? = null
)

@Serializable
data class Resource(
    val status: String,
    val used_percent: Int? = null,
    val remaining: Remaining,
    val estimated_end_date: String? = null,
    val basis: String,
    val missing_data: List<String>,
    val maintenance: Maintenance? = null,
    val message: String
)

@Serializable
data class Suggestion(
    val equipment_id: String,
    val name: String,
    val score: Double
)

@Serializable
data class Usage(
    val operating_hours: Double? = null,
    val cycles: Double? = null
)

@Serializable
data class Visual(
    val category: String,
    val signs: List<String>,
    val explanation: String? = null,
    val recommendation: String? = null,
    val detection_confidence: Double? = null,
    val assessment_confidence: Double? = null,
    val analyzed_at: String? = null,
    val disclaimer: String? = null,
    val note: String? = null
)
