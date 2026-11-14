package ru.kst.deffector

import android.os.SystemClock
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlin.math.roundToInt

@Composable
fun ArScreen(vm: AppState) {
    val tracker = remember { DetectionTracker() }
    var tracks by remember { mutableStateOf<List<DetectionTrack>>(emptyList()) }
    var area by remember { mutableStateOf(IntSize.Zero) }
    var expanded by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(false) }
    val snapshot = vm.frame
    val density = LocalDensity.current
    val fontScale = density.fontScale.coerceAtLeast(1f)
    val labelHeight = with(density) { (92.dp * fontScale).toPx() }
    val headerHeight = with(density) { (94.dp * fontScale).toPx() }
    val capacity = ((area.height - headerHeight) / labelHeight).toInt().coerceIn(0, 3)
    LaunchedEffect(snapshot) {
        if (snapshot != null) tracks = tracker.update(snapshot.result.detections, snapshot.at, snapshot.bitmap.width, snapshot.bitmap.height)
    }
    LaunchedEffect(vm.selected, snapshot) {
        if (vm.selected == null) while (true) {
            delay(100)
            tracks = tracker.advance(SystemClock.elapsedRealtime())
        }
    }
    Column(Modifier.fillMaxSize()) {
        Box(Modifier.weight(1f).fillMaxWidth().background(Color.Black).onSizeChanged { area = it }) {
            CameraFeed(Modifier.fillMaxSize(), vm::onFrame, vm::cameraFailed)
            CameraHeading("Осмотр узлов", "Нажмите на метку, чтобы открыть анализ")
            tracks.forEachIndexed { index, track -> key(track.key) {
                val target = previewBox(track.box, track.width, track.height, area.width.toFloat(), area.height.toFloat())
                val left by animateFloatAsState(target.left, tween(420), label = "left")
                val top by animateFloatAsState(target.top, tween(420), label = "top")
                val right by animateFloatAsState(target.right, tween(420), label = "right")
                val bottom by animateFloatAsState(target.bottom, tween(420), label = "bottom")
                val alpha by animateFloatAsState(if (track.visible) 1f else 0f, tween(ArTiming.FADE_MS.toInt()), label = "fade")
                val color = when (track.detection.attention_level) {
                    "check" -> Color(0xFFFFD36D)
                    "defect" -> Color(0xFFFF7D8C)
                    "none" -> Mint
                    else -> Color(0xFFCBDBE2)
                }
                val selectable = track.visible && track.missingSince == null && track.seen == snapshot?.at && !vm.busy
                Canvas(Modifier.fillMaxSize().graphicsLayer { this.alpha = alpha }) {
                    val boxSize = Size((right - left).coerceAtLeast(1f), (bottom - top).coerceAtLeast(1f))
                    drawRoundRect(color.copy(alpha = .07f), Offset(left, top), boxSize, CornerRadius(10.dp.toPx()))
                    drawRoundRect(color.copy(alpha = .6f), Offset(left, top), boxSize, CornerRadius(10.dp.toPx()), style = Stroke(1.dp.toPx()))
                    val length = minOf(20.dp.toPx(), boxSize.width / 3, boxSize.height / 3)
                    listOf(Offset(left, top), Offset(right, top), Offset(left, bottom), Offset(right, bottom)).forEachIndexed { i, p ->
                        drawLine(color, p, p + Offset(if (i % 2 == 0) length else -length, 0f), 3.dp.toPx())
                        drawLine(color, p, p + Offset(0f, if (i < 2) length else -length), 3.dp.toPx())
                    }
                    if (index < capacity) drawLine(color.copy(alpha = .35f), Offset(left, top),
                        Offset(20.dp.toPx(), headerHeight + index * labelHeight + 12.dp.toPx()), 1.dp.toPx())
                }
                Box(Modifier.offset { IntOffset(left.roundToInt(), top.roundToInt()) }
                    .size(with(density) { (right - left).coerceAtLeast(1f).toDp() }, with(density) { (bottom - top).coerceAtLeast(1f).toDp() })
                    .semantics { contentDescription = track.detection.label + ", " + percent(track.detection.detection_confidence) }
                    .clickable(enabled = selectable) { vm.choose(track.detection, snapshot) })
                if (index < capacity) Surface(color = CameraGlass, shape = RoundedCornerShape(14.dp),
                    border = BorderStroke(1.dp, color.copy(alpha = .5f)),
                    modifier = Modifier.offset { IntOffset(16.dp.roundToPx(), (headerHeight + index * labelHeight).roundToInt()) }
                        .widthIn(max = 224.dp).fillMaxWidth(.62f).height(86.dp * fontScale).graphicsLayer { this.alpha = alpha }
                        .clickable(enabled = selectable) { vm.choose(track.detection, snapshot) }) {
                    Column(Modifier.padding(horizontal = 12.dp, vertical = 9.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text("${symbol(track.detection.attention_level)} ${track.detection.label} · ${percent(track.detection.detection_confidence)}",
                            color = color, style = MaterialTheme.typography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(track.detection.reason.orEmpty(), color = Color.White, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(track.detection.recommended_action.orEmpty(), color = Color(0xFFC0D5DF), style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
            } }
            if (tracks.none { it.visible }) Surface(color = CameraGlass, shape = RoundedCornerShape(14.dp),
                modifier = Modifier.align(Alignment.BottomCenter).padding(16.dp)) {
                Text(if (snapshot == null) "Ищем узлы в кадре…" else "Измените ракурс или подойдите ближе",
                    color = Color.White, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(14.dp))
            }
        }
        Surface(shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp), color = MaterialTheme.colorScheme.surface) {
            Column(Modifier.fillMaxWidth().heightIn(max = if (expanded) 340.dp else 210.dp)
                .verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Требуют проверки", style = MaterialTheme.typography.titleMedium)
                    TextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "Свернуть" else "Все · ${vm.attention.size}") }
                }
                vm.cameraError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                if (vm.attention.isEmpty()) Text("Узлов, требующих проверки, нет", color = MaterialTheme.colorScheme.onSurfaceVariant)
                vm.attention.forEach { a ->
                    val color = statusColor(a.level)
                    Surface(shape = RoundedCornerShape(16.dp), color = color.copy(alpha = .045f), border = BorderStroke(1.dp, color.copy(alpha = .2f))) {
                        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("${symbol(a.level)} ${a.name}", color = color, style = MaterialTheme.typography.titleMedium)
                            a.reasons.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                            Text(a.hint, style = MaterialTheme.typography.bodyMedium)
                            Text(a.recommended_action, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            if (a.component_id in snapshot?.result?.not_in_frame.orEmpty()) StatusPill("Не в кадре", MaterialTheme.colorScheme.onSurfaceVariant)
                            if (!a.detectable) Text("Автоматическое распознавание этого типа недоступно", style = MaterialTheme.typography.bodySmall)
                            TextButton(enabled = !vm.busy, onClick = { vm.openComponent(a.component_id) }) { Text("Карточка узла  →") }
                        }
                    }
                }
                if (tracks.size > capacity) {
                    Text("Распознанные узлы", style = MaterialTheme.typography.titleMedium)
                    tracks.filter { it.visible && it.missingSince == null }.forEach { t ->
                        TextButton(onClick = { vm.choose(t.detection, snapshot) }, enabled = !vm.busy && t.seen == snapshot?.at) {
                            Text("${symbol(t.detection.attention_level)} ${t.detection.label} · ${percent(t.detection.detection_confidence)}")
                        }
                    }
                }
            }
        }
    }
    vm.selected?.let { d ->
        AlertDialog(onDismissRequest = { if (!vm.busy) vm.clearSelection() }, title = { Text(d.label) }, text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                StatusPill("Уверенность распознавания: ${percent(d.detection_confidence)}", Teal)
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
                        Action("Анализировать", !vm.busy, vm::analyze)
                        SecondaryAction("Открыть карточку", !vm.busy) { d.component_id?.let(vm::openComponent) }
                    }
                }
                if (vm.busy) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Анализ выполняется. Он может занять более 20 секунд.") }
                vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error); TextButton(enabled = !vm.busy, onClick = vm::repeat) { Text("Повторить") } }
            }
        }, confirmButton = { TextButton(enabled = !vm.busy, onClick = vm::clearSelection) { Text("Закрыть") } })
    }
}
