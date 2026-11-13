package ru.kst.deffector

import android.os.SystemClock
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlin.math.roundToInt

private data class Track(val key: String, val detection: Detection, val seen: Long, val w: Int, val h: Int, val visible: Boolean = true)

@Composable
fun ArScreen(vm: AppState) {
    var tracks by remember { mutableStateOf<List<Track>>(emptyList()) }
    var area by remember { mutableStateOf(IntSize.Zero) }
    val snapshot = vm.frame
    LaunchedEffect(snapshot) {
        if (snapshot == null) { tracks = emptyList(); return@LaunchedEffect }
        val occurrences = mutableMapOf<String, Int>()
        val incoming = snapshot.result.detections.filter { runCatching { normalizedBox(it.bbox) }.isSuccess }.map { d ->
            val base = d.component_id ?: d.cv_class
            val i = occurrences.getOrDefault(base, 0); occurrences[base] = i + 1
            Track("$base:$i", d, snapshot.at, snapshot.bitmap.width, snapshot.bitmap.height)
        }
        val absent = tracks.filter { old -> incoming.none { it.key == old.key } }.map { it.copy(visible = false) }
        tracks = incoming + absent
        delay(500)
        tracks = tracks.filter { it.visible }
    }
    // Даже при зависшем запросе старые рамки не остаются на движущемся изображении.
    LaunchedEffect(snapshot, vm.selected) {
        if (snapshot != null && vm.selected == null) {
            delay(1500)
            tracks = tracks.map { it.copy(visible = false) }
            delay(500); tracks = emptyList()
        }
    }
    Column(Modifier.fillMaxSize()) {
        Box(Modifier.weight(1f).fillMaxWidth().background(Color.Black).onSizeChanged { area = it }) {
            CameraFeed(Modifier.fillMaxSize(), vm::onFrame, vm::cameraFailed)
            val density = LocalDensity.current
            val labelHeight = with(density) { 98.dp.toPx() }
            val capacity = (area.height / labelHeight).toInt().coerceAtLeast(1)
            tracks.forEachIndexed { index, track -> key(track.key) {
                val target = previewBox(track.detection.bbox, track.w, track.h, area.width.toFloat(), area.height.toFloat())
                val left by animateFloatAsState(target.left, tween(160), label = "left")
                val top by animateFloatAsState(target.top, tween(160), label = "top")
                val right by animateFloatAsState(target.right, tween(160), label = "right")
                val bottom by animateFloatAsState(target.bottom, tween(160), label = "bottom")
                val alpha by animateFloatAsState(if (track.visible) 1f else 0f, tween(500), label = "fade")
                val color = if (track.detection.attention_level == "check") Color(0xFFFFC107) else statusColor(track.detection.attention_level)
                Canvas(Modifier.fillMaxSize().graphicsLayer { this.alpha = alpha }) {
                    drawRect(color, Offset(left, top), Size((right - left).coerceAtLeast(1f), (bottom - top).coerceAtLeast(1f)), style = Stroke(3.dp.toPx()))
                    if (index < capacity) drawLine(color, Offset(left, top), Offset(8.dp.toPx(), index * labelHeight + 10.dp.toPx()), 1.dp.toPx())
                }
                Box(Modifier.offset { IntOffset(left.roundToInt(), top.roundToInt()) }
                    .size(with(density) { (right - left).coerceAtLeast(1f).toDp() }, with(density) { (bottom - top).coerceAtLeast(1f).toDp() })
                    .clickable(enabled = track.visible && !vm.busy) { vm.choose(track.detection) })
                if (index < capacity) Surface(color = Color(0xEA11272B), shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.offset { IntOffset(8.dp.roundToPx(), (index * labelHeight).roundToInt()) }
                        .width(244.dp).height(94.dp).graphicsLayer { this.alpha = alpha }
                        .border(1.dp, color, RoundedCornerShape(8.dp))
                        .clickable(enabled = track.visible && !vm.busy) { vm.choose(track.detection) }) {
                    Column(Modifier.padding(8.dp)) {
                        Text("${symbol(track.detection.attention_level)} ${track.detection.label} · ${percent(track.detection.detection_confidence)}", color = Color.White,
                            style = MaterialTheme.typography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(track.detection.reason.orEmpty(), color = Color.White, style = MaterialTheme.typography.labelMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(track.detection.recommended_action.orEmpty(), color = Color(0xFFB2E1E1), style = MaterialTheme.typography.labelMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
            } }
            if (snapshot?.result?.detections?.isEmpty() == true) Text("Узлы не найдены. Измените ракурс или подойдите ближе.",
                color = Color.White, modifier = Modifier.background(Color.Black.copy(alpha = .7f)).padding(12.dp))
        }
        Column(Modifier.fillMaxWidth().heightIn(max = 250.dp).verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            vm.cameraError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (snapshot == null && vm.error == null) Text("Ожидание распознавания узлов…")
            if (tracks.size > (area.height / with(LocalDensity.current) { 98.dp.toPx() }).toInt()) {
                Text("Распознанные узлы")
                tracks.filter { it.visible }.forEach { t -> TextButton(onClick = { vm.choose(t.detection) }, enabled = !vm.busy) { Text("${symbol(t.detection.attention_level)} ${t.detection.label}") } }
            }
            Text("Требуют проверки", style = MaterialTheme.typography.titleMedium)
            if (vm.attention.isEmpty()) Text("Узлов, требующих проверки, нет")
            vm.attention.forEach { a ->
                Column(Modifier.fillMaxWidth().border(1.dp, statusColor(a.level), RoundedCornerShape(8.dp)).padding(10.dp)) {
                    Text("${symbol(a.level)} ${a.name}", color = statusColor(a.level))
                    a.reasons.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                    Text(a.hint); Text(a.recommended_action, style = MaterialTheme.typography.bodySmall)
                    if (a.component_id in snapshot?.result?.not_in_frame.orEmpty()) Text("Не в кадре")
                    if (!a.detectable) Text("Автоматическое распознавание этого типа недоступно")
                    TextButton(enabled = !vm.busy, onClick = { vm.openComponent(a.component_id) }) { Text("Карточка узла") }
                }
            }
        }
    }
    vm.selected?.let { d ->
        AlertDialog(onDismissRequest = { if (!vm.busy) vm.clearSelection() }, title = { Text(d.label) }, text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Уверенность распознавания: ${percent(d.detection_confidence)}")
                d.reason?.let { Text(it) }; d.recommended_action?.let { Text(it) }
                vm.card?.components?.find { it.id == d.component_id }?.let { c ->
                    Text(c.resource.message, color = statusColor(c.resource.status))
                    Text(visualLabel(d.visual_category ?: c.visual.category))
                }
                when (d.match) {
                    "not_in_card" -> Text("узел не найден в карточке оборудования")
                    "ambiguous" -> {
                        Text("Уточните узел из карточки оборудования")
                        d.candidates.orEmpty().forEach { id ->
                            TextButton(enabled = !vm.busy, onClick = { vm.selectCandidate(id) }) { Text(vm.card?.components?.find { it.id == id }?.name ?: id) }
                        }
                    }
                    else -> {
                        Action("Открыть карточку", !vm.busy) { d.component_id?.let(vm::openComponent) }
                        Action("Анализировать", !vm.busy, vm::analyze)
                    }
                }
                if (vm.busy) { CircularProgressIndicator(); Text("Анализ выполняется. Он может занять более 20 секунд.") }
                vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error); TextButton(enabled = !vm.busy, onClick = vm::repeat) { Text("Повторить") } }
            }
        }, confirmButton = { TextButton(enabled = !vm.busy, onClick = vm::clearSelection) { Text("Закрыть") } })
    }
}
