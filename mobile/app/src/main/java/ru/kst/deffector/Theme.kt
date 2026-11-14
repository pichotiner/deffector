package ru.kst.deffector

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

val Ink = Color(0xFF152D39)
val Teal = Color(0xFF086D71)
val Mint = Color(0xFFBCEEDB)
val CameraGlass = Color(0xE6192E39)

@Composable
fun DeffectorTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = Teal, onPrimary = Color.White,
            primaryContainer = Color(0xFFDDF2EB), onPrimaryContainer = Ink,
            secondary = Color(0xFF526A75), background = Color(0xFFF2F5F7),
            onBackground = Ink, surface = Color.White, onSurface = Ink,
            surfaceVariant = Color(0xFFE9EFF2), onSurfaceVariant = Color(0xFF536976),
            outline = Color(0xFF71858E), outlineVariant = Color(0xFFDDE5E9),
            error = Color(0xFFB52B40), errorContainer = Color(0xFFFFE9EC)
        ),
        typography = Typography(
            headlineSmall = TextStyle(fontWeight = FontWeight.Bold, fontSize = 26.sp, lineHeight = 32.sp, letterSpacing = (-.5).sp),
            titleLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 22.sp, lineHeight = 28.sp),
            titleMedium = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 23.sp),
            bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 24.sp),
            bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 21.sp),
            bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 18.sp),
            labelLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 20.sp),
            labelMedium = TextStyle(fontWeight = FontWeight.Medium, fontSize = 12.sp, lineHeight = 16.sp)
        ),
        shapes = Shapes(small = RoundedCornerShape(12.dp), medium = RoundedCornerShape(18.dp), large = RoundedCornerShape(24.dp)),
        content = content
    )
}

// Значки рисуются локально: дополнительных библиотек и загрузок нет.
@Composable
fun UiIcon(kind: String, modifier: Modifier = Modifier, tint: Color = LocalContentColor.current) {
    Canvas(modifier.size(22.dp)) {
        val u = size.minDimension / 24f
        fun line(x: Float, y: Float, xx: Float, yy: Float) = drawLine(tint, Offset(x * u, y * u), Offset(xx * u, yy * u), 1.8f * u, StrokeCap.Round)
        when (kind) {
            "back" -> { line(19f, 12f, 5f, 12f); line(5f, 12f, 11f, 6f); line(5f, 12f, 11f, 18f) }
            "settings" -> {
                listOf(6f to 9f, 12f to 16f, 18f to 7f).forEach { (x, y) ->
                    line(x, 3f, x, y - 2f); line(x, y + 2f, x, 21f)
                    drawCircle(tint, 2.2f * u, Offset(x * u, y * u), style = Stroke(1.8f * u))
                }
            }
            "list" -> { listOf(6f, 12f, 18f).forEach { y -> line(9f, y, 21f, y); drawCircle(tint, 1.2f * u, Offset(4f * u, y * u)) } }
            else -> {
                listOf(Triple(3f, 3f, 1f), Triple(21f, 3f, -1f), Triple(3f, 21f, 1f), Triple(21f, 21f, -1f)).forEach { (x, y, dx) ->
                    line(x, y, x + dx * 5f, y); line(x, y, x, y + if (y < 12) 5f else -5f)
                }
                if (kind == "scan") line(7f, 12f, 17f, 12f)
            }
        }
    }
}

@Composable
fun StatusPill(text: String, color: Color, modifier: Modifier = Modifier) {
    Surface(color = color.copy(alpha = .10f), contentColor = color, shape = RoundedCornerShape(10.dp), modifier = modifier) {
        Text(text, Modifier.padding(horizontal = 10.dp, vertical = 6.dp), style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
fun CameraHeading(title: String, subtitle: String, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth().background(Brush.verticalGradient(listOf(Color(0xDB10252F), Color.Transparent))).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(5.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            UiIcon("scan", tint = Mint)
            Text(title, color = Color.White, style = MaterialTheme.typography.titleMedium)
        }
        Text(subtitle, color = Color(0xFFD2E2E8), style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
fun ScanGuide(modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val side = size.width * .68f
        val x = (size.width - side) / 2
        val y = (size.height - side * .62f) / 2
        val h = side * .62f
        val length = 24.dp.toPx()
        val stroke = 3.dp.toPx()
        listOf(Offset(x, y), Offset(x + side, y), Offset(x, y + h), Offset(x + side, y + h)).forEachIndexed { i, p ->
            drawLine(Mint, p, p + Offset(if (i % 2 == 0) length else -length, 0f), stroke, StrokeCap.Round)
            drawLine(Mint, p, p + Offset(0f, if (i < 2) length else -length), stroke, StrokeCap.Round)
        }
    }
}
