package ru.kst.deffector

import android.graphics.Bitmap
import java.io.ByteArrayOutputStream
import kotlin.math.*

data class Box(val left: Float, val top: Float, val right: Float, val bottom: Float)
fun normalizedBox(b: List<Double>): List<Double> {
    require(b.size == 4 && b.all { it.isFinite() } && b[2] > 0 && b[3] > 0) { "Некорректная рамка" }
    val x = b[0].coerceIn(0.0, 1.0); val y = b[1].coerceIn(0.0, 1.0)
    return listOf(x, y, (b[0] + b[2]).coerceIn(x, 1.0), (b[1] + b[3]).coerceIn(y, 1.0))
}
fun previewBox(b: List<Double>, imageW: Int, imageH: Int, viewW: Float, viewH: Float): Box {
    val scale = max(viewW / imageW, viewH / imageH)
    val dx = (viewW - imageW * scale) / 2; val dy = (viewH - imageH * scale) / 2
    val n = normalizedBox(b)
    return Box(dx + n[0].toFloat() * imageW * scale, dy + n[1].toFloat() * imageH * scale,
        dx + n[2].toFloat() * imageW * scale, dy + n[3].toFloat() * imageH * scale)
}
fun cropPixels(b: List<Double>, w: Int, h: Int): IntArray {
    val n = normalizedBox(b)
    val padx = (n[2] - n[0]) * .15; val pady = (n[3] - n[1]) * .15
    val left = floor((n[0] - padx) * w + 1e-7).toInt().coerceIn(0, w - 1)
    val top = floor((n[1] - pady) * h + 1e-7).toInt().coerceIn(0, h - 1)
    val right = ceil((n[2] + padx) * w - 1e-7).toInt().coerceIn(left + 1, w)
    val bottom = ceil((n[3] + pady) * h - 1e-7).toInt().coerceIn(top + 1, h)
    return intArrayOf(left, top, right - left, bottom - top)
}
fun crop(bitmap: Bitmap, b: List<Double>): Bitmap {
    val p = cropPixels(b, bitmap.width, bitmap.height)
    return Bitmap.createBitmap(bitmap, p[0], p[1], p[2], p[3])
}
fun resize(bitmap: Bitmap, width: Int): Bitmap = Bitmap.createScaledBitmap(
    bitmap, width, max(1, (bitmap.height.toDouble() * width / bitmap.width).roundToInt()), true)
fun jpeg(bitmap: Bitmap): ByteArray = ByteArrayOutputStream().use {
    bitmap.compress(Bitmap.CompressFormat.JPEG, 85, it); it.toByteArray()
}
