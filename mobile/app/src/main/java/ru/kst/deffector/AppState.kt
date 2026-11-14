package ru.kst.deffector

import android.app.Application
import android.graphics.Bitmap
import androidx.compose.runtime.*
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.coroutines.*
import kotlinx.coroutines.tasks.await
import okhttp3.RequestBody.Companion.toRequestBody

enum class Screen { CAMERA, LIST, EQUIPMENT, AR, COMPONENT, INSPECTION, SETTINGS }
data class Candidate(val id: String, val name: String, val confidence: Double?)
data class DetectionFrame(val result: DetectResult, val bitmap: Bitmap)

class AppState(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("settings", 0)
    var server by mutableStateOf(prefs.getString("server", "").orEmpty()); private set
    var engineer by mutableStateOf(prefs.getString("engineer", "").orEmpty()); private set
    private var api: Api? = server.takeIf { it.isNotBlank() }?.let { runCatching { Network.create(it) }.getOrNull() }
    var screen by mutableStateOf(Screen.CAMERA); private set
    var card by mutableStateOf<EquipmentCard?>(null); private set
    var component by mutableStateOf<Component?>(null); private set
    var items by mutableStateOf<List<EquipmentShort>>(emptyList()); private set
    var attention by mutableStateOf<List<AttentionItem>>(emptyList()); private set
    var frame by mutableStateOf<DetectionFrame?>(null); private set
    var selected by mutableStateOf<Detection?>(null); private set
    private var selectedFrame: DetectionFrame? = null
    var candidates by mutableStateOf<List<Candidate>>(emptyList()); private set
    var busy by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null); private set
    var notice by mutableStateOf<String?>(null); private set
    var cameraError by mutableStateOf<String?>(null); private set
    var manualHint by mutableStateOf(false); private set
    private var latest: Bitmap? = null
    private var retry: (() -> Unit)? = null
    private var settingsReturn = Screen.CAMERA
    private var lastScan = 0L
    private var lastDetect = 0L
    private val seen = mutableMapOf<String, Long>()
    private val qr = BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
    private val text = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
    private fun service() = api ?: throw IllegalStateException("Укажите адрес ПК в настройках")

    fun go(next: Screen) {
        if (next == Screen.SETTINGS) settingsReturn = screen
        screen = next; error = null; notice = null; cameraError = null; clearSelection(); frame = null; latest = null
        if (next == Screen.CAMERA) { manualHint = false; seen.clear() }
    }
    fun back() = go(when (screen) {
        Screen.COMPONENT -> Screen.EQUIPMENT
        Screen.INSPECTION -> if (component != null) Screen.COMPONENT else Screen.EQUIPMENT
        Screen.AR -> Screen.EQUIPMENT
        Screen.SETTINGS -> settingsReturn
        else -> Screen.CAMERA
    })
    fun cameraFailed(message: String) { cameraError = message }
    fun suggestManual() { manualHint = true }
    fun repeat() { error = null; retry?.invoke() }
    private fun task(allowRetry: Boolean = true, action: suspend () -> Unit) {
        if (busy) return
        retry = if (allowRetry) { { task(action = action) } } else null
        viewModelScope.launch {
            busy = true; error = null; notice = null
            try { action() } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                error = Network.message(e)
                if (!allowRetry) {
                    error += " Проверьте историю перед повторной записью: осмотр мог сохраниться."
                    retry = { refresh() }
                }
            }
            finally { busy = false }
        }
    }
    fun saveSettings(url: String, name: String) = task {
        val checked = Network.address(url).toString().trimEnd('/')
        if (checked != server) { card = null; component = null; settingsReturn = Screen.CAMERA }
        api = Network.create(checked); server = checked; engineer = name.trim()
        prefs.edit().putString("server", server).putString("engineer", engineer).apply()
        notice = "Настройки сохранены"
    }
    fun health() = task {
        val h = service().health()
        notice = "Бэкенд: ${h.status}. ИИ: ${h.ai.status}, режим ${h.ai.mode}. ${h.time}"
    }
    fun search(q: String) = task { items = service().list(q).items }
    fun manual() { go(Screen.LIST); search("") }
    fun lookup(value: String, mode: String) = task { find(value.trim(), mode) }
    private suspend fun find(value: String, mode: String): Boolean {
        if (value.isBlank()) return false
        val r = when (mode) {
            "qr" -> service().lookup(qr = value)
            "serial" -> service().lookup(serial = value)
            else -> service().lookup(marking = value)
        }
        if (r.found && r.equipment_id != null) {
            val found = service().card(r.equipment_id)
            candidates = listOf(Candidate(found.id, found.name, r.match_confidence))
        } else {
            candidates = r.suggestions.orEmpty().map { Candidate(it.equipment_id, it.name, it.score) }
            manualHint = true
        }
        return r.found
    }
    fun dismissCandidates() { candidates = emptyList(); manualHint = true }
    fun openEquipment(id: String) = task {
        val c = service().card(id)
        candidates = emptyList(); card = c; component = null; go(Screen.EQUIPMENT)
    }
    fun refresh() = task {
        card = service().card(requireNotNull(card).id)
        component?.let { component = service().component(requireNotNull(card).id, it.id) }
        if (screen == Screen.INSPECTION) go(Screen.EQUIPMENT)
    }
    fun openComponent(id: String) = task {
        component = service().component(requireNotNull(card).id, id); go(Screen.COMPONENT)
    }
    fun openAr() = task {
        attention = service().attention(requireNotNull(card).id).items; go(Screen.AR)
    }
    fun choose(d: Detection, source: DetectionFrame) {
        selectedFrame = source
        selected = d
    }
    fun clearSelection() {
        selected = null
        selectedFrame = null
    }
    fun selectCandidate(id: String) { selected = selected?.copy(component_id = id, match = "matched") }
    fun identify() = task {
        val image = latest ?: throw IllegalStateException("Дождитесь изображения с камеры")
        val result = service().identify(Network.image(withContext(Dispatchers.Default) { jpeg(image) }))
        candidates = result.candidates.map { Candidate(it.equipment_id, it.name, it.confidence) }
        if (!result.recognized || candidates.isEmpty()) manualHint = true
    }

    // Вызывается последовательно анализатором CameraX. Bitmap уже обрезан и повёрнут.
    suspend fun onFrame(bitmap: Bitmap) {
        latest = bitmap
        val now = android.os.SystemClock.elapsedRealtime()
        if (busy || selected != null || candidates.isNotEmpty() || api == null) return
        if (screen == Screen.AR && now - lastDetect > 180 && error == null) {
            lastDetect = now
            try {
                val image = withContext(Dispatchers.Default) { jpeg(resize(bitmap, 640)) }
                val result = service().detect(requireNotNull(card).id, Network.image(image))
                if (screen == Screen.AR && selected == null) frame = DetectionFrame(result, bitmap)
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (screen == Screen.AR && selected == null) {
                    frame = null
                    error = Network.message(e)
                    retry = { error = null }
                }
            }
        } else if (screen == Screen.CAMERA && now - lastScan > 1100 && error == null) {
            lastScan = now
            try {
                val input = InputImage.fromBitmap(bitmap, 0)
                val code = qr.process(input).await().firstOrNull()?.rawValue
                if (code != null && shouldLookup("qr:$code", now)) { find(code, "qr"); return }
                val lines = text.process(input).await().textBlocks.flatMap { it.lines }.map { it.text.trim() }
                    .filter { it.length in 4..80 && it.any(Char::isDigit) }.take(4)
                for (line in lines) {
                    if (screen != Screen.CAMERA || candidates.isNotEmpty()) break
                    if (shouldLookup(line, now)) {
                        val clean = line.replace(Regex("(?i)^(S/N|SN:|SERIAL:|MARKING:)\\s*"), "")
                        if (!find(clean, "serial")) find(clean, "marking")
                    }
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { error = Network.message(e); retry = { error = null; seen.clear() } }
        }
    }
    private fun shouldLookup(key: String, now: Long): Boolean {
        val old = seen[key]; seen[key] = now
        return old == null || now - old > 8000
    }
    fun analyze() = task {
        val d = selected ?: throw IllegalStateException("Выберите рамку узла")
        val snapshot = selectedFrame ?: throw IllegalStateException("Дождитесь распознавания узла")
        val id = d.component_id ?: throw IllegalStateException("Сначала выберите узел из карточки")
        val image = withContext(Dispatchers.Default) { jpeg(crop(snapshot.bitmap, d.bbox)) }
        component = service().analyze(requireNotNull(card).id, id, Network.image(image),
            d.detection_confidence.toString().toRequestBody())
        card = service().card(requireNotNull(card).id)
        go(Screen.COMPONENT)
    }
    fun inspection(whole: Boolean = false) { if (whole) component = null; go(Screen.INSPECTION) }
    fun submit(type: String, comment: String, attach: Boolean) = task(allowRetry = false) {
        require(engineer.isNotBlank()) { "Укажите имя инженера в настройках" }
        require(type !in listOf("defect", "remark") || comment.isNotBlank()) { "Для дефекта и замечания нужен комментарий" }
        val eq = requireNotNull(card).id
        val result = service().inspect(eq, InspectionIn(component?.id, type, comment.trim().ifBlank { null }, engineer, attach))
        component = result.component
        card = service().card(eq).copy(history = service().history(eq).items)
        go(if (component != null) Screen.COMPONENT else Screen.EQUIPMENT)
        notice = "Осмотр сохранён"
    }
    override fun onCleared() { qr.close(); text.close(); super.onCleared() }
}
