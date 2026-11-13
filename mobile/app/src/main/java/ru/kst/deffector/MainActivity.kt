package ru.kst.deffector

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.BackHandler
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.delay

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Color(0xFF075F65), secondary = Color(0xFF48666A),
                background = Color(0xFFF3F6F6), surface = Color.White)) {
                App(viewModel())
            }
        }
    }
}

fun statusColor(level: String) = when (level) {
    "defect", "due", "possible_defect", "deviation" -> Color(0xFFBD2435)
    "check", "approaching", "check_recommended" -> Color(0xFF956200)
    "none", "ok", "no_visible_issues", "normal" -> Color(0xFF087443)
    else -> Color(0xFF626F7E)
}
fun symbol(level: String) = when (level) { "defect" -> "✕"; "check" -> "!"; "none" -> "✓"; else -> "?" }
val inspectionTypes = linkedMapOf("checked" to "Компонент проверен", "defect" to "Обнаружен дефект", "remark" to "Замечание",
    "maintenance" to "Обслуживание", "replacement" to "Замена")
fun visualLabel(category: String) = when (category) {
    "no_visible_issues" -> "видимых проблем не обнаружено"
    "check_recommended" -> "рекомендуется проверка"
    "possible_defect" -> "обнаружены признаки возможного дефекта"
    else -> "Визуальный анализ не проводился"
}
fun percent(value: Double?) = value?.let { "${(it * 100).toInt()} %" } ?: "нет данных"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App(vm: AppState) {
    BackHandler(vm.screen != Screen.CAMERA && !vm.busy) { vm.back() }
    val view = LocalView.current
    DisposableEffect(vm.screen) {
        view.keepScreenOn = vm.screen in listOf(Screen.CAMERA, Screen.AR)
        onDispose { view.keepScreenOn = false }
    }
    Scaffold(topBar = {
        TopAppBar(title = { Text(when (vm.screen) {
            Screen.CAMERA -> "Деффектор · идентификация"; Screen.LIST -> "Выбор оборудования"
            Screen.EQUIPMENT -> vm.card?.id ?: "Оборудование"; Screen.AR -> "AR-осмотр"
            Screen.COMPONENT -> "Карточка узла"; Screen.INSPECTION -> "Регистрация осмотра"; Screen.SETTINGS -> "Настройки"
        }, style = MaterialTheme.typography.titleMedium) }, navigationIcon = {
            if (vm.screen != Screen.CAMERA) TextButton(enabled = !vm.busy, onClick = vm::back) { Text("Назад") }
        }, actions = { if (vm.screen != Screen.SETTINGS) TextButton(enabled = !vm.busy, onClick = { vm.go(Screen.SETTINGS) }) { Text("Настройки") } })
    }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            if (vm.busy) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
                Text("Выполняется запрос…", Modifier.padding(horizontal = 16.dp), style = MaterialTheme.typography.labelMedium)
            }
            vm.error?.let { message ->
                Surface(color = MaterialTheme.colorScheme.errorContainer) {
                    Column(Modifier.fillMaxWidth().padding(12.dp)) {
                        Text(message)
                        TextButton(enabled = !vm.busy, onClick = vm::repeat) { Text("Повторить") }
                    }
                }
            }
            vm.notice?.let { Text(it, Modifier.padding(12.dp), color = MaterialTheme.colorScheme.primary) }
            when (vm.screen) {
                Screen.CAMERA -> IdentifyScreen(vm)
                Screen.LIST -> ManualScreen(vm)
                Screen.SETTINGS -> SettingsScreen(vm)
                Screen.EQUIPMENT -> EquipmentScreen(vm)
                Screen.COMPONENT -> ComponentScreen(vm)
                Screen.INSPECTION -> InspectionScreen(vm)
                Screen.AR -> ArScreen(vm)
            }
        }
    }
    if (vm.candidates.isNotEmpty()) AlertDialog(onDismissRequest = vm::dismissCandidates,
        title = { Text("Подтвердите оборудование") }, text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                vm.candidates.forEach { candidate ->
                    Text("Это ${candidate.id}, ${candidate.name}?")
                    candidate.confidence?.let { Text("Уверенность: ${percent(it)}") }
                    Button(enabled = !vm.busy, onClick = { vm.openEquipment(candidate.id) }) { Text("Да, открыть") }
                }
            }
        }, confirmButton = {}, dismissButton = { TextButton(enabled = !vm.busy, onClick = { vm.dismissCandidates(); vm.manual() }) { Text("Выбрать другое") } })
}

