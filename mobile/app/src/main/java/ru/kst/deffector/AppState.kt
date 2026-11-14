package ru.kst.deffector

import android.app.Application
import android.graphics.Bitmap
import android.net.Uri
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

enum class Screen { CAMERA, LIST, EQUIPMENT, AR, COMPONENT, INSPECTION, SETTINGS, LOGIN }
data class SavedReport(val uri: Uri, val mime: String)
data class Candidate(val id: String, val name: String, val confidence: Double?)
data class DetectionFrame(val result: DetectResult, val bitmap: Bitmap, val at: Long = android.os.SystemClock.elapsedRealtime())

class AppState(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("settings", 0)
    var server by mutableStateOf(prefs.getString("server", "").orEmpty()); private set
    // Вход: токен и учётная запись хранятся в настройках приложения до выхода или истечения срока.
    private var token: String? = prefs.getString("token", null)
    var user by mutableStateOf(prefs.getString("user", null)?.let { saved ->
        runCatching { Network.json.decodeFromString(User.serializer(), saved) }.getOrNull()
    }?.takeIf { token != null }); private set
    val engineer: String get() = user?.name.orEmpty()
    fun can(permission: String) = user?.permissions?.contains(permission) == true
    private var api: Api? = server.takeIf { it.isNotBlank() }?.let { runCatching { Network.create(it) { token } }.getOrNull() }
    var screen by mutableStateOf(if (user == null) Screen.LOGIN else Screen.CAMERA); private set
    var savedReport by mutableStateOf<SavedReport?>(null); private set
    var card by mutableStateOf<EquipmentCard?>(null); private set
    var component by mutableStateOf<Component?>(null); private set
    var items by mutableStateOf<List<EquipmentShort>>(emptyList()); private set
    var attention by mutableStateOf<List<AttentionItem>>(emptyList()); private set
    var frame by mutableStateOf<DetectionFrame?>(null); private set
    var selected by mutableStateOf<Detection?>(null); private set
    var candidates by mutableStateOf<List<Candidate>>(emptyList()); private set
    var busy by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null); private set
    var notice by mutableStateOf<String?>(null); private set
    var cameraError by mutableStateOf<String?>(null); private set
    var manualHint by mutableStateOf(false); private set
    private var recognitionSeen = false
    private var latest: Bitmap? = null
    private var selectedFrame: DetectionFrame? = null
    private var retry: (() -> Unit)? = null
    private var settingsReturn = Screen.CAMERA
    private var lastScan = 0L
    private var lastDetect = 0L
    private val seen = mutableMapOf<String, Long>()
    private val qr = BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
    private val text = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
    private fun service() = api ?: throw IllegalStateException("Укажите адрес ПК в настройках")

    fun go(target: Screen) {
        // Без входа доступны только экран входа и настройки подключения.
        val next = if (user == null && target != Screen.SETTINGS) Screen.LOGIN else target
        if (next == Screen.SETTINGS) settingsReturn = screen
        screen = next; error = null; notice = null; cameraError = null; selected = null; selectedFrame = null; frame = null; latest = null
        savedReport = null
        manualHint = false; recognitionSeen = false
        if (next == Screen.CAMERA) seen.clear()
    }
    fun back() = go(when (screen) {
        Screen.COMPONENT -> Screen.EQUIPMENT
        Screen.INSPECTION -> if (component != null) Screen.COMPONENT else Screen.EQUIPMENT
        Screen.AR -> Screen.EQUIPMENT
        Screen.SETTINGS -> settingsReturn
        else -> Screen.CAMERA
    })
    fun cameraFailed(message: String) { cameraError = message }
    fun suggestManual() {
        if (screen in listOf(Screen.CAMERA, Screen.AR) && !recognitionSeen && candidates.isEmpty()) manualHint = true
    }
    private fun recognitionFound() { recognitionSeen = true; manualHint = false }
    fun repeat() { error = null; retry?.invoke() }
    private fun task(allowRetry: Boolean = true, action: suspend () -> Unit) {
        if (busy) return
        retry = if (allowRetry) { { task(action = action) } } else null
        viewModelScope.launch {
            busy = true; error = null; notice = null
            try { action() } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (expired(e)) return@launch
                error = Network.message(e)
                if (!allowRetry) {
                    error += " Проверьте историю перед повторной записью: осмотр мог сохраниться."
                    retry = { refresh() }
                }
            }
            finally { busy = false }
        }
    }
    // Сервер ответил 401 при действующем входе: вход истёк или завершён — нужен новый.
    private fun expired(e: Exception): Boolean {
        if (!Network.unauthorized(e) || user == null) return false
        signOut(Network.message(e))
        return true
    }
    private fun forgetSession() {
        token = null; user = null; card = null; component = null
        prefs.edit().remove("token").remove("user").apply()
    }
    private fun signOut(message: String?) {
        forgetSession(); settingsReturn = Screen.LOGIN
        go(Screen.LOGIN); error = message; retry = { error = null }
    }
    fun login(email: String, password: String) = task {
        val result = service().login(LoginIn(email.trim(), password))
        token = result.token; user = result.user
        prefs.edit().putString("token", result.token)
            .putString("user", Network.json.encodeToString(User.serializer(), result.user)).apply()
        go(Screen.CAMERA)
        notice = "Вход выполнен: ${result.user.name}, ${result.user.role_name}"
    }
    fun logout() {
        val service = api; val bearer = token
        // Сервер завершает вход; без связи он истечёт сам по сроку.
        if (service != null && bearer != null) viewModelScope.launch { runCatching { service.logout("Bearer $bearer") } }
        signOut(null)
    }
    fun saveSettings(url: String) = task {
        val checked = Network.address(url).toString().trimEnd('/')
        val changed = checked != server
        api = Network.create(checked) { token }; server = checked
        prefs.edit().putString("server", server).apply()
        // Вход действует только на том сервере, где он выполнен.
        if (changed) { forgetSession(); settingsReturn = Screen.LOGIN }
        notice = if (changed) "Настройки сохранены. Войдите в систему" else "Настройки сохранены"
    }
    fun saveReport(uri: Uri, format: String) = task {
        val id = requireNotNull(card).id
        val bytes = withContext(Dispatchers.IO) { service().report(id, format).use { it.bytes() } }
        withContext(Dispatchers.IO) {
            val output = getApplication<Application>().contentResolver.openOutputStream(uri)
                ?: throw IllegalStateException("Не удалось открыть файл для записи")
            output.use { it.write(bytes) }
        }
        savedReport = SavedReport(uri, if (format == "pdf") "application/pdf" else Network.XLSX)
        notice = "Отчёт сохранён"
    }
    fun reportNotOpened() { notice = "Отчёт сохранён, но на телефоне нет приложения для его просмотра" }
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
            recognitionFound()
            val found = service().card(r.equipment_id)
            candidates = listOf(Candidate(found.id, found.name, r.match_confidence))
        } else {
            candidates = r.suggestions.orEmpty().map { Candidate(it.equipment_id, it.name, it.score) }
            if (candidates.isNotEmpty()) recognitionFound() else suggestManual()
        }
        return r.found
    }
    fun dismissCandidates() { candidates = emptyList(); suggestManual() }
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
    fun choose(d: Detection, source: DetectionFrame? = frame) {
        if (source == null || busy) return
        selectedFrame = source
        selected = d
    }
    fun clearSelection() { selected = null; selectedFrame = null }
    fun selectCandidate(id: String) { selected = selected?.copy(component_id = id, match = "matched") }
    fun identify() = task {
        val image = latest ?: throw IllegalStateException("Дождитесь изображения с камеры")
        val result = service().identify(Network.image(withContext(Dispatchers.Default) { jpeg(image) }))
        candidates = result.candidates.map { Candidate(it.equipment_id, it.name, it.confidence) }
        if (candidates.isNotEmpty()) recognitionFound() else suggestManual()
    }

    // Вызывается последовательно анализатором CameraX. Bitmap уже обрезан и повёрнут.
    suspend fun onFrame(bitmap: Bitmap) {
        latest = bitmap
        val now = android.os.SystemClock.elapsedRealtime()
        if (busy || selected != null || candidates.isNotEmpty() || api == null) return
        if (screen == Screen.AR && now - lastDetect >= ArTiming.DETECT_INTERVAL_MS && error == null) {
            lastDetect = now
            val equipmentId = requireNotNull(card).id
            try {
                val image = withContext(Dispatchers.Default) { jpeg(resize(bitmap, 640)) }
                val result = service().detect(equipmentId, Network.image(image))
                if (screen == Screen.AR && selected == null && !busy && card?.id == equipmentId) {
                    frame = DetectionFrame(result, bitmap)
                    if (result.detections.isNotEmpty()) recognitionFound()
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (expired(e)) return
                if (screen == Screen.AR && selected == null && !busy && card?.id == equipmentId) {
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
                if (!code.isNullOrBlank()) recognitionFound()
                if (code != null && shouldLookup("qr:$code", now)) { find(code, "qr"); return }
                val lines = text.process(input).await().textBlocks.flatMap { it.lines }.map { it.text.trim() }
                    .filter { it.length in 4..80 && it.any(Char::isDigit) }.take(4)
                if (lines.isNotEmpty()) recognitionFound()
                for (line in lines) {
                    if (screen != Screen.CAMERA || candidates.isNotEmpty()) break
                    if (shouldLookup(line, now)) {
                        val clean = line.replace(Regex("(?i)^(S/N|SN:|SERIAL:|MARKING:)\\s*"), "")
                        if (!find(clean, "serial")) find(clean, "marking")
                    }
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { if (!expired(e)) { error = Network.message(e); retry = { error = null; seen.clear() } } }
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
        require(can("inspect")) { "Для записи осмотра нужна роль инженера или мастера" }
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