@Composable fun Action(label: String, enabled: Boolean = true, onClick: () -> Unit) {
    Button(onClick = onClick, enabled = enabled, modifier = Modifier.fillMaxWidth()) { Text(label) }
}
@Composable fun Panel(title: String, content: @Composable ColumnScope.() -> Unit) {
    Surface(shape = RoundedCornerShape(16.dp), tonalElevation = 1.dp, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            content()
        }
    }
}
@Composable fun Page(content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
}
@Composable fun Field(label: String, value: Any?) { Text("$label: ${value ?: "нет данных"}") }

@Composable fun IdentifyScreen(vm: AppState) {
    var number by rememberSaveableInput { "" }
    var mode by rememberSaveableInput { "serial" }
    LaunchedEffect(Unit) { delay(10000); vm.suggestManual() }
    Column(Modifier.fillMaxSize()) {
        Box(Modifier.weight(1f).fillMaxWidth().background(Color.Black)) {
            CameraFeed(Modifier.fillMaxSize(), vm::onFrame, vm::cameraFailed)
            Text("Наведите камеру на QR-код или табличку", color = Color.White,
                modifier = Modifier.align(Alignment.TopCenter).background(Color.Black.copy(alpha = .65f)).padding(12.dp))
        }
        Column(Modifier.heightIn(max = 330.dp).verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            vm.cameraError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (vm.server.isBlank()) Text("Задайте адрес ПК в настройках")
            if (vm.manualHint) Text("Не удалось определить? Выберите оборудование вручную.")
            Action("Выбрать вручную", !vm.busy, vm::manual)
            Action("Определить по фото", !vm.busy && vm.server.isNotBlank(), vm::identify)
            Row {
                FilterChip(selected = mode == "serial", onClick = { mode = "serial" }, label = { Text("Серийный номер") })
                Spacer(Modifier.width(8.dp))
                FilterChip(selected = mode == "marking", onClick = { mode = "marking" }, label = { Text("Маркировка") })
            }
            OutlinedTextField(value = number, onValueChange = { number = it }, label = { Text("Номер с таблички") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
            Action("Найти по номеру", !vm.busy && number.isNotBlank()) { vm.lookup(number, mode) }
        }
    }
}

// Состояние полей сохраняется при повороте и восстановлении Activity.
@Composable fun rememberSaveableInput(init: () -> String) = androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(init()) }

@Composable fun ManualScreen(vm: AppState) {
    var query by rememberSaveableInput { "" }
    Page {
        OutlinedTextField(query, { query = it }, label = { Text("Название, модель или номер") }, modifier = Modifier.fillMaxWidth())
        Action("Найти", !vm.busy) { vm.search(query) }
        if (vm.items.isEmpty() && !vm.busy) Text("Оборудование не найдено")
        vm.items.forEach { item -> Panel("${item.id} · ${item.name}") {
            Field("Модель", item.model); Field("S/N", item.serial_number); Field("Маркировка", item.marking); Field("Расположение", item.location)
            Action("Открыть", !vm.busy) { vm.openEquipment(item.id) }
        } }
    }
}

@Composable fun SettingsScreen(vm: AppState) {
    var url by rememberSaveableInput { vm.server }
    var name by rememberSaveableInput { vm.engineer }
    Page {
        Text("Подключите телефон и ПК к одной локальной сети.")
        OutlinedTextField(url, { url = it }, label = { Text("Адрес ПК") }, placeholder = { Text("http://192.168.1.20:8000") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(name, { name = it }, label = { Text("Имя инженера") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        Action("Сохранить", !vm.busy) { vm.saveSettings(url, name) }
        Action("Проверить связь", !vm.busy && vm.server.isNotBlank(), vm::health)
        Text("Проверка связи использует сохранённый адрес. Интернет для работы не требуется.")
    }
}

@Composable fun Characteristics(items: List<Characteristic>) { items.forEach { Field(it.name, it.value?.let { v -> "$v ${it.unit.orEmpty()}" }) } }
@Composable fun NormativeBlock(n: Normative, usage: Usage) {
    Panel("Нормативный срок службы") {
        Field("Годы", n.life_years); Field("Часы", n.life_hours); Field("Циклы", n.life_cycles)
        Field("Интервал обслуживания, дней", n.maintenance_interval_days)
        Field("Наработка, ч", usage.operating_hours); Field("Рабочие циклы", usage.cycles)
    }
}
@Composable fun ResourceBlock(r: Resource) {
    Panel("Расчётная оценка остаточного ресурса") {
        if (r.status == "insufficient_data") Text("Недостаточно данных для оценки", fontWeight = FontWeight.Bold)
        Text(r.message, color = statusColor(r.status))
        Field("Выработка, %", r.used_percent); Field("Остаток, лет", r.remaining.years)
        Field("Остаток, ч", r.remaining.hours); Field("Остаток, циклов", r.remaining.cycles)
        Field("Ожидаемая дата", r.estimated_end_date); Text(r.basis)
        val names = mapOf("installed_at" to "дата установки", "operating_hours" to "наработка", "cycles" to "число циклов", "last_maintenance_at" to "дата обслуживания", "normative" to "норматив")
        if (r.missing_data.isNotEmpty()) Text("Не хватает: " + r.missing_data.joinToString { names[it] ?: it })
        r.maintenance?.let { Field("Следующее обслуживание", it.next_due_date); it.overdue_days?.let { days -> Field("Просрочка, дней", days) }; it.days_left?.let { days -> Field("До обслуживания, дней", days) } }
    }
}
@Composable fun VisualBlock(v: Visual) {
    Panel("Результат визуального анализа") {
        Text(visualLabel(v.category), color = statusColor(v.category), fontWeight = FontWeight.Bold)
        v.signs.forEach { Text("• $it") }; v.explanation?.let { Text(it) }; v.recommendation?.let { Text(it) }
        Field("Уверенность распознавания", percent(v.detection_confidence))
        Field("Уверенность анализа", percent(v.assessment_confidence)); Field("Время анализа", v.analyzed_at)
        if (v.category != "not_analyzed") Text(v.disclaimer ?: "Предварительный осмотр по изображению. Внутренние неисправности так не определяются")
        if (v.category == "no_visible_issues") Text(v.note ?: "Отсутствие видимых дефектов не подтверждает исправность оборудования")
    }
}
@Composable fun Parameters(items: List<Parameter>) {
    if (items.isEmpty()) Text("Параметры не предоставлены")
    items.forEach { p -> Panel((if (p.status == "deviation") "! " else "") + p.name) {
        Text("${p.value ?: "нет данных"} ${p.unit.orEmpty()}", style = MaterialTheme.typography.titleLarge, color = statusColor(p.status))
        Field("Нижняя уставка", p.setpoint_min); Field("Верхняя уставка", p.setpoint_max)
        Field("Время замера", p.measured_at); Text(p.message, color = statusColor(p.status))
    } }
}
@Composable fun HistoryRows(items: List<HistoryItem>, components: List<Component>) {
    if (items.isEmpty()) Text("Записей пока нет")
    items.sortedByDescending { it.performed_at }.forEach { h -> Panel(inspectionTypes[h.type] ?: h.type) {
        Field("Дата", h.performed_at); Field("Узел", components.find { it.id == h.component_id }?.name ?: h.component_id ?: "Оборудование")
        Field("Комментарий", h.comment); Field("Выполнил", h.performed_by); h.recommendation?.let { Text(it) }
        h.visual?.let { Text(visualLabel(it.category)); it.explanation?.let { e -> Text(e) }; it.recommendation?.let { r -> Text(r) } }
    } }
}

@Composable fun EquipmentScreen(vm: AppState) {
    val c = vm.card ?: return
    var tab by rememberSaveableInput { "Обзор" }
    Column {
        ScrollableTabRow(selectedTabIndex = listOf("Обзор", "Состав", "Параметры", "История").indexOf(tab), edgePadding = 0.dp) {
            listOf("Обзор", "Состав", "Параметры", "История").forEach { title -> Tab(selected = tab == title, onClick = { tab = title }, text = { Text(title + if (title == "Параметры" && c.deviations_count > 0) " (${c.deviations_count})" else "") }) }
        }
        Page {
            when (tab) {
                "Обзор" -> {
                    Text(c.name, style = MaterialTheme.typography.headlineSmall)
                    if (c.deviations_count > 0) Text("! Параметров с отклонениями: ${c.deviations_count}", color = statusColor("defect"))
                    Action("Начать AR-осмотр", !vm.busy, vm::openAr)
                    Panel("Паспорт оборудования") {
                        Field("Идентификатор", c.id); Field("Модель", c.model); Field("Изготовитель", c.manufacturer)
                        Field("S/N", c.serial_number); Field("Маркировка", c.marking); Field("Расположение", c.location)
                        Field("Ввод в эксплуатацию", c.commissioned_at); Characteristics(c.characteristics)
                    }
                    NormativeBlock(c.normative, c.usage); ResourceBlock(c.resource)
                    Action("Зарегистрировать осмотр оборудования", !vm.busy) { vm.inspection(true) }
                }
                "Состав" -> {
                    val ordered = mutableListOf<Pair<Component, Int>>()
                    fun append(parent: String?, depth: Int) {
                        c.components.filter { it.parent_id == parent }.sortedBy { it.order ?: 0 }.forEach { node ->
                            if (ordered.none { it.first.id == node.id }) { ordered.add(node to depth); append(node.id, depth + 1) }
                        }
                    }
                    append(null, 0)
                    c.components.filter { node -> ordered.none { it.first.id == node.id } }.forEach { ordered.add(it to 0) }
                    ordered.forEach { (node, depth) ->
                        Column(Modifier.padding(start = (depth.coerceAtMost(3) * 12).dp)) {
                            Panel("${symbol(node.attention.level)} ${node.name}") {
                                Text(node.type_name, color = statusColor(node.attention.level)); node.attention.reasons.forEach { Text(it) }
                                Text(node.attention.recommended_action)
                                Action("Открыть ${node.id}", !vm.busy) { vm.openComponent(node.id) }
                            }
                        }
                    }
                }
                "Параметры" -> Parameters(c.parameters)
                "История" -> { Action("Обновить", !vm.busy, vm::refresh); HistoryRows(c.history, c.components) }
            }
        }
    }
}

@Composable fun ComponentScreen(vm: AppState) {
    val c = vm.component ?: return
    Page {
        Text(c.name, style = MaterialTheme.typography.headlineSmall)
        Field("Идентификатор", c.id); Field("Тип", c.type_name); Characteristics(c.characteristics)
        Panel("Даты") { Field("Установка", c.installed_at); Field("Последняя замена", c.last_replaced_at); Field("Последнее обслуживание", c.last_maintenance_at) }
        NormativeBlock(c.normative, c.usage); ResourceBlock(c.resource); VisualBlock(c.visual)
        Panel("Рекомендуемые действия") { c.attention.reasons.forEach { Text(it) }; Text(c.attention.recommended_action) }
        Parameters(vm.card?.parameters.orEmpty().filter { it.id in c.parameters })
        Action("Зарегистрировать осмотр", !vm.busy) { vm.inspection() }
        Text("Предыдущие результаты проверок", style = MaterialTheme.typography.titleLarge)
        HistoryRows(c.previous_results, vm.card?.components.orEmpty())
    }
}

@Composable fun InspectionScreen(vm: AppState) {
    var type by rememberSaveableInput { "checked" }
    var comment by rememberSaveableInput { "" }
    var attach by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(false) }
    Page {
        Text(vm.component?.name ?: vm.card?.name.orEmpty(), style = MaterialTheme.typography.titleLarge)
        Field("Инженер", vm.engineer.ifBlank { "укажите в настройках" })
        inspectionTypes.filterKeys { it != "replacement" || vm.component != null }.forEach { (key, title) ->
            Row(Modifier.fillMaxWidth().clickable { type = key }, verticalAlignment = Alignment.CenterVertically) {
                RadioButton(selected = type == key, onClick = { type = key }); Text(title)
            }
        }
        val required = type in listOf("defect", "remark")
        OutlinedTextField(comment, { comment = it }, label = { Text(if (required) "Комментарий *" else "Комментарий") }, modifier = Modifier.fillMaxWidth(), minLines = 3)
        val available = vm.component?.visual?.category?.let { it != "not_analyzed" } == true
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = attach && available, enabled = available, onCheckedChange = { attach = it })
            Text("Приложить результат визуального анализа")
        }
        Action("Сохранить осмотр", !vm.busy && vm.engineer.isNotBlank() && (!required || comment.isNotBlank())) { vm.submit(type, comment, attach && available) }
    }
}
